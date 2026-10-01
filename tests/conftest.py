import os
from urllib.parse import urlparse

import pytest


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
