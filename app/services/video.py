from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.models import VideoSegmentAnalysis, VideoTechnicalTerm, VideoAnalysisResult, VideoSegment
from app.services.providers import analyze_video_segment, synthesize_video


FRAMES_DIR = Path(__file__).resolve().parents[2] / "video-frames"
SEGMENT_DURATION = 45


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _check_tool(name: str) -> str:
    cmd = shutil.which(name)
    if not cmd and name == "ffmpeg":
        try:
            import imageio_ffmpeg

            cmd = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            cmd = None
    if not cmd:
        raise RuntimeError(f"الأداة '{name}' غير مثبتة. قم بتثبيتها أولاً.")
    return cmd


def _extract_video_id(url: str) -> str:
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    if "/shorts/" in url:
        return url.split("/shorts/")[1].split("?")[0]
    return ""


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    allowed_hosts = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }
    return parsed.scheme == "https" and host in allowed_hosts


def get_playlist_videos(url: str, start: int | None = None, end: int | None = None) -> list[dict]:
    yt_dlp = _check_tool("yt-dlp")
    result = _run(
        [yt_dlp, "--flat-playlist", "--yes-playlist", "--print",
         "%(playlist_index)s\t%(id)s\t%(title)s\t%(webpage_url)s",
         "--no-warnings", url],
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"فشل قراءة القائمة: {result.stderr}")

    videos: list[dict] = []
    for raw_line in result.stdout.splitlines():
        parts = raw_line.split("\t")
        if len(parts) < 4:
            continue
        index_raw, vid, title, video_url = parts[:4]
        idx = 1
        try:
            idx = int(index_raw)
        except ValueError:
            idx = len(videos) + 1
        if not video_url.startswith("http"):
            video_url = f"https://www.youtube.com/watch?v={vid}"
        videos.append({"index": idx, "id": vid, "title": title, "url": video_url})

    if start or end:
        filtered = []
        for video in videos:
            pos = video["index"]
            if start is not None and pos < start:
                continue
            if end is not None and pos > end:
                continue
            filtered.append(video)
        videos = filtered

    return videos


def get_direct_video_url(video_url: str) -> str:
    yt_dlp = _check_tool("yt-dlp")
    result = _run([yt_dlp, "--no-playlist", "-f", "best[ext=mp4]/best", "-g", video_url], timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"فشل الحصول على رابط الفيديو: {result.stderr}")
    direct = result.stdout.splitlines()[0].strip()
    if not direct:
        raise RuntimeError("رابط الفيديو فارغ")
    return direct


def download_video_file(video_url: str, output_dir: Path) -> Path:
    yt_dlp = _check_tool("yt-dlp")
    ffmpeg = _check_tool("ffmpeg")
    output_template = output_dir / "source.%(ext)s"
    result = _run(
        [
            yt_dlp,
            "--no-playlist",
            "--no-warnings",
            "--ffmpeg-location",
            ffmpeg,
            "-f",
            "best[height<=480][ext=mp4]/best[height<=480]/best[ext=mp4]/best",
            "--merge-output-format",
            "mp4",
            "-o",
            str(output_template),
            video_url,
        ],
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"فشل تنزيل نسخة التحليل من الفيديو: {result.stderr.strip()}")

    candidates = [
        path for path in output_dir.glob("source.*")
        if path.is_file() and path.suffix not in {".part", ".ytdl"}
    ]
    if not candidates:
        raise RuntimeError("اكتمل تنزيل الفيديو لكن ملف التحليل غير موجود.")
    return max(candidates, key=lambda path: path.stat().st_size)


def get_video_info(url: str) -> dict:
    yt_dlp = _check_tool("yt-dlp")
    result = _run(
        [yt_dlp, "--no-playlist", "--print", "%(title)s\t%(duration)s\t%(id)s",
         "--no-warnings", url],
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"فشل الحصول على معلومات الفيديو: {result.stderr}")
    parts = result.stdout.strip().split("\t")
    return {
        "title": parts[0] if len(parts) > 0 else "بدون عنوان",
        "duration": float(parts[1]) if len(parts) > 1 and parts[1] else 0,
        "id": parts[2] if len(parts) > 2 else "",
    }


