import os
import uuid
import logging
import mimetypes
from datetime import datetime
from typing import Optional, Tuple, BinaryIO, Union
from io import BytesIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi import UploadFile

logger = logging.getLogger("containerMgmt.blob_storage")

class RustFSClient:
    """
    S3-compatible blob and object storage client for RustFS.
    Manages uploading, downloading, streaming, and deletion of file blobs.
    """

    def __init__(self):
        self.endpoint_url = os.getenv("RUSTFS_ENDPOINT_URL", "http://rustfs:9000")
        self.access_key = os.getenv("RUSTFS_ACCESS_KEY", "rustfs_admin")
        self.secret_key = os.getenv("RUSTFS_SECRET_KEY", "rustfs_secret_password_123")
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
        if file_obj is None and "file_bytes" in kwargs:
            file_obj = kwargs["file_bytes"]
        fname = original_filename or kwargs.get("file_name")
        if isinstance(file_obj, UploadFile):
            fname = fname or file_obj.filename or "upload"
            file_obj.file.seek(0)
            content = file_obj.file.read()
        elif isinstance(file_obj, bytes):
            fname = fname or "upload.bin"
            content = file_obj
        else:
            fname = fname or "upload.bin"
            content = file_obj.read()

        file_ext = os.path.splitext(fname)[1]
        unique_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:12]}"
        object_key = f"{folder.strip('/')}/{unique_id}{file_ext}"

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
            fallback_dir = os.path.join("BLOB", folder)
            os.makedirs(fallback_dir, exist_ok=True)
            fallback_path = os.path.join(fallback_dir, f"{unique_id}{file_ext}")
            with open(fallback_path, "wb") as f:
                f.write(content)
            logger.warning("Saved to fallback local path: %s", fallback_path)
            return fallback_path

    def get_file(self, object_key: str) -> Tuple[Optional[BinaryIO], str, str]:
        """
        Retrieves a blob from RustFS.
        Returns (streaming_body, content_type, filename).
        """
        clean_key = object_key.replace("BLOB/", "").replace("\\", "/")
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
        local_candidates = [
            object_key,
            os.path.join("BLOB", clean_key),
            os.path.normpath(object_key)
        ]
        for candidate in local_candidates:
            if os.path.isfile(candidate):
                try:
                    f = open(candidate, "rb")
                    return f, mime_type, filename
                except Exception as disk_err:
                    logger.error("Error reading local fallback file %s: %s", candidate, disk_err)

        return None, mime_type, filename

    def delete_file(self, object_key: str) -> bool:
        """
        Deletes a blob from RustFS and any local fallback path.
        """
        if not object_key:
            return True

        clean_key = object_key.replace("BLOB/", "").replace("\\", "/")

        # Delete from RustFS
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=clean_key)
            logger.info("Deleted blob from RustFS: %s", clean_key)
        except Exception as e:
            logger.warning("RustFS delete object warning for '%s': %s", clean_key, e)

        # Delete local copy if present
        local_candidates = [object_key, os.path.join("BLOB", clean_key)]
        for path in local_candidates:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

        return True

    def get_presigned_url(self, object_key: str, expires_in: int = 3600) -> Optional[str]:
        """
        Generates a presigned GET URL for direct download / streaming.
        """
        clean_key = object_key.replace("BLOB/", "").replace("\\", "/")
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
