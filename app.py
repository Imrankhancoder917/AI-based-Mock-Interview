import os
from pathlib import Path
import json
from datetime import datetime, timezone



from flask import Flask, current_app, flash, jsonify, make_response, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename
from sqlalchemy.exc import SQLAlchemyError

from config import Config
from extensions import db, login_manager
from models import User, InterviewSession, CandidateProfile, JobDescription, Question, Answer, FeedbackReport
from parsers import canonical_known_skill, parse_uploaded_file, _SKILL_ALIASES
from services import AIService, InterviewQuestion, TTSService, WhisperService
from reports import reports_bp
from report_service import ReportService


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


def determine_active_phase(history_len: int, is_followup: bool = False) -> tuple[str, int]:
    from services.adaptive_engine import determine_phase_from_q_num
    if is_followup:
        phase_index = max(1, history_len)
    else:
        phase_index = history_len + 1
    phase = determine_phase_from_q_num(phase_index)
    return phase, phase_index


def _sync_interview_memory(interview_sess, state: dict, resume_profile: dict) -> dict:
    """Synchronize and rebuild category memory arrays from DB history and current state."""
    keys = [
        "question_history",
        "topic_history",
        "topic_group_history",
        "category_history",
        "covered_projects",
        "covered_skills",
        "covered_subjects",
        "covered_internships",
        "covered_experience",
        "covered_certificates"
    ]
    for k in keys:
        if k not in state:
            state[k] = []
            
    question_history = list(state["question_history"])
    topic_history = list(state["topic_history"])
    topic_group_history = list(state["topic_group_history"])
    category_history = list(state["category_history"])
    covered_projects = list(state["covered_projects"])
    covered_skills = list(state["covered_skills"])
    covered_subjects = list(state["covered_subjects"])
    covered_internships = list(state["covered_internships"])
    covered_experience = list(state["covered_experience"])
    covered_certificates = list(state["covered_certificates"])

    # Rebuild from normalized history list in state
    for h in state.get("history", []):
        cat = h.get("category")
        top = h.get("topic")
        if cat and cat not in category_history:
            category_history.append(cat)
        if top and top.lower() not in [t.lower() for t in topic_history]:
            topic_history.append(top)
        if top:
            from services.adaptive_engine import resolve_topic_group
            tg = resolve_topic_group(top)
            if tg not in topic_group_history:
                topic_group_history.append(tg)

    if interview_sess:
        # Recovery Logic: restore phase state if missing
        if not state.get("current_phase") and getattr(interview_sess, "current_phase", None):
            state["current_phase"] = interview_sess.current_phase
        if (state.get("phase_index") is None or state.get("phase_index") == 0) and getattr(interview_sess, "phase_index", None) is not None:
            state["phase_index"] = interview_sess.phase_index

        for q in interview_sess.questions:
            txt = q.question_text.strip()
            if txt not in question_history:
                question_history.append(txt)
            
            top_k = getattr(q, "topic_key", None)
            if top_k and top_k.lower() not in [t.lower() for t in topic_history]:
                topic_history.append(top_k)
            if top_k:
                from services.adaptive_engine import resolve_topic_group
                tg = resolve_topic_group(top_k)
                if tg not in topic_group_history:
                    topic_group_history.append(tg)
            
            kind = q.question_type
            signals = q.expected_signals or []
            
            for sig in signals:
                sig_clean = sig.strip()
                if not sig_clean:
                    continue
                
                from parsers import _is_date_like
                if _is_date_like(sig_clean):
                    continue
                
                if sig_clean.lower() not in [t.lower() for t in topic_history]:
                    topic_history.append(sig_clean)
                
                if kind in ("project_based", "project"):
                    if sig_clean not in covered_projects:
                        covered_projects.append(sig_clean)
                elif kind in ("internship_based", "internship"):
                    if sig_clean not in covered_internships:
                        covered_internships.append(sig_clean)
                elif kind in ("experience_based", "experience"):
                    if sig_clean not in covered_experience:
                        covered_experience.append(sig_clean)
                elif kind in ("resume_based", "jd_based", "skill"):
                    if sig_clean not in covered_skills:
                        covered_skills.append(sig_clean)
                elif kind in ("core_subject", "subject"):
                    if sig_clean not in covered_subjects:
                        covered_subjects.append(sig_clean)
                elif kind in ("certificate_based", "certificate"):
                    if sig_clean not in covered_certificates:
                        covered_certificates.append(sig_clean)
                        
    state["question_history"] = question_history
    state["topic_history"] = topic_history
    state["topic_group_history"] = topic_group_history
    state["category_history"] = category_history
    state["covered_projects"] = covered_projects
    state["covered_skills"] = covered_skills
    state["covered_subjects"] = covered_subjects
    state["covered_internships"] = covered_internships
    state["covered_experience"] = covered_experience
    state["covered_certificates"] = covered_certificates
    return state



def _build_resume_profile() -> dict:
    if current_user and current_user.is_authenticated:
        profile = CandidateProfile.query.filter_by(user_id=current_user.id, is_active=True).first()
        if profile and profile.parsed_resume_data:
            return profile.parsed_resume_data
    state = _get_interview_state()
    res = state.get("resume_profile") or session.get("resume_profile")
    if res:
        return res
    return {}


def _build_job_profile() -> dict:
    if current_user and current_user.is_authenticated:
        jd_model = JobDescription.query.filter_by(user_id=current_user.id, is_active=True).first()
        if jd_model and jd_model.parsed_jd_data:
            return jd_model.parsed_jd_data
    state = _get_interview_state()
    jd = state.get("job_description") or session.get("job_description")
    if jd:
        return jd
    return {}


def _build_history() -> list[dict]:
    return _get_interview_state().get("history", [])


def _normalize_session_history(raw_history: Iterable[dict] | None) -> list[dict]:
    """Normalize legacy or incoming history payloads into structured history entries.

    Each entry: {question, answer, score, weaknesses, topic, ...subscores}
    """
    if not raw_history:
        return []
    normalized = []
    for item in raw_history:
        try:
            q = str(item.get("question", "")).strip()
            a = str(item.get("answer", "")).strip()
            s = int(item.get("score", 0)) if item.get("score") is not None else 0
            # accept gaps/gaps/gaps-like keys
            weaknesses = item.get("gaps") or item.get("weaknesses") or item.get("weakness") or item.get("gaps", [])
            if isinstance(weaknesses, str):
                weaknesses = [weaknesses]
            weaknesses = [str(w) for w in (weaknesses or [])]
            topic = str(item.get("topic") or item.get("follow_up_seed") or (item.get("expected_signals") or [""])[0] or "").strip()
            normalized.append({
                "question": q,
                "answer": a,
                "score": s,
                "weaknesses": weaknesses,
                "topic": topic,
                "category": str(item.get("category", "")).strip(),
                "technical_accuracy": int(item.get("technical_accuracy", 5)),
                "relevance": int(item.get("relevance", 5)),
                "depth": int(item.get("depth", 5)),
                "communication": int(item.get("communication", 5)),
                "repeated_answer_detected": bool(item.get("repeated_answer_detected", False)),
            })
        except Exception:
            continue
    return normalized



