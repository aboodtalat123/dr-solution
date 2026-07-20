"""Run a real, concise end-to-end check against the local video API."""

from __future__ import annotations

import argparse
import json
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="https://www.youtube.com/watch?v=jNQXAC9IVRw",
        help="Short public YouTube video used for the smoke test.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    started = time.monotonic()
    response = httpx.post(
        f"{args.base_url.rstrip('/')}/api/analyze-video",
        json={
            "url": args.url,
            "start": None,
            "end": None,
            "api_key": "",
            "provider": "gemini",
            "model": "",
        },
        timeout=600,
    )
    response.raise_for_status()
    payload = response.json()
    item = payload["results"][0]
    if item.get("error"):
        print(json.dumps({"status": "failed", "error": item["error"]}, ensure_ascii=False))
        return 2

    segments = item.get("segments", [])
    summary = {
        "status": "success",
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "videos": payload.get("total", 0),
        "title": item.get("video_title", ""),
        "duration_seconds": item.get("duration_sec", 0),
        "transcript_source": item.get("transcript_source", ""),
        "segmentation_mode": item.get("segmentation_mode", ""),
        "segments": len(segments),
        "frames_returned": sum(
            str(segment.get("frame_data_url", "")).startswith("data:image/")
            for segment in segments
        ),
        "explanations_returned": sum(
            bool(segment.get("arabic_explanation")) for segment in segments
        ),
        "summary_returned": bool(item.get("overall_summary")),
        "learning_objectives": len(item.get("learning_objectives", [])),
        "warnings": item.get("warnings", []),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