def get_transcript(url: str) -> list[dict]:
    video_id = _extract_video_id(url)
    if not video_id:
        return []

    yt_dlp = _check_tool("yt-dlp")
    with tempfile.TemporaryDirectory(prefix="transcript_") as tmpdir:
        cmd = [
            yt_dlp, "--skip-download",
            "--write-auto-subs", "--write-subs",
            "--sub-langs", "ar.*,en.*,ar,en",
            "--convert-subs", "srt",
            "-o", os.path.join(tmpdir, "%(id)s.%(ext)s"),
            "--no-warnings", url,
        ]
        result = _run(cmd, timeout=120)
        if result.returncode != 0:
            return []

        srt_files = sorted(Path(tmpdir).glob("*.srt"))
        if not srt_files:
            vtt_files = sorted(Path(tmpdir).glob("*.vtt"))
            if vtt_files:
                return _parse_vtt(vtt_files[0])
            return []

        return _parse_srt(srt_files[0])


def _parse_srt(path: Path) -> list[dict]:
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    segments = []
    blocks = re.split(r'\n\n+', content.strip())
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        time_match = re.match(
            r'\d+:\d+:\d+[,.]\d+\s*-->\s*\d+:\d+:\d+[,.]\d+',
            lines[1]
        )
        if not time_match:
            continue
        times = re.findall(r'(\d+:\d+:\d+)[,.](\d+)', lines[1])
        if len(times) < 2:
            continue
        start = _ts_to_sec(times[0][0] + "." + times[0][1][:3])
        end = _ts_to_sec(times[1][0] + "." + times[1][1][:3])
        text = " ".join(l.strip() for l in lines[2:] if l.strip())
        text = re.sub(r'<[^>]+>', '', text).strip()
        if text:
            segments.append({"start": start, "end": end, "text": text})
    return segments


def _parse_vtt(path: Path) -> list[dict]:
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    segments = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        time_match = re.match(
            r'(\d+:\d+:\d+[.,]\d+)\s+-->\s+(\d+:\d+:\d+[.,]\d+)', line
        )
        if time_match:
            start = _ts_to_sec(time_match.group(1).replace(",", "."))
            end = _ts_to_sec(time_match.group(2).replace(",", "."))
            i += 1
            texts = []
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("NOTE"):
                texts.append(lines[i].strip())
                i += 1
            text = " ".join(texts)
            text = re.sub(r'<[^>]+>', '', text).strip()
            if text:
                segments.append({"start": start, "end": end, "text": text})
        i += 1
    return segments


def _ts_to_sec(t: str) -> float:
    t = t.replace(",", ".")
    parts = t.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


