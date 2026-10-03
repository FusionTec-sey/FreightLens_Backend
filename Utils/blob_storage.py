import os
import re
import uuid
import hashlib
import hmac
import logging
import mimetypes
import time
from datetime import datetime
from typing import Optional, Tuple, BinaryIO, Union
from io import BytesIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi import UploadFile

logger = logging.getLogger("containerMgmt.blob_storage")

BLOB_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "BLOB"))


def _safe_key(key: str) -> str:
    """Return a normalized object key or reject unsafe filesystem-like paths."""
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Blob key must not be empty")
    if "\x00" in key:
        raise ValueError("Blob key contains a null byte")

    normalized = key.strip().replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("Absolute blob paths are not allowed")

    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Blob key contains an unsafe path segment")
    if parts[0].lower() == "blob":
        parts = parts[1:]
    if not parts:
        raise ValueError("Blob key must identify a file or folder")
    return "/".join(parts)


def _local_fallback_path(key: str) -> str:
    """Resolve a validated object key beneath the local BLOB fallback root."""
    clean_key = _safe_key(key)
    candidate = os.path.realpath(os.path.join(BLOB_ROOT, *clean_key.split("/")))
    if os.path.commonpath([BLOB_ROOT, candidate]) != BLOB_ROOT:
        raise ValueError("Blob key escapes the fallback storage root")
    return candidate


