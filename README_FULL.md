# InterviewForge — Full Project Reference

This file consolidates the entire project into a single reference: overview, setup and the full source code for each module so you can inspect or copy everything from one place.

---

## Project Overview

InterviewForge is a Flask-based interview practice platform with:
- Adaptive question generation and scoring (deterministic local heuristics)
- Resume and job-description parsing
- Speech transcription (Groq/Groq Whisper) and TTS (gTTS)
- PDF report generation (ReportLab)
- SQLAlchemy models with SQLite/MySQL support

---

## Prerequisites

- Python 3.11+ (3.14 used in local test)
- pip
- Optional: MySQL server (for production), or use bundled SQLite for local dev

---

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### `/services/adaptive_engine.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
import itertools
import random
import re
from typing import Iterable


ROLE_TEMPLATES = {
	"engineering": [
		"You shipped {skill} in {project}. Why did you choose that approach over the obvious alternative?",
		"Walk me through the hardest tradeoff you made in {project}. What broke first, and how did you fix it?",
		"Your resume mentions {skill}. Explain the system design decisions behind that work as if I were reviewing the architecture doc.",
		"If I pressure-tested the latency or reliability of {project}, where would the bottleneck likely appear and why?",
	],
	"product": [
		"You led {project}. How did you decide which user problem was worth solving first, and what evidence changed your mind?",
		"What was the hardest stakeholder tradeoff in {project}, and how did you keep the plan defensible?",
		"Why did you prioritize {skill} in that product decision instead of a faster shortcut?",
		"If launch metrics had missed target, what would you have instrumented first and why?",
	],
	"data": [
		"In {project}, you used {skill}. What assumptions mattered most, and how did you validate them?",
		"Tell me about the metrics or experiments that actually changed the decision in {project}.",
		"If the model or dashboard drifted, how would you detect it before the business noticed?",
		"Why was {skill} the right approach rather than a simpler baseline?",
	],
	"general": [
		"You worked on {project}. What is the most defensible technical or business tradeoff you made there?",
		"Why was {skill} the right choice for that problem instead of a simpler or more fashionable option?",
		"What would you do differently if this project had to survive a real production incident?",
		"Walk me through the exact decision that gave this project its edge over alternatives.",
	],
}

TRAP_PATTERNS = [
	"You said {skill} was the best choice. Why would that be a bad decision for this system?",
	"If the interviewer challenged your assumption in {project}, what counterexample would you offer?",
	"Which part of your answer is most likely to fail under scale or under pressure?",
	"What would happen if the team removed the thing you claimed was critical?",
]

FOLLOW_UP_PATTERNS = [
	"What exact metric changed after that decision?",
	"Why was that the right tradeoff for the team at the time?",
	"What would you tell a senior engineer who disagreed with you?",
	"What part of the solution is still fragile today?",
]


@dataclass(slots=True)
class InterviewQuestion:
	prompt: str
	kind: str
	difficulty: int
	expected_signals: list[str] = field(default_factory=list)
	follow_up_seed: str = ""
	trap: bool = False


@dataclass(slots=True)
class InterviewContext:
	resume_profile: dict
	job_description: dict | None = None
	role_family: str = "general"
	difficulty: int = 5
	session_history: list[dict] = field(default_factory=list)


class AdaptiveEngine:
	"""Generates interviewer-style prompts and adapts difficulty based on session state."""

	def __init__(self, seed: int | None = None):
		self.random = random.Random(seed)

	def build_role_family(self, resume_profile: dict, job_description: dict | None = None) -> str:
		resume_text = self._flatten_profile(resume_profile)
		jd_text = self._flatten_profile(job_description or {})
		combined = f"{resume_text} {jd_text}".lower()

		if any(token in combined for token in ["product manager", "product designer", "pm", "roadmap", "stakeholder"]):
			return "product"
		if any(token in combined for token in ["data", "analytics", "model", "experiment", "sql", "pipeline"]):
			return "data"
		if any(token in combined for token in ["engineer", "backend", "frontend", "platform", "system", "api", "architecture"]):
			return "engineering"
		return "general"

	def generate_resume_question(self, context: InterviewContext) -> InterviewQuestion:
		project = self._pick_project(context.resume_profile)
		skill = self._pick_skill(context.resume_profile)
		template = self._pick_template(context.role_family)
		prompt = template.format(project=project, skill=skill)
		return InterviewQuestion(
			prompt=prompt,
			kind="resume_based",
			difficulty=context.difficulty,
			expected_signals=[skill, project],
			follow_up_seed=project,
		)

	def generate_jd_question(self, context: InterviewContext) -> InterviewQuestion:
		jd = context.job_description or {}
		required_skills = self._list_from_profile(jd, ["required_skills", "technologies"])
		responsibilities = self._list_from_profile(jd, ["responsibilities"])
		skill = self._pick_from_list(required_skills, fallback=self._pick_skill(context.resume_profile))
		responsibility = self._pick_from_list(responsibilities, fallback="the role")

		prompt = (
			f"This role emphasizes {skill}. Walk me through how you would handle {responsibility.lower()} "
			f"without creating avoidable technical debt or stakeholder churn."
		)

		return InterviewQuestion(
			prompt=prompt,
			kind="jd_based",
			difficulty=max(context.difficulty, 5),
			expected_signals=[skill, responsibility],
			follow_up_seed=responsibility,
		)

	def generate_follow_up_question(self, base_question: InterviewQuestion, answer: str, evaluation_score: int) -> InterviewQuestion:
		seed = base_question.follow_up_seed or self._compact_phrase(base_question.prompt)
		if evaluation_score >= 8 and len(answer.split()) >= 40:
			template = self.random.choice(["What would you do if that approach had to scale 10x?", "What is the weakest part of that solution under load?", "Which tradeoff did you intentionally accept?"])
		elif evaluation_score >= 5:
			template = self.random.choice(FOLLOW_UP_PATTERNS)
		else:
			template = f"You mentioned {seed}. Can you give me the concrete example I can verify?"

		return InterviewQuestion(
			prompt=template,
			kind="follow_up",
			difficulty=min(10, base_question.difficulty + 1),
			expected_signals=base_question.expected_signals,
			follow_up_seed=seed,
		)

	def generate_trap_question(self, context: InterviewContext, base_question: InterviewQuestion | None = None) -> InterviewQuestion:
		project = self._pick_project(context.resume_profile)
		skill = self._pick_skill(context.resume_profile)
		template = self.random.choice(TRAP_PATTERNS)
		prompt = template.format(project=project, skill=skill)

		if base_question is not None:
			prompt = f"{base_question.prompt} Now challenge your own answer: {prompt}"

		return InterviewQuestion(
			prompt=prompt,
			kind="trap",
			difficulty=min(10, context.difficulty + 2),
			expected_signals=[skill, project, "tradeoff", "risk"],
			follow_up_seed=project,
			trap=True,
		)

	def adapt_difficulty(self, current_difficulty: int, score: int, history: Iterable[dict] | None = None) -> int:
		history = list(history or [])
		adjusted = current_difficulty

		if score >= 9:
			adjusted += 2
		elif score >= 7:
			adjusted += 1
		elif score <= 4:
			adjusted -= 1

		if history:
			recent_scores = [item.get("score", 0) for item in history[-3:]]
			if recent_scores and sum(recent_scores) / len(recent_scores) < 5:
				adjusted -= 1

		return max(1, min(10, adjusted))

	def build_next_question(self, context: InterviewContext) -> InterviewQuestion:
		resume_weight = self._profile_strength(context.resume_profile)
		jd_weight = self._profile_strength(context.job_description or {})

		if context.session_history and len(context.session_history) % 4 == 3:
			return self.generate_trap_question(context, self._last_question(context.session_history))

		if jd_weight >= resume_weight and context.job_description:
			return self.generate_jd_question(context)

		return self.generate_resume_question(context)

	def _pick_template(self, role_family: str) -> str:
		templates = ROLE_TEMPLATES.get(role_family, ROLE_TEMPLATES["general"])
		return self.random.choice(templates)

	def _pick_skill(self, profile: dict) -> str:
		skills = self._list_from_profile(profile, ["skills", "required_skills", "technologies"])
		return self._pick_from_list(skills, fallback="your core stack")

	def _pick_project(self, profile: dict) -> str:
		projects = self._list_from_profile(profile, ["projects", "experience"])
		return self._pick_from_list(projects, fallback="your most relevant project")

	def _pick_from_list(self, values: list[str], fallback: str) -> str:
		cleaned = [self._compact_phrase(item) for item in values if item]
		cleaned = [item for item in cleaned if item]
		if not cleaned:
			return fallback
		return self.random.choice(cleaned[:8])

	def _list_from_profile(self, profile: dict, keys: list[str]) -> list[str]:
		values: list[str] = []
		for key in keys:
			value = profile.get(key)
			if isinstance(value, list):
				values.extend(str(item) for item in value)
			elif isinstance(value, str):
				values.extend([part.strip() for part in re.split(r"[\n,;]", value) if part.strip()])
		return values

	def _flatten_profile(self, profile: dict) -> str:
		if not profile:
			return ""
		chunks = []
		for value in profile.values():
			if isinstance(value, list):
				chunks.extend(str(item) for item in value)
			elif isinstance(value, str):
				chunks.append(value)
		return " ".join(chunks)

	def _profile_strength(self, profile: dict) -> int:
		text = self._flatten_profile(profile).lower()
		score = 0
		for token in ["skills", "projects", "experience", "education", "technologies", "responsibilities"]:
			if token in text:
				score += 1
		return score

	def _compact_phrase(self, text: str) -> str:
		return re.sub(r"\s+", " ", text).strip(" -:\t\n")[:120]

	def _last_question(self, history: list[dict]) -> InterviewQuestion | None:
		if not history:
			return None
		last = history[-1]
		return InterviewQuestion(
			prompt=str(last.get("question", "")),
			kind=str(last.get("kind", "resume_based")),
			difficulty=int(last.get("difficulty", 5)),
			expected_signals=[str(item) for item in last.get("expected_signals", [])],
			follow_up_seed=str(last.get("follow_up_seed", "")),
			trap=bool(last.get("trap", False)),
		)
```

### `/services/evaluation_service.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Iterable


FAANG_SIGNAL_WORDS = {
	"tradeoff",
	"scalable",
	"latency",
	"reliability",
	"observability",
	"ownership",
	"debt",
	"impact",
	"architecture",
	"migration",
	"refactor",
	"latency",
	"throughput",
	"benchmark",
	"root cause",
	"debug",
	"cache",
	"failure",
	"metric",
	"experiment",
	"prioritize",
	"consensus",
	"stakeholder",
}

SENIORITY_MARKERS = {
	"senior": 1.15,
	"staff": 1.25,
	"lead": 1.18,
	"principal": 1.28,
	"manager": 1.12,
}


@dataclass(slots=True)
class AnswerEvaluation:
	score: int
	reasoning: str
	strengths: list[str] = field(default_factory=list)
	gaps: list[str] = field(default_factory=list)
	follow_up: str = ""
	red_flags: list[str] = field(default_factory=list)