@lru_cache(maxsize=2)
def _load_whisper_model(model_name: str, compute_type: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("مكتبة faster-whisper غير مثبتة على الخادم.") from exc

    cpu_threads = max(1, min(os.cpu_count() or 2, 4))
    return WhisperModel(
        model_name,
        device="cpu",
        compute_type=compute_type,
        cpu_threads=cpu_threads,
    )


def transcribe_with_whisper(video_path: Path, settings: Settings) -> list[dict]:
    model = _load_whisper_model(settings.whisper_model, settings.whisper_compute_type)
    segments, _ = model.transcribe(
        str(video_path),
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    transcript = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            transcript.append({
                "start": float(segment.start),
                "end": float(segment.end),
                "text": text,
            })
    return transcript


def detect_scene_boundaries(
    video_path: Path,
    duration: float,
    settings: Settings,
) -> list[float]:
    if not settings.video_enable_scene_detection or duration <= 0:
        return []
    try:
        from scenedetect import ContentDetector, detect
    except ImportError as exc:
        raise RuntimeError("مكتبة PySceneDetect غير مثبتة على الخادم.") from exc

    scenes = detect(
        str(video_path),
        ContentDetector(threshold=settings.video_scene_threshold),
        show_progress=False,
    )
    candidates = [float(start.get_seconds()) for start, _ in scenes[1:]]
    boundaries = []
    last = 0.0
    for second in candidates:
        if second >= duration:
            continue
        if second - last >= settings.video_min_scene_seconds:
            boundaries.append(second)
            last = second
    return boundaries


def _split_long_intervals(boundaries: list[float], max_duration: float) -> list[float]:
    if max_duration <= 0:
        return boundaries
    expanded = [boundaries[0]]
    for start, end in zip(boundaries, boundaries[1:]):
        cursor = start + max_duration
        while cursor < end:
            expanded.append(cursor)
            cursor += max_duration
        expanded.append(end)
    return sorted(set(expanded))


def _limit_boundaries(boundaries: list[float], max_segments: int) -> list[float]:
    limited = list(boundaries)
    max_segments = max(1, max_segments)
    while len(limited) - 1 > max_segments:
        durations = [end - start for start, end in zip(limited, limited[1:])]
        shortest = min(range(len(durations)), key=durations.__getitem__)
        remove_at = shortest if shortest == len(durations) - 1 else shortest + 1
        del limited[remove_at]
    return limited


def build_video_segments(
    transcript: list[dict],
    scene_boundaries: list[float],
    duration: float,
    settings: Settings,
) -> tuple[list[dict], str]:
    transcript_end = max((float(item.get("end", 0)) for item in transcript), default=0.0)
    duration = max(float(duration or 0), transcript_end, 1.0)

    if scene_boundaries:
        boundaries = [0.0, *scene_boundaries, duration]
        segmentation_mode = "scene_detection"
    else:
        boundaries = [0.0]
        cursor = float(SEGMENT_DURATION)
        while cursor < duration:
            boundaries.append(cursor)
            cursor += SEGMENT_DURATION
        boundaries.append(duration)
        segmentation_mode = "timed_fallback"

    boundaries = sorted(set(max(0.0, min(float(value), duration)) for value in boundaries))
    if boundaries[0] != 0.0:
        boundaries.insert(0, 0.0)
    if boundaries[-1] != duration:
        boundaries.append(duration)
    boundaries = _split_long_intervals(boundaries, settings.video_max_segment_seconds)
    boundaries = _limit_boundaries(boundaries, settings.video_max_segments)

    segments = []
    for start, end in zip(boundaries, boundaries[1:]):
        matching_text = []
        for item in transcript:
            item_start = float(item.get("start", 0))
            item_end = float(item.get("end", item_start))
            midpoint = (item_start + item_end) / 2
            if start <= midpoint < end or (end == duration and midpoint == end):
                text = str(item.get("text", "")).strip()
                if text:
                    matching_text.append(text)
        segments.append({"start": start, "end": end, "text": " ".join(matching_text)})
    return segments, segmentation_mode


def _merge_transcript_chunks(transcript: list[dict], chunk_duration: float = SEGMENT_DURATION) -> list[dict]:
    if not transcript:
        return []
    merged = []
    current = {"start": transcript[0]["start"], "end": transcript[0]["end"], "texts": [transcript[0]["text"]]}
    for seg in transcript[1:]:
        if seg["start"] - current["start"] < chunk_duration:
            current["end"] = seg["end"]
            current["texts"].append(seg["text"])
        else:
            merged.append({
                "start": current["start"],
                "end": current["end"],
                "text": " ".join(current["texts"]),
            })
            current = {"start": seg["start"], "end": seg["end"], "texts": [seg["text"]]}
    if current["texts"]:
        merged.append({
            "start": current["start"],
            "end": current["end"],
            "text": " ".join(current["texts"]),
        })
    return merged


def grab_frame(url_or_direct: str, second: int, output_path: Path | None = None) -> Path:
    FRAMES_DIR.mkdir(exist_ok=True)
    if output_path is None:
        output_path = FRAMES_DIR / f"frame-{second}.jpg"
    if output_path.exists():
        return output_path

    ffmpeg = _check_tool("ffmpeg")
    result = _run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-ss", str(second), "-i", url_or_direct,
         "-frames:v", "1", "-q:v", "2", str(output_path)],
        timeout=120,
    )
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"فشل التقاط الإطار عند الثانية {second}: {result.stderr}")
    return output_path


