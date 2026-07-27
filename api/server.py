from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from botocore.exceptions import ClientError, NoCredentialsError
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi_clerk_auth import ClerkConfig, ClerkHTTPBearer, HTTPAuthorizationCredentials
from openai import OpenAI
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import CLERK_JWKS_URL, MODEL_NAME, PROMPT_VERSION
from api.db import create_visit, get_usage_today, get_visit, increment_usage, list_visits
from api.exports import create_export
from api.rate_limit import RateLimitExceeded, check_and_increment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("consultation-app")

app = FastAPI(title="MediNotes Pro API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

clerk_config = ClerkConfig(jwks_url=CLERK_JWKS_URL)
clerk_guard = ClerkHTTPBearer(clerk_config)

SYSTEM_PROMPT = """
You are provided with notes written by a doctor from a patient's visit.
Your job is to summarize the visit for the doctor and provide an email.
Reply with exactly three sections with the headings:
### Summary of visit for the doctor's records
### Next steps for the doctor
### Draft of email to patient in patient-friendly language
"""


class VisitRequest(BaseModel):
    patient_name: str = Field(min_length=1)
    date_of_visit: str = Field(min_length=1)
    notes: str = Field(min_length=1)


class ExportRequest(BaseModel):
    visit_sk: str
    format: str = "markdown"


def user_prompt_for(visit: VisitRequest) -> str:
    return f"""Create the summary, next steps and draft email for:
Patient Name: {visit.patient_name}
Date of Visit: {visit.date_of_visit}
Notes:
{visit.notes}"""


def _sse(data: str, event: str | None = None) -> str:
    lines = data.split("\n")
    payload = "".join(f"data: {line}\n" for line in lines)
    if event:
        return f"event: {event}\n{payload}\n"
    return f"{payload}\n"


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "unhandled_request_error request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )
        raise

    elapsed_ms = (time.perf_counter() - started) * 1000
    if request.url.path.startswith("/api/") or response.status_code >= 400:
        logger.info(
            "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
    response.headers["X-Request-Id"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception(
        "unhandled_exception request_id=%s method=%s path=%s error_type=%s error=%s",
        request_id,
        request.method,
        request.url.path,
        type(exc).__name__,
        exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": request_id,
            "error_type": type(exc).__name__,
        },
    )


@app.exception_handler(NoCredentialsError)
async def missing_aws_credentials_handler(request: Request, exc: NoCredentialsError):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        "aws_credentials_missing request_id=%s method=%s path=%s",
        request_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "AWS credentials not found in this process. "
                "On Lambda this uses the execution role. "
                "For local Docker, mount ~/.aws or pass AWS_ACCESS_KEY_ID / "
                "AWS_SECRET_ACCESS_KEY (and AWS_SESSION_TOKEN if needed)."
            ),
            "request_id": request_id,
            "error_type": "NoCredentialsError",
        },
    )


@app.exception_handler(ClientError)
async def aws_client_error_handler(request: Request, exc: ClientError):
    request_id = getattr(request.state, "request_id", "unknown")
    error = exc.response.get("Error", {}) if getattr(exc, "response", None) else {}
    logger.exception(
        "aws_client_error request_id=%s method=%s path=%s code=%s message=%s",
        request_id,
        request.method,
        request.url.path,
        error.get("Code"),
        error.get("Message"),
    )
    return JSONResponse(
        status_code=502,
        content={
            "detail": f"AWS error: {error.get('Code', 'ClientError')}",
            "request_id": request_id,
            "error_type": "ClientError",
        },
    )


@app.exception_handler(StarletteHTTPException)
async def logged_http_exception_handler(request: Request, exc: StarletteHTTPException):
    request_id = getattr(request.state, "request_id", "unknown")
    if exc.status_code >= 500:
        logger.error(
            "http_exception request_id=%s method=%s path=%s status=%s detail=%s",
            request_id,
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
        )
    elif exc.status_code >= 400 and request.url.path.startswith("/api/"):
        logger.warning(
            "http_exception request_id=%s method=%s path=%s status=%s detail=%s",
            request_id,
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
        )
    return await http_exception_handler(request, exc)


@app.get("/health")
def health_check():
    return {"status": "healthy", "prompt_version": PROMPT_VERSION, "model": MODEL_NAME}


@app.get("/api/usage")
def usage(creds: HTTPAuthorizationCredentials = Depends(clerk_guard)):
    user_id = creds.decoded["sub"]
    try:
        return get_usage_today(user_id)
    except Exception:
        logger.exception("usage_failed user_id=%s", user_id)
        raise


@app.get("/api/visits")
def visits(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
    limit: int = Query(default=50, ge=1, le=100),
):
    user_id = creds.decoded["sub"]
    try:
        items = list_visits(user_id, limit=limit)
        return {
            "visits": [
                {
                    "visit_id": v.get("visit_id"),
                    "sk": v.get("sk"),
                    "patient_name": v.get("patient_name"),
                    "date_of_visit": v.get("date_of_visit"),
                    "summary": v.get("summary"),
                    "notes": v.get("notes"),
                    "model": v.get("model"),
                    "prompt_version": v.get("prompt_version"),
                    "input_tokens": v.get("input_tokens", 0),
                    "output_tokens": v.get("output_tokens", 0),
                    "created_at": v.get("created_at"),
                }
                for v in items
            ]
        }
    except Exception:
        logger.exception("list_visits_failed user_id=%s", user_id)
        raise


