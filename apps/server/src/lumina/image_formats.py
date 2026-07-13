from __future__ import annotations


IMAGE_MIME_BY_FORMAT = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
IMAGE_FORMAT_BY_MIME = {
    mime_type: name for name, mime_type in IMAGE_MIME_BY_FORMAT.items()
}