class EvaluationService:
	"""Scores interview answers with structured heuristics.

	The service is intentionally deterministic so it can operate without
	external model dependencies while still producing interview-grade feedback.
	"""

	def score_answer(
		self,
		question: str,
		answer: str,
		expected_signals: Iterable[str] | None = None,
		difficulty: int = 5,
		trap_mode: bool = False,
	) -> AnswerEvaluation:
		answer_clean = self._normalize(answer)
		question_clean = self._normalize(question)
		expected = [self._normalize(item) for item in (expected_signals or []) if item]

		if not answer_clean:
			return AnswerEvaluation(
				score=0,
				reasoning="The answer was empty, so no signal could be evaluated.",
				gaps=["No substantive answer provided"],
				follow_up=self._follow_up_for_gap(question, expected),
				red_flags=["Empty response"],
			)

		token_count = len(answer_clean.split())
		sentence_count = max(1, len(re.findall(r"[.!?]+", answer)))
		specificity = self._specificity_score(answer_clean)
		relevance = self._relevance_score(answer_clean, expected, question_clean)
		structure = self._structure_score(answer, token_count, sentence_count)
		seniority = self._seniority_score(answer_clean)
		faang_density = self._faang_density(answer_clean)

		raw_score = (specificity * 2.1) + (relevance * 3.5) + (structure * 1.6) + (seniority * 1.1) + (faang_density * 1.7)

		if trap_mode:
			raw_score *= 0.95 if self._contains_confident_but_empty_claim(answer_clean) else 1.0

		difficulty_multiplier = 0.92 + (difficulty * 0.018)
		score = max(0, min(10, round((raw_score / 10) * difficulty_multiplier, 1)))

		strengths = self._strengths(answer_clean, expected, specificity, relevance, structure, faang_density)
		gaps = self._gaps(answer_clean, expected, specificity, relevance, structure)
		reasoning = self._build_reasoning(score, strengths, gaps)
		follow_up = self._follow_up_for_gap(question, expected, strengths=strengths, gaps=gaps)
		red_flags = self._red_flags(answer_clean, trap_mode)

		return AnswerEvaluation(
			score=int(math.floor(score)),
			reasoning=reasoning,
			strengths=strengths[:4],
			gaps=gaps[:4],
			follow_up=follow_up,
			red_flags=red_flags[:3],
		)

	def generate_feedback(self, evaluation: AnswerEvaluation, question: str) -> str:
		opening = f"You handled the prompt: {question[:95].rstrip()}"
		score_line = f"Score: {evaluation.score}/10."

		if evaluation.score >= 8:
			tone = "Strong response. You gave a focused answer with enough signal to indicate real ownership."
		elif evaluation.score >= 5:
			tone = "Decent direction, but the answer needs more specificity, tradeoffs, or evidence of impact."
		else:
			tone = "The response was too shallow for a serious interviewer. Tighten the structure and anchor it in concrete examples."

		next_steps = []
		if evaluation.gaps:
			next_steps.append(f"Improve: {evaluation.gaps[0].lower()}")
		if evaluation.follow_up:
			next_steps.append(f"Follow-up practice: {evaluation.follow_up}")
		if evaluation.red_flags:
			next_steps.append(f"Watch out for: {evaluation.red_flags[0].lower()}")

		return "\n".join([opening, score_line, tone, *next_steps])

	def _normalize(self, text: str) -> str:
		return re.sub(r"\s+", " ", text.lower()).strip()

	def _specificity_score(self, answer: str) -> float:
		patterns = [
			r"\b\d+%\b",
			r"\b\d+(?:\.\d+)?x\b",
			r"\b\d+\b",
			r"\b(days?|weeks?|months?|users?|requests?|transactions?|latency|ms|seconds?)\b",
			r"\b(spring boot|node\\.js|postgresql|redis|kafka|docker|kubernetes|aws|azure|gcp)\b",
		]
		hits = sum(1 for pattern in patterns if re.search(pattern, answer))
		length_bonus = min(1.0, len(answer.split()) / 120)
		return min(3.0, hits * 0.85 + length_bonus * 1.2)

	def _relevance_score(self, answer: str, expected: list[str], question: str) -> float:
		if not expected:
			return 1.5 if len(answer.split()) > 40 else 0.8

		hit_count = 0
		for signal in expected:
			if signal in answer:
				hit_count += 1

		if hit_count == 0:
			if any(token in answer for token in question.split()[:8]):
				return 1.0
			return 0.2

		return min(3.5, 0.9 + hit_count * 0.9)

	def _structure_score(self, answer: str, token_count: int, sentence_count: int) -> float:
		has_transition = any(marker in answer for marker in ["first", "then", "because", "so", "therefore", "however", "for example"])
		concise_ratio = min(1.0, token_count / 140)
		sentence_bonus = min(1.0, sentence_count / 4)
		return min(2.0, (0.7 if has_transition else 0.2) + concise_ratio + sentence_bonus * 0.4)

	def _seniority_score(self, answer: str) -> float:
		signal = 0.0
		for marker, value in SENIORITY_MARKERS.items():
			if marker in answer:
				signal = max(signal, value)
		if "tradeoff" in answer or "stakeholder" in answer or "alignment" in answer:
			signal = max(signal, 1.0)
		return signal

	def _faang_density(self, answer: str) -> float:
		hits = sum(1 for term in FAANG_SIGNAL_WORDS if term in answer)
		return min(1.8, hits * 0.28)

	def _contains_confident_but_empty_claim(self, answer: str) -> bool:
		phrases = ["I know it well", "very familiar", "I have used it a lot", "I can do anything", "easy problem"]
		return any(phrase.lower() in answer for phrase in phrases)

	def _strengths(self, answer: str, expected: list[str], specificity: float, relevance: float, structure: float, faang_density: float) -> list[str]:
		strengths = []
		if specificity >= 1.8:
			strengths.append("Used concrete details and implementation signals")
		if relevance >= 2.0:
			strengths.append("Stayed aligned to the prompt and domain context")
		if structure >= 1.2:
			strengths.append("Response had a usable structure")
		if faang_density >= 0.8:
			strengths.append("Used interviewer-grade terminology around tradeoffs and impact")
		if expected and any(signal in answer for signal in expected[:3]):
			strengths.append("Referenced expected signals from the source material")
		return strengths

	def _gaps(self, answer: str, expected: list[str], specificity: float, relevance: float, structure: float) -> list[str]:
		gaps = []
		if specificity < 1.0:
			gaps.append("Add numbers, constraints, or implementation details")
		if relevance < 1.0:
			gaps.append("Tie the answer back to the actual system or experience")
		if structure < 1.0:
			gaps.append("Answer in a sharper problem / action / outcome pattern")
		if expected and not any(signal in answer for signal in expected):
			gaps.append("Cover the most important expected concepts explicitly")
		return gaps

	def _follow_up_for_gap(self, question: str, expected: list[str], strengths: list[str] | None = None, gaps: list[str] | None = None) -> str:
		strengths = strengths or []
		gaps = gaps or []
		if gaps:
			return "What was the main tradeoff you considered, and what metric told you that decision was correct?"
		if expected:
			topic = expected[0].replace("node.js", "Node.js")
			return f"Can you walk me through a concrete decision you made around {topic} and what you would change if you had one more week?"
		if strengths:
			return "What was the hardest constraint in that project, and how did you validate your solution under pressure?"
		return f"What is the most defensible technical tradeoff in your answer to '{question[:60]}'?"

	def _red_flags(self, answer: str, trap_mode: bool) -> list[str]:
		red_flags = []
		if trap_mode and any(term in answer for term in ["always", "never", "perfect", "trivial"]):
			red_flags.append("Overconfident language can signal shallow reasoning")
		if len(answer.split()) < 20:
			red_flags.append("Very short answer for a senior-level prompt")
		if """I don't know""" in answer.lower():
			red_flags.append("Needs a better recovery strategy for uncertainty")
		return red_flags

	def _build_reasoning(self, score: int, strengths: list[str], gaps: list[str]) -> str:
		if score >= 8:
			prefix = "Strong interviewer signal"
		elif score >= 5:
			prefix = "Mixed interviewer signal"
		else:
			prefix = "Weak interviewer signal"

		details = []
		if strengths:
			details.append(f"strengths: {strengths[0].lower()}")
		if gaps:
			details.append(f"gaps: {gaps[0].lower()}")

		if details:
			return f"{prefix}. " + " ".join(details).capitalize()
		return f"{prefix}. The answer was internally consistent but limited in depth."
```

### `/services/tts_service.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO

from gtts import gTTS


@dataclass(slots=True)
class SpeechResult:
	text: str
	audio_bytes: bytes
	mime_type: str = "audio/mpeg"
	provider: str = "gtts"


class TTSService:
	"""Generates short MP3 responses using gTTS and caches repeated phrases."""

	def __init__(self, language: str = "en", slow: bool = False):
		self.language = language
		self.slow = slow

	def synthesize(self, text: str, language: str | None = None, slow: bool | None = None) -> SpeechResult:
		normalized_text = self._normalize_text(text)
		audio_bytes = _cached_audio(normalized_text, language or self.language, self.slow if slow is None else slow)
		return SpeechResult(text=normalized_text, audio_bytes=audio_bytes)

	def synthesize_base64(self, text: str, language: str | None = None, slow: bool | None = None) -> dict:
		result = self.synthesize(text=text, language=language, slow=slow)
		import base64

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
def _cached_audio(text: str, language: str, slow: bool) -> bytes:
	buffer = BytesIO()
	gTTS(text=text, lang=language, slow=slow).write_to_fp(buffer)
	return buffer.getvalue()
```

### `/services/whisper_service.py`

```python
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
```

### `/reports.py`

```python
from __future__ import annotations

from io import BytesIO

from flask import Blueprint, Response, current_app, render_template, request, session, url_for, send_file
from flask_login import current_user, login_required

from report_service import ReportService


reports_bp = Blueprint("reports", __name__)


def _build_report_context() -> tuple[dict, dict, dict]:
	interview_state = session.get("interview_state", {})
	resume_profile = interview_state.get("resume_profile") or session.get("resume_profile") or {}
	job_description = interview_state.get("job_description") or session.get("job_description") or {}
	return interview_state, resume_profile, job_description


@reports_bp.route("/reports/latest")
@login_required
def latest_report():
	interview_state, resume_profile, job_description = _build_report_context()
	report = ReportService().build_report(
		user_name=current_user.full_name,
		interview_state=interview_state,
		resume_profile=resume_profile,
		job_description=job_description,
	)

	return render_template(
		"report.html",
		title="Interview Report | InterviewForge",
		page_type="report",
		body_class="report-page",
		report=report,
		interview_state=interview_state,
		pdf_url=url_for("reports.download_report_pdf"),
		interview_url=url_for("interview_room"),
	)


@reports_bp.route("/reports/latest.pdf")
@login_required
def download_report_pdf():
	interview_state, resume_profile, job_description = _build_report_context()
	report = ReportService().build_report(
		user_name=current_user.full_name,
		interview_state=interview_state,
		resume_profile=resume_profile,
		job_description=job_description,
	)
	pdf_bytes = ReportService().build_pdf(report)

	return send_file(
		BytesIO(pdf_bytes),
		mimetype="application/pdf",
		as_attachment=True,
		download_name=f"InterviewForge-Report-{current_user.full_name.replace(' ', '-')}.pdf",
		max_age=0,
	)


@reports_bp.route("/api/reports/latest")
@login_required
def latest_report_json():
	interview_state, resume_profile, job_description = _build_report_context()
	report = ReportService().build_report(
		user_name=current_user.full_name,
		interview_state=interview_state,
		resume_profile=resume_profile,
		job_description=job_description,
	)
	return {
		"ok": True,
		"report": {
			"candidate_name": report.candidate_name,
			"overall_score": report.overall_score,
			"technical_score": report.technical_score,
			"communication_score": report.communication_score,
			"strengths": report.strengths,
			"weaknesses": report.weaknesses,
			"improvement_roadmap": report.improvement_roadmap,
			"resume_honesty_check": report.resume_honesty_check,
			"transcript_summary": report.transcript_summary,
			"session_highlights": report.session_highlights,
			"question_count": report.question_count,
			"average_answer_length": report.average_answer_length,
			"average_evaluation_score": report.average_evaluation_score,
		},
	}
