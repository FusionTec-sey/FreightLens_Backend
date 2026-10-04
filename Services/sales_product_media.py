"""Optional sales thumbnails from already-scoped product rows, never documents."""
from Utils.blob_storage import blob_storage


def sales_thumbnail(images):
    if not isinstance(images, list) or not images or not isinstance(images[0], dict):
        return None
    key = images[0].get('file_url') or images[0].get('url')
    if not isinstance(key, str) or not key.startswith('products/images/'):
        return None
    try:
        return blob_storage.signed_url(key, ttl=24 * 60 * 60)
    except (ValueError, RuntimeError):
        # Missing optional media must not bypass signing or block draft access.
        return None
