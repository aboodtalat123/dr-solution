from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.models import (
    AnalysisDepth,
    ChapterAnalysis,
    ContentKind,
    GlossaryItem,
    ProviderName,
    QuestionPreferences,
    SlideAnalysis,
    StudyQuestion,
    VideoSegment,
    VideoSegmentAnalysis,
    VideoTechnicalTerm,
)
from app.services.documents import ExtractedDocument, ImagePayload, SlideSource


LANGUAGES = {
    "ar": "العربية",
    "en": "الإنجليزية",
    "fr": "الفرنسية",
    "de": "الألمانية",
    "es": "الإسبانية",
    "tr": "التركية",
}

DEPTH_GUIDANCE = {
    "focused": "شرح مركز ومباشر يذكر الفكرة الأساسية من دون إطالة.",
    "balanced": "شرح دراسي متوازن يوضح الفكرة والمصطلحات والعلاقات المهمة.",
    "deep": "شرح عميق خطوة بخطوة مع سياق وأمثلة وروابط بين المفاهيم.",
}

QUESTION_TYPE_LABELS = {
    "multiple_choice": "اختيار من متعدد",
    "true_false": "صح أو خطأ",
    "short_answer": "إجابة قصيرة",
    "essay": "مقالي",
}

CONTENT_KIND_GUIDANCE = {
    "auto": "استنتج نوع المادة من محتواها واختر أسلوب الشرح الأكاديمي الأنسب.",
    "lecture": "هذه محاضرة أو شابتر؛ ركّز على تسلسل المفاهيم وما يحتاجه الطالب للامتحان.",
    "research": "هذا بحث علمي؛ وضّح سؤال البحث والمنهجية والنتائج والأدلة والقيود.",
    "book": "هذا كتاب أو فصل كتاب؛ تتبّع الأفكار والحجج والمفاهيم والأمثلة بترابط.",
    "university_document": "هذا مستند جامعي؛ وضّح المتطلبات والتعريفات والإجراءات والمواعيد من دون افتراضات.",
}


class ProviderError(RuntimeError):
    pass


class ProviderNotConfigured(ProviderError):
    pass


class SlideBatch(BaseModel):
    slides: list[SlideAnalysis] = Field(default_factory=list)


class ChapterSynthesis(BaseModel):
    chapter_title: str = "شابتر بلا عنوان"
    source_language: str = "غير محددة"
    chapter_overview: str = ""
    learning_objectives: list[str] = Field(default_factory=list)
    chapter_summary: str = ""
    glossary: list[GlossaryItem] = Field(default_factory=list)
    questions: list[StudyQuestion] = Field(default_factory=list)


@dataclass(slots=True)
class ProviderAnswer:
    model: str
    content: ChapterAnalysis


