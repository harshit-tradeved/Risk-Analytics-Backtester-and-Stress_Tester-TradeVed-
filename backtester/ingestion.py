"""
Instagram / video ingestion pipeline.

Core logic extracted from friend's adaptability_agent.py — yt-dlp → ffmpeg → Groq Whisper
→ transcript + cv2 frame extraction → Azure vision → on_screen_text.

Returns from handle_url():
    {
        "type":                 "video" | "carousel" | "image",
        "transcript":           str,
        "on_screen_text":       str,
        "original_source_text": str,   # combined on_screen_text + transcript (best for extraction)
        "source_url":           str,
        "caption":              str    # may be empty
    }

Env vars required:
    GROQ_API_KEY              — Groq Whisper transcription (whisper-large-v3-turbo)
    APIFY_TOKEN               — fallback when yt-dlp is blocked by Instagram
    AZURE_API_KEY             — vision frame analysis (Azure GPT-5.3-Codex or gpt-4o)
    AZURE_ENDPOINT            — Azure Responses API endpoint
    AZURE_VISION_MODEL        — optional override for vision (defaults to AZURE_MODEL)
    GROQ_WHISPER_LANGUAGE     — optional, defaults to "hi" (Hindi); set to "" for auto-detect
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


# ── Public entry point ────────────────────────────────────────────────────────

def handle_url(url: str) -> dict:
    """Download, transcribe, and analyze any YouTube/Instagram/TikTok video URL."""
    return _download_and_process(url)


def _is_instagram_url(url: str) -> bool:
    return "instagram.com" in url.lower()


# ── Download ──────────────────────────────────────────────────────────────────

def _download_and_process(url: str) -> dict:
    """
    Download + process any video URL via yt-dlp, with an Instagram-specific
    Apify fallback used ONLY for actual instagram.com URLs.

    Found via reel_pipeline_test_results_100.xlsx (148-URL run): several
    YouTube URLs that failed yt-dlp for unrelated reasons (age-gate, region
    lock, deleted video) were being routed through the Instagram Apify
    fallback anyway (the old function was Instagram-only by name AND by
    behavior), producing a nonsensical "Instagram blocked this post" error
    for YouTube content. Fallback is now platform-gated.
    """
    import subprocess
    import time
    tmp_dir = tempfile.mkdtemp()
    output_template = os.path.join(tmp_dir, "slide_%(playlist_index|1)s.%(ext)s")
    is_instagram = _is_instagram_url(url)
    print(f"  Downloading video from {url[:60]}...")

    # --js-runtimes node: recent yt-dlp versions need a JS runtime to solve
    # YouTube's signature challenges on some videos; Node.js is a common
    # pre-installed runtime (unlike deno, which yt-dlp otherwise expects).
    # Without this, some otherwise-downloadable YouTube videos fail.
    cmd = ["yt-dlp", "-o", output_template, "--format", "mp4/best[ext=mp4]/best",
           "--js-runtimes", "node"]
    if is_instagram:
        # Instagram auth: cookies file takes priority over --cookies-from-browser.
        # Resolved via config.py (not raw os.getenv) so relative paths in .env
        # work regardless of the process's cwd.
        from config import INSTAGRAM_COOKIES_FILE, INSTAGRAM_COOKIES_BROWSER
        if INSTAGRAM_COOKIES_FILE and os.path.exists(INSTAGRAM_COOKIES_FILE):
            cmd += ["--cookies", INSTAGRAM_COOKIES_FILE]
            print(f"  Using Instagram cookies from {INSTAGRAM_COOKIES_FILE}")
        elif INSTAGRAM_COOKIES_BROWSER:
            cmd += ["--cookies-from-browser", INSTAGRAM_COOKIES_BROWSER]
    cmd.append(url)

    # One retry with a short backoff: platform bot-detection / transient
    # throttling sometimes rejects the first request but allows a second one
    # moments later.
    result = subprocess.run(cmd, capture_output=True, text=True)
    downloaded = sorted(f for f in os.listdir(tmp_dir) if not f.startswith("."))
    if result.returncode != 0 or not downloaded:
        time.sleep(3)
        result = subprocess.run(cmd, capture_output=True, text=True)
        downloaded = sorted(f for f in os.listdir(tmp_dir) if not f.startswith("."))

    if result.returncode != 0 or not downloaded:
        if is_instagram:
            print("  yt-dlp blocked by Instagram, trying Apify fallback...")
            content_obj = _fetch_instagram_video_via_apify(url, tmp_dir)
            if content_obj is not None:
                return content_obj
            raise RuntimeError(
                "Instagram blocked this download (both yt-dlp and the Apify fallback failed "
                "after a retry). This is usually Instagram's anti-scraping detection, not a "
                "problem with this specific post — try again in a minute, or set "
                "INSTAGRAM_COOKIES_FILE/INSTAGRAM_COOKIES_BROWSER in .env for a logged-in "
                f"session. yt-dlp error: {result.stderr[:200] if result.returncode != 0 else 'no output file'}"
            )
        # Non-Instagram platforms (YouTube, TikTok, ...) have no Instagram-specific
        # fallback — surface the real yt-dlp failure instead of a misleading one.
        raise RuntimeError(
            "Could not download this video after a retry (age-restricted, region-locked, "
            "private, or removed content are common causes). "
            f"yt-dlp error: {result.stderr[:300] if result.returncode != 0 else 'no output file produced'}"
        )

    if len(downloaded) == 1:
        path = os.path.join(tmp_dir, downloaded[0])
        ext = Path(path).suffix.lower()
        content_obj = _handle_image(path) if ext in _IMAGE_EXTENSIONS else _process_video(path)
        content_obj["source_url"] = url
        return content_obj

    print(f"  Carousel detected: {len(downloaded)} slides")
    return _process_carousel(tmp_dir, downloaded, url)


def _fetch_instagram_video_via_apify(url: str, tmp_dir: str) -> dict | None:
    try:
        items = _apify_run("apify~instagram-reel-scraper", {"username": [url], "resultsLimit": 1})
    except Exception as e:
        print(f"Apify Instagram fetch failed: {e}")
        return None

    if not items or not isinstance(items[0], dict):
        return None

    item = items[0]
    video_url = item.get("videoUrl")

    if not video_url and item.get("error"):
        reason = item.get("errorDescription") or item.get("error")
        raise RuntimeError(f"Instagram blocked this post: {reason}")

    if not video_url:
        return None

    import requests
    video_path = os.path.join(tmp_dir, "slide_1.mp4")
    resp = requests.get(video_url, timeout=60, stream=True)
    resp.raise_for_status()
    with open(video_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)

    content_obj = _process_video(video_path)
    content_obj["source_url"] = url
    if item.get("caption"):
        content_obj["caption"] = item["caption"]
    return content_obj


def _apify_run(actor_id: str, input_data: dict) -> list:
    import requests
    token = os.getenv("APIFY_TOKEN", "")
    if not token:
        raise RuntimeError("APIFY_TOKEN not set in .env")
    run_url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    resp = requests.post(run_url, json=input_data, params={"token": token}, timeout=120)
    resp.raise_for_status()
    return resp.json()


# ── Video processing ──────────────────────────────────────────────────────────

def _process_video(video_path: str) -> dict:
    transcript = _extract_transcript(video_path)

    frames = _extract_frames(video_path, interval_sec=3)
    print(f"  Extracted {len(frames)} frames for vision analysis")

    vision = _analyze_frames_vision(frames) if frames else {}
    on_screen_text = vision.get("on_screen_text", "") or ""

    source_parts = []
    if on_screen_text:
        source_parts.append(f"On-screen text:\n{on_screen_text}")
    if transcript:
        source_parts.append(f"Spoken audio:\n{transcript}")

    return {
        "type": "video",
        "transcript": transcript,
        "on_screen_text": on_screen_text,
        "original_source_text": "\n\n".join(source_parts),
        "caption": "",
    }


# ── Frame extraction (from adaptability_agent.py:603–620) ────────────────────

def _extract_frames(path: str, interval_sec: int = 3) -> list:
    """Sample one frame every interval_sec seconds. Returns list of base64 JPEG strings."""
    try:
        import cv2
    except ImportError:
        logger.warning("opencv-python not installed — skipping frame extraction")
        return []

    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_interval = max(1, int(fps * interval_sec))
    frames = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % frame_interval == 0:
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            frames.append(base64.b64encode(buf.tobytes()).decode())
        idx += 1
    cap.release()
    return frames


# ── Vision analysis (adapted from adaptability_agent.py:758–798) ─────────────

def _analyze_frames_vision(frames: list) -> dict:
    """
    Send up to 5 sampled frames to Azure vision to extract on-screen text
    and trading-related visual elements.
    Returns {} on any failure so on_screen_text gracefully degrades to "".
    """
    from config import AZURE_API_KEY, AZURE_ENDPOINT, AZURE_MODEL
    vision_model = os.getenv("AZURE_VISION_MODEL", AZURE_MODEL)

    if not AZURE_API_KEY or not frames:
        return {}

    # Sample at most 5 frames evenly
    if len(frames) > 5:
        step = max(1, len(frames) // 5)
        sampled = [frames[i] for i in range(0, len(frames), step)][:5]
    else:
        sampled = frames

    # Build vision input: image blocks + text prompt
    content_blocks = [
        {"type": "input_image", "image_url": f"data:image/jpeg;base64,{img}"}
        for img in sampled
    ]
    content_blocks.append({
        "type": "input_text",
        "text": (
            "Analyze these video frames and return JSON:\n"
            "{\n"
            '  "on_screen_text": "ONLY text the creator deliberately added as captions, titles, '
            'bullet points, CTAs, watermarks, or graphic overlays to communicate their message — '
            'combined verbatim across all frames. Copy exact words, do not paraphrase. If the same '
            'caption appears across multiple frames include it ONCE in its most complete form. '
            'EXCLUDE incidental background text (books, posters, whiteboards) unless the video is '
            'clearly about that object.",\n'
            '  "key_trading_elements": ["every trading-related visual: charts, indicators, price levels, P&L"],\n'
            '  "video_format": "talking_head | text_based | chart_analysis | screen_recording | mixed | other"\n'
            "}\n"
            "Return only valid JSON."
        ),
    })

    import requests as _req
    try:
        print(f"  Running vision analysis on {len(sampled)} frames...")
        resp = _req.post(
            AZURE_ENDPOINT,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {AZURE_API_KEY}",
            },
            json={
                "model":             vision_model,
                "instructions":      "You are a video content analyst. Extract visible information exactly. Return only valid JSON.",
                "input":             [{"role": "user", "content": content_blocks}],
                "max_output_tokens": 900,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_text = ""
        for item in data.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") in ("output_text", "text"):
                        raw_text = part["text"].strip()
                        break
        if not raw_text:
            return {}
        # Strip markdown fences if present
        raw_text = re.sub(r"^```[a-z]*\n?", "", raw_text).rstrip("`").strip()
        result = json.loads(raw_text)
        return result if isinstance(result, dict) else {}
    except Exception as e:
        logger.warning("Vision analysis failed (non-fatal): %s", e)
        return {}


# ── Transcript (from adaptability_agent.py:643–755) ──────────────────────────

def _is_repetition_loop(text: str) -> bool:
    """Detect Whisper's repetition-loop hallucination."""
    words = text.split()
    if len(words) < 8:
        return False
    for n in range(1, 7):
        if len(words) < n * 4:
            continue
        phrase = tuple(words[:n])
        repeats = 1
        i = n
        while i + n <= len(words) and tuple(words[i:i + n]) == phrase:
            repeats += 1
            i += n
        if repeats >= 4 and (repeats * n) / len(words) >= 0.6:
            return True
    return False


