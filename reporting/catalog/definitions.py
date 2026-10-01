from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from sqlalchemy.sql.elements import ColumnElement


class DataType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    CURRENCY = "currency"
    DATE = "date"
    BOOLEAN = "boolean"


class OrgScope(str, Enum):
    OWNED = "owned"
    SHARED = "shared"
    GLOBAL = "global"


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    expression: ColumnElement[Any]
    data_type: DataType = DataType.STRING
    field_class: str | None = None
    filter_ops: frozenset[str] = field(default_factory=frozenset)
    sortable: bool = False
    aggregatable: bool = False
    allowed_values: frozenset[Any] | None = None


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    expression: ColumnElement[Any]
    field_class: str | None = None
    currency_field: str | None = None


@dataclass(frozen=True)
class DatasetDef:
    key: str
    label: str
    model: Any
    module: str
    permission: str
    org_scope: OrgScope
    fields: Mapping[str, FieldDef]
    metrics: Mapping[str, MetricDef] = field(default_factory=dict)
    from_clause: Any | None = None
    search_fields: tuple[ColumnElement[Any], ...] = ()
    default_sort: str | None = None
    max_rows: int = 10_000
