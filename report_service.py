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
    confidence_score: int
    problem_solving_score: int
    project_explanation_score: int
    core_subjects_score: int
    duration_mins: int
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

        tech_accs = [h.get("technical_accuracy") for h in history if h.get("technical_accuracy") is not None]
        if tech_accs:
            technical_score = self._normalize_score(mean(tech_accs))
        else:
            technical_score = self._normalize_score(self._technical_score(history, resume_profile, job_description))

        comms = [h.get("communication") for h in history if h.get("communication") is not None]
        if comms:
            communication_score = self._normalize_score(mean(comms))
        else:
            communication_score = self._normalize_score(self._communication_score(history))

        relevances = [h.get("relevance") for h in history if h.get("relevance") is not None]
        relevance_score = self._normalize_score(mean(relevances)) if relevances else technical_score

        depths = [h.get("depth") for h in history if h.get("depth") is not None]
        depth_score = self._normalize_score(mean(depths)) if depths else technical_score

        repeated_answer_detected = any(h.get("repeated_answer_detected", False) for h in history)

        confidence_score = self._normalize_score(self._confidence_score(history))
        problem_solving_score = self._normalize_score(self._problem_solving_score(history))
        project_explanation_score = self._normalize_score(self._project_explanation_score(history))
        core_subjects_score = self._normalize_score(self._core_subjects_score(history))
        
        duration_mins = interview_state.get("duration_mins", 0)

        strengths = self._strengths(history, technical_score, communication_score)
        weaknesses = self._weaknesses(history, technical_score, communication_score)
        if repeated_answer_detected:
            weaknesses.insert(0, "Repeated Answer Pattern Detected: Multiple answers were highly similar and did not adequately address individual questions.")
            
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
            confidence_score=confidence_score,
            problem_solving_score=problem_solving_score,
            project_explanation_score=project_explanation_score,
            core_subjects_score=core_subjects_score,
            duration_mins=duration_mins,
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
                "relevance_score": relevance_score,
                "depth_score": depth_score,
                "repeated_answer_detected": repeated_answer_detected,
            },
        )

    def reconstruct_state_from_db(self, session) -> dict:
        history = []
        for q in session.questions:
            if q.answer:
                score_val = float(q.answer.score) if q.answer.score is not None else 5.0
                history.append({
                    "question": q.question_text,
                    "answer": q.answer.response_text,
                    "score": score_val,
                    "weaknesses": [],
                    "topic": q.question_type or "",
                    "technical_accuracy": score_val,
                    "relevance": score_val,
                    "depth": score_val,
                    "communication": score_val,
                    "repeated_answer_detected": False,
                })
        
        duration = 0
        if session.started_at and session.completed_at:
            duration = int((session.completed_at - session.started_at).total_seconds() / 60)
        elif session.feedback_report and session.feedback_report.full_report_json:
            duration = session.feedback_report.full_report_json.get("duration_mins", 0)
            
        return {
            "history": history,
            "duration_mins": duration,
            "difficulty": session.questions[0].difficulty if session.questions else 5,
            "role_family": session.questions[0].question_type if session.questions else "adaptive",
        }

    def back_populate_session(self, session_id: int):
        from extensions import db
        from models import InterviewSession
        session = db.session.get(InterviewSession, session_id)
        if not session or not session.feedback_report:
            return
            
        state = self.reconstruct_state_from_db(session)
        resume_profile = session.candidate_profile.parsed_resume_data if session.candidate_profile else {}
        job_description = session.job_description.parsed_jd_data if session.job_description else {}
        
        report = self.build_report(
            user_name=session.user.full_name,
            interview_state=state,
            resume_profile=resume_profile,
            job_description=job_description
        )
        self.populate_db_analytics(session.id, report, state["history"])

    def populate_db_analytics(self, session_id: int, report: InterviewReport, history: list[dict]):
        from extensions import db
        from models import (
            InterviewSession, InterviewHistory,
            InterviewReport as DBInterviewReport, QuestionEvaluation,
            InterviewAnalytics, SkillAnalytics
        )
        from datetime import datetime, timezone
        
        session = db.session.get(InterviewSession, session_id)
        if not session:
            return

        # 1. InterviewHistory
        hist = InterviewHistory.query.filter_by(interview_session_id=session_id).first()
        if not hist:
            hist = InterviewHistory(interview_session_id=session_id)
            db.session.add(hist)
        
        hist.user_id = session.user_id
        hist.interview_name = f"{session.candidate_profile.target_role or 'Technical'} Mock Interview"
        hist.interview_type = f"{session.job_description.title or 'Technical'} Mock"
        hist.date = session.completed_at or session.started_at or datetime.now(timezone.utc)
        hist.duration_mins = report.duration_mins
        hist.total_questions = len(history)
        hist.questions_answered = len(history)
        
        diff_val = report.data_points.get("difficulty", 5)
        if isinstance(diff_val, int):
            hist.difficulty = "Easy" if diff_val <= 3 else "Intermediate" if diff_val <= 7 else "Advanced"
        else:
            hist.difficulty = str(diff_val)
            
        hist.status = session.status or "completed"

        # 2. InterviewReport
        rep = DBInterviewReport.query.filter_by(interview_session_id=session_id).first()
        if not rep:
            rep = DBInterviewReport(interview_session_id=session_id)
            db.session.add(rep)
            
        rep.summary = report.transcript_summary
        rep.strengths = report.strengths
        rep.weaknesses = report.weaknesses
        rep.recommendations = report.improvement_roadmap

        # 3. QuestionEvaluations
        QuestionEvaluation.query.filter_by(interview_session_id=session_id).delete()
        
        for idx, item in enumerate(history):
            q_text = item.get("question")
            q_model = None
            for q in session.questions:
                if q.question_text == q_text:
                    q_model = q
                    break
            
            score_val = item.get("score", 5.0)
            q_strengths = item.get("strengths") or []
            q_weaknesses = item.get("weaknesses") or item.get("gaps") or []
            q_suggestions = item.get("suggestions") or []
            
            q_eval_text = ""
            if q_model and q_model.answer:
                q_eval_text = q_model.answer.feedback or ""
            
            if isinstance(q_strengths, str):
                q_strengths = [q_strengths]
            if isinstance(q_weaknesses, str):
                q_weaknesses = [q_weaknesses]
            if isinstance(q_suggestions, str):
                q_suggestions = [q_suggestions]

            q_ev = QuestionEvaluation(
                interview_session_id=session_id,
                question_text=q_text,
                answer_text=item.get("answer", ""),
                score=score_val,
                evaluation=q_eval_text,
                strengths=q_strengths,
                weaknesses=q_weaknesses,
                suggestions=q_suggestions,
                time_spent=120,
                question_type=q_model.question_type if q_model else "adaptive",
                difficulty=q_model.difficulty if q_model else 5
            )
            db.session.add(q_ev)

        # 4. InterviewAnalytics
        an = InterviewAnalytics.query.filter_by(interview_session_id=session_id).first()
        if not an:
            an = InterviewAnalytics(interview_session_id=session_id)
            db.session.add(an)
            
        an.overall_score = report.overall_score
        
        if report.overall_score >= 90:
            an.performance_grade = "A+"
            an.interview_rating = "Strong Hire"
        elif report.overall_score >= 80:
            an.performance_grade = "A"
            an.interview_rating = "Strong Hire"
        elif report.overall_score >= 70:
            an.performance_grade = "B"
            an.interview_rating = "Hire"
        elif report.overall_score >= 60:
            an.performance_grade = "C"
            an.interview_rating = "Lean Hire"
        else:
            an.performance_grade = "F"
            an.interview_rating = "No Hire"

        an.confidence_score = report.confidence_score
        an.completion_percentage = int((len(history) / 15.0) * 100) if len(history) < 15 else 100
        
        # breakdown dimensions
        an.technical_accuracy = report.technical_score
        an.relevance = report.data_points.get("relevance_score", report.technical_score)
        an.communication = report.communication_score
        an.depth = report.data_points.get("depth_score", report.technical_score)
        an.problem_solving = report.problem_solving_score
        an.system_design = report.core_subjects_score
        an.project_understanding = report.project_explanation_score

        # 5. SkillAnalytics
        SkillAnalytics.query.filter_by(interview_session_id=session_id).delete()
        
        resume_skills = session.candidate_profile.parsed_resume_data.get("skills", []) if session.candidate_profile else []
        cleaned_skills = []
        for skill in resume_skills:
            if isinstance(skill, str) and skill.strip():
                for item in history:
                    q_text = str(item.get("question", "")).lower()
                    a_text = str(item.get("answer", "")).lower()
                    if skill.lower() in q_text or skill.lower() in a_text:
                        cleaned_skills.append(skill)
                        break
                        
        seen = set()
        cleaned_skills = [x for x in cleaned_skills if not (x.lower() in seen or seen.add(x.lower()))]
        
        from statistics import mean
        for skill in cleaned_skills:
            skill_scores = []
            for item in history:
                q_text = str(item.get("question", "")).lower()
                a_text = str(item.get("answer", "")).lower()
                if skill.lower() in q_text or skill.lower() in a_text:
                    skill_scores.append(float(item.get("score", 5.0)))
            
            if skill_scores:
                avg_score = int(round(mean(skill_scores) * 10))
                
                if avg_score >= 80:
                    level = "Advanced"
                    priority = "Low"
                elif avg_score >= 60:
                    level = "Intermediate"
                    priority = "Medium"
                else:
                    level = "Beginner"
                    priority = "High"
                    
                sk_an = SkillAnalytics(
                    interview_session_id=session_id,
                    skill_name=skill,
                    average_score=avg_score,
                    performance_level=level,
                    improvement_priority=priority
                )
                db.session.add(sk_an)
                
        db.session.commit()

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

        relevance_val = report.data_points.get("relevance_score")
        depth_val = report.data_points.get("depth_score")

        if relevance_val is not None and depth_val is not None:
            summary_table = Table(
                [
                    [
                        self._metric_box("Overall", report.overall_score),
                        self._metric_box("Technical", report.technical_score),
                        self._metric_box("Communication", report.communication_score)
                    ],
                    [
                        self._metric_box("Relevance", relevance_val),
                        self._metric_box("Depth", depth_val),
                        self._metric_box("Duration", f"{report.duration_mins}m")
                    ]
                ],
                colWidths=[doc.width / 3.0] * 3,
                hAlign="LEFT",
            )
        else:
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

        if report.data_points.get("repeated_answer_detected"):
            warning_style = ParagraphStyle(
                name="RepeatedAnswerWarning",
                parent=styles["body"],
                textColor=colors.HexColor("#ef4444"),
                fontName="Helvetica-Bold",
                backColor=colors.HexColor("#fef2f2"),
                borderColor=colors.HexColor("#fee2e2"),
                borderWidth=1,
                borderPadding=8,
                spaceAfter=10,
            )
            story.append(Paragraph("WARNING: Repeated Answer Pattern Detected<br/><font size='9.5' face='Helvetica' color='#991b1b'>Multiple answers were highly similar and did not adequately address individual questions.</font>", warning_style))
            story.append(Spacer(1, 0.15 * inch))

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

    def _confidence_score(self, history: list[dict]) -> float:
        if not history: return 5.0
        scores = []
        for item in history:
            answer = str(item.get("answer", "")).lower()
            penalty = 0.5 if re.search(r"\b(maybe|i think|probably|not sure|guess)\b", answer) else 1.0
            base_score = float(item.get("score", 5.0))
            scores.append(min(10.0, base_score * penalty + 1.0))
        return mean(scores)

    def _problem_solving_score(self, history: list[dict]) -> float:
        if not history: return 5.0
        scores = []
        for item in history:
            answer = str(item.get("answer", "")).lower()
            bonus = 1.0 if re.search(r"\b(first|then|finally|because|therefore|approach|solution)\b", answer) else 0.0
            base_score = float(item.get("score", 5.0))
            scores.append(min(10.0, base_score + bonus))
        return mean(scores)

    def _project_explanation_score(self, history: list[dict]) -> float:
        if not history: return 5.0
        # Check if they talked about projects
        scores = []
        for item in history:
            answer = str(item.get("answer", "")).lower()
            bonus = 1.0 if re.search(r"\b(built|designed|implemented|project|team|my role|achieved)\b", answer) else 0.0
            base_score = float(item.get("score", 5.0))
            scores.append(min(10.0, base_score + bonus))
        return mean(scores)

    def _core_subjects_score(self, history: list[dict]) -> float:
        if not history: return 5.0
        scores = []
        for item in history:
            answer = str(item.get("answer", "")).lower()
            bonus = 1.0 if re.search(r"\b(database|network|os|operating system|thread|memory|algorithm|structure|oop)\b", answer) else 0.0
            base_score = float(item.get("score", 5.0))
            scores.append(min(10.0, base_score + bonus))
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