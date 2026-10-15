"""Give a vendor the people and the places it actually has.

The supplier row carries one `contact_person`, one `email`, one `phone` and one
free-text `address`. A vendor of any size has a salesperson, someone in
accounts, and someone who answers when a shipment is late; and it has a
registered office that is not the factory, which is not where the goods ship
from, which is not where the payment advice goes. Collapsed into one line each,
the second of anything displaces the first, which is why those fields fill up
with "Ms Chen / Mr Wang (accounts)" and addresses that are three addresses.

Rows, like the identifiers before them:

* a contact knows what it is for -- sales, accounts, logistics, escalation --
  so a buyer can address the right person without asking;
* an address knows what kind it is, because a registered address on a customs
  declaration and a factory address on a packing list are different mistakes;
* one of each may be marked primary, and the primary is what the existing
  single fields on the supplier continue to show. Nothing that reads the old
  columns breaks.

The old columns are deliberately left in place and still written. Moving every
screen that reads `supplier.contact_person` is a larger change than this
migration, and a half-moved field is worse than an un-moved one.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_supplier_contacts_addresses")

_CONTACTS = """
    CREATE TABLE IF NOT EXISTS containermgmt.supplier_contacts (
        id SERIAL PRIMARY KEY,
        supplier_id INTEGER NOT NULL
            REFERENCES containermgmt.supplier(supplier_id) ON DELETE CASCADE,
        name VARCHAR(150) NOT NULL,
        role VARCHAR(30),
        job_title VARCHAR(100),
        email VARCHAR(150),
        phone VARCHAR(50),
        mobile VARCHAR(50),
        is_primary BOOLEAN NOT NULL DEFAULT FALSE,
        notes TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by INTEGER REFERENCES usercredentials.users(id),
        updated_by INTEGER REFERENCES usercredentials.users(id),
        is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        deleted_by INTEGER REFERENCES usercredentials.users(id)
    )
"""

_ADDRESSES = """
    CREATE TABLE IF NOT EXISTS containermgmt.supplier_addresses (
        id SERIAL PRIMARY KEY,
        supplier_id INTEGER NOT NULL
            REFERENCES containermgmt.supplier(supplier_id) ON DELETE CASCADE,
        address_type VARCHAR(30) NOT NULL DEFAULT 'OTHER',
        label VARCHAR(100),
        line1 VARCHAR(200),
        line2 VARCHAR(200),
        city VARCHAR(100),
        state VARCHAR(100),
        postal_code VARCHAR(30),
        country VARCHAR(100),
        is_primary BOOLEAN NOT NULL DEFAULT FALSE,
        notes TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_by INTEGER REFERENCES usercredentials.users(id),
        updated_by INTEGER REFERENCES usercredentials.users(id),
        is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        deleted_by INTEGER REFERENCES usercredentials.users(id)
    )
"""

# The vendor's existing single contact and single address become the primary
# row of each, so the first thing anyone sees is what they saw yesterday. Only
# vendors that have nothing in the new tables are seeded, so the backfill is
# safe to run again.
_SEED_CONTACT = """
    INSERT INTO containermgmt.supplier_contacts
        (supplier_id, name, role, email, phone, is_primary, created_at, updated_at)
    SELECT s.supplier_id,
           trim(s.contact_person),
           'SALES',
           nullif(trim(coalesce(s.email, '')), ''),
           nullif(trim(coalesce(s.phone, '')), ''),
           TRUE, now(), now()
    FROM containermgmt.supplier s
    WHERE s.is_deleted IS NOT TRUE
      AND coalesce(trim(s.contact_person), '') <> ''
      AND NOT EXISTS (
          SELECT 1 FROM containermgmt.supplier_contacts c
          WHERE c.supplier_id = s.supplier_id AND c.is_deleted IS NOT TRUE
      )
"""

# The old column is one free-text blob with no structure to recover, so it goes
# into line1 under its own type rather than being guessed apart into a city and
# a postcode that may be wrong.
_SEED_ADDRESS = """
    INSERT INTO containermgmt.supplier_addresses
        (supplier_id, address_type, line1, country, is_primary, notes, created_at, updated_at)
    SELECT s.supplier_id, 'REGISTERED', trim(s.address), s.country, TRUE,
           'Imported from the vendor''s single address field.', now(), now()
    FROM containermgmt.supplier s
    WHERE s.is_deleted IS NOT TRUE
      AND coalesce(trim(s.address), '') <> ''
      AND NOT EXISTS (
          SELECT 1 FROM containermgmt.supplier_addresses a
          WHERE a.supplier_id = s.supplier_id AND a.is_deleted IS NOT TRUE
      )
"""


def ensure_supplier_contacts_and_addresses():
    with engine.begin() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'containermgmt' AND table_name = 'supplier'
        """)).first()
        if not exists:
            logger.info("supplier table is not there yet; nothing to do.")
            return

        conn.execute(text(_CONTACTS))
        conn.execute(text(_ADDRESSES))

        for table in ("supplier_contacts", "supplier_addresses"):
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS ix_{table}_supplier
                ON containermgmt.{table} (supplier_id)
                WHERE is_deleted IS NOT TRUE
            """))
            # One primary per vendor, enforced rather than hoped for: two
            # primary addresses is the state in which nobody knows which one
            # the purchase order printed.
            conn.execute(text(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_one_primary
                ON containermgmt.{table} (supplier_id)
                WHERE is_primary IS TRUE AND is_deleted IS NOT TRUE
            """))

        seeded_contacts = conn.execute(text(_SEED_CONTACT)).rowcount
        seeded_addresses = conn.execute(text(_SEED_ADDRESS)).rowcount
        if seeded_contacts or seeded_addresses:
            logger.info(
                "Seeded %s vendor contact(s) and %s address(es) from the single old fields.",
                seeded_contacts, seeded_addresses,
            )
        logger.info("Supplier contacts and addresses are ready.")
