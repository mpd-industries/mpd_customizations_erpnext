from __future__ import annotations

import base64
import io
import json
import os
import re

import frappe

from mpd_customizations.asset_organizer.ai import logger
from frappe.utils import now_datetime

from mpd_customizations.mpd_base.item_ai.dedup import (
    check_item_duplicates,
    check_item_duplicates_and_set_status,
)
from mpd_customizations.mpd_base.ai.llm import call_llm
from mpd_customizations.asset_organizer.ai.schemas import (
    CATEGORY_SCHEMA_MAP,
    CATEGORY_TASK_KEY_MAP,
    PaymentExtractionSchema,
    SegmentationSchema,
)


_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".tif", ".bmp"}


def _image_bytes_to_pdf(image_bytes: bytes) -> bytes:
    """Convert raw image bytes to a single-page PDF using Pillow."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def _read_file_as_base64(file_url: str) -> tuple[str, str]:
    """
    Given a Frappe file URL, returns (base64_data_url, filename).
    Handles three cases:
      - /private/files/... or /files/...  → read from local filesystem
      - /api/method/frappe_s3_attachment... → fetch via HTTP (S3 presigned redirect)
      - Anything else                       → try as an absolute filesystem path

    Image files (jpg, png, etc.) are automatically converted to single-page PDFs
    so all document types flow through the same PDF code path.
    """
    import urllib.parse

    # --- Extract filename from URL query string or path ---
    parsed = urllib.parse.urlparse(file_url)
    qs = urllib.parse.parse_qs(parsed.query)
    filename = (
        qs.get("file_name", [None])[0]
        or os.path.basename(parsed.path)
        or "document.pdf"
    )

    # --- Read raw bytes ---
    if "/api/method/" in file_url:
        raw = _fetch_api_file(file_url)
    else:
        site_path = frappe.get_site_path()
        if file_url.startswith("/private/files/"):
            abs_path = os.path.join(site_path, file_url.lstrip("/"))
        elif file_url.startswith("/files/"):
            abs_path = os.path.join(site_path, "public", file_url.lstrip("/"))
        else:
            abs_path = file_url

        with open(abs_path, "rb") as fh:
            raw = fh.read()

    # --- Convert images to PDF so all uploads share one code path ---
    ext = os.path.splitext(filename)[1].lower()
    if ext in _IMAGE_EXTENSIONS:
        logger.info(f"Converting image '{filename}' to PDF before LLM submission")
        raw = _image_bytes_to_pdf(raw)
        filename = os.path.splitext(filename)[0] + ".pdf"

    b64 = base64.b64encode(raw).decode("utf-8")
    return f"data:application/pdf;base64,{b64}", filename


def _fetch_api_file(file_url: str) -> bytes:
    """
    Download a file stored in S3 via frappe_s3_attachment.
    Parses the S3 key from the URL and fetches the object directly using
    S3Operations — no HTTP round-trip needed.
    """
    import urllib.parse
    from frappe_s3_attachment.controller import S3Operations

    parsed = urllib.parse.urlparse(file_url)
    qs = urllib.parse.parse_qs(parsed.query)
    key = qs.get("key", [None])[0]
    if not key:
        raise ValueError(f"No 'key' parameter found in S3 file URL: {file_url}")

    s3 = S3Operations()
    response = s3.read_file_from_s3(key)
    return response["Body"].read()


def _split_pdf(pdf_bytes: bytes, pages: list[int]) -> bytes:
    """Return a new PDF containing only the specified 1-based page numbers."""
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _save_split_file(apr_name: str, pdf_bytes: bytes, filename: str) -> str:
    """
    Save split PDF bytes as a private Frappe File attached to the APR.
    Returns the file URL.
    """
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "attached_to_doctype": "Asset Procurement Record",
        "attached_to_name": apr_name,
        "is_private": 1,
        "content": pdf_bytes,
    })
    file_doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return file_doc.file_url

