import pytest
from Services.sales_product_media import sales_thumbnail


@pytest.mark.parametrize('images', [None, [], ['invalid'], [{'file_url': 'orders/private.pdf'}],
    [{'file_url': 'https://external.invalid/image.png'}]])
def test_non_product_media_is_not_signed(images, monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Must not sign this source')
    monkeypatch.setattr('Services.sales_product_media.blob_storage.signed_url', deny)
    assert sales_thumbnail(images) is None


def test_product_image_uses_existing_signer(monkeypatch):
    calls = []
    def sign(key, ttl):
        calls.append((key, ttl))
        return '/blobs/synthetic?sig=synthetic'
    monkeypatch.setattr('Services.sales_product_media.blob_storage.signed_url', sign)
    assert sales_thumbnail([{'file_url': 'products/images/sample.png'}]) == '/blobs/synthetic?sig=synthetic'
    assert calls == [('products/images/sample.png', 86400)]


def test_signing_failure_never_returns_raw_key(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError('Signing unavailable')
    monkeypatch.setattr('Services.sales_product_media.blob_storage.signed_url', unavailable)
    assert sales_thumbnail([{'file_url': 'products/images/sample.png'}]) is None
