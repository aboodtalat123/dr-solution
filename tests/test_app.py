from dataclasses import replace

import fitz
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.models import QuestionPreferences, SlideAnalysis, StudyQuestion
from app.services.documents import DocumentExtractor


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "3.1.0"
    assert response.headers["cache-control"] == "no-store"


def test_home_serves_chapter_workspace() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Dr. Solution." in response.text
    assert "حوّل ملفك الأكاديمي إلى شرح متكامل" in response.text
    assert "تنزيل HTML" in response.text


def test_providers_expose_bring_your_own_key_links() -> None:
    response = client.get("/api/providers")

    assert response.status_code == 200
    providers = {provider["id"]: provider for provider in response.json()}
    assert providers["gemini"]["accepts_user_key"] is True
    assert providers["gemini"]["free_tier"] is True
    assert providers["gemini"]["model"] == "gemini-3.1-flash-lite"
    assert providers["gemini"]["key_url"] == "https://aistudio.google.com/api-keys"
    assert providers["deepseek"]["accepts_user_key"] is True
    assert providers["deepseek"]["free_tier"] is True
    assert providers["deepseek"]["key_url"] == "https://platform.deepseek.com/api_keys"


def test_public_mode_requires_a_user_api_key() -> None:
    public_settings = replace(get_settings(), require_user_api_key=True)
    app.dependency_overrides[get_settings] = lambda: public_settings
    try:
        response = client.post(
            "/api/analyze",
            files={"file": ("sample.pdf", b"not-read-without-a-key", "application/pdf")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "مفتاح المحرك" in response.json()["detail"]


def test_pdf_extraction_creates_one_visual_slide_per_page() -> None:
    pdf = fitz.open()
    for page_number in range(1, 4):
        page = pdf.new_page()
        page.insert_textbox(
            fitz.Rect(72, 72, 500, 700),
            f"Page {page_number}. A clear chapter slide for extraction. " * 8,
        )
    payload = pdf.tobytes()
    pdf.close()

    result = DocumentExtractor(max_text_chars=10_000, max_pages=10).extract(
        "sample.pdf",
        payload,
        "application/pdf",
    )

    assert result.total_pages == 3
    assert len(result.slides) == 3
    assert "clear chapter slide" in result.slides[0].text
    assert result.slides[0].preview.mime_type == "image/jpeg"
    assert result.slides[0].preview.data_url.startswith("data:image/jpeg;base64,")
    assert result.extraction_mode == "page_text_and_vision"


def test_pdf_extraction_respects_page_limit() -> None:
    pdf = fitz.open()
    for _ in range(4):
        pdf.new_page()
    payload = pdf.tobytes()
    pdf.close()

    result = DocumentExtractor(max_text_chars=2_000, max_pages=2).extract(
        "limited.pdf",
        payload,
        "application/pdf",
    )

    assert result.total_pages == 4
    assert len(result.slides) == 2
    assert result.truncated is True


def test_question_models_support_all_interactive_types() -> None:
    preferences = QuestionPreferences(
        types=["multiple_choice", "true_false", "short_answer", "essay"],
        count=12,
        difficulty="challenging",
    )
    question = StudyQuestion(
        type="multiple_choice",
        question="What is the key idea?",
        options=["A", "B", "C", "D"],
        correct_answer="A",
    )
    slide = SlideAnalysis(page_number=1, title="Introduction")

    assert preferences.count == 12
    assert len(preferences.types) == 4
    assert question.correct_answer == "A"
    assert slide.page_number == 1


def test_rejects_unsupported_extension() -> None:
    extractor = DocumentExtractor(max_text_chars=2_000, max_pages=3)

    try:
        extractor.extract("notes.txt", b"hello", "text/plain")
    except ValueError as exc:
        assert "غير مدعوم" in str(exc)
    else:
        raise AssertionError("unsupported file should be rejected")