class AIProvider(ABC):
    name: ProviderName
    supports_vision: bool

    def __init__(self, settings: Settings, api_key: str | None = None) -> None:
        self.settings = settings
        self.api_key = (api_key or "").strip()

    async def analyze(
        self,
        document: ExtractedDocument,
        target_language: str,
        depth: AnalysisDepth,
        preferences: QuestionPreferences,
        content_kind: ContentKind,
        on_progress: "Callable[[int, int], None] | None" = None,
    ) -> ProviderAnswer:
        if not self.supports_vision and not document.text:
            raise ProviderError("هذا المحرك يحتاج نصاً قابلاً للنسخ. استخدم Gemini أو Claude للملفات المصوّرة.")

        batch_size = max(1, min(self.settings.analysis_batch_size, 2))
        batches = [document.slides[index : index + batch_size] for index in range(0, len(document.slides), batch_size)]
        total_slides = len(document.slides)
        semaphore = asyncio.Semaphore(2)

        async def analyze_batch(slides: list[SlideSource]) -> SlideBatch:
            async with semaphore:
                raw = await self._request_json(
                    self._slide_prompt(document.filename, slides, target_language, depth, content_kind),
                    [slide.preview for slide in slides] if self.supports_vision else [],
                )
            try:
                return SlideBatch.model_validate(raw)
            except ValidationError as exc:
                raise ProviderError("تعذر تنظيم شرح إحدى مجموعات السلايدات. أعد المحاولة.") from exc

        analyzed_batches: list[SlideBatch] = []
        done_slides = 0
        for coro in asyncio.as_completed(analyze_batch(batch) for batch in batches):
            batch_result = await coro
            analyzed_batches.append(batch_result)
            done_slides += len(batch_result.slides)
            if on_progress:
                on_progress(min(done_slides, total_slides), total_slides)
        if on_progress:
            on_progress(total_slides, total_slides)
        analyzed_by_page = {
            slide.page_number: slide
            for batch in analyzed_batches
            for slide in batch.slides
            if 1 <= slide.page_number <= document.total_pages
        }

        slides: list[SlideAnalysis] = []
        for source in document.slides:
            analysis = analyzed_by_page.get(source.page_number)
            if analysis is None:
                analysis = SlideAnalysis(
                    page_number=source.page_number,
                    title=f"السلايد {source.page_number}",
                    explanation=source.text or "تعذر توليد شرح هذه الصفحة.",
                    slide_summary=source.text[:320],
                )
            analysis.original_text = source.text
            analysis.preview_data_url = source.preview.data_url
            slides.append(analysis)

        synthesis_raw = await self._request_json(
            self._synthesis_prompt(
                document.filename,
                slides,
                target_language,
                preferences,
                content_kind,
            ),
            [],
        )
        try:
            synthesis = ChapterSynthesis.model_validate(synthesis_raw)
        except ValidationError as exc:
            raise ProviderError("تم شرح السلايدات لكن تعذر بناء خلاصة الشابتر. أعد المحاولة.") from exc

        allowed_types = set(preferences.types)
        questions = (
            [question for question in synthesis.questions if question.type in allowed_types][: preferences.count]
            if preferences.enabled
            else []
        )
        chapter = ChapterAnalysis(
            chapter_title=synthesis.chapter_title,
            source_language=synthesis.source_language,
            chapter_overview=synthesis.chapter_overview,
            learning_objectives=synthesis.learning_objectives,
            slides=slides,
            chapter_summary=synthesis.chapter_summary,
            glossary=synthesis.glossary,
            questions=questions,
        )
        return ProviderAnswer(self.model_name, chapter)

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def _request_json(self, prompt: str, images: list[ImagePayload]) -> dict:
        raise NotImplementedError

    @staticmethod
    def _slide_prompt(
        filename: str,
        slides: list[SlideSource],
        target_language: str,
        depth: AnalysisDepth,
        content_kind: ContentKind,
    ) -> str:
        language = LANGUAGES[target_language]
        pages = "\n\n".join(
            f"[SLIDE {slide.page_number}]\n{slide.text or 'لا يوجد نص قابل للاستخراج؛ اقرأ صورة الصفحة.'}"
            for slide in slides
        )
        page_numbers = ", ".join(str(slide.page_number) for slide in slides)
        return f"""
أنت مدرس جامعي ومحلل محتوى أكاديمي داخل Dr. Solution. اشرح صفحات الملف بترتيبها، واعتمد على النص وصورة كل صفحة معاً. لا تضف معلومات غير مؤكدة.

الملف: {filename}
أرقام السلايدات المطلوبة: {page_numbers}
لغة كل المخرجات: {language}
مستوى الشرح: {DEPTH_GUIDANCE[depth]}
نوع المادة وأسلوبها: {CONTENT_KIND_GUIDANCE[content_kind]}
الصور المرفقة مرتبة تماماً مثل أرقام السلايدات أعلاه.

أعد JSON فقط بهذا الشكل:
{{
  "slides": [
    {{
      "page_number": 1,
      "title": "عنوان واضح للسلايد",
      "translation": "ترجمة دقيقة وكاملة لنص السلايد إلى لغة المخرجات مع الحفاظ على المصطلحات والمعنى. MUST be one translated line per original slide line, each on its own line separated by a newline (\\n). If the slide has 4 lines, return exactly 4 translated lines. Do not merge into a paragraph.",
      "explanation": "شرح تعليمي موسع ومنظم للفكرة كأنك تشرحها لطالب في محاضرة. اشرح المصطلحات، العلاقات بين المفاهيم، الأسباب والنتائج، واربطها بسياق المادة. لا تترك فكرة غامضة دون توضيح. استشهد بأمثلة عند الحاجة.",
      "image_description": "وصف تفصيلي لكل عنصر بصري: الرسوم البيانية، الجداول، المخططات الانسيابية، الأشكال التوضيحية. اشرح ماذا يمثل كل جزء، العلاقات البصرية، الألوان إن كانت مهمة، وما الذي يستنتجه الطالب من هذا العنصر البصري. إن لم توجد عناصر بصرية مهمة فاكتب 'لا توجد عناصر بصرية مهمة'.",
      "content_analysis": "تحليل عميق للمحتوى: ما هي الفكرة المحورية للسلايد؟ كيف ترتبط بما قبلها وما بعدها؟ ما المصطلحات المفتاحية؟ ما التطبيقات أو الأمثلة العملية؟ ما الأخطاء الشائعة أو النقاط التي تحتاج انتباهاً خاصاً؟ اربط المفاهيم بعضها ببعض.",
      "key_points": ["نقطة رئيسية واحدة تحمل فكرة كاملة على الأقل 3-7 نقاط رئيسية تغطي كل جوانب السلايد"],
      "slide_summary": "خلاصة وافية من 4-6 جمل تلخص الفكرة الرئيسية للسلايد واهم النقاط التي يجب أن يتذكرها الطالب"
    }}
  ]
}}

قواعد:
- أعد عنصراً واحداً لكل رقم سلايد مطلوب، وبنفس الرقم والترتيب.
- لا تكرر الترجمة داخل الشرح.
- فسّر المخططات والجداول بصرياً، ولا تكتفِ بقول توجد صورة.
- اجعل كل حقل وافياً ومتكاملاً. الشرح يجب أن يكون كافياً لفهم الطالب للسلايد دون الحاجة لمصدر آخر.
- اكتب حقولاً فارغة فقط عندما يكون المحتوى غير موجود فعلاً.
- لا تضع Markdown أو أي نص خارج JSON.

النصوص المستخرجة:
{pages}
""".strip()

    @staticmethod
    def _synthesis_prompt(
        filename: str,
        slides: list[SlideAnalysis],
        target_language: str,
        preferences: QuestionPreferences,
        content_kind: ContentKind,
    ) -> str:
        language = LANGUAGES[target_language]
        slide_digest = "\n".join(
            f"{slide.page_number}. {slide.title}: {slide.slide_summary}" for slide in slides
        )
        if preferences.enabled:
            selected_types = ", ".join(QUESTION_TYPE_LABELS[item] for item in preferences.types)
            question_instruction = f"""
أنشئ {preferences.count} سؤالاً بالضبط، موزعة قدر الإمكان بين الأنواع: {selected_types}.
مستوى الصعوبة: {preferences.difficulty}.
استخدم قيم type الإنجليزية التالية فقط: {', '.join(preferences.types)}.
- multiple_choice: أربع خيارات، وضع نص الخيار الصحيح في correct_answer.
- true_false: options تكون ["صح", "خطأ"] والإجابة واحدة منهما.
- short_answer وessay: options قائمة فارغة، وضع نموذج الإجابة في correct_answer.
"""
        else:
            question_instruction = "لا تنشئ أسئلة وأعد questions كقائمة فارغة."

        return f"""
ابنِ خلاصة دراسية متكاملة للشابتر التالي اعتماداً فقط على ملخصات سلايداته.

الملف: {filename}
لغة المخرجات: {language}
نوع المادة وأسلوب التلخيص: {CONTENT_KIND_GUIDANCE[content_kind]}

أعد JSON فقط:
{{
  "chapter_title": "عنوان الشابتر",
  "source_language": "لغة المصدر",
  "chapter_overview": "صورة عامة مترابطة وشاملة عن موضوع الشابتر. اشرح السياق العام، الفكرة الرئيسية التي يقدمها الشابتر، كيف يبني المفاهيم، وأهمية هذا الشابتر في مجال الدراسة. فقرة متكاملة من 6-8 جمل.",
  "learning_objectives": ["هدف تعلم واضح وقابل للقياس يصف ماذا سيتعلم الطالب (3-6 أهداف)"],
  "chapter_summary": "خلاصة نهائية منظمة ومفيدة للمراجعة. أعد كتابة الأفكار الرئيسية للشابتر بشكل مترابط مع إبراز العلاقات بين المفاهيم، والتسلسل المنطقي للمادة. اذكر الاستنتاجات النهائية والتطبيقات. فقرتان إلى ثلاث فقرات تغطي كل المحتوى.",
  "glossary": [{{"term": "مصطلح", "meaning": "معناه المبسط مع شرح سياق استخدامه في المادة"}}],
  "questions": [
    {{
      "type": "multiple_choice",
      "difficulty": "متوسط",
      "question": "نص السؤال",
      "options": ["خيار 1", "خيار 2", "خيار 3", "خيار 4"],
      "correct_answer": "الإجابة الصحيحة أو النموذجية",
      "explanation": "لماذا هذه الإجابة صحيحة مع شرح مبسط يربطها بمفاهيم الشابتر"
    }}
  ]
}}

{question_instruction}
لا تضع Markdown أو نصاً خارج JSON.

ملخصات السلايدات:
{slide_digest}
""".strip()