```

### `/report_service.py`

```python
(file content shown earlier in this README under report service)
```

### `/requirements.txt`

```text
Flask>=3.0,<4.0
Flask-Login>=0.6,<1.0
Flask-SQLAlchemy>=3.1,<4.0
bcrypt>=4.1,<5.0
PyMySQL>=1.1,<2.0
PyMuPDF>=1.24,<2.0
python-docx>=1.1,<2.0
easyocr>=1.7,<2.0
Pillow>=10.0,<11.0
gTTS>=2.5,<3.0
requests>=2.32,<3.0
reportlab>=4.2,<5.0
python-dotenv>=1.0,<2.0
```

### `/services/ai_service.py`

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .adaptive_engine import AdaptiveEngine, InterviewContext, InterviewQuestion
from .evaluation_service import AnswerEvaluation, EvaluationService


@dataclass(slots=True)
class InterviewTurn:
	question: InterviewQuestion
	answer: str = ""
	evaluation: AnswerEvaluation | None = None


@dataclass(slots=True)
class InterviewRound:
	question: dict
	follow_up: dict | None = None
	evaluation: dict | None = None
	feedback: str = ""


class AIService:
	"""Facade that coordinates question generation, evaluation, and feedback."""

	def __init__(self, seed: int | None = None):
		self.engine = AdaptiveEngine(seed=seed)
		self.evaluator = EvaluationService()

	def create_context(self, resume_profile: dict, job_description: dict | None = None, difficulty: int = 5, session_history: list[dict] | None = None) -> InterviewContext:
		role_family = self.engine.build_role_family(resume_profile, job_description)
		return InterviewContext(
			resume_profile=resume_profile,
			job_description=job_description,
			role_family=role_family,
			difficulty=difficulty,
			session_history=session_history or [],
		)

	def generate_question(self, resume_profile: dict, job_description: dict | None = None, difficulty: int = 5, session_history: list[dict] | None = None) -> InterviewQuestion:
		context = self.create_context(resume_profile, job_description, difficulty, session_history)
		return self.engine.build_next_question(context)

	def evaluate_answer(
		self,
		question: InterviewQuestion,
		answer: str,
		difficulty: int | None = None,
	) -> AnswerEvaluation:
		return self.evaluator.score_answer(
			question=question.prompt,
			answer=answer,
			expected_signals=question.expected_signals,
			difficulty=difficulty or question.difficulty,
			trap_mode=question.trap,
		)

	def generate_round(
		self,
		resume_profile: dict,
		job_description: dict | None = None,
		answer: str = "",
		current_question: InterviewQuestion | None = None,
		session_history: list[dict] | None = None,
		difficulty: int = 5,
	) -> InterviewRound:
		question = current_question or self.generate_question(resume_profile, job_description, difficulty, session_history)
		evaluation = self.evaluate_answer(question, answer, difficulty=difficulty) if answer else None

		follow_up = None
		feedback = ""
		if evaluation is not None:
			next_difficulty = self.engine.adapt_difficulty(question.difficulty, evaluation.score, session_history or [])
			follow_up_question = self.engine.generate_follow_up_question(question, answer, evaluation.score)
			follow_up = asdict(follow_up_question)
			feedback = self.evaluator.generate_feedback(evaluation, question.prompt)
			follow_up["difficulty"] = next_difficulty

		return InterviewRound(
			question=asdict(question),
			follow_up=follow_up,
			evaluation=asdict(evaluation) if evaluation else None,
			feedback=feedback,
		)

	def generate_trap_question(self, resume_profile: dict, job_description: dict | None = None, difficulty: int = 7, session_history: list[dict] | None = None) -> InterviewQuestion:
		context = self.create_context(resume_profile, job_description, difficulty, session_history)
		return self.engine.generate_trap_question(context)

	def score_text_answer(self, question_text: str, answer: str, expected_signals: list[str] | None = None, difficulty: int = 5, trap_mode: bool = False) -> dict:
		evaluation = self.evaluator.score_answer(question_text, answer, expected_signals, difficulty, trap_mode)
		return {
			"score": evaluation.score,
			"reasoning": evaluation.reasoning,
			"strengths": evaluation.strengths,
			"gaps": evaluation.gaps,
			"follow_up": evaluation.follow_up,
			"red_flags": evaluation.red_flags,
			"feedback": self.evaluator.generate_feedback(evaluation, question_text),
		}
```

### `/parsers.py`

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RESUME_SECTION_ALIASES = {
	"skills": {"skills", "technical skills", "core skills", "competencies", "proficiencies"},
	"projects": {"projects", "selected projects", "project experience", "portfolio"},
	"certifications": {"certifications", "certificates", "licenses", "accreditations"},
	"education": {"education", "academic background", "academics", "qualifications"},
	"experience": {"experience", "work experience", "professional experience", "employment history", "work history"},
}

JD_SECTION_ALIASES = {
	"required_skills": {"requirements", "required skills", "what you need", "qualifications"},
	"responsibilities": {"responsibilities", "what you'll do", "what you will do", "role", "about the role"},
	"technologies": {"tech stack", "technologies", "tools", "preferred technologies", "stack"},
}

SKILL_TOKENS = {
	"python", "flask", "fastapi", "django", "sql", "sqlalchemy", "postgresql", "mysql", "mongodb",
	"aws", "azure", "gcp", "docker", "kubernetes", "react", "javascript", "typescript", "html", "css",
	"node.js", "nodejs", "rest", "graphql", "git", "ci/cd", "machine learning", "nlp", "llm",
}


@dataclass
class ParsedDocument:
	extracted_text: str
	sections: dict[str, list[str]]


def _lazy_imports():
	import fitz  # type: ignore
	from docx import Document  # type: ignore
	from PIL import Image  # type: ignore
	return fitz, Document, Image


def _clean_lines(text: str) -> list[str]:
	lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
	return [line for line in lines if line]


def _normalize_heading(value: str) -> str:
	return re.sub(r"[^a-z0-9\s]", "", value.lower()).strip()


def _section_match(heading: str, aliases: set[str]) -> bool:
	normalized = _normalize_heading(heading)
	return any(normalized == alias or normalized.startswith(alias + " ") for alias in aliases)


def _extract_section_blocks(lines: list[str], aliases: dict[str, set[str]]) -> dict[str, list[str]]:
	sections = {key: [] for key in aliases}
	active_key = None

	for line in lines:
		if _section_match(line, set().union(*aliases.values())):
			for section_name, section_aliases in aliases.items():
				if _section_match(line, section_aliases):
					active_key = section_name
					break
			continue

		if active_key:
			if re.fullmatch(r"[A-Z][A-Za-z\s/&-]{2,}", line) and len(line.split()) <= 5:
				active_key = None
				continue
			sections[active_key].append(line)

	return {key: value for key, value in sections.items() if value}


def _section_text(lines: list[str], aliases: set[str]) -> str:
	collecting = False
	collected: list[str] = []

	for line in lines:
		if _section_match(line, aliases):
			collecting = True
			continue
		if collecting and re.fullmatch(r"[A-Z][A-Za-z\s/&-]{2,}", line) and len(line.split()) <= 5:
			break
		if collecting:
			collected.append(line)

	return "\n".join(collected).strip()


def _list_from_text(text: str) -> list[str]:
	parts = re.split(r"[\n•·|;/]", text)
	values = []
	for part in parts:
		cleaned = re.sub(r"^[-*]\s*", "", part).strip()
		if cleaned:
			values.append(cleaned)
	return values


def _extract_skills_from_text(text: str) -> list[str]:
	lowered = text.lower()
	found = []
	for token in sorted(SKILL_TOKENS, key=len, reverse=True):
		if token in lowered and token not in found:
			found.append(token)
	for match in re.findall(r"\b[A-Za-z][A-Za-z0-9+/.-]{1,}\b", text):
		lowered_match = match.lower()
		if len(lowered_match) > 2 and lowered_match not in found and re.search(r"[A-Z]|\.|/|\+", match):
			found.append(match)
	return found[:20]


def extract_text_from_pdf(file_path: Path) -> str:
	fitz, _, _ = _lazy_imports()
	document = fitz.open(file_path)
	parts = []
	for page in document:
		parts.append(page.get_text("text"))
	return "\n".join(parts)


def extract_text_from_docx(file_path: Path) -> str:
	_, Document, _ = _lazy_imports()
	document = Document(str(file_path))
	return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_text_from_image(file_path: Path) -> str:
	_, _, Image = _lazy_imports()
	import easyocr  # type: ignore

	reader = easyocr.Reader(["en"], gpu=False)
	image = Image.open(file_path)
	results = reader.readtext(image, detail=0, paragraph=True)
	return "\n".join(str(item) for item in results)


def parse_document(file_path: Path, doc_type: str) -> ParsedDocument:
	suffix = file_path.suffix.lower()
	if suffix == ".pdf":
		extracted_text = extract_text_from_pdf(file_path)
	elif suffix == ".docx":
		extracted_text = extract_text_from_docx(file_path)
	else:
		extracted_text = extract_text_from_image(file_path)

	lines = _clean_lines(extracted_text)
	section_aliases = RESUME_SECTION_ALIASES if doc_type == "resume" else JD_SECTION_ALIASES
	sections = _extract_section_blocks(lines, section_aliases)

	return ParsedDocument(extracted_text=extracted_text, sections=sections)


def _resume_result(parsed_document: ParsedDocument) -> dict:
	text = parsed_document.extracted_text
	lines = _clean_lines(text)
	sections = parsed_document.sections

	skills_block = sections.get("skills") or []
	skills_text = "\n".join(skills_block) if skills_block else _section_text(lines, RESUME_SECTION_ALIASES["skills"])

	return {
		"document_type": "resume",
		"summary": {
			"skills": _extract_skills_from_text(skills_text or text),
			"projects": _list_from_text("\n".join(sections.get("projects", []))),
			"certifications": _list_from_text("\n".join(sections.get("certifications", []))),
			"education": _list_from_text("\n".join(sections.get("education", []))),
			"experience": _list_from_text("\n".join(sections.get("experience", []))),
		},
	}


def _jd_result(parsed_document: ParsedDocument) -> dict:
	text = parsed_document.extracted_text
	lines = _clean_lines(text)
	sections = parsed_document.sections
	required_skills_text = "\n".join(sections.get("required_skills", [])) or _section_text(lines, JD_SECTION_ALIASES["required_skills"])
	responsibilities_text = "\n".join(sections.get("responsibilities", [])) or _section_text(lines, JD_SECTION_ALIASES["responsibilities"])
	technologies_text = "\n".join(sections.get("technologies", [])) or _section_text(lines, JD_SECTION_ALIASES["technologies"])

	return {
		"document_type": "jd",
		"summary": {
			"required_skills": _extract_skills_from_text(required_skills_text or text),
			"responsibilities": _list_from_text(responsibilities_text),
			"technologies": _extract_skills_from_text(technologies_text or text),
		},
	}


def parse_uploaded_file(file_path: Path, doc_type: str) -> dict:
	parsed_document = parse_document(file_path, doc_type)
	if doc_type == "resume":
		return _resume_result(parsed_document)
	return _jd_result(parsed_document)
```

Create `.env` (a sample is included in the repo). For local dev the repository is already configured to use SQLite at `/tmp/interviewforge.db`.

---

## Run (development)

```bash
export $(cat .env | xargs)
python3 -m flask run --host=0.0.0.0 --port=5001
# or
python3 app.py
```

If you prefer SQLite local file in the project instance directory, set in `.env`:

```
DATABASE_URL=sqlite:///instance/interviewforge.db
```

---

## Environment (.env)

The repository includes `.env` at project root. Example values used locally:

```
FLASK_APP=app.py
FLASK_ENV=development
SECRET_KEY=change-this-secret-key

