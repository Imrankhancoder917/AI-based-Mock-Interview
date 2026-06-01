from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os

import requests


GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str | None = None
    provider: str = "groq"
    model: str = "whisper-large-v3-turbo"


class WhisperService:
    """Transcribes browser-recorded audio using Groq Whisper with a small HTTP client.

    The implementation keeps latency low by streaming the recorded blob directly to
    Groq's transcription endpoint without any local model initialization.
    """

    def __init__(self, api_key: str | None = None, model: str = "whisper-large-v3-turbo", timeout: int = 60):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.model = model
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def transcribe(self, audio_file, filename: str = "recording.webm", language: str = "en") -> TranscriptionResult:
        if not self.is_configured:
            raise RuntimeError("GROQ_API_KEY is required for speech transcription.")

        content, content_type = self._read_audio(audio_file)
        response = requests.post(
            GROQ_TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            data={
                "model": self.model,
                "language": language,
                "response_format": "json",
                "temperature": 0,
            },
            files={"file": (filename, BytesIO(content), content_type or "application/octet-stream")},
            timeout=self.timeout,
        )
        response.raise_for_status()

        payload = response.json()
        transcript = str(payload.get("text", "")).strip()
        detected_language = payload.get("language") or language

        return TranscriptionResult(text=transcript, language=detected_language, provider="groq", model=self.model)

    def _read_audio(self, audio_file) -> tuple[bytes, str | None]:
        if hasattr(audio_file, "read"):
            try:
                position = audio_file.tell()
            except Exception:  # pragma: no cover - depends on storage object
                position = None

            content = audio_file.read()
            if position is not None:
                try:
                    audio_file.seek(position)
                except Exception:  # pragma: no cover - depends on storage object
                    pass
            return content, getattr(audio_file, "content_type", None)

        if isinstance(audio_file, (bytes, bytearray)):
            return bytes(audio_file), None

        raise TypeError("Unsupported audio input type for transcription.")