def _extract_transcript(video_path: str) -> str:
    """
    Extract audio transcript using Groq Whisper with:
    - imageio-ffmpeg auto-path (avoids PATH issues on Windows)
    - Silence detection (skips music-only/silent videos)
    - Repetition-loop hallucination guard
    - Windows CREATE_NO_WINDOW flag (prevents crash with no console parent)
    """
    import subprocess

    # Auto-configure ffmpeg from imageio-ffmpeg bundle — avoids PATH issues on Windows
    ffmpeg_bin = "ffmpeg"
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        try:
            import moviepy.config as _mconfig
            _mconfig.change_settings({"FFMPEG_BINARY": ffmpeg_bin})
        except Exception:
            pass
    except Exception:
        pass

    # Silence detection via moviepy amplitude check
    try:
        import moviepy.editor as mp
        import numpy as np
        clip = mp.VideoFileClip(video_path)
        if clip.audio is None:
            clip.close()
            print("  No audio track — using Vision OCR only")
            return ""
        sample = clip.audio.subclip(0, min(5, clip.duration)).to_soundarray(fps=8000)
        peak = float(np.abs(sample).max()) if sample.size > 0 else 0.0
        clip.close()
        if peak < 0.01:
            print("  Audio is silent (peak < 0.01) — using Vision OCR only")
            return ""
    except Exception:
        pass  # Proceed even if amplitude check fails

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name

    try:
        print(f"  Extracting audio via ffmpeg...")
        _popen_kwargs: dict = {
            "stdin":   subprocess.DEVNULL,
            "stdout":  subprocess.PIPE,
            "stderr":  subprocess.PIPE,
            "timeout": 60,
        }
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            _popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        sp = subprocess.run(
            [ffmpeg_bin, "-y", "-i", video_path,
             "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
            **_popen_kwargs,
        )
        if sp.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed (exit {sp.returncode}): "
                f"{sp.stderr.decode(errors='replace')[:300]}"
            )

        from openai import OpenAI as _OpenAI
        groq_key = os.getenv("GROQ_API_KEY", "")
        if not groq_key:
            raise RuntimeError("GROQ_API_KEY not set — cannot transcribe")

        groq_client = _OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
        print("  Transcribing audio (Groq whisper-large-v3-turbo)...")
        lang = os.getenv("GROQ_WHISPER_LANGUAGE", "hi") or None  # "" → None = auto-detect
        with open(audio_path, "rb") as audio_file:
            kwargs: dict = {
                "model":           os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo"),
                "file":            audio_file,
                "response_format": "json",
            }
            if lang:
                kwargs["language"] = lang
            transcription = groq_client.audio.transcriptions.create(**kwargs)

        text = (transcription.text or "").strip()

        if len(text.split()) < 3:
            print(f"  Transcript too short ({len(text.split())} words) — using Vision OCR only")
            return ""

        if _is_repetition_loop(text):
            print(f"  Transcript looks like a repetition-loop hallucination — discarding")
            return ""

        print(f"  Transcript: {len(text.split())} words")
        return text

    except Exception as e:
        logger.warning("Whisper transcription failed: %s", e)
        return ""
    finally:
        if os.path.exists(audio_path):
            try:
                os.unlink(audio_path)
            except Exception:
                pass


