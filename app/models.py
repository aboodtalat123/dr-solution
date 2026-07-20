from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ProviderName = Literal["gemini", "claude", "deepseek"]
AnalysisDepth = Literal["focused", "balanced", "deep"]
ContentKind = Literal["auto", "lecture", "research", "book", "university_document"]
QuestionType = Literal["multiple_choice", "true_false", "short_answer", "essay"]
QuestionDifficulty = Literal["easy", "mixed", "challenging"]


class QuestionPreferences(BaseModel):
    enabled: bool = True
    types: list[QuestionType] = Field(default_factory=lambda: ["multiple_choice", "true_false"])
    count: int = Field(default=8, ge=1, le=20)
    difficulty: QuestionDifficulty = "mixed"


class GlossaryItem(BaseModel):
    term: str
    meaning: str


class StudyQuestion(BaseModel):
    type: QuestionType = "multiple_choice"
    difficulty: str = "متوسط"
    question: str = ""
    options: list[str] = Field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""


class SlideAnalysis(BaseModel):
    page_number: int
    title: str = "سلايد بلا عنوان"
    original_text: str = ""
    translation: str = ""
    explanation: str = ""
    image_description: str = ""
    content_analysis: str = ""
    key_points: list[str] = Field(default_factory=list)
    slide_summary: str = ""
    preview_data_url: str = ""


class ChapterAnalysis(BaseModel):
    chapter_title: str = "شابتر بلا عنوان"
    source_language: str = "غير محددة"
    chapter_overview: str = ""
    learning_objectives: list[str] = Field(default_factory=list)
    slides: list[SlideAnalysis] = Field(default_factory=list)
    chapter_summary: str = ""
    glossary: list[GlossaryItem] = Field(default_factory=list)
    questions: list[StudyQuestion] = Field(default_factory=list)


class DocumentStats(BaseModel):
    pages: int = 1
    analyzed_pages: int = 1
    characters: int = 0
    images: int = 0
    truncated: bool = False
    extraction_mode: str


class AnalysisResponse(BaseModel):
    id: str
    provider: ProviderName
    model: str
    filename: str
    mime_type: str
    target_language: str
    content_kind: ContentKind
    created_at: datetime
    stats: DocumentStats
    preferences: QuestionPreferences
    result: ChapterAnalysis


class ProviderInfo(BaseModel):
    id: ProviderName
    label: str
    model: str
    configured: bool
    supports_vision: bool
    free_tier: bool = False
    accepts_user_key: bool = True
    requires_user_key: bool = False
    key_url: str = ""


class VideoSegment(BaseModel):
    index: int
    start_sec: float
    end_sec: float
    transcript_text: str


class VideoTechnicalTerm(BaseModel):
    term: str
    arabic_equivalent: str = ""
    explanation: str = ""


class VideoSegmentAnalysis(BaseModel):
    index: int
    start_sec: float
    end_sec: float
    title: str = ""
    arabic_explanation: str = ""
    translation: str = ""
    key_points: list[str] = Field(default_factory=list)
    technical_terms: list[VideoTechnicalTerm] = Field(default_factory=list)
    segment_summary: str = ""
    frame_data_url: str = ""


class VideoAnalysisResult(BaseModel):
    video_title: str = ""
    duration_sec: float = 0
    segments: list[VideoSegmentAnalysis] = Field(default_factory=list)
    overall_summary: str = ""
    learning_objectives: list[str] = Field(default_factory=list)
    glossary: list[VideoTechnicalTerm] = Field(default_factory=list)


class VideoAnalyzeRequest(BaseModel):
    url: str
    start: int | None = None
    end: int | None = None
    api_key: str = ""
    provider: str = "gemini"
    model: str = ""


class HealthResponse(BaseModel):
    status: str
    version: str
    providers_ready: int
