from __future__ import annotations

from datetime import datetime, timezone

import bcrypt
from flask_login import UserMixin

from extensions import db, login_manager


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    profile_image = db.Column(db.String(255), nullable=True)

    candidate_profiles = db.relationship(
        "CandidateProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    job_descriptions = db.relationship(
        "JobDescription",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    interview_sessions = db.relationship(
        "InterviewSession",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def set_password(self, password: str) -> None:
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))
        self.password_hash = hashed.decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), self.password_hash.encode("utf-8"))


class CandidateProfile(TimestampMixin, db.Model):
    __tablename__ = "candidate_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    profile_name = db.Column(db.String(160), nullable=False)
    target_role = db.Column(db.String(160), nullable=True)
    years_experience = db.Column(db.Numeric(4, 1), nullable=True)
    parsed_resume_data = db.Column(db.JSON, nullable=False, default=dict)
    is_active = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship("User", back_populates="candidate_profiles")
    interview_sessions = db.relationship(
        "InterviewSession",
        back_populates="candidate_profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class JobDescription(TimestampMixin, db.Model):
    __tablename__ = "job_descriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    company_name = db.Column(db.String(180), nullable=True)
    location = db.Column(db.String(180), nullable=True)
    parsed_jd_data = db.Column(db.JSON, nullable=False, default=dict)
    is_active = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship("User", back_populates="job_descriptions")
    interview_sessions = db.relationship(
        "InterviewSession",
        back_populates="job_description",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class InterviewSession(TimestampMixin, db.Model):
    __tablename__ = "interview_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_profile_id = db.Column(
        db.Integer,
        db.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_description_id = db.Column(
        db.Integer,
        db.ForeignKey("job_descriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = db.Column(db.String(32), nullable=False, default="draft", index=True)
    session_token = db.Column(db.String(80), nullable=True, unique=True, index=True)
    current_round = db.Column(db.Integer, nullable=False, default=0)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_activity_at = db.Column(db.DateTime(timezone=True), nullable=True)
    current_phase = db.Column(db.String(80), nullable=True)
    phase_index = db.Column(db.Integer, nullable=True, default=0)

    user = db.relationship("User", back_populates="interview_sessions")
    candidate_profile = db.relationship("CandidateProfile", back_populates="interview_sessions")
    job_description = db.relationship("JobDescription", back_populates="interview_sessions")
    questions = db.relationship(
        "Question",
        back_populates="interview_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Question.order_index",
    )
    answers = db.relationship(
        "Answer",
        back_populates="interview_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Answer.created_at",
    )
    feedback_report = db.relationship(
        "FeedbackReport",
        back_populates="interview_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    interview_history = db.relationship(
        "InterviewHistory",
        back_populates="interview_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    interview_report_analytics = db.relationship(
        "InterviewReport",
        back_populates="interview_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    question_evaluations = db.relationship(
        "QuestionEvaluation",
        back_populates="interview_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    interview_analytics = db.relationship(
        "InterviewAnalytics",
        back_populates="interview_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    skill_analytics = db.relationship(
        "SkillAnalytics",
        back_populates="interview_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Question(TimestampMixin, db.Model):
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    interview_session_id = db.Column(
        db.Integer,
        db.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(64), nullable=False, default="adaptive")
    difficulty = db.Column(db.Integer, nullable=False, default=5)
    expected_signals = db.Column(db.JSON, nullable=False, default=list)
    trap = db.Column(db.Boolean, nullable=False, default=False)
    order_index = db.Column(db.Integer, nullable=False, default=0)
    asked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    topic_key = db.Column(db.String(120), nullable=True)

    interview_session = db.relationship("InterviewSession", back_populates="questions")
    answer = db.relationship(
        "Answer",
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class Answer(TimestampMixin, db.Model):
    __tablename__ = "answers"

    id = db.Column(db.Integer, primary_key=True)
    interview_session_id = db.Column(
        db.Integer,
        db.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id = db.Column(
        db.Integer,
        db.ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    response_text = db.Column(db.Text, nullable=False)
    transcribed_text = db.Column(db.Text, nullable=True)
    score = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    feedback = db.Column(db.Text, nullable=True)
    answered_at = db.Column(db.DateTime(timezone=True), nullable=True)

    interview_session = db.relationship("InterviewSession", back_populates="answers")
    question = db.relationship("Question", back_populates="answer")


class FeedbackReport(TimestampMixin, db.Model):
    __tablename__ = "feedback_reports"

    id = db.Column(db.Integer, primary_key=True)
    interview_session_id = db.Column(
        db.Integer,
        db.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    overall_score = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    technical_score = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    communication_score = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    summary = db.Column(db.Text, nullable=False, default="")
    strengths = db.Column(db.JSON, nullable=False, default=list)
    weaknesses = db.Column(db.JSON, nullable=False, default=list)
    improvement_roadmap = db.Column(db.JSON, nullable=False, default=list)
    full_report_json = db.Column(db.JSON, nullable=False, default=dict)
    pdf_path = db.Column(db.String(255), nullable=True)
    generated_at = db.Column(db.DateTime(timezone=True), nullable=True)

    interview_session = db.relationship("InterviewSession", back_populates="feedback_report")


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id)) if user_id.isdigit() else None


class InterviewHistory(TimestampMixin, db.Model):
    __tablename__ = "interview_history"

    id = db.Column(db.Integer, primary_key=True)
    interview_session_id = db.Column(
        db.Integer,
        db.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    interview_name = db.Column(db.String(180), nullable=False)
    interview_type = db.Column(db.String(64), nullable=False)
    date = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    duration_mins = db.Column(db.Integer, nullable=False, default=0)
    total_questions = db.Column(db.Integer, nullable=False, default=0)
    questions_answered = db.Column(db.Integer, nullable=False, default=0)
    difficulty = db.Column(db.String(32), nullable=False, default="Intermediate")
    status = db.Column(db.String(32), nullable=False, default="completed")

    interview_session = db.relationship("InterviewSession", back_populates="interview_history")

    @property
    def overall_score(self):
        if self.interview_session and self.interview_session.interview_analytics:
            return self.interview_session.interview_analytics.overall_score
        return 0.0


class InterviewReport(TimestampMixin, db.Model):
    __tablename__ = "interview_reports"

    id = db.Column(db.Integer, primary_key=True)
    interview_session_id = db.Column(
        db.Integer,
        db.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    summary = db.Column(db.Text, nullable=False, default="")
    strengths = db.Column(db.JSON, nullable=False, default=list)
    weaknesses = db.Column(db.JSON, nullable=False, default=list)
    recommendations = db.Column(db.JSON, nullable=False, default=list)

    interview_session = db.relationship("InterviewSession", back_populates="interview_report_analytics")


class QuestionEvaluation(TimestampMixin, db.Model):
    __tablename__ = "question_evaluations"

    id = db.Column(db.Integer, primary_key=True)
    interview_session_id = db.Column(
        db.Integer,
        db.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_text = db.Column(db.Text, nullable=False)
    answer_text = db.Column(db.Text, nullable=False)
    score = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    evaluation = db.Column(db.Text, nullable=True)
    strengths = db.Column(db.JSON, nullable=False, default=list)
    weaknesses = db.Column(db.JSON, nullable=False, default=list)
    suggestions = db.Column(db.JSON, nullable=False, default=list)
    time_spent = db.Column(db.Integer, nullable=False, default=0)
    question_type = db.Column(db.String(64), nullable=False, default="adaptive")
    difficulty = db.Column(db.Integer, nullable=False, default=5)

    interview_session = db.relationship("InterviewSession", back_populates="question_evaluations")


class InterviewAnalytics(TimestampMixin, db.Model):
    __tablename__ = "interview_analytics"

    id = db.Column(db.Integer, primary_key=True)
    interview_session_id = db.Column(
        db.Integer,
        db.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    overall_score = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    performance_grade = db.Column(db.String(10), nullable=True)
    interview_rating = db.Column(db.String(32), nullable=True)
    confidence_score = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    completion_percentage = db.Column(db.Numeric(5, 2), nullable=False, default=0)

    # breakdown dimensions
    technical_accuracy = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    relevance = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    communication = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    depth = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    problem_solving = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    system_design = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    project_understanding = db.Column(db.Numeric(5, 2), nullable=False, default=0)

    interview_session = db.relationship("InterviewSession", back_populates="interview_analytics")


class SkillAnalytics(TimestampMixin, db.Model):
    __tablename__ = "skill_analytics"

    id = db.Column(db.Integer, primary_key=True)
    interview_session_id = db.Column(
        db.Integer,
        db.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_name = db.Column(db.String(120), nullable=False)
    average_score = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    performance_level = db.Column(db.String(32), nullable=False, default="Intermediate")
    improvement_priority = db.Column(db.String(32), nullable=False, default="Medium")

    interview_session = db.relationship("InterviewSession", back_populates="skill_analytics")
