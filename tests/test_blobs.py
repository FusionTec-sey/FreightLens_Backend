import importlib.util
from io import BytesIO
from pathlib import Path
import sys
import types

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
if "Utils" not in sys.modules:
    utils_package = types.ModuleType("Utils")
    utils_package.__path__ = [str(ROOT / "Utils")]
    sys.modules["Utils"] = utils_package

auth_package = types.ModuleType("auth")
auth_package.__path__ = [str(ROOT / "auth")]
auth_dependencies = types.ModuleType("auth.dependencies")


def get_current_user():
    raise HTTPException(status_code=401, detail="Not authenticated")


auth_dependencies.get_current_user = get_current_user
sys.modules["auth"] = auth_package
sys.modules["auth.dependencies"] = auth_dependencies

MODULE_SPEC = importlib.util.spec_from_file_location(
    "blob_router_under_test",
    ROOT / "Routes" / "BlobRouter.py",
)
blob_router_module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(blob_router_module)
BlobRouter = blob_router_module.BlobRouter
_open_clients = []


@pytest.fixture(autouse=True)
def close_test_clients(monkeypatch):
    monkeypatch.setenv("MEDIA_SIGNING_KEY", "test-media-signing-key")
    yield
    while _open_clients:
        _open_clients.pop().__exit__(None, None, None)


def _client(authenticated=False):
    app = FastAPI()
    app.include_router(BlobRouter)

    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: object()
    else:
        def deny_user():
            raise HTTPException(status_code=401, detail="Not authenticated")

        app.dependency_overrides[get_current_user] = deny_user
    client = TestClient(app)
    client.__enter__()
    _open_clients.append(client)
    return client


def test_upload_requires_authentication():
    response = _client().post(
        "/blobs/upload?folder=products/images",
        files={"file": ("photo.jpg", b"image", "image/jpeg")},
    )
    assert response.status_code == 401


def test_upload_rejects_unapproved_folder():
    response = _client(authenticated=True).post(
        "/blobs/upload?folder=orders/x",
        files={"file": ("photo.jpg", b"image", "image/jpeg")},
    )
    assert response.status_code == 400


def test_upload_rejects_executable_disguised_as_image():
    response = _client(authenticated=True).post(
        "/blobs/upload?folder=products/images",
        files={"file": ("payload.exe", b"not-an-image", "image/jpeg")},
    )
    assert response.status_code == 400


def test_upload_accepts_valid_product_image(monkeypatch):
    monkeypatch.setattr(
        blob_router_module.blob_storage,
        "upload_file",
        lambda **kwargs: "products/images/generated.jpg",
    )
    response = _client(authenticated=True).post(
        "/blobs/upload?folder=products/images",
        files={"file": ("photo.jpg", b"image", "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["object_key"] == "products/images/generated.jpg"


def test_upload_enforces_folder_size_limit(monkeypatch):
    monkeypatch.setitem(blob_router_module.UPLOAD_RULES["products/images"], "max_bytes", 4)
    response = _client(authenticated=True).post(
        "/blobs/upload?folder=products/images",
        files={"file": ("photo.jpg", b"12345", "image/jpeg")},
    )
    assert response.status_code == 413


def test_health_requires_authentication(monkeypatch):
    monkeypatch.setattr(blob_router_module.blob_storage, "ensure_bucket_exists", lambda: True)
    assert _client().get("/blobs/health/status").status_code == 401

    response = _client(authenticated=True).get("/blobs/health/status")
    assert response.status_code == 200
    assert "endpoint" not in response.json()


def test_non_media_blob_paths_are_not_public():
    client = _client()
    for path in (".env", "containerMgmt.py", "orders/private.pdf"):
        response = client.get(f"/blobs/{path}")
        assert response.status_code == 404


def test_media_requires_a_valid_signature(monkeypatch):
    monkeypatch.setattr(blob_router_module.blob_storage, "verify_signed_url", lambda *args: False)
    response = _client().get("/blobs/products/images/photo.jpg?exp=1&sig=bad")
    assert response.status_code == 404


def test_traversal_blob_paths_are_not_public():
    response = _client().get("/blobs/products/images/%2E%2E/%2E%2E/app.log")
    assert response.status_code == 404


def test_public_product_media_supports_full_and_range_responses(monkeypatch):
    def fake_get_file_range(key, byte_range=None):
        if byte_range:
            return BytesIO(b"bc"), "image/jpeg", "photo.jpg", 2, "bytes 1-2/4"
        return BytesIO(b"abcd"), "image/jpeg", "photo.jpg", 4, None

    monkeypatch.setattr(blob_router_module.blob_storage, "get_file_range", fake_get_file_range)
    monkeypatch.setattr(blob_router_module.blob_storage, "verify_signed_url", lambda *args: True)
    client = _client()

    response = client.get("/blobs/products/images/photo.jpg?exp=9999999999&sig=valid")
    assert response.status_code == 200
    assert response.content == b"abcd"

    range_response = client.get(
        "/blobs/products/images/photo.jpg?exp=9999999999&sig=valid",
        headers={"Range": "bytes=1-2"},
    )
    assert range_response.status_code == 206
    assert range_response.content == b"bc"
    assert range_response.headers["content-range"] == "bytes 1-2/4"


def test_generic_blob_delete_route_is_removed():
    response = _client(authenticated=True).delete("/blobs/products/images/photo.jpg")
    assert response.status_code == 405