class RustFSClient:
    """
    S3-compatible blob and object storage client for RustFS.
    Manages uploading, downloading, streaming, and deletion of file blobs.
    """

    def __init__(self):
        self.endpoint_url = os.getenv("RUSTFS_ENDPOINT_URL", "http://rustfs:9000")
        self.access_key = os.getenv("RUSTFS_ACCESS_KEY")
        self.secret_key = os.getenv("RUSTFS_SECRET_KEY")
        self.bucket_name = os.getenv("RUSTFS_BUCKET_NAME", "containermgmt-blobs")
        self.region = os.getenv("RUSTFS_REGION", "us-east-1")
        self._s3_client = None

    @property
    def client(self):
        if self._s3_client is None:
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    retries={"max_attempts": 3, "mode": "standard"}
                )
            )
        return self._s3_client

    def ensure_bucket_exists(self) -> bool:
        """
        Ensures the target object storage bucket exists in RustFS.
        Creates it if it does not already exist.
        """
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
            logger.info("RustFS bucket '%s' is ready.", self.bucket_name)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchBucket"):
                try:
                    self.client.create_bucket(Bucket=self.bucket_name)
                    logger.info("Created RustFS bucket '%s'.", self.bucket_name)
                    return True
                except Exception as create_err:
                    logger.error("Failed to create RustFS bucket '%s': %s", self.bucket_name, create_err)
                    return False
            else:
                # Attempt creation anyway
                try:
                    self.client.create_bucket(Bucket=self.bucket_name)
                    logger.info("Created RustFS bucket '%s'.", self.bucket_name)
                    return True
                except Exception:
                    logger.warning("RustFS head_bucket check warning: %s", e)
                    return False
        except Exception as ex:
            logger.error("Could not connect to RustFS endpoint %s: %s", self.endpoint_url, ex)
            return False

    def upload_file(
        self,
        file_obj: Optional[Union[UploadFile, bytes, BinaryIO]] = None,
        folder: str = "general",
        original_filename: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Uploads a file or bytes to RustFS under the specified folder prefix.
        Returns the unique object key (e.g., 'Shipping/20260831120000_abc123.pdf').
        """
        clean_folder = _safe_key(folder)
        if file_obj is None and "file_bytes" in kwargs:
            file_obj = kwargs["file_bytes"]
        fname = original_filename or kwargs.get("file_name")
        if hasattr(file_obj, "file") and hasattr(file_obj.file, "read"):
            fname = fname or getattr(file_obj, "filename", None) or "upload"
            try:
                file_obj.file.seek(0)
            except Exception:
                pass
            content = file_obj.file.read()
        elif isinstance(file_obj, (bytes, bytearray)):
            fname = fname or "upload.bin"
            content = bytes(file_obj)
        elif hasattr(file_obj, "read"):
            fname = fname or getattr(file_obj, "name", None) or getattr(file_obj, "filename", None) or "upload.bin"
            content = file_obj.read()
            if hasattr(content, "__await__"):
                import asyncio
                content = asyncio.run(content)
        else:
            content = b""

        file_ext = os.path.splitext(fname)[1]
        unique_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:12]}"
        object_key = f"{clean_folder}/{unique_id}{file_ext}"

        mime_type, _ = mimetypes.guess_type(fname)
        mime_type = mime_type or "application/octet-stream"

        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=object_key,
                Body=content,
                ContentType=mime_type,
                Metadata={
                    "original_filename": fname,
                    "uploaded_at": datetime.utcnow().isoformat()
                }
            )
            logger.info("Uploaded blob to RustFS: %s (%d bytes)", object_key, len(content))
            return object_key
        except Exception as e:
            logger.error("Failed to upload blob '%s' to RustFS: %s", object_key, e)
            # Fallback to local storage if RustFS is unreachable
            fallback_dir = _local_fallback_path(clean_folder)
            os.makedirs(fallback_dir, exist_ok=True)
            fallback_path = os.path.join(fallback_dir, f"{unique_id}{file_ext}")
            with open(fallback_path, "wb") as f:
                f.write(content)
            logger.warning("Saved to fallback local path: %s", fallback_path)
            return object_key

    def get_file(self, object_key: str) -> Tuple[Optional[BinaryIO], str, str]:
        """
        Retrieves a blob from RustFS.
        Returns (streaming_body, content_type, filename).
        """
        clean_key = _safe_key(object_key)
        filename = os.path.basename(clean_key)
        mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "application/octet-stream"

        # 1. Try RustFS object store
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=clean_key)
            body = response["Body"]
            ctype = response.get("ContentType", mime_type)
            return body, ctype, filename
        except Exception as rustfs_err:
            logger.debug("Object key '%s' not in RustFS bucket, checking local disk: %s", clean_key, rustfs_err)

        # 2. Fallback check on local disk
        candidate = _local_fallback_path(clean_key)
        if os.path.isfile(candidate):
            try:
                f = open(candidate, "rb")
                return f, mime_type, filename
            except Exception as disk_err:
                logger.error("Error reading local fallback file %s: %s", candidate, disk_err)

        return None, mime_type, filename

    def get_file_info(self, object_key: str) -> Optional[dict]:
        """
        Retrieves metadata about a blob (file size, content type, ETag, etc.).
        Checks RustFS first, then fallback to local disk.
        """
        clean_key = _safe_key(object_key)
        try:
            head = self.client.head_object(Bucket=self.bucket_name, Key=clean_key)
            mime_type, _ = mimetypes.guess_type(clean_key)
            return {
                "size": head.get("ContentLength", 0),
                "content_type": head.get("ContentType") or mime_type or "application/octet-stream",
                "etag": head.get("ETag"),
                "filename": os.path.basename(clean_key),
                "in_rustfs": True
            }
        except Exception:
            pass

        # Check local disk
        candidate = _local_fallback_path(clean_key)
        if os.path.isfile(candidate):
            mime_type, _ = mimetypes.guess_type(candidate)
            return {
                "size": os.path.getsize(candidate),
                "content_type": mime_type or "application/octet-stream",
                "etag": None,
                "filename": os.path.basename(candidate),
                "in_rustfs": False,
            }
        return None

    def fingerprint_file_version(self, object_key: str, *, max_bytes: int,
                                 version_id: Optional[str] = None) -> dict:
        return self._fingerprint_file_version(object_key, max_bytes=max_bytes, version_id=version_id)

    def read_verified_file_version(self, fingerprint: dict, *, max_bytes: int) -> bytes:
        """Return only the fully validated bytes of an internally saved fingerprint."""
        if not fingerprint.get('version_id') or fingerprint.get('version_id') == 'null':
            raise ValueError('An exact reviewed object version is required')
        if fingerprint.get('bucket') != self.bucket_name:
            raise ValueError('Evidence bucket mismatch')
        content = BytesIO()
        actual = self._fingerprint_file_version(fingerprint['object_key'], max_bytes=max_bytes,
            version_id=fingerprint['version_id'], content=content)
        if actual != fingerprint:
            raise ValueError('Reviewed evidence content changed')
        return content.getvalue()

    def _fingerprint_file_version(self, object_key: str, *, max_bytes: int,
                                  version_id: Optional[str] = None, content=None) -> dict:
        """Hash one complete, non-null object version without any local fallback.

        Internal evidence primitive, NOT an authorization boundary. The owning
        service must authorize/scoped-resolve the key and persist the returned
        version/hash before review. Later checks must request that exact version.
        Versioning is not retention: missing/deleted versions fail closed. This
        method neither configures buckets nor uploads/copies/locks objects.
        """
        clean_key = _safe_key(object_key)
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError('An explicit positive evidence size limit is required')

        def valid_version(value):
            return (isinstance(value, str) and bool(value.strip()) and value != 'null'
                    and len(value) <= 1024 and not any(ord(c) < 32 or ord(c) == 127 for c in value))

        if version_id is not None and not valid_version(version_id):
            raise ValueError('A non-null object version is required')
        params = dict(Bucket=self.bucket_name, Key=clean_key)
        if version_id is not None:
            params['VersionId'] = version_id
        # Deliberately do not call get_file: its compatibility fallback cannot
        # establish a version-pinned evidence identity.
        response = self.client.get_object(**params)
        body = response.get('Body')
        try:
            actual_version = response.get('VersionId')
            if not valid_version(actual_version) or (version_id is not None and actual_version != version_id):
                raise ValueError('Evidence object version is unavailable or mismatched')
            if response.get('DeleteMarker') or response.get('ContentRange'):
                raise ValueError('Complete evidence object required')
            size = response.get('ContentLength')
            if type(size) is not int or not 0 < size <= max_bytes:
                raise ValueError('Evidence object size is missing, empty or exceeds the configured limit')
            if body is None:
                raise ValueError('Evidence object body is missing')
            digest = hashlib.sha256()
            received = 0
            while True:
                chunk = body.read(min(64 * 1024, size - received + 1))
                if not isinstance(chunk, bytes):
                    raise ValueError('Evidence stream must contain bytes')
                if not chunk:
                    break
                received += len(chunk)
                if received > size:
                    raise ValueError('Evidence stream exceeds declared size')
                digest.update(chunk)
                if content is not None:
                    content.write(chunk)
            if received != size:
                raise ValueError('Evidence stream is incomplete')
            return dict(policy='blob-sha256-v1', bucket=self.bucket_name, object_key=clean_key,
                        version_id=actual_version, size=received, sha256=digest.hexdigest())
        finally:
            if body is not None:
                body.close()

    def get_file_range(
        self,
        object_key: str,
        byte_range: Optional[str] = None
    ) -> Tuple[Optional[BinaryIO], str, str, Optional[int], Optional[str]]:
        """
        Retrieves a blob or byte range from RustFS or local fallback.
        Supports byte range requests for video streaming / resuming.
        Returns (streaming_body, content_type, filename, content_length, content_range).
        """
        clean_key = _safe_key(object_key)
        filename = os.path.basename(clean_key)
        mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "application/octet-stream"

        # 1. Try RustFS object store
        try:
            params = {"Bucket": self.bucket_name, "Key": clean_key}
            if byte_range:
                params["Range"] = byte_range
            response = self.client.get_object(**params)
            body = response["Body"]
            ctype = response.get("ContentType", mime_type)
            clen = response.get("ContentLength")
            crange = response.get("ContentRange")
            return body, ctype, filename, clen, crange
        except Exception as rustfs_err:
            logger.debug("Object key '%s' not in RustFS bucket or range error, checking local disk: %s", clean_key, rustfs_err)

        # 2. Fallback check on local disk
        candidate = _local_fallback_path(clean_key)
        if os.path.isfile(candidate):
            try:
                f = open(candidate, "rb")
                file_size = os.path.getsize(candidate)
                if byte_range and byte_range.startswith("bytes="):
                    r = byte_range[6:]
                    parts = r.split("-")
                    start = int(parts[0]) if parts[0] else 0
                    end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
                    end = min(end, file_size - 1)
                    f.seek(start)
                    length = end - start + 1
                    crange = f"bytes {start}-{end}/{file_size}"
                    return f, mime_type, filename, length, crange
                return f, mime_type, filename, file_size, None
            except Exception as disk_err:
                logger.error("Error reading local fallback file %s: %s", candidate, disk_err)

        return None, mime_type, filename, None, None

    def delete_file(self, object_key: str) -> bool:
        """
        Deletes a blob from RustFS and any local fallback path.
        """
        clean_key = _safe_key(object_key)

        # Delete from RustFS
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=clean_key)
            logger.info("Deleted blob from RustFS: %s", clean_key)
        except Exception as e:
            logger.warning("RustFS delete object warning for '%s': %s", clean_key, e)

        # Delete local copy if present
        local_path = _local_fallback_path(clean_key)
        try:
            if os.path.isfile(local_path):
                os.remove(local_path)
        except OSError as exc:
            logger.warning("Local fallback delete warning for '%s': %s", clean_key, exc)

        return True

    @staticmethod
    def _signing_key() -> bytes:
        key = os.getenv("MEDIA_SIGNING_KEY", "")
        if not key:
            raise RuntimeError("MEDIA_SIGNING_KEY is required to sign media URLs")
        return key.encode("utf-8")

    def _media_signature(self, object_key: str, expires_at: int) -> str:
        clean_key = _safe_key(object_key)
        payload = f"{clean_key}:{int(expires_at)}".encode("utf-8")
        return hmac.new(self._signing_key(), payload, hashlib.sha256).hexdigest()

    def signed_url(self, object_key: str, ttl: int) -> str:
        """Return an application URL with a short-lived HMAC signature."""
        clean_key = _safe_key(object_key)
        expires_at = int(time.time()) + max(1, int(ttl))
        signature = self._media_signature(clean_key, expires_at)
        return f"/blobs/{clean_key}?exp={expires_at}&sig={signature}"

    def verify_signed_url(self, object_key: str, expires_at: int, signature: str) -> bool:
        """Validate a media URL without revealing why an invalid link failed."""
        try:
            expiry = int(expires_at)
            if expiry < int(time.time()) or not signature:
                return False
            expected = self._media_signature(object_key, expiry)
            return hmac.compare_digest(expected, signature)
        except (TypeError, ValueError, RuntimeError):
            return False

    def get_presigned_url(self, object_key: str, expires_in: int = 3600) -> Optional[str]:
        """
        Generates a presigned GET URL for direct download / streaming.
        """
        clean_key = _safe_key(object_key)
        try:
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": clean_key},
                ExpiresIn=expires_in
            )
            return url
        except Exception as e:
            logger.error("Failed to generate presigned URL for %s: %s", clean_key, e)
            return None


# Global singleton instance
blob_storage = RustFSClient()
