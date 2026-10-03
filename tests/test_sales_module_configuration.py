from types import SimpleNamespace
from fastapi import Depends
from tests.test_inventory_locations import locations  # noqa: F401


def test_sales_entitlement_requires_explicit_platform_admin_configuration(locations):
    from Routes.Organisation.Organisation import AdminRouter
    from auth.security_guards import require_root_admin
    f = locations; f.app.include_router(AdminRouter, dependencies=[Depends(require_root_admin)])
    url = f'/admin/organisations/{f.org_a}/modules'
    body = {'modules': ['INVENTORY', 'SALES']}
    assert f.client.patch(url, json=body).status_code == 403
    f.context.is_root = True
    assert f.client.patch(url, json=body).status_code == 403
    f.user.roles = [SimpleNamespace(is_platform_admin=True)]
    response = f.client.patch(url, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['modules'] == ['INVENTORY', 'SALES']
    assert f.client.patch(url, json={'modules': ['UNKNOWN']}).status_code == 400
    for dep in f.user_dependencies: f.app.dependency_overrides.pop(dep)
    assert f.client.patch(url, json=body).status_code == 401
