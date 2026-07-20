from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings


BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
settings = get_settings()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Document translation, explanation, and visual analysis API.",
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )

    if settings.allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    application.include_router(router)
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif request.url.path in ("/", "/about", "/privacy", "/robots.txt", "/sitemap.xml"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(413)
    async def payload_too_large(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=413, content={"detail": str(exc)})

    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/robots.txt", include_in_schema=False)
    async def robots() -> FileResponse:
        return FileResponse(STATIC_DIR / "robots.txt")

    @application.get("/google55b1a35237dc5a3c.html", include_in_schema=False)
    async def google_verify() -> FileResponse:
        return FileResponse(STATIC_DIR / "google55b1a35237dc5a3c.html")

    @application.get("/sitemap.xml", include_in_schema=False)
    async def sitemap() -> FileResponse:
        return FileResponse(STATIC_DIR / "sitemap.xml")

    @application.get("/about", include_in_schema=False)
    async def about() -> FileResponse:
        return FileResponse(STATIC_DIR / "about.html")

    @application.get("/privacy", include_in_schema=False)
    async def privacy() -> FileResponse:
        return FileResponse(STATIC_DIR / "privacy.html")

    @application.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "favicon.svg")

    return application


app = create_app()
