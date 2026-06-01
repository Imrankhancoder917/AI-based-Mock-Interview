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


def _normalize_session_history(raw_history: Iterable[dict] | None) -> list[dict]:
    """Normalize legacy or incoming history payloads into structured history entries.

    Each entry: {question, answer, score, weaknesses, topic}
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
            normalized.append({"question": q, "answer": a, "score": s, "weaknesses": weaknesses, "topic": topic})
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
        raw_history = payload.get("session_history") or _build_history()
        history = _normalize_session_history(raw_history)
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
        raw_history = list(payload.get("session_history") or _build_history())
        history = _normalize_session_history(raw_history)
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

        # Build structured history entry and keep only recent meaningful items
        topic = current_question.follow_up_seed or (current_question.expected_signals[0] if current_question.expected_signals else "")
        weaknesses = evaluation.gaps if getattr(evaluation, "gaps", None) else []
        entry = {
            "question": current_question.prompt,
            "answer": answer,
            "score": evaluation.score,
            "weaknesses": weaknesses,
            "topic": topic,
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

        # Use AIService follow-up (may be Groq-backed); it will read follow_up_seed embedded above
        next_question = service.generate_followup_question(current_question, answer, evaluation.score)
        feedback = service.evaluator.generate_feedback(evaluation, current_question.prompt)

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
        except RuntimeError as exc:  # pragma: no cover - external API/runtime variability
            # Likely missing dependency or environment issue; surface helpful message
            return jsonify({"ok": False, "error": "TTS runtime error: " + str(exc)}), 502
        except Exception as exc:  # pragma: no cover - external API/runtime variability
            # Log exception server-side and return generic message to client
            import logging

            logging.getLogger(__name__).exception("Unhandled exception in api_speech_respond: %s", exc)
            return jsonify({"ok": False, "error": "TTS service failed. See server logs."}), 502

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
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=app.config["DEBUG"], host="0.0.0.0", port=port)