def _is_meaningful_history(entry: dict) -> bool:
    a = entry.get("answer", "") or ""
    s = int(entry.get("score", 0) or 0)
    weaknesses = entry.get("weaknesses") or []
    if not a:
        return False
    if len(a.split()) >= 20 or s >= 5 or weaknesses:
        return True
    return False


def _append_history(history: list[dict], entry: dict, max_items: int = 6) -> list[dict]:
    history = list(history or [])
    history.append(entry)
    # keep only meaningful items, preserve order, keep most recent
    meaningful = [h for h in history if _is_meaningful_history(h)]
    if not meaningful:
        return []
    return meaningful[-max_items:]


def _ensure_profile_and_jd(user_id) -> tuple[CandidateProfile | None, JobDescription | None]:
    profile = CandidateProfile.query.filter_by(user_id=user_id, is_active=True).first()
    jd = JobDescription.query.filter_by(user_id=user_id, is_active=True).first()
    return profile, jd


def _calculate_streak(user_id) -> int:
    sessions = InterviewSession.query.filter_by(user_id=user_id).all()
    if not sessions:
        return 0
        
    import datetime
    dates = {s.created_at.date() for s in sessions if s.created_at}
    if not dates:
        return 0
        
    sorted_dates = sorted(list(dates), reverse=True)
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    
    if sorted_dates[0] not in (today, yesterday):
        return 0
        
    streak = 0
    current_date = sorted_dates[0]
    
    for date in sorted_dates:
        if date == current_date:
            streak += 1
            current_date -= datetime.timedelta(days=1)
        elif date < current_date:
            break
            
    return streak


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
        "category": question.category,
        "topic": question.topic,
    }


def _flatten_skill_names(raw_skills) -> list[str]:
    if not raw_skills:
        return []

    flattened = []

    def add_skill(value) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for nested_value in value.values():
                add_skill(nested_value)
            return
        if isinstance(value, (list, tuple, set)):
            for nested_value in value:
                add_skill(nested_value)
            return

        skill = str(value).strip()
        if skill and skill not in flattened:
            flattened.append(skill)

    add_skill(raw_skills)
    return flattened