# ── Image handling (from adaptability_agent.py:550–556 + vision call) ────────

def _handle_image(path: str) -> dict:
    """Extract base64 image data + run vision to get on_screen_text."""
    ext_map = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".gif": "gif", ".webp": "webp"}
    suffix = Path(path).suffix.lower()
    with open(path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    media_type = f"image/{ext_map.get(suffix, 'jpeg')}"
    # Reuse vision analysis on the single image
    vision = _analyze_frames_vision([img_b64])
    on_screen_text = vision.get("on_screen_text", "") or ""

    return {
        "type": "image",
        "transcript": "",
        "on_screen_text": on_screen_text,
        "original_source_text": f"On-screen text:\n{on_screen_text}" if on_screen_text else "",
        "caption": "",
    }


# ── Carousel ──────────────────────────────────────────────────────────────────

def _process_carousel(tmp_dir: str, files: list, url: str) -> dict:
    slides = []
    source_parts = []

    for i, fname in enumerate(files, start=1):
        path = os.path.join(tmp_dir, fname)
        ext = Path(path).suffix.lower()
        if ext in _IMAGE_EXTENSIONS:
            obj = _handle_image(path)
        else:
            obj = _process_video(path)
            slides.append({"index": i, "type": "video"})
        text = obj.get("original_source_text", "")
        if text:
            source_parts.append(f"Slide {i}/{len(files)}:\n{text}")

    return {
        "type": "carousel",
        "num_slides": len(files),
        "slides": slides,
        "transcript": "",
        "on_screen_text": "",
        "original_source_text": "\n\n".join(source_parts),
        "caption": "",
        "source_url": url,
    }
