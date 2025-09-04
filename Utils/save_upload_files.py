import os
from typing import List
from fastapi import UploadFile
from datetime import datetime
import uuid

# Define your base upload directory
UPLOAD_DIR = "BLOB/"

def save_uploaded_files(files: List[UploadFile], path) -> List[str]:
    """
    Saves uploaded files to the disk and returns the list of saved file paths.
    """
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    saved_paths = []

    for file in files:
        if file.filename == "":
            continue  # Skip empty uploads

        # Generate unique filename to avoid overwriting
        file_ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}{file_ext}"

        # Define full path
        file_path = os.path.join(UPLOAD_DIR + path, unique_filename)

        # Save file
        with open(file_path, "wb") as f:
            content = file.file.read()
            f.write(content)

        # Save relative path (can adjust if needed)
        saved_paths.append(file_path)

    return saved_paths


import os
from typing import List

def remove_files(file_paths: List[str]) -> None:
    """
    Removes files given by the list of file paths if they exist.
    Logs any errors encountered during removal.
    """
    for path in file_paths:
        if not path:
            continue  # skip empty or None paths

        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Could not delete file {path}: {e}")
