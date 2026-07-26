from __future__ import annotations

import logging
import re
from io import BytesIO
from uuid import uuid4

import boto3
from fpdf import FPDF

from api.config import AWS_REGION, PRESIGNED_URL_EXPIRES, S3_EXPORTS_BUCKET

logger = logging.getLogger("consultation-app.exports")

_s3 = boto3.client("s3", region_name=AWS_REGION)

_UNICODE_REPLACEMENTS = {
    "\u2014": "-",
    "\u2013": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u00a0": " ",
    "\u2022": "*",
}


def _pdf_safe(text: str) -> str:
    for src, dst in _UNICODE_REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", name.strip(), flags=re.UNICODE)
    return cleaned[:80] or "export"


def _pdf_bytes(title: str, body: str) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(0, 8, _pdf_safe(title))
    pdf.ln(4)
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, _pdf_safe(body))
    out = BytesIO()
    pdf.output(out)
    return out.getvalue()


def create_export(
    *,
    user_id: str,
    visit_id: str,
    patient_name: str,
    summary: str,
    fmt: str,
) -> dict[str, str]:
    fmt = fmt.lower().strip()
    if fmt not in {"markdown", "md", "pdf"}:
        raise ValueError("format must be markdown or pdf")

    filename_base = _safe_filename(f"{patient_name}_{visit_id}")

    if fmt in {"markdown", "md"}:
        key = f"exports/{user_id}/{visit_id}/{uuid4().hex}.md"
        content = (
            f"# Consultation - {patient_name}\n\n"
            f"Visit ID: `{visit_id}`\n\n"
            f"{summary}\n"
        ).encode("utf-8")
        content_type = "text/markdown; charset=utf-8"
        download_name = f"{filename_base}.md"
        export_format = "markdown"
    else:
        key = f"exports/{user_id}/{visit_id}/{uuid4().hex}.pdf"
        content = _pdf_bytes(f"Consultation - {patient_name}", summary)
        content_type = "application/pdf"
        download_name = f"{filename_base}.pdf"
        export_format = "pdf"

    logger.info(
        "export_upload_start user_id=%s visit_id=%s format=%s key=%s bytes=%s",
        user_id,
        visit_id,
        export_format,
        key,
        len(content),
    )

    _s3.put_object(
        Bucket=S3_EXPORTS_BUCKET,
        Key=key,
        Body=content,
        ContentType=content_type,
        ContentDisposition=f'attachment; filename="{download_name}"',
        ServerSideEncryption="AES256",
    )

    url = _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_EXPORTS_BUCKET, "Key": key},
        ExpiresIn=PRESIGNED_URL_EXPIRES,
    )

    logger.info(
        "export_upload_ok user_id=%s visit_id=%s format=%s key=%s",
        user_id,
        visit_id,
        export_format,
        key,
    )
    return {"url": url, "key": key, "format": export_format}
