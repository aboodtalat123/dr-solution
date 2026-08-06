from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.services.providers import get_rate_limiter
from app.models import (
    VideoSegmentAnalysis,
    VideoTechnicalTerm,
    VideoAnalysisResult,
)


SEGMENT_DURATION = 45
FRAMES_DIR = Path(__file__).resolve().parents[2] / "video-frames"
FRAMES_DIR.mkdir(exist_ok=True)

# ─── Cache ───
_video_cache: dict[str, dict] = {}
_CACHE_TTL = 3600  # 1 hour


def _cache_get(key: str) -> dict | None:
    entry = _video_cache.get(key)
    if entry and time.time() - entry["_ts"] < _CACHE_TTL:
        return entry
    return None


def _cache_set(key: str, data: dict) -> None:
    data["_ts"] = time.time()
    _video_cache[key] = data
    if len(_video_cache) > 50:
        oldest = min(_video_cache, key=lambda k: _video_cache[k].get("_ts", 0))
        del _video_cache[oldest]


# ─── Utilities ───

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
        raise RuntimeError(f"الأداة '{name}' غير مثبتة.")
    return cmd


def _extract_video_id(url: str) -> str:
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    if "/shorts/" in url:
        return url.split("/shorts/")[1].split("?")[0]
    return ""


# ─── YouTube helpers ───

def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    allowed = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
    return parsed.scheme == "https" and host in allowed


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
        videos = [v for v in videos if (start is None or v["index"] >= start) and (end is None or v["index"] <= end)]
    return videos


