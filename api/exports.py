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

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\d+)\.\s+(.*)$")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")


def _pdf_safe(text: str) -> str:
    for src, dst in _UNICODE_REPLACEMENTS.items():
        text = text.replace(src, dst)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    return text.encode("latin-1", "replace").decode("latin-1")


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", name.strip(), flags=re.UNICODE)
    return cleaned[:80] or "export"


def _content_width(pdf: FPDF, indent: float = 0) -> float:
    width = pdf.epw - indent
    if width < 20:
        raise ValueError(f"Insufficient PDF content width: {width:.1f}mm")
    return width


def _write_block(
    pdf: FPDF,
    text: str,
    *,
    indent: float = 0,
    line_height: float = 6,
    markdown: bool = False,
) -> None:
    pdf.set_x(pdf.l_margin + indent)
    pdf.multi_cell(
        _content_width(pdf, indent),
        line_height,
        text,
        markdown=markdown,
        new_x="LMARGIN",
        new_y="NEXT",
    )


def _write_markdown_pdf(pdf: FPDF, markdown_text: str) -> None:
    heading_sizes = {1: 16, 2: 14, 3: 12, 4: 11, 5: 11, 6: 11}
    list_indent = 6

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            pdf.ln(3)
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            level = len(heading.group(1))
            text = _pdf_safe(heading.group(2))
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", heading_sizes.get(level, 11))
            _write_block(pdf, text, line_height=7)
            pdf.ln(1)
            continue

        bullet = _BULLET_RE.match(stripped)
        if bullet:
            text = _pdf_safe(bullet.group(1))
            pdf.set_font("Helvetica", size=11)
            _write_block(pdf, f"- {text}", indent=list_indent, markdown=True)
            continue

        ordered = _ORDERED_RE.match(stripped)
        if ordered:
            number, content = ordered.group(1), _pdf_safe(ordered.group(2))
            pdf.set_font("Helvetica", size=11)
            _write_block(
                pdf,
                f"{number}. {content}",
                indent=list_indent,
                markdown=True,
            )
            continue

        pdf.set_font("Helvetica", size=11)
        _write_block(pdf, _pdf_safe(stripped), markdown=True)


def _pdf_bytes(title: str, body: str) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    _write_block(pdf, _pdf_safe(title), line_height=9)
    pdf.ln(2)
    _write_markdown_pdf(pdf, body)
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
