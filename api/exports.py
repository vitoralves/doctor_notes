from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import boto3
from fpdf import FPDF

from api.config import AWS_REGION, PRESIGNED_URL_EXPIRES, S3_EXPORTS_BUCKET

_s3 = boto3.client("s3", region_name=AWS_REGION)


def _pdf_bytes(title: str, body: str) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(0, 8, title)
    pdf.ln(4)
    pdf.set_font("Helvetica", size=11)
    safe = body.encode("latin-1", "replace").decode("latin-1")
    pdf.multi_cell(0, 6, safe)
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

    if fmt in {"markdown", "md"}:
        key = f"exports/{user_id}/{visit_id}/{uuid4().hex}.md"
        content = (
            f"# Consultation — {patient_name}\n\n"
            f"Visit ID: `{visit_id}`\n\n"
            f"{summary}\n"
        ).encode("utf-8")
        content_type = "text/markdown; charset=utf-8"
        download_name = f"{patient_name.replace(' ', '_')}_{visit_id}.md"
    else:
        key = f"exports/{user_id}/{visit_id}/{uuid4().hex}.pdf"
        content = _pdf_bytes(f"Consultation — {patient_name}", summary)
        content_type = "application/pdf"
        download_name = f"{patient_name.replace(' ', '_')}_{visit_id}.pdf"

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
    return {"url": url, "key": key, "format": "pdf" if fmt == "pdf" else "markdown"}