DATABASE_URL=sqlite:////tmp/interviewforge.db

GROQ_API_KEY=gsk_... (optional for speech)

PRIMARY_LLM_MODEL=llama-3.3-70b-versatile
SECONDARY_LLM_MODEL=mixtral-8x7b-32768
WHISPER_MODEL=whisper-large-v3

UPLOAD_FOLDER=uploads
REPORT_FOLDER=reports
MAX_CONTENT_LENGTH=16777216

DEFAULT_DIFFICULTY=medium
MAX_QUESTIONS=10
PASS_SCORE_THRESHOLD=7
```

---

## Files (full source)

Below are the main Python files embedded in full. Copy/paste as needed.


### `/app.py`

```python
import os
from pathlib import Path

from flask import Flask, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename
from sqlalchemy.exc import SQLAlchemyError

from config import Config
from extensions import db, login_manager
from models import User
from parsers import parse_uploaded_file
from services import AIService, InterviewQuestion, TTSService, WhisperService
from reports import reports_bp


ALLOWED_EXTENSIONS = {"pdf", "docx", "jpg", "jpeg", "png"}


def _allowed_file(filename: str) -> bool:
	return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _wants_json_response() -> bool:
	return request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.accept_mimetypes


def _normalize_email(email: str) -> str:
	return email.strip().lower()


def _validate_auth_payload(full_name: str, email: str, password: str, confirm_password: str | None = None):
	errors = []

	if not full_name.strip():
		errors.append("Full name is required.")

	if "@" not in email or "." not in email.split("@")[-1]:
		errors.append("Enter a valid email address.")

	if len(password) < 8:
		errors.append("Password must be at least 8 characters.")

	if confirm_password is not None and password != confirm_password:
		errors.append("Passwords do not match.")

	return errors


def _get_interview_state() -> dict:
	return session.get("interview_state", {})


def _set_interview_state(state: dict) -> None:
	session["interview_state"] = state
	session.modified = True


def _upsert_interview_state(**updates) -> dict:
	state = _get_interview_state().copy()
	state.update(updates)
	_set_interview_state(state)
	return state


def _build_resume_profile() -> dict:
	state = _get_interview_state()
	return state.get("resume_profile") or session.get("resume_profile") or {}


def _build_job_profile() -> dict:
	state = _get_interview_state()
	return state.get("job_description") or session.get("job_description") or {}


def _build_history() -> list[dict]:
	return _get_interview_state().get("history", [])


def _default_difficulty() -> int:
	raw_value = str(current_app.config.get("DEFAULT_DIFFICULTY", "medium")).strip().lower()
	if raw_value.isdigit():
		return max(1, min(10, int(raw_value)))
	return {
		"easy": 3,
		"medium": 5,
		"hard": 8,
	}.get(raw_value, 5)


def _get_interview_service() -> AIService:
	return AIService(seed=current_user.id if current_user.is_authenticated else None)


def _get_whisper_service() -> WhisperService:
	return WhisperService()


def _get_tts_service() -> TTSService:
	return TTSService()


def _serialize_question(question: InterviewQuestion) -> dict:
	return {
		"prompt": question.prompt,
		"kind": question.kind,
		"difficulty": question.difficulty,
		"expected_signals": question.expected_signals,
		"follow_up_seed": question.follow_up_seed,
		"trap": question.trap,
	}


def _question_from_payload(payload: dict, default_difficulty: int | None = None) -> InterviewQuestion:
	if default_difficulty is None:
		default_difficulty = _default_difficulty()
	return InterviewQuestion(
		prompt=str(payload.get("prompt", "")),
		kind=str(payload.get("kind", "resume_based")),
		difficulty=int(payload.get("difficulty", default_difficulty)),
		expected_signals=list(payload.get("expected_signals", [])),
		follow_up_seed=str(payload.get("follow_up_seed", "")),
		trap=bool(payload.get("trap", False)),
	)


def create_app() -> Flask:
	app = Flask(__name__, instance_relative_config=True)
	app.config.from_object(Config)

	os.makedirs(app.instance_path, exist_ok=True)

	db.init_app(app)
	login_manager.init_app(app)
	app.register_blueprint(reports_bp)

	with app.app_context():
		try:
			db.create_all()
		except SQLAlchemyError:
			app.logger.warning("Database initialization skipped because the database connection was unavailable.")
		os.makedirs(Path(app.instance_path) / app.config["UPLOAD_FOLDER"], exist_ok=True)
		os.makedirs(Path(app.instance_path) / app.config["REPORT_FOLDER"], exist_ok=True)

	@app.route("/")
	def landing() -> str:
		return render_template("landing.html", title="InterviewForge")

	@app.route("/login", methods=["GET", "POST"])
	def login() -> str:
		if current_user.is_authenticated:
			return redirect(url_for("dashboard"))

		error = None
		email = ""

		if request.method == "POST":
			email = _normalize_email(request.form.get("email", ""))
			password = request.form.get("password", "")

			user = User.query.filter_by(email=email).first()

			if user is None or not user.check_password(password):
				error = "Invalid email or password."
			else:
				login_user(user, remember=True)
				flash(f"Welcome back, {user.full_name.split()[0]}.", "success")
				return redirect(url_for("dashboard"))

		return render_template(
			"login.html",
			title="Login | InterviewForge",
			email=email,
			error=error,
			page_type="auth",
			body_class="auth-page auth-login-page",
		)

	@app.route("/register", methods=["GET", "POST"])
	def register() -> str:
		if current_user.is_authenticated:
			return redirect(url_for("dashboard"))

		error = None
		full_name = ""
		email = ""

		if request.method == "POST":
			full_name = request.form.get("full_name", "").strip()
			email = _normalize_email(request.form.get("email", ""))
			password = request.form.get("password", "")
			confirm_password = request.form.get("confirm_password", "")

			errors = _validate_auth_payload(full_name, email, password, confirm_password)
			if User.query.filter_by(email=email).first() is not None:
				errors.append("An account with that email already exists.")

			if errors:
				error = errors[0]
			else:
				user = User(full_name=full_name, email=email)
				user.set_password(password)
				db.session.add(user)
				db.session.commit()
				login_user(user, remember=True)
				flash("Account created successfully. You are now signed in.", "success")
				return redirect(url_for("dashboard"))

		return render_template(
			"register.html",
			title="Create Account | InterviewForge",
			full_name=full_name,
			email=email,
			error=error,
			page_type="auth",
			body_class="auth-page auth-register-page",
		)

	@app.route("/logout")
	@login_required
	def logout() -> str:
		logout_user()
		flash("You have been signed out.", "info")
		return redirect(url_for("landing"))

	@app.route("/dashboard")
	@login_required
	def dashboard() -> str:
		dashboard_stats = [
			{"label": "Sessions completed", "value": "18", "change": "+12%"},
			{"label": "Interview score", "value": "84", "change": "+6 pts"},
			{"label": "Resume matches", "value": "96%", "change": "+4%"},
			{"label": "Feedback actions", "value": "11", "change": "+3"},
		]

		recent_sessions = [
			{"role": "Product Designer", "mode": "Voice", "score": "91", "status": "Completed", "time": "Today, 09:40"},
			{"role": "Senior Backend Engineer", "mode": "Behavioral", "score": "84", "status": "Completed", "time": "Yesterday, 18:05"},
			{"role": "Data Analyst", "mode": "Resume-based", "score": "78", "status": "Needs review", "time": "Yesterday, 10:30"},
			{"role": "AI Product Manager", "mode": "Mixed", "score": "88", "status": "Completed", "time": "May 21, 16:15"},
		]

		return render_template(
			"dashboard.html",
			title="Dashboard | InterviewForge",
			page_type="dashboard",
			body_class="dashboard-page",
			dashboard_stats=dashboard_stats,
			recent_sessions=recent_sessions,
			user_name=current_user.full_name,
		)

	@app.route("/interview-room")
	@login_required
	def interview_room() -> str:
		interview_service = _get_interview_service()
		resume_profile = _build_resume_profile()
		job_description = _build_job_profile()
		state = _get_interview_state()
		initial_question = state.get("current_question")

		if initial_question is None and (resume_profile or job_description):
			question = interview_service.generate_question(
				resume_profile=resume_profile,
				job_description=job_description,
				difficulty=int(state.get("difficulty", _default_difficulty())),
				session_history=state.get("history", []),
			)
			initial_question = _serialize_question(question)
			_upsert_interview_state(
				resume_profile=resume_profile,
				job_description=job_description,
				difficulty=question.difficulty,
				current_question=initial_question,
			)

		return render_template(
			"interview_room.html",
			title="Interview Room | InterviewForge",
			page_type="interview",
			body_class="interview-page",
			user_name=current_user.full_name,
			has_resume=bool(resume_profile),
			has_jd=bool(job_description),
			role_family=interview_service.create_context(resume_profile, job_description).role_family,
			initial_question=initial_question,
			interview_state=state,
		)

	@app.route("/api/interview/generate-question", methods=["POST"])
	@login_required
	def api_generate_question():
		payload = request.get_json(silent=True) or {}
		resume_profile = payload.get("resume_profile") or _build_resume_profile()
		job_description = payload.get("job_description") or _build_job_profile()
		history = payload.get("session_history") or _build_history()
		difficulty = int(payload.get("difficulty") or _get_interview_state().get("difficulty", _default_difficulty()))

		service = _get_interview_service()
		question = service.generate_question(resume_profile, job_description, difficulty, history)
		serialized_question = _serialize_question(question)

		_upsert_interview_state(
			resume_profile=resume_profile,
			job_description=job_description,
			difficulty=question.difficulty,
			current_question=serialized_question,
		)

		return jsonify({
			"ok": True,
			"question": serialized_question,
			"difficulty": question.difficulty,
			"role_family": service.create_context(resume_profile, job_description, difficulty, history).role_family,
			"progress": len(history),
		})

	@app.route("/api/interview/process-answer", methods=["POST"])
	@login_required
	def api_process_answer():
		payload = request.get_json(silent=True) or {}
		answer = str(payload.get("answer", "")).strip()
		resume_profile = payload.get("resume_profile") or _build_resume_profile()
		job_description = payload.get("job_description") or _build_job_profile()
		history = list(payload.get("session_history") or _build_history())
		difficulty = int(payload.get("difficulty") or _get_interview_state().get("difficulty", _default_difficulty()))
		current_question_data = payload.get("current_question") or _get_interview_state().get("current_question")
		service = _get_interview_service()

		if current_question_data:
			current_question = _question_from_payload(current_question_data, difficulty)
		else:
			current_question = service.generate_question(resume_profile, job_description, difficulty, history)
			current_question_data = _serialize_question(current_question)

		evaluation = service.evaluate_answer(current_question, answer, difficulty=difficulty)
		next_difficulty = service.engine.adapt_difficulty(current_question.difficulty, evaluation.score, history)
		next_question = service.engine.generate_follow_up_question(current_question, answer, evaluation.score)
		feedback = service.evaluator.generate_feedback(evaluation, current_question.prompt)

		history.append({
			"question": current_question.prompt,
			"kind": current_question.kind,
			"difficulty": current_question.difficulty,
			"answer": answer,
			"score": evaluation.score,
			"expected_signals": current_question.expected_signals,
			"follow_up_seed": current_question.follow_up_seed,
			"trap": current_question.trap,
		})

		_upsert_interview_state(
			resume_profile=resume_profile,
			job_description=job_description,
			difficulty=next_difficulty,
			history=history,
			current_question=_serialize_question(next_question),
			last_feedback=feedback,
		)

		return jsonify({
			"ok": True,
			"evaluation": {
				"score": evaluation.score,
				"reasoning": evaluation.reasoning,
				"strengths": evaluation.strengths,
				"gaps": evaluation.gaps,
				"follow_up": evaluation.follow_up,
				"red_flags": evaluation.red_flags,
			},
			"feedback": feedback,
			"next_question": _serialize_question(next_question),
			"difficulty": next_difficulty,
			"progress": len(history),
			"transcript_entry": {
				"question": current_question.prompt,
				"answer": answer,
				"score": evaluation.score,
			},
		})

	@app.route("/api/speech/transcribe", methods=["POST"])
	@login_required
	def api_speech_transcribe():
		audio_file = request.files.get("audio") or request.files.get("file")
		if audio_file is None or audio_file.filename == "":
			return jsonify({"ok": False, "error": "No audio file was provided."}), 400

		language = request.form.get("language", "en")

		try:
			result = _get_whisper_service().transcribe(audio_file, filename=audio_file.filename, language=language)
			return jsonify({
				"ok": True,
				"transcript": result.text,
				"language": result.language,
				"provider": result.provider,
				"model": result.model,
			})
		except Exception as exc:  # pragma: no cover - external API/runtime variability
			return jsonify({"ok": False, "error": str(exc)}), 502

	@app.route("/api/speech/respond", methods=["POST"])
	@login_required
	def api_speech_respond():
		payload = request.get_json(silent=True) or {}
		text = str(payload.get("text", "")).strip()
		language = str(payload.get("language", "en")).strip() or "en"
		slow = bool(payload.get("slow", False))

		if not text:
			return jsonify({"ok": False, "error": "Response text is required."}), 400

		try:
			speech = _get_tts_service().synthesize_base64(text=text, language=language, slow=slow)
			speech["ok"] = True
			return jsonify(speech)
		except Exception as exc:  # pragma: no cover - external API/runtime variability
			return jsonify({"ok": False, "error": str(exc)}), 502

	@app.route("/upload", methods=["GET", "POST"])
	@login_required
	def upload() -> str:
		parsed_result = None
		error = None

		if request.method == "POST":
			document_type = request.form.get("document_type", "resume")
			uploaded_file = request.files.get("document")

			if uploaded_file is None or uploaded_file.filename == "":
				error = "Choose a file before uploading."
			elif not _allowed_file(uploaded_file.filename):
				error = "Only PDF, DOCX, JPG, and PNG files are supported."
			else:
				uploads_dir = Path(app.instance_path) / app.config["UPLOAD_FOLDER"]
				uploads_dir.mkdir(parents=True, exist_ok=True)
				filename = secure_filename(uploaded_file.filename)
				destination = uploads_dir / f"{current_user.id}_{filename}"
				uploaded_file.save(destination)

				try:
					parsed_result = parse_uploaded_file(destination, document_type)
					parsed_result["filename"] = uploaded_file.filename
					parsed_result["document_type"] = document_type

					parsed_summary = parsed_result.get("summary", {})
					if document_type == "resume":
						session["resume_profile"] = parsed_summary
						_upsert_interview_state(resume_profile=parsed_summary)
					else:
						session["job_description"] = parsed_summary
						_upsert_interview_state(job_description=parsed_summary)
					session.modified = True
				except Exception as exc:  # pragma: no cover - runtime dependency/file variability
					error = f"We could not parse that file: {exc}"

			if _wants_json_response():
				if error:
					return jsonify({"ok": False, "error": error}), 400
				return jsonify({"ok": True, "result": parsed_result})

			if error:
				flash(error, "danger")
			else:
				flash("File uploaded and parsed successfully.", "success")

		return render_template(
			"upload.html",
			title="Upload | InterviewForge",
			page_type="upload",
			body_class="upload-page",
			error=error,
			parsed_result=parsed_result,
		)

	return app


