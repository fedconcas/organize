"""Capped, read-only text extraction. Nothing extracted here is ever written to disk."""

import hashlib
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Optional

READ_CAP = 64 * 1024
TEXT_CAP = 1500
PDF_PAGES = 2
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
TEXT_EXTENSIONS = {
    "txt", "md", "markdown", "csv", "tsv", "json", "xml", "yaml", "yml", "log", "ini", "cfg", "toml",
    "html", "htm", "rtf", "tex", "py", "js", "ts", "sh", "sql", "srt", "vtt", "eml",
}

for _name in ("pdfminer", "pdfminer.pdfpage", "pdfminer.pdfinterp", "pdfminer.converter"):
    logging.getLogger(_name).setLevel(logging.ERROR)


def content_digest(path: Path) -> str:
    """SHA-256 over the first READ_CAP bytes plus the size, used as a cache key."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            digest.update(handle.read(READ_CAP))
        digest.update(str(path.stat().st_size).encode())
    except OSError:
        digest.update(b"unreadable")
    return digest.hexdigest()


def _squash(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:TEXT_CAP]


def _plain(path: Path) -> str:
    with path.open("rb") as handle:
        data = handle.read(READ_CAP)
    if b"\x00" in data[:1024]:
        return ""
    return data.decode("utf-8", errors="replace")


def _pdf(path: Path) -> str:
    from pdfminer.high_level import extract_text

    return extract_text(str(path), maxpages=PDF_PAGES) or ""


def _docx(path: Path) -> str:
    with zipfile.ZipFile(str(path)) as archive:
        info = archive.getinfo("word/document.xml")
        if info.file_size > 20 * 1024 * 1024:
            return ""
        with archive.open(info) as handle:
            xml = handle.read(READ_CAP * 4).decode("utf-8", errors="replace")
    text = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", " ", text)


def extract_text(path: Path) -> str:
    """Up to TEXT_CAP characters of readable text, or "" when the type is not supported."""
    extension = path.suffix.lower().lstrip(".")
    try:
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            return ""
        if extension in TEXT_EXTENSIONS:
            return _squash(_plain(path))
        if extension == "pdf":
            return _squash(_pdf(path))
        if extension == "docx":
            return _squash(_docx(path))
    except Exception:
        # Malformed documents must never stop an analysis.
        return ""
    return ""


def first_line(text: Optional[str], limit: int = 300) -> str:
    return (text or "")[:limit]
