import logging
import os
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from auth.dependencies import get_current_user
from Utils.blob_storage import _safe_key, blob_storage

logger = logging.getLogger("containerMgmt.blobs")

BlobRouter = APIRouter(prefix="/blobs", tags=["Blob & Media Storage (RustFS)"])

PUBLIC_MEDIA_PREFIXES = ("products/images/", "products/videos/", "suppliers/logos/")
UPLOAD_RULES = {
    "products/images": {
        "max_bytes": 10 * 1024 * 1024,
        "content_prefix": "image/",
        "extensions": {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"},
    },
    "products/videos": {
        "max_bytes": 200 * 1024 * 1024,
        "content_prefix": "video/",
        "extensions": {".m4v", ".mov", ".mp4", ".ogv", ".webm"},
    },
}


def _signed_media_path(blob_path: str, exp: int | None, sig: str | None) -> str:
    try:
        normalized = _safe_key(blob_path)
    except ValueError:
        raise HTTPException(status_code=404, detail="Blob not found")
    if not normalized.startswith(PUBLIC_MEDIA_PREFIXES):
        raise HTTPException(status_code=404, detail="Blob not found")
    if not blob_storage.verify_signed_url(normalized, exp, sig):
        raise HTTPException(status_code=404, detail="Blob not found")
    return normalized


@BlobRouter.get("/health/status")
def check_blob_storage_health(current_user=Depends(get_current_user)):
    """Check connectivity to RustFS object store bucket."""
    is_ready = blob_storage.ensure_bucket_exists()
    return {
        "status": "connected" if is_ready else "error",
        "bucket": blob_storage.bucket_name,
    }


@BlobRouter.head("/{blob_path:path}")
def head_blob(blob_path: str, exp: int | None = Query(None), sig: str | None = Query(None)):
    """
    Check if a blob exists in RustFS and return its content type and length.
    Useful for video pre-buffering and image existence checks.
    """
    blob_path = _signed_media_path(blob_path, exp, sig)
    try:
        info = blob_storage.get_file_info(blob_path)
    except ValueError:
        raise HTTPException(status_code=404, detail="Blob not found")
    if not info:
        raise HTTPException(status_code=404, detail="Blob not found")

    headers = {
        "Content-Type": info["content_type"],
        "Content-Length": str(info["size"]),
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=300",
    }
    if info.get("etag"):
        headers["ETag"] = info["etag"]

    return Response(status_code=200, headers=headers)


@BlobRouter.get("/{blob_path:path}")
def get_blob(blob_path: str, request: Request, exp: int | None = Query(None), sig: str | None = Query(None)):
    """
    Stream a blob (image, video, document, logo) from RustFS.
    Supports HTTP Range requests (RFC 7233) for HTML5 video playback, seeking, and streaming.
    """
    blob_path = _signed_media_path(blob_path, exp, sig)
    range_header = request.headers.get("Range")

    try:
        body, ctype, fname, clen, crange = blob_storage.get_file_range(
            blob_path,
            byte_range=range_header,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Blob not found")
    if body is None:
        raise HTTPException(status_code=404, detail=f"Blob '{blob_path}' not found in RustFS or local storage")

    response_headers = {
        "Content-Type": ctype,
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=300",
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
async def upload_blob(
    file: UploadFile = File(...),
    folder: str = Query(..., description="Target product-media folder in RustFS"),
    current_user=Depends(get_current_user),
):
    """
    Generic upload endpoint to store any media or document in RustFS.
    Returns the unique object key and accessible URL path.
    """
    rule = UPLOAD_RULES.get(folder)
    if rule is None:
        raise HTTPException(status_code=400, detail="Unsupported upload folder")

    content_type = (file.content_type or "").lower()
    extension = os.path.splitext(file.filename or "")[1].lower()
    if not content_type.startswith(rule["content_prefix"]) or extension not in rule["extensions"]:
        raise HTTPException(status_code=400, detail="Unsupported media type")

    content = await file.read(rule["max_bytes"] + 1)
    if len(content) > rule["max_bytes"]:
        raise HTTPException(status_code=413, detail="Uploaded media exceeds the size limit")

    key = blob_storage.upload_file(file_obj=content, folder=folder, original_filename=file.filename)
    return {
        "success": True,
        "object_key": key,
        "url": blob_storage.signed_url(key, ttl=24 * 60 * 60),
        "file_name": file.filename,
        "message": "File stored successfully in RustFS"
    }