app = create_app()


if __name__ == "__main__":
	app.run(debug=app.config["DEBUG"], host="0.0.0.0", port=5000)

---

## Templates

The project's Jinja templates are included below for easy reference.

### `/templates/base.html`

```html
<!doctype html>
<html lang="en">
	<head>
		<meta charset="utf-8" />
		<meta name="viewport" content="width=device-width, initial-scale=1" />
		<meta name="description" content="InterviewForge - AI adaptive mock interviews with resume-aware questions, voice practice, and instant feedback." />
		<title>{{ title or "InterviewForge" }}</title>
		<link rel="preconnect" href="https://fonts.googleapis.com" />
		<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
		<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet" />
		<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous" />
		<link rel="stylesheet" href="{{ url_for('static', filename='css/global.css') }}" />
		{% block page_styles %}{% endblock %}
	</head>
	<body class="{{ body_class or '' }}">
		<div class="site-shell">
			<div class="ambient ambient-one"></div>
			<div class="ambient ambient-two"></div>
				{% if page_type == 'auth' %}
				<header class="site-header auth-header">
					<nav class="navbar auth-nav">
						<div class="container-fluid px-0">
							<a class="navbar-brand brand-mark" href="{{ url_for('landing') }}">
								<span class="brand-icon">IF</span>
								<span>InterviewForge</span>
							</a>
							<div class="auth-nav-links">
								{% if request.endpoint == 'login' %}
								<a class="auth-nav-link" href="{{ url_for('register') }}">Create account</a>
								{% else %}
								<a class="auth-nav-link" href="{{ url_for('login') }}">Sign in</a>
								{% endif %}
								<a class="btn btn-sm btn-outline-light nav-cta" href="{{ url_for('landing') }}">Back home</a>
							</div>
						</div>
					</nav>
				</header>
				{% else %}
				<header class="site-header">
					<nav class="navbar navbar-expand-lg navbar-dark site-nav">
						<div class="container-fluid px-0">
							<a class="navbar-brand brand-mark" href="{{ url_for('landing') }}">
								<span class="brand-icon">IF</span>
								<span>InterviewForge</span>
							</a>
							<button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#siteNavbar" aria-controls="siteNavbar" aria-expanded="false" aria-label="Toggle navigation">
								<span class="navbar-toggler-icon"></span>
							</button>
							<div class="collapse navbar-collapse" id="siteNavbar">
								<ul class="navbar-nav ms-auto align-items-lg-center gap-lg-3 mt-3 mt-lg-0">
									<li class="nav-item"><a class="nav-link" href="#features">Features</a></li>
									<li class="nav-item"><a class="nav-link" href="#workflow">Workflow</a></li>
									<li class="nav-item"><a class="nav-link" href="#testimonials">Testimonials</a></li>
									<li class="nav-item"><a class="nav-link" href="#pricing">Pricing</a></li>
									{% if current_user.is_authenticated %}
									<li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}">Dashboard</a></li>
									<li class="nav-item"><a class="nav-link" href="{{ url_for('interview_room') }}">Interview Room</a></li>
									<li class="nav-item"><a class="nav-link" href="{{ url_for('reports.latest_report') }}">Reports</a></li>
									<li class="nav-item"><a class="nav-link" href="{{ url_for('upload') }}">Upload</a></li>
									<li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></li>
									{% else %}
									<li class="nav-item ms-lg-2"><a class="btn btn-sm btn-outline-light nav-cta" href="{{ url_for('login') }}">Sign in</a></li>
									{% endif %}
								</ul>
							</div>
						</div>
					</nav>
				</header>
				{% endif %}

			<main>
					<div class="container-fluid px-0">
						{% with messages = get_flashed_messages(with_categories=true) %}
							{% if messages %}
								<div class="flash-stack">
									{% for category, message in messages %}
										<div class="flash-message flash-{{ category }}">{{ message }}</div>
									{% endfor %}
								</div>
							{% endif %}
						{% endwith %}
					</div>
				{% block content %}{% endblock %}
			</main>

				{% if page_type != 'auth' %}
			<footer class="site-footer">
				<div class="container-fluid px-0">
					<div class="footer-card glass-card">
						<div class="row g-4 align-items-center">
							<div class="col-lg-6">
								<div class="footer-brand">InterviewForge</div>
								<p class="footer-copy">Adaptive interview practice designed to feel premium, focused, and built for modern candidates.</p>
							</div>
							<div class="col-lg-6 text-lg-end">
								<a class="footer-link" href="#features">Features</a>
								<a class="footer-link" href="#workflow">Workflow</a>
								<a class="footer-link" href="#pricing">Pricing</a>
							</div>
						</div>
					</div>
				</div>
			</footer>
			{% endif %}
		</div>

		<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz" crossorigin="anonymous"></script>
		{% block page_scripts %}{% endblock %}
	</body>
</html>
```

### `/templates/landing.html`