def _compute_skill_match(resume_profile: dict | None, jd_data: dict | None) -> dict:
    """
    Compare resume skills against JD required skills.
    Returns a dict with matched, missing, match_pct, resume_total, jd_total.
    All comparisons are case-insensitive. Junk tokens are excluded.
    """
    def _validated_skill_names(raw_values) -> list[str]:
        validated: list[str] = []
        seen: set[str] = set()
        for value in _flatten_skill_names(raw_values):
            canonical = canonical_known_skill(value)
            if not canonical:
                continue
            key = canonical.lower()
            if key in seen:
                continue
            seen.add(key)
            validated.append(canonical)
        return validated

    # Flatten resume skills from categorised dict or flat list
    resume_clean = _validated_skill_names(
        resume_profile.get("skills") if resume_profile else None
    )

    # JD required skills
    jd_flat: list[str] = []
    if jd_data:
        jd_summary = jd_data.get("summary", jd_data)
        raw_jd_skills = jd_summary.get("required_skills") or jd_summary.get("skills") or []
        jd_flat = _validated_skill_names(raw_jd_skills)

    if not jd_flat:
        return {
            "matched": [],
            "missing": [],
            "match_pct": 0,
            "resume_total": len(resume_clean),
            "jd_total": 0,
            "has_resume": bool(resume_clean),
            "has_jd": False,
        }

    # Case-insensitive alias-aware matching
    resume_lower = {_SKILL_ALIASES.get(s.lower(), s.lower()) for s in resume_clean}

    matched: list[str] = []
    missing: list[str] = []
    seen_lower: set[str] = set()

    for skill in jd_flat:
        raw_key = skill.lower()
        if raw_key in seen_lower:
            continue
        seen_lower.add(raw_key)
        
        alias_key = _SKILL_ALIASES.get(raw_key, raw_key)
        if alias_key in resume_lower:
            matched.append(skill)
        else:
            missing.append(skill)

    jd_total = len(matched) + len(missing)
    match_pct = round((len(matched) / jd_total) * 100) if jd_total > 0 else 0

    return {
        "matched": matched,
        "missing": missing,
        "match_pct": match_pct,
        "resume_total": len(resume_clean),
        "jd_total": jd_total,
        "has_resume": True,
        "has_jd": True,
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
        category=str(payload.get("category", "")),
        topic=str(payload.get("topic", "")),
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
        try:
            user_count = User.query.count()
            interview_count = InterviewSession.query.count()
            reports_count = FeedbackReport.query.count()
            resumes_count = CandidateProfile.query.count()
        except SQLAlchemyError:
            user_count = 0
            interview_count = 0
            reports_count = 0
            resumes_count = 0
        return render_template("landing.html", title="InterviewForge", user_count=user_count, interview_count=interview_count, reports_count=reports_count, resumes_count=resumes_count, body_class="landing-page")

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

    @app.route("/api/profile/upload-image", methods=["POST"])
    @login_required
    def upload_profile_image():
        if "image" not in request.files:
            return jsonify({"ok": False, "error": "No image uploaded"}), 400
            
        file = request.files["image"]
        if file.filename == "":
            return jsonify({"ok": False, "error": "No selected file"}), 400
            
        if not (file and file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))):
            return jsonify({"ok": False, "error": "Invalid file type. Only JPG, PNG, WEBP allowed."}), 400
            
        import uuid
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        
        profile_dir = Path(current_app.root_path) / "static" / "profiles"
        os.makedirs(profile_dir, exist_ok=True)
        
        file_path = profile_dir / unique_filename
        file.save(file_path)
        
        current_user.profile_image = unique_filename
        db.session.commit()
        
        return jsonify({
            "ok": True, 
            "url": url_for('static', filename=f'profiles/{unique_filename}')
        })

    @app.route("/api/profile/update-details", methods=["POST"])
    @login_required
    def update_profile_details():
        data = request.json or {}
        full_name = data.get("full_name", "").strip()
        
        if not full_name:
            return jsonify({"ok": False, "error": "Full name cannot be empty"}), 400
            
        current_user.full_name = full_name
        db.session.commit()
        
        return jsonify({
            "ok": True,
            "full_name": full_name
        })

    @app.route("/api/profile/remove-image", methods=["POST"])
    @login_required
    def remove_profile_image():
        if current_user.profile_image:
            try:
                profile_dir = Path(current_app.root_path) / "static" / "profiles"
                file_path = profile_dir / current_user.profile_image
                if file_path.exists():
                    os.remove(file_path)
            except Exception as e:
                current_app.logger.error(f"Error deleting profile image: {e}")
                
            current_user.profile_image = None
            db.session.commit()
            
        return jsonify({"ok": True})

    @app.route("/dashboard")
    @login_required
    def dashboard() -> str:
        # Load completed interviews from DB
        completed_interviews = InterviewSession.query.filter_by(user_id=current_user.id, status="completed").all()
        interview_count = len(completed_interviews)
        
        # Calculate dynamic streak
        streak = _calculate_streak(current_user.id)
        
        # Calculate average score of completed interviews
        avg_score = 0
        best_score = 0
        scores = []
        for sess in completed_interviews:
            if sess.feedback_report:
                score_val = int(sess.feedback_report.overall_score)
                scores.append(score_val)
                if score_val > best_score:
                    best_score = score_val
        
        if scores:
            avg_score = int(sum(scores) / len(scores))
            
        # Strengths & Weaknesses Count from the latest completed report
        latest_report = FeedbackReport.query.join(InterviewSession).filter(InterviewSession.user_id == current_user.id).order_by(FeedbackReport.generated_at.desc()).first()
        strengths_count = len(latest_report.strengths) if latest_report else 0
        weaknesses_count = len(latest_report.weaknesses) if latest_report else 0

        # Construct Recent Activity chronologically
        activities = []
        
        # Candidate Profiles
        profiles = CandidateProfile.query.filter_by(user_id=current_user.id).all()
        for p in profiles:
            activities.append({
                "type": "resume",
                "title": "Uploaded Resume",
                "detail": f"AI parsed resume: {p.profile_name}",
                "score": None,
                "timestamp": p.created_at,
                "time_str": p.created_at.strftime("%b %d, %H:%M"),
                "icon": "bi bi-file-earmark-text",
                "icon_class": "icon-success"
            })
            
        # Job Descriptions
        jds = JobDescription.query.filter_by(user_id=current_user.id).all()
        for jd in jds:
            activities.append({
                "type": "jd",
                "title": "Uploaded Job Description",
                "detail": f"For position: {jd.title}",
                "score": None,
                "timestamp": jd.created_at,
                "time_str": jd.created_at.strftime("%b %d, %H:%M"),
                "icon": "bi bi-file-earmark-text",
                "icon_class": "icon-orange"
            })
            
        # Interview Sessions
        sessions = InterviewSession.query.filter_by(user_id=current_user.id).all()
        for s in sessions:
            role = s.job_description.title if s.job_description else "Mock Interview"
            score = None
            if s.feedback_report:
                score = f"{int(s.feedback_report.overall_score)}%"
            elif s.answers:
                ans_scores = [float(a.score) for a in s.answers if a.score is not None]
                if ans_scores:
                    score = f"{int(sum(ans_scores)/len(ans_scores)*10)}%"
                    
            activities.append({
                "type": "interview",
                "title": "Completed Mock Interview" if s.status == "completed" else "Practice Interview Session",
                "detail": role,
                "score": score,
                "timestamp": s.completed_at or s.last_activity_at or s.created_at,
                "time_str": (s.completed_at or s.last_activity_at or s.created_at).strftime("%b %d, %H:%M"),
                "icon": "bi bi-calendar-check",
                "icon_class": "icon-primary" if s.status == "completed" else "icon-purple"
            })
            
        # Sort activities descending by timestamp
        activities.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Calculate Total Practice Time
        total_seconds = 0
        for s in completed_interviews:
            if s.completed_at and s.started_at:
                total_seconds += (s.completed_at - s.started_at).total_seconds()
        if total_seconds == 0:
            all_answers = Answer.query.join(InterviewSession).filter(InterviewSession.user_id == current_user.id).all()
            total_seconds = len(all_answers) * 120 # Estimate 2 minutes per question
            
        total_hours = int(total_seconds // 3600)
        total_mins = int((total_seconds % 3600) // 60)
        practice_time_str = f"{total_hours}h {total_mins}m" if total_seconds > 0 else "0m"
        
        # Retrieve parsed resume skills from latest CandidateProfile
        latest_profile = CandidateProfile.query.filter_by(user_id=current_user.id).order_by(CandidateProfile.created_at.desc()).first()
        skills = []
        if latest_profile and latest_profile.parsed_resume_data:
            skills = latest_profile.parsed_resume_data.get("skills") or latest_profile.parsed_resume_data.get("technologies") or []
            
        skills_data = _flatten_skill_names(skills)[:8]
        
        # AI Coach Recommendations
        coach_recommendations = None
        if latest_report:
            roadmap = latest_report.improvement_roadmap
            weaknesses = latest_report.weaknesses
            coach_recommendations = {
                "recommended": roadmap[0] if len(roadmap) > 0 else "Practice adaptive system design",
                "focus_area": weaknesses[0] if len(weaknesses) > 0 else "Deepen engineering tradeoffs",
                "next_goal": f"Score {min(100, int(latest_report.overall_score + 8))}%+"
            }
            
        # Upcoming Interview: Check if there's any scheduled (none in database, so set to None)
        upcoming_interview = None
        
        # Construct Dynamic Notifications
        notifications = []
        
        if latest_profile:
            notifications.append({
                "id": f"notif-resume-{latest_profile.id}",
                "title": "Resume Analyzed",
                "desc": f"AI parsed your resume: {latest_profile.profile_name}",
                "time": latest_profile.created_at.strftime("%b %d"),
                "icon": "bi bi-file-earmark-text",
                "unread": False
            })
            
        for s in completed_interviews[:3]:
            role = s.job_description.title if s.job_description else "Mock Interview"
            notifications.append({
                "id": f"notif-session-{s.id}",
                "title": "Interview Completed",
                "desc": f"Mock interview session for {role} finished.",
                "time": s.completed_at.strftime("%b %d"),
                "icon": "bi bi-calendar-check",
                "unread": False
            })
            if s.feedback_report:
                notifications.append({
                    "id": f"notif-report-{s.feedback_report.id}",
                    "title": "Report Generated",
                    "desc": f"Detailed skill and gap breakdown report ready for {role}.",
                    "time": s.feedback_report.generated_at.strftime("%b %d"),
                    "icon": "bi bi-chat-left-dots",
                    "unread": False
                })
                
        # Construct Chart Data Points (Last 7 completed interviews)
        chart_labels = []
        chart_data = []
        for idx, sess in enumerate(completed_interviews[-7:]):
            chart_labels.append(f"Session {idx+1}")
            if sess.feedback_report:
                chart_data.append(int(sess.feedback_report.overall_score))
            else:
                ans_scores = [float(a.score) for a in sess.answers if a.score is not None]
                if ans_scores:
                    chart_data.append(int(sum(ans_scores) / len(ans_scores) * 10))
                else:
                    chart_data.append(0)
                    
        # Next Role preference
        next_role = None
        latest_jd = JobDescription.query.filter_by(user_id=current_user.id).order_by(JobDescription.created_at.desc()).first()
        if latest_profile or latest_jd:
            next_role = (latest_profile.target_role if latest_profile else None) or (latest_jd.title if latest_jd else None) or "Selected Role"

        # Resume ↔ JD Skill Match (active docs only)
        active_profile = CandidateProfile.query.filter_by(user_id=current_user.id, is_active=True).first()
        active_jd_doc = JobDescription.query.filter_by(user_id=current_user.id, is_active=True).first()
        skill_match = _compute_skill_match(
            active_profile.parsed_resume_data if active_profile else None,
            active_jd_doc.parsed_jd_data if active_jd_doc else None,
        )
            
        return render_template(
            "dashboard.html",
            title="Dashboard | InterviewForge",
            page_type="dashboard",
            body_class="dashboard-page",
            user_name=current_user.full_name,
            streak=streak,
            interview_count=interview_count,
            avg_score=avg_score,
            best_score=best_score,
            practice_time_str=practice_time_str,
            strengths_count=strengths_count,
            weaknesses_count=weaknesses_count,
            activities=activities[:4], # Show top 4 activities
            skills_data=skills_data,
            coach_recommendations=coach_recommendations,
            upcoming_interview=upcoming_interview,
            latest_report=latest_report,
            next_role=next_role,
            chart_labels=chart_labels,
            chart_data=chart_data,
            notifications=notifications,
            skill_match=skill_match,
        )

    @app.route("/api/chat-assistant", methods=["POST"])
    @login_required
    def chat_assistant():
        import requests
        data = request.get_json() or {}
        message = data.get("message", "").strip()
        if not message:
            return jsonify({"ok": False, "error": "Message is empty."}), 400

        msg_lower = message.lower()
        
        predefined_responses = {
            "start": "To start a mock interview, navigate to the **Dashboard** and click **Start Mock Interview** under the 'Quick Actions' list, or click **Mock Interview** in the sidebar. This will open the adaptive Interview Room where you can practice in real-time.",
            "mock": "Mock interviews in InterviewForge are powered by advanced AI. When you start a session, the system generates custom, conversational technical questions based on your parsed resume and the target job description. The difficulty adapts dynamically based on how well you answer each question.",
            "score": "Your interview scores are calculated by analyzing your response quality, technical accuracy, structural clarity, and communication style. Each answer is scored, and at the end of the session, they are aggregated into Overall, Technical, and Communication scores.",
            "download": "To download your report, click **Download Report** from the sidebar or select **Download Report** under 'Quick Actions'. If you have completed at least one mock interview, you can view the complete interactive performance breakdown and click the **Download PDF** button at the top to export a high-quality PDF copy.",
            "report": "To view your feedback reports, click **Download Report** in the sidebar. If you have finished an interview session, it will show you overall grades, key strengths, improvement areas, a resume honesty check, and a session transcript summary.",
            "resume": "Resume analysis works by uploading your resume (PDF, DOCX, or images) via the **Upload Resume** page. The system parses your skills, projects, and experience, which are then used to tailor the mock interview questions directly to your background.",
            "upload": "To upload your resume, click **Upload Resume** in the sidebar. Select your document type (Resume or Job Description), drag and drop your file, and click **Upload and parse**. The extracted profile will automatically power your next interview session.",
            "improve": "You can improve your performance by reading the personalized feedback in your **Feedback Report**. Focus on the 'Improvement Roadmap' and targeted focus areas (like System Design or Data Structures) shown in the 'AI Interview Coach' section of your Dashboard.",
            "analytics": "You can view your detailed analytics and metrics directly on the **Dashboard**. The dashboard shows your overall stats, a visual Line Chart of your performance over time, and a Circular Progress breakdown of your top skills.",
            "settings": "You can access settings by clicking **Settings** in the main navigation. There you can adjust your profile details, target role preferences, and mock interview difficulty.",
            "help": "I can help you prepare for your interviews! Ask me questions like:\n• 'How do mock interviews work?'\n• 'How is my score calculated?'\n• 'Where can I download my report?'\n• 'How do I upload a resume?'",
        }

        # Check if we can find a keyword match
        matched_reply = None
        for key, reply in predefined_responses.items():
            if key in msg_lower:
                matched_reply = reply
                break

        # If no specific keyword is found, fallback to a general guide
        if not matched_reply:
            matched_reply = (
                "InterviewForge is an AI-powered mock interview platform that helps you land your dream job. "
                "You can upload your resume, take adaptive mock interviews (text/voice), receive detailed feedback "
                "reports, and track your progress over time.\n\n"
                "Ask me about:\n"
                "• **Mock Interviews** (how they work and how to start)\n"
                "• **Resume Analysis** (how to upload and parse)\n"
                "• **AI Evaluation & Scores**\n"
                "• **Downloading Reports**\n"
                "• **Dashboard Metrics & Analytics**"
            )

        # Groq-powered response (if key is set)
        api_key = os.environ.get("GROQ_API_KEY", "")
        model = os.environ.get("SECONDARY_LLM_MODEL", "grok-3-mini")

        if api_key:
            try:
                system_prompt = (
                    "You are the InterviewForge AI Assistant, a helpful and knowledgeable guide for candidates preparing for technical interviews on InterviewForge.\n"
                    "Your goal is to answer user questions about the platform's features, interviews, reports, resume upload, and analytics.\n"
                    "Here is what you know about the platform:\n"
                    "1. Mock Interviews: AI-powered adaptive technical interviews. Tailored to the candidate's resume and job description. Voice (Whisper + TTS) and text support.\n"
                    "2. Resume Upload & Parsing: Supports PDF, DOCX, JPG, PNG. Extracts skills, experience, and projects to customize interview sessions.\n"
                    "3. AI Evaluation: Scores each response based on accuracy, depth, and clarity, providing an overall average score (e.g. 78%).\n"
                    "4. Feedback Reports: Comprehensive breakdown showing Overall/Technical/Communication scores, Strengths, Weaknesses, an Improvement Roadmap, Resume Honesty Check, and an exportable PDF version.\n"
                    "5. Dashboard: Premium central hub containing streak tracking, recent session records, progress charts, and recommended focus areas from the AI Coach.\n\n"
                    "Keep your responses friendly, professional, structured, and direct. Use markdown for headings, bullets, and bold text. Keep it brief (under 150 words)."
                )

                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": message}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 300,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                payload = resp.json()
                if "choices" in payload and payload["choices"]:
                    content = payload["choices"][0]["message"].get("content", "").strip()
                    if content:
                        return jsonify({"ok": True, "reply": content})
            except Exception as e:
                current_app.logger.warning(f"Groq Chat Assistant failed: {e}")

        # Return the robust predefined/rule-based fallback response
        return jsonify({"ok": True, "reply": matched_reply})

    @app.route("/interview-room")
    @login_required
    def interview_room() -> str:
        interview_service = _get_interview_service()
        resume_profile = _build_resume_profile()
        print(json.dumps(resume_profile, indent=2))
        job_description = _build_job_profile()
        state = _get_interview_state()
        initial_question = state.get("current_question")
        
        profile, jd_model = _ensure_profile_and_jd(current_user.id)

        # Reset draft session if active resume or active JD in database does not match the draft session's associated documents
        draft_sess = InterviewSession.query.filter_by(user_id=current_user.id, status="draft").first()
        if draft_sess:
            if (profile and draft_sess.candidate_profile_id != profile.id) or (jd_model and draft_sess.job_description_id != jd_model.id):
                db.session.delete(draft_sess)
                db.session.commit()
                # Clear state
                session.pop("session_token", None)
                _set_interview_state({})
                initial_question = None

        if initial_question is None:
            if not profile or not jd_model:
                flash("Please upload a Resume and Job Description to begin your practice interview.", "warning")
                return redirect(url_for('upload'))

        return render_template(
            "interview_room.html",
            title="Interview Room | InterviewForge",
            page_type="interview",
            body_class="interview-page",
            user_name=current_user.full_name,
            has_resume=bool(resume_profile),
            has_jd=bool(job_description),
            role_family=interview_service.create_context(resume_profile, job_description).role_family if (resume_profile and job_description) else "Full Stack Developer",
            initial_question=initial_question,
            interview_state=state,
            active_resume=profile,
            active_jd=jd_model,
        )

    @app.route("/api/interview/generate-question", methods=["POST"])
    @login_required
    def api_generate_question():
        payload = request.get_json(silent=True) or {}
        resume_profile = payload.get("resume_profile") or _build_resume_profile()
        print(json.dumps(resume_profile, indent=2))
        job_description = payload.get("job_description") or _build_job_profile()
        raw_history = payload.get("session_history") or _build_history()
        history = _normalize_session_history(raw_history)
        difficulty = int(payload.get("difficulty") or _get_interview_state().get("difficulty", _default_difficulty()))

        state = _get_interview_state()

        # Sync with database if active session exists
        session_token = state.get("session_token") or session.get("session_token")
        interview_sess = None
        if session_token:
            interview_sess = InterviewSession.query.filter_by(session_token=session_token).first()

        # Re-sync memory tracking
        state = _sync_interview_memory(interview_sess, state, resume_profile)

        # Calculate phase and index, and save to cache & DB
        current_phase, phase_index = determine_active_phase(len(history), is_followup=False)
        state["current_phase"] = current_phase
        state["phase_index"] = phase_index
        state["coding_mode_enabled"] = current_app.config.get("CODING_MODE_ENABLED", False)

        if interview_sess:
            interview_sess.current_phase = current_phase
            interview_sess.phase_index = phase_index
            db.session.commit()

        service = _get_interview_service()
        question = service.generate_question(
            resume_profile,
            job_description,
            difficulty,
            history,
            question_history=state["question_history"],
            state_memory=state
        )
        serialized_question = _serialize_question(question)

        if question and question.prompt:
            q_prompt = question.prompt.strip()
            if q_prompt not in state["question_history"]:
                state["question_history"].append(q_prompt)
            
            # Sync generated question topics & category items
            topic = question.topic or question.follow_up_seed or (question.expected_signals[0] if question.expected_signals else "")
            if topic and topic.lower() not in [t.lower() for t in state["topic_history"]]:
                state["topic_history"].append(topic)
                
            category = question.category
            if category and category not in state.setdefault("category_history", []):
                state["category_history"].append(category)
                
            kind = question.kind
            for sig in question.expected_signals:
                sig_clean = sig.strip()
                if not sig_clean:
                    continue
                from parsers import _is_date_like
                if _is_date_like(sig_clean):
                    continue
                if kind in ("project_based", "project"):
                    if sig_clean not in state["covered_projects"]:
                        state["covered_projects"].append(sig_clean)
                elif kind in ("internship_based", "internship"):
                    if sig_clean not in state["covered_internships"]:
                        state["covered_internships"].append(sig_clean)
                elif kind in ("experience_based", "experience"):
                    if sig_clean not in state["covered_experience"]:
                        state["covered_experience"].append(sig_clean)
                elif kind in ("resume_based", "jd_based", "skill"):
                    if sig_clean not in state["covered_skills"]:
                        state["covered_skills"].append(sig_clean)
                elif kind in ("core_subject", "subject"):
                    if sig_clean not in state["covered_subjects"]:
                        state["covered_subjects"].append(sig_clean)
                elif kind in ("certificate_based", "certificate"):
                    if sig_clean not in state["covered_certificates"]:
                        state["covered_certificates"].append(sig_clean)

        profile, jd_model = _ensure_profile_and_jd(current_user.id)
        if not profile or not jd_model:
            return jsonify({"ok": False, "error": "Please upload and set active both a resume and a job description before starting the interview."}), 400
            
        if not interview_sess:
            import secrets
            session_token = secrets.token_hex(16)
            session["session_token"] = session_token
            
            interview_sess = InterviewSession(
                user_id=current_user.id,
                candidate_profile_id=profile.id,
                job_description_id=jd_model.id,
                status="draft",
                session_token=session_token,
                started_at=datetime.now(timezone.utc),
                last_activity_at=datetime.now(timezone.utc),
                current_phase=current_phase,
                phase_index=phase_index
            )
            db.session.add(interview_sess)
            db.session.commit()

        state.update({
            "resume_profile": resume_profile,
            "job_description": job_description,
            "difficulty": question.difficulty,
            "current_question": serialized_question,
            "session_token": session_token,
            "current_phase": current_phase,
            "phase_index": phase_index,
            "coding_mode_enabled": state["coding_mode_enabled"]
        })
        _set_interview_state(state)

        return jsonify({
            "ok": True,
            "question": serialized_question,
            "difficulty": question.difficulty,
            "role_family": service.create_context(resume_profile, job_description, difficulty, history).role_family if (resume_profile and job_description) else "Full Stack Developer",
            "progress": len(history),
        })

    @app.route("/api/interview/process-answer", methods=["POST"])
    @login_required
    def api_process_answer():
        try:
            print("=" * 80)
            print("PROCESS ANSWER STARTED")
            print("=" * 80)

            # Step 4: Validate Session State
            if "interview_state" not in session:
                session["interview_state"] = {}

            # Step 5: Validate Question History
            interview_state = session["interview_state"]
            question_history = interview_state.get("question_history", [])

            payload = request.get_json(silent=True) or {}
            answer = str(payload.get("answer", "")).strip()
            resume_profile = payload.get("resume_profile") or _build_resume_profile()
            job_description = payload.get("job_description") or _build_job_profile()
            raw_history = list(payload.get("session_history") or _build_history())
            history = _normalize_session_history(raw_history)
            difficulty = int(payload.get("difficulty") or _get_interview_state().get("difficulty", _default_difficulty()))
            current_question_data = payload.get("current_question") or _get_interview_state().get("current_question")
            service = _get_interview_service()

            state = _get_interview_state()

            # Sync with database if active session exists
            session_token = state.get("session_token") or session.get("session_token")
            interview_sess = None
            if session_token:
                interview_sess = InterviewSession.query.filter_by(session_token=session_token).first()

            # Re-sync memory tracking
            state = _sync_interview_memory(interview_sess, state, resume_profile)

            if current_question_data:
                current_question = _question_from_payload(current_question_data, difficulty)
            else:
                current_question = service.generate_question(
                    resume_profile,
                    job_description,
                    difficulty,
                    history,
                    question_history=state["question_history"],
                    state_memory=state
                )
                current_question_data = _serialize_question(current_question)

            if current_question.prompt.strip() not in state["question_history"]:
                state["question_history"].append(current_question.prompt.strip())

            # Step 6: Validate Current Question
            if not current_question_data:
                print("WARNING: current_question_data missing")

            if not current_question:
                print("WARNING: current_question missing")

            # Step 3: Print Critical Objects
            print("CURRENT QUESTION DATA:")
            print(current_question_data)

            print("CURRENT QUESTION:")
            print(current_question)

            print("INTERVIEW STATE:")
            print(interview_state)

            print("QUESTION HISTORY:")
            print(question_history)

            print("SESSION DATA:")
            print(session)

            evaluation = service.evaluate_answer(current_question, answer, difficulty=difficulty, session_history=history)

            # Step 7: Validate Resume Profile
            print("RESUME PROFILE:")
            print(json.dumps(
                resume_profile,
                indent=2,
                default=str
            ))

            next_difficulty = service.engine.adapt_difficulty(current_question.difficulty, evaluation.score, history)

            # Build structured history entry and keep only recent meaningful items
            topic = current_question.topic or current_question.follow_up_seed or (current_question.expected_signals[0] if current_question.expected_signals else "")
            weaknesses = evaluation.gaps if getattr(evaluation, "gaps", None) else []
            entry = {
                "question": current_question.prompt,
                "answer": answer,
                "score": evaluation.score,
                "weaknesses": weaknesses,
                "topic": topic,
                "category": current_question.category,
                "technical_accuracy": getattr(evaluation, "technical_accuracy", 5.0),
                "relevance": getattr(evaluation, "relevance", 5.0),
                "depth": getattr(evaluation, "depth", 5.0),
                "communication": getattr(evaluation, "communication", 5.0),
                "repeated_answer_detected": getattr(evaluation, "repeated_answer_detected", False),
            }
            history = _append_history(history, entry)

            # Provide recent history summary to follow-up generator via follow_up_seed
            try:
                summary_items = [f"{h.get('topic','') or h.get('question','')[:30]}({h.get('score',0)})" for h in history[-4:]]
                history_summary = "; ".join([s for s in summary_items if s])
                if history_summary:
                    current_question.follow_up_seed = (str(current_question.follow_up_seed or "") + " | H: " + history_summary)[:200]
            except Exception:
                pass

            # Step 8: Validate AI Service
            print("GENERATING FOLLOW-UP")
            
            # Calculate phase and index, and save to cache & DB
            current_phase, phase_index = determine_active_phase(len(history), is_followup=True)
            state["current_phase"] = current_phase
            state["phase_index"] = phase_index
            state["coding_mode_enabled"] = current_app.config.get("CODING_MODE_ENABLED", False)

            if interview_sess:
                interview_sess.current_phase = current_phase
                interview_sess.phase_index = phase_index
                db.session.commit()

            next_question = service.generate_followup_question(
                current_question,
                answer,
                evaluation.score,
                resume_profile=resume_profile,
                job_description=job_description,
                session_history=history,
                question_history=state["question_history"],
                state_memory=state
            )
            followup_question = next_question
            print("FOLLOW-UP GENERATED:")
            print(followup_question)
            
            if next_question and next_question.prompt:
                next_prompt = next_question.prompt.strip()
                if next_prompt not in state["question_history"]:
                    state["question_history"].append(next_prompt)

                # Sync next_question topic and signals to state categories
                next_topic = next_question.topic or next_question.follow_up_seed or (next_question.expected_signals[0] if next_question.expected_signals else "")
                if next_topic and next_topic.lower() not in [t.lower() for t in state["topic_history"]]:
                    state["topic_history"].append(next_topic)
                    
                next_category = next_question.category
                if next_category and next_category not in state.setdefault("category_history", []):
                    state["category_history"].append(next_category)
                
                next_kind = next_question.kind
                for sig in next_question.expected_signals:
                    sig_clean = sig.strip()
                    if not sig_clean:
                        continue
                    from parsers import _is_date_like
                    if _is_date_like(sig_clean):
                        continue
                    if next_kind in ("project_based", "project"):
                        if sig_clean not in state["covered_projects"]:
                            state["covered_projects"].append(sig_clean)
                    elif next_kind in ("internship_based", "internship"):
                        if sig_clean not in state["covered_internships"]:
                            state["covered_internships"].append(sig_clean)
                    elif next_kind in ("experience_based", "experience"):
                        if sig_clean not in state["covered_experience"]:
                            state["covered_experience"].append(sig_clean)
                    elif next_kind in ("resume_based", "jd_based", "skill"):
                        if sig_clean not in state["covered_skills"]:
                            state["covered_skills"].append(sig_clean)
                    elif next_kind in ("core_subject", "subject"):
                        if sig_clean not in state["covered_subjects"]:
                            state["covered_subjects"].append(sig_clean)
                    elif next_kind in ("certificate_based", "certificate"):
                        if sig_clean not in state["covered_certificates"]:
                            state["covered_certificates"].append(sig_clean)

            feedback = service.evaluator.generate_feedback(evaluation, current_question.prompt)

            profile, jd_model = _ensure_profile_and_jd(current_user.id)
            if not profile or not jd_model:
                return jsonify({"ok": False, "error": "Please upload and set active both a resume and a job description before starting the interview."}), 400
                
            # Step 9: Validate Database Writes
            print("SAVING ANSWER")
            if not interview_sess:
                import secrets
                session_token = secrets.token_hex(16)
                session["session_token"] = session_token
                
                interview_sess = InterviewSession(
                    user_id=current_user.id,
                    candidate_profile_id=profile.id,
                    job_description_id=jd_model.id,
                    status="draft",
                    session_token=session_token,
                    started_at=datetime.now(timezone.utc),
                    last_activity_at=datetime.now(timezone.utc)
                )
                db.session.add(interview_sess)
                db.session.commit()

            # Save Question
            q_model = Question(
                interview_session_id=interview_sess.id,
                question_text=current_question.prompt,
                question_type=current_question.kind,
                difficulty=current_question.difficulty,
                expected_signals=current_question.expected_signals,
                trap=current_question.trap,
                order_index=len(interview_sess.questions),
                topic_key=current_question.topic
            )
            db.session.add(q_model)
            db.session.commit()
            
            # Save Answer
            a_model = Answer(
                interview_session_id=interview_sess.id,
                question_id=q_model.id,
                response_text=answer,
                score=evaluation.score,
                feedback=feedback,
                answered_at=datetime.now(timezone.utc)
            )
            db.session.add(a_model)
            
            # Update interview session details
            interview_sess.current_round = len(history)
            interview_sess.last_activity_at = datetime.now(timezone.utc)
            
            # Generate Report if completion threshold is reached
            if len(history) >= 15:
                interview_sess.status = "completed"
                interview_sess.completed_at = datetime.now(timezone.utc)
                
                temp_state = _get_interview_state().copy()
                temp_state.update({
                    "history": history,
                    "last_feedback": feedback,
                    "difficulty": next_difficulty
                })
                
                duration_mins = 0
                if interview_sess.started_at and interview_sess.completed_at:
                    duration_mins = int((interview_sess.completed_at - interview_sess.started_at).total_seconds() / 60)
                temp_state["duration_mins"] = duration_mins
                
                report = ReportService().build_report(
                    user_name=current_user.full_name,
                    interview_state=temp_state,
                    resume_profile=profile.parsed_resume_data,
                    job_description=jd_model.parsed_jd_data
                )
                
                fb_report = FeedbackReport.query.filter_by(interview_session_id=interview_sess.id).first()
                if not fb_report:
                    fb_report = FeedbackReport(interview_session_id=interview_sess.id)
                    db.session.add(fb_report)
                    
                fb_report.overall_score = report.overall_score
                fb_report.technical_score = report.technical_score
                fb_report.communication_score = report.communication_score
                fb_report.summary = report.transcript_summary
                fb_report.strengths = report.strengths
                fb_report.weaknesses = report.weaknesses
                fb_report.improvement_roadmap = report.improvement_roadmap
                fb_report.full_report_json = {
                    "resume_honesty_check": report.resume_honesty_check,
                    "session_highlights": report.session_highlights,
                    "question_count": report.question_count,
                    "average_answer_length": report.average_answer_length,
                    "average_evaluation_score": report.average_evaluation_score,
                    "confidence_score": report.confidence_score,
                    "problem_solving_score": report.problem_solving_score,
                    "project_explanation_score": report.project_explanation_score,
                    "core_subjects_score": report.core_subjects_score,
                    "duration_mins": report.duration_mins,
                    "relevance_score": report.data_points.get("relevance_score", 0),
                    "depth_score": report.data_points.get("depth_score", 0),
                    "repeated_answer_detected": report.data_points.get("repeated_answer_detected", False),
                }
                fb_report.generated_at = datetime.now(timezone.utc)
                
            db.session.commit()
            print("ANSWER SAVED")

            _upsert_interview_state(
                resume_profile=resume_profile,
                job_description=job_description,
                difficulty=next_difficulty,
                history=history,
                current_question=_serialize_question(next_question),
                last_feedback=feedback,
                session_token=session_token,
                question_history=question_history,
                current_phase=current_phase,
                phase_index=phase_index,
                coding_mode_enabled=state["coding_mode_enabled"],
                audit_trail=state.get("audit_trail", [])
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

        except Exception as e:
            import traceback
            print("=" * 80)
            print("PROCESS ANSWER ERROR")
            traceback.print_exc()
            print("=" * 80)

            return jsonify({
                "success": False,
                "error": str(e),
                "exception_type": type(e).__name__
            }), 500

    @app.route("/api/interview/sync", methods=["POST"])
    @login_required
    def api_sync_interview():
        payload = request.get_json(silent=True) or {}
        raw_history = list(payload.get("session_history", []))
        history = _normalize_session_history(raw_history)
        
        state = _get_interview_state()
        state["history"] = history
        session["interview_state"] = state
        
        # If they hit sync and they have >= 15 questions, let's regenerate the report
        if len(history) >= 15:
            session_token = state.get("session_token") or session.get("session_token")
            if session_token:
                interview_sess = InterviewSession.query.filter_by(session_token=session_token).first()
                if interview_sess:
                    interview_sess.status = "completed"
                    interview_sess.completed_at = datetime.now(timezone.utc)
                    db.session.commit()
                    
                    service = _get_interview_service()
                    user_name = current_user.full_name
                    resume_profile = state.get("resume_profile") or _build_resume_profile()
                    job_description = state.get("job_description") or _build_job_profile()
                    report = service.report_service.build_report(user_name, state, resume_profile, job_description)
                    
                    # Overwrite existing FeedbackReport for this session
                    existing_report = FeedbackReport.query.filter_by(interview_session_id=interview_sess.id).first()
                    import json
                    from dataclasses import asdict
                    if existing_report:
                        existing_report.overall_score = report.overall_score
                        existing_report.technical_score = report.technical_score
                        existing_report.communication_score = report.communication_score
                        existing_report.strengths = report.strengths
                        existing_report.weaknesses = report.weaknesses
                        existing_report.improvement_roadmap = report.improvement_roadmap
                        existing_report.summary = report.transcript_summary
                        existing_report.full_report_json = asdict(report)
                        existing_report.generated_at = datetime.now(timezone.utc)
                    else:
                        db_report = FeedbackReport(
                            interview_session_id=interview_sess.id,
                            overall_score=report.overall_score,
                            technical_score=report.technical_score,
                            communication_score=report.communication_score,
                            strengths=report.strengths,
                            weaknesses=report.weaknesses,
                            improvement_roadmap=report.improvement_roadmap,
                            summary=report.transcript_summary,
                            full_report_json=asdict(report),
                            generated_at=datetime.now(timezone.utc)
                        )
                        db.session.add(db_report)
                    db.session.commit()

        return jsonify({"ok": True})

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
        except RuntimeError as exc:  # pragma: no cover - external API/runtime variability
            # Likely missing dependency or environment issue; surface helpful message
            return jsonify({"ok": False, "error": "TTS runtime error: " + str(exc)}), 502
        except Exception as exc:  # pragma: no cover - external API/runtime variability
            # Log exception server-side and return generic message to client
            import logging

            logging.getLogger(__name__).exception("Unhandled exception in api_speech_respond: %s", exc)
            return jsonify({"ok": False, "error": "TTS service failed. See server logs."}), 502

    @app.route("/api/skill-match", methods=["GET"])
    @login_required
    def api_skill_match():
        """Return skill match data for the active Resume ↔ active JD."""
        active_profile = CandidateProfile.query.filter_by(
            user_id=current_user.id, is_active=True
        ).first()
        active_jd = JobDescription.query.filter_by(
            user_id=current_user.id, is_active=True
        ).first()

        resume_data = active_profile.parsed_resume_data if active_profile else None
        jd_data = active_jd.parsed_jd_data if active_jd else None

        result = _compute_skill_match(resume_data, jd_data)
        result["ok"] = True
        result["resume_name"] = active_profile.profile_name if active_profile else None
        result["jd_title"] = active_jd.title if active_jd else None
        return jsonify(result)

    @app.route("/api/documents/set-active", methods=["POST"])
    @login_required
    def set_active_document():
        doc_type = request.form.get("type")
        doc_id = request.form.get("id")
        
        # Deleting active draft session if active resume/JD changes
        draft_sess = InterviewSession.query.filter_by(user_id=current_user.id, status="draft").first()
        if draft_sess:
            db.session.delete(draft_sess)
            db.session.commit()
        
        # Clear state
        session.pop("session_token", None)
        _set_interview_state({})

        if doc_type == "resume":
            CandidateProfile.query.filter_by(user_id=current_user.id).update({"is_active": False})
            profile = CandidateProfile.query.filter_by(id=doc_id, user_id=current_user.id).first()
            if profile:
                profile.is_active = True
                _upsert_interview_state(resume_profile=profile.parsed_resume_data)
        elif doc_type == "jd":
            JobDescription.query.filter_by(user_id=current_user.id).update({"is_active": False})
            jd = JobDescription.query.filter_by(id=doc_id, user_id=current_user.id).first()
            if jd:
                jd.is_active = True
                _upsert_interview_state(job_description=jd.parsed_jd_data)
        else:
            return jsonify({"ok": False, "error": "Invalid document type"}), 400
            
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/api/documents/delete", methods=["POST"])
    @login_required
    def delete_document():
        doc_type = request.form.get("type")
        doc_id = request.form.get("id")
        
        if doc_type == "resume":
            profile = CandidateProfile.query.filter_by(id=doc_id, user_id=current_user.id).first()
            if profile:
                db.session.delete(profile)
        elif doc_type == "jd":
            jd = JobDescription.query.filter_by(id=doc_id, user_id=current_user.id).first()
            if jd:
                db.session.delete(jd)
        else:
            return jsonify({"ok": False, "error": "Invalid document type"}), 400
            
        db.session.commit()
        return jsonify({"ok": True})

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
                    
                    # Deleting active draft session if active resume/JD changes on new upload
                    draft_sess = InterviewSession.query.filter_by(user_id=current_user.id, status="draft").first()
                    if draft_sess:
                        db.session.delete(draft_sess)
                        db.session.commit()
                    
                    # Clear state
                    session.pop("session_token", None)
                    _set_interview_state({})

                    if document_type == "resume":
                        session["resume_profile"] = parsed_summary
                        _upsert_interview_state(resume_profile=parsed_summary)
                        
                        CandidateProfile.query.filter_by(user_id=current_user.id).update({"is_active": False})
                        # Save to database CandidateProfile
                        profile = CandidateProfile(
                            user_id=current_user.id,
                            profile_name=uploaded_file.filename,
                            target_role=parsed_summary.get("target_role") or "Candidate",
                            years_experience=parsed_summary.get("years_experience"),
                            parsed_resume_data=parsed_summary,
                            is_active=True
                        )
                        db.session.add(profile)
                        db.session.commit()
                    else:
                        session["job_description"] = parsed_summary
                        _upsert_interview_state(job_description=parsed_summary)
                        
                        JobDescription.query.filter_by(user_id=current_user.id).update({"is_active": False})
                        # Save to database JobDescription
                        jd = JobDescription(
                            user_id=current_user.id,
                            title=parsed_summary.get("title") or parsed_summary.get("role") or "Selected Role",
                            company_name=parsed_summary.get("company_name"),
                            location=parsed_summary.get("location"),
                            parsed_jd_data=parsed_summary,
                            is_active=True
                        )
                        db.session.add(jd)
                        db.session.commit()
                    session.modified = True
                except Exception as exc:  # pragma: no cover - runtime dependency/file variability
                    error = f"We could not parse that file: {exc}"

            # Always return JSON on POST — the frontend handles display via AJAX
            if error:
                return jsonify({"ok": False, "error": error}), 400
            doc_type_label = "Resume" if document_type == "resume" else "Job Description"
            return jsonify({
                "ok": True,
                "message": f"{doc_type_label} uploaded successfully.",
                "result": parsed_result,
            })

        active_resume = CandidateProfile.query.filter_by(user_id=current_user.id, is_active=True).first()
        active_jd = JobDescription.query.filter_by(user_id=current_user.id, is_active=True).first()
        
        all_resumes = CandidateProfile.query.filter_by(user_id=current_user.id).order_by(CandidateProfile.created_at.desc()).all()
        all_jds = JobDescription.query.filter_by(user_id=current_user.id).order_by(JobDescription.created_at.desc()).all()

        skill_match = _compute_skill_match(
            active_resume.parsed_resume_data if active_resume else None,
            active_jd.parsed_jd_data if active_jd else None,
        )

        response = make_response(render_template(
            "upload.html",
            title="Upload | InterviewForge",
            page_type="upload",
            body_class="upload-page",
            user_name=current_user.full_name,
            error=error,
            parsed_result=parsed_result,
            active_resume=active_resume,
            active_jd=active_jd,
            all_resumes=all_resumes,
            all_jds=all_jds,
            skill_match=skill_match,
        ))
        # Prevent browser from caching the upload page so file inputs always reset
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=app.config["DEBUG"], host="0.0.0.0", port=port)