class GeminiProvider(AIProvider):
    name: ProviderName = "gemini"
    supports_vision = True

    @property
    def model_name(self) -> str:
        return self.settings.gemini_model

    async def _request_json(self, prompt: str, images: list[ImagePayload]) -> dict:
        api_key = self.api_key or self.settings.gemini_api_key
        if not api_key:
            raise ProviderNotConfigured("مفتاح Gemini غير مضاف إلى إعدادات الخادم.")

        parts: list[dict] = [{"text": prompt}]
        parts.extend(
            {"inlineData": {"mimeType": image.mime_type, "data": image.base64_data}}
            for image in images
        )
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent"
        )
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.18,
                "responseMimeType": "application/json",
                "maxOutputTokens": 8192,
            },
        }
        headers = {"x-goog-api-key": api_key}
        response = await _post_with_retry(url, headers, payload, self.settings.request_timeout_seconds)
        _raise_for_provider_error(response, "Gemini")

        try:
            blocks = response.json()["candidates"][0]["content"]["parts"]
            text = "\n".join(block.get("text", "") for block in blocks)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("وصل رد غير مكتمل من Gemini. جرّب الملف مرة أخرى.") from exc
        return _parse_json(text)


class ClaudeProvider(AIProvider):
    name: ProviderName = "claude"
    supports_vision = True

    @property
    def model_name(self) -> str:
        return self.settings.anthropic_model

    async def _request_json(self, prompt: str, images: list[ImagePayload]) -> dict:
        api_key = self.api_key or self.settings.anthropic_api_key
        if not api_key:
            raise ProviderNotConfigured("مفتاح Claude غير مضاف إلى إعدادات الخادم.")

        content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.mime_type,
                    "data": image.base64_data,
                },
            }
            for image in images
        ]
        content.append({"type": "text", "text": prompt})
        payload = {
            "model": self.settings.anthropic_model,
            "max_tokens": 8192,
            "temperature": 0.18,
            "messages": [{"role": "user", "content": content}],
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        response = await _post_with_retry(
            "https://api.anthropic.com/v1/messages",
            headers,
            payload,
            self.settings.request_timeout_seconds,
        )
        _raise_for_provider_error(response, "Claude")
        try:
            blocks = response.json()["content"]
            text = "\n".join(block["text"] for block in blocks if block.get("type") == "text")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("وصل رد غير مكتمل من Claude. جرّب الملف مرة أخرى.") from exc
        return _parse_json(text)


class DeepSeekProvider(AIProvider):
    name: ProviderName = "deepseek"
    supports_vision = False

    @property
    def model_name(self) -> str:
        return self.settings.deepseek_model

    async def _request_json(self, prompt: str, images: list[ImagePayload]) -> dict:
        api_key = self.api_key or self.settings.deepseek_api_key
        if not api_key:
            raise ProviderNotConfigured("مفتاح DeepSeek غير مضاف إلى إعدادات الخادم.")
        payload = {
            "model": self.settings.deepseek_model,
            "temperature": 0.18,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "أعد JSON صالحاً فقط والتزم بالمخطط المطلوب."},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        response = await _post_with_retry(
            "https://api.deepseek.com/chat/completions",
            headers,
            payload,
            self.settings.request_timeout_seconds,
        )
        _raise_for_provider_error(response, "DeepSeek")
        try:
            text = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("وصل رد غير مكتمل من DeepSeek. جرّب الملف مرة أخرى.") from exc
        return _parse_json(text)


def get_provider(name: ProviderName, settings: Settings, api_key: str | None = None) -> AIProvider:
    providers: dict[ProviderName, type[AIProvider]] = {
        "gemini": GeminiProvider,
        "claude": ClaudeProvider,
        "deepseek": DeepSeekProvider,
    }
    return providers[name](settings, api_key)


async def get_provider_chat(
    question: str,
    page_context: str,
    provider_name: ProviderName,
    settings: Settings,
    api_key: str | None = None,
    history: list[dict] | None = None,
    slide_number: str | int | None = None,
) -> str:
    api_key = (api_key or "").strip() or {
        "gemini": settings.gemini_api_key,
        "deepseek": settings.deepseek_api_key,
    }.get(provider_name, "")
    if not api_key:
        raise ProviderError("مفتاح API غير مضاف.")

    history_text = ""
    if history:
        history_text = "\n".join(
            f"{'المستخدم' if m['role'] == 'user' else 'المساعد'}: {m['text']}"
            for m in history[-12:]
        )

    prompt = f"""أنت مساعد أكاديمي خبير اسمك Dr. Solution. لديك معرفة واسعة في جميع المجالات الأكاديمية والعامة، وتجيب عن أي سؤال من معرفتك الخاصة.

إذا كان السؤال عاماً (عن التاريخ، الجغرافيا، العلوم، أي موضوع خارج المادة الحالية)، أجب فوراً من معرفتك الخاصة دون الرجوع للسياق.

أما إذا كان السؤال عن السلايد أو المادة المرفوعة، استخدم السياق المرفق أدناه للإجابة بتعمق ودقة.

{"السؤال الحالي يخص السلايد رقم " + str(slide_number) + "." if slide_number else ""}
سياق الصفحة الحالية (هو محتوى السلايد المطلوب، استخدمه للإجابة عن أسئلة السلايد):
{page_context or "—"}

{"تاريخ المحادثة السابقة:\n" + history_text if history_text else ""}
السؤال: {question}

قواعد صارمة:
- للسؤال العام: أجب من معرفتك فوراً، لا تقل "غير متوفر في المادة".
- لسؤال السلايد: السؤال يخص السلايد رقم {str(slide_number) if slide_number else "الحالي"}، والسياق المرفق أعلاه هو محتواه. حلل هذا السياق بتعمق ولا تقل إنه غير متوفر.
- لا تختلق معلومات. إذا لم تكن متأكداً، قل ذلك بصراحة.
- أجب بالعربية الفصحى بوضوح وتنظيم.
- لا تضع أي Markdown."""
    url: str
    headers: dict
    payload: dict

    if provider_name == "gemini":
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent"
        )
        contents = []
        if history:
            for m in history[-10:]:
                role = "model" if m["role"] == "bot" else "user"
                contents.append({"role": role, "parts": [{"text": m["text"]}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        payload = {
            "contents": contents,
            "generationConfig": {"temperature": 0.35, "maxOutputTokens": 2048},
        }
        headers = {"x-goog-api-key": api_key}
        response = await _post_with_retry(url, headers, payload, settings.request_timeout_seconds)
        _raise_for_provider_error(response, "Gemini")
        try:
            blocks = response.json()["candidates"][0]["content"]["parts"]
            return "\n".join(block.get("text", "") for block in blocks)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("وصل رد غير مكتمل من Gemini.") from exc

    elif provider_name == "deepseek":
        url = "https://api.deepseek.com/chat/completions"
        messages = [{"role": "system", "content": "أنت مساعد أكاديمي خبير اسمك Dr. Solution. لك معرفة واسعة بكل المجالات. السؤال العام تجيب من معرفتك فوراً ولا تقل 'غير متوفر'. السؤال عن المادة تستخدم السياق المرفق. أجب بالعربية الفصحى."}]
        if history:
            for m in history[-10:]:
                role = "assistant" if m["role"] == "bot" else "user"
                messages.append({"role": role, "content": m["text"]})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": settings.deepseek_model,
            "temperature": 0.35,
            "messages": messages,
            "max_tokens": 2048,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        response = await _post_with_retry(url, headers, payload, settings.request_timeout_seconds)
        _raise_for_provider_error(response, "DeepSeek")
        try:
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("وصل رد غير مكتمل من DeepSeek.") from exc

    raise ProviderError(f"المحرك {provider_name} غير مدعوم للمساعد الذكي.")


VIDEO_SEGMENT_PROMPT = """
أنت مدرس جامعي ومحلل محتوى أكاديمي داخل Dr. Solution. سأعطيك صورة من مقطع فيديو تعليمي (سلايد أو شاشة عرض) مع النص اللي قاله الدكتور/المحاضر في هذا المقطع.

المهمة: اشرح مقطع الفيديو هذا بناءً على الصورة والنص معاً.

قواعد أساسية:
- اشرح بالعربية الفصحى.
- المصطلحات التقنية أو العلمية الإنجليزية (مثل Array, Loop, DNA, Algorithm) أبرزها بخط عريض (**مصطلح**) واكتب معناها بالعربي.
- لا تترجم المصطلحات المتخصصة — اشرحها فقط.
- لا تخلق معلومات غير موجودة في الصورة أو النص.
- إذا النص بالإنجليزية، ترجم الشرح للعربية مع الحفاظ على المصطلحات.
- إذا النص بالعربية، استخدمه مباشرة وأبرز المصطلحات الإنجليزية.

أعد JSON فقط بهذا الشكل:
{
  "title": "عنوان واضح لهذا المقطع",
  "arabic_explanation": "شرح تعليمي كامل للفكرة بناءً على الصورة والنص. اشرح المصطلحات، العلاقات، وكأنك تشرح لطالب.",
  "translation": "إذا كان النص الأصلي بالإنجليزية، اكتب ترجمته العربية هنا. إذا كان النص عربي، اتركه فارغاً.",
  "key_points": ["نقطة رئيسية 1", "نقطة رئيسية 2", "نقطة رئيسية 3"],
  "technical_terms": [
    {"term": "EnglishTerm", "arabic_equivalent": "المقابل العربي", "explanation": "شرح بسيط للمصطلح"}
  ],
  "segment_summary": "خلاصة 2-3 جمل لهذا المقطع"
}
لا تضع Markdown أو نص خارج JSON.
""".strip()


async def analyze_video_segment(
    image_b64: str,
    mime_type: str,
    transcript: str,
    model: str,
    api_key: str,
    settings: Settings,
) -> dict:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    prompt = f"صورة من مقطع فيديو تعليمي.\n\nالنص المقابل لهذا المقطع:\n{transcript}"
    parts: list[dict] = [{"text": prompt}]
    parts.append({"inlineData": {"mimeType": mime_type, "data": image_b64}})
    parts.append({"text": VIDEO_SEGMENT_PROMPT})
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.18,
            "responseMimeType": "application/json",
            "maxOutputTokens": 8192,
        },
    }
    headers = {"x-goog-api-key": api_key}
    response = await _post_with_retry(url, headers, payload, settings.request_timeout_seconds)
    _raise_for_provider_error(response, "Gemini")
    try:
        blocks = response.json()["candidates"][0]["content"]["parts"]
        text = "\n".join(block.get("text", "") for block in blocks)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ProviderError("وصل رد غير مكتمل من Gemini.") from exc
    return _parse_json(text)


VIDEO_SYNTHESIS_PROMPT = """
أنت مدرس جامعي. لدي تحليل لمقاطع فيديو تعليمية متعددة. المطلوب: بناء خلاصة دراسية متكاملة للمادة كاملة.

أعد JSON فقط بهذا الشكل:
{
  "overall_summary": "خلاصة عامة شاملة للمادة من 3-5 فقرات تغطي كل الأفكار الرئيسية",
  "learning_objectives": ["هدف تعلم 1", "هدف تعلم 2", "هدف تعلم 3"],
  "glossary": [
    {"term": "EnglishTerm", "arabic_equivalent": "المقابل العربي", "explanation": "شرح المصطلح"}
  ]
}
لا تضع Markdown أو نص خارج JSON.

تحليل المقاطع:
""".strip()


async def synthesize_video(
    segments: list[VideoSegmentAnalysis],
    model: str,
    api_key: str,
    settings: Settings,
) -> dict:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    segments_text = "\n\n".join(
        f"[مقطع {s.index}] {s.title}\n{s.segment_summary}"
        for s in segments
    )
    prompt = VIDEO_SYNTHESIS_PROMPT + "\n" + segments_text
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.18,
            "responseMimeType": "application/json",
            "maxOutputTokens": 8192,
        },
    }
    headers = {"x-goog-api-key": api_key}
    response = await _post_with_retry(url, headers, payload, settings.request_timeout_seconds)
    _raise_for_provider_error(response, "Gemini")
    try:
        blocks = response.json()["candidates"][0]["content"]["parts"]
        text = "\n".join(block.get("text", "") for block in blocks)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ProviderError("وصل رد غير مكتمل من Gemini.") from exc
    return _parse_json(text)


