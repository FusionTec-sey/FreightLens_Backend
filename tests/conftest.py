import os
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from sqlalchemy import Column, Integer, String, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base


TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://test:test@localhost/containermgmt_test",
)

# These values must exist before application modules are imported during collection.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["DISABLE_SCHEDULER"] = "1"
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-not-for-production")
os.environ.setdefault("MEDIA_SIGNING_KEY", "test-media-signing-key-not-for-production")
os.environ.setdefault("CMA_CGM_WEBHOOK_SECRET", "test-webhook-secret-not-for-production")


TestBase = declarative_base()


class TenantRecord(TestBase):
    __tablename__ = "tenant_records"
    __table_args__ = {"schema": "testsupport"}

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, nullable=False, index=True)
    label = Column(String(100), nullable=False)


@pytest.fixture(scope="session")
def test_database_url():
    """Return a URL that is provably isolated from application databases."""
    database_name = urlparse(TEST_DATABASE_URL.replace("postgresql+psycopg2", "postgresql")).path.lstrip("/")
    if not database_name.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must reference a database whose name ends with '_test'")
    return TEST_DATABASE_URL


@pytest.fixture
def organisation_contexts():
    """Stable two-tenant contexts for authorization and isolation tests."""
    from Utils.org_filter import OrgContext

    return (
        OrgContext(current_org_id=1001, allowed_org_ids=[1001], is_root=False),
        OrgContext(current_org_id=2002, allowed_org_ids=[2002], is_root=False),
    )


@pytest.fixture
def role_users(organisation_contexts):
    first, second = organisation_contexts
    return (
        SimpleNamespace(id=1, username="org-a-user", roles=["employee"], org_id=first.org_id),
        SimpleNamespace(id=2, username="org-b-finance", roles=["finance"], org_id=second.org_id),
    )


@pytest.fixture
def access_tokens(role_users):
    from auth.tokens import create_access_token

    return {
        user.username: create_access_token(
            {"sub": user.username, "org_id": user.org_id, "roles": user.roles},
            expires_delta=timedelta(minutes=5),
        )
        for user in role_users
    }


@pytest.fixture(scope="session")
def test_engine(test_database_url):
    engine = create_engine(test_database_url, pool_pre_ping=True, connect_args={"connect_timeout": 2})
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS testsupport"))
            TestBase.metadata.create_all(connection)
            from Utils.migrate_20261002_stock_ledger import prepare_product_stock_scope
            prepare_product_stock_scope(connection)
            from Utils.migrate_20261002_stock_unit_policy import prepare_stock_unit_policy
            prepare_stock_unit_policy(connection)
            from Utils.migrate_20261002_stock_batches import prepare_stock_batches
            prepare_stock_batches(connection)
            from Utils.migrate_20261002_stock_serials import prepare_stock_serials
            prepare_stock_serials(connection)
            from Utils.migrate_20261003_valuation_charges import prepare_valuation_charges
            prepare_valuation_charges(connection)
            from Utils.migrate_20261005_stock_movements import prepare_inventory_handover_schema
            prepare_inventory_handover_schema(connection)
            from Utils.migrate_20261005_stock_serial_handovers import prepare_stock_serial_handover_schema
            prepare_stock_serial_handover_schema(connection)
    except OperationalError as exc:
        engine.dispose()
        if os.getenv("REQUIRE_TEST_DATABASE") == "1":
            pytest.fail("Required isolated PostgreSQL test database is unavailable")
        pytest.skip(f"isolated PostgreSQL test database is unavailable: {exc.orig}")

    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def tenant_record_model():
    return TenantRecord