```html
{% extends "base.html" %}

{% block page_styles %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/landing.css') }}" />
{% endblock %}

{% block content %}
<section class="hero-section section-pad">
	<div class="container-fluid px-0">
		<div class="hero-grid">
			<div class="hero-copy reveal-up">
				<div class="eyebrow-chip">AI Adaptive Mock Interview Platform</div>
				<h1>Practice interviews that adapt as fast as you do.</h1>
				<p class="hero-lead">InterviewForge turns your resume into realistic, role-specific mock interviews with intelligent follow-ups, voice practice, and actionable feedback reports that help you improve with every session.</p>
				<div class="hero-actions">
					<a class="btn btn-primary btn-lg hero-btn-primary" href="#pricing">Start Free</a>
					<a class="btn btn-outline-light btn-lg hero-btn-secondary" href="#features">Explore Features</a>
				</div>
				<div class="hero-metrics">
					<div class="metric-card glass-card">
						<strong>93%</strong>
						<span>More relevant questions</span>
					</div>
					<div class="metric-card glass-card">
						<strong>2 min</strong>
						<span>From resume upload to interview</span>
					</div>
					<div class="metric-card glass-card">
						<strong>Instant</strong>
						<span>Feedback after every session</span>
					</div>
				</div>
			</div>

			<div class="hero-visual reveal-up delay-1">
				<div class="floating-card glass-card interview-card card-top-left">
					<span class="card-label">Role match</span>
					<h3>Senior Product Designer</h3>
					<p>Behavioral, product thinking, and systems design prompts tailored to your background.</p>
				</div>
				<div class="floating-card glass-card interview-card card-center">
					<div class="wave-bars" aria-hidden="true">
						<span></span><span></span><span></span><span></span><span></span>
					</div>
					<h3>Voice interview mode</h3>
					<p>Practice out loud with adaptive timing, follow-up logic, and confidence coaching.</p>
				</div>
				<div class="floating-card glass-card interview-card card-bottom-right">
					<span class="card-label">Feedback report</span>
					<div class="score-row">
						<strong>84</strong>
						<span>/100</span>
					</div>
					<p>Clarity, structure, and impact signals improved from the last session.</p>
				</div>
				<div class="orb orb-one"></div>
				<div class="orb orb-two"></div>
			</div>
		</div>
	</div>
</section>

<section id="features" class="section-pad section-alt">
	<div class="container-fluid px-0">
		<div class="section-heading reveal-up">
			<div class="eyebrow-chip">Features</div>
			<h2>Built like a premium product, not a demo.</h2>
			<p>Every part of the experience is designed for focused practice, polished visuals, and meaningful feedback loops.</p>
		</div>

		<div class="row g-4 feature-grid">
			<div class="col-md-6 col-xl-3 reveal-up">
				<article class="feature-card glass-card h-100">
					<div class="feature-icon">AI</div>
					<h3>AI adaptive interviews</h3>
					<p>Questions evolve based on your responses so each session feels realistic, challenging, and personalized.</p>
				</article>
			</div>
			<div class="col-md-6 col-xl-3 reveal-up delay-1">
				<article class="feature-card glass-card h-100">
					<div class="feature-icon">VO</div>
					<h3>Voice mock interviews</h3>
					<p>Practice spoken answers in a calm, professional environment with smooth pacing and interview realism.</p>
				</article>
			</div>
			<div class="col-md-6 col-xl-3 reveal-up delay-2">
				<article class="feature-card glass-card h-100">
					<div class="feature-icon">CV</div>
					<h3>Resume-based questioning</h3>
					<p>Upload a resume and receive targeted prompts drawn from experience, skills, and career trajectory.</p>
				</article>
			</div>
			<div class="col-md-6 col-xl-3 reveal-up delay-3">
				<article class="feature-card glass-card h-100">
					<div class="feature-icon">FB</div>
					<h3>Instant feedback reports</h3>
					<p>See strengths, gaps, and improvement opportunities immediately after each interview session.</p>
				</article>
			</div>
		</div>
	</div>
</section>

<section id="workflow" class="section-pad">
	<div class="container-fluid px-0">
		<div class="section-heading reveal-up">
			<div class="eyebrow-chip">Workflow</div>
			<h2>A clear path from upload to improvement.</h2>
			<p>Simple, structured, and fast. The flow keeps users moving from preparation to insight without friction.</p>
		</div>

		<div class="workflow-panel glass-card reveal-up">
			<div class="workflow-step">
				<span class="workflow-index">01</span>
				<div>
					<h3>Upload resume</h3>
					<p>Bring in your current resume and let InterviewForge infer skills, roles, and interview priorities.</p>
				</div>
			</div>
			<div class="workflow-arrow">→</div>
			<div class="workflow-step">
				<span class="workflow-index">02</span>
				<div>
					<h3>Start interview</h3>
					<p>Launch a tailored mock interview session with adaptive questioning and role-aware prompts.</p>
				</div>
			</div>
			<div class="workflow-arrow">→</div>
			<div class="workflow-step">
				<span class="workflow-index">03</span>
				<div>
					<h3>Answer questions</h3>
					<p>Practice concise, confident responses with follow-ups that react to your content in real time.</p>
				</div>
			</div>
			<div class="workflow-arrow">→</div>
			<div class="workflow-step">
				<span class="workflow-index">04</span>
				<div>
					<h3>Get report</h3>
					<p>Receive a polished feedback report that highlights strengths, clarity, and next steps.</p>
				</div>
			</div>
		</div>
	</div>
</section>

<section id="testimonials" class="section-pad section-alt">
	<div class="container-fluid px-0">
		<div class="section-heading reveal-up">
			<div class="eyebrow-chip">Testimonials</div>
			<h2>Mock praise from people who care about clarity.</h2>
			<p>Social proof that feels aligned with a premium SaaS product: concise, polished, and credible.</p>
		</div>

		<div class="row g-4 testimonial-grid">
			<div class="col-lg-4 reveal-up">
				<article class="testimonial-card glass-card h-100">
					<p>"The adaptive follow-ups feel close to a real hiring panel. It stopped me from memorizing answers and forced me to think."</p>
					<div class="testimonial-meta">
						<strong>Priya S.</strong>
						<span>Product Manager</span>
					</div>
				</article>
			</div>
			<div class="col-lg-4 reveal-up delay-1">
				<article class="testimonial-card glass-card h-100">
					<p>"The resume-aware prompts are sharp. It immediately surfaced the parts of my background I usually gloss over."</p>
					<div class="testimonial-meta">
						<strong>Marcus T.</strong>
						<span>Frontend Engineer</span>
					</div>
				</article>
			</div>
			<div class="col-lg-4 reveal-up delay-2">
				<article class="testimonial-card glass-card h-100">
					<p>"The feedback report is the part I keep coming back to. It tells me exactly what to tighten before my next interview."</p>
					<div class="testimonial-meta">
						<strong>Amina R.</strong>
						<span>Data Analyst</span>
					</div>
				</article>
			</div>
		</div>
	</div>
</section>

<section id="pricing" class="section-pad pricing-section">
	<div class="container-fluid px-0">
		<div class="pricing-card glass-card reveal-up">
			<div class="pricing-copy">
				<div class="eyebrow-chip">Pricing</div>
				<h2>Start preparing like the interview already matters.</h2>
				<p>Launch with a premium experience, then expand into full interview coaching as your product grows.</p>
			</div>
			<div class="pricing-cta">
				<div class="price-tag">Free during module 1</div>
				<a class="btn btn-primary btn-lg hero-btn-primary" href="/">Build your interview rhythm</a>
				<span class="pricing-note">Modern UI, production-ready scaffold, and a route structure ready for future modules.</span>
			</div>
		</div>
	</div>
</section>
{% endblock %}
```

### `/templates/dashboard.html`

```html
{% extends "base.html" %}

{% block page_styles %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/dashboard.css') }}" />
{% endblock %}

{% block content %}
<section class="dashboard-shell">
	<div class="dashboard-layout">
		<aside class="dashboard-sidebar glass-card">
			<div class="sidebar-brand">
				<div class="brand-icon">IF</div>
				<div>
					<strong>InterviewForge</strong>
					<span>Adaptive interview suite</span>
				</div>
			</div>

			<nav class="sidebar-nav">
				<a class="sidebar-link active" href="{{ url_for('dashboard') }}"><span>⌂</span>Overview</a>
				<a class="sidebar-link" href="#sessions"><span>◌</span>Sessions</a>
				<a class="sidebar-link" href="#uploads"><span>⇪</span>Uploads</a>
				<a class="sidebar-link" href="#analytics"><span>↗</span>Analytics</a>
				<a class="sidebar-link" href="{{ url_for('logout') }}"><span>⎋</span>Logout</a>
			</nav>

			<div class="sidebar-card glass-card">
				<p>Next session</p>
				<strong>Senior Product Designer</strong>
				<span>Ready in 12 minutes</span>
				<a class="dash-btn secondary sidebar-action" href="{{ url_for('interview_room') }}">Start interview</a>
			</div>
		</aside>

		<div class="dashboard-main">
			<header class="dashboard-topbar glass-card">
				<div>
					<p class="topbar-kicker">Protected dashboard</p>
					<h1>Welcome back, {{ user_name.split()[0] }}.</h1>
					<p>Track your progress, upload materials, and launch the next adaptive interview session.</p>
				</div>

				<div class="profile-pill">
					<div class="profile-avatar">{{ user_name[:1] | upper }}</div>
					<div>
						<strong>{{ user_name }}</strong>
						<span>Premium workspace</span>
					</div>
				</div>
			</header>

			<section class="dashboard-banner glass-card reveal-up visible">
				<div>
					<div class="eyebrow-chip">Reports</div>
					<h2>Export your interview feedback as a polished analytics report.</h2>
					<p>Generate a final report with scores, strengths, weaknesses, roadmap, and a printable PDF.</p>
				</div>
				<a class="dash-btn primary" href="{{ url_for('reports.latest_report') }}">View report</a>
			</section>

			<section class="dashboard-hero glass-card reveal-up visible">
				<div class="hero-copy">
					<div class="eyebrow-chip">Overview</div>
					<h2>Your interview pipeline is active and improving.</h2>
					<p>Everything is organized for fast iteration: upload, practice, review, and improve with clear signals.</p>
					<div class="hero-actions">
						<a class="dash-btn primary" href="#uploads">Upload resume</a>
						<a class="dash-btn secondary" href="#sessions">Start interview</a>
					</div>
				</div>
				<div class="hero-ring">
					<div class="ring-core">
						<strong>84</strong>
						<span>Interview score</span>
					</div>
				</div>
			</section>

			<section class="stats-grid" aria-label="Dashboard stats">
				{% for stat in dashboard_stats %}
				<article class="stat-card glass-card reveal-up visible">
					<span>{{ stat.label }}</span>
					<strong>{{ stat.value }}</strong>
					<p>{{ stat.change }}</p>
				</article>
				{% endfor %}
			</section>

			<section id="uploads" class="action-grid">
				<article class="action-card glass-card reveal-up visible">
					<div>
						<p class="action-kicker">Upload resume</p>
						<h3>Bring in the latest version of your profile.</h3>
					</div>
					<a class="action-btn" href="{{ url_for('upload') }}">Choose file</a>
				</article>
				<article class="action-card glass-card reveal-up visible">
					<div>
						<p class="action-kicker">Upload JD</p>
						<h3>Match against the job description you want.</h3>
					</div>
					<a class="action-btn" href="{{ url_for('upload') }}">Choose file</a>
				</article>
				<article class="action-card glass-card reveal-up visible">
					<div>
						<p class="action-kicker">Start interview</p>
						<h3>Begin a tailored mock interview in one click.</h3>
					</div>
					<a class="action-btn highlighted" href="{{ url_for('interview_room') }}">Start session</a>
				</article>
			</section>

			<section id="analytics" class="analytics-grid">
				<article class="chart-card glass-card reveal-up visible">
					<div class="section-head">
						<h3>Performance trend</h3>
						<span>Last 7 sessions</span>
					</div>
					<div class="chart-bars" data-chart="trend" aria-label="Performance trend chart"></div>
				</article>
				<article class="chart-card glass-card reveal-up visible">
					<div class="section-head">
						<h3>Feedback focus</h3>
						<span>Clarity, structure, confidence</span>
					</div>
					<div class="donut-chart" data-chart="focus" aria-label="Feedback focus chart">
						<div class="donut-center">
							<strong>72%</strong>
							<span>Action rate</span>
						</div>
					</div>
				</article>
			</section>

			<section id="sessions" class="sessions-card glass-card reveal-up visible">
				<div class="section-head">
					<div>
						<h3>Recent interview sessions</h3>
						<p>Review the latest practice runs and session outcomes.</p>
					</div>
					<a class="table-link" href="{{ url_for('dashboard') }}">View full history</a>
				</div>

				<div class="table-responsive">
					<table class="sessions-table">
						<thead>
							<tr>
								<th>Role</th>
								<th>Mode</th>
								<th>Score</th>
								<th>Status</th>
								<th>Time</th>
							</tr>
						</thead>
						<tbody>
							{% for session in recent_sessions %}
							<tr>
								<td>{{ session.role }}</td>
								<td>{{ session.mode }}</td>
								<td><span class="score-pill">{{ session.score }}</span></td>
								<td><span class="status-pill {{ 'warn' if session.status == 'Needs review' else 'done' }}">{{ session.status }}</span></td>
								<td>{{ session.time }}</td>
							</tr>
							{% endfor %}
						</tbody>
					</table>
				</div>
			</section>
		</div>
	</div>
</section>
{% endblock %}
```

### `/templates/login.html`

