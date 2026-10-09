"""Temporary, root-only import from the legacy containermgmt MySQL database.

Source rows are retained in PostgreSQL except known temporary upgrade copies.
Only the explicitly mapped operational tables are promoted into v2 tables.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import MetaData, Table, and_, insert, select, update, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from Model.db import engine


SOURCE_DATABASE = "containermgmt"
IGNORED_SOURCE_TABLES = frozenset({"container_details02", "bill_of_landing_backup"})
IMPORT_ORDER = (
    "consignee", "container_type", "logisticsprovider", "material",
    "shipping_document", "status", "supplier", "unload_venue", "vessals",
    "bill_of_landing", "container_details", "container_products",
    "container_docs", "packing_list", "report_details", "damageproduct",
    "report_images",
)
PRIMARY_KEYS = {
    "consignee": ("consignee_id",),
    "container_type": ("type_id",),
    "logisticsprovider": ("Id",),
    "material": ("Id",),
    "shipping_document": ("doc_id",),
    "status": ("status_id",),
    "supplier": ("supplier_id",),
    "unload_venue": ("venue_id",),
    "vessals": ("id",),
    "bill_of_landing": ("BillOfLanding",),
    "container_details": ("Container_ID",),
    "container_products": ("ContainerId", "MaterialId"),
    "container_docs": ("docs_id",),
    "packing_list": ("container_id",),
    "report_details": ("report_id",),
    "damageproduct": ("id",),
    "report_images": ("id",),
}
AUDIT_USER_COLUMNS = ("created_by", "updated_by", "deleted_by")
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LegacySyncError(Exception):
    pass


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    raise TypeError(f"Unsupported source value: {type(value).__name__}")


def _canonical(value):
    return json.dumps(value, default=_json_default, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _mysql_connection():
    import pymysql

    host = os.getenv("LEGACY_MYSQL_HOST", "").strip()
    user = os.getenv("LEGACY_MYSQL_USER", "").strip()
    password = os.getenv("LEGACY_MYSQL_PASSWORD", "")
    ca = os.getenv("LEGACY_MYSQL_SSL_CA", "").strip()
    if not all((host, user, password)):
        raise LegacySyncError("Legacy MySQL credentials are not configured on the backend.")
    try:
        connection_options = dict(
            host=host,
            port=int(os.getenv("LEGACY_MYSQL_PORT", "3306")),
            user=user,
            password=password,
            database=SOURCE_DATABASE,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
            read_timeout=60,
            write_timeout=10,
            autocommit=False,
        )
        if ca:
            connection_options.update(ssl_ca=ca, ssl_verify_cert=True, ssl_verify_identity=True)
        return pymysql.connect(**connection_options)
    except Exception as exc:
        raise LegacySyncError("Could not connect to the legacy containermgmt database.") from exc


def _source_snapshot():
    connection = _mysql_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name",
                (SOURCE_DATABASE,),
            )
            table_names = [next(iter(row.values())) for row in cursor.fetchall()]
            snapshot = {}
            for name in table_names:
                if name in IGNORED_SOURCE_TABLES:
                    continue
                if not SAFE_IDENTIFIER.fullmatch(name):
                    raise LegacySyncError("Legacy database contains an unsupported table name.")
                cursor.execute(f"SELECT * FROM `{name}`")
                rows = cursor.fetchall()
                keyed = []
                repeats = defaultdict(int)
                for row in rows:
                    if name in PRIMARY_KEYS:
                        key = _canonical([row[column] for column in PRIMARY_KEYS[name]])
                    else:
                        digest = _hash(row)
                        repeats[digest] += 1
                        key = f"{digest}:{repeats[digest]}"
                    keyed.append((key, row, _hash(row)))
                snapshot[name] = sorted(keyed, key=lambda item: item[0])
            return snapshot
    finally:
        connection.rollback()
        connection.close()


def _organisation_name(name):
    normalized = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    if "noblecon" in normalized:
        return "noblecon", "Noblecon Enterprise"
    if "sahajanand" in normalized:
        return "sahajanand", "Sahajanand"
    if normalized:
        return f"legacy-{normalized[:80]}", (name or "").strip()[:150]
    return "legacy-unknown", "Unknown legacy organisation"


def _org_slug_for_row(table_name, row, source_rows):
    if table_name == "consignee":
        return _organisation_name(row.get("consignee_name"))[0]
    if table_name == "bill_of_landing":
        consignee = source_rows.get("consignee", {}).get(row.get("Consignee"))
        return _organisation_name((consignee or {}).get("consignee_name"))[0]
    if table_name == "container_details":
        bol = source_rows.get("bill_of_landing", {}).get(row.get("BillOfLanding"))
        if bol:
            slug = _org_slug_for_row("bill_of_landing", bol, source_rows)
            if slug != "legacy-unknown":
                return slug
    return "legacy-unknown"


def _source_lookup(snapshot):
    keys = {"consignee": "consignee_id", "bill_of_landing": "BillOfLanding"}
    lookup = {name: {row[keys[name]]: row for _, row, _ in items}
              for name, items in snapshot.items() if name in keys}
    supplier_owners = defaultdict(set)
    for bol in lookup.get("bill_of_landing", {}).values():
        if bol.get("Supplier") is not None:
            supplier_owners[bol["Supplier"]].add(_org_slug_for_row("bill_of_landing", bol, lookup))
    lookup["_supplier_owners"] = supplier_owners
    return lookup


def _org_ids(conn, snapshot, create):
    organisations = conn.execute(text(
        "SELECT id, name, display_name, base_currency FROM usercredentials.organisations"
    )).mappings().all()
    existing = {org["name"].lower(): org["id"] for org in organisations}
    for org in organisations:
        slug, _ = _organisation_name(org["display_name"] or org["name"])
        existing.setdefault(slug, org["id"])
    root_id = existing.get("sahaj")
    if root_id is None:
        raise LegacySyncError("The target has no Sahaj root organisation.")
    root_currency = next(org["base_currency"] for org in organisations if org["id"] == root_id)
    names = {"legacy-unknown": "Unknown legacy organisation"}
    for _, row, _ in snapshot.get("consignee", []):
        slug, display = _organisation_name(row.get("consignee_name"))
        names[slug] = display
    missing = [slug for slug in names if slug not in existing]
    if create:
        for slug in missing:
            org_id = conn.execute(text("""
                INSERT INTO usercredentials.organisations
                    (name, display_name, parent_org_id, is_active, modules, plan, base_currency)
                VALUES (:name, :display_name, :parent_id, true,
                    ARRAY['LOGISTICS','ORDERS','INVENTORY'], 'complete', :base_currency)
                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
            """), {"name": slug, "display_name": names[slug], "parent_id": root_id,
                   "base_currency": root_currency}).scalar_one()
            existing[slug] = org_id
    return existing, root_id, missing


def _payload(table_name, row, table, source_rows, org_ids, root_id):
    result = {column: value for column, value in row.items() if column in table.c}
    for column in AUDIT_USER_COLUMNS:
        if column in result:
            result[column] = None  # The credentials database is explicitly excluded.
    if "org_id" in table.c:
        slug = _org_slug_for_row(table_name, row, source_rows)
        if table_name == "supplier":
            owners = source_rows["_supplier_owners"].get(row.get("supplier_id"), set())
            if not owners or "legacy-unknown" in owners:
                slug = "legacy-unknown"
            elif len(owners) == 1:
                slug = next(iter(owners))
            else:
                slug = None
            result["is_shared"] = slug is None
        result["org_id"] = root_id if slug is None else org_ids.get(slug)
        if result["org_id"] is None:
            return None
    if table_name == "supplier":
        result["is_active"] = not bool(row.get("is_deleted"))
    return result


def _target_row(conn, table, source_row, table_name):
    condition = and_(*(table.c[column] == source_row[column] for column in PRIMARY_KEYS[table_name]))
    return conn.execute(select(table).where(condition)).mappings().first(), condition


def _status(conn, tracked, table, table_name, row, source_hash, payload):
    target, condition = _target_row(conn, table, row, table_name)
    if target is None:
        return ("new" if tracked is None or tracked["status"] == "blocked" else "conflict"), condition
    if tracked is None:
        return "conflict", condition
    target_hash = _hash({name: target[name] for name in payload})
    if target_hash != tracked["target_hash"]:
        return "conflict", condition
    return ("unchanged" if source_hash == tracked["source_hash"] else "changed"), condition


def _plan(conn, snapshot):
    metadata = MetaData()
    tables = {
        name: Table(name, metadata, schema="containermgmt", autoload_with=conn)
        for name in IMPORT_ORDER if name in snapshot
    }
    records = Table("legacy_sync_rows", metadata, schema="containermgmt", autoload_with=conn)
    org_ids, root_id, missing_orgs = _org_ids(conn, snapshot, create=False)
    source_rows = _source_lookup(snapshot)
    counts = {}
    fingerprint_parts = []
    for table_name in sorted(snapshot):
        counter = Counter()
        for key, row, source_hash in snapshot[table_name]:
            fingerprint_parts.append((table_name, key, source_hash))
            tracked = conn.execute(select(records).where(
                records.c.source_table == table_name,
                records.c.source_key == key,
            )).mappings().first()
            if table_name not in tables:
                counter["archived"] += 1
                continue
            table = tables[table_name]
            payload = _payload(table_name, row, table, source_rows, org_ids, root_id)
            if payload is None:
                # The new organisation will be created by apply.
                payload = _payload(table_name, row, table, source_rows,
                                   {**org_ids, **{slug: -1 for slug in missing_orgs}}, root_id)
            status, _ = _status(conn, tracked, table, table_name, row, source_hash, payload)
            counter[status] += 1
        counts[table_name] = dict(counter)
    return {
        "source_database": SOURCE_DATABASE,
        "fingerprint": _hash(fingerprint_parts),
        "tables": counts,
        "organisations_to_create": sorted(missing_orgs),
        "source_rows": sum(len(rows) for rows in snapshot.values()),
    }


def preview_legacy_sync():
    snapshot = _source_snapshot()
    with engine.connect() as conn:
        return _plan(conn, snapshot)


def apply_legacy_sync(expected_fingerprint):
    snapshot = _source_snapshot()
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('legacy-containermgmt-sync'))"))
        plan = _plan(conn, snapshot)
        if plan["fingerprint"] != expected_fingerprint:
            raise LegacySyncError("The legacy source changed. Run Check legacy data again.")
        org_ids, root_id, _ = _org_ids(conn, snapshot, create=True)
        source_rows = _source_lookup(snapshot)
        metadata = MetaData()
        records = Table("legacy_sync_rows", metadata, schema="containermgmt", autoload_with=conn)
        tables = {
            name: Table(name, metadata, schema="containermgmt", autoload_with=conn)
            for name in IMPORT_ORDER if name in snapshot
        }
        run_id = conn.execute(text("""
            INSERT INTO containermgmt.legacy_sync_runs
                (source_database, source_fingerprint, status)
            VALUES ('containermgmt', :fingerprint, 'RUNNING') RETURNING id
        """), {"fingerprint": plan["fingerprint"]}).scalar_one()
        summary = Counter()
        for table_name in list(IMPORT_ORDER) + sorted(set(snapshot) - set(IMPORT_ORDER)):
            for key, row, source_hash in snapshot.get(table_name, []):
                tracked = conn.execute(select(records).where(
                    records.c.source_table == table_name,
                    records.c.source_key == key,
                )).mappings().first()
                status = "archived"
                target_hash = tracked["target_hash"] if tracked else None
                if table_name in tables:
                    table = tables[table_name]
                    payload = _payload(table_name, row, table, source_rows, org_ids, root_id)
                    status, condition = _status(conn, tracked, table, table_name, row, source_hash, payload)
                    if status in ("new", "changed"):
                        try:
                            with conn.begin_nested():
                                if status == "new":
                                    conn.execute(insert(table).values(**payload))
                                else:
                                    conn.execute(update(table).where(condition).values(**payload))
                            target, _ = _target_row(conn, table, row, table_name)
                            target_hash = _hash({name: target[name] for name in payload})
                            status = "imported" if status == "new" else "updated"
                        except Exception:
                            status = "blocked"
                summary[status] += 1
                stored_row = json.loads(_canonical(row))
                statement = pg_insert(records).values(
                    source_table=table_name, source_key=key, source_hash=source_hash,
                    source_row=stored_row,
                    target_table=table_name if table_name in tables else None,
                    target_key=key if table_name in tables and status not in ("blocked", "conflict") else None,
                    target_hash=target_hash,
                    status=status, last_run_id=run_id,
                )
                conn.execute(statement.on_conflict_do_update(
                    index_elements=[records.c.source_table, records.c.source_key],
                    set_={
                        "source_hash": statement.excluded.source_hash,
                        "source_row": statement.excluded.source_row,
                        "target_table": statement.excluded.target_table,
                        "target_key": statement.excluded.target_key,
                        "target_hash": statement.excluded.target_hash,
                        "status": statement.excluded.status,
                        "last_run_id": statement.excluded.last_run_id,
                        "updated_at": text("now()"),
                    },
                ))
            if table_name in tables and len(PRIMARY_KEYS[table_name]) == 1:
                pk = PRIMARY_KEYS[table_name][0]
                sequence = conn.execute(text("SELECT pg_get_serial_sequence(:table, :column)"), {
                    "table": f"containermgmt.{table_name}", "column": pk,
                }).scalar()
                if sequence:
                    conn.execute(text("SELECT setval(CAST(:sequence AS regclass), "
                                      "GREATEST((SELECT COALESCE(MAX(\"" + pk + "\"), 1) "
                                      "FROM containermgmt.\"" + table_name + "\"), 1), true)"),
                                 {"sequence": sequence})
        result = dict(summary)
        conn.execute(text("""
            UPDATE containermgmt.legacy_sync_runs
            SET status = 'COMPLETE', finished_at = now(), summary = CAST(:summary AS jsonb)
            WHERE id = :run_id
        """), {"summary": _canonical(result), "run_id": run_id})
        return {"run_id": run_id, "summary": result, "organisations_created": plan["organisations_to_create"]}
