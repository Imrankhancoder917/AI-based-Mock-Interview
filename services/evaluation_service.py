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
    relevance: float = 0.0
    keyword_match: float = 0.0
    answer_length: float = 0.0
    technical_accuracy: float = 0.0
    depth: float = 0.0
    reasoning_score: float = 0.0
    communication: float = 0.0
    repeated_answer_detected: bool = False



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
        session_history: list[dict] | None = None,
    ) -> AnswerEvaluation:
        # Calculate rule engine objective metrics
        relevance = self._compute_relevance_score(question, answer, list(expected_signals or []))
        length = self._compute_length_score(answer)
        keyword_match = self._compute_keyword_match_score(question, answer, list(expected_signals or []))

        # Check generic and repetition metrics
        penalty, repeated_detected = self._compute_repetition_penalty_and_flag(answer, session_history)
        is_generic = False
        if "project" in question.lower() or "built" in question.lower() or "implemented" in question.lower():
            if not self._check_project_context(question, answer, list(expected_signals or [])):
                is_generic = True
        if self._is_definitional_answer(answer):
            is_generic = True

        # Attempt Groq-based semantic evaluation first
        try:
            api_key = os.environ.get("GROQ_API_KEY", "")
            if api_key:
                result = self._call_groq_evaluator(question, answer, list(expected_signals or []), difficulty, trap_mode, api_key)
                if result:
                    # Subjective scores from LLM
                    technical_accuracy = float(result.get("technical_accuracy", 5.0))
                    depth = float(result.get("depth", 5.0))
                    communication = float(result.get("communication", 5.0))
                    reasoning_score = float(result.get("reasoning_score", 5.0))
                    reasoning_text = str(result.get("explanation") or result.get("reasoning", "")).strip()

                    # Final Score Formula (0-100)
                    raw_score = (
                        relevance * 0.35 +
                        keyword_match * 0.20 +
                        length * 0.10 +
                        technical_accuracy * 0.15 +
                        depth * 0.10 +
                        reasoning_score * 0.05 +
                        communication * 0.05
                    )
                    score_100 = raw_score * 10

                    # Caps & Penalties
                    if not answer.strip():
                        score_100 = 0.0
                    elif relevance == 0:
                        score_100 = min(score_100, 20.0)
                    elif is_generic:
                        score_100 = min(score_100, 40.0)

                    score_100 -= penalty
                    score_100 = max(0.0, min(100.0, score_100))
                    
                    final_score = int(round(score_100 / 10.0))

                    strengths = [str(s) for s in (result.get("strengths") or [])][:4]
                    gaps = [str(s) for s in (result.get("gaps") or [])][:4]
                    follow_up = str(result.get("follow_up") or "").strip()
                    red_flags = [str(s) for s in (result.get("red_flags") or [])][:3]

                    return AnswerEvaluation(
                        score=final_score,
                        reasoning=reasoning_text,
                        strengths=strengths,
                        gaps=gaps,
                        follow_up=follow_up,
                        red_flags=red_flags,
                        relevance=relevance,
                        keyword_match=keyword_match,
                        answer_length=length,
                        technical_accuracy=technical_accuracy,
                        depth=depth,
                        reasoning_score=reasoning_score,
                        communication=communication,
                        repeated_answer_detected=repeated_detected
                    )
        except Exception:
            pass

        # Fallback to deterministic scoring
        return self._heuristic_score(question, answer, expected_signals, difficulty, trap_mode, session_history)

    def _call_groq_evaluator(self, question: str, answer: str, expected: list[str], difficulty: int, trap_mode: bool, api_key: str) -> dict | None:
        """Call Groq responses API to obtain a structured JSON evaluation."""
        model = os.environ.get("SECONDARY_LLM_MODEL", "grok-3-mini")

        system_prompt = (
            "You are a strict software engineering technical interviewer. Evaluate the candidate's ANSWER to the given QUESTION.\n"
            "Evaluate ONLY the following subjective criteria on a scale of 0 to 10:\n"
            "- technical_accuracy (0-10)\n"
            "- depth (0-10)\n"
            "- communication (0-10)\n"
            "- reasoning_score (0-10)\n\n"
            "Be EXTREMELY strict. Do NOT be encouraging or motivational. Do not assume correctness. Vague or generic answers must receive very low scores.\n"
            "Return a single JSON object and nothing else with fields:\n"
            "technical_accuracy (number), depth (number), communication (number), reasoning_score (number), "
            "explanation (short string describing the technical evaluation details), "
            "strengths (array of concise strings), gaps (array of concise strings), "
            "follow_up (one follow-up question to probe the biggest gap), red_flags (array of concise strings).\n"
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
                    if s.startswith("```") and s.endswith("```"):
                        parts = s.split("\n", 1)
                        if len(parts) > 1:
                            s = parts[1].rsplit("\n", 1)[0]
                    try:
                        obj = json.loads(s)
                        if "technical_accuracy" in obj:
                            return obj
                    except Exception:
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
        session_history: list[dict] | None = None,
    ) -> AnswerEvaluation:
        answer_clean = self._normalize(answer)
        question_clean = self._normalize(question)
        expected = [self._normalize(item) for item in (expected_signals or []) if item]

        relevance = self._compute_relevance_score(question, answer, list(expected_signals or []))
        length = self._compute_length_score(answer)
        keyword_match = self._compute_keyword_match_score(question, answer, list(expected_signals or []))

        specificity = self._specificity_score(answer_clean)
        structure = self._structure_score(answer, len(answer_clean.split()), max(1, len(re.findall(r"[.!?]+", answer))))
        seniority = self._seniority_score(answer_clean)
        faang_density = self._faang_density(answer_clean)

        tech_acc = min(10.0, specificity * 2.5 + (2.0 if relevance > 5 else 0.0))
        depth = min(10.0, specificity * 2.0 + faang_density * 2.0 + seniority * 2.0)
        communication = min(10.0, structure * 5.0)
        reasoning_score = min(10.0, seniority * 4.0 + (3.0 if "tradeoff" in answer_clean or "why" in question_clean else 1.0))

        if not answer_clean:
            tech_acc = depth = communication = reasoning_score = 0.0

        raw_score = (
            relevance * 0.35 +
            keyword_match * 0.20 +
            length * 0.10 +
            tech_acc * 0.15 +
            depth * 0.10 +
            reasoning_score * 0.05 +
            communication * 0.05
        )
        score_100 = raw_score * 10

        is_generic = False
        if "project" in question.lower() or "built" in question.lower() or "implemented" in question.lower():
            if not self._check_project_context(question, answer, list(expected_signals or [])):
                is_generic = True
        if self._is_definitional_answer(answer):
            is_generic = True

        if not answer_clean:
            score_100 = 0.0
        elif relevance == 0:
            score_100 = min(score_100, 20.0)
        elif is_generic:
            score_100 = min(score_100, 40.0)

        penalty, repeated_detected = self._compute_repetition_penalty_and_flag(answer, session_history)
        score_100 -= penalty
        score_100 = max(0.0, min(100.0, score_100))

        final_score = int(round(score_100 / 10.0))

        strengths = self._strengths(answer_clean, expected, specificity, relevance, structure, faang_density)
        gaps = self._gaps(answer_clean, expected, specificity, relevance, structure)
        reasoning_text = self._build_reasoning(final_score, strengths, gaps)
        follow_up = self._follow_up_for_gap(question, expected, strengths=strengths, gaps=gaps)
        red_flags = self._red_flags(answer_clean, trap_mode)

        return AnswerEvaluation(
            score=final_score,
            reasoning=reasoning_text,
            strengths=strengths[:4],
            gaps=gaps[:4],
            follow_up=follow_up,
            red_flags=red_flags[:3],
            relevance=relevance,
            keyword_match=keyword_match,
            answer_length=length,
            technical_accuracy=tech_acc,
            depth=depth,
            reasoning_score=reasoning_score,
            communication=communication,
            repeated_answer_detected=repeated_detected
        )

    def generate_feedback(self, evaluation: AnswerEvaluation, question: str) -> str:
        opening = f"You handled the prompt: {question[:95].rstrip()}"
        score_line = f"Score: {evaluation.score}/10."

        score_val = evaluation.score * 10
        if score_val >= 85:
            tone = "Strong technical understanding. Specific examples. Good architecture awareness."
        elif score_val >= 60:
            tone = "Understands fundamentals. Needs more depth and technical detail."
        elif score_val >= 40:
            tone = "Limited explanation. Missing implementation details."
        else:
            tone = "Answer does not adequately address the question. Lacks technical accuracy or relevance."

        next_steps = []
        if evaluation.gaps:
            next_steps.append(f"Improve: {evaluation.gaps[0].lower()}")
        if evaluation.follow_up:
            next_steps.append(f"Follow-up practice: {evaluation.follow_up}")
        if evaluation.red_flags:
            next_steps.append(f"Watch out for: {evaluation.red_flags[0].lower()}")
        if evaluation.repeated_answer_detected:
            next_steps.append("WARNING: Repeated Answer Pattern Detected - Multiple answers were highly similar and did not adequately address individual questions.")

        return "\n".join([opening, score_line, tone, *next_steps])

    def _compute_relevance_score(self, question: str, answer: str, expected_signals: list[str]) -> float:
        stop_words = {
            "what", "is", "how", "did", "you", "use", "the", "a", "an", "and", "in", "on", "of", "to", "for", 
            "with", "about", "your", "my", "project", "explain", "describe", "detail", "tell", "me", "some",
            "any", "that", "this", "these", "those", "it", "they", "we", "us", "them", "he", "she", "i", "was"
        }
        q_words = {w for w in re.findall(r"\b\w{3,}\b", question.lower()) if w not in stop_words}
        s_words = set()
        for sig in expected_signals:
            for w in re.findall(r"\b\w{3,}\b", sig.lower()):
                s_words.add(w)

        key_words = q_words.union(s_words)
        ans_words = {w for w in re.findall(r"\b\w{3,}\b", answer.lower())}

        if not ans_words:
            return 0.0

        matches = key_words.intersection(ans_words)
        if not matches:
            return 0.0

        overlap_ratio = len(matches) / max(1, len(key_words))
        score = 2.0 + min(8.0, overlap_ratio * 15.0)
        return round(score, 2)

    def _compute_length_score(self, answer: str) -> float:
        words = len(answer.strip().split())
        if words < 10:
            return 1.0
        elif words < 25:
            return 4.0
        elif words < 60:
            return 6.0
        elif words < 120:
            return 8.0
        else:
            return 10.0

    def _compute_repetition_penalty_and_flag(self, answer: str, session_history: list[dict] | None) -> tuple[int, bool]:
        if not session_history or not answer:
            return 0, False

        from difflib import SequenceMatcher
        ans_clean = re.sub(r"\s+", " ", answer.strip().lower())
        repeat_count = 0
        is_repeat = False

        for h in session_history:
            prev_ans = str(h.get("answer", "")).strip().lower()
            if not prev_ans:
                continue
            prev_ans_clean = re.sub(r"\s+", " ", prev_ans)
            
            similarity = SequenceMatcher(None, ans_clean, prev_ans_clean).ratio()
            if similarity > 0.8:
                is_repeat = True
                repeat_count += 1

        if is_repeat:
            penalty = repeat_count * 10
            return penalty, True

        return 0, False

    def _compute_keyword_match_score(self, question: str, answer: str, expected_signals: list[str]) -> float:
        expected_keywords = set()
        stop_words = {"what", "is", "how", "did", "you", "use", "the", "a", "an", "and", "in", "on", "of", "to", "for", "with", "about", "your", "my", "project", "explain"}

        for sig in expected_signals:
            for w in re.findall(r"\b\w{3,}\b", sig.lower()):
                expected_keywords.add(w)

        for w in re.findall(r"\b\w{3,}\b", question.lower()):
            if w not in stop_words:
                expected_keywords.add(w)

        if not expected_keywords:
            return 10.0

        ans_lower = answer.lower()
        matched = [kw for kw in expected_keywords if kw in ans_lower]
        score = (len(matched) / len(expected_keywords)) * 10.0
        return round(score, 2)

    def _check_project_context(self, question: str, answer: str, expected_signals: list[str]) -> bool:
        ans_lower = answer.lower()
        architecture_terms = {"architecture", "design", "structure", "system", "components", "pattern", "database", "server", "microservice", "api", "flow"}
        implementation_terms = {"implemented", "built", "developed", "configured", "used", "wrote", "integrated", "created", "deployed"}

        has_architecture = any(t in ans_lower for t in architecture_terms)
        has_implementation = any(t in ans_lower for t in implementation_terms)
        return has_architecture and has_implementation

    def _is_definitional_answer(self, answer: str) -> bool:
        ans_clean = answer.strip().lower()
        pattern = r"^[a-z0-9+#_.\-]+\s+is\s+(?:a|an|the|used|defined|referred|stands)\b"
        if re.match(pattern, ans_clean) and len(ans_clean.split()) < 20:
            return True
        return False

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
