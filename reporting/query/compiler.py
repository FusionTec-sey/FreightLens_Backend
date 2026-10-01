from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from reporting.catalog import DatasetDef, OrgScope
from reporting.policy import AccessPolicy


@dataclass(frozen=True)
class QueryFilter:
    field: str
    op: str
    value: Any


@dataclass(frozen=True)
class QueryRequest:
    fields: tuple[str, ...]
    filters: tuple[QueryFilter, ...] = ()
    search: str | None = None
    sort_by: str | None = None
    sort_desc: bool = False
    offset: int = 0
    limit: int = 50


@dataclass(frozen=True)
class CompiledQuery:
    statement: Select
    count_statement: Select
    field_keys: tuple[str, ...]
    effective_limit: int


class QueryCompiler:
    def compile(
        self,
        dataset: DatasetDef,
        request: QueryRequest,
        policy: AccessPolicy,
    ) -> CompiledQuery:
        if dataset.module not in policy.module_names or not policy.has(dataset.permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dataset access denied")

        selected_fields = []
        for key in request.fields:
            field = self._field(dataset, key)
            if not policy.allows_field_class(field.field_class):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Field '{key}' is not available to this user",
                )
            selected_fields.append(field)
        if not selected_fields:
            raise HTTPException(status_code=400, detail="At least one report field is required")

        from_clause = dataset.from_clause if dataset.from_clause is not None else dataset.model
        statement = select(*(field.expression.label(field.key) for field in selected_fields)).select_from(from_clause)
        count_statement = select(func.count()).select_from(from_clause)

        criteria = self._scope_criteria(dataset, policy)
        if hasattr(dataset.model, "is_deleted"):
            criteria.append(dataset.model.is_deleted.is_(False))

        for query_filter in request.filters:
            field = self._field(dataset, query_filter.field)
            if not policy.allows_field_class(field.field_class):
                raise HTTPException(status_code=403, detail=f"Filter field '{field.key}' is not available")
            criteria.append(self._filter_expression(field, query_filter))

        if request.search and request.search.strip():
            if not dataset.search_fields:
                raise HTTPException(status_code=400, detail="This dataset does not support search")
            pattern = f"%{request.search.strip()}%"
            criteria.append(or_(*(expression.ilike(pattern) for expression in dataset.search_fields)))

        if criteria:
            statement = statement.where(*criteria)
            count_statement = count_statement.where(*criteria)

        sort_key = request.sort_by or dataset.default_sort
        if sort_key:
            sort_field = self._field(dataset, sort_key)
            if not sort_field.sortable:
                raise HTTPException(status_code=400, detail=f"Field '{sort_key}' is not sortable")
            direction = desc if request.sort_desc else asc
            statement = statement.order_by(direction(sort_field.expression).nullslast())

        effective_limit = min(max(request.limit, 1), dataset.max_rows)
        statement = statement.offset(max(request.offset, 0)).limit(effective_limit)
        return CompiledQuery(
            statement=statement,
            count_statement=count_statement,
            field_keys=tuple(field.key for field in selected_fields),
            effective_limit=effective_limit,
        )

    @staticmethod
    def _field(dataset: DatasetDef, key: str):
        try:
            return dataset.fields[key]
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown report field '{key}'") from exc

    @staticmethod
    def _scope_criteria(dataset: DatasetDef, policy: AccessPolicy) -> list[Any]:
        if dataset.org_scope == OrgScope.GLOBAL:
            return []
        if not hasattr(dataset.model, "org_id"):
            raise RuntimeError(f"Dataset '{dataset.key}' has no org_id for {dataset.org_scope.value} scope")
        owned = dataset.model.org_id.in_(policy.org_ids)
        if dataset.org_scope == OrgScope.OWNED:
            return [owned]
        if not hasattr(dataset.model, "is_shared"):
            raise RuntimeError(f"Dataset '{dataset.key}' has no is_shared marker")
        return [or_(dataset.model.is_shared.is_(True), owned)]

    @staticmethod
    def _filter_expression(field, query_filter: QueryFilter):
        if query_filter.op not in field.filter_ops:
            raise HTTPException(
                status_code=400,
                detail=f"Operator '{query_filter.op}' is not allowed for '{field.key}'",
            )
        value = query_filter.value
        if query_filter.op == "in" and (
            not isinstance(value, (list, tuple, set, frozenset)) or not value
        ):
            raise HTTPException(status_code=400, detail=f"Filter '{field.key}' requires a non-empty list")
        if field.allowed_values is not None:
            values = value if query_filter.op == "in" else [value]
            if any(item not in field.allowed_values for item in values):
                raise HTTPException(status_code=400, detail=f"Invalid value for '{field.key}'")
        expression = field.expression
        operations = {
            "eq": lambda: expression == value,
            "in": lambda: expression.in_(value),
            "contains": lambda: expression.ilike(f"%{value}%"),
            "gte": lambda: expression >= value,
            "lte": lambda: expression <= value,
            "is_null": lambda: expression.is_(None) if value else expression.is_not(None),
        }
        return operations[query_filter.op]()


class QueryExecutor:
    def execute(self, db: Session, compiled: CompiledQuery, *, timeout_ms: int = 5_000):
        bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            db.execute(select(func.set_config("statement_timeout", str(timeout_ms), True)))
        total = db.execute(compiled.count_statement).scalar_one()
        rows = db.execute(compiled.statement).mappings().all()
        return rows, total
