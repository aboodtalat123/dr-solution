from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Annotated, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.models import (
    AnalysisDepth,
    AnalysisResponse,
    ContentKind,
    DocumentStats,
    HealthResponse,
    ProviderInfo,
    ProviderName,
    QuestionPreferences,
)
from app.services.documents import DocumentError, DocumentExtractor
from app.services.providers import LANGUAGES, ProviderError, get_provider, get_provider_chat
from app.models import VideoAnalyzeRequest
from app.services.video import is_youtube_url, process_video, process_video_deep


class ChatMessage(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    question: str
    page_context: str = ""
    slide_number: str = ""
    api_key: str = ""
    provider: str = "gemini"
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    answer: str
    sources: list = []


router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    ready = sum(settings.provider_is_configured(name) for name in ("gemini", "claude", "deepseek"))
    return HealthResponse(status="ok", version=settings.app_version, providers_ready=ready)


@router.get("/providers", response_model=list[ProviderInfo])
async def providers(settings: Annotated[Settings, Depends(get_settings)]) -> list[ProviderInfo]:
    return [
        ProviderInfo(
            id="gemini",
            label="Gemini Free",
            model=settings.gemini_model,
            configured=bool(settings.gemini_api_key),
            supports_vision=True,
            free_tier=True,
            requires_user_key=settings.require_user_api_key,
            key_url="https://aistudio.google.com/api-keys",
        ),
        ProviderInfo(
            id="claude",
            label="Claude",
            model=settings.anthropic_model,
            configured=bool(settings.anthropic_api_key),
            supports_vision=True,
            free_tier=False,
            requires_user_key=settings.require_user_api_key,
        ),
        ProviderInfo(
            id="deepseek",
            label="DeepSeek Chat",
            model=settings.deepseek_model,
            configured=bool(settings.deepseek_api_key),
            supports_vision=False,
            free_tier=False,
            accepts_user_key=True,
            requires_user_key=settings.require_user_api_key,
            key_url="https://platform.deepseek.com/api_keys",
        ),
    ]


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_document(
    file: Annotated[UploadFile, File(description="PDF or image")],
    provider: Annotated[ProviderName, Form()] = "gemini",
    target_language: Annotated[str, Form()] = "ar",
    depth: Annotated[AnalysisDepth, Form()] = "balanced",
    content_kind: Annotated[ContentKind, Form()] = "auto",
    api_key: Annotated[str, Form()] = "",
    questions_enabled: Annotated[bool, Form()] = True,
    question_types: Annotated[str, Form()] = "multiple_choice,true_false",
    question_count: Annotated[int, Form()] = 8,
    question_difficulty: Annotated[str, Form()] = "mixed",
    settings: Annotated[Settings, Depends(get_settings)] = None,
) -> AnalysisResponse:
    if target_language not in LANGUAGES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "لغة الإخراج غير مدعومة.")

    request_api_key = api_key.strip()
    if len(request_api_key) > 256:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "صيغة مفتاح API غير صالحة.")
    if settings.require_user_api_key and not request_api_key:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "أضف مفتاح المحرك الخاص بك لإكمال التحليل.",
        )

    filename = (file.filename or "document").strip()
    content = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"حجم الملف أكبر من الحد المسموح ({settings.max_upload_mb} MB).",
        )

    allowed_question_types = {"multiple_choice", "true_false", "short_answer", "essay"}
    selected_question_types = [
        item.strip() for item in question_types.split(",") if item.strip() in allowed_question_types
    ]
    if questions_enabled and not selected_question_types:
        selected_question_types = ["multiple_choice"]
    difficulty = question_difficulty if question_difficulty in {"easy", "mixed", "challenging"} else "mixed"
    preferences = QuestionPreferences(
        enabled=questions_enabled,
        types=selected_question_types,
        count=max(1, min(question_count, 20)),
        difficulty=difficulty,
    )

    extractor = DocumentExtractor(settings.max_text_chars, settings.max_pages)
    try:
        document = extractor.extract(filename, content, file.content_type)
        selected_provider = get_provider(provider, settings, request_api_key or None)
        answer = await selected_provider.analyze(
            document,
            target_language,
            depth,
            preferences,
            content_kind,
        )
    except DocumentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return AnalysisResponse(
        id=uuid4().hex[:12],
        provider=provider,
        model=answer.model,
        filename=filename,
        mime_type=document.mime_type,
        target_language=target_language,
        content_kind=content_kind,
        created_at=datetime.now(timezone.utc),
        stats=DocumentStats(
            pages=document.total_pages,
            analyzed_pages=len(document.slides),
            characters=len(document.text),
            images=document.discovered_images,
            truncated=document.truncated,
            extraction_mode=document.extraction_mode,
        ),
        preferences=preferences,
        result=answer.content,
    )


