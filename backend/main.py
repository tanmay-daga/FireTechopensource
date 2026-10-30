"""
main.py - FastAPI entry point for the Bug Buster backend.

Endpoints (the contract the frontend relies on - do not rename):
    GET  /health        -> {"status", "ollama", "model", "model_available"}
    POST /analyze-bug   -> multipart/form-data: image, repo_path, issue_hint (optional)
                           returns {"culprit_file", "root_cause", "git_diff", "fixed_code", ...}

This file wires everything together: settings from the environment, CORS,
upload checks, then scanner -> Gemma (screenshot) -> file selection ->
Gemma (code) -> patch validation. It never modifies the user's repository.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gemma_engine import EngineError, GemmaEngine
from patch_validator import validate_patch
from scanner import (
    ScanError,
    build_code_context,
    extract_keywords,
    resolve_repo_path,
    scan_repository,
    select_relevant_files,
)

load_dotenv(Path(__file__).resolve().parent / ".env")

_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=_level if _level in {"DEBUG", "INFO", "WARNING", "ERROR"} else "INFO",
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bugbuster")


# --------------------------------------------------------------------------
# Settings (read once, validated, never contain secrets)
# --------------------------------------------------------------------------
def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("Ignoring invalid %s; using default %s", name, default)
        return default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class Settings:
    ollama_host: str
    ollama_model: str
    max_upload_bytes: int
    max_files: int
    max_file_bytes: int
    max_total_source_bytes: int
    max_prompt_source_chars: int
    max_selected_files: int
    allowed_origins: tuple
    allowed_repo_roots: tuple
    request_timeout_s: int
    ollama_timeout_s: int
    num_ctx: int

    @classmethod
    def from_env(cls) -> "Settings":
        host = (os.getenv("OLLAMA_HOST") or "http://localhost:11434").strip().rstrip("/")
        if not re.match(r"^https?://", host):
            host = "http://" + host
        parsed = urlparse(host)
        if not parsed.hostname:
            logger.warning("OLLAMA_HOST is invalid; using http://localhost:11434")
            host, parsed = "http://localhost:11434", urlparse("http://localhost:11434")
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}:
            logger.warning("OLLAMA_HOST is not this machine: screenshots and code will leave this computer.")

        model = (os.getenv("OLLAMA_MODEL") or "gemma3:4b").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:/\-]{1,100}", model):
            logger.warning("OLLAMA_MODEL looks invalid; using gemma3:4b")
            model = "gemma3:4b"

        origins = []
        for item in (os.getenv("ALLOWED_ORIGINS") or "").split(","):
            item = item.strip().rstrip("/")
            if not item:
                continue
            if item == "*":
                logger.warning("ALLOWED_ORIGINS='*' is ignored: list exact origins instead.")
                continue
            if not re.match(r"^https?://", item):
                logger.warning("Ignoring invalid origin in ALLOWED_ORIGINS: %s", item[:60])
                continue
            origins.append(item)

        roots = []
        for item in (os.getenv("ALLOWED_REPO_ROOTS") or "").split(","):
            item = item.strip()
            if not item:
                continue
            try:
                roots.append(Path(item).expanduser().resolve(strict=True))
            except (OSError, RuntimeError, ValueError):
                logger.warning("Ignoring ALLOWED_REPO_ROOTS entry that does not exist: %s", item[:80])

        return cls(
            ollama_host=host,
            ollama_model=model,
            max_upload_bytes=_env_int("MAX_UPLOAD_MB", 10, 1, 50) * 1024 * 1024,
            max_files=_env_int("MAX_FILES", 100, 1, 2000),
            max_file_bytes=_env_int("MAX_FILE_SIZE_KB", 200, 1, 5000) * 1024,
            max_total_source_bytes=_env_int("MAX_TOTAL_SOURCE_KB", 500, 10, 20000) * 1024,
            max_prompt_source_chars=_env_int("MAX_PROMPT_SOURCE_KB", 40, 4, 400) * 1024,
            max_selected_files=_env_int("MAX_SELECTED_FILES", 8, 1, 30),
            allowed_origins=tuple(origins),
            allowed_repo_roots=tuple(roots),
            request_timeout_s=_env_int("REQUEST_TIMEOUT_S", 540, 30, 3600),
            ollama_timeout_s=_env_int("OLLAMA_TIMEOUT_S", 180, 10, 1800),
            num_ctx=_env_int("OLLAMA_NUM_CTX", 16384, 2048, 131072),
        )


settings = Settings.from_env()


# --------------------------------------------------------------------------
# Errors -> consistent JSON: {"detail": "...", "error": "code"}
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status_code: int, message: str, code: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code


async def _handle_known_error(_request: Request, exc) -> JSONResponse:
    return JSONResponse({"detail": exc.message, "error": exc.code}, status_code=exc.status_code)


# --------------------------------------------------------------------------
# Response models
# --------------------------------------------------------------------------
class AnalysisDetails(BaseModel):
    """Extra information for the UI. The frontend may ignore all of this."""

    confidence: str
    culprit_lines: Optional[str] = None
    evidence: list[str] = Field(default_factory=list)
    guesses: list[str] = Field(default_factory=list)
    screenshot_analysis: str = ""
    files_analyzed: list[str] = Field(default_factory=list)
    files_truncated: list[str] = Field(default_factory=list)
    file_selection: str = ""
    scan_truncated: bool = False
    patch_verified: bool = False
    patch_warnings: list[str] = Field(default_factory=list)
    patch_errors: list[str] = Field(default_factory=list)
    model: str = ""
    elapsed_seconds: float = 0.0


class AnalyzeBugResponse(BaseModel):
    culprit_file: str
    root_cause: str
    git_diff: str
    fixed_code: str
    analysis: AnalysisDetails


# --------------------------------------------------------------------------
# App, middleware
# --------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = GemmaEngine(
        settings.ollama_host, settings.ollama_model, settings.ollama_timeout_s, settings.num_ctx
    )
    app.state.gate = asyncio.Semaphore(1)  # one analysis at a time: a local model is the bottleneck
    logger.info("Bug Buster backend ready (model=%s)", settings.ollama_model)
    yield


app = FastAPI(title="Bug Buster Backend", version="1.0.0", lifespan=lifespan)

for _cls in (ApiError, ScanError, EngineError):
    app.add_exception_handler(_cls, _handle_known_error)


@app.middleware("http")
async def reject_oversized_uploads(request: Request, call_next):
    """Cheap early check on Content-Length, before the body is parsed."""
    if request.method == "POST" and request.url.path == "/analyze-bug":
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > settings.max_upload_bytes + 1_048_576:
            return JSONResponse(
                {"detail": f"Upload too large (limit {settings.max_upload_bytes // (1024 * 1024)} MB).",
                 "error": "upload_too_large"},
                status_code=413,
            )
    return await call_next(request)


# Added AFTER the middleware above so CORS headers are also present on its responses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# --------------------------------------------------------------------------
# Upload helpers
# --------------------------------------------------------------------------
_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _sniff_image(data: bytes) -> Optional[str]:
    """Identify the image from its first bytes; the client-declared type is not trusted."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def _read_image(upload: UploadFile) -> bytes:
    declared = (upload.content_type or "").lower()
    if declared and declared not in _ALLOWED_IMAGE_TYPES and declared != "application/octet-stream":
        raise ApiError(415, "Unsupported image type. Upload a PNG, JPEG or WebP screenshot.", "unsupported_image")
    chunks, total = [], 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_upload_bytes:
            raise ApiError(
                413,
                f"Image too large (limit {settings.max_upload_bytes // (1024 * 1024)} MB).",
                "upload_too_large",
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise ApiError(400, "The uploaded image is empty.", "empty_image")
    if _sniff_image(data) is None:
        raise ApiError(415, "The file is not a valid PNG, JPEG or WebP image.", "unsupported_image")
    return data


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/health")
async def health(request: Request):
    info = await request.app.state.engine.health()
    ok = info["ollama"] == "connected" and info["model_available"]
    body = {
        "status": "ok" if ok else "degraded",
        "ollama": info["ollama"],
        "model": settings.ollama_model,
        "model_available": info["model_available"],
    }
    if info["ollama"] != "connected":
        body["detail"] = "Ollama is not reachable. Start it with 'ollama serve'."
    elif not info["model_available"]:
        body["detail"] = f"Model not installed. Run: ollama pull {settings.ollama_model}"
    return JSONResponse(body, status_code=200 if ok else 503)


@app.post("/analyze-bug", response_model=AnalyzeBugResponse)
async def analyze_bug(
    request: Request,
    image: UploadFile = File(...),
    repo_path: str = Form(...),
    issue_hint: Optional[str] = Form(None),
):
    """Analyse a screenshot + local repository and return a suggested patch (never applied)."""
    started = time.monotonic()
    hint = " ".join((issue_hint or "").split())[:1000]
    try:
        image_bytes = await _read_image(image)
        async with request.app.state.gate:
            return await asyncio.wait_for(
                _analyze(request.app.state.engine, image_bytes, repo_path, hint, started),
                timeout=settings.request_timeout_s,
            )
    except (ApiError, ScanError, EngineError):
        raise
    except (asyncio.TimeoutError, TimeoutError):
        raise ApiError(504, "The analysis took too long and was stopped. Try again with a smaller repository.", "request_timeout")
    except Exception:
        logger.exception("Unhandled error in /analyze-bug")
        raise ApiError(500, "Unexpected internal error. Check the backend logs.", "internal_error")
    finally:
        await image.close()


async def _analyze(engine: GemmaEngine, image_bytes: bytes, repo_path: str, hint: str, started: float):
    root = await run_in_threadpool(resolve_repo_path, repo_path, settings.allowed_repo_roots)
    scan = await run_in_threadpool(
        scan_repository, root, settings.max_files, settings.max_file_bytes, settings.max_total_source_bytes
    )
    if not scan.files:
        raise ApiError(
            422,
            "No supported source files (.py .js .jsx .ts .tsx .html .css) were found in that repository.",
            "no_source_files",
        )
    logger.info("Scanned %d files from '%s'", len(scan.files), root.name)

    # Stage 1: what does the screenshot show?
    screenshot_analysis = await engine.describe_screenshot(image_bytes, hint)

    # Smart filtering: choose the files most related to what was seen.
    phrases, tokens = extract_keywords(screenshot_analysis, hint)
    selection = await run_in_threadpool(
        select_relevant_files, scan.files, phrases, tokens, settings.max_selected_files
    )
    code_context, included, truncated_files = build_code_context(
        selection.files, settings.max_prompt_source_chars
    )

    # Stage 2: find the culprit in the code.
    result = await engine.analyze_code(
        screenshot_analysis=screenshot_analysis,
        issue_hint=hint,
        tree=scan.tree,
        code_context=code_context,
        known_paths=included,
    )
    answer = result.answer

    details = AnalysisDetails(
        confidence="insufficient" if result.insufficient else answer.confidence,
        culprit_lines=result.culprit_lines,
        evidence=answer.evidence,
        guesses=answer.guesses,
        screenshot_analysis=screenshot_analysis,
        files_analyzed=included,
        files_truncated=truncated_files,
        file_selection=selection.mode,
        scan_truncated=scan.truncated,
        patch_warnings=list(result.warnings),
        model=settings.ollama_model,
    )

    if result.insufficient:
        details.elapsed_seconds = round(time.monotonic() - started, 1)
        return AnalyzeBugResponse(
            culprit_file="Unknown - insufficient evidence",
            root_cause=answer.root_cause.strip()
            or "Bug Buster could not find enough evidence in the scanned files to say which file causes this bug. "
            "Try adding an issue description or a clearer screenshot.",
            git_diff="",
            fixed_code="",
            analysis=details,
        )

    report = await run_in_threadpool(validate_patch, answer.git_diff, root)
    details.patch_verified = report.verified
    details.patch_warnings += report.warnings
    details.patch_errors = report.errors
    details.elapsed_seconds = round(time.monotonic() - started, 1)

    return AnalyzeBugResponse(
        culprit_file=result.culprit_path or "",
        root_cause=answer.root_cause.strip(),
        git_diff=report.patch if report.valid else "",
        fixed_code=answer.fixed_code,
        analysis=details,
    )


if __name__ == "__main__":  # optional: `python main.py` instead of the uvicorn command
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