async def _post_with_retry(
    url: str,
    headers: dict[str, str],
    payload: dict,
    timeout_seconds: int,
) -> httpx.Response:
    last_response: httpx.Response | None = None
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        for attempt in range(2):
            try:
                response = await client.post(url, headers=headers, json=payload)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 1:
                    raise ProviderError("انقطع الاتصال بخدمة الذكاء الاصطناعي. أعد المحاولة.") from exc
                await asyncio.sleep(1.2)
                continue
            last_response = response
            if response.status_code < 500:
                return response
            if attempt == 0:
                await asyncio.sleep(1.2)
        return last_response
    raise ProviderError("تعذر الاتصال بخدمة الذكاء الاصطناعي.")


def _parse_json(raw: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProviderError("وصلت نتيجة غير منظمة من المحرك. أعد المحاولة.") from exc
    if not isinstance(payload, dict):
        raise ProviderError("وصلت نتيجة غير متوقعة من المحرك. أعد المحاولة.")
    return payload


def _raise_for_provider_error(response: httpx.Response, provider: str) -> None:
    if response.is_success:
        return
    detail = ""
    try:
        payload = response.json()
        error = payload.get("error", payload)
        if isinstance(error, dict):
            detail = str(error.get("message", ""))
    except json.JSONDecodeError:
        detail = ""

    if response.status_code in {401, 403}:
        raise ProviderError(f"مفتاح {provider} غير صالح أو لا يملك الصلاحية المطلوبة.")
    if response.status_code == 402 or "insufficient balance" in detail.lower():
        raise ProviderError(f"رصيد {provider} غير كافٍ. اشحن الحساب أو استخدم محركاً آخر.")
    if response.status_code == 429:
        raise ProviderError(f"تم بلوغ الحد المجاني في {provider}. انتظر قليلاً ثم أعد المحاولة.")
    if response.status_code >= 500:
        raise ProviderError(f"خدمة {provider} غير متاحة مؤقتاً. جرّب بعد قليل.")
    raise ProviderError(detail or f"فشل الطلب إلى {provider} برمز {response.status_code}.")
