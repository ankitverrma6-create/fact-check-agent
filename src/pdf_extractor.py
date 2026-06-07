"""PDF text extraction utilities."""

from __future__ import annotations

import io
from typing import BinaryIO

from pypdf import PdfReader


class PDFExtractionError(Exception):
    """Raised when PDF text cannot be extracted."""


def extract_text_from_pdf(
    file_obj: BinaryIO | bytes,
    *,
    max_pages: int = 50,
) -> tuple[str, int]:
    """
    Extract text from a PDF upload.

    Returns:
        Tuple of (extracted_text, page_count).
    """
    if isinstance(file_obj, bytes):
        stream: BinaryIO = io.BytesIO(file_obj)
    else:
        stream = file_obj
        stream.seek(0)

    try:
        reader = PdfReader(stream)
    except Exception as exc:
        raise PDFExtractionError("Unable to read PDF file.") from exc

    page_count = len(reader.pages)
    if page_count == 0:
        raise PDFExtractionError("PDF contains no pages.")

    pages_to_read = min(page_count, max_pages)
    chunks: list[str] = []

    for index in range(pages_to_read):
        page = reader.pages[index]
        text = page.extract_text() or ""
        if text.strip():
            chunks.append(text.strip())

    if not chunks:
        raise PDFExtractionError(
            "No readable text found. The PDF may be scanned or image-only."
        )

    combined = "\n\n".join(chunks)
    if page_count > max_pages:
        combined += (
            f"\n\n[Note: Only the first {max_pages} of {page_count} pages were analyzed.]"
        )

    return combined, page_count
