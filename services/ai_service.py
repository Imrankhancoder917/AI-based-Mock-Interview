from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import re
from typing import Any

import requests

from .adaptive_engine import AdaptiveEngine, InterviewContext, InterviewQuestion, PHASE_CATEGORIES
from .evaluation_service import AnswerEvaluation, EvaluationService


class QuestionValidator:
    """Validator for AI-generated questions to ensure they are production-grade,
    relevant, correctly formatted, and do not contain forbidden topics/phrases.
    """
    
    @staticmethod
    def validate(
        question_text: str,
        kind: str,
        expected_signals: list[str],
        question_history: list[str],
        topic_history: list[str],
        resume_profile: dict,
        category: str = "",
        topic: str = "",
        job_description: dict | None = None,
        session_history: list[dict] | None = None,
        current_phase: str = "INTRODUCTION",
        coding_mode_enabled: bool = False,
        entity_name: str = "",
        relaxation_stage: int = 0,
        entity_type: str = "",
    ) -> tuple[bool, str | None]:
        """Validate an AI-generated question.
        Returns:
            (is_valid: bool, reject_reason: str | None)
        """
        from services.adaptive_engine import PHASE_CATEGORIES, CATEGORY_ALLOWED_ENTITY_TYPES
        
        q_text = question_text.strip()
        if not q_text:
            return False, "Empty question"
            
        if len(q_text) < 15:
            return False, "Question is too short"
            
        if not q_text.endswith("?"):
            return False, "Question does not end with a question mark"

        placeholders = ["[project", "[company", "[role", "<company", "<project", "<role", "insert name", "[insert", "{project"]
        for p in placeholders:
            if p in q_text.lower():
                return False, f"Contains placeholder: {p}"

        from parsers import _is_date_like
        for sig in expected_signals:
            if _is_date_like(sig):
                return False, f"Expected signal '{sig}' is a date-like entity"

        date_patterns = [
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
            r"\b\d{4}\b",
            r"\b\d{4}\s*-\s*\d{4}\b",
            r"\b\d{4}\s*-\s*Present\b"
        ]
        for pat in date_patterns:
            if re.search(pat, q_text, re.IGNORECASE):
                return False, f"Question contains date entity matching pattern: {pat}"

        # Reject generic project labels
        generic_labels = {
            "web application",
            "ai web application",
            "full stack application",
            "full stack ai web application",
            "machine learning project",
            "software system",
            "web platform",
            "application",
            "platform",
            "system"
        }
        for sig in expected_signals:
            if sig.strip().lower() in generic_labels:
                return False, f"Expected signal '{sig}' is a generic project label"

        q_text_lower = q_text.strip().lower()
        
        # Forbidden follow-ups checks
        if "high level" in q_text_lower and "implementation of" in q_text_lower:
            return False, "Contains forbidden high-level implementation follow-up pattern"
            
        forbidden_skill_archs = [
            "architecture of html", "html architecture",
            "architecture of css", "css architecture",
            "architecture of git", "git architecture",
            "walk me through git", "explain the architecture of html"
        ]
        for fa in forbidden_skill_archs:
            if fa in q_text_lower:
                return False, f"Contains forbidden skill architecture question: {fa}"

        # Database technology project-like pattern rejection
        database_products = {
            "mysql",
            "postgresql",
            "mongodb",
            "sqlite",
            "oracle",
            "redis",
            "cassandra",
            "dynamodb",
            "postgres"
        }
        for db in database_products:
            if f"database design for {db}" in q_text_lower:
                return False, f"Contains forbidden database project-like pattern: 'database design for {db}'"
            if f"architecture of {db}" in q_text_lower:
                return False, f"Contains forbidden database project-like pattern: 'architecture of {db}'"
            if f"implementation of {db}" in q_text_lower:
                return False, f"Contains forbidden database project-like pattern: 'implementation of {db}'"
            if f"schema of {db}" in q_text_lower:
                return False, f"Contains forbidden database project-like pattern: 'schema of {db}'"

        # Topic Group / Entity / Cooldown / Duplicate Checks
        from services.adaptive_engine import resolve_topic_group, CATEGORY_TO_TOPIC_GROUP, AdaptiveEngine
        engine = AdaptiveEngine()
        clean_cand_entity = engine._clean_entity_name(entity_name or (expected_signals[0] if expected_signals else "")).strip().lower()

        # Resolve entity_type if not explicitly passed
        resolved_entity_type = entity_type
        if not resolved_entity_type:
            if "internship" in kind.lower():
                resolved_entity_type = "internship"
            elif entity_name and entity_name.strip().lower() == "apex planet":
                resolved_entity_type = "internship"
            elif entity_name and resume_profile:
                clean_entity_name = engine._clean_entity_name(entity_name).strip().lower()
                for i in resume_profile.get("internships") or []:
                    i_company = engine._clean_entity_name(i.get("company") or "").strip().lower()
                    if i_company == clean_entity_name:
                        resolved_entity_type = "internship"
                        break

        # Also check if any known internship company name or "apex planet" is in the question text or entity_name
        is_internship_ref = (resolved_entity_type == "internship")
        if not is_internship_ref:
            if "apex planet" in q_text_lower:
                is_internship_ref = True
            elif entity_name and entity_name.strip().lower() == "apex planet":
                is_internship_ref = True
            elif resume_profile:
                for i in resume_profile.get("internships") or []:
                    co = i.get("company") or ""
                    if co and co.strip().lower() in q_text_lower:
                        is_internship_ref = True
                        break

        # 1. Exact same topic_key uniqueness
        if topic and topic_history:
            if topic.strip().lower() in [t.strip().lower() for t in topic_history]:
                return False, f"Topic '{topic}' has already been covered in this session"

        # 2. Topic Group Cooldown (Stage dependent)
        cand_topic_group = resolve_topic_group(topic, entity_type=resolved_entity_type)
        recent_topic_groups = []
        for h in (session_history or [])[-4:]:
            tk = h.get("topic") or ""
            if tk:
                h_ent_type = h.get("entity_type", "")
                recent_topic_groups.append(resolve_topic_group(tk, entity_type=h_ent_type))

        if relaxation_stage < 4 and cand_topic_group in recent_topic_groups:
            # Check if there is an alternative topic group allowed in current phase
            alt_topic_group_exists = False
            for other_cat in PHASE_CATEGORIES.get(current_phase, []):
                def_tg = CATEGORY_TO_TOPIC_GROUP.get(other_cat)
                if def_tg and def_tg not in recent_topic_groups:
                    alt_topic_group_exists = True
                    break
            if alt_topic_group_exists:
                return False, f"Topic group '{cand_topic_group}' was recently covered, and alternative topic groups exist."

        # 3. Entity Cooldown (Hard rule: Entity appears 4+ times in last 6 questions)
        recent_entities_6 = []
        for h in (session_history or [])[-5:]:
            ent = h.get("entity") or h.get("follow_up_seed") or ""
            if ent:
                recent_entities_6.append(engine._clean_entity_name(ent).strip().lower())
        if recent_entities_6.count(clean_cand_entity) >= 3:
            return False, f"Entity '{entity_name}' appears 4+ times in the last 6 questions."

        # 4. Strengthened Duplicate Detection (Same Entity + Same Topic Group)
        for h in (session_history or []):
            h_ent = h.get("entity") or h.get("follow_up_seed") or ""
            h_topic = h.get("topic") or ""
            if h_ent and h_topic:
                h_ent_clean = engine._clean_entity_name(h_ent).strip().lower()
                h_tg = resolve_topic_group(h_topic, entity_type=resolved_entity_type)
                if h_ent_clean == clean_cand_entity and h_tg == cand_topic_group:
                    return False, f"Duplicate question concept: entity '{entity_name}' was already asked under topic group '{cand_topic_group}'."

        # Priority 4: Internship Topic Group Cooldown
        # Reject same internship entity + same internship topic group if asked within last 5 questions
        if resolved_entity_type == "internship" and cand_topic_group.startswith("intern_"):
            for h in (session_history or [])[-5:]:
                h_ent = h.get("entity") or h.get("follow_up_seed") or ""
                h_topic_key = h.get("topic") or ""
                if h_ent and h_topic_key:
                    h_ent_clean = engine._clean_entity_name(h_ent).strip().lower()
                    h_ent_type = h.get("entity_type", "")
                    h_tg = resolve_topic_group(h_topic_key, entity_type=h_ent_type)
                    if h_ent_clean == clean_cand_entity and h_tg == cand_topic_group:
                        return False, f"Internship topic group cooldown: '{entity_name}' + '{cand_topic_group}' asked within last 5 questions."

        # Category Uniqueness (no consecutive category repeats within 3 questions) - only for non-followups
        if kind != "follow_up" and category and session_history:
            recent_categories = [h.get("category") for h in session_history[-2:] if h.get("category")]
            if category in recent_categories:
                return False, f"Category '{category}' repeated consecutively within last 3 questions"

        # Phase compatibility check
        if is_internship_ref:
            from services.adaptive_engine import INTERNSHIP_CATEGORIES_BY_PHASE
            allowed_cats = INTERNSHIP_CATEGORIES_BY_PHASE.get(current_phase, ["Behavioral + Project"])
        else:
            allowed_cats = PHASE_CATEGORIES.get(current_phase, [])
        if allowed_cats and category not in allowed_cats:
            return False, f"Category '{category}' is incompatible with phase '{current_phase}'"

        # Category ↔ Entity Compatibility check
        if kind != "follow_up":
            clean_kind = kind.replace("_based", "")
            if resolved_entity_type:
                clean_kind = resolved_entity_type
            allowed_types = CATEGORY_ALLOWED_ENTITY_TYPES.get(category)
            if allowed_types and clean_kind not in allowed_types:
                return False, f"Category '{category}' is incompatible with entity type '{clean_kind}'"

        # Coding Safety check
        if not coding_mode_enabled and (current_phase == "CODING" or category == "Theoretical DSA"):
            coding_verbs = ["write code", "write a function", "write python", "write javascript", "implement a function", "code up", "write a program", "coding challenge", "complete solution"]
            for verb in coding_verbs:
                if verb in q_text_lower:
                    return False, f"Coding safety mode is active, but question asks to write code: '{verb}'"

        # Follow-up phase/category checks
        if kind == "follow_up":
            allowed_followup_cats = {"Tradeoffs", "Debugging", "Scalability", "Performance", "Failure Scenarios", "Implementation"}
            if category not in allowed_followup_cats:
                return False, f"Follow-up category '{category}' is not allowed"
            if category == "Problem Understanding":
                return False, "Problem Understanding follow-ups are forbidden"

        # Resume/JD Relevance Filter
        common_tech_tools = {
            "cassandra", "redis", "kafka", "mongodb", "postgresql", "mysql", "dynamodb", "elasticsearch", "rabbitmq",
            "kubernetes", "docker", "terraform", "ansible", "jenkins", "aws", "gcp", "azure",
            "react", "angular", "vue", "flask", "django", "spring", "rails", "graphql", "grpc", "sqlite",
            "typescript", "javascript", "python", "java", "golang", "rust", "c++", "c#", "swift", "kotlin",
            "jwt", "oauth", "spark", "hadoop", "flink", "hive", "s3", "lambda", "ecs", "eks", "fargate"
        }
        
        flat_context = ""
        if resume_profile:
            flat_context += json.dumps(resume_profile).lower()
        if job_description:
            flat_context += json.dumps(job_description).lower()
            
        for tech in common_tech_tools:
            if re.search(r"\b" + re.escape(tech) + r"\b", q_text_lower):
                if tech not in flat_context:
                    return False, f"Question mentions technology '{tech}' not found in candidate profile or job description"

        # Regex to check if any generic label is the target of architecture / implementation
        label_pattern = r"\b(architecture|design|explain|implement|steps|structure|system design)\b.*?\b(web application|ai web application|full stack application|full stack ai web application|machine learning project|software system|web platform|application|platform|system)\b"
        if re.search(label_pattern, q_text_lower):
            match = re.search(label_pattern, q_text_lower)
            matched_label = match.group(2)
            if matched_label in {"application", "platform", "system"}:
                if re.search(rf"\b(explain|implement|architecture of|design of|structure of)\s+(the\s+)?(application|platform|system)[.?]?$", q_text_lower):
                    return False, f"Treats generic label '{matched_label}' as a project entity"
            else:
                return False, f"Treats generic label '{matched_label}' as a project entity"

        # EXACT QUESTION DUPLICATE PROTECTION (last 20 questions)
        def normalize_q(text: str) -> str:
            t = text.lower().strip()
            t = re.sub(r"[^\w\s]", "", t)  # remove punctuation
            return " ".join(t.split())

        q_norm = normalize_q(q_text)
        
        # Build last 20 questions list from session_history and question_history
        recent_questions = []
        if session_history:
            recent_questions.extend([h.get("question", "") for h in session_history if h.get("question")])
        for q_hist in question_history:
            if q_hist not in recent_questions:
                recent_questions.append(q_hist)
        recent_questions = recent_questions[-20:]

        for prev in recent_questions:
            if normalize_q(prev) == q_norm:
                return False, f"Exact duplicate of recent question (normalized match): '{prev}'"

        for prev in question_history:
            prev_words = set(prev.lower().split())
            q_words = set(q_text_lower.split())
            if prev_words and q_words:
                overlap = len(prev_words & q_words) / max(len(prev_words), len(q_words))
                if overlap > 0.8:
                    return False, "Highly similar to a previous question"

        companies = []
        raw_companies = resume_profile.get("companies") or []
        for c in raw_companies:
            if isinstance(c, str) and c.strip():
                companies.append(c.strip())
        for i in (resume_profile.get("internships") or []):
            if isinstance(i, dict) and i.get("company"):
                companies.append(i["company"].strip())
        for e in (resume_profile.get("experience") or []):
            if isinstance(e, dict) and e.get("company"):
                companies.append(e["company"].strip())
                
        architecture_keywords = {"architecture", "system design", "infrastructure", "scaling", "scale", "bottleneck", "rebuild from scratch", "technical design"}
        
        for company in companies:
            if company and company.lower() in q_text_lower:
                if any(kw in q_text_lower for kw in architecture_keywords):
                    return False, f"Asks company architecture for '{company}'"

        skills = []
        raw_skills = resume_profile.get("skills") or []
        if isinstance(raw_skills, dict):
            for v in raw_skills.values():
                if isinstance(v, list):
                    skills.extend(v)
        else:
            skills = raw_skills
            
        for skill in skills:
            if isinstance(skill, str) and skill.strip():
                skill_clean = skill.strip()
                if skill_clean.lower() in q_text_lower:
                    if any(kw in q_text_lower for kw in architecture_keywords):
                        return False, f"Asks architecture for general skill '{skill_clean}'"

        # Strict pattern-based validation check for internship entities
        if is_internship_ref:
            FORBIDDEN_INTERNSHIP_PATTERNS = [
                "architecture of",
                "components of",
                "data flow through",
                "database schema of",
                "system design of",
                "platform architecture of",
                "service architecture of",
                "database schema",
                "schema decisions",
                "evidence convinced you",
                "problem addressed by",
                "actually existed",
            ]
            for pattern in FORBIDDEN_INTERNSHIP_PATTERNS:
                if pattern in q_text_lower:
                    return False, f"Internship question contains forbidden pattern '{pattern}'"

        return True, None