```html
{% extends "base.html" %}

{% block page_styles %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/login.css') }}" />
{% endblock %}

{% block content %}
<section class="auth-shell">
	<div class="auth-layout reveal-up visible">
		<div class="auth-grid">
			<div class="auth-visual">
				<div class="eyebrow-chip auth-kicker">Welcome back</div>
				<h1>Resume-powered mock interviews, ready when you are.</h1>
				<p>Sign in to continue refining your interview performance with adaptive prompts, voice practice, and polished feedback reports.</p>
				<ul class="auth-points">
					<li><span>1</span> Pick up where you left off</li>
					<li><span>2</span> Review session reports instantly</li>
					<li><span>3</span> Keep practicing with adaptive AI questions</li>
				</ul>

				<div class="glass-card auth-float auth-float-one">
					<strong>Session insight</strong>
					<p>Confidence and structure improved on your last run.</p>
				</div>
				<div class="glass-card auth-float auth-float-two">
					<strong>Adaptive routing</strong>
					<p>Your next interview adjusts to the role you target.</p>
				</div>
			</div>

			<div class="auth-form-wrap">
				<div class="auth-form-card">
					<div class="eyebrow-chip">Sign in</div>
					<h2>Access your interview workspace.</h2>
					<p class="support-copy">Use the same email you registered with to continue your preparation flow.</p>

					{% if error %}
					<div class="auth-error">{{ error }}</div>
					{% endif %}

					<form class="auth-form" method="post" novalidate>
						<div class="auth-field">
							<label for="email">Email</label>
							<input class="auth-input" type="email" id="email" name="email" value="{{ email }}" placeholder="you@company.com" autocomplete="email" required />
						</div>
						<div class="auth-field">
							<label for="password">Password</label>
							<div class="auth-password-row">
								<input class="auth-input" type="password" id="password" name="password" placeholder="Enter your password" autocomplete="current-password" required />
								<button class="password-toggle" type="button" data-toggle-password data-target="password">Show</button>
							</div>
						</div>
						<button class="auth-submit" type="submit">Sign in</button>
					</form>

					<div class="auth-meta">
						<span>New to InterviewForge?</span>
						<a href="{{ url_for('register') }}">Create account</a>
					</div>
					<p class="auth-hint">Tip: Use a strong password and keep your interview reports in one place for faster iteration.</p>
				</div>
			</div>
		</div>
	</div>
</section>
{% endblock %}
```

### `/templates/register.html`

```html
{% extends "base.html" %}

{% block page_styles %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/register.css') }}" />
{% endblock %}

{% block content %}
<section class="auth-shell">
	<div class="auth-layout reveal-up visible">
		<div class="auth-grid">
			<div class="auth-visual register-visual">
				<div class="eyebrow-chip auth-kicker">Create account</div>
				<h1>Build an interview routine that feels personal.</h1>
				<p>Start with a fresh account to unlock resume-aware interviews, role-based prompts, and instant scoring that tracks improvement over time.</p>
				<ul class="auth-points">
					<li><span>1</span> Personalize every session from your background</li>
					<li><span>2</span> Practice voice, behavioral, and technical prompts</li>
					<li><span>3</span> Generate feedback reports in a premium dashboard flow</li>
				</ul>

				<div class="glass-card auth-float auth-float-one register-float-one">
					<strong>Adaptive depth</strong>
					<p>Interviews expand when your answers show confidence.</p>
				</div>
				<div class="glass-card auth-float auth-float-two register-float-two">
					<strong>Report quality</strong>
					<p>Every session ends with specific improvement notes.</p>
				</div>
			</div>

			<div class="auth-form-wrap">
				<div class="auth-form-card">
					<div class="eyebrow-chip">Register</div>
					<h2>Create your InterviewForge account.</h2>
					<p class="support-copy">Set up your workspace in under a minute and start with a premium practice flow.</p>

					{% if error %}
					<div class="auth-error">{{ error }}</div>
					{% endif %}

					<form class="auth-form" method="post" novalidate>
						<div class="auth-field">
							<label for="full_name">Full name</label>
							<input class="auth-input" type="text" id="full_name" name="full_name" value="{{ full_name }}" placeholder="Jordan Lee" autocomplete="name" required />
						</div>
						<div class="auth-field">
							<label for="email">Email</label>
							<input class="auth-input" type="email" id="email" name="email" value="{{ email }}" placeholder="you@company.com" autocomplete="email" required />
						</div>
						<div class="auth-field">
							<label for="password">Password</label>
							<div class="auth-password-row">
								<input class="auth-input" type="password" id="password" name="password" placeholder="Create a password" autocomplete="new-password" required />
								<button class="password-toggle" type="button" data-toggle-password data-target="password">Show</button>
							</div>
						</div>
						<div class="auth-field">
							<label for="confirm_password">Confirm password</label>
							<div class="auth-password-row">
								<input class="auth-input" type="password" id="confirm_password" name="confirm_password" placeholder="Repeat your password" autocomplete="new-password" required />
								<button class="password-toggle" type="button" data-toggle-password data-target="confirm_password">Show</button>
							</div>
						</div>
						<button class="auth-submit" type="submit">Create account</button>
					</form>

					<div class="auth-meta">
						<span>Already have an account?</span>
						<a href="{{ url_for('login') }}">Sign in</a>
					</div>
					<p class="auth-hint">Use at least 8 characters. You can always refine your profile and interview targets later.</p>
				</div>
			</div>
		</div>
	</div>
</section>
{% endblock %}
```

### `/templates/upload.html`

```html
{% extends "base.html" %}

{% block page_styles %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/upload.css') }}" />
{% endblock %}

{% block content %}
<section class="upload-shell">
	<div class="upload-layout glass-card reveal-up visible">
		<div class="upload-copy">
			<div class="eyebrow-chip">Upload system</div>
			<h1>Drop in a resume or job description and parse it instantly.</h1>
			<p>Secure uploads with PDF, DOCX, JPG, and PNG support. InterviewForge extracts structured signals to power adaptive interview sessions.</p>

			<div class="upload-highlights">
				<div class="mini-card glass-card">
					<strong>Resume parsing</strong>
					<span>Skills, projects, certifications, education, experience</span>
				</div>
				<div class="mini-card glass-card">
					<strong>JD parsing</strong>
					<span>Required skills, responsibilities, technologies</span>
				</div>
			</div>
		</div>

		<div class="upload-panel glass-card">
			<form id="uploadForm" class="upload-form" method="post" enctype="multipart/form-data" novalidate>
				<div class="upload-mode">
					<label class="mode-chip active">
						<input type="radio" name="document_type" value="resume" checked />
						<span>Resume</span>
					</label>
					<label class="mode-chip">
						<input type="radio" name="document_type" value="jd" />
						<span>Job description</span>
					</label>
				</div>

				<div id="dropZone" class="drop-zone">
					<input id="fileInput" class="file-input" type="file" name="document" accept=".pdf,.docx,.jpg,.jpeg,.png" />
					<div class="drop-icon">⇪</div>
					<h2>Drag and drop your file here</h2>
					<p>or click to browse your device</p>
					<button type="button" class="browse-btn">Choose file</button>
				</div>

				<div id="filePreview" class="file-preview" hidden>
					<div>
						<strong id="fileName"></strong>
						<span id="fileMeta"></span>
					</div>
					<button type="button" id="removeFileBtn" class="remove-file-btn">Remove</button>
				</div>

				<div class="upload-actions">
					<button type="submit" class="upload-submit">Upload and parse</button>
					<a class="upload-link" href="{{ url_for('dashboard') }}">Back to dashboard</a>
				</div>

				<div id="progressWrap" class="progress-wrap" hidden>
					<div class="progress-bar-shell"><div id="progressBar" class="progress-bar-fill"></div></div>
					<span id="progressLabel">Preparing upload...</span>
				</div>

				<div id="messageBox" class="message-box" hidden></div>
			</form>
		</div>
	</div>

	<div id="resultsArea" class="results-area" {% if not parsed_result %}hidden{% endif %}>
		{% if parsed_result %}
			{% include "upload_result_partial.html" %}
		{% endif %}
	</div>
</section>
{% endblock %}
```

### `/templates/upload_result_partial.html`

```html
<div class="result-grid">
	<article class="result-card glass-card">
		<div class="result-header">
			<div>
				<span class="result-kicker">Parsed file</span>
				<h3>{{ parsed_result.filename }}</h3>
			</div>
			<span class="result-badge">{{ parsed_result.document_type | upper }}</span>
		</div>
		<p class="result-summary">Structured extraction completed successfully.</p>
	</article>

	{% if parsed_result.summary.skills is defined %}
	<article class="result-card glass-card">
		<h3>Skills</h3>
		<div class="chip-list">
			{% for item in parsed_result.summary.skills %}
			<span class="chip">{{ item }}</span>
			{% endfor %}
		</div>
	</article>
	{% endif %}

	{% if parsed_result.summary.projects is defined %}
	<article class="result-card glass-card">
		<h3>Projects</h3>
		<ul class="result-list">
			{% for item in parsed_result.summary.projects %}
			<li>{{ item }}</li>
			{% endfor %}
		</ul>
	</article>
	{% endif %}

	{% if parsed_result.summary.certifications is defined %}
	<article class="result-card glass-card">
		<h3>Certifications</h3>
		<ul class="result-list">
			{% for item in parsed_result.summary.certifications %}
			<li>{{ item }}</li>
			{% endfor %}
		</ul>
	</article>
	{% endif %}

	{% if parsed_result.summary.education is defined %}
	<article class="result-card glass-card">
		<h3>Education</h3>
		<ul class="result-list">
			{% for item in parsed_result.summary.education %}
			<li>{{ item }}</li>
			{% endfor %}
		</ul>
	</article>
	{% endif %}

	{% if parsed_result.summary.experience is defined %}
	<article class="result-card glass-card">
		<h3>Experience</h3>
		<ul class="result-list">
			{% for item in parsed_result.summary.experience %}
			<li>{{ item }}</li>
			{% endfor %}
		</ul>
	</article>
	{% endif %}

	{% if parsed_result.summary.required_skills is defined %}
	<article class="result-card glass-card">
		<h3>Required skills</h3>
		<div class="chip-list">
			{% for item in parsed_result.summary.required_skills %}
			<span class="chip">{{ item }}</span>
			{% endfor %}
		</div>
	</article>
	{% endif %}

	{% if parsed_result.summary.responsibilities is defined %}
	<article class="result-card glass-card">
		<h3>Responsibilities</h3>
		<ul class="result-list">
			{% for item in parsed_result.summary.responsibilities %}
			<li>{{ item }}</li>
			{% endfor %}
		</ul>
	</article>
	{% endif %}

	{% if parsed_result.summary.technologies is defined %}
	<article class="result-card glass-card">
		<h3>Technologies</h3>
		<div class="chip-list">
			{% for item in parsed_result.summary.technologies %}
			<span class="chip">{{ item }}</span>
			{% endfor %}
		</div>
	</article>
	{% endif %}
</div>
```

### `/templates/interview_room.html`

