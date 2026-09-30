import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "Utils" / "blob_storage.py"
MODULE_SPEC = importlib.util.spec_from_file_location("blob_storage_under_test", MODULE_PATH)
storage_module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(storage_module)


@pytest.mark.parametrize(
    "key",
    ["", "/etc/passwd", "C:/Windows/system.ini", "../app.log", "products/../app.log", "a//b", "a/./b", "bad\x00key"],
)
def test_safe_key_rejects_unsafe_paths(key):
    with pytest.raises(ValueError):
        storage_module._safe_key(key)


def test_safe_key_normalizes_legacy_blob_prefix():
    assert storage_module._safe_key(r"BLOB\products\images\photo.jpg") == "products/images/photo.jpg"


def test_delete_rejects_an_empty_key():
    with pytest.raises(ValueError):
        storage_module.RustFSClient().delete_file("")


def test_local_fallback_never_reads_raw_process_paths(monkeypatch):
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        fallback_root = temp_path / "BLOB"
        fallback_root.mkdir()
        outside_file = temp_path / "app.log"
        outside_file.write_bytes(b"sensitive")

        monkeypatch.setattr(storage_module, "BLOB_ROOT", str(fallback_root.resolve()))
        client = storage_module.RustFSClient()

        class MissingObjectStore:
            def get_object(self, **kwargs):
                raise RuntimeError("offline")

        client._s3_client = MissingObjectStore()

        with pytest.raises(ValueError):
            client.get_file(str(outside_file))


def test_local_fallback_reads_only_from_blob_root(monkeypatch):
    with TemporaryDirectory() as temp_dir:
        fallback_root = Path(temp_dir) / "BLOB"
        media_file = fallback_root / "products" / "images" / "photo.jpg"
        media_file.parent.mkdir(parents=True)
        media_file.write_bytes(b"image-data")

        monkeypatch.setattr(storage_module, "BLOB_ROOT", str(fallback_root.resolve()))
        client = storage_module.RustFSClient()

        class MissingObjectStore:
            def get_object(self, **kwargs):
                raise RuntimeError("offline")

        client._s3_client = MissingObjectStore()
        body, content_type, filename = client.get_file("products/images/photo.jpg")
        try:
            assert body.read() == b"image-data"
            assert content_type == "image/jpeg"
            assert filename == "photo.jpg"
        finally:
            body.close()
