import os
import logging
from typing import List
from fastapi import UploadFile
from .blob_storage import blob_storage

logger = logging.getLogger("containerMgmt.upload")

def save_uploaded_files(files: List[UploadFile], path: str) -> List[str]:
    """
    Uploads files to RustFS object store (with local fallback) and returns the list of stored object keys / paths.
    """
    saved_paths = []
    if not files:
        return saved_paths

    for file in files:
        if not file or not file.filename:
            continue  # Skip empty uploads

        try:
            object_key = blob_storage.upload_file(file_obj=file, folder=path, original_filename=file.filename)
            saved_paths.append(object_key)
        except Exception as e:
            logger.error("Failed to save uploaded file '%s': %s", file.filename, e)

    return saved_paths

def remove_files(file_paths: List[str]) -> None:
    """
    Removes files from RustFS object store and any local disk copy.
    """
    if not file_paths:
        return

    for path in file_paths:
        if not path:
            continue
        try:
            blob_storage.delete_file(path)
        except Exception as e:
            logger.warning("Could not delete file blob '%s': %s", path, e)
