from __future__ import annotations

from io import BytesIO
from flask import Blueprint, Response, current_app, render_template, request, session, url_for, send_file, redirect, flash, jsonify
from flask_login import current_user, login_required
from statistics import mean

from extensions import db
from report_service import ReportService, InterviewReport
from models import (
    FeedbackReport, InterviewSession, InterviewHistory,
    InterviewReport as DBInterviewReport, QuestionEvaluation,
    InterviewAnalytics, SkillAnalytics
)

reports_bp = Blueprint("reports", __name__)


def _build_report_context() -> tuple[dict, dict, dict]:
    interview_state = session.get("interview_state", {})
    resume_profile = interview_state.get("resume_profile") or session.get("resume_profile") or {}
    job_description = interview_state.get("job_description") or session.get("job_description") or {}
    return interview_state, resume_profile, job_description


@reports_bp.route("/reports/latest")
@login_required
def latest_report():
    completed_sessions = InterviewSession.query.filter_by(user_id=current_user.id, status="completed").order_by(InterviewSession.completed_at.desc()).all()
    
    # Back-populate any session that doesn't have history records
    for s in completed_sessions:
        h_check = InterviewHistory.query.filter_by(interview_session_id=s.id).first()
        if not h_check:
            ReportService().back_populate_session(s.id)
            
    # Refetch completed histories
    all_hist = InterviewHistory.query.filter_by(user_id=current_user.id, status="completed").order_by(InterviewHistory.date.desc()).all()
    
    if not all_hist:
        return render_template(
            "report.html",
            title="Interview Analytics Dashboard | InterviewForge",
            page_type="report",
            body_class="report-page",
            is_empty=True,
            histories=[],
            selected_id=None,
            interview_url=url_for("interview_room"),
            interview_state={},
            overview={},
            report={
                "overall_score": 0,
                "duration_mins": 0,
                "question_count": 0,
                "technical_score": 0,
                "problem_solving_score": 0,
                "communication_score": 0,
                "confidence_score": 0,
                "project_explanation_score": 0,
                "core_subjects_score": 0,
                "transcript_summary": "",
                "strengths": [],
                "weaknesses": [],
                "improvement_roadmap": [],
                "data_points": {
                    "placement_readiness": 0,
                    "recruiter_verdict": "N/A",
                    "relevance_score": 0,
                    "depth_score": 0,
                    "repeated_answer_detected": False
                }
            },
            analytics={},
            skills=[],
            questions=[],
            historical_stats={},
            trend_labels=[],
            trend_data=[],
            comparison=None,
            pdf_url=None
        )
        
    selected_id = request.args.get("id", type=int)
    selected_hist = None
    if selected_id:
        selected_hist = InterviewHistory.query.filter_by(interview_session_id=selected_id, user_id=current_user.id).first()
    
    if not selected_hist:
        selected_hist = all_hist[0]
        selected_id = selected_hist.interview_session_id
        
    session_item = db.session.get(InterviewSession, selected_id)
    hist = selected_hist
    rep = DBInterviewReport.query.filter_by(interview_session_id=selected_id).first()
    an = InterviewAnalytics.query.filter_by(interview_session_id=selected_id).first()
    skills = SkillAnalytics.query.filter_by(interview_session_id=selected_id).all()
    questions = QuestionEvaluation.query.filter_by(interview_session_id=selected_id).order_by(QuestionEvaluation.id.asc()).all()
    
    # Back populate on the fly if details missing
    if not rep or not an or not skills or not questions:
        ReportService().back_populate_session(selected_id)
        rep = DBInterviewReport.query.filter_by(interview_session_id=selected_id).first()
        an = InterviewAnalytics.query.filter_by(interview_session_id=selected_id).first()
        skills = SkillAnalytics.query.filter_by(interview_session_id=selected_id).all()
        questions = QuestionEvaluation.query.filter_by(interview_session_id=selected_id).order_by(QuestionEvaluation.id.asc()).all()
    state = ReportService().reconstruct_state_from_db(session_item)

    # Historical Summary Stats (Section 9)
    total_interviews = len(all_hist)
    avg_score = int(round(mean([float(h.overall_score) for h in all_hist]))) if all_hist else 0
    best_score = int(max([float(h.overall_score) for h in all_hist])) if all_hist else 0
    worst_score = int(min([float(h.overall_score) for h in all_hist])) if all_hist else 0
    total_questions = sum([h.questions_answered for h in all_hist])
    avg_duration = int(round(mean([h.duration_mins for h in all_hist]))) if all_hist else 0
    
    from sqlalchemy import func
    skill_avgs = db.session.query(
        SkillAnalytics.skill_name,
        func.avg(SkillAnalytics.average_score).label("avg")
    ).join(InterviewHistory, SkillAnalytics.interview_session_id == InterviewHistory.interview_session_id)\
     .filter(InterviewHistory.user_id == current_user.id)\
     .group_by(SkillAnalytics.skill_name).all()
     
    strongest_skill = max(skill_avgs, key=lambda x: x[1])[0] if skill_avgs else "None"
    weakest_skill = min(skill_avgs, key=lambda x: x[1])[0] if skill_avgs else "None"
    
    all_skills_history = db.session.query(
        SkillAnalytics.skill_name,
        SkillAnalytics.average_score,
        InterviewHistory.date
    ).join(InterviewHistory, SkillAnalytics.interview_session_id == InterviewHistory.interview_session_id)\
     .filter(InterviewHistory.user_id == current_user.id)\
     .order_by(SkillAnalytics.skill_name, InterviewHistory.date.asc()).all()
     
    from collections import defaultdict
    skill_series = defaultdict(list)
    for name, score, dt in all_skills_history:
        skill_series[name].append((score, dt))
        
    skill_deltas = {}
    for name, series in skill_series.items():
        if len(series) >= 2:
            delta = float(series[-1][0]) - float(series[0][0])
            skill_deltas[name] = delta
            
    most_improved_skill = max(skill_deltas, key=skill_deltas.get) if skill_deltas else "None"
    
    # Trend Data
    trend_reports = list(reversed(all_hist[:10]))
    trend_labels = [h.date.strftime("%b %d") for h in trend_reports]
    trend_data = [int(h.overall_score) for h in trend_reports]
    
    # Comparison (Section 13)
    chronological_hist = list(reversed(all_hist))
    selected_idx = -1
    for i, h in enumerate(chronological_hist):
        if h.interview_session_id == selected_id:
            selected_idx = i
            break
            
    comparison = None
    if selected_idx > 0:
        prev_hist = chronological_hist[selected_idx - 1]
        prev_an = InterviewAnalytics.query.filter_by(interview_session_id=prev_hist.interview_session_id).first()
        if prev_an:
            score_diff = int(an.overall_score) - int(prev_an.overall_score)
            prev_skills = SkillAnalytics.query.filter_by(interview_session_id=prev_hist.interview_session_id).all()
            prev_skills_map = {s.skill_name.lower(): s.average_score for s in prev_skills}
            
            skill_improvements = []
            for s in skills:
                prev_sc = prev_skills_map.get(s.skill_name.lower())
                if prev_sc is not None:
                    delta = float(s.average_score) - float(prev_sc)
                    if delta > 0:
                        skill_improvements.append(f"{s.skill_name} improved by {int(delta)}%")
            
            prev_rep = DBInterviewReport.query.filter_by(interview_session_id=prev_hist.interview_session_id).first()
            weakness_changes = []
            if prev_rep and prev_rep.weaknesses:
                curr_weaknesses_set = {w.lower() for w in rep.weaknesses} if rep and rep.weaknesses else set()
                resolved = []
                for pw in prev_rep.weaknesses:
                    if not any(cw in pw.lower() or pw.lower() in cw for cw in curr_weaknesses_set):
                        resolved.append(pw)
                if resolved:
                    weakness_changes.append(f"Resolved {len(resolved)} previous weakness(es)")
                else:
                    weakness_changes.append("No previous weaknesses were fully resolved.")
                    
            comparison = {
                "prev_name": prev_hist.interview_name,
                "prev_date": prev_hist.date.strftime("%b %d"),
                "score_diff": score_diff,
                "skill_improvements": skill_improvements,
                "weakness_changes": weakness_changes,
                "performance_trend": "Improved" if score_diff > 0 else "Declined" if score_diff < 0 else "Stable"
            }
            
    return render_template(
        "report.html",
        title="Interview Analytics Dashboard | InterviewForge",
        page_type="report",
        body_class="report-page",
        is_empty=False,
        histories=all_hist,
        selected_id=selected_id,
        interview_state=state,
        overview={
            "name": hist.interview_name,
            "type": hist.interview_type,
            "date": hist.date.strftime("%B %d, %Y"),
            "time": hist.date.strftime("%I:%M %p"),
            "duration": hist.duration_mins,
            "total_questions": hist.total_questions,
            "questions_answered": hist.questions_answered,
            "difficulty": hist.difficulty,
            "status": hist.status
        },
        report={
            "overall_score": int(an.overall_score) if an else 0,
            "duration_mins": hist.duration_mins if hist else 0,
            "question_count": hist.total_questions if hist else 0,
            "technical_score": int(an.technical_accuracy) if an else 0,
            "problem_solving_score": int(an.problem_solving) if an else 0,
            "communication_score": int(an.communication) if an else 0,
            "confidence_score": int(an.confidence_score) if an else 0,
            "project_explanation_score": int(an.project_understanding) if an else 0,
            "core_subjects_score": int(an.system_design) if an else 0,
            "transcript_summary": rep.summary if rep else "",
            "strengths": rep.strengths if rep else [],
            "weaknesses": rep.weaknesses if rep else [],
            "improvement_roadmap": rep.recommendations if rep else [],
            "data_points": {
                "placement_readiness": int(an.overall_score) if an else 0,
                "recruiter_verdict": an.interview_rating if an else "N/A",
                "relevance_score": int(an.relevance) if an else 0,
                "depth_score": int(an.depth) if an else 0,
                "repeated_answer_detected": any("repeated answer" in w.lower() for w in rep.weaknesses) if rep and rep.weaknesses else False,
            }
        },
        analytics={
            "overall_score": int(an.overall_score) if an else 0,
            "grade": an.performance_grade if an else "N/A",
            "rating": an.interview_rating if an else "N/A",
            "confidence_score": int(an.confidence_score) if an else 0,
            "completion_percentage": int(an.completion_percentage) if an else 0,
            "technical_accuracy": int(an.technical_accuracy) if an else 0,
            "relevance": int(an.relevance) if an else 0,
            "communication": int(an.communication) if an else 0,
            "depth": int(an.depth) if an else 0,
            "problem_solving": int(an.problem_solving) if an else 0,
            "system_design": int(an.system_design) if an else 0,
            "project_understanding": int(an.project_understanding) if an else 0
        },
        skills=[{
            "name": s.skill_name,
            "score": int(s.average_score),
            "level": s.performance_level,
            "priority": s.improvement_priority
        } for s in skills],
        questions=[{
            "id": q.id,
            "question": q.question_text,
            "answer": q.answer_text,
            "score": int(q.score),
            "evaluation": q.evaluation,
            "strengths": q.strengths,
            "weaknesses": q.weaknesses,
            "suggestions": q.suggestions,
            "time_spent": q.time_spent,
            "type": q.question_type,
            "difficulty": q.difficulty
        } for q in questions],
        historical_stats={
            "total_interviews": total_interviews,
            "avg_score": avg_score,
            "best_score": best_score,
            "worst_score": worst_score,
            "total_questions": total_questions,
            "avg_duration": avg_duration,
            "strongest_skill": strongest_skill,
            "weakest_skill": weakest_skill,
            "most_improved_skill": most_improved_skill
        },
        trend_labels=trend_labels,
        trend_data=trend_data,
        comparison=comparison,
        pdf_url=url_for("reports.download_report_pdf_by_id", session_id=selected_id),
        interview_url=url_for("interview_room")
    )


