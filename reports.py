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