def image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


GOALS_PROMPT = """Extract EVERY learning objective, goal, or agenda item visible in this course video screenshot.

Rules:
1. Each bullet/number is ONE separate objective string.
2. PRESERVE Arabic text exactly as written — do NOT translate.
3. Clean OCR artifacts but keep the original meaning.
4. Return ONLY valid JSON with this exact shape:
{{"objectives":["first objective","second objective"]}}

If no clear objectives, return:
{{"objectives":["No clear objectives found in this frame"]}}"""


async def extract_with_gemini(image_b64: str, model: str, api_key: str) -> list[str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": image_b64}},
                {"text": GOALS_PROMPT},
            ]
        }],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json", "maxOutputTokens": 4096},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        resp.raise_for_status()
        data = resp.json()

    text = ""
    try:
        blocks = data["candidates"][0]["content"]["parts"]
        text = "\n".join(b.get("text", "") for b in blocks)
    except (KeyError, IndexError):
        raise RuntimeError("رد غير متوقع من Gemini")

    return _parse_goals(text)


async def extract_with_claude(image_b64: str, model: str, api_key: str) -> list[str]:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                {"type": "text", "text": GOALS_PROMPT},
            ]
        }],
    )
    text = message.content[0].text
    return _parse_goals(text)


def _parse_goals(text: str) -> list[str]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").replace("json", "", 1).strip()

    try:
        data = json.loads(cleaned)
        objectives = data.get("objectives", [])
        if isinstance(objectives, list):
            return [str(item).strip() for item in objectives if str(item).strip()]
    except json.JSONDecodeError:
        pass

    lines = []
    for line in cleaned.replace("\r\n", "\n").split("\n"):
        stripped = line.strip(" \t•·●○▪►→‣⁃-–—·*\"'«»")
        if stripped and len(stripped) > 2:
            lines.append(stripped)
    return lines if lines else ["لا توجد أهداف واضحة في هذا الإطار"]


async def process_video(
    url: str,
    second: int,
    start: int | None,
    end: int | None,
    provider: str,
    model: str,
    api_key: str,
    settings: Settings,
) -> dict:
    videos = await asyncio.to_thread(get_playlist_videos, url, start, end)
    if not videos:
        raise RuntimeError("لم يتم العثور على فيديوهات.")

    results = []
    for video in videos:
        try:
            direct_url = await asyncio.to_thread(get_direct_video_url, video["url"])
            frame_path = await asyncio.to_thread(grab_frame, direct_url, second)
            image_b64 = await asyncio.to_thread(image_to_base64, frame_path)

            if provider == "gemini":
                objectives = await extract_with_gemini(
                    image_b64, model or settings.gemini_model, api_key or settings.gemini_api_key
                )
            elif provider == "claude":
                objectives = await extract_with_claude(
                    image_b64, model or settings.anthropic_model, api_key or settings.anthropic_api_key
                )
            else:
                raise RuntimeError(f"المحرك {provider} غير مدعوم لاستخراج أهداف الفيديو.")

            results.append({
                "video_title": video["title"],
                "video_url": video["url"],
                "timestamp_seconds": second,
                "objectives": objectives,
                "objectives_count": len(objectives),
                "frame": str(frame_path),
            })
        except Exception as exc:
            results.append({
                "video_title": video["title"],
                "video_url": video["url"],
                "timestamp_seconds": second,
                "objectives": [],
                "objectives_count": 0,
                "error": str(exc),
            })

    return {
        "results": results,
        "total_videos": len(results),
        "total_objectives": sum(r.get("objectives_count", 0) for r in results),
        "provider": provider,
        "second": second,
    }