def get_video_info(url: str) -> dict:
    yt_dlp = _check_tool("yt-dlp")
    result = _run(
        [yt_dlp, "--no-playlist", "--print",
         "%(title)s\t%(duration)s\t%(id)s",
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


def get_chapters(video_url: str) -> list[dict]:
    """Get YouTube chapters (if any)."""
    yt_dlp = _check_tool("yt-dlp")
    result = _run(
        [yt_dlp, "--no-playlist", "--print-chapters",
         "--print", "%(chapters)s",
         "--no-warnings", video_url],
        timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        chapters = json.loads(result.stdout.strip())
        if isinstance(chapters, list):
            return chapters
    except (json.JSONDecodeError, ValueError):
        pass
    return []


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
    for block in re.split(r'\n\n+', content.strip()):
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        if not re.match(r'\d+:\d+:\d+[,.]\d+\s*-->\s*\d+:\d+:\d+[,.]\d+', lines[1]):
            continue
        times = re.findall(r'(\d+:\d+:\d+)[,.](\d+)', lines[1])
        if len(times) < 2:
            continue
        start = _ts_to_sec(times[0][0] + "." + times[0][1][:3])
        end = _ts_to_sec(times[1][0] + "." + times[1][1][:3])
        text = re.sub(r'<[^>]+>', '', " ".join(l.strip() for l in lines[2:] if l.strip())).strip()
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
        m = re.match(r'(\d+:\d+:\d+[.,]\d+)\s+-->\s+(\d+:\d+:\d+[.,]\d+)', line)
        if m:
            start = _ts_to_sec(m.group(1).replace(",", "."))
            end = _ts_to_sec(m.group(2).replace(",", "."))
            i += 1
            texts = []
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("NOTE"):
                texts.append(lines[i].strip())
                i += 1
            text = re.sub(r'<[^>]+>', '', " ".join(texts)).strip()
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


# ─── Whisper ───

@lru_cache(maxsize=2)
def _load_whisper_model(model_name: str, compute_type: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("مكتبة faster-whisper غير مثبتة.") from exc
    cpu_threads = max(1, min(os.cpu_count() or 2, 4))
    return WhisperModel(model_name, device="cpu", compute_type=compute_type, cpu_threads=cpu_threads)


def download_audio_only(video_url: str, output_dir: Path) -> Path:
    yt_dlp = _check_tool("yt-dlp")
    ffmpeg = _check_tool("ffmpeg")
    output_template = output_dir / "audio.%(ext)s"
    result = _run(
        [yt_dlp, "--no-playlist", "--no-warnings",
         "--ffmpeg-location", ffmpeg,
         "-x", "--audio-format", "mp3",
         "--audio-quality", "10",
         "-o", str(output_template), video_url],
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"فشل تحميل الصوت: {result.stderr.strip()}")
    candidates = [p for p in output_dir.glob("audio.*") if p.is_file() and p.suffix not in {".part", ".ytdl"}]
    if not candidates:
        raise RuntimeError("اكتمل تحميل الصوت لكن الملف غير موجود.")
    return max(candidates, key=lambda p: p.stat().st_size)


def transcribe_with_whisper(audio_path: Path, settings: Settings) -> list[dict]:
    model = _load_whisper_model(settings.whisper_model, settings.whisper_compute_type)
    segments, _ = model.transcribe(str(audio_path), beam_size=1, vad_filter=True, condition_on_previous_text=False)
    return [{"start": float(s.start), "end": float(s.end), "text": s.text.strip()} for s in segments if s.text.strip()]


# ─── Frame Extraction ───

def get_youtube_thumbnail(video_id: str, quality: str = "hqdefault") -> bytes | None:
    """Fetch a static YouTube thumbnail by video ID. No ffmpeg, no download needed."""
    urls = [
        f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/0.jpg",
        f"https://i.ytimg.com/vi/{video_id}/1.jpg",
        f"https://i.ytimg.com/vi/{video_id}/2.jpg",
        f"https://i.ytimg.com/vi/{video_id}/3.jpg",
    ]
    for url in urls:
        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 2000:
                return resp.content
        except Exception:
            continue
    return None


def grab_frame(
    video_id: str,
    second: float,
    output_path: Path | None = None,
    direct_url: str | None = None,
) -> bytes | None:
    """Try YouTube thumbnail first, fall back to ffmpeg streaming."""
    if output_path is None:
        output_path = FRAMES_DIR / f"{video_id}_{int(second)}.jpg"
    if output_path.exists():
        return output_path.read_bytes()

    # 1) Try YouTube static thumbnail
    data = get_youtube_thumbnail(video_id)
    if data:
        output_path.write_bytes(data)
        return data

    # 2) Fallback: ffmpeg streaming from direct URL (no file saved)
    if not direct_url:
        return None
    try:
        ffmpeg = _check_tool("ffmpeg")
        dir_path = output_path.parent
        dir_path.mkdir(parents=True, exist_ok=True)
        tmp = output_path.with_suffix(".tmp.jpg")
        result = _run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(second), "-i", direct_url,
             "-frames:v", "1", "-q:v", "2", str(tmp)],
            timeout=120,
        )
        if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 1000:
            tmp.rename(output_path)
            return output_path.read_bytes()
    except Exception:
        pass
    return None


def image_to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


# ─── Segmentation ───

def build_video_segments(
    transcript: list[dict],
    duration: float,
    chapters: list[dict],
    settings: Settings,
) -> tuple[list[dict], str]:
    transcript_end = max((float(item.get("end", 0)) for item in transcript), default=0.0)
    duration = max(float(duration or 0), transcript_end, 1.0)

    # Strategy 1: use YouTube chapters
    boundaries = []
    segmentation_mode = ""
    if chapters:
        boundaries = [0.0]
        for ch in chapters:
            t = float(ch.get("start_time", 0) or ch.get("start", 0))
            if 0 < t < duration:
                boundaries.append(t)
        boundaries.append(duration)
        segmentation_mode = "chapters"

    # Strategy 2: use timed segments
    if len(boundaries) < 2:
        boundaries = [0.0]
        cursor = float(SEGMENT_DURATION)
        while cursor < duration:
            boundaries.append(cursor)
            cursor += SEGMENT_DURATION
        boundaries.append(duration)
        segmentation_mode = "timed"

    boundaries = sorted(set(max(0.0, min(float(v), duration)) for v in boundaries))
    if boundaries[0] != 0.0:
        boundaries.insert(0, 0.0)
    if boundaries[-1] != duration:
        boundaries.append(duration)
    boundaries = _limit_boundaries(boundaries, settings.video_max_segments)

    segments = []
    for start, end in zip(boundaries, boundaries[1:]):
        matching = []
        for item in transcript:
            mid = (float(item.get("start", 0)) + float(item.get("end", 0))) / 2
            if start <= mid < end:
                text = str(item.get("text", "")).strip()
                if text:
                    matching.append(text)
        segments.append({"start": start, "end": end, "text": " ".join(matching)})
    return segments, segmentation_mode


def _limit_boundaries(boundaries: list[float], max_segments: int) -> list[float]:
    limited = list(boundaries)
    max_segments = max(1, max_segments)
    while len(limited) - 1 > max_segments:
        durations = [end - start for start, end in zip(limited, limited[1:])]
        shortest = min(range(len(durations)), key=durations.__getitem__)
        remove_at = shortest if shortest == len(durations) - 1 else shortest + 1
        del limited[remove_at]
    return limited


# ─── Gemini Goals Extraction ───

GOALS_PROMPT = """Extract EVERY learning objective, goal, or agenda item visible in this course video screenshot.
Rules:
1. Each bullet/number is ONE separate objective string.
2. PRESERVE Arabic text exactly as written — do NOT translate.
3. Clean OCR artifacts but keep the original meaning.
4. Return ONLY valid JSON with this exact shape:
{"objectives":["first objective","second objective"]}
If no clear objectives, return:
{"objectives":["No clear objectives found in this frame"]}"""


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


async def extract_goals_from_frame(image_b64: str, model: str, api_key: str, rpm: int = 30, rpd: int = 1500) -> list[str]:
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
    await get_rate_limiter("gemini", rpm, rpd).acquire()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        resp.raise_for_status()
        data = resp.json()
    try:
        blocks = data["candidates"][0]["content"]["parts"]
        text = "\n".join(b.get("text", "") for b in blocks)
    except (KeyError, IndexError):
        raise RuntimeError("رد غير متوقع من Gemini")
    return _parse_goals(text)


# ─── Main Pipeline ───

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
            frame_data = get_youtube_thumbnail(video["id"])
            if not frame_data:
                try:
                    direct_url = await asyncio.to_thread(get_direct_video_url, video["url"])
                    frame_data = grab_frame(video["id"], second, direct_url=direct_url)
                except Exception:
                    pass
            if not frame_data:
                raise RuntimeError("تعذر الحصول على صورة من الفيديو.")
            image_b64 = image_to_base64(frame_data)

            if provider == "gemini":
                objectives = await extract_goals_from_frame(
                    image_b64, model or settings.gemini_model, api_key or settings.gemini_api_key,
                    rpm=settings.gemini_rpm, rpd=settings.gemini_rpd,
                )
            else:
                raise RuntimeError(f"المحرك {provider} غير مدعوم لاستخراج الأهداف.")

            results.append({
                "video_title": video["title"],
                "video_url": video["url"],
                "timestamp_seconds": second,
                "objectives": objectives,
                "objectives_count": len(objectives),
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

    return {"results": results, "total_videos": len(results),
            "total_objectives": sum(r.get("objectives_count", 0) for r in results),
            "provider": provider, "second": second}


def get_direct_video_url(video_url: str) -> str:
    yt_dlp = _check_tool("yt-dlp")
    result = _run([yt_dlp, "--no-playlist", "-f", "best[ext=mp4]/best", "-g", video_url], timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"فشل الحصول على رابط البث: {result.stderr}")
    direct = result.stdout.splitlines()[0].strip()
    if not direct:
        raise RuntimeError("رابط البث فارغ")
    return direct


async def analyze_single_video(
    video: dict,
    settings: Settings,
    api_key: str,
    model: str,
) -> VideoAnalysisResult:
    video_url = video["url"]
    video_id = video.get("id") or _extract_video_id(video_url)

    # Check cache
    cache_key = f"{video_id}:{model}"
    cached = _cache_get(cache_key)
    if cached:
        return VideoAnalysisResult(**cached)

    info = await asyncio.to_thread(get_video_info, video_url)
    title = info.get("title", "فيديو بدون عنوان")
    duration = float(info.get("duration", 0) or 0)
    if duration > settings.video_max_duration_seconds:
        limit_minutes = settings.video_max_duration_seconds // 60
        raise RuntimeError(f"مدة الفيديو تتجاوز الحد ({limit_minutes} دقيقة).")

    warnings: list[str] = []
    transcript_source = ""

    # Transcript
    try:
        transcript = await asyncio.to_thread(get_transcript, video_url)
    except RuntimeError as exc:
        transcript = []
        warnings.append(str(exc))
    if transcript:
        transcript_source = "youtube_captions"

    # Whisper fallback
    if not transcript:
        with tempfile.TemporaryDirectory(prefix="dr-solution-") as tmpdir:
            workspace = Path(tmpdir)
            if not settings.video_enable_whisper:
                warnings.append("لا توجد ترجمة YouTube وWhisper متوقف.")
            elif duration > settings.video_whisper_max_duration_seconds:
                limit_minutes = settings.video_whisper_max_duration_seconds // 60
                warnings.append(f"تجاوز حد Whisper ({limit_minutes} دقيقة).")
            else:
                try:
                    audio = await asyncio.to_thread(download_audio_only, video_url, workspace)
                    transcript = await asyncio.to_thread(transcribe_with_whisper, audio, settings)
                    if transcript:
                        transcript_source = "whisper"
                    else:
                        warnings.append("Whisper لم يكتشف كلاماً واضحاً.")
                except Exception as exc:
                    warnings.append(f"Whisper: {exc}")

    # Chapters
    chapters = await asyncio.to_thread(get_chapters, video_url)

    # Build segments
    segments, segmentation_mode = build_video_segments(transcript, duration, chapters, settings)
    if not transcript_source:
        transcript_source = "unavailable"

    # Get direct URL for ffmpeg fallback
    direct_url = None
    try:
        direct_url = await asyncio.to_thread(get_direct_video_url, video_url)
    except RuntimeError:
        pass

    # Analyze each segment
    semaphore = asyncio.Semaphore(2)
    segment_results: list[VideoSegmentAnalysis] = []

    async def process_segment(idx: int, seg: dict) -> VideoSegmentAnalysis:
        async with semaphore:
            frame_data_url = ""
            try:
                mid_sec = int((seg["start"] + seg["end"]) / 2)
                data = await asyncio.to_thread(grab_frame, video_id, mid_sec, direct_url=direct_url)
                if data:
                    frame_data_url = f"data:image/jpeg;base64,{image_to_base64(data)}"
                    raw = await analyze_video_segment(
                        image_to_base64(data), "image/jpeg", seg["text"],
                        model, api_key, settings,
                    )
                else:
                    raw = await analyze_video_segment(
                        "", "image/jpeg", seg["text"],
                        model, api_key, settings,
                        no_image=True,
                    )
                terms = [
                    VideoTechnicalTerm(
                        term=item.get("term", ""),
                        arabic_equivalent=item.get("arabic_equivalent", ""),
                        explanation=item.get("explanation", ""),
                    ) for item in raw.get("technical_terms", [])
                ]
                return VideoSegmentAnalysis(
                    index=idx + 1, start_sec=seg["start"], end_sec=seg["end"],
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
                    index=idx + 1, start_sec=seg["start"], end_sec=seg["end"],
                    title=f"مقطع {idx + 1}", transcript_text=seg["text"],
                    arabic_explanation=f"تعذر التحليل: {exc}",
                    segment_summary=f"تعذر التحليل: {exc}",
                    frame_data_url=frame_data_url,
                )

    tasks = [process_segment(i, seg) for i, seg in enumerate(segments)]
    for coro in asyncio.as_completed(tasks):
        segment_results.append(await coro)
    segment_results.sort(key=lambda s: s.index)

    # Glossary
    all_terms: list[VideoTechnicalTerm] = []
    seen = set()
    for seg in segment_results:
        for t in seg.technical_terms:
            if t.term.lower() not in seen:
                seen.add(t.term.lower())
                all_terms.append(t)

    # Synthesis
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
        study_plan = synthesis.get("study_plan", [])
    except Exception as exc:
        overall_summary = ""
        objectives = []
        study_plan = []
        warnings.append(f"تعذر بناء الخلاصة العامة: {exc}")

    result = VideoAnalysisResult(
        video_title=title,
        duration_sec=duration,
        transcript_source=transcript_source,
        segmentation_mode=segmentation_mode,
        warnings=list(dict.fromkeys(warnings)),
        segments=segment_results,
        overall_summary=overall_summary,
        learning_objectives=objectives,
        glossary=all_terms,
        study_plan=study_plan,
    )

    _cache_set(cache_key, result.model_dump(mode="json"))
    return result


async def process_video_deep(
    url: str,
    start: int | None,
    end: int | None,
    api_key: str,
    model: str,
    settings: Settings,
) -> list[dict]:
    if not is_youtube_url(url):
        raise RuntimeError("رابط YouTube صالح يبدأ بـ https:// مطلوب.")
    api_key = api_key.strip() or settings.gemini_api_key
    if not api_key:
        raise RuntimeError("مفتاح Gemini مطلوب لتحليل الفيديو.")

    resolve_model = model.strip() or settings.gemini_model
    videos = await asyncio.to_thread(get_playlist_videos, url, start, end)
    if not videos:
        raise RuntimeError("لم يتم العثور على فيديوهات.")
    if len(videos) > settings.video_max_playlist_items:
        raise RuntimeError(f"الحد الأقصى {settings.video_max_playlist_items} فيديوهات.")

    results = []
    for video in videos:
        try:
            analysis = await analyze_single_video(video, settings, api_key, resolve_model)
            results.append(analysis.model_dump(mode="json"))
        except Exception as exc:
            results.append({"video_title": video["title"], "error": str(exc), "segments": []})
    return results
