# Temporary legacy MySQL sync

The source is **only** the MySQL `containermgmt` database. The old credentials
database is never connected or imported. The destination is the PostgreSQL database
already configured by `DATABASE_URL` in the running backend container.

The root-admin Tenant Console exposes **Check legacy data** and **Apply previewed
sync**. The first call is read-only in both databases. The second call requires the
source fingerprint from that preview and serializes imports with a PostgreSQL
advisory transaction lock. There is no background polling or automatic deletion.

## Backend configuration

Set these in the backend's local environment file, then recreate the backend Docker
service so Compose passes them into the container:

```text
LEGACY_MYSQL_HOST=your-source-host
LEGACY_MYSQL_PORT=3309
LEGACY_MYSQL_USER=your-read-only-source-user
LEGACY_MYSQL_PASSWORD=your-source-password
# Optional, only when the source server requires a trusted CA:
LEGACY_MYSQL_SSL_CA=
```

If configured, the CA path must exist **inside** the backend container. The backend
repository is bind-mounted at `/app` in the local Compose stack, so a certificate
placed at `Backend/certs/legacy-mysql-ca.pem` is available as
`/app/certs/legacy-mysql-ca.pem`. Keep the password only in the backend environment
file. The browser receives counts and status, never connection settings or source
rows. Use a MySQL user with `SELECT` on `containermgmt` and no privileges on the
credentials database. With the current source settings and a blank CA path, the
connection was verified to be unencrypted. Configure TLS or a protected tunnel if
the source server supports one.

## Import behavior

- Source rows are retained as JSONB with their source table, key and hash in
  `containermgmt.legacy_sync_rows`. The temporary upgrade copies
  `container_details02` and `bill_of_landing_backup` are excluded entirely from
  preview and apply.
- Supported operational tables are imported in foreign-key order. The source and
  target primary keys match where possible. Existing target rows with the same key
  but no recorded source link are conflicts and are not overwritten.
- A repeated sync skips unchanged rows. A source change updates a linked target only
  when the target still matches the previous import. Local edits become conflicts.
  Rows rejected by target constraints remain archived with `blocked` status.
- Old user IDs in audit columns are not mapped because the credentials database is
  excluded. They remain in the archived source row; target audit user FKs are null.
- Consignee names create or match organisations. Bill of landing ownership follows
  its consignee; container ownership follows its bill of landing. Unresolved
  records use `legacy-unknown`.
- Suppliers used by one known consignee organisation become tenant suppliers.
  Suppliers used by multiple known organisations become shared. Suppliers with no
  usage or uncertain ownership go to `legacy-unknown`.
- Operational tables without organisation columns remain global reference data.
  Other unsupported tables are archived, not inserted into live operational tables.

The `legacy-unknown` organisation is deliberately retained while it owns records.
Review and remap those records before removing it. A future sync will flag locally
remapped rows as conflicts instead of reverting them to unknown ownership.

The current source has no product, purchase-order, stock-movement or payment tables.
This sync does not invent those records or post stock or money. Document path strings
are archived/imported as metadata; this process does not copy referenced files.

## Verification

Run `pytest tests/test_legacy_sync_service.py -q`, then build the frontend. After
backend configuration, check `/admin/legacy-sync/preview` as a root admin. Review
table counts and conflicts before applying. Check the run summary and rerun the
preview to identify remaining blocked/conflicting records. Reconcile imported table
counts and organisation assignments before relying on them in production.
