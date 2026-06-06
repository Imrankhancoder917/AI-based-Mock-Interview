from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
import asyncio
import base64
import os
from typing import Optional
import logging
import threading
import queue


@dataclass(slots=True)
class SpeechResult:
    text: str
    audio_bytes: bytes
    mime_type: str = "audio/mpeg"
    provider: str = "edge-tts"


class TTSService:
    """Generates short MP3 responses using edge-tts (Microsoft neural voices).

    The public API is kept compatible with the previous implementation so
    callers do not need to change. This implementation uses the en-GB-RyanNeural
    voice (Paul Bettany / JARVIS style) by default and returns MP3 bytes for
    browser playback.
    """

    def __init__(self, language: str = "en-US", slow: bool = False, voice: Optional[str] = None):
        self.language = language
        self.slow = slow
        # prefer explicit voice or fallback to en-GB-RyanNeural (Paul Bettany / JARVIS style)
        self.voice = voice or os.environ.get("TTS_VOICE", "en-GB-RyanNeural")

    def synthesize(self, text: str, language: str | None = None, slow: bool | None = None) -> SpeechResult:
        normalized_text = self._normalize_text(text)
        audio_bytes = _cached_audio_edge(normalized_text, self.voice)
        return SpeechResult(text=normalized_text, audio_bytes=audio_bytes)

    def synthesize_base64(self, text: str, language: str | None = None, slow: bool | None = None) -> dict:
        result = self.synthesize(text=text, language=language, slow=slow)

        encoded = base64.b64encode(result.audio_bytes).decode("ascii")
        return {
            "text": result.text,
            "mime_type": result.mime_type,
            "provider": result.provider,
            "audio_base64": encoded,
            "data_url": f"data:{result.mime_type};base64,{encoded}",
        }

    def _normalize_text(self, text: str) -> str:
        return " ".join(text.split()).strip()


@lru_cache(maxsize=256)
def _cached_audio_edge(text: str, voice: str) -> bytes:
    """Synchronous wrapper that synthesizes speech via edge-tts async API and returns MP3 bytes.

    This function attempts to run the async synth function in a fresh event loop so it is
    safe to call from synchronous Flask request contexts.
    """
    logger = logging.getLogger(__name__)

    def _run_coro_in_thread(coro_func, *coro_args):
        q: "queue.Queue[tuple[bool, object]]" = queue.Queue()

        def _target():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(coro_func(*coro_args))
                q.put((True, result))
            except Exception as e:
                q.put((False, e))
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        ok, value = q.get()
        if not ok:
            raise value
        return value

    # Always run edge-tts in a separate thread with its own event loop. This
    # avoids issues when the Flask server or other frameworks already have a
    # running asyncio event loop in the main thread (which makes
    # `asyncio.run`/new loop usage problematic).
    try:
        return _run_coro_in_thread(_edge_synthesize_bytes, text, voice)
    except Exception:
        logger.exception("edge-tts synthesis failed")
        raise


async def _edge_synthesize_bytes(text: str, voice: str) -> bytes:
    """Async helper that streams audio from edge-tts and returns concatenated MP3 bytes."""
    try:
        import edge_tts
    except Exception as exc:
        raise RuntimeError("edge-tts is required for TTS but is not installed: " + str(exc))

    communicate = edge_tts.Communicate(text, voice=voice)
    buffer = BytesIO()

    async for message in communicate.stream():
        # message can be dict-like or tuple/list depending on version
        mtype = None
        data = None
        if isinstance(message, dict):
            mtype = message.get("type")
            data = message.get("data")
        elif isinstance(message, (list, tuple)) and len(message) >= 2:
            mtype, data = message[0], message[1]

        if mtype == "audio":
            # data may be bytes or base64 string
            if isinstance(data, (bytes, bytearray)):
                buffer.write(data)
            elif isinstance(data, str):
                # base64 encoded audio
                try:
                    buffer.write(base64.b64decode(data))
                except Exception:
                    # ignore malformed chunks
                    continue

    return buffer.getvalue()