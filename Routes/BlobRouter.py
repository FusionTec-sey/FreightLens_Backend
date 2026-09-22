import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from Utils.blob_storage import blob_storage

logger = logging.getLogger("containerMgmt.blobs")

BlobRouter = APIRouter(prefix="/blobs", tags=["Blob & Media Storage (RustFS)"])


@BlobRouter.get("/health/status")
def check_blob_storage_health():
    """Check connectivity to RustFS object store bucket."""
    is_ready = blob_storage.ensure_bucket_exists()
    return {
        "status": "connected" if is_ready else "error",
        "bucket": blob_storage.bucket_name,
        "endpoint": blob_storage.endpoint_url
    }


@BlobRouter.head("/{blob_path:path}")
def head_blob(blob_path: str):
    """
    Check if a blob exists in RustFS and return its content type and length.
    Useful for video pre-buffering and image existence checks.
    """
    info = blob_storage.get_file_info(blob_path)
    if not info:
        raise HTTPException(status_code=404, detail="Blob not found")

    headers = {
        "Content-Type": info["content_type"],
        "Content-Length": str(info["size"]),
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=86400",
    }
    if info.get("etag"):
        headers["ETag"] = info["etag"]

    return Response(status_code=200, headers=headers)


@BlobRouter.get("/{blob_path:path}")
def get_blob(blob_path: str, request: Request):
    """
    Stream a blob (image, video, document, logo) from RustFS.
    Supports HTTP Range requests (RFC 7233) for HTML5 video playback, seeking, and streaming.
    """
    range_header = request.headers.get("Range")

    body, ctype, fname, clen, crange = blob_storage.get_file_range(blob_path, byte_range=range_header)
    if body is None:
        raise HTTPException(status_code=404, detail=f"Blob '{blob_path}' not found in RustFS or local storage")

    response_headers = {
        "Content-Type": ctype,
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=86400",
    }
    if clen is not None:
        response_headers["Content-Length"] = str(clen)

    if range_header and crange:
        # Partial content response for video seeking / audio streaming
        response_headers["Content-Range"] = crange
        status_code = 206
    else:
        status_code = 200

    return StreamingResponse(
        content=body,
        status_code=status_code,
        headers=response_headers,
        media_type=ctype
    )


@BlobRouter.post("/upload")
def upload_blob(
    file: UploadFile = File(...),
    folder: str = Query("general", description="Target folder prefix in RustFS (e.g. 'products/images', 'suppliers/logos')")
):
    """
    Generic upload endpoint to store any media or document in RustFS.
    Returns the unique object key and accessible URL path.
    """
    key = blob_storage.upload_file(file_obj=file, folder=folder, original_filename=file.filename)
    return {
        "success": True,
        "object_key": key,
        "url": f"/blobs/{key}",
        "file_name": file.filename,
        "message": "File stored successfully in RustFS"
    }


@BlobRouter.delete("/{blob_path:path}")
def delete_blob(blob_path: str):
    """Delete a blob from RustFS."""
    success = blob_storage.delete_file(blob_path)
    return {"success": success, "message": f"Blob '{blob_path}' removed"}
