from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

import fitz


SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class DocumentError(ValueError):
    pass


@dataclass(slots=True)
class ImagePayload:
    data: bytes
    mime_type: str
    label: str

    @property
    def base64_data(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    @property
    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.base64_data}"


@dataclass(slots=True)
class SlideSource:
    page_number: int
    text: str
    preview: ImagePayload
    image_count: int = 0


@dataclass(slots=True)
class ExtractedDocument:
    filename: str
    mime_type: str
    slides: list[SlideSource] = field(default_factory=list)
    total_pages: int = 1
    discovered_images: int = 0
    truncated: bool = False
    extraction_mode: str = "page_vision"

    @property
    def text(self) -> str:
        return "\n\n".join(
            f"[الصفحة {slide.page_number}]\n{slide.text}" for slide in self.slides if slide.text
        )


class DocumentExtractor:
    def __init__(self, max_text_chars: int, max_pages: int) -> None:
        self.max_text_chars = max_text_chars
        self.max_pages = max_pages

    def extract(self, filename: str, content: bytes, declared_mime: str | None) -> ExtractedDocument:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise DocumentError("نوع الملف غير مدعوم. استخدم PDF أو PNG أو JPG أو WEBP.")
        if not content:
            raise DocumentError("الملف فارغ.")

        if suffix == ".pdf":
            return self._extract_pdf(filename, content)
        return self._extract_image(filename, content, suffix, declared_mime)

    def _extract_image(
        self,
        filename: str,
        content: bytes,
        suffix: str,
        declared_mime: str | None,
    ) -> ExtractedDocument:
        try:
            image = fitz.open(stream=content, filetype=suffix.lstrip("."))
            image.close()
        except Exception as exc:
            raise DocumentError("تعذر قراءة الصورة. تأكد أن الملف غير تالف.") from exc

        mime_type = IMAGE_MIME_TYPES.get(suffix, declared_mime or "image/png")
        preview = ImagePayload(content, mime_type, "السلايد 1")
        return ExtractedDocument(
            filename=filename,
            mime_type=mime_type,
            slides=[SlideSource(page_number=1, text="", preview=preview, image_count=1)],
            total_pages=1,
            discovered_images=1,
            extraction_mode="single_image",
        )

    def _extract_pdf(self, filename: str, content: bytes) -> ExtractedDocument:
        try:
            document = fitz.open(stream=content, filetype="pdf")
        except Exception as exc:
            raise DocumentError("تعذر فتح ملف PDF. تأكد أن الملف غير تالف.") from exc

        try:
            if document.needs_pass:
                raise DocumentError("ملفات PDF المحمية بكلمة مرور غير مدعومة حالياً.")
            if len(document) == 0:
                raise DocumentError("ملف PDF لا يحتوي على صفحات.")

            slide_count = min(len(document), self.max_pages)
            remaining_text = self.max_text_chars
            slides: list[SlideSource] = []
            discovered_images = 0
            truncated = len(document) > self.max_pages

            for page_index in range(slide_count):
                page = document[page_index]
                raw_text = page.get_text("text").strip()
                selected_text = raw_text[:remaining_text] if remaining_text > 0 else ""
                remaining_text -= len(selected_text)
                if len(selected_text) < len(raw_text):
                    truncated = True

                image_count = len(page.get_images(full=True))
                discovered_images += image_count
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False)
                preview = ImagePayload(
                    pixmap.tobytes("jpeg", jpg_quality=74),
                    "image/jpeg",
                    f"السلايد {page_index + 1}",
                )
                slides.append(
                    SlideSource(
                        page_number=page_index + 1,
                        text=selected_text,
                        preview=preview,
                        image_count=image_count,
                    )
                )

            has_text = any(slide.text for slide in slides)
            mode = "page_text_and_vision" if has_text else "page_vision"
            return ExtractedDocument(
                filename=filename,
                mime_type="application/pdf",
                slides=slides,
                total_pages=len(document),
                discovered_images=discovered_images,
                truncated=truncated,
                extraction_mode=mode,
            )
        finally:
            document.close()