async def analyze_single_video(
    video: dict,
    settings: Settings,
    api_key: str,
    model: str,
) -> VideoAnalysisResult:
    video_url = video["url"]
    info = await asyncio.to_thread(get_video_info, video_url)
    title = info.get("title", "فيديو بدون عنوان")
    duration = float(info.get("duration", 0) or 0)
    if duration > settings.video_max_duration_seconds:
        limit_minutes = settings.video_max_duration_seconds // 60
        raise RuntimeError(f"مدة الفيديو تتجاوز الحد الحالي للتحليل ({limit_minutes} دقيقة).")

    warnings: list[str] = []
    try:
        transcript = await asyncio.to_thread(get_transcript, video_url)
    except RuntimeError as exc:
        transcript = []
        warnings.append(str(exc))
    transcript_source = "youtube_captions" if transcript else ""

    with tempfile.TemporaryDirectory(prefix="dr-solution-video-") as tmpdir:
        workspace = Path(tmpdir)
        video_path = await asyncio.to_thread(download_video_file, video_url, workspace)

        if not transcript:
            if not settings.video_enable_whisper:
                warnings.append("لا توجد ترجمة YouTube وWhisper متوقف في إعدادات الخادم.")
            elif duration and duration > settings.video_whisper_max_duration_seconds:
                limit_minutes = settings.video_whisper_max_duration_seconds // 60
                warnings.append(
                    f"لا توجد ترجمة YouTube؛ تم تجاوز حد Whisper المجاني ({limit_minutes} دقيقة)، "
                    "لذلك سيعتمد الشرح على الصورة فقط."
                )
            else:
                try:
                    transcript = await asyncio.to_thread(transcribe_with_whisper, video_path, settings)
                    if transcript:
                        transcript_source = "whisper"
                    else:
                        warnings.append("اكتمل Whisper لكن لم يكتشف كلاماً واضحاً في الفيديو.")
                except Exception as exc:
                    warnings.append(f"تعذر تشغيل Whisper: {exc}")

        try:
            scene_boundaries = await asyncio.to_thread(
                detect_scene_boundaries,
                video_path,
                duration or max((item.get("end", 0) for item in transcript), default=0),
                settings,
            )
        except Exception as exc:
            scene_boundaries = []
            warnings.append(f"تعذر كشف تغيّر السلايدات؛ استُخدم التقطيع الزمني: {exc}")

        segments, segmentation_mode = build_video_segments(
            transcript,
            scene_boundaries,
            duration,
            settings,
        )
        if not scene_boundaries:
            warnings.append("لم تُكتشف تغيّرات سلايد واضحة؛ استُخدم التقطيع الزمني الآمن.")
        if not transcript_source:
            transcript_source = "unavailable"

        semaphore = asyncio.Semaphore(2)
        segment_results: list[VideoSegmentAnalysis] = []

        async def process_segment(idx: int, seg: dict) -> VideoSegmentAnalysis:
            async with semaphore:
                frame_data_url = ""
                try:
                    mid_sec = int((seg["start"] + seg["end"]) / 2)
                    frame_path = await asyncio.to_thread(
                        grab_frame,
                        str(video_path),
                        mid_sec,
                        workspace / f"frame-{idx + 1:03}.jpg",
                    )
                    image_b64 = image_to_base64(frame_path)
                    frame_data_url = f"data:image/jpeg;base64,{image_b64}"
                    raw = await analyze_video_segment(
                        image_b64,
                        "image/jpeg",
                        seg["text"],
                        model,
                        api_key,
                        settings,
                    )
                    terms = [
                        VideoTechnicalTerm(
                            term=item.get("term", ""),
                            arabic_equivalent=item.get("arabic_equivalent", ""),
                            explanation=item.get("explanation", ""),
                        )
                        for item in raw.get("technical_terms", [])
                    ]
                    return VideoSegmentAnalysis(
                        index=idx + 1,
                        start_sec=seg["start"],
                        end_sec=seg["end"],
                        title=raw.get("title", f"مقطع {idx + 1}"),
                        transcript_text=seg["text"],
                        arabic_explanation=raw.get("arabic_explanation", ""),
                        translation=raw.get("translation", ""),
                        key_points=raw.get("key_points", []),
                        technical_terms=terms,
                        segment_summary=raw.get("segment_summary", ""),
                        frame_data_url=frame_data_url,
                    )
                except Exception as exc:
                    warnings.append(f"تعذر تحليل المقطع {idx + 1}: {exc}")
                    return VideoSegmentAnalysis(
                        index=idx + 1,
                        start_sec=seg["start"],
                        end_sec=seg["end"],
                        title=f"مقطع {idx + 1}",
                        transcript_text=seg["text"],
                        arabic_explanation=f"تعذر التحليل: {exc}",
                        segment_summary=f"تعذر التحليل: {exc}",
                        frame_data_url=frame_data_url,
                    )

        tasks = [process_segment(i, seg) for i, seg in enumerate(segments)]
        for coro in asyncio.as_completed(tasks):
            segment_results.append(await coro)
        segment_results.sort(key=lambda segment: segment.index)

    all_terms = []
    seen_terms = set()
    for seg in segment_results:
        for t in seg.technical_terms:
            key = t.term.lower()
            if key not in seen_terms:
                seen_terms.add(key)
                all_terms.append(t)

    try:
        synthesis = await synthesize_video(segment_results, model, api_key, settings)
        overall_summary = synthesis.get("overall_summary", "")
        objectives = synthesis.get("learning_objectives", [])
        glossary_terms = []
        for gt in synthesis.get("glossary", []):
            glossary_terms.append(VideoTechnicalTerm(
                term=gt.get("term", ""),
                arabic_equivalent=gt.get("arabic_equivalent", ""),
                explanation=gt.get("explanation", ""),
            ))
        if glossary_terms:
            all_terms = glossary_terms
    except Exception as exc:
        overall_summary = ""
        objectives = []
        warnings.append(f"تعذر بناء الخلاصة العامة: {exc}")

    return VideoAnalysisResult(
        video_title=title,
        duration_sec=duration,
        transcript_source=transcript_source,
        segmentation_mode=segmentation_mode,
        warnings=list(dict.fromkeys(warnings)),
        segments=segment_results,
        overall_summary=overall_summary,
        learning_objectives=objectives,
        glossary=all_terms,
    )


async def process_video_deep(
    url: str,
    start: int | None,
    end: int | None,
    api_key: str,
    model: str,
    settings: Settings,
) -> list[dict]:
    if not is_youtube_url(url):
        raise RuntimeError("يجب استخدام رابط YouTube صالح يبدأ بـ https://.")
    api_key = api_key.strip() or settings.gemini_api_key
    if not api_key:
        raise RuntimeError("مفتاح Gemini مطلوب لتحليل الفيديو.")

    resolve_model = model.strip() or settings.gemini_model
    videos = await asyncio.to_thread(get_playlist_videos, url, start, end)
    if not videos:
        raise RuntimeError("لم يتم العثور على فيديوهات.")
    if len(videos) > settings.video_max_playlist_items:
        raise RuntimeError(
            f"يمكن تحليل {settings.video_max_playlist_items} فيديوهات كحد أقصى في العملية الواحدة. "
            "حدّد حقلي من وإلى لتقسيم القائمة."
        )

    results = []
    for video in videos:
        try:
            analysis = await analyze_single_video(video, settings, api_key, resolve_model)
            results.append(analysis.model_dump(mode="json"))
        except Exception as exc:
            results.append({
                "video_title": video["title"],
                "error": str(exc),
                "segments": [],
            })
    return results
