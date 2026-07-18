from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile, ZipFile

from ..document_limits import MAX_OPENXML_MEMBERS


MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".html": "text/html",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".py": "text/x-python",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_OPENXML_REQUIRED_MEMBER = {
    ".docx": "word/document.xml",
    ".xlsx": "xl/workbook.xml",
    ".pptx": "ppt/presentation.xml",
}
_MAX_OPENXML_EXPANDED_BYTES = 150 * 1024 * 1024


def sniff_mime(content: bytes, extension: str) -> str:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    if extension in _OPENXML_REQUIRED_MEMBER:
        return _sniff_openxml_mime(content, extension)
    if extension in {".txt", ".html", ".md", ".csv", ".tsv", ".py"}:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return "application/octet-stream"
        return MIME_BY_EXTENSION[extension]
    return "application/octet-stream"


def _sniff_openxml_mime(content: bytes, extension: str) -> str:
    if not content.startswith(b"PK\x03\x04"):
        return "application/octet-stream"
    try:
        with ZipFile(BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > MAX_OPENXML_MEMBERS:
                return "application/octet-stream"
            expanded_size = sum(member.file_size for member in members)
            if expanded_size > _MAX_OPENXML_EXPANDED_BYTES:
                return "application/octet-stream"
            names = {member.filename.replace("\\", "/") for member in members}
    except (BadZipFile, OSError, ValueError):
        return "application/octet-stream"
    required = {"[Content_Types].xml", _OPENXML_REQUIRED_MEMBER[extension]}
    return (
        MIME_BY_EXTENSION[extension]
        if required.issubset(names)
        else "application/octet-stream"
    )