@reports_bp.route("/api/interviews/history")
@login_required
def api_interviews_history():
    completed_sessions = InterviewSession.query.filter_by(user_id=current_user.id, status="completed").all()
    for s in completed_sessions:
        h_check = InterviewHistory.query.filter_by(interview_session_id=s.id).first()
        if not h_check:
            ReportService().back_populate_session(s.id)
            
    history_records = InterviewHistory.query.filter_by(user_id=current_user.id).order_by(InterviewHistory.date.desc()).all()
    return jsonify({
        "ok": True,
        "history": [{
            "id": h.interview_session_id,
            "name": h.interview_name,
            "type": h.interview_type,
            "date": h.date.isoformat(),
            "score": float(h.overall_score),
            "duration": h.duration_mins,
            "questions": h.total_questions,
            "difficulty": h.difficulty,
            "status": h.status
        } for h in history_records]
    })


@reports_bp.route("/api/interviews/<int:session_id>")
@login_required
def api_interview_details(session_id):
    session = InterviewSession.query.filter_by(id=session_id, user_id=current_user.id).first()
    if not session:
        return jsonify({"ok": False, "error": "Interview not found"}), 404
        
    hist = InterviewHistory.query.filter_by(interview_session_id=session_id).first()
    if not hist:
        ReportService().back_populate_session(session_id)
        hist = InterviewHistory.query.filter_by(interview_session_id=session_id).first()
        
    rep = DBInterviewReport.query.filter_by(interview_session_id=session_id).first()
    an = InterviewAnalytics.query.filter_by(interview_session_id=session_id).first()
    skills = SkillAnalytics.query.filter_by(interview_session_id=session_id).all()
    questions = QuestionEvaluation.query.filter_by(interview_session_id=session_id).order_by(QuestionEvaluation.id.asc()).all()
    
    return jsonify({
        "ok": True,
        "overview": {
            "name": hist.interview_name,
            "type": hist.interview_type,
            "date": hist.date.isoformat(),
            "duration": hist.duration_mins,
            "total_questions": hist.total_questions,
            "questions_answered": hist.questions_answered,
            "difficulty": hist.difficulty,
            "status": hist.status
        },
        "report": {
            "summary": rep.summary if rep else "",
            "strengths": rep.strengths if rep else [],
            "weaknesses": rep.weaknesses if rep else [],
            "recommendations": rep.recommendations if rep else []
        },
        "analytics": {
            "overall_score": float(an.overall_score) if an else 0.0,
            "grade": an.performance_grade if an else "N/A",
            "rating": an.interview_rating if an else "N/A",
            "confidence_score": float(an.confidence_score) if an else 0.0,
            "completion_percentage": float(an.completion_percentage) if an else 0.0,
            "technical_accuracy": float(an.technical_accuracy) if an else 0.0,
            "relevance": float(an.relevance) if an else 0.0,
            "communication": float(an.communication) if an else 0.0,
            "depth": float(an.depth) if an else 0.0,
            "problem_solving": float(an.problem_solving) if an else 0.0,
            "system_design": float(an.system_design) if an else 0.0,
            "project_understanding": float(an.project_understanding) if an else 0.0
        },
        "skills": [{
            "name": s.skill_name,
            "score": float(s.average_score),
            "level": s.performance_level,
            "priority": s.improvement_priority
        } for s in skills],
        "questions": [{
            "id": q.id,
            "question": q.question_text,
            "answer": q.answer_text,
            "score": float(q.score),
            "evaluation": q.evaluation,
            "strengths": q.strengths,
            "weaknesses": q.weaknesses,
            "suggestions": q.suggestions,
            "time_spent": q.time_spent,
            "type": q.question_type,
            "difficulty": q.difficulty
        } for q in questions]
    })