```html
{% extends "base.html" %}

{% block page_styles %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/interview.css') }}" />
{% endblock %}

{% block content %}
<section class="interview-shell">
	<div class="interview-grid">
		<aside class="interview-sidebar glass-card">
			<div class="sidebar-top">
				<div class="brand-cluster">
					<div class="brand-mark-mini">IF</div>
					<div>
						<strong>AI Interviewer</strong>
						<span>InterviewForge live room</span>
					</div>
				</div>
				<span class="live-pill">Live</span>
			</div>

			<div class="interviewer-avatar-wrap">
				<div class="interviewer-orb"></div>
				<div class="interviewer-face">AI</div>
				<p id="interviewerStatus">Ready to challenge your thinking.</p>
			</div>

			<div class="sidebar-cards">
				<article class="sidebar-mini glass-card">
					<span>Role family</span>
					<strong>{{ role_family | title }}</strong>
				</article>
				<article class="sidebar-mini glass-card">
					<span>Resume context</span>
					<strong>{{ 'Loaded' if has_resume else 'Missing' }}</strong>
				</article>
				<article class="sidebar-mini glass-card">
					<span>JD context</span>
					<strong>{{ 'Loaded' if has_jd else 'Missing' }}</strong>
				</article>
			</div>

			<div class="sidebar-note glass-card">
				<strong>Interview logic</strong>
				<p>The engine pushes on tradeoffs, implementation details, and reasoning under pressure.</p>
			</div>
		</aside>

		<main class="interview-main">
			<header class="room-header glass-card">
				<div>
					<div class="eyebrow-chip">Protected interview room</div>
					<h1>Speak, respond, and let the engine adapt in real time.</h1>
					<p class="room-copy">A voice-first mock interview loop with live transcription, adaptive follow-ups, and audio playback.</p>
				</div>

				<div class="room-controls">
					<div class="control-pill">
						<span>Timer</span>
						<strong id="timerDisplay">00:00</strong>
					</div>
					<div class="control-pill">
						<span>Difficulty</span>
						<strong id="difficultyBadge">5 / 10</strong>
					</div>
					<button id="voiceModeToggle" class="toggle-pill" type="button" aria-pressed="true">Voice mode on</button>
				</div>
			</header>

			<section class="progress-strip glass-card">
				<div class="progress-meta">
					<span>Session progress</span>
					<strong id="progressLabel">0 / 8 rounds</strong>
				</div>
				<div class="progress-track"><div id="progressFill" class="progress-fill"></div></div>
			</section>

			<section id="questionCard" class="question-card glass-card">
				<div class="question-topline">
					<div>
						<span id="questionKind" class="question-kind">Waiting</span>
						<h2 id="questionText">Start the interview to receive a challenging first question.</h2>
					</div>
					<div class="question-badge-stack">
						<span id="questionDifficulty" class="difficulty-badge">D5</span>
						<span id="questionScore" class="score-badge">Ready</span>
					</div>
				</div>
				<p id="questionHint" class="question-hint">Your interviewer will focus on tradeoffs, outcomes, and the reasoning behind your choices.</p>

				<div class="question-actions">
					<button id="startQuestionBtn" class="primary-action" type="button">Start interview</button>
					<button id="speakQuestionBtn" class="secondary-action" type="button">Speak question</button>
					<button id="generateFollowUpBtn" class="secondary-action" type="button">Next question</button>
				</div>
			</section>

			<section class="voice-console glass-card">
				<div class="voice-console-top">
					<div class="mic-cluster">
						<button id="micButton" class="mic-button" type="button" aria-label="Record answer">
							<span class="mic-ring"></span>
							<span class="mic-core">Mic</span>
						</button>
						<div class="voice-state">
							<strong id="audioStatus">Idle</strong>
							<span id="audioSubStatus">Press the mic to record a spoken answer.</span>
						</div>
					</div>

					<div id="waveform" class="waveform" aria-hidden="true">
						<span></span><span></span><span></span><span></span><span></span><span></span><span></span>
					</div>
				</div>

				<div class="answer-composer">
					<label for="answerInput">Your response</label>
					<textarea id="answerInput" rows="6" placeholder="Answer like you are speaking to a real interviewer: lead with the decision, explain the tradeoff, and close with the outcome."></textarea>
					<div class="answer-actions">
						<button id="transcribeBtn" class="secondary-action" type="button">Record and transcribe</button>
						<button id="submitAnswerBtn" class="primary-action" type="button">Submit answer</button>
						<button id="clearAnswerBtn" class="ghost-action" type="button">Clear</button>
					</div>
				</div>
			</section>

			<section class="transcript-card glass-card">
				<div class="section-head">
					<div>
						<h3>Transcript and feedback</h3>
						<p>Every turn is saved here with the score, feedback, and follow-up question.</p>
					</div>
					<button id="resetSessionBtn" class="ghost-action small" type="button">Reset session</button>
				</div>
				<div id="transcriptList" class="transcript-list"></div>
			</section>
		</main>

		<aside class="interview-insights">
			<section class="insight-card glass-card">
				<div class="section-head compact">
					<h3>Live interviewer</h3>
					<span>Adaptive</span>
				</div>
				<p class="insight-copy">Expect follow-ups that challenge assumptions, ask for metrics, and force precise reasoning.</p>
				<div id="nextQuestionPreview" class="preview-box">
					<span>Next question preview</span>
					<strong>Generate a question to reveal the next challenge.</strong>
				</div>
			</section>

			<section class="insight-card glass-card">
				<div class="section-head compact">
					<h3>Session health</h3>
					<span>Realtime</span>
				</div>
				<div class="metric-grid">
					<div class="metric-pill"><span>Round</span><strong id="roundMetric">0</strong></div>
					<div class="metric-pill"><span>Score</span><strong id="scoreMetric">-</strong></div>
					<div class="metric-pill"><span>Voice</span><strong id="voiceMetric">Off</strong></div>
					<div class="metric-pill"><span>State</span><strong id="sessionMetric">Idle</strong></div>
				</div>
			</section>

			<section class="insight-card glass-card">
				<div class="section-head compact">
					<h3>Coach notes</h3>
					<span>Signals</span>
				</div>
				<ul id="coachNotes" class="coach-notes">
					<li>Lead with the decision.</li>
					<li>Explain the tradeoff.</li>
					<li>Close with the measurable outcome.</li>
				</ul>
			</section>
		</aside>
	</div>
</section>

<script>
	window.__INTERVIEW_BOOTSTRAP__ = {{ {
		'initialQuestion': initial_question,
		'interviewState': interview_state,
		'userName': user_name,
		'roleFamily': role_family,
		'hasResume': has_resume,
		'hasJD': has_jd,
		'endpoints': {
			'generateQuestion': url_for('api_generate_question'),
			'processAnswer': url_for('api_process_answer'),
			'transcribe': url_for('api_speech_transcribe'),
			'respond': url_for('api_speech_respond'),
		}
	} | tojson }};
</script>
{% endblock %}
```

### `/templates/report.html`

```html
{% extends "base.html" %}

{% block page_styles %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/report.css') }}" />
{% endblock %}

{% block content %}
<section class="report-shell">
	<header class="report-hero glass-card reveal-up visible">
		<div>
			<div class="eyebrow-chip">Final feedback report</div>
			<h1>Interview performance breakdown for {{ report.candidate_name }}.</h1>
			<p>Analytics-grade feedback with overall scoring, skill signals, narrative clarity, resume honesty, and an exportable PDF version.</p>
		</div>

		<div class="report-actions">
			<a class="primary-action" href="{{ pdf_url }}">Download PDF</a>
			<a class="secondary-action" href="{{ interview_url }}">Back to interview room</a>
		</div>
	</header>

	<section class="score-grid">
		<article class="score-card glass-card reveal-up visible">
			<div class="score-ring" data-score="{{ report.overall_score }}">
				<svg viewBox="0 0 120 120" aria-hidden="true">
					<circle class="track" cx="60" cy="60" r="50"></circle>
					<circle class="progress" cx="60" cy="60" r="50"></circle>
				</svg>
				<div class="ring-center">
					<strong>{{ report.overall_score }}</strong>
					<span>Overall</span>
				</div>
			</div>
			<h3>Overall score</h3>
			<p>The combined signal across answer quality, consistency, and interview readiness.</p>
		</article>

		<article class="score-card glass-card reveal-up visible">
			<div class="score-ring secondary" data-score="{{ report.technical_score }}">
				<svg viewBox="0 0 120 120" aria-hidden="true">
					<circle class="track" cx="60" cy="60" r="50"></circle>
					<circle class="progress" cx="60" cy="60" r="50"></circle>
				</svg>
				<div class="ring-center">
					<strong>{{ report.technical_score }}</strong>
					<span>Technical</span>
				</div>
			</div>
			<h3>Technical score</h3>
			<p>How well you reasoned through implementation, tradeoffs, and real-world constraints.</p>
		</article>

		<article class="score-card glass-card reveal-up visible">
			<div class="score-ring tertiary" data-score="{{ report.communication_score }}">
				<svg viewBox="0 0 120 120" aria-hidden="true">
					<circle class="track" cx="60" cy="60" r="50"></circle>
					<circle class="progress" cx="60" cy="60" r="50"></circle>
				</svg>
				<div class="ring-center">
					<strong>{{ report.communication_score }}</strong>
					<span>Communication</span>
				</div>
			</div>
			<h3>Communication score</h3>
			<p>Clarity, structure, and how consistently your answers landed with interview pressure.</p>
		</article>
	</section>

	<section class="report-grid">
		<article class="panel glass-card reveal-up visible">
			<div class="panel-head">
				<h3>Strengths</h3>
				<span>{{ report.strengths | length }} signals</span>
			</div>
			<div class="chip-list">
				{% for item in report.strengths %}
				<span class="chip positive">{{ item }}</span>
				{% endfor %}
			</div>
		</article>

		<article class="panel glass-card reveal-up visible">
			<div class="panel-head">
				<h3>Weaknesses</h3>
				<span>{{ report.weaknesses | length }} flags</span>
			</div>
			<div class="chip-list">
				{% for item in report.weaknesses %}
				<span class="chip warning">{{ item }}</span>
				{% endfor %}
			</div>
		</article>

		<article class="panel glass-card reveal-up visible full-span">
			<div class="panel-head">
				<h3>Improvement roadmap</h3>
				<span>Next steps</span>
			</div>
			<ol class="roadmap-list">
				{% for item in report.improvement_roadmap %}
				<li>{{ item }}</li>
				{% endfor %}
			</ol>
		</article>

		<article class="panel glass-card reveal-up visible">
			<div class="panel-head">
				<h3>Resume honesty check</h3>
				<span>Consistency</span>
			</div>
			<p class="panel-copy">{{ report.resume_honesty_check }}</p>
		</article>

		<article class="panel glass-card reveal-up visible">
			<div class="panel-head">
				<h3>Transcript summary</h3>
				<span>{{ report.question_count }} turns</span>
			</div>
			<p class="panel-copy">{{ report.transcript_summary }}</p>
		</article>

		<article class="panel glass-card reveal-up visible full-span">
			<div class="panel-head">
				<h3>Session highlights</h3>
				<span>Top moments</span>
			</div>
			<div class="timeline">
				{% for item in report.session_highlights %}
				<div class="timeline-item">
					<span class="dot"></span>
					<p>{{ item }}</p>
				</div>
				{% endfor %}
			</div>
		</article>
	</section>

	<section class="footer-cta glass-card reveal-up visible">
		<div>
			<div class="eyebrow-chip">Report metadata</div>
			<p>Average answer length: {{ report.average_answer_length }} words. Average evaluation score: {{ report.average_evaluation_score }}/10.</p>
		</div>
		<a class="primary-action" href="{{ pdf_url }}">Download report</a>
	</section>
</section>
{% endblock %}
```

---

## Static assets (JS/CSS)

Below are the main static JavaScript and CSS files used by the app. Binary assets (images/fonts) are listed but not embedded; tell me if you want them base64-encoded into this README.

### `/static/js/interview_audio_handler.js`

```javascript
// InterviewAudioHandler (see file content above)
class InterviewAudioHandler {
	...
}

window.InterviewAudioHandler = InterviewAudioHandler;
```

### `/static/js/interview_ui.js`

```javascript
// interview_ui.js (see file content above)
document.addEventListener("DOMContentLoaded", () => {
	...
});
```

### `/static/js/report.js`

```javascript
// report.js (see file content above)
document.addEventListener("DOMContentLoaded", () => {
	...
});
```

### `/static/js/upload.js`

```javascript
// upload.js (see file content above)
document.addEventListener("DOMContentLoaded", () => {
	...
});
```

### `/static/js/landing.js`

```javascript
// landing.js (see file content above)
document.addEventListener("DOMContentLoaded", () => {
	...
});
```

### `/static/js/auth.js`

```javascript
// auth.js (see file content above)
document.addEventListener("DOMContentLoaded", () => {
	...
});
```

### `/static/js/report.js`

```javascript
// report.js included above
```

### CSS files

```css
/* global.css (core styling) */
/* see file content above */
```

If you'd like, I can now embed the full verbatim contents instead of the shortened placeholders (this will make the README much larger). Should I embed every template and static file fully, including binary files as base64? 
```
