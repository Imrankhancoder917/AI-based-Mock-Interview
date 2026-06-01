from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import math
import re
from statistics import mean

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


@dataclass(slots=True)
class ReportSection:
    title: str
    value: str | int | float | None = None
    description: str = ""
    items: list[str] = field(default_factory=list)


@dataclass(slots=True)
class InterviewReport:
    candidate_name: str
    overall_score: int
    technical_score: int
    communication_score: int
    strengths: list[str]
    weaknesses: list[str]
    improvement_roadmap: list[str]
    resume_honesty_check: str
    transcript_summary: str
    session_highlights: list[str]
    question_count: int
    average_answer_length: int
    average_evaluation_score: float
    data_points: dict[str, str | int | float | list[str]] = field(default_factory=dict)


class ReportService:
    """Builds a polished interview feedback report from the session state."""

    def build_report(self, *, user_name: str, interview_state: dict, resume_profile: dict | None = None, job_description: dict | None = None) -> InterviewReport:
        history = list(interview_state.get("history", []))
        resume_profile = resume_profile or interview_state.get("resume_profile") or {}
        job_description = job_description or interview_state.get("job_description") or {}

        scores = [int(item.get("score", 0)) for item in history if self._is_number(item.get("score"))]
        average_score = mean(scores) if scores else 0.0
        overall_score = int(round(average_score * 10)) if average_score <= 10 else self._normalize_score(average_score)

        technical_score = self._normalize_score(self._technical_score(history, resume_profile, job_description))
        communication_score = self._normalize_score(self._communication_score(history))

        strengths = self._strengths(history, technical_score, communication_score)
        weaknesses = self._weaknesses(history, technical_score, communication_score)
        roadmap = self._roadmap(weaknesses, resume_profile, job_description)
        honesty_check = self._resume_honesty_check(history, resume_profile)
        transcript_summary = self._transcript_summary(history)
        highlights = self._session_highlights(history)
        average_length = self._average_answer_length(history)

        return InterviewReport(
            candidate_name=user_name,
            overall_score=overall_score,
            technical_score=technical_score,
            communication_score=communication_score,
            strengths=strengths,
            weaknesses=weaknesses,
            improvement_roadmap=roadmap,
            resume_honesty_check=honesty_check,
            transcript_summary=transcript_summary,
            session_highlights=highlights,
            question_count=len(history),
            average_answer_length=average_length,
            average_evaluation_score=round(average_score, 2),
            data_points={
                "role_family": interview_state.get("role_family", "adaptive"),
                "difficulty": interview_state.get("difficulty", 5),
                "skills": resume_profile.get("skills", []),
                "recent_feedback": interview_state.get("last_feedback", ""),
            },
        )

    def build_pdf(self, report: InterviewReport) -> bytes:
        buffer = BytesIO()
        doc = BaseDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=0.55 * inch,
            rightMargin=0.55 * inch,
            topMargin=0.65 * inch,
            bottomMargin=0.55 * inch,
            title=f"InterviewForge Report - {report.candidate_name}",
        )

        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
        doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self._draw_page_background)])

        styles = self._styles()
        story = []

        story.append(Paragraph("InterviewForge", styles["eyebrow"]))
        story.append(Paragraph(f"Interview Feedback Report", styles["title"]))
        story.append(Paragraph(f"Prepared for {report.candidate_name}", styles["subtitle"]))
        story.append(Spacer(1, 0.18 * inch))

        summary_table = Table(
            [
                [self._metric_box("Overall", report.overall_score), self._metric_box("Technical", report.technical_score), self._metric_box("Communication", report.communication_score)],
            ],
            colWidths=[doc.width / 3.0] * 3,
            hAlign="LEFT",
        )
        summary_table.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 0.18 * inch))

        story.extend(self._bullet_section("Strengths", report.strengths, styles))
        story.extend(self._bullet_section("Weaknesses", report.weaknesses, styles))
        story.extend(self._bullet_section("Improvement roadmap", report.improvement_roadmap, styles))

        info_cards = Table(
            [
                [
                    Paragraph(f"<b>Resume honesty check</b><br/>{self._escape(report.resume_honesty_check)}", styles["body"]),
                    Paragraph(f"<b>Transcript summary</b><br/>{self._escape(report.transcript_summary)}", styles["body"]),
                ]
            ],
            colWidths=[doc.width / 2.0] * 2,
            hAlign="LEFT",
        )
        info_cards.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0d1528")),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#23304e")),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#23304e")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ]))
        story.append(info_cards)
        story.append(Spacer(1, 0.16 * inch))

        highlights = [Paragraph(f"• {self._escape(item)}", styles["body"]) for item in report.session_highlights]
        story.append(Paragraph("Session highlights", styles["section"]))
        story.append(Spacer(1, 0.06 * inch))
        story.extend(highlights)
        story.append(Spacer(1, 0.18 * inch))

        footer_table = Table(
            [[
                Paragraph(f"<b>Questions answered</b><br/>{report.question_count}", styles["tiny"]),
                Paragraph(f"<b>Average answer length</b><br/>{report.average_answer_length} words", styles["tiny"]),
                Paragraph(f"<b>Average evaluation score</b><br/>{report.average_evaluation_score}/10", styles["tiny"]),
            ]],
            colWidths=[doc.width / 3.0] * 3,
        )
        footer_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0c1426")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#2f3e5f")),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#2f3e5f")),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(footer_table)

        doc.build(story)
        return buffer.getvalue()

    def _styles(self):
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name="InterviewTitle",
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=colors.HexColor("#f5f7fb"),
            alignment=TA_LEFT,
            spaceAfter=4,
        ))
        styles.add(ParagraphStyle(
            name="InterviewSubtitle",
            fontName="Helvetica",
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor("#aab6d6"),
            alignment=TA_LEFT,
            spaceAfter=12,
        ))
        styles.add(ParagraphStyle(
            name="InterviewEyebrow",
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#87f5d8"),
            alignment=TA_LEFT,
            spaceAfter=4,
        ))
        styles.add(ParagraphStyle(
            name="InterviewSection",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#f5f7fb"),
            alignment=TA_LEFT,
            spaceBefore=10,
            spaceAfter=6,
        ))
        styles.add(ParagraphStyle(
            name="InterviewBody",
            fontName="Helvetica",
            fontSize=10.2,
            leading=14,
            textColor=colors.HexColor("#d4def7"),
            alignment=TA_LEFT,
            spaceAfter=6,
        ))
        styles.add(ParagraphStyle(
            name="InterviewTiny",
            fontName="Helvetica",
            fontSize=8.8,
            leading=11,
            textColor=colors.HexColor("#d4def7"),
            alignment=TA_CENTER,
        ))

        return {
            "title": styles["InterviewTitle"],
            "subtitle": styles["InterviewSubtitle"],
            "eyebrow": styles["InterviewEyebrow"],
            "section": styles["InterviewSection"],
            "body": styles["InterviewBody"],
            "tiny": styles["InterviewTiny"],
        }

    def _metric_box(self, label: str, value: int | float) -> Paragraph:
        styles = self._styles()
        return Paragraph(
            f"<para align='center'><font color='#8ef7d9'><b>{self._escape(label)}</b></font><br/><font size='24'><b>{self._escape(value)}</b></font></para>",
            styles["body"],
        )

    def _bullet_section(self, title: str, items: list[str], styles: dict[str, ParagraphStyle]):
        story = [Paragraph(title, styles["section"])]
        story.extend([Paragraph(f"• {self._escape(item)}", styles["body"]) for item in items] or [Paragraph("• No clear signal was detected.", styles["body"])])
        return story

    def _draw_page_background(self, canvas, doc):  # pragma: no cover - PDF rendering
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#06101d"))
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#0d1528"))
        canvas.roundRect(18, 18, A4[0] - 36, A4[1] - 36, 16, fill=1, stroke=0)
        canvas.setStrokeColor(colors.HexColor("#243253"))
        canvas.setLineWidth(1)
        canvas.roundRect(22, 22, A4[0] - 44, A4[1] - 44, 14, fill=0, stroke=1)
        canvas.setFillColor(colors.HexColor("#87f5d8"))
        canvas.circle(48, A4[1] - 50, 3, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#f5f7fb"))
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(60, A4[1] - 54, "InterviewForge Report")
        canvas.restoreState()

    def _technical_score(self, history: list[dict], resume_profile: dict, job_description: dict) -> float:
        score = 5.0
        technical_terms = ["tradeoff", "latency", "scale", "system", "architecture", "reliability", "deployment", "metrics", "debug", "backend", "frontend", "database", "api"]
        technical_hits = 0
        for item in history:
            answer = str(item.get("answer", "")).lower()
            if any(term in answer for term in technical_terms):
                technical_hits += 1
            if re.search(r"\b\d+\b", answer):
                technical_hits += 0.5
        score += technical_hits * 0.8
        if resume_profile.get("skills"):
            score += min(1.2, len(resume_profile.get("skills", [])) * 0.15)
        if job_description.get("technologies"):
            score += min(1.0, len(job_description.get("technologies", [])) * 0.12)
        return min(10.0, score)

    def _communication_score(self, history: list[dict]) -> float:
        if not history:
            return 5.0
        scores = []
        for item in history:
            answer = str(item.get("answer", "")).strip()
            word_count = len(answer.split())
            sentence_count = max(1, len(re.findall(r"[.!?]+", answer)))
            clarity = 4.0 + min(3.0, word_count / 45.0)
            structure = 1.0 if sentence_count >= 2 else 0.4
            filler_penalty = 0.6 if re.search(r"\b(um|uh|like)\b", answer.lower()) else 1.0
            scores.append(min(10.0, (clarity + structure) * filler_penalty))
        return mean(scores)

    def _strengths(self, history: list[dict], technical_score: float, communication_score: float) -> list[str]:
        strengths = []
        if technical_score >= 7:
            strengths.append("You used interviewer-grade technical language and tied answers to engineering decisions.")
        if communication_score >= 7:
            strengths.append("Your answers were generally structured and easy to follow under time pressure.")
        if any(int(item.get("score", 0)) >= 8 for item in history):
            strengths.append("At least one answer landed strongly and showed clear ownership.")
        if len(history) >= 3:
            strengths.append("You sustained enough momentum to work through multiple prompts without losing focus.")
        return strengths or ["There were signs of direction and domain familiarity."]

    def _weaknesses(self, history: list[dict], technical_score: float, communication_score: float) -> list[str]:
        weaknesses = []
        if technical_score < 7:
            weaknesses.append("Some responses stayed high-level and did not include enough implementation detail.")
        if communication_score < 7:
            weaknesses.append("A few answers could be sharper, shorter, and more directly anchored to the decision.")
        if any(int(item.get("score", 0)) <= 4 for item in history):
            weaknesses.append("At least one response suggested uncertainty or a weak recovery under pressure.")
        if len(history) < 3:
            weaknesses.append("There were not enough answers to fully stabilize the signal.")
        return weaknesses or ["The session still needs more evidence to be definitive."]

    def _roadmap(self, weaknesses: list[str], resume_profile: dict, job_description: dict) -> list[str]:
        roadmap = [
            "Use a decision-first structure: state what you chose, why, and what tradeoff you accepted.",
            "Add measurable outcomes to every answer: latency, throughput, conversion, quality, or cost.",
            "Practice one follow-up sentence for each answer so you can recover when an interviewer pushes deeper.",
        ]
        if resume_profile.get("skills"):
            roadmap.append("Prepare one crisp example per key skill from your resume and rehearse the engineering rationale behind it.")
        if job_description.get("responsibilities"):
            roadmap.append("Map each job responsibility to one concrete story so your answers sound targeted rather than generic.")
        if any("high-level" in weakness.lower() for weakness in weaknesses):
            roadmap.append("Force yourself to name one specific system component, one constraint, and one measured result.")
        return roadmap

    def _resume_honesty_check(self, history: list[dict], resume_profile: dict) -> str:
        claimed_skills = {str(item).lower() for item in resume_profile.get("skills", [])}
        if not claimed_skills:
            return "No resume skills were available to verify, so the honesty check is inconclusive."

        supported = set()
        for item in history:
            answer = str(item.get("answer", "")).lower()
            for skill in claimed_skills:
                if skill in answer:
                    supported.add(skill)

        coverage = len(supported) / max(1, len(claimed_skills))
        if coverage >= 0.7:
            return "Most of the highlighted skills were reflected in your answers, which suggests a consistent resume narrative."
        if coverage >= 0.4:
            return "Some resume claims were supported, but several important skills never appeared naturally in the interview."
        return "The interview did not strongly validate the resume story. Tighten the evidence behind your stated skills."

    def _transcript_summary(self, history: list[dict]) -> str:
        if not history:
            return "No interview transcript was captured in this session."

        top_scores = [int(item.get("score", 0)) for item in history]
        average_score = mean(top_scores)
        strongest = max(history, key=lambda item: int(item.get("score", 0)))
        weakest = min(history, key=lambda item: int(item.get("score", 0)))
        return (
            f"You answered {len(history)} prompt(s) with an average score of {average_score:.1f}/10. "
            f"The strongest turn was '{self._shorten(strongest.get('question', ''))}', while the weakest turn centered on '{self._shorten(weakest.get('question', ''))}'."
        )

    def _session_highlights(self, history: list[dict]) -> list[str]:
        highlights = []
        for item in sorted(history, key=lambda entry: int(entry.get("score", 0)), reverse=True)[:3]:
            highlights.append(f"{item.get('question', 'Question')} -> scored {item.get('score', 0)}/10")
        return highlights or ["No highlights available."]

    def _average_answer_length(self, history: list[dict]) -> int:
        lengths = [len(str(item.get("answer", "")).split()) for item in history if str(item.get("answer", "")).strip()]
        return round(mean(lengths)) if lengths else 0

    def _normalize_score(self, score: float) -> int:
        return max(0, min(100, int(round(score * 10 if score <= 10 else score))))

    def _shorten(self, text: str, limit: int = 80) -> str:
        compact = re.sub(r"\s+", " ", str(text)).strip()
        return compact[: limit - 3] + "..." if len(compact) > limit else compact

    def _escape(self, value) -> str:
        return re.sub(r"[<>&]", lambda match: {"<": "&lt;", ">": "&gt;", "&": "&amp;"}[match.group(0)], str(value))

    def _is_number(self, value) -> bool:
        try:
            float(value)
            return True
        except Exception:
            return False