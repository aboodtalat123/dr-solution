from dataclasses import replace

import fitz
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.models import QuestionPreferences, SlideAnalysis, StudyQuestion
from app.services.documents import DocumentExtractor
from app.services import video as video_service


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "3.2.0"
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
    assert providers["deepseek"]["free_tier"] is False
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


def test_video_segments_follow_scene_boundaries_and_transcript() -> None:
    settings = replace(
        get_settings(),
        video_max_segments=8,
        video_max_segment_seconds=120,
    )
    transcript = [
        {"start": 2.0, "end": 8.0, "text": "Introduction"},
        {"start": 44.0, "end": 52.0, "text": "Second slide"},
        {"start": 85.0, "end": 95.0, "text": "Conclusion"},
    ]

    segments, mode = video_service.build_video_segments(
        transcript,
        scene_boundaries=[40.0, 80.0],
        duration=120.0,
        settings=settings,
    )

    assert mode == "scene_detection"
    assert [(segment["start"], segment["end"]) for segment in segments] == [
        (0.0, 40.0),
        (40.0, 80.0),
        (80.0, 120.0),
    ]
    assert [segment["text"] for segment in segments] == [
        "Introduction",
        "Second slide",
        "Conclusion",
    ]


def test_video_segments_limit_gemini_requests() -> None:
    settings = replace(
        get_settings(),
        video_max_segments=4,
        video_max_segment_seconds=60,
    )

    segments, mode = video_service.build_video_segments(
        transcript=[],
        scene_boundaries=[20.0, 40.0, 60.0, 80.0, 100.0, 120.0, 140.0],
        duration=160.0,
        settings=settings,
    )

    assert mode == "scene_detection"
    assert len(segments) == 4
    assert segments[0]["start"] == 0.0
    assert segments[-1]["end"] == 160.0


def test_whisper_transcription_is_lazy_and_timestamped(monkeypatch, tmp_path) -> None:
    class FakeSegment:
        start = 1.25
        end = 3.75
        text = "  شرح تجريبي  "

    class FakeWhisperModel:
        def transcribe(self, path, **options):
            assert path.endswith("sample.mp4")
            assert options["beam_size"] == 1
            assert options["vad_filter"] is True
            return iter([FakeSegment()]), object()

    monkeypatch.setattr(video_service, "_load_whisper_model", lambda *_: FakeWhisperModel())
    settings = replace(get_settings(), whisper_model="tiny", whisper_compute_type="int8")

    transcript = video_service.transcribe_with_whisper(tmp_path / "sample.mp4", settings)

    assert transcript == [{"start": 1.25, "end": 3.75, "text": "شرح تجريبي"}]


def test_youtube_url_validation() -> None:
    assert video_service.is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert video_service.is_youtube_url("https://youtu.be/dQw4w9WgXcQ")
    assert not video_service.is_youtube_url("http://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not video_service.is_youtube_url("https://example.com/video")
    assert not video_service.is_youtube_url("https://youtube.com.example.com/video")


def test_video_analysis_rejects_non_youtube_urls_before_processing() -> None:
    response = client.post(
        "/api/analyze-video",
        json={
            "url": "https://example.com/video",
            "api_key": "test-api-key-long-enough",
            "provider": "gemini",
        },
    )

    assert response.status_code == 422
    assert "YouTube" in response.json()["detail"]
