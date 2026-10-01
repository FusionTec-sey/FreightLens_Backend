import jwt

from Utils.org_filter import apply_org_filter
from auth.config import settings


def test_transactional_database_fixture_enforces_tenant_filter(
    db_session,
    organisation_contexts,
    tenant_record_model,
):
    first, second = organisation_contexts
    db_session.add_all(
        [
            tenant_record_model(org_id=first.org_id, label="visible to org A"),
            tenant_record_model(org_id=second.org_id, label="visible to org B"),
        ]
    )
    db_session.flush()

    records = apply_org_filter(
        db_session.query(tenant_record_model),
        tenant_record_model,
        first,
    ).all()

    assert [record.label for record in records] == ["visible to org A"]


def test_role_user_tokens_preserve_tenant_claims(role_users, access_tokens):
    for user in role_users:
        claims = jwt.decode(
            access_tokens[user.username],
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        assert claims["sub"] == user.username
        assert claims["org_id"] == user.org_id
        assert claims["roles"] == user.roles