@router.post("/analyze/stream")
async def analyze_document_stream(
    file: Annotated[UploadFile, File(description="PDF or image")],
    provider: Annotated[ProviderName, Form()] = "gemini",
    target_language: Annotated[str, Form()] = "ar",
    depth: Annotated[AnalysisDepth, Form()] = "balanced",
    content_kind: Annotated[ContentKind, Form()] = "auto",
    api_key: Annotated[str, Form()] = "",
    questions_enabled: Annotated[bool, Form()] = True,
    question_types: Annotated[str, Form()] = "multiple_choice,true_false",
    question_count: Annotated[int, Form()] = 8,
    question_difficulty: Annotated[str, Form()] = "mixed",
    settings: Annotated[Settings, Depends(get_settings)] = None,
):
    if target_language not in LANGUAGES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "لغة الإخراج غير مدعومة.")

    request_api_key = api_key.strip()
    if len(request_api_key) > 256:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "صيغة مفتاح API غير صالحة.")
    if settings.require_user_api_key and not request_api_key:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "أضف مفتاح المحرك الخاص بك لإكمال التحليل.",
        )

    filename = (file.filename or "document").strip()
    content = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"حجم الملف أكبر من الحد المسموح ({settings.max_upload_mb} MB).",
        )

    allowed_question_types = {"multiple_choice", "true_false", "short_answer", "essay"}
    selected_question_types = [
        item.strip() for item in question_types.split(",") if item.strip() in allowed_question_types
    ]
    if questions_enabled and not selected_question_types:
        selected_question_types = ["multiple_choice"]
    difficulty = question_difficulty if question_difficulty in {"easy", "mixed", "challenging"} else "mixed"
    preferences = QuestionPreferences(
        enabled=questions_enabled,
        types=selected_question_types,
        count=max(1, min(question_count, 20)),
        difficulty=difficulty,
    )

    extractor = DocumentExtractor(settings.max_text_chars, settings.max_pages)
    try:
        document = extractor.extract(filename, content, file.content_type)
    except DocumentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    selected_provider = get_provider(provider, settings, request_api_key or None)
    total = len(document.slides)
    progress_queue: asyncio.Queue = asyncio.Queue()

    def on_progress(done: int, pages: int) -> None:
        progress_queue.put_nowait({"type": "progress", "done": done, "total": pages})

    async def run_analysis() -> None:
        try:
            answer = await selected_provider.analyze(
                document,
                target_language,
                depth,
                preferences,
                content_kind,
                on_progress=on_progress,
            )
        except DocumentError as exc:
            progress_queue.put_nowait({"type": "error", "message": str(exc)})
            return
        except ProviderError as exc:
            progress_queue.put_nowait({"type": "error", "message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            progress_queue.put_nowait({"type": "error", "message": f"حدث خطأ غير متوقع: {exc}"})
            return
        response = AnalysisResponse(
            id=uuid4().hex[:12],
            provider=provider,
            model=answer.model,
            filename=filename,
            mime_type=document.mime_type,
            target_language=target_language,
            content_kind=content_kind,
            created_at=datetime.now(timezone.utc),
            stats=DocumentStats(
                pages=document.total_pages,
                analyzed_pages=len(document.slides),
                characters=len(document.text),
                images=document.discovered_images,
                truncated=document.truncated,
                extraction_mode=document.extraction_mode,
            ),
            preferences=preferences,
            result=answer.content,
        )
        progress_queue.put_nowait({"type": "done", "payload": response.model_dump(mode="json")})

    async def event_stream():
        yield (json.dumps({"type": "start", "total": total}, ensure_ascii=False) + "\n").encode("utf-8")
        task = asyncio.create_task(run_analysis())
        while True:
            item = await progress_queue.get()
            yield (json.dumps(item, ensure_ascii=False) + "\n").encode("utf-8")
            if item["type"] in ("done", "error"):
                break
        await task

    return StreamingResponse(event_stream(), media_type="application/x-ndjson; charset=utf-8")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatResponse:
    if not body.question.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "سؤال فارغ.")

    try:
        answer = await get_provider_chat(
            body.question,
            body.page_context,
            body.provider or "gemini",
            settings,
            api_key=body.api_key or None,
            history=[m.model_dump() for m in body.history],
            slide_number=body.slide_number or None,
        )
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return ChatResponse(answer=answer)


class VideoExtractRequest(BaseModel):
    url: str
    second: int = 12
    start: int | None = None
    end: int | None = None
    provider: str = "gemini"
    api_key: str = ""
    model: str = ""


@router.post("/extract-video-goals")
async def extract_video_goals(
    body: VideoExtractRequest,
    settings: Annotated[Settings, Depends(get_settings)],
):
    if not body.url.strip():
        raise HTTPException(422, "رابط الفيديو مطلوب")
    second = max(1, min(body.second, 300))
    try:
        result = await process_video(
            url=body.url.strip(),
            second=second,
            start=body.start,
            end=body.end,
            provider=body.provider.lower(),
            model=body.model,
            api_key=body.api_key.strip(),
            settings=settings,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return result


@router.post("/analyze-video")
async def analyze_video(
    body: VideoAnalyzeRequest,
    settings: Annotated[Settings, Depends(get_settings)],
):
    if not body.url.strip():
        raise HTTPException(422, "رابط الفيديو مطلوب")
    if not is_youtube_url(body.url):
        raise HTTPException(422, "أدخل رابط YouTube صالحاً يبدأ بـ https://")
    try:
        results = await process_video_deep(
            url=body.url.strip(),
            start=body.start,
            end=body.end,
            api_key=body.api_key.strip(),
            model=body.model,
            settings=settings,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return {"results": results, "total": len(results)}
