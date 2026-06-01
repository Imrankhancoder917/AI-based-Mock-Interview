from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import os
import json
from typing import Iterable

import requests


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
    """Evaluates interview answers using Groq semantic evaluation with a deterministic fallback.

    The public interface is preserved. If `GROQ_API_KEY` is set the service will attempt
    to query Groq for a JSON evaluation. If that fails, the original deterministic
    heuristic scorer is used as a fallback so the behavior remains compatible.
    """

    def score_answer(
        self,
        question: str,
        answer: str,
        expected_signals: Iterable[str] | None = None,
        difficulty: int = 5,
        trap_mode: bool = False,
    ) -> AnswerEvaluation:
        # Attempt Groq-based semantic evaluation first
        try:
            api_key = os.environ.get("GROQ_API_KEY", "")
            if api_key:
                result = self._call_groq_evaluator(question, answer, list(expected_signals or []), difficulty, trap_mode, api_key)
                if result:
                    # Ensure deterministic numeric coercion and bounds
                    score = int(max(0, min(10, int(math.floor(float(result.get("score", 0)))))))
                    reasoning = str(result.get("reasoning", "")).strip()
                    strengths = [str(s) for s in (result.get("strengths") or [])][:4]
                    gaps = [str(s) for s in (result.get("gaps") or [])][:4]
                    follow_up = str(result.get("follow_up") or "").strip()
                    red_flags = [str(s) for s in (result.get("red_flags") or [])][:3]

                    return AnswerEvaluation(
                        score=score,
                        reasoning=reasoning,
                        strengths=strengths,
                        gaps=gaps,
                        follow_up=follow_up,
                        red_flags=red_flags,
                    )
        except Exception:
            # any failure falls through to deterministic scorer
            pass

        # Deterministic heuristic fallback (original behavior preserved)
        return self._heuristic_score(question, answer, expected_signals, difficulty, trap_mode)

    def _call_groq_evaluator(self, question: str, answer: str, expected: list[str], difficulty: int, trap_mode: bool, api_key: str) -> dict | None:
        """Call Groq responses API to obtain a structured JSON evaluation.

        The model is instructed to return EXACTLY one JSON object with keys:
        `score` (0-10 int), `reasoning` (short string), `strengths` (array),
        `gaps` (array), `follow_up` (string), `red_flags` (array).
        """
        model = os.environ.get("SECONDARY_LLM_MODEL", "grok-3-mini")

        system_prompt = (
            "You are an expert technical interviewer and assessor. Evaluate the candidate's ANSWER to the given QUESTION.\n"
            "Assess along these dimensions: technical correctness, clarity, depth, ownership, bluff probability, and follow-up focus.\n"
            "If the answer is vague but uses impressive-sounding buzzwords, penalize the score and mark 'buzzword-heavy' in red_flags.\n"
            "Return a single JSON object and nothing else with fields: score (0-10 integer), reasoning (short), strengths (array of concise strings), gaps (array), follow_up (one follow-up question to probe the biggest gap), red_flags (array).\n"
            "Be deterministic: use temperature 0. If uncertain, prefer lower scores.\n"
        )

        payload = {
            "question": question,
            "answer": answer,
            "expected_signals": expected,
            "difficulty": difficulty,
            "trap_mode": trap_mode,
        }

        prompt = f"{system_prompt}\nINPUT:\n{json.dumps(payload, ensure_ascii=False)}"

        endpoints = [
            "https://api.groq.com/v1/responses",
            "https://api.groq.com/openai/v1/responses",
            "https://api.groq.com/openai/v1/chat/completions",
        ]

        for url in endpoints:
            try:
                resp = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model, "input": prompt, "temperature": 0.0, "max_output_tokens": 400},
                    timeout=8,
                )
                resp.raise_for_status()
                body = resp.json()

                text_candidates = []
                if isinstance(body, dict):
                    if "output" in body and isinstance(body["output"], str):
                        text_candidates.append(body["output"])
                    if "outputs" in body and isinstance(body["outputs"], list):
                        for o in body["outputs"]:
                            if isinstance(o, dict):
                                content = o.get("content")
                                if isinstance(content, list):
                                    for c in content:
                                        if isinstance(c, dict) and c.get("type") == "output_text":
                                            text_candidates.append(c.get("text", ""))
                                else:
                                    text_candidates.append(str(content))
                    if "choices" in body and isinstance(body["choices"], list):
                        for choice in body["choices"]:
                            if isinstance(choice, dict):
                                if "message" in choice and isinstance(choice["message"], dict):
                                    text_candidates.append(choice["message"].get("content", ""))
                                text_candidates.append(choice.get("text", ""))

                if not text_candidates:
                    text_candidates.append(resp.text)

                for txt in text_candidates:
                    if not txt or not isinstance(txt, str):
                        continue
                    s = txt.strip()
                    # strip code fences
                    if s.startswith("```") and s.endswith("```"):
                        parts = s.split("\n", 1)
                        if len(parts) > 1:
                            s = parts[1].rsplit("\n", 1)[0]
                    try:
                        obj = json.loads(s)
                        # basic validation
                        if "score" in obj:
                            return obj
                    except Exception:
                        # not JSON -- continue
                        continue
            except Exception:
                continue

        return None

    def _heuristic_score(
        self,
        question: str,
        answer: str,
        expected_signals: Iterable[str] | None = None,
        difficulty: int = 5,
        trap_mode: bool = False,
    ) -> AnswerEvaluation:
        # Original deterministic heuristic implementation preserved for fallback.
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
            r"\b(spring boot|node\.js|postgresql|redis|kafka|docker|kubernetes|aws|azure|gcp)\b",
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
        return f"What is the most defensible technical tradeoff in your answer to '{question[:60]}'"

    def _red_flags(self, answer: str, trap_mode: bool) -> list[str]:
        red_flags = []
        if trap_mode and any(term in answer for term in ["always", "never", "perfect", "trivial"]):
            red_flags.append("Overconfident language can signal shallow reasoning")
        if len(answer.split()) < 20:
            red_flags.append("Very short answer for a senior-level prompt")
        if """I don't know""" in answer.lower():
            red_flags.append("Needs a better recovery strategy for uncertainty")
        # detect buzzword-heavy answers
        buzzwords = ["AI", "blockchain", "machine learning", "microservices", "cloud-native", "serverless"]
        lower = answer.lower()
        buzz_count = sum(1 for b in buzzwords if b.lower() in lower)
        if buzz_count >= 3 and len(answer.split()) < 80:
            red_flags.append("Buzzword-heavy answer with little substance")
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