@reports_bp.route("/api/interviews/<int:session_id>/report")
@login_required
def api_interview_report(session_id):
    session = InterviewSession.query.filter_by(id=session_id, user_id=current_user.id).first()
    if not session:
        return jsonify({"ok": False, "error": "Interview not found"}), 404
        
    rep = DBInterviewReport.query.filter_by(interview_session_id=session_id).first()
    if not rep:
        ReportService().back_populate_session(session_id)
        rep = DBInterviewReport.query.filter_by(interview_session_id=session_id).first()
        
    return jsonify({
        "ok": True,
        "summary": rep.summary if rep else "",
        "strengths": rep.strengths if rep else [],
        "weaknesses": rep.weaknesses if rep else [],
        "recommendations": rep.recommendations if rep else []
    })


@reports_bp.route("/api/interviews/<int:session_id>/analytics")
@login_required
def api_interview_analytics(session_id):
    session = InterviewSession.query.filter_by(id=session_id, user_id=current_user.id).first()
    if not session:
        return jsonify({"ok": False, "error": "Interview not found"}), 404
        
    an = InterviewAnalytics.query.filter_by(interview_session_id=session_id).first()
    if not an:
        ReportService().back_populate_session(session_id)
        an = InterviewAnalytics.query.filter_by(interview_session_id=session_id).first()
        
    questions = QuestionEvaluation.query.filter_by(interview_session_id=session_id).order_by(QuestionEvaluation.id.asc()).all()
    timeline = [{"question": f"Q{i+1}", "score": float(q.score)} for i, q in enumerate(questions)]
    
    return jsonify({
        "ok": True,
        "analytics": {
            "overall_score": float(an.overall_score) if an else 0.0,
            "grade": an.performance_grade if an else "N/A",
            "rating": an.interview_rating if an else "N/A",
            "confidence_score": float(an.confidence_score) if an else 0.0,
            "completion_percentage": float(an.completion_percentage) if an else 0.0,
            "technical_accuracy": float(an.technical_accuracy) if an else 0.0,
            "relevance": float(an.relevance) if an else 0.0,
            "communication": float(an.communication) if an else 0.0,
            "depth": float(an.depth) if an else 0.0,
            "problem_solving": float(an.problem_solving) if an else 0.0,
            "system_design": float(an.system_design) if an else 0.0,
            "project_understanding": float(an.project_understanding) if an else 0.0
        },
        "timeline": timeline
    })