def _sanitize_profile(data: Any) -> Any:
    """Recursively scrub email, phone number, address/location keywords, and links from the profile data."""
    if isinstance(data, dict):
        forbidden_keys = {"email", "phone", "address", "location", "linkedin", "github", "contact", "website", "url", "link"}
        cleaned_dict = {}
        for k, v in data.items():
            if k.lower() in forbidden_keys:
                continue
            cleaned_dict[k] = _sanitize_profile(v)
        return cleaned_dict
    elif isinstance(data, list):
        cleaned_list = []
        for item in data:
            sanitized_item = _sanitize_profile(item)
            if sanitized_item:
                cleaned_list.append(sanitized_item)
        return cleaned_list
    elif isinstance(data, str):
        # Remove retrieval metadata, highlights, and vector search annotations
        text = re.sub(r"\(\d+\)$", "", data).strip()
        text = re.sub(r"\s*\|\s*H:.*$", "", text).strip()
        text = re.sub(r"\[Highlight.*?\]|\(Snippet.*?\)", "", text, flags=re.IGNORECASE).strip()

        # Remove PII and links
        text = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "", text)
        text = re.sub(r"https?://[^\s]+|www\.[^\s]+|linkedin\.com/[^\s]+|github\.com/[^\s]+", "", text)
        text = re.sub(r"\+?\d{1,4}[-.\s]?\(?\d{1,3}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}", "", text)
        text = re.sub(r"(?i)\b(address|location|phone|email|linkedin|github|website)\b\s*:\s*[^\n]+", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not re.search(r"[a-zA-Z0-9]", text):
            return ""
        return text
    return data


# Legacy round phase logic removed


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
    """Facade that coordinates question generation, evaluation, and feedback.

    ALL question generation is 100% dynamic. There are NO hardcoded question banks.
    Every question is personalized using the candidate's Resume + JD + Performance.
    """

    def __init__(self, seed: int | None = None):
        self.engine = AdaptiveEngine(seed=seed)
        self.evaluator = EvaluationService()

    def create_context(self, resume_profile: dict, job_description: dict | None = None, difficulty: int = 5, session_history: list[dict] | None = None) -> InterviewContext:
        sanitized_resume = _sanitize_profile(resume_profile)
        sanitized_jd = _sanitize_profile(job_description) if job_description else None
        role_family = self.engine.build_role_family(sanitized_resume, sanitized_jd)
        return InterviewContext(
            resume_profile=sanitized_resume,
            job_description=sanitized_jd,
            role_family=role_family,
            difficulty=difficulty,
            session_history=session_history or [],
        )

    def generate_question(self, resume_profile: dict, job_description: dict | None = None, difficulty: int = 5, session_history: list[dict] | None = None, question_history: list[str] | None = None, state_memory: dict | None = None) -> InterviewQuestion:
        """Generate a single realistic, interviewer-style question using Groq."""
        if not state_memory:
            cats = self.engine._extract_history_categories(session_history or [], resume_profile)
            state_memory = {
                "question_history": question_history or [h.get("question", "") for h in (session_history or [])],
                "topic_history": list(cats["topic_history"]),
                "covered_projects": list(cats["covered_projects"]),
                "covered_skills": list(cats["covered_skills"]),
                "covered_subjects": list(cats["covered_subjects"]),
                "covered_internships": list(cats["covered_internships"]),
                "covered_experience": list(cats["covered_experience"]),
                "covered_certificates": [],
            }

        # Ensure active phase and coding mode are in state memory
        history_len = len(session_history or [])
        current_phase = state_memory.get("current_phase")
        if not current_phase:
            from app import determine_active_phase
            current_phase, phase_index = determine_active_phase(history_len, is_followup=False)
            state_memory["current_phase"] = current_phase
            state_memory["phase_index"] = phase_index
        coding_mode_enabled = state_memory.get("coding_mode_enabled") or False

        # Exclusions for fail-safe loop
        rejected_entities = set()
        rejected_categories = set()
        
        last_reason = "Unknown validation failure"
        last_entity = "Unknown"
        last_category = "Unknown"

        context = self.create_context(resume_profile, job_description, difficulty, session_history)
        
        MAX_GENERATION_ATTEMPTS = 10
        final_question = None

        for attempt in range(MAX_GENERATION_ATTEMPTS):
            # Attempt 10: trigger phase-aware safe fallback
            if attempt == 9:
                # Log failure
                print("VALIDATION FAILURE")
                print(f"REASON: {last_reason}")
                print(f"ENTITY: {last_entity}")
                print(f"CATEGORY: {last_category}")
                print("\nFallback Triggered\n")
                
                # Fetch fallback category
                allowed_cats = list(PHASE_CATEGORIES.get(current_phase, ["Behavioral + Project"]))
                if current_phase == "CODING":
                    allowed_cats = ["Coding"] if coding_mode_enabled else ["Theoretical DSA"]
                fallback_category = allowed_cats[0]
                
                # Find a valid fallback entity, passing all rejected entities/categories as exclusions
                fallback_payload = self.engine.select_topic_and_context(
                    context, state_memory,
                    exclude_categories=list(rejected_categories) if rejected_categories else None,
                    exclude_entities=list(rejected_entities) if rejected_entities else None
                )
                target_entity = fallback_payload["target_entity"]
                entity_type = fallback_payload["entity_type"]

                # Force category compatibility for internship fallback
                if entity_type == "internship":
                    from services.adaptive_engine import INTERNSHIP_CATEGORIES_BY_PHASE
                    allowed_intern_cats = INTERNSHIP_CATEGORIES_BY_PHASE.get(current_phase, ["Behavioral + Project"])
                    fallback_category = allowed_intern_cats[0]
                
                final_question = self.engine.build_fallback_question(context, target_entity, entity_type, category=fallback_category)
                break

            # Switch logic:
            # Attempts 1-3: normal regeneration (exclusions = None)
            # Attempts 4-6: switch entity (exclude rejected entities)
            # Attempts 7-9: switch category (exclude rejected categories & entities)
            exclude_ents = list(rejected_entities) if attempt >= 3 else None
            exclude_cats = list(rejected_categories) if attempt >= 6 else None

            # Get target entity and category using exclusions
            context_payload = self.engine.select_topic_and_context(
                context, 
                state_memory, 
                exclude_categories=exclude_cats, 
                exclude_entities=exclude_ents
            )
            
            entity_type = context_payload["entity_type"]
            target_entity = context_payload["target_entity"]
            target_difficulty = context_payload["difficulty"]
            category = context_payload.get("category", "Behavioral + Project")

            # Force category compatibility for internship entities
            if entity_type == "internship":
                from services.adaptive_engine import INTERNSHIP_CATEGORIES_BY_PHASE
                allowed_intern_cats = INTERNSHIP_CATEGORIES_BY_PHASE.get(current_phase, ["Behavioral + Project"])
                if category not in allowed_intern_cats:
                    category = allowed_intern_cats[0]

            if isinstance(target_entity, dict):
                entity_name = target_entity.get("name") or target_entity.get("company") or target_entity.get("title") or "your project"
            else:
                entity_name = str(target_entity)
            entity_name = self.engine._clean_entity_name(entity_name)

            # Call LLM logic
            api_key = os.environ.get("GROQ_API_KEY", "")
            model = os.environ.get("SECONDARY_LLM_MODEL", "grok-3-mini")

            # Determine category specific guidelines/rules
            specific_rules = ""
            if entity_type == "project":
                specific_rules = (
                    "The selected target is a PROJECT. You may ask about technical architecture, system design, "
                    "data flow, tradeoffs, optimization, performance, caching, scalability, or distributed system designs.\n"
                    "STRICT PROJECT NAME RULE: You must ALWAYS refer to the project using its 'name' (e.g., 'Digital Mental Health and Psychological Support System'). "
                    "NEVER use its 'type' (e.g., 'Full Stack AI Web Application') as the primary interview entity/focus of the question. "
                    "For example, NEVER ask: 'Explain Full Stack AI Web Application', 'How did you implement Full Stack AI Web Application?', "
                    "or 'Walk me through the architecture of Full Stack AI Web Application'.\n"
                )
            elif entity_type == "internship":
                specific_rules = (
                    "The selected target is an INTERNSHIP. You MUST focus exclusively on responsibilities, tasks, "
                    "technologies used, challenges, impact, mentorship, team collaboration, or learning.\n"
                    "STRICTLY FORBIDDEN: Do NOT ask about technical architecture, system design, or scaling for this internship company.\n"
                )
            elif entity_type == "experience":
                specific_rules = (
                    "The selected target is work EXPERIENCE. You MUST focus on ownership, leadership, debugging, "
                    "technical decisions, impact, project contributions, or team collaboration.\n"
                    "STRICTLY FORBIDDEN: Do NOT ask about technical architecture, system design, or scaling for this employer.\n"
                )
            elif entity_type == "skill":
                specific_rules = (
                    "The selected target is a general SKILL / tool. You MUST focus on practical usage, implementation details, "
                    "debugging, project context, or best practice questions.\n"
                    "STRICTLY FORBIDDEN: Do NOT ask about the 'architecture' or 'design' of the skill itself (e.g., NEVER ask about HTML/CSS/Git architecture).\n"
                )
            elif entity_type == "subject":
                specific_rules = (
                    f"The selected target is a core CS SUBJECT: {target_entity}. Ask a contextual CS fundamentals question "
                    "relevant to the candidate's resume/JD. Avoid generic textbook definitions.\n"
                )
            elif entity_type == "behavioral":
                specific_rules = (
                    "The selected target is BEHAVIORAL. Ask a situational question grounded in the candidate's projects "
                    "or work experience. Focus on deadline handling, team collaboration, conflicts, or learnings.\n"
                )

            # Database category specific rules based on entity_type
            if category == "Database":
                if entity_type == "project":
                    specific_rules += (
                        "\nDATABASE CATEGORY RULES FOR PROJECT ENTITIES:\n"
                        f"The target database entity is a PROJECT: {entity_name}. Focus the question on the database aspects of this project.\n"
                        "Allowed topics: schema design, relationship modeling, indexing strategy, query bottlenecks, or handling traffic scalability.\n"
                        f"Example: 'How did you design the database schema for {entity_name}?' or 'What indexing strategy did you use in {entity_name}?'\n"
                        "STRICTLY FORBIDDEN: Do NOT ask database selection templates that treat the project name as a database product itself.\n"
                    )
                elif entity_type == "skill":
                    specific_rules += (
                        "\nDATABASE CATEGORY RULES FOR DATABASE TECHNOLOGY/SKILL ENTITIES:\n"
                        f"The target database entity is a database technology/skill: {entity_name}.\n"
                        "Allowed topics: why you chose it over alternatives, advantages, limitations, query optimization, indexing, or scaling the database technology.\n"
                        "STRICTLY FORBIDDEN: Do NOT treat the database technology itself as a project. "
                        f"For example, NEVER ask: 'Why did you choose the database design for {entity_name}?', "
                        f"'Explain the database architecture of {entity_name}', or similar generic patterns.\n"
                    )

            # Enforce Coding Safety instructions inside prompt
            if category == "Theoretical DSA" or (current_phase == "CODING" and not coding_mode_enabled):
                specific_rules += (
                    "\nCODING SAFETY MODE IS ACTIVE:\n"
                    "You MUST only ask theoretical DSA, complexity analysis, algorithm reasoning, or debugging questions.\n"
                    "STRICTLY FORBIDDEN: Do NOT ask the candidate to write code or implement a function. Focus only on conceptual "
                    "explanations and tradeoffs.\n"
                )

            difficulty_guidelines = (
                "DIFFICULTY SYSTEM:\n"
                "- Difficulty 1-3: Project Overview, Problem Statement, Basic Concepts, Technology Introduction.\n"
                "- Difficulty 4-6: Implementation Details, Technology Usage, Debugging, Module Design.\n"
                "- Difficulty 7-8: Architecture, Tradeoffs, Optimization, Performance, Security.\n"
                "- Difficulty 9-10: Scalability, Reliability, Production Systems, Monitoring, Caching, Distributed Systems, System Design, Failure Recovery.\n"
            )

            styles = [
                "Analytical",
                "Practical",
                "Architecture-Focused",
                "Debugging-Focused",
                "System Design",
                "Behavioral",
                "Technical Deep Dive"
            ]
            style = self.engine.random.choice(styles)

            db_subtopic_info = ""
            if category == "Database":
                db_history_count = sum(1 for h in (session_history or []) if h.get("category") == "Database")
                subtopics = ["Selection", "Schema Design", "Relationships", "Indexing", "Query Optimization", "Scalability", "Failure Recovery"]
                selected_subtopic = subtopics[db_history_count % len(subtopics)]
                
                db_subtopic_instructions = {
                    "Selection": "Focus on database selection: why this database was chosen, alternatives considered, requirements, and tradeoffs.",
                    "Schema Design": "Focus on schema design: how the schema was structured, entity design, and changing requirements.",
                    "Relationships": "Focus on modeling relationships: how foreign keys, relationships, or references are set up.",
                    "Indexing": "Focus on indexing strategies: what indexes were created and how slow queries are identified.",
                    "Query Optimization": "Focus on query optimization, caching, transactions, performance bottlenecks, or expensive queries.",
                    "Scalability": "Focus on database scaling: how to handle 10x traffic, 1 million users, sharding, or replication.",
                    "Failure Recovery": "Focus on database failure scenarios: crash recovery, corruption, failover, or backups."
                }
                db_subtopic_info = f"\nDATABASE SUBTOPIC FOCUS: {db_subtopic_instructions.get(selected_subtopic, '')}\n"

            system_prompt = (
                "You are a pragmatic, senior technical interviewer conducting a mock interview.\n\n"
                f"TARGET CATEGORY: {category}\n"
                f"INTERVIEW STYLE: {style}\n\n"
                f"{db_subtopic_info}"
                "ABSOLUTE RULES:\n"
                "1. Generate EXACTLY one question. No multiple questions.\n"
                "2. NEVER ask generic textbook questions (e.g., 'What is X?', 'Define Y').\n"
                "3. NEVER use, reference, or ask about personal details (names, emails, phone, addresses, URLs).\n"
                "4. NEVER repeat a question that has already been asked in this session.\n"
                "5. Every question MUST reference specific content from the candidate's resume or job description.\n"
                "6. NEVER answer or explain the question. You are strictly the interviewer.\n"
                "7. NEVER include debug tokens, index values, raw parser metadata, or prefixes like 'H:', '(0)', 'Q:'.\n"
                "8. Ensure the question sounds like a real technical interviewer who has read the candidate's resume.\n"
                "9. FORBIDDEN PATTERNS: Do NOT ask questions like 'How did your implementation of X work at a high level?' or ask about the 'architecture' or 'design' of HTML, CSS, or Git (e.g., never ask 'Explain HTML architecture' or 'Walk me through Git design').\n\n"
                f"TARGET ENTITY TYPE: {entity_type.upper()}\n"
                f"TARGET ENTITY: {json.dumps(target_entity, ensure_ascii=False)}\n"
                f"TARGET DIFFICULTY: {target_difficulty}/10\n\n"
                f"{difficulty_guidelines}\n"
                f"{specific_rules}\n"
                "OUTPUT FORMAT: Return ONLY valid JSON:\n"
                "{\n"
                '  "question": "the actual interview question",\n'
                '  "kind": "project_based|resume_based|jd_based|core_subject|behavioral|follow_up|trap|internship_based|experience_based",\n'
                '  "difficulty": 1-10,\n'
                '  "expected_signals": ["keyword1", "keyword2"],\n'
                '  "follow_up_seed": "short topic seed",\n'
                '  "trap": false,\n'
                '  "category": "the exact category matching TARGET CATEGORY",\n'
                '  "topic": "a unique semantic topic name like meshpay_architecture or jwt_authentication"\n'
                "}\n"
            )

            # Local question history
            q_history_list = [h.get("question", "").strip() for h in (session_history or []) if h.get("question")]
            if question_history:
                for q_str in question_history:
                    if q_str.strip() not in q_history_list:
                        q_history_list.append(q_str.strip())
            question_history_local = q_history_list

            user_payload = {
                "entity_type": entity_type,
                "target_entity": target_entity,
                "difficulty": target_difficulty,
                "resume_context": context_payload["resume_context"],
                "jd_context": context_payload["jd_context"],
                "question_history": question_history_local[-10:],
                "topic_history": context_payload["topic_history"][-10:],
                "answer_history": context_payload["answer_history"][-3:],
            }

            if attempt > 0:
                system_prompt += f"\nWARNING: Do NOT suggest any of these questions under any circumstances:\n" + "\n".join(f"- {q}" for q in question_history_local)

            generated_question = None
            if api_key:
                result = self._call_groq(system_prompt, user_payload, api_key, model, temperature=0.7 + 0.03 * attempt)
                if result:
                    try:
                        generated_question = self._parse_question_response(result, target_difficulty)
                        if generated_question and not generated_question.category:
                            generated_question.category = category
                    except Exception:
                        generated_question = None

            if generated_question:
                # Validate
                from services.adaptive_engine import resolve_topic_group
                is_valid, reject_reason = QuestionValidator.validate(
                    question_text=generated_question.prompt,
                    kind=generated_question.kind,
                    expected_signals=generated_question.expected_signals,
                    question_history=question_history_local,
                    topic_history=context_payload["topic_history"],
                    resume_profile=resume_profile,
                    category=generated_question.category,
                    topic=generated_question.topic,
                    job_description=job_description,
                    session_history=session_history,
                    current_phase=current_phase,
                    coding_mode_enabled=coding_mode_enabled,
                    entity_name=entity_name,
                    relaxation_stage=state_memory.get("relaxation_stage", 0),
                    entity_type=entity_type
                )
                
                if is_valid:
                    final_question = generated_question
                    break
                else:
                    last_reason = reject_reason
                    last_entity = entity_name
                    last_category = category
                    
                    # Print validation failure in the requested format
                    print("VALIDATION FAILURE\n")
                    print("REASON:")
                    print(reject_reason)
                    print("\nENTITY:")
                    print(entity_name)
                    print("\nTOPIC_GROUP:")
                    print(resolve_topic_group(generated_question.topic, entity_type=entity_type))
                    print("\nCATEGORY:")
                    print(category)
                    print()
                    
                    # Store in audit trail
                    if state_memory is not None:
                        trail = state_memory.setdefault("audit_trail", [])
                        trail.append({
                            "rejection_reason": reject_reason,
                            "entity": entity_name,
                            "category": category,
                            "topic_key": generated_question.topic
                        })
                        if len(trail) > 100:
                            state_memory["audit_trail"] = trail[-100:]
                    
                    # Add to exclusions
                    rejected_entities.add(entity_name)
                    rejected_categories.add(category)
            else:
                last_reason = "Groq generation failed / empty response"
                last_entity = entity_name
                last_category = category
                
                print("VALIDATION FAILURE\n")
                print("REASON:")
                print(last_reason)
                print("\nENTITY:")
                print(entity_name)
                print("\nTOPIC_GROUP:")
                print("Unknown")
                print("\nCATEGORY:")
                print(category)
                print()

                # Store in audit trail
                if state_memory is not None:
                    trail = state_memory.setdefault("audit_trail", [])
                    trail.append({
                        "rejection_reason": last_reason,
                        "entity": entity_name,
                        "category": category,
                        "topic_key": "Unknown"
                    })
                    if len(trail) > 100:
                        state_memory["audit_trail"] = trail[-100:]
                
                rejected_entities.add(entity_name)
                rejected_categories.add(category)

        # Print mandatory debug logging block before returning
        entity_name_final = final_question.follow_up_seed or "your project"
        entity_type_final = final_question.kind
        from services.adaptive_engine import resolve_topic_group
        tg_final = resolve_topic_group(final_question.topic, entity_type=entity_type_final)
        
        # Calculate usage counts
        clean_final_entity = self.engine._clean_entity_name(entity_name_final).strip().lower()
        entity_usage_count = 1 + sum(1 for h in (session_history or []) if self.engine._clean_entity_name(h.get("entity") or h.get("follow_up_seed") or "").strip().lower() == clean_final_entity)
        project_usage_count = entity_usage_count if entity_type_final in ("project", "project_based") else 0

        # Priority 8: Enhanced debug logging with recent history
        recent_3 = []
        for h in (session_history or [])[-3:]:
            recent_3.append({
                "entity": h.get("entity") or h.get("follow_up_seed") or "?",
                "category": h.get("category", "?"),
                "entity_type": h.get("entity_type", "?")
            })

        print("==================================================")
        print("PHASE:")
        print(current_phase)
        print("\nCATEGORY:")
        print(final_question.category)
        print("\nENTITY:")
        print(entity_name_final)
        print("\nENTITY_TYPE:")
        print(entity_type_final)
        print("\nTOPIC_KEY:")
        print(final_question.topic)
        print("\nTOPIC_GROUP:")
        print(tg_final)
        print("\nENTITY_USAGE_COUNT:")
        print(entity_usage_count)
        print("\nPROJECT_USAGE_COUNT:")
        print(project_usage_count)
        print("\nRECENT_3_HISTORY:")
        for i, rh in enumerate(recent_3):
            print(f"  [{i+1}] {rh['entity']} | {rh['category']} | {rh['entity_type']}")
        if entity_type_final == "internship" or "internship" in str(entity_type_final).lower():
            print("ENTITY")
            print("ENTITY_TYPE: internship")
            print("TEMPLATE_GROUP: internship")
        print("==================================================")

        # Store approved question in audit trail
        if state_memory is not None:
            trail = state_memory.setdefault("audit_trail", [])
            trail.append({
                "phase": current_phase,
                "category": final_question.category,
                "entity": entity_name_final,
                "entity_type": entity_type_final,
                "topic_key": final_question.topic,
                "validation_status": "fallback" if attempt == 9 else "approved"
            })
            if len(trail) > 100:
                state_memory["audit_trail"] = trail[-100:]

        return final_question

    def evaluate_answer(
        self,
        question: InterviewQuestion,
        answer: str,
        difficulty: int | None = None,
        session_history: list[dict] | None = None,
    ) -> AnswerEvaluation:
        return self.evaluator.score_answer(
            question=question.prompt,
            answer=answer,
            expected_signals=question.expected_signals,
            difficulty=difficulty or question.difficulty,
            trap_mode=question.trap,
            session_history=session_history,
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
            follow_up_question = self.generate_followup_question(
                question,
                answer,
                evaluation.score,
                resume_profile=resume_profile,
                job_description=job_description,
                session_history=session_history
            )
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

    def generate_followup_question(
        self,
        base_question: InterviewQuestion,
        answer: str,
        evaluation_score: int,
        resume_profile: dict | None = None,
        job_description: dict | None = None,
        session_history: list[dict] | None = None,
        question_history: list[str] | None = None,
        state_memory: dict | None = None,
    ) -> InterviewQuestion:
        """Generate a follow-up question using Groq, with dynamic difficulty adjustment and a 10-attempt fail-safe loop."""
        if not state_memory:
            cats = self.engine._extract_history_categories(session_history or [], resume_profile or {})
            state_memory = {
                "question_history": question_history or [h.get("question", "") for h in (session_history or [])],
                "topic_history": list(cats["topic_history"]),
                "covered_projects": list(cats["covered_projects"]),
                "covered_skills": list(cats["covered_skills"]),
                "covered_subjects": list(cats["covered_subjects"]),
                "covered_internships": list(cats["covered_internships"]),
                "covered_experience": list(cats["covered_experience"]),
                "covered_certificates": [],
            }

        # Ensure active phase and coding mode are in state memory
        history_len = len(session_history or [])
        current_phase = state_memory.get("current_phase")
        if not current_phase:
            from app import determine_active_phase
            current_phase, phase_index = determine_active_phase(history_len, is_followup=True)
            state_memory["current_phase"] = current_phase
            state_memory["phase_index"] = phase_index
        coding_mode_enabled = state_memory.get("coding_mode_enabled") or False

        # Exclusions for fail-safe loop
        rejected_entities = set()
        rejected_categories = set()

        last_reason = "Unknown validation failure"
        last_entity = "Unknown"
        last_category = "Unknown"

        context = self.create_context(resume_profile or {}, job_description, base_question.difficulty, session_history)

        # Determine difficulty adjustment instruction
        if evaluation_score <= 4:
            diff_instruction = (
                "The candidate STRUGGLED with the previous question (score <= 4/10). "
                "Ask a SIMPLER, more fundamental question on the same topic. "
                "Example: If they couldn't explain ACID, ask 'What is a database transaction?' "
                "Reduce the difficulty significantly."
            )
        elif evaluation_score <= 6:
            diff_instruction = (
                "The candidate gave a PARTIAL answer (score 5-6/10). "
                "Ask for specific implementation details or concrete examples. "
                "Keep the same difficulty level."
            )
        elif evaluation_score <= 8:
            diff_instruction = (
                "The candidate gave a GOOD answer (score 7-8/10). "
                "Increase complexity. Ask about tradeoffs, edge cases, or scaling challenges. "
                "Push them to demonstrate deeper understanding."
            )
        else:
            diff_instruction = (
                "The candidate gave an EXCELLENT answer (score 9-10/10). "
                "Ask an ADVANCED question: system design, optimization, scalability, "
                "architecture decisions, or real-world production scenarios. "
                "Challenge them at senior/staff engineer level."
            )

        # Base category and entity info from base_question
        category = base_question.category or "Behavioral + Project"
        entity_name = self.engine._clean_entity_name(base_question.follow_up_seed or self.engine._compact_phrase(base_question.prompt))
        entity_type = "project"
        if base_question.kind in ("project_based", "project"):
            entity_type = "project"
        elif base_question.kind in ("internship_based", "internship"):
            entity_type = "internship"
        elif base_question.kind in ("experience_based", "experience"):
            entity_type = "experience"
        elif base_question.kind == "skill":
            entity_type = "skill"
        elif base_question.kind == "company":
            entity_type = "company"
        elif base_question.kind == "certificate":
            entity_type = "certificate"

        # Force category compatibility for internship follow-ups
        if entity_type == "internship":
            from services.adaptive_engine import INTERNSHIP_CATEGORIES_BY_PHASE
            allowed_intern_cats = INTERNSHIP_CATEGORIES_BY_PHASE.get(current_phase, ["Behavioral + Project"])
            if category not in allowed_intern_cats:
                category = allowed_intern_cats[0]

        # Find initial target entity dictionary from resume_profile
        target_entity = None
        if resume_profile:
            for p in resume_profile.get("projects") or []:
                if self.engine._clean_entity_name(p.get("name") or "").lower() == entity_name.lower():
                    target_entity = p
                    break
            if not target_entity:
                for i in resume_profile.get("internships") or []:
                    if self.engine._clean_entity_name(i.get("company") or "").lower() == entity_name.lower():
                        target_entity = i
                        break
            if not target_entity:
                for e in resume_profile.get("experience") or []:
                    if self.engine._clean_entity_name(e.get("company") or "").lower() == entity_name.lower():
                        target_entity = e
                        break
        if not target_entity:
            target_entity = {"name": entity_name}

        MAX_GENERATION_ATTEMPTS = 10
        final_question = None

        # Build local question history list
        q_history_list = [h.get("question", "").strip() for h in (session_history or []) if h.get("question")]
        if base_question and base_question.prompt:
            q_history_list.append(base_question.prompt.strip())
        if question_history:
            for q_str in question_history:
                if q_str.strip() not in q_history_list:
                    q_history_list.append(q_str.strip())
        question_history_local = q_history_list
        for attempt in range(MAX_GENERATION_ATTEMPTS):
            if attempt == 9:
                # Log failure
                print("VALIDATION FAILURE")
                print(f"REASON: {last_reason}")
                print(f"ENTITY: {last_entity}")
                print(f"CATEGORY: {last_category}")
                print("\nFallback Triggered\n")

                if entity_type == "internship":
                    from services.adaptive_engine import INTERNSHIP_CATEGORIES_BY_PHASE
                    allowed_intern_cats = INTERNSHIP_CATEGORIES_BY_PHASE.get(current_phase, ["Behavioral + Project"])
                    fallback_category = allowed_intern_cats[0]
                    entity_type_final = "internship"
                else:
                    # Fetch fallback category
                    allowed_cats = list(PHASE_CATEGORIES.get(current_phase, ["Behavioral + Project"]))
                    if current_phase == "CODING":
                        allowed_cats = ["Coding"] if coding_mode_enabled else ["Theoretical DSA"]
                    fallback_category = allowed_cats[0]

                    # Find a valid fallback entity
                    fallback_payload = self.engine.select_topic_and_context(context, state_memory)
                    target_entity = fallback_payload["target_entity"]
                    entity_type_final = fallback_payload["entity_type"]

                final_question = self.engine.build_fallback_question(context, target_entity, entity_type_final, category=fallback_category)
                break

            # Switch logic:
            # Attempts 1-3: normal regeneration (exclusions = None)
            # Attempts 4-6: switch entity (exclude rejected entities)
            # Attempts 7-9: switch category (exclude rejected categories & entities)
            curr_category = category
            curr_entity_name = entity_name
            curr_entity_type = entity_type
            curr_target_entity = target_entity

            if attempt >= 3:
                if entity_type == "internship":
                    from services.adaptive_engine import INTERNSHIP_CATEGORIES_BY_PHASE
                    allowed_intern_cats = INTERNSHIP_CATEGORIES_BY_PHASE.get(current_phase, ["Behavioral + Project"])
                    # Filter out already rejected categories if any
                    valid_intern_cats = [c for c in allowed_intern_cats if c not in rejected_categories]
                    if not valid_intern_cats:
                        valid_intern_cats = allowed_intern_cats
                    curr_category = valid_intern_cats[0]
                    curr_entity_name = entity_name
                    curr_entity_type = "internship"
                    curr_target_entity = target_entity
                else:
                    exclude_ents = list(rejected_entities) if attempt >= 3 else None
                    exclude_cats = list(rejected_categories) if attempt >= 6 else None

                    context_payload = self.engine.select_topic_and_context(
                        context,
                        state_memory,
                        exclude_categories=exclude_cats,
                        exclude_entities=exclude_ents
                    )
                    curr_entity_type = context_payload["entity_type"]
                    curr_target_entity = context_payload["target_entity"]
                    curr_category = context_payload.get("category", "Behavioral + Project")

                    if isinstance(curr_target_entity, dict):
                        curr_entity_name = curr_target_entity.get("name") or curr_target_entity.get("company") or curr_target_entity.get("title") or "your project"
                    else:
                        curr_entity_name = str(curr_target_entity)
                    curr_entity_name = self.engine._clean_entity_name(curr_entity_name)

            # Build system prompt dynamically based on target entity and category
            api_key = os.environ.get("GROQ_API_KEY", "")
            model = os.environ.get("SECONDARY_LLM_MODEL", "grok-3-mini")

            # Determine category specific guidelines/rules
            specific_rules = ""
            if curr_entity_type == "project":
                specific_rules = (
                    "The selected target is a PROJECT. You may ask about technical architecture, system design, "
                    "data flow, tradeoffs, optimization, performance, caching, scalability, or distributed system designs.\n"
                    "STRICT PROJECT NAME RULE: You must ALWAYS refer to the project using its 'name' (e.g., 'Digital Mental Health and Psychological Support System'). "
                    "NEVER use its 'type' (e.g., 'Full Stack AI Web Application') as the primary interview entity/focus of the question. "
                    "For example, NEVER ask: 'Explain Full Stack AI Web Application', 'How did you implement Full Stack AI Web Application?', "
                    "or 'Walk me through the architecture of Full Stack AI Web Application'.\n"
                )
            elif curr_entity_type == "internship":
                specific_rules = (
                    "The selected target is an INTERNSHIP. You MUST focus exclusively on responsibilities, tasks, "
                    "technologies used, challenges, impact, mentorship, team collaboration, or learning.\n"
                    "STRICTLY FORBIDDEN: Do NOT ask about technical architecture, system design, or scaling for this internship company.\n"
                )
            elif curr_entity_type == "experience":
                specific_rules = (
                    "The selected target is work EXPERIENCE. You MUST focus on ownership, leadership, debugging, "
                    "technical decisions, impact, project contributions, or team collaboration.\n"
                    "STRICTLY FORBIDDEN: Do NOT ask about technical architecture, system design, or scaling for this employer.\n"
                )
            elif curr_entity_type == "skill":
                specific_rules = (
                    "The selected target is a general SKILL / tool. You MUST focus on practical usage, implementation details, "
                    "debugging, project context, or best practice questions.\n"
                    "STRICTLY FORBIDDEN: Do NOT ask about the 'architecture' or 'design' of the skill itself (e.g., NEVER ask about HTML/CSS/Git architecture).\n"
                )
            elif curr_entity_type == "subject":
                specific_rules = (
                    f"The selected target is a core CS SUBJECT: {curr_target_entity}. Ask a contextual CS fundamentals question "
                    "relevant to the candidate's resume/JD. Avoid generic textbook definitions.\n"
                )
            elif curr_entity_type == "behavioral":
                specific_rules = (
                    "The selected target is BEHAVIORAL. Ask a situational question grounded in the candidate's projects "
                    "or work experience. Focus on deadline handling, team collaboration, conflicts, or learnings.\n"
                )

            # Database category specific rules based on entity_type
            if curr_category == "Database":
                if curr_entity_type == "project":
                    specific_rules += (
                        "\nDATABASE CATEGORY RULES FOR PROJECT ENTITIES:\n"
                        f"The target database entity is a PROJECT: {curr_entity_name}. Focus the question on the database aspects of this project.\n"
                        "Allowed topics: schema design, relationship modeling, indexing strategy, query bottlenecks, or handling traffic scalability.\n"
                        f"Example: 'How did you design the database schema for {curr_entity_name}?' or 'What indexing strategy did you use in {curr_entity_name}?'\n"
                        "STRICTLY FORBIDDEN: Do NOT ask database selection templates that treat the project name as a database product itself.\n"
                    )
                elif curr_entity_type == "skill":
                    specific_rules += (
                        "\nDATABASE CATEGORY RULES FOR DATABASE TECHNOLOGY/SKILL ENTITIES:\n"
                        f"The target database entity is a database technology/skill: {curr_entity_name}.\n"
                        "Allowed topics: why you chose it over alternatives, advantages, limitations, query optimization, indexing, or scaling the database technology.\n"
                        "STRICTLY FORBIDDEN: Do NOT treat the database technology itself as a project. "
                        f"For example, NEVER ask: 'Why did you choose the database design for {curr_entity_name}?', "
                        f"'Explain the database architecture of {curr_entity_name}', or similar generic patterns.\n"
                    )

            # Enforce Coding Safety instructions inside prompt
            if curr_category == "Theoretical DSA" or (current_phase == "CODING" and not coding_mode_enabled):
                specific_rules += (
                    "\nCODING SAFETY MODE IS ACTIVE:\n"
                    "You MUST only ask theoretical DSA, complexity analysis, algorithm reasoning, or debugging questions.\n"
                    "STRICTLY FORBIDDEN: Do NOT ask the candidate to write code or implement a function. Focus only on conceptual "
                    "explanations and tradeoffs.\n"
                )

            styles = [
                "Analytical",
                "Practical",
                "Architecture-Focused",
                "Debugging-Focused",
                "System Design",
                "Behavioral",
                "Technical Deep Dive"
            ]
            style = self.engine.random.choice(styles)

            db_subtopic_info = ""
            if curr_category == "Database":
                db_history_count = sum(1 for h in (session_history or []) if h.get("category") == "Database")
                subtopics = ["Selection", "Schema Design", "Relationships", "Indexing", "Query Optimization", "Scalability", "Failure Recovery"]
                selected_subtopic = subtopics[db_history_count % len(subtopics)]

                db_subtopic_instructions = {
                    "Selection": "Focus on database selection: why this database was chosen, alternatives considered, requirements, and tradeoffs.",
                    "Schema Design": "Focus on schema design: how the schema was structured, entity design, and changing requirements.",
                    "Relationships": "Focus on modeling relationships: how foreign keys, relationships, or references are set up.",
                    "Indexing": "Focus on indexing strategies: what indexes were created and how slow queries are identified.",
                    "Query Optimization": "Focus on query optimization, caching, transactions, performance bottlenecks, or expensive queries.",
                    "Scalability": "Focus on database scaling: how to handle 10x traffic, 1 million users, sharding, or replication.",
                    "Failure Recovery": "Focus on database failure scenarios: crash recovery, corruption, failover, or backups."
                }
                db_subtopic_info = f"\nDATABASE SUBTOPIC FOCUS: {db_subtopic_instructions.get(selected_subtopic, '')}\n"

            system_prompt = (
                "You are a pragmatic, senior technical interviewer. Generate EXACTLY one follow-up question.\n\n"
                f"TARGET CATEGORY: {curr_category}\n"
                f"INTERVIEW STYLE: {style}\n\n"
                f"{db_subtopic_info}"
                "RULES:\n"
                "1. NEVER ask generic questions. Always reference the candidate's specific context.\n"
                "2. NEVER repeat the previous question or ask about personal details.\n"
                "3. Seamlessly continue from their previous answer.\n"
                "4. STRICT DIVISION: Only generate technical architecture, scaling architecture, system design, or internal design questions for projects in the 'projects' list. NEVER ask technical architecture or scaling questions for employers/companies/organizations listed in internships or experience. For companies/employers, generate questions about responsibilities, tasks, contributions, technologies used, challenges, or team collaboration.\n"
                "5. STRICT PROJECT NAME VALIDATION: Never generate questions asking about dates, months, years, or date ranges as if they were project names (e.g., NEVER ask 'Walk me through the technical architecture of Oct 2025' or 'Explain the system design of 2023 - 2024'). Date entities must not be treated as projects.\n"
                "6. STRICT PROJECT NAME/TYPE SEPARATION: Project-based questions must always refer to the project using its 'name' (e.g. 'Digital Mental Health and Psychological Support System'). Never refer to the project using its 'type' (e.g. 'Full Stack AI Web Application') as if it were the project's name. Never ask: 'Explain Full Stack AI Web Application', 'How did you implement Full Stack AI Web Application?', or similar.\n"
                "7. FOLLOW-UP SPECIFIC RULES:\n"
                "   - Design the follow-up question directly based on the candidate's previous answer, answer quality, answer completeness, detected technologies, detected challenges, detected tradeoffs, detected bottlenecks, detected impact, detected architecture discussion, or detected scalability discussion.\n"
                "   - NEVER use generic fallback prompts like 'How did your implementation of X work at a high level?'. Probe specific technical details, components, or tradeoffs they mentioned.\n"
                "   - FORBIDDEN PATTERNS: Do NOT ask questions like 'How did your implementation of X work at a high level?' or ask about the 'architecture' or 'design' of HTML, CSS, or Git (e.g., never ask 'Explain HTML architecture' or 'Walk me through Git design').\n"
                f"8. DIFFICULTY ADJUSTMENT: {diff_instruction}\n"
                "9. Always ask exactly ONE question. Do not provide answers or explanations.\n\n"
                f"TARGET ENTITY TYPE: {curr_entity_type.upper()}\n"
                f"TARGET ENTITY: {json.dumps(curr_target_entity, ensure_ascii=False)}\n\n"
                f"{specific_rules}\n"
                "OUTPUT FORMAT: Return ONLY valid JSON:\n"
                "{\n"
                '  "question": "the follow-up interview question",\n'
                '  "kind": "follow_up",\n'
                '  "difficulty": 1-10,\n'
                '  "expected_signals": ["keyword1", "keyword2"],\n'
                '  "follow_up_seed": "short topic seed",\n'
                '  "trap": false,\n'
                '  "category": "the exact category matching TARGET CATEGORY",\n'
                '  "topic": "a unique semantic topic name like meshpay_architecture or jwt_authentication"\n'
                "}\n"
            )

            sanitized_resume = _sanitize_profile(resume_profile) if resume_profile else None
            sanitized_jd = _sanitize_profile(job_description) if job_description else None

            payload = {
                "resume_profile": sanitized_resume or {},
                "job_description": sanitized_jd or {},
                "session_history": (session_history or [])[-3:],
                "base_question": {
                    "prompt": base_question.prompt,
                    "kind": base_question.kind,
                    "difficulty": base_question.difficulty,
                },
                "answer": answer,
                "evaluation_score": evaluation_score,
                "question_history": question_history_local[-10:],
            }

            if attempt > 0:
                system_prompt += f"\nWARNING: Do NOT suggest any of these questions under any circumstances:\n" + "\n".join(f"- {q}" for q in question_history_local)

            generated_question = None
            if api_key:
                result = self._call_groq(system_prompt, payload, api_key, model, temperature=0.6 + 0.05 * attempt)
                if result:
                    try:
                        generated_question = self._parse_question_response(result, base_question.difficulty)
                        if generated_question:
                            generated_question.kind = "follow_up"
                            if not generated_question.category:
                                generated_question.category = curr_category
                    except Exception:
                        generated_question = None

            if generated_question:
                # Validate
                from services.adaptive_engine import resolve_topic_group
                is_valid, reject_reason = QuestionValidator.validate(
                    question_text=generated_question.prompt,
                    kind=generated_question.kind,
                    expected_signals=generated_question.expected_signals,
                    question_history=question_history_local,
                    topic_history=[],
                    resume_profile=resume_profile or {},
                    category=generated_question.category,
                    topic=generated_question.topic,
                    job_description=job_description,
                    session_history=session_history,
                    current_phase=current_phase,
                    coding_mode_enabled=coding_mode_enabled,
                    entity_name=curr_entity_name,
                    relaxation_stage=state_memory.get("relaxation_stage", 0),
                    entity_type=curr_entity_type
                )

                if is_valid:
                    final_question = generated_question
                    break
                else:
                    last_reason = reject_reason
                    last_entity = curr_entity_name
                    last_category = curr_category

                    # Print validation failure in the requested format
                    print("VALIDATION FAILURE\n")
                    print("REASON:")
                    print(reject_reason)
                    print("\nENTITY:")
                    print(curr_entity_name)
                    print("\nTOPIC_GROUP:")
                    print(resolve_topic_group(generated_question.topic, entity_type=curr_entity_type))
                    print("\nCATEGORY:")
                    print(curr_category)
                    print()

                    # Store in audit trail
                    if state_memory is not None:
                        trail = state_memory.setdefault("audit_trail", [])
                        trail.append({
                            "rejection_reason": reject_reason,
                            "entity": curr_entity_name,
                            "category": curr_category,
                            "topic_key": generated_question.topic
                        })
                        if len(trail) > 100:
                            state_memory["audit_trail"] = trail[-100:]

                    # Add to exclusions
                    rejected_entities.add(curr_entity_name)
                    rejected_categories.add(curr_category)
            else:
                last_reason = "Groq generation failed / empty response"
                last_entity = curr_entity_name
                last_category = curr_category

                print("VALIDATION FAILURE\n")
                print("REASON:")
                print(last_reason)
                print("\nENTITY:")
                print(curr_entity_name)
                print("\nTOPIC_GROUP:")
                print("Unknown")
                print("\nCATEGORY:")
                print(curr_category)
                print()

                # Store in audit trail
                if state_memory is not None:
                    trail = state_memory.setdefault("audit_trail", [])
                    trail.append({
                        "rejection_reason": last_reason,
                        "entity": curr_entity_name,
                        "category": curr_category,
                        "topic_key": "Unknown"
                    })
                    if len(trail) > 100:
                        state_memory["audit_trail"] = trail[-100:]

                rejected_entities.add(curr_entity_name)
                rejected_categories.add(curr_category)

        if final_question is None:
            # Fallback
            # Log failure
            print("VALIDATION FAILURE\n")
            print("REASON:")
            print(last_reason)
            print("\nENTITY:")
            print(last_entity)
            print("\nTOPIC_GROUP:")
            print("Unknown")
            print("\nCATEGORY:")
            print(last_category)
            print()
            print("\nFallback Triggered\n")

            # Store in audit trail
            if state_memory is not None:
                trail = state_memory.setdefault("audit_trail", [])
                trail.append({
                    "rejection_reason": last_reason,
                    "entity": last_entity,
                    "category": last_category,
                    "topic_key": "Unknown"
                })
                if len(trail) > 100:
                    state_memory["audit_trail"] = trail[-100:]

            # Fetch fallback category
            allowed_cats = list(PHASE_CATEGORIES.get(current_phase, ["Behavioral + Project"]))
            if current_phase == "CODING":
                allowed_cats = ["Coding"] if coding_mode_enabled else ["Theoretical DSA"]
            fallback_category = allowed_cats[0]

            fallback_payload = self.engine.select_topic_and_context(
                context, state_memory,
                exclude_categories=list(rejected_categories) if rejected_categories else None,
                exclude_entities=list(rejected_entities) if rejected_entities else None
            )
            final_question = self.engine.build_fallback_question(
                context,
                fallback_payload["target_entity"],
                fallback_payload["entity_type"],
                category=fallback_category
            )

        # Print mandatory debug logging block before returning
        entity_name_final = final_question.follow_up_seed or "your project"
        entity_type_final = final_question.kind
        from services.adaptive_engine import resolve_topic_group
        tg_final = resolve_topic_group(final_question.topic, entity_type=entity_type_final)
        
        # Calculate usage counts
        clean_final_entity = self.engine._clean_entity_name(entity_name_final).strip().lower()
        entity_usage_count = 1 + sum(1 for h in (session_history or []) if self.engine._clean_entity_name(h.get("entity") or h.get("follow_up_seed") or "").strip().lower() == clean_final_entity)
        project_usage_count = entity_usage_count if entity_type_final in ("project", "project_based") else 0

        # Priority 8: Enhanced debug logging with recent history
        recent_3 = []
        for h in (session_history or [])[-3:]:
            recent_3.append({
                "entity": h.get("entity") or h.get("follow_up_seed") or "?",
                "category": h.get("category", "?"),
                "entity_type": h.get("entity_type", "?")
            })

        print("==================================================")
        print("PHASE:")
        print(current_phase)
        print("\nCATEGORY:")
        print(final_question.category)
        print("\nENTITY:")
        print(entity_name_final)
        print("\nENTITY_TYPE:")
        print(entity_type_final)
        print("\nTOPIC_KEY:")
        print(final_question.topic)
        print("\nTOPIC_GROUP:")
        print(tg_final)
        print("\nENTITY_USAGE_COUNT:")
        print(entity_usage_count)
        print("\nPROJECT_USAGE_COUNT:")
        print(project_usage_count)
        print("\nRECENT_3_HISTORY:")
        for i, rh in enumerate(recent_3):
            print(f"  [{i+1}] {rh['entity']} | {rh['category']} | {rh['entity_type']}")
        if entity_type_final == "internship" or "internship" in str(entity_type_final).lower():
            print("ENTITY")
            print("ENTITY_TYPE: internship")
            print("TEMPLATE_GROUP: internship")
        print("==================================================")

        # Store approved question in audit trail
        if state_memory is not None:
            trail = state_memory.setdefault("audit_trail", [])
            trail.append({
                "phase": current_phase,
                "category": final_question.category,
                "entity": entity_name_final,
                "entity_type": entity_type_final,
                "topic_key": final_question.topic,
                "validation_status": "approved"
            })
            if len(trail) > 100:
                state_memory["audit_trail"] = trail[-100:]

        return final_question

    def score_text_answer(self, question_text: str, answer: str, expected_signals: list[str] | None = None, difficulty: int = 5, trap_mode: bool = False, session_history: list[dict] | None = None) -> dict:
        evaluation = self.evaluator.score_answer(question_text, answer, expected_signals, difficulty, trap_mode, session_history)
        return {
            "score": evaluation.score,
            "reasoning": evaluation.reasoning,
            "strengths": evaluation.strengths,
            "gaps": evaluation.gaps,
            "follow_up": evaluation.follow_up,
            "red_flags": evaluation.red_flags,
            "feedback": self.evaluator.generate_feedback(evaluation, question_text),
            "relevance": evaluation.relevance,
            "keyword_match": evaluation.keyword_match,
            "answer_length": evaluation.answer_length,
            "technical_accuracy": evaluation.technical_accuracy,
            "depth": evaluation.depth,
            "reasoning_score": evaluation.reasoning_score,
            "communication": evaluation.communication,
            "repeated_answer_detected": evaluation.repeated_answer_detected,
        }


    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_groq(self, system_prompt: str, user_payload: dict, api_key: str, model: str, temperature: float = 0.7) -> str | None:
        """Unified Groq API caller that tries multiple endpoint formats."""
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
                    json={"model": model, "input": prompt, "temperature": temperature, "max_output_tokens": 512},
                    timeout=12,
                )
                resp.raise_for_status()
                body = resp.json()

                text_candidates = []
                if isinstance(body, dict):
                    if "output" in body and isinstance(body["output"], str):
                        text_candidates.append(body["output"])
                    if "outputs" in body and isinstance(body["outputs"], list):
                        for o in body["outputs"]:
                            if isinstance(o, dict) and "content" in o:
                                if isinstance(o["content"], list):
                                    for c in o["content"]:
                                        if isinstance(c, dict) and c.get("type") == "output_text":
                                            text_candidates.append(c.get("text", ""))
                                else:
                                    text_candidates.append(str(o.get("content", "")))
                    if "choices" in body and isinstance(body["choices"], list):
                        for choice in body["choices"]:
                            if isinstance(choice, dict):
                                if "message" in choice and isinstance(choice["message"], dict):
                                    text_candidates.append(choice["message"].get("content", ""))
                                text_candidates.append(choice.get("text", ""))

                if not text_candidates:
                    text_candidates.append(resp.text)

                for txt in text_candidates:
                    if txt and isinstance(txt, str):
                        txt = txt.strip()
                        if txt.startswith("```") and txt.endswith("```"):
                            parts = txt.split("\n", 1)
                            if len(parts) > 1:
                                txt = parts[1].rsplit("\n", 1)[0]
                        return txt

            except Exception:
                continue

        return None

    def _parse_question_response(self, text: str, fallback_difficulty: int) -> InterviewQuestion:
        """Parse a Groq response text into an InterviewQuestion."""
        try:
            obj = json.loads(text)
            question_text = str(obj.get("question") or obj.get("prompt") or obj.get("text", "")).strip()
            
            # Scrub any raw metadata prefixes/suffixes the LLM might have hallucinated
            question_text = re.sub(r"^(?:H:|Q:|Question:|Q\d+:|H\d+:)\s*", "", question_text, flags=re.IGNORECASE)
            question_text = re.sub(r"\(\d+\)$", "", question_text).strip()
            
            kind = str(obj.get("kind", "resume_based"))
            difficulty_val = int(obj.get("difficulty", max(1, min(10, fallback_difficulty))))
            expected = list(obj.get("expected_signals", [])) or []
            follow_seed = str(obj.get("follow_up_seed", ""))
            trap_flag = bool(obj.get("trap", False))
            category = str(obj.get("category", "")).strip()
            topic = str(obj.get("topic", "")).strip()

            if not topic:
                name_part = follow_seed or (expected[0] if expected else "general")
                entity_slug = re.sub(r'[^a-z0-9_]', '', name_part.lower().replace(" ", "_"))
                category_slug = re.sub(r'[^a-z0-9_]', '', category.lower().replace(" ", "_").replace("+", "_"))
                topic = f"{entity_slug}_{category_slug}"

            return InterviewQuestion(
                prompt=question_text,
                kind=kind,
                difficulty=max(1, min(10, difficulty_val)),
                expected_signals=[str(s) for s in expected],
                follow_up_seed=follow_seed,
                trap=trap_flag,
                category=category,
                topic=topic,
            )
        except Exception:
            if text:
                return InterviewQuestion(
                    prompt=text,
                    kind="resume_based",
                    difficulty=max(1, min(10, fallback_difficulty)),
                    expected_signals=[],
                    follow_up_seed="",
                    trap=False,
                    category="",
                    topic="general",
                )
            raise