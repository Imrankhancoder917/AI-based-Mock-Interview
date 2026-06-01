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