@reports_bp.route("/api/interviews/<int:session_id>", methods=["DELETE"])
@login_required
def api_delete_interview(session_id):
    session = InterviewSession.query.filter_by(id=session_id, user_id=current_user.id).first()
    if not session:
        return jsonify({"ok": False, "error": "Interview session not found"}), 404
        
    db.session.delete(session)
    db.session.commit()
    return jsonify({"ok": True, "message": "Interview report and all associated data permanently deleted."})


@reports_bp.route("/api/interviews/<int:session_id>/download")
@login_required
def download_report_pdf_by_id(session_id):
    session = InterviewSession.query.filter_by(id=session_id, user_id=current_user.id).first()
    if not session:
        return "Interview not found", 404
        
    # Ensure premium history records are back-populated if missing
    h_check = InterviewHistory.query.filter_by(interview_session_id=session_id).first()
    if not h_check:
        ReportService().back_populate_session(session_id)
        
    state = ReportService().reconstruct_state_from_db(session)
    resume_profile = session.candidate_profile.parsed_resume_data if session.candidate_profile else {}
    job_description = session.job_description.parsed_jd_data if session.job_description else {}
    
    report_obj = ReportService().build_report(
        user_name=session.user.full_name,
        interview_state=state,
        resume_profile=resume_profile,
        job_description=job_description
    )
    
    # Query skills and questions to inject PDF data points
    skills = SkillAnalytics.query.filter_by(interview_session_id=session_id).all()
    questions = QuestionEvaluation.query.filter_by(interview_session_id=session_id).order_by(QuestionEvaluation.id).all()
    
    skills_list = [{
        "name": sk.skill_name,
        "score": int(sk.average_score),
        "level": sk.performance_level,
        "priority": sk.improvement_priority
    } for sk in skills]
    
    questions_list = [{
        "question": q.question_text,
        "answer": q.answer_text,
        "score": float(q.score),
        "evaluation": q.evaluation or ""
    } for q in questions]
    
    report_obj.data_points["skills_list"] = skills_list
    report_obj.data_points["questions_list"] = questions_list
    
    pdf_bytes = ReportService().build_pdf(report_obj)
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"InterviewForge-Report-{session_id}.pdf",
        max_age=0
    )