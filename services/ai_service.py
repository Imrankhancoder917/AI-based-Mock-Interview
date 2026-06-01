from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from typing import Any

import requests

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
        """Generate a single realistic, interviewer-style question using Groq.

        Falls back to the existing `AdaptiveEngine` when the Groq API is not configured
        or if the request fails for any reason. Returns an `InterviewQuestion`.
        """
        context = self.create_context(resume_profile, job_description, difficulty, session_history)

        api_key = os.environ.get("GROQ_API_KEY", "")
        model = os.environ.get("SECONDARY_LLM_MODEL", "grok-3-mini")

        system_prompt = (
            "You are a senior technical interviewer. Produce EXACTLY one realistic, conversational, "
            "technical interview question. Base the question on the candidate resume profile, the job description, "
            "the session history, any documented weaknesses, and the requested difficulty. Never ask a generic textbook "
            "question unless the candidate appears weak. The output MUST be valid JSON with the fields: \n"
            "  - question: string (the question to ask)\n"
            "  - kind: string (one of 'resume_based','jd_based','follow_up','trap')\n"
            "  - difficulty: integer 1-10\n"
            "  - expected_signals: array of short strings (keywords or signals to look for)\n"
            "  - follow_up_seed: string (optional short seed for followups)\n"
            "  - trap: boolean\n"
            "Return only the JSON object and nothing else. Keep the question concise but natural."
        )

        user_payload = {
            "resume_profile": resume_profile,
            "job_description": job_description or {},
            "session_history": session_history or [],
            "difficulty": difficulty,
        }

        if not api_key:
            # no Groq configured, fallback to existing engine
            return self.engine.build_next_question(context)

        # Try known Groq-style endpoints; prefer the modern /v1/responses API
        endpoints = [
            "https://api.groq.com/v1/responses",
            "https://api.groq.com/openai/v1/responses",
            "https://api.groq.com/openai/v1/chat/completions",
        ]

        prompt = f"{system_prompt}\n\nINPUT:\n{json.dumps(user_payload, ensure_ascii=False)}"

        for url in endpoints:
            try:
                resp = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "input": prompt,
                        "temperature": 0.7,
                        "max_output_tokens": 512,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                payload = resp.json()

                # Groq may return in different shapes; attempt to extract text then parse JSON
                text_candidates = []
                if isinstance(payload, dict):
                    # common keys
                    if "output" in payload and isinstance(payload["output"], str):
                        text_candidates.append(payload["output"])  # legacy shape
                    if "outputs" in payload and isinstance(payload["outputs"], list):
                        for o in payload["outputs"]:
                            if isinstance(o, dict) and "content" in o:
                                # responses API
                                if isinstance(o["content"], list):
                                    for c in o["content"]:
                                        if isinstance(c, dict) and c.get("type") == "output_text":
                                            text_candidates.append(c.get("text", ""))
                                else:
                                    text_candidates.append(str(o.get("content", "")))
                    if "choices" in payload and isinstance(payload["choices"], list):
                        for choice in payload["choices"]:
                            if isinstance(choice, dict):
                                if "message" in choice and isinstance(choice["message"], dict):
                                    text_candidates.append(choice["message"].get("content", ""))
                                text_candidates.append(choice.get("text", ""))

                # Fallback: try top-level text in response
                if not text_candidates:
                    try:
                        text_candidates.append(resp.text)
                    except Exception:
                        pass

                # Try parsing each candidate as JSON
                for txt in text_candidates:
                    if not txt or not isinstance(txt, str):
                        continue
                    txt = txt.strip()
                    # If the model returned code fences, strip them
                    if txt.startswith("```") and txt.endswith("```"):
                        # crude strip
                        parts = txt.split("\n", 1)
                        if len(parts) > 1:
                            txt = parts[1].rsplit("\n", 1)[0]
                    try:
                        obj = json.loads(txt)
                        question_text = str(obj.get("question") or obj.get("prompt") or obj.get("text", "")).strip()
                        kind = str(obj.get("kind", "resume_based"))
                        difficulty_val = int(obj.get("difficulty", max(1, min(10, difficulty))))
                        expected = list(obj.get("expected_signals", [])) or []
                        follow_seed = str(obj.get("follow_up_seed", ""))
                        trap_flag = bool(obj.get("trap", False))

                        return InterviewQuestion(
                            prompt=question_text,
                            kind=kind,
                            difficulty=max(1, min(10, difficulty_val)),
                            expected_signals=[str(s) for s in expected],
                            follow_up_seed=follow_seed,
                            trap=trap_flag,
                        )
                    except Exception:
                        # not JSON - try to interpret as plain text question
                        if txt:
                            return InterviewQuestion(
                                prompt=txt,
                                kind="resume_based",
                                difficulty=max(1, min(10, difficulty)),
                                expected_signals=[],
                                follow_up_seed="",
                                trap=False,
                            )
            except Exception:
                # try next endpoint
                continue

        # If all Groq attempts fail, fall back to the deterministic engine
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
            follow_up_question = self.generate_followup_question(question, answer, evaluation.score)
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

    def generate_followup_question(self, base_question: InterviewQuestion, answer: str, evaluation_score: int) -> InterviewQuestion:
        """Generate a single follow-up question using Groq, falling back to the engine on failure.

        Must return an `InterviewQuestion` instance compatible with existing code.
        """
        api_key = os.environ.get("GROQ_API_KEY", "")
        model = os.environ.get("SECONDARY_LLM_MODEL", "grok-3-mini")

        system_prompt = (
            "You are a pragmatic interviewer crafting a single natural follow-up question. Use the base question, "
            "the candidate's answer, and the numeric evaluation score to decide whether to probe for depth, clarity, or a concrete example. "
            "Return EXACTLY one JSON object with fields: question, kind, difficulty (1-10), expected_signals (array), follow_up_seed, trap (boolean)."
        )

        payload = {
            "base_question": {
                "prompt": base_question.prompt,
                "kind": base_question.kind,
                "difficulty": base_question.difficulty,
                "expected_signals": base_question.expected_signals,
            },
            "answer": answer,
            "evaluation_score": evaluation_score,
        }

        if not api_key:
            return self.engine.generate_follow_up_question(base_question, answer, evaluation_score)

        url = "https://api.groq.com/v1/responses"
        prompt = f"{system_prompt}\n\nINPUT:\n{json.dumps(payload, ensure_ascii=False)}"
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "input": prompt, "temperature": 0.6, "max_output_tokens": 300},
                timeout=8,
            )
            resp.raise_for_status()
            body = resp.json()
            # extract plausible text
            text = None
            if isinstance(body, dict):
                if "output" in body and isinstance(body["output"], str):
                    text = body["output"]
                elif "choices" in body and isinstance(body["choices"], list) and body["choices"]:
                    ch = body["choices"][0]
                    if isinstance(ch, dict) and "message" in ch and isinstance(ch["message"], dict):
                        text = ch["message"].get("content") or ch.get("text")
            if not text:
                text = resp.text

            if text:
                text = text.strip()
                try:
                    obj = json.loads(text)
                    question_text = str(obj.get("question") or obj.get("prompt") or obj.get("text", "")).strip()
                    kind = str(obj.get("kind", "follow_up"))
                    difficulty_val = int(obj.get("difficulty", max(1, min(10, base_question.difficulty + 1))))
                    expected = list(obj.get("expected_signals", [])) or base_question.expected_signals
                    follow_seed = str(obj.get("follow_up_seed", base_question.follow_up_seed or ""))
                    trap_flag = bool(obj.get("trap", False))

                    return InterviewQuestion(
                        prompt=question_text,
                        kind=kind,
                        difficulty=max(1, min(10, difficulty_val)),
                        expected_signals=[str(s) for s in expected],
                        follow_up_seed=follow_seed,
                        trap=trap_flag,
                    )
                except Exception:
                    # fallback to plain-text
                    return InterviewQuestion(
                        prompt=text,
                        kind="follow_up",
                        difficulty=min(10, base_question.difficulty + 1),
                        expected_signals=base_question.expected_signals,
                        follow_up_seed=base_question.follow_up_seed,
                        trap=False,
                    )
        except Exception:
            pass

        # final fallback: original engine
        return self.engine.generate_follow_up_question(base_question, answer, evaluation_score)

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