@app.get("/api/visits/{visit_id}")
def visit_detail(
    visit_id: str,
    sk: str = Query(...),
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
):
    user_id = creds.decoded["sub"]
    try:
        item = get_visit(user_id, sk)
    except Exception:
        logger.exception("get_visit_failed user_id=%s visit_id=%s", user_id, visit_id)
        raise
    if not item or item.get("visit_id") != visit_id:
        raise HTTPException(status_code=404, detail="Visit not found")
    return item


@app.post("/api/exports")
def export_visit(
    body: ExportRequest,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
):
    user_id = creds.decoded["sub"]
    logger.info(
        "export_start user_id=%s visit_sk=%s format=%s",
        user_id,
        body.visit_sk,
        body.format,
    )
    try:
        item = get_visit(user_id, body.visit_sk)
        if not item:
            raise HTTPException(status_code=404, detail="Visit not found")
        result = create_export(
            user_id=user_id,
            visit_id=item["visit_id"],
            patient_name=item["patient_name"],
            summary=item["summary"],
            fmt=body.format,
        )
        logger.info(
            "export_ok user_id=%s visit_id=%s format=%s key=%s",
            user_id,
            item["visit_id"],
            result.get("format"),
            result.get("key"),
        )
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning(
            "export_bad_request user_id=%s visit_sk=%s format=%s error=%s",
            user_id,
            body.visit_sk,
            body.format,
            exc,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "export_failed user_id=%s visit_sk=%s format=%s error_type=%s",
            user_id,
            body.visit_sk,
            body.format,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Export failed ({type(exc).__name__}). Check CloudWatch for details.",
        ) from exc


@app.post("/api/consultation")
def consultation_summary(
    visit: VisitRequest,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
):
    user_id = creds.decoded["sub"]
    logger.info(
        "consultation_start user_id=%s patient=%s date=%s notes_len=%s",
        user_id,
        visit.patient_name,
        visit.date_of_visit,
        len(visit.notes),
    )

    try:
        rate = check_and_increment(user_id)
    except RateLimitExceeded as exc:
        logger.warning(
            "rate_limit_exceeded user_id=%s limit=%s used=%s",
            user_id,
            exc.limit,
            exc.current,
        )
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Daily generation limit reached",
                "limit": exc.limit,
                "used": exc.current,
            },
        ) from exc
    except Exception:
        logger.exception("rate_limit_check_failed user_id=%s", user_id)
        rate = {"limit": 0, "used": 0, "remaining": 0}

    client = OpenAI()
    prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt_for(visit)},
    ]

    try:
        stream = client.chat.completions.create(
            model=MODEL_NAME,
            messages=prompt,
            stream=True,
            stream_options={"include_usage": True},
        )
    except Exception:
        logger.exception(
            "openai_stream_create_failed user_id=%s model=%s",
            user_id,
            MODEL_NAME,
        )
        raise HTTPException(status_code=502, detail="Model provider unavailable") from None

    def event_stream():
        buffer_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0

        yield _sse(
            json.dumps(
                {
                    "model": MODEL_NAME,
                    "prompt_version": PROMPT_VERSION,
                    "rate_limit": rate,
                }
            ),
            event="meta",
        )

        try:
            for chunk in stream:
                if getattr(chunk, "usage", None):
                    input_tokens = chunk.usage.prompt_tokens or 0
                    output_tokens = chunk.usage.completion_tokens or 0

                if not chunk.choices:
                    continue

                text = chunk.choices[0].delta.content
                if not text:
                    continue

                buffer_parts.append(text)
                lines = text.split("\n")
                for line in lines[:-1]:
                    yield _sse(line)
                    yield _sse("  ")
                yield _sse(lines[-1])

            summary = "".join(buffer_parts)
            saved = create_visit(
                user_id=user_id,
                patient_name=visit.patient_name,
                date_of_visit=visit.date_of_visit,
                notes=visit.notes,
                summary=summary,
                model=MODEL_NAME,
                prompt_version=PROMPT_VERSION,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            usage = increment_usage(
                user_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

            yield _sse(
                json.dumps(
                    {
                        "visit_id": saved["visit_id"],
                        "sk": saved["sk"],
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "model": MODEL_NAME,
                        "prompt_version": PROMPT_VERSION,
                        "usage_today": usage,
                    }
                ),
                event="done",
            )
            logger.info(
                "consultation_complete user_id=%s visit_id=%s model=%s prompt_version=%s in=%s out=%s",
                user_id,
                saved["visit_id"],
                MODEL_NAME,
                PROMPT_VERSION,
                input_tokens,
                output_tokens,
            )
        except Exception as exc:
            logger.exception(
                "consultation_failed user_id=%s error_type=%s",
                user_id,
                type(exc).__name__,
            )
            yield _sse(
                json.dumps({"message": "Generation failed. Please try again."}),
                event="error",
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


static_path = Path("static")


def _resolve_static(path: str) -> Path | None:
    cleaned = path.strip("/")
    if not cleaned:
        candidate = static_path / "index.html"
        return candidate if candidate.is_file() else None

    candidates = [
        static_path / cleaned,
        static_path / f"{cleaned}.html",
        static_path / cleaned / "index.html",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


if static_path.exists():
    next_assets = static_path / "_next"
    if next_assets.is_dir():
        app.mount("/_next", StaticFiles(directory=str(next_assets)), name="next_assets")

    @app.get("/")
    async def serve_root():
        return FileResponse(static_path / "index.html")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="Not found")

        resolved = _resolve_static(full_path)
        if resolved:
            return FileResponse(resolved)

        not_found = static_path / "404.html"
        if not_found.is_file():
            return FileResponse(not_found, status_code=404)
        raise HTTPException(status_code=404, detail="Not found")
