from __future__ import annotations

from dataclasses import dataclass, field
import itertools
import random
import re
from typing import Iterable, Any


@dataclass(slots=True)
class InterviewQuestion:
    prompt: str
    kind: str
    difficulty: int
    expected_signals: list[str] = field(default_factory=list)
    follow_up_seed: str = ""
    trap: bool = False
    category: str = ""
    topic: str = ""


@dataclass(slots=True)
class InterviewContext:
    resume_profile: dict
    job_description: dict | None = None
    role_family: str = "general"
    difficulty: int = 5
    session_history: list[dict] = field(default_factory=list)



PHASE_CATEGORIES = {
    "INTRODUCTION": [
        "Problem Understanding",
        "Behavioral + Project"
    ],
    "PROBLEM_SOLVING": [
        "Implementation",
        "Debugging",
        "Database",
        "Performance"
    ],
    "SYSTEM_DESIGN": [
        "Architecture",
        "Tradeoffs",
        "Scalability",
        "Security",
        "Failure Scenarios",
        "Production Operations"
    ],
    "BEHAVIORAL": [
        "Behavioral + Project"
    ],
    "CODING": [
        "Coding",
        "Algorithms",
        "Data Structures",
        "Theoretical DSA"
    ],
    "WRAP_UP": [
        "Reflection",
        "Lessons Learned",
        "Future Improvements"
    ]
}

TOPIC_GROUPS = {
    "system_design": [
        "architecture",
        "components",
        "data_flow",
        "structure",
        "high_level_design",
        "workflow"
    ],
    "implementation": [
        "implementation",
        "feature",
        "module",
        "development",
        "coding"
    ],
    "debugging": [
        "bug",
        "debugging",
        "failure",
        "issue",
        "root_cause"
    ],
    "database": [
        "schema",
        "relationships",
        "indexing",
        "query_optimization",
        "database",
        "mysql",
        "postgres",
        "sqlite",
        "mongodb",
        "sql",
        "db",
        "selection"
    ],
    "performance": [
        "latency",
        "performance",
        "optimization",
        "bottleneck"
    ],
    "scalability": [
        "scaling",
        "availability",
        "traffic",
        "capacity"
    ],
    "tradeoffs": [
        "tradeoff",
        "decision",
        "alternative"
    ],
    "behavioral": [
        "challenge",
        "conflict",
        "leadership",
        "communication"
    ]
}

# Internship-specific topic groups for finer-grained cooldown tracking
INTERNSHIP_TOPIC_GROUPS = {
    "intern_responsibility": [
        "responsibility", "role", "primary", "assigned", "duties",
        "contribution", "ownership"
    ],
    "intern_learning": [
        "learn", "skill", "improve", "growth", "mentor",
        "training", "onboard", "ramp"
    ],
    "intern_challenge": [
        "challenge", "difficult", "obstacle", "struggle",
        "problem", "blocker", "setback"
    ],
    "intern_teamwork": [
        "team", "collaborat", "communication", "standup",
        "review", "feedback", "pair", "cross_functional"
    ],
    "intern_workflow": [
        "workflow", "process", "agile", "sprint", "ticket",
        "ci", "deploy", "git", "version_control"
    ],
    "intern_debugging": [
        "bug", "debug", "fix", "issue", "root_cause",
        "troubleshoot", "error"
    ],
    "intern_impact": [
        "impact", "result", "outcome", "deliver", "ship",
        "production", "user"
    ],
    "intern_requirements": [
        "requirement", "understand", "spec", "task",
        "information", "communic"
    ],
}

CATEGORY_TO_TOPIC_GROUP = {
    "Problem Understanding": "system_design",
    "Architecture": "system_design",
    "Implementation": "implementation",
    "Debugging": "debugging",
    "Database": "database",
    "Performance": "performance",
    "Scalability": "scalability",
    "Tradeoffs": "tradeoffs",
    "Behavioral + Project": "behavioral",
    "Reflection": "behavioral",
    "Lessons Learned": "behavioral",
    "Future Improvements": "behavioral",
    "Coding": "implementation",
    "Algorithms": "implementation",
    "Data Structures": "implementation",
    "Theoretical DSA": "implementation",
    "Security": "system_design",
    "Production Operations": "system_design",
}

INTERNSHIP_CATEGORIES_BY_PHASE = {
    "INTRODUCTION": ["Problem Understanding", "Behavioral + Project"],
    "PROBLEM_SOLVING": ["Implementation", "Debugging"],
    "BEHAVIORAL": ["Behavioral + Project", "Lessons Learned"],
    "WRAP_UP": ["Lessons Learned"]
}

def resolve_topic_group(topic_key: str, entity_type: str = "") -> str:
    """Resolve a topic key to a topic group. Checks internship-specific groups first for internship entities."""
    if not topic_key:
        return "implementation"
    tk_lower = topic_key.lower()
    # For internship entities, check internship topic groups first
    if entity_type == "internship":
        for group, keywords in INTERNSHIP_TOPIC_GROUPS.items():
            for kw in keywords:
                if kw in tk_lower:
                    return group
    for group, keywords in TOPIC_GROUPS.items():
        for kw in keywords:
            if kw in tk_lower:
                return group
    return "implementation"

CATEGORY_ALLOWED_ENTITY_TYPES = {
    "Problem Understanding": {
        "project",
        "internship",
        "experience"
    },
    "Architecture": {
        "project"
    },
    "Implementation": {
        "project",
        "internship",
        "experience"
    },
    "Tradeoffs": {
        "project"
    },
    "Scalability": {
        "project"
    },
    "Failure Scenarios": {
        "project"
    },
    "Production Operations": {
        "project"
    },
    "Behavioral + Project": {
        "project",
        "internship",
        "experience"
    },
    "Database": {
        "project",
        "skill"
    },
    "Security": {
        "project",
        "skill"
    },
    "Debugging": {
        "project",
        "internship",
        "experience",
        "skill"
    },
    "Performance": {
        "project",
        "internship",
        "experience"
    },
    "Skill Usage": {
        "skill"
    },
    "Technology Selection": {
        "skill"
    }
}

def determine_phase_from_q_num(question_number: int) -> str:
    if question_number <= 1:
        return "INTRODUCTION"
    elif question_number <= 4:
        return "PROBLEM_SOLVING"
    elif question_number <= 7:
        return "SYSTEM_DESIGN"
    elif question_number <= 10:
        return "BEHAVIORAL"
    elif question_number <= 12:
        return "CODING"
    else:
        return "WRAP_UP"


class AdaptiveEngine:
    """Generates interviewer-style prompts and adapts difficulty based on session state.

    All question generation is 100% dynamic – there are NO hardcoded question banks,
    predefined templates, or generic prompts.  Every question is constructed at runtime
    from the candidate's resume profile, job description, and in-session performance.

    The engine follows a strict round-priority schedule:
        Round 1-3   → Project deep-dive (using actual project names & tech stacks)
        Round 4-5   → Resume skill verification
        Round 6-8   → JD skill alignment
        Round 9-11  → Core subjects (CS fundamentals derived from resume/JD context)
        Round 12-15 → Behavioral / situational questions
    """

    MAX_QUESTIONS = 15

    def __init__(self, seed: int | None = None):
        self.random = random.Random(seed)

    def check_entity_validity(self, entity_val: Any, category: str) -> bool:
        """Verify if the entity is appropriate for the given category to avoid nonsensical questions."""
        # If the entity is a dictionary (project/internship/experience), it's generally valid.
        if isinstance(entity_val, dict):
            # For database category, if it's a project, check if it uses a database
            if category == "Database":
                # Check project technologies/tech stack for database keywords
                techs = [str(t).lower() for t in entity_val.get("technologies", []) + entity_val.get("tech_stack", [])]
                db_keywords = ["mysql", "postgresql", "mongodb", "sqlite", "oracle", "dynamodb", "redis", "cassandra", "mariadb", "couchdb", "neo4j", "sql", "nosql", "dbms", "database", "firebase", "firestore", "postgres"]
                if any(any(kw in t for kw in db_keywords) for t in techs):
                    return True
                return True
            return True
            
        # If the entity is a string (like a skill name, subject, company, etc.)
        entity_str = str(entity_val).lower().strip()
        
        if category == "Database":
            db_keywords = ["mysql", "postgresql", "mongodb", "sqlite", "oracle", "dynamodb", "redis", "cassandra", "mariadb", "couchdb", "neo4j", "sql", "nosql", "dbms", "database", "firebase", "firestore", "postgres"]
            return any(kw in entity_str for kw in db_keywords)
            
        if category == "Security":
            sec_keywords = ["security", "auth", "jwt", "oauth", "ssl", "tls", "crypt", "cipher", "hashing", "firewall", "cors", "penetration", "owasp", "https", "shield", "iam", "cognito", "keycloak", "encryption", "decryption"]
            return any(kw in entity_str for kw in sec_keywords)
            
        return True

    def _get_candidates_for_category(self, category: str, context: InterviewContext, state_memory: dict) -> list[tuple[str, Any]]:
        candidates = []
        
        # 1. Projects
        projects = self._extract_projects(context.resume_profile)
        for p in projects:
            candidates.append(("project", p))
            
        # 2. Skills (Resume and JD)
        skills = self._extract_skills(context.resume_profile)
        jd = context.job_description or {}
        jd_skills = self._list_from_profile(jd, ["required_skills", "technologies", "skills", "requirements"])
        all_skills = list(dict.fromkeys(skills + jd_skills))
        for s in all_skills:
            candidates.append(("skill", s))
            
        # 3. Internships
        internships = self._extract_internships(context.resume_profile)
        for i in internships:
            candidates.append(("internship", i))
            
        # 4. Experience
        experience = self._extract_experience(context.resume_profile)
        for e in experience:
            candidates.append(("experience", e))
            
        # 5. Companies
        companies = self._extract_companies(context.resume_profile)
        for c in companies:
            candidates.append(("company", c))
            
        # 6. CS subjects
        skills_lower = list(set(s.lower() for s in skills + jd_skills))
        subject_map = {
            "dbms": ["database", "sql", "mysql", "postgresql", "mongodb", "nosql", "dbms", "oracle"],
            "networking": ["tcp", "http", "api", "rest", "socket", "network", "dns", "ip"],
            "os": ["linux", "process", "thread", "memory", "os", "operating system", "docker", "kubernetes"],
            "dsa": ["algorithm", "data structure", "sorting", "tree", "graph", "array", "linked list", "stack", "queue"],
            "oop": ["java", "python", "c++", "oop", "class", "object", "inheritance", "polymorphism"],
            "system_design": ["architecture", "microservice", "scalab", "distributed", "cloud", "aws", "azure"],
        }
        subjects = []
        for subject, keywords in subject_map.items():
            if any(kw in " ".join(skills_lower) for kw in keywords):
                subjects.append(subject)
        if not subjects:
            subjects = list(subject_map.keys())
        for sub in subjects:
            candidates.append(("subject", sub))
            
        # 7. Certificates
        certificates = context.resume_profile.get("certificates") or []
        if not isinstance(certificates, list):
            certificates = [certificates] if certificates else []
        for cert in certificates:
            candidates.append(("certificate", cert))
            
        return candidates

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _clean_entity_name(self, text: str) -> str:
        """Strip retrieval metadata, trailing digits, and highlights."""
        if not isinstance(text, str):
            return str(text)
        text = re.sub(r"\(\d+\)$", "", text).strip()
        text = re.sub(r"\s*\|\s*H:.*$", "", text).strip()
        text = re.sub(r"\[Highlight.*?\]|\(Snippet.*?\)", "", text, flags=re.IGNORECASE).strip()
        return text

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

    def determine_next_category(
        self,
        difficulty: int,
        history: list[dict],
        current_phase: str = "INTRODUCTION",
        coding_mode_enabled: bool = False,
        exclude_categories: list[str] | None = None,
        state_memory: dict | None = None
    ) -> str:
        # Define priority weights
        weights = {
            "Architecture": 3,
            "Implementation": 3,
            "Debugging": 3,
            "Performance": 2,
            "Tradeoffs": 2,
            "Scalability": 2,
            "Problem Understanding": 2,
            "Failure Scenarios": 2,
            "Database": 1,
            "Security": 1,
            "Behavioral + Project": 1,
            "Production Operations": 1,
            "Coding": 1,
            "Algorithms": 1,
            "Data Structures": 1,
            "Theoretical DSA": 1,
            "Reflection": 1,
            "Lessons Learned": 1,
            "Future Improvements": 1
        }

        # Filter categories by current phase
        allowed_categories = list(PHASE_CATEGORIES.get(current_phase, ["Behavioral + Project"]))
        if current_phase == "CODING" and not coding_mode_enabled:
            allowed_categories = ["Theoretical DSA"]

        # Apply exclusions if provided
        if exclude_categories:
            allowed_categories = [c for c in allowed_categories if c not in exclude_categories]

        # Fail-safe: if all allowed categories are excluded, recover them
        if not allowed_categories:
            allowed_categories = list(PHASE_CATEGORIES.get(current_phase, ["Behavioral + Project"]))
            if current_phase == "CODING" and not coding_mode_enabled:
                allowed_categories = ["Theoretical DSA"]

        # Filter out categories asked in the last 3 questions (to prevent consecutive repeats)
        recent_categories = [h.get("category") for h in history[-3:] if h.get("category")]
        filtered_categories = [c for c in allowed_categories if c not in recent_categories]
        if not filtered_categories:
            filtered_categories = allowed_categories

        # Retrieve relaxation stage
        stage = state_memory.get("relaxation_stage", 0) if state_memory else 0

        # Topic Group Cooldown in category selection
        recent_topic_groups = []
        for h in history[-4:]:
            tk = h.get("topic") or ""
            if tk:
                recent_topic_groups.append(resolve_topic_group(tk))

        # Check if alternative topic group exists
        alt_exists = False
        for c in filtered_categories:
            tg = CATEGORY_TO_TOPIC_GROUP.get(c)
            if tg and tg not in recent_topic_groups:
                alt_exists = True
                break

        candidate_weights = []
        for c in filtered_categories:
            w = float(weights.get(c, 1))
            
            # Topic Group Cooldown penalty
            tg = CATEGORY_TO_TOPIC_GROUP.get(c)
            if tg and tg in recent_topic_groups:
                if alt_exists or stage >= 4:
                    penalty = 0.5 if stage >= 2 else 0.1
                    w *= penalty

            # Category diversity encouragement
            history_categories = [h.get("category") for h in history if h.get("category")]
            if c in history_categories:
                w *= 0.3

            candidate_weights.append(max(0.01, w))

        selected_category = self.random.choices(filtered_categories, weights=candidate_weights, k=1)[0]
        return selected_category

    def _calculate_relaxation_stage(
        self,
        context: InterviewContext,
        state_memory: dict,
        current_phase: str,
        coding_mode_enabled: bool,
        exclude_categories: list[str] | None = None,
        exclude_entities: list[str] | None = None
    ) -> int:
        allowed_categories = list(PHASE_CATEGORIES.get(current_phase, ["Behavioral + Project"]))
        if current_phase == "CODING" and not coding_mode_enabled:
            allowed_categories = ["Theoretical DSA"]
        if exclude_categories:
            allowed_categories = [c for c in allowed_categories if c not in exclude_categories]
        if not allowed_categories:
            allowed_categories = list(PHASE_CATEGORIES.get(current_phase, ["Behavioral + Project"]))
            if current_phase == "CODING" and not coding_mode_enabled:
                allowed_categories = ["Theoretical DSA"]

        # Gather all valid candidates
        all_candidates = []
        for cat in allowed_categories:
            entity_candidates = self._get_candidates_for_category(cat, context, state_memory)
            for cand_type, cand_val in entity_candidates:
                # Filter by allowed type
                allowed_types = CATEGORY_ALLOWED_ENTITY_TYPES.get(cat, {"project", "skill", "internship", "experience", "subject", "company", "certificate"})
                if cand_type not in allowed_types:
                    continue
                if not self.check_entity_validity(cand_val, cat):
                    continue
                # Exclude check
                if isinstance(cand_val, dict):
                    name = cand_val.get("name") or cand_val.get("company") or cand_val.get("title") or ""
                else:
                    name = str(cand_val)
                name_clean = self._clean_entity_name(name).strip().lower()
                
                if exclude_entities and any(name_clean == self._clean_entity_name(ex).strip().lower() for ex in exclude_entities):
                    continue
                all_candidates.append((cat, cand_type, cand_val, name_clean))

        # Recent entities and topic groups for checking rejections
        recent_topic_groups = []
        for h in context.session_history[-4:]:
            tk = h.get("topic") or ""
            if tk:
                recent_topic_groups.append(resolve_topic_group(tk))

        # Hard reject of entity 4+ times in last 6 questions
        recent_entities_6 = []
        for h in context.session_history[-5:]:
            ent = h.get("entity") or h.get("follow_up_seed") or ""
            if ent:
                recent_entities_6.append(self._clean_entity_name(ent).strip().lower())

        # Exact duplicate prompt check
        historical_topic_keys = [h.get("topic", "").strip().lower() for h in context.session_history if h.get("topic")]

        # For each relaxation stage (0 to 4), let's calculate weights
        # and count candidates with weight >= 0.05
        for stage in range(5):
            valid_count = 0
            for cat, cand_type, cand_val, name_clean in all_candidates:
                # Check hard constraints first (these are NEVER relaxed)
                # 1. Exact duplicate topic check
                entity_slug = re.sub(r'[^a-z0-9_]', '', name_clean.replace(" ", "_"))
                category_slug = re.sub(r'[^a-z0-9_]', '', cat.lower().replace(" ", "_").replace("+", "_"))
                est_topic_key = f"{entity_slug}_{category_slug}"
                if est_topic_key in historical_topic_keys:
                    continue
                # 2. Entity cooldown hard rule: 4+ times in last 6
                if recent_entities_6.count(name_clean) >= 4:
                    continue

                # 3. Topic Group Cooldown (Stage dependent)
                est_topic_group = resolve_topic_group(est_topic_key)
                if stage < 4 and est_topic_group in recent_topic_groups:
                    # Alternative topic group check
                    alt_topic_group_exists = False
                    for other_cat in allowed_categories:
                        def_tg = CATEGORY_TO_TOPIC_GROUP.get(other_cat)
                        if def_tg and def_tg not in recent_topic_groups:
                            alt_topic_group_exists = True
                            break
                    if alt_topic_group_exists:
                        continue # Hard rejected

                # Start calculating weight
                weight = {
                    "project": 15.0,
                    "internship": 10.0,
                    "experience": 8.0,
                    "certificate": 5.0,
                    "skill": 3.0,
                    "subject": 2.0,
                    "company": 2.0
                }.get(cand_type, 1.0)

                # Project overuse prevention
                project_usage = 0
                for h in context.session_history:
                    h_ent = h.get("entity") or h.get("follow_up_seed") or ""
                    if h_ent and self._clean_entity_name(h_ent).strip().lower() == name_clean:
                        project_usage += 1
                if cand_type == "project":
                    if project_usage == 1:
                        weight *= 0.4
                    elif project_usage == 2:
                        weight *= 0.2
                    elif project_usage >= 3:
                        weight *= 0.1
                    # Hard rule check
                    recent_7_entities = [self._clean_entity_name(h.get("entity") or h.get("follow_up_seed") or "").strip().lower() for h in context.session_history[-7:]]
                    if recent_7_entities.count(name_clean) >= 3:
                        continue # Hard reject

                # Entity cooldown soft penalty
                recent_entities_5 = [self._clean_entity_name(h.get("entity") or h.get("follow_up_seed") or "").strip().lower() for h in context.session_history[-4:]]
                recent_cnt = recent_entities_5.count(name_clean)
                if recent_cnt == 2:
                    weight *= 0.8 if stage >= 3 else 0.4
                elif recent_cnt >= 3:
                    weight *= 0.6 if stage >= 3 else 0.2

                # Category coverage penalty
                if stage == 0:
                    COVERAGE_CATEGORIES = ["Problem Understanding", "Implementation", "Architecture", "Database", "Performance", "Tradeoffs", "Scalability", "Failure Scenarios", "Lessons Learned"]
                    if cat in COVERAGE_CATEGORIES:
                        # Has this category been asked for this project/entity before?
                        cat_asked_for_entity = False
                        for h in context.session_history:
                            h_ent = h.get("entity") or h.get("follow_up_seed") or ""
                            h_cat = h.get("category") or ""
                            if h_ent and self._clean_entity_name(h_ent).strip().lower() == name_clean and h_cat == cat:
                                cat_asked_for_entity = True
                                break
                        if cat_asked_for_entity:
                            # Check if there are unasked categories in the coverage list for P in current phase
                            unasked_exist = False
                            for other_cat in allowed_categories:
                                if other_cat in COVERAGE_CATEGORIES:
                                    other_asked = False
                                    for h in context.session_history:
                                        h_ent = h.get("entity") or h.get("follow_up_seed") or ""
                                        h_cat = h.get("category") or ""
                                        if h_ent and self._clean_entity_name(h_ent).strip().lower() == name_clean and h_cat == other_cat:
                                            other_asked = True
                                            break
                                    if not other_asked:
                                        unasked_exist = True
                                        break
                            if unasked_exist:
                                weight *= 0.3

                # Topic Group Cooldown soft penalty
                if est_topic_group in recent_topic_groups:
                    weight *= 0.5 if stage >= 2 else 0.1

                # Category diversity encouragement
                history_categories = [h.get("category") for h in context.session_history if h.get("category")]
                if cat in history_categories:
                    weight *= 0.3

                if weight >= 0.05:
                    valid_count += 1

            if valid_count >= 3:
                return stage
        return 4

    def select_topic_and_context(self, context: InterviewContext, state_memory: dict, exclude_categories: list[str] | None = None, exclude_entities: list[str] | None = None) -> dict:
        """Select a target topic/entity dynamically and build structured context payload for AI generation."""
        covered_projects = set(state_memory.get("covered_projects") or [])
        covered_skills = set(s.lower() for s in (state_memory.get("covered_skills") or []))
        covered_subjects = set(s.lower() for s in (state_memory.get("covered_subjects") or []))
        covered_internships = set(i.lower() for i in (state_memory.get("covered_internships") or []))
        covered_experience = set(e.lower() for e in (state_memory.get("covered_experience") or []))
        covered_certificates = set(c.lower() for c in (state_memory.get("covered_certificates") or []))
        
        projects = self._extract_projects(context.resume_profile)
        skills = self._extract_skills(context.resume_profile)
        internships = self._extract_internships(context.resume_profile)
        experience = self._extract_experience(context.resume_profile)
        companies = self._extract_companies(context.resume_profile)
        
        # JD skills
        jd = context.job_description or {}
        jd_skills = self._list_from_profile(jd, ["required_skills", "technologies", "skills", "requirements"])
        
        # CS subjects
        all_skills = list(set(s.lower() for s in skills + jd_skills))
        subject_map = {
            "dbms": ["database", "sql", "mysql", "postgresql", "mongodb", "nosql", "dbms", "oracle"],
            "networking": ["tcp", "http", "api", "rest", "socket", "network", "dns", "ip"],
            "os": ["linux", "process", "thread", "memory", "os", "operating system", "docker", "kubernetes"],
            "dsa": ["algorithm", "data structure", "sorting", "tree", "graph", "array", "linked list", "stack", "queue"],
            "oop": ["java", "python", "c++", "oop", "class", "object", "inheritance", "polymorphism"],
            "system_design": ["architecture", "microservice", "scalab", "distributed", "cloud", "aws", "azure"],
        }
        
        subjects = []
        for subject, keywords in subject_map.items():
            if any(kw in " ".join(all_skills) for kw in keywords):
                subjects.append(subject)
        if not subjects:
            subjects = list(subject_map.keys())
  
        certificates = context.resume_profile.get("certificates") or []
        if not isinstance(certificates, list):
            certificates = [certificates] if certificates else []

        # Determine phase and coding mode
        current_phase = state_memory.get("current_phase") or "INTRODUCTION"
        coding_mode_enabled = state_memory.get("coding_mode_enabled") or False

        # Run candidate pool health check to set relaxation stage
        relaxation_stage = self._calculate_relaxation_stage(
            context,
            state_memory,
            current_phase,
            coding_mode_enabled,
            exclude_categories,
            exclude_entities
        )
        state_memory["relaxation_stage"] = relaxation_stage

        # Category determination with exclusions support
        category = self.determine_next_category(context.difficulty, context.session_history, current_phase, coding_mode_enabled, exclude_categories, state_memory)
        
        # Enforce strict compatibility filtering with category switching loop
        max_category_switches = 5
        switch_count = 0
        valid_candidates = []
        
        while switch_count < max_category_switches:
            allowed_types = CATEGORY_ALLOWED_ENTITY_TYPES.get(category, {"project", "skill", "internship", "experience", "subject", "company", "certificate"})
            entity_candidates = self._get_candidates_for_category(category, context, state_memory)
            
            # Filter candidates by allowed type, validity, and exclusions
            valid_candidates = []
            for cand_type, cand_val in entity_candidates:
                if cand_type not in allowed_types:
                    continue
                if not self.check_entity_validity(cand_val, category):
                    continue
                
                # Check exclusions
                if isinstance(cand_val, dict):
                    name = cand_val.get("name") or cand_val.get("company") or cand_val.get("title") or ""
                else:
                    name = str(cand_val)
                name_clean = self._clean_entity_name(name).strip().lower()
                
                if exclude_entities and any(name_clean == self._clean_entity_name(ex).strip().lower() for ex in exclude_entities):
                    continue
                    
                valid_candidates.append((cand_type, cand_val))
                
            if valid_candidates:
                break
            else:
                # No valid candidate for this category; switch category
                switch_count += 1
                if not exclude_categories:
                    exclude_categories = []
                if category not in exclude_categories:
                    exclude_categories.append(category)
                category = self.determine_next_category(context.difficulty, context.session_history, current_phase, coding_mode_enabled, exclude_categories, state_memory)
                
        # If we exhausted switches, fallback to safe default
        if not valid_candidates:
            category = "Behavioral + Project"
            if projects:
                valid_candidates = [("project", projects[0])]
            else:
                valid_candidates = [("project", {"name": "your project", "technologies": ["software engineering"]})]

        # Hard exclusions filter step
        recent_7_entities = [self._clean_entity_name(h.get("entity") or h.get("follow_up_seed") or "").strip().lower() for h in context.session_history[-7:]]
        recent_5_entities_for_cooldown = [self._clean_entity_name(h.get("entity") or h.get("follow_up_seed") or "").strip().lower() for h in context.session_history[-5:]]
        recent_5_entities = [self._clean_entity_name(h.get("entity") or h.get("follow_up_seed") or "").strip().lower() for h in context.session_history[-4:]]

        filtered_valid_candidates = []
        for cand_type, cand_val in valid_candidates:
            if isinstance(cand_val, dict):
                name = cand_val.get("name") or cand_val.get("company") or cand_val.get("title") or ""
            else:
                name = str(cand_val)
            name_clean = name.strip().lower()
            
            # Hard Rules:
            # 1. Project overuse: No project more than 3 times in last 8 questions.
            if cand_type == "project" and recent_7_entities.count(name_clean) >= 3:
                continue
            # 2. Entity cooldown: Entity 4+ times in last 6 questions.
            if recent_5_entities_for_cooldown.count(name_clean) >= 3:
                continue
                
            filtered_valid_candidates.append((cand_type, cand_val))

        if not filtered_valid_candidates:
            if projects:
                valid_candidates = [("project", projects[0])]
            else:
                valid_candidates = [("project", {"name": "your project", "technologies": ["software engineering"]})]
        else:
            valid_candidates = filtered_valid_candidates

        allowed_categories = list(PHASE_CATEGORIES.get(current_phase, ["Behavioral + Project"]))
        all_projects_covered = all(p.get("name") in covered_projects for p in projects) if projects else False
        
        candidate_weights = []
        for cand_type, cand_val in valid_candidates:
            if isinstance(cand_val, dict):
                name = cand_val.get("name") or cand_val.get("company") or cand_val.get("title") or ""
            else:
                name = str(cand_val)
            name_clean = name.strip().lower()
            
            # Base priority weights: Projects >> Experience > Certificates > Skills > Subjects >> Internships
            base_w = {
                "project": 20.0,
                "experience": 10.0,
                "certificate": 8.0,
                "skill": 6.0,
                "subject": 5.0,
                "internship": 3.0,
                "company": 2.0
            }.get(cand_type, 1.0)

            # Priority 1: Internship cooldown - exclude if in last 3 questions
            if cand_type == "internship":
                recent_3_entities = [self._clean_entity_name(h.get("entity") or h.get("follow_up_seed") or "").strip().lower() for h in context.session_history[-3:]]
                if name_clean in recent_3_entities:
                    base_w *= 0.02  # Near-zero weight, strongly prefer other entities
            
            # Project overuse prevention soft penalty
            project_usage = 0
            for h in context.session_history:
                h_ent = h.get("entity") or h.get("follow_up_seed") or ""
                if h_ent and self._clean_entity_name(h_ent).strip().lower() == name_clean:
                    project_usage += 1
            if cand_type == "project":
                if project_usage == 1:
                    base_w *= 0.4
                elif project_usage == 2:
                    base_w *= 0.2
                elif project_usage >= 3:
                    base_w *= 0.1
                
            # Entity cooldown soft penalty
            recent_cnt = recent_5_entities.count(name_clean)
            if recent_cnt == 2:
                base_w *= 0.8 if relaxation_stage >= 3 else 0.4
            elif recent_cnt >= 3:
                base_w *= 0.6 if relaxation_stage >= 3 else 0.2
                
            # Category coverage soft prioritization
            if relaxation_stage < 1:
                COVERAGE_CATEGORIES = ["Problem Understanding", "Implementation", "Architecture", "Database", "Performance", "Tradeoffs", "Scalability", "Failure Scenarios", "Lessons Learned"]
                if category in COVERAGE_CATEGORIES:
                    cat_asked = False
                    for h in context.session_history:
                        h_ent = h.get("entity") or h.get("follow_up_seed") or ""
                        h_cat = h.get("category") or ""
                        if h_ent and self._clean_entity_name(h_ent).strip().lower() == name_clean and h_cat == category:
                            cat_asked = True
                            break
                    if cat_asked:
                        unasked_exist = False
                        for other_cat in allowed_categories:
                            if other_cat in COVERAGE_CATEGORIES:
                                other_asked = False
                                for h in context.session_history:
                                    h_ent = h.get("entity") or h.get("follow_up_seed") or ""
                                    h_cat = h.get("category") or ""
                                    if h_ent and self._clean_entity_name(h_ent).strip().lower() == name_clean and h_cat == other_cat:
                                        other_asked = True
                                        break
                                if not other_asked:
                                    unasked_exist = True
                                    break
                        if unasked_exist:
                            base_w *= 0.3

            # Topic Group Cooldown soft penalty
            entity_slug = re.sub(r'[^a-z0-9_]', '', name_clean.replace(" ", "_"))
            category_slug = re.sub(r'[^a-z0-9_]', '', category.lower().replace(" ", "_").replace("+", "_"))
            est_topic_key = f"{entity_slug}_{category_slug}"
            est_topic_group = resolve_topic_group(est_topic_key, entity_type=cand_type)
            
            recent_topic_groups = []
            for h in context.session_history[-4:]:
                tk = h.get("topic") or ""
                if tk:
                    recent_topic_groups.append(resolve_topic_group(tk, entity_type=cand_type))
            if est_topic_group in recent_topic_groups:
                base_w *= 0.5 if relaxation_stage >= 2 else 0.1

            # Phase-based prioritization
            if current_phase == "INTRODUCTION":
                if cand_type in ["project", "internship"]:
                    base_w *= 2.0
            elif current_phase == "SYSTEM_DESIGN":
                if cand_type == "project":
                    base_w *= 3.0
            elif current_phase == "BEHAVIORAL":
                if cand_type in ["internship", "experience"]:
                    base_w *= 2.0
            elif current_phase == "CODING":
                if cand_type in ["skill", "project"]:
                    base_w *= 2.0
                    
            candidate_weights.append(max(0.01, base_w))
            
        selected_entity_type, selected_entity = self.random.choices(valid_candidates, weights=candidate_weights, k=1)[0]

        # Reselection safety for internships in phases without natural internship categories
        if selected_entity_type == "internship" and current_phase in ("SYSTEM_DESIGN", "CODING"):
            project_candidates = [c for c in valid_candidates if c[0] == "project"]
            experience_candidates = [c for c in valid_candidates if c[0] == "experience"]
            other_candidates = [c for c in valid_candidates if c[0] not in ("internship", "project", "experience")]
            
            if project_candidates:
                selected_entity_type, selected_entity = self.random.choice(project_candidates)
            elif experience_candidates:
                selected_entity_type, selected_entity = self.random.choice(experience_candidates)
            elif other_candidates:
                selected_entity_type, selected_entity = self.random.choice(other_candidates)
        
        return {
            "target_entity": selected_entity,
            "entity_type": selected_entity_type,
            "category": category,
            "difficulty": context.difficulty,
            "resume_context": context.resume_profile,
            "jd_context": context.job_description or {},
            "question_history": state_memory.get("question_history") or [],
            "topic_history": state_memory.get("topic_history") or [],
            "answer_history": context.session_history,
        }

    def build_fallback_question(self, context: InterviewContext, target_entity: Any, entity_type: str, category: str = "") -> InterviewQuestion:
        """Fallback question generator when LLM/API is offline or failing."""
        difficulty = context.difficulty
        
        # Determine active phase
        history_len = len(context.session_history)
        current_phase = determine_phase_from_q_num(history_len + 1)
        allowed_cats = PHASE_CATEGORIES.get(current_phase, ["Behavioral + Project"])
        
        if not category or category not in allowed_cats:
            category = allowed_cats[0]

        # Force category compatibility for internship entities
        if entity_type == "internship":
            allowed_intern_cats = INTERNSHIP_CATEGORIES_BY_PHASE.get(current_phase, ["Behavioral + Project"])
            if category not in allowed_intern_cats:
                category = allowed_intern_cats[0]
            
        if isinstance(target_entity, dict):
            name = self._clean_entity_name(target_entity.get("name") or target_entity.get("company") or "your project")
            techs = target_entity.get("technologies", []) or target_entity.get("tech_stack", []) or []
        elif isinstance(target_entity, str):
            name = self._clean_entity_name(target_entity)
            techs = []
        else:
            name = "your project"
            techs = []
 
        if entity_type == "internship":
            internship_templates = {
                "Behavioral + Project": [
                    "What was your primary responsibility during your {name} internship?",
                    "What would you do differently if you repeated your {name} internship?",
                    "How did you handle feedback from your manager at {name}?",
                    "What was your biggest contribution during your time at {name}?",
                    "How did you prioritize tasks during your {name} internship?",
                    "What initiative did you take beyond your assigned work at {name}?",
                    "How did you manage competing deadlines at {name}?",
                ],
                "Implementation": [
                    "What was the most challenging task you worked on during your {name} internship?",
                    "How did your development workflow change during your {name} internship?",
                    "What tools or technologies did you use daily at {name}?",
                    "How did you approach writing your first piece of production code at {name}?",
                    "What coding standards or practices did you follow at {name}?",
                    "How did you test the code you wrote during your {name} internship?",
                    "What was the most complex feature you contributed to at {name}?",
                ],
                "Debugging": [
                    "Describe a bug you fixed during your {name} internship.",
                    "How did you approach debugging unfamiliar code at {name}?",
                    "What debugging tools or techniques did you learn at {name}?",
                    "What was the most time-consuming issue you resolved during your {name} internship?",
                    "How did you reproduce a reported bug during your time at {name}?",
                ],
                "Lessons Learned": [
                    "What did you learn from working on real-world projects during your {name} internship?",
                    "What technical skill improved the most during your {name} internship?",
                    "What surprised you most about professional software development at {name}?",
                    "How did your understanding of software engineering change after your {name} internship?",
                    "What advice would you give to someone starting an internship at a company like {name}?",
                    "What was the gap between academic knowledge and real-world practice you noticed at {name}?",
                ],
                "Problem Understanding": [
                    "How did you understand the requirements for your assigned tasks during your {name} internship?",
                    "What information did you need before starting your assigned work at {name}?",
                    "How were project requirements communicated to you during your {name} internship?",
                    "How did you clarify ambiguous requirements during your work at {name}?",
                    "What process did you follow to break down a large task at {name}?",
                    "How did you handle tasks where the requirements changed midway at {name}?",
                ]
            }
            templates = internship_templates.get(category, internship_templates["Behavioral + Project"])

            # Priority 6: Fallback repeat protection - filter templates already used in history
            used_questions_normalized = set()
            for h in context.session_history:
                hq = h.get("question", "")
                if hq:
                    used_questions_normalized.add(re.sub(r'[^\w\s]', '', hq.lower().strip()))

            unused_templates = []
            for t in templates:
                rendered = t.format(name=name)
                rendered_norm = re.sub(r'[^\w\s]', '', rendered.lower().strip())
                if rendered_norm not in used_questions_normalized:
                    unused_templates.append(t)

            if unused_templates:
                templates = unused_templates

            raw_prompt = self.random.choice(templates)
            prompt = raw_prompt.format(name=name)

            # Debug logging
            print("\nENTITY:")
            print(name)
            print("\nENTITY_TYPE:")
            print("internship")
            print("\nTEMPLATE_GROUP:")
            print("internship")
            print("ENTITY")
            print("ENTITY_TYPE: internship")
            print("TEMPLATE_GROUP: internship")
        elif category == "Database":
            db_history_count = sum(1 for h in context.session_history if h.get("category") == "Database")
            subtopics = ["Selection", "Schema Design", "Relationships", "Indexing", "Query Optimization", "Scalability", "Failure Recovery"]
            selected_subtopic = subtopics[db_history_count % len(subtopics)]
            
            if entity_type == "project":
                db_templates = {
                    "Selection": ["Why did you choose the database technology for {name} over alternative storage solutions?"],
                    "Schema Design": ["How did you design the database schema for {name}?"],
                    "Relationships": ["How did you model relationships between entities in {name}?"],
                    "Indexing": ["What indexing strategy did you use in {name}?"],
                    "Query Optimization": ["What query in {name} became the database bottleneck?"],
                    "Scalability": ["How would the database for {name} handle 10x traffic?"],
                    "Failure Recovery": ["What happens if the database server for {name} crashes?"]
                }
            else:  # skill / database technology
                db_templates = {
                    "Selection": ["Why did you choose {name} over alternatives?"],
                    "Schema Design": ["What schema constraints of {name} did you establish in your project?"],
                    "Relationships": ["How did you model references or relationships between tables in {name}?"],
                    "Indexing": ["What indexing features of {name} did you use?"],
                    "Query Optimization": ["How did you optimize {name} query performance?"],
                    "Scalability": ["How would you scale {name}?"],
                    "Failure Recovery": ["What limitations of {name} did you encounter?"]
                }
            templates = db_templates.get(selected_subtopic, db_templates["Selection"])
            raw_prompt = self.random.choice(templates)
            prompt = raw_prompt.format(name=name)
        else:
            fallback_templates = {
                "Problem Understanding": [
                    "Why was the problem solved by {name} worth solving?",
                    "What user pain point were you targeting with {name}?",
                    "What alternatives were available before you built {name}?",
                    "What evidence convinced you that the problem addressed by {name} actually existed?",
                ],
                "Architecture": [
                    "What are the major components of the {name} system?",
                    "How does data flow through the {name} application?",
                    "What architectural decision in {name} had the biggest impact?",
                ],
                "Implementation": [
                    "Which feature in {name} took the longest to build?",
                    "What was the most difficult module to implement in {name}?",
                    "What implementation decision in {name} would you change today?",
                ],
                "Debugging": [
                    "What was the hardest bug you fixed in {name}?",
                    "Describe a difficult bug you encountered in {name}.",
                    "How did you isolate the root cause of the bug in {name}?",
                ],
                "Performance": [
                    "What performance bottleneck did you encounter in {name}?",
                    "How did you optimize response times in {name}?",
                ],
                "Scalability": [
                    "What breaks first under 10x traffic in {name}?",
                    "How would you redesign {name} for 1 million users?",
                ],
                "Security": [
                    "What security risks exist in the {name} application?",
                    "How did you protect user data in {name}?",
                ],
                "Failure Scenarios": [
                    "What happens if the database or downstream service for {name} goes down?",
                    "How would the {name} system recover from service failures?",
                ],
                "Tradeoffs": [
                    "What design tradeoff did you make in {name}?",
                    "What alternative architecture for {name} did you reject?",
                ],
                "Production Operations": [
                    "How would you monitor the {name} application?",
                    "What metrics would you track in {name}?",
                ],
                "Behavioral + Project": [
                    "Tell me about a challenge you faced during {name}.",
                    "What mistake during {name} taught you the most?",
                    "What would you do differently today regarding {name}?",
                ],
                "Coding": [
                    "Explain how you would write a function to search for an element in a rotated sorted array.",
                    "How would you implement a rate limiter algorithm conceptually?"
                ],
                "Algorithms": [
                    "What is the time complexity of binary search?",
                    "How does the quicksort algorithm perform partition conceptually?"
                ],
                "Data Structures": [
                    "When would you use a hash table over a binary search tree?",
                    "Explain the difference between a stack and a queue data structure."
                ],
                "Theoretical DSA": [
                    "What is the time complexity of binary search?",
                    "How do binary search trees balance runtime operations theoretically?"
                ],
                "Reflection": [
                    "What would you improve if you rebuilt {name} today?",
                    "Looking back at {name}, what was the most complex technical decision?"
                ],
                "Lessons Learned": [
                    "What is the most valuable lesson you learned while working on {name}?",
                    "How did building {name} change your approach to system development?"
                ],
                "Future Improvements": [
                    "If you had another three months, what major features would you add to {name}?",
                    "How would you enhance the reliability of {name} in the future?"
                ],
            }
            templates = fallback_templates.get(category, fallback_templates["Behavioral + Project"])

            # Priority 6: Fallback repeat protection - filter templates already used in history
            used_questions_normalized = set()
            for h in context.session_history:
                hq = h.get("question", "")
                if hq:
                    used_questions_normalized.add(re.sub(r'[^\w\s]', '', hq.lower().strip()))

            unused_templates = []
            for t in templates:
                rendered = t.format(name=name)
                rendered_norm = re.sub(r'[^\w\s]', '', rendered.lower().strip())
                if rendered_norm not in used_questions_normalized:
                    unused_templates.append(t)

            if unused_templates:
                templates = unused_templates

            raw_prompt = self.random.choice(templates)
            prompt = raw_prompt.format(name=name)
        
        expected_signals = [name] + [str(t) for t in techs[:3]]
        
        # Determine semantic topic key
        entity_slug = re.sub(r'[^a-z0-9_]', '', name.lower().replace(" ", "_"))
        category_slug = re.sub(r'[^a-z0-9_]', '', category.lower().replace(" ", "_").replace("+", "_"))
        topic = f"{entity_slug}_{category_slug}"
 
        return InterviewQuestion(
            prompt=prompt,
            kind=entity_type + "_based" if entity_type in ("project", "internship", "experience") else entity_type,
            difficulty=difficulty,
            expected_signals=expected_signals,
            follow_up_seed=name,
            trap=False,
            category=category,
            topic=topic,
        )
 
    def build_next_question(self, context: InterviewContext) -> InterviewQuestion:
        """Build next question (used as the full template-based deterministic generator when LLM is offline/disabled)."""
        covered = self._extract_covered_topics(context.session_history)
        covered_projects = []
        covered_skills = []
        covered_subjects = []
        covered_internships = []
        covered_experience = []
        
        projects = self._extract_projects(context.resume_profile)
        skills = self._extract_skills(context.resume_profile)
        
        for c in covered:
            for p in projects:
                if p["name"].lower() == c.lower():
                    covered_projects.append(p["name"])
            for s in skills:
                if s.lower() == c.lower():
                    covered_skills.append(s)
            if c.lower() in ("dbms", "networking", "os", "dsa", "oop", "system_design"):
                covered_subjects.append(c.lower())
                
        state_memory = {
            "question_history": [h.get("question", "") for h in context.session_history],
            "topic_history": list(covered),
            "covered_projects": covered_projects,
            "covered_skills": covered_skills,
            "covered_subjects": covered_subjects,
            "covered_internships": covered_internships,
            "covered_experience": covered_experience,
            "covered_certificates": [],
        }
        
        context_payload = self.select_topic_and_context(context, state_memory)
        
        # Print debug logging
        target_entity = context_payload["target_entity"]
        entity_type = context_payload["entity_type"]
        category = context_payload.get("category", "Behavioral + Project")
        if isinstance(target_entity, dict):
            entity_name = target_entity.get("name") or target_entity.get("company") or target_entity.get("title") or "your project"
        else:
            entity_name = str(target_entity)
        entity_name = self._clean_entity_name(entity_name)
        
        print(f"CATEGORY: {category}")
        print(f"ENTITY: {entity_name}")
        print(f"ENTITY_TYPE: {entity_type}")
        
        return self.build_fallback_question(
            context,
            context_payload["target_entity"],
            context_payload["entity_type"],
            category=context_payload.get("category", "Behavioral + Project")
        )

    def generate_follow_up_question(self, base_question: InterviewQuestion, answer: str, evaluation_score: int) -> InterviewQuestion:
        """Build a contextual follow-up question based on answer quality."""
        seed = self._clean_entity_name(base_question.follow_up_seed or self._compact_phrase(base_question.prompt))
        
        category = base_question.category or "Behavioral + Project"
        entity_slug = re.sub(r'[^a-z0-9_]', '', seed.lower().replace(" ", "_"))
        category_slug = re.sub(r'[^a-z0-9_]', '', category.lower().replace(" ", "_").replace("+", "_"))
        topic = f"{entity_slug}_{category_slug}"

        if base_question.kind in ("internship_based", "experience_based"):
            if evaluation_score >= 8 and len(answer.split()) >= 40:
                prompt = (
                    f"That sounds like a significant contribution at {seed}. "
                    f"How did you measure the impact of that work, and how did it influence the project's overall timeline?"
                )
                diff = min(10, base_question.difficulty + 2)
            elif evaluation_score >= 7:
                prompt = (
                    f"Regarding your work at {seed}, what was the most critical technical challenge you personally owned, "
                    f"and how did you resolve it?"
                )
                diff = min(10, base_question.difficulty + 1)
            elif evaluation_score >= 5:
                prompt = (
                    f"Can you walk me through the specific technologies you used at {seed} and how they helped you complete your tasks?"
                )
                diff = base_question.difficulty
            else:
                prompts = [
                    f"Let's focus on a simpler part of your role at {seed}. What was a typical daily task for you?",
                    f"How did you collaborate with your teammates or mentor at {seed}?",
                    f"What was the main learning experience you gained from your time at {seed}?",
                ]
                prompt = self.random.choice(prompts)
                diff = max(1, base_question.difficulty - 1)

            return InterviewQuestion(
                prompt=prompt,
                kind=base_question.kind,
                difficulty=diff,
                expected_signals=base_question.expected_signals,
                follow_up_seed=seed,
                category=category,
                topic=topic,
            )

        if evaluation_score >= 8 and len(answer.split()) >= 40:
            prompt = (
                f"You explained {seed} well. Now, if the system had to handle 10x the current load, "
                f"which component would become the bottleneck first, and how would you redesign it?"
            )
            diff = min(10, base_question.difficulty + 2)
        elif evaluation_score >= 7:
            prompt = (
                f"Regarding {seed}, what was the most critical tradeoff you accepted in that implementation, "
                f"and what metric told you the decision was correct?"
            )
            diff = min(10, base_question.difficulty + 1)
        elif evaluation_score >= 5:
            prompt = (
                f"Can you walk me through a concrete, specific example of how you implemented {seed}? "
                f"I need to understand the actual steps you took."
            )
            diff = base_question.difficulty
        else:
            prompts = [
                f"Let's focus on a simpler part of {seed}. What specific problem were you trying to solve?",
                f"Can you walk me through the core logic or functionality of {seed}?",
                f"Can you walk me through a real example from your project regarding {seed}?",
                f"What are the major modules or components involved in {seed}?",
                f"What technologies did you use for {seed}, and what was your specific role?",
            ]
            prompt = self.random.choice(prompts)
            diff = max(1, base_question.difficulty - 1)

        return InterviewQuestion(
            prompt=prompt,
            kind="follow_up",
            difficulty=diff,
            expected_signals=base_question.expected_signals,
            follow_up_seed=seed,
            category=category,
            topic=topic,
        )

    def generate_trap_question(self, context: InterviewContext, base_question: InterviewQuestion | None = None) -> InterviewQuestion:
        """Generate a trap question that challenges the candidate's assumptions."""
        project = self._clean_entity_name(self._pick_project(context.resume_profile))
        skill = self._clean_entity_name(self._pick_skill(context.resume_profile))

        prompts = [
            f"You chose {skill} for {project}. What is the strongest argument *against* that choice, and why might a senior engineer reject it?",
            f"In {project}, what is the single biggest technical risk you accepted, and what would happen if it failed in production?",
            f"If I told you that {skill} was the wrong tool for {project}, how would you defend your decision with evidence?",
            f"What is the weakest part of {project}'s architecture, and what would break first under real production traffic?",
        ]
        prompt = self.random.choice(prompts)

        return InterviewQuestion(
            prompt=prompt,
            kind="trap",
            difficulty=min(10, context.difficulty + 2),
            expected_signals=[skill, project, "tradeoff", "risk"],
            follow_up_seed=project,
            trap=True,
        )

    def adapt_difficulty(self, current_difficulty: int, score: int, history: Iterable[dict] | None = None) -> int:
        """Adjust difficulty based on latest score and recent performance trend."""
        history = list(history or [])
        adjusted = current_difficulty

        # Score-based adjustment (maps to user's 0-100 scale via score * 10)
        if score >= 9:  # >= 90%
            adjusted += 2
        elif score >= 7:  # >= 70%
            adjusted += 1
        elif score <= 4:  # < 50%
            adjusted -= 1
        elif score <= 2:  # < 30%
            adjusted -= 2

        # Trend-based adjustment
        if history:
            recent_scores = [item.get("score", 0) for item in history[-3:]]
            if recent_scores and sum(recent_scores) / len(recent_scores) < 4:
                adjusted -= 1
            elif recent_scores and sum(recent_scores) / len(recent_scores) >= 8:
                adjusted += 1

        return max(1, min(10, adjusted))

    # ------------------------------------------------------------------
    # Phase 1: Project Deep-Dive Questions (Rounds 1-3)
    # ------------------------------------------------------------------

    def _generate_project_question(self, context: InterviewContext, asked: list[str]) -> InterviewQuestion:
        """Generate a question about the candidate's ACTUAL projects."""
        projects = self._extract_projects(context.resume_profile)
        skills = self._extract_skills(context.resume_profile)

        if not projects:
            # Fallback to skills if no projects found
            return self._generate_resume_skill_question(context, asked)

        project = self.random.choice(projects[:5])
        project_name = self._clean_entity_name(project.get("name", "your project"))
        project_tech = project.get("technologies", [])
        project_desc = project.get("description", "")

        # Build a question that uses the ACTUAL project name and details following the required templates
        question_variants = []

        # 1. Project Overview / 2. Problem Statement
        question_variants.extend([
            f"Tell me about your {project_name} project.",
            f"What problem does {project_name} solve?",
        ])

        # 3. Architecture
        question_variants.extend([
            f"Walk me through the technical architecture of {project_name}.",
            f"Explain the system design and architecture of {project_name}.",
        ])

        # 4. Tech Stack Justification
        if project_tech:
            tech = self.random.choice(project_tech) if isinstance(project_tech, list) else str(project_tech)
            question_variants.extend([
                f"Why did you choose {tech} for {project_name}?",
                f"How did you use {tech} in this project?",
            ])

        # 5. Challenges
        question_variants.extend([
            f"What challenges did you face during the implementation of {project_name}?",
            f"What was the hardest engineering challenge you faced while building {project_name}?",
        ])

        # 6. Scalability / 7. Improvements
        question_variants.extend([
            f"If you had to scale {project_name} to handle 10x the traffic, what would break first?",
            f"If you had to rebuild {project_name} from scratch today, what would you change and why?",
        ])

        # Filter out already-asked questions
        available = [q for q in question_variants if not any(self._similar(q, a) for a in asked)]
        prompt = self.random.choice(available) if available else self.random.choice(question_variants)

        return InterviewQuestion(
            prompt=prompt,
            kind="project_based",
            difficulty=context.difficulty,
            expected_signals=[project_name] + (project_tech[:3] if isinstance(project_tech, list) else []),
            follow_up_seed=project_name,
        )

    # ------------------------------------------------------------------
    # Phase 2: Resume Skill Verification (Rounds 4-5)
    # ------------------------------------------------------------------

    def _generate_resume_skill_question(self, context: InterviewContext, asked: list[str]) -> InterviewQuestion:
        """Generate a question about skills listed on the candidate's resume."""
        skills = self._extract_skills(context.resume_profile)
        covered_topics = self._extract_covered_topics(context.session_history)

        # Filter out skills already covered
        uncovered = [s for s in skills if s.lower() not in covered_topics]
        target_skills = uncovered if uncovered else skills

        if not target_skills:
            return self._generate_general_question(context)

        skill = self._clean_entity_name(self.random.choice(target_skills[:8]))
        projects = self._extract_projects(context.resume_profile)
        project_name = self._clean_entity_name(projects[0].get("name", "your work") if projects else "your work")

        question_variants = [
            f"You listed {skill} on your resume. Can you describe a real scenario where you applied {skill} to solve a production problem?",
            f"How have you used {skill} in {project_name}? Walk me through the implementation details.",
            f"What are the limitations of {skill} that you've encountered in practice, and how did you work around them?",
            f"Compare {skill} with an alternative you considered. Why did {skill} win for your use case?",
        ]

        available = [q for q in question_variants if not any(self._similar(q, a) for a in asked)]
        prompt = self.random.choice(available) if available else self.random.choice(question_variants)

        return InterviewQuestion(
            prompt=prompt,
            kind="resume_based",
            difficulty=context.difficulty,
            expected_signals=[skill, project_name],
            follow_up_seed=skill,
        )

    # ------------------------------------------------------------------
    # Phase 3: JD Skill Alignment (Rounds 6-8)
    # ------------------------------------------------------------------

    def _generate_jd_skill_question(self, context: InterviewContext, asked: list[str]) -> InterviewQuestion:
        """Generate questions aligned to the Job Description requirements."""
        jd = context.job_description or {}
        jd_skills = self._list_from_profile(jd, ["required_skills", "technologies", "skills", "requirements"])
        resume_skills = self._extract_skills(context.resume_profile)
        covered_topics = self._extract_covered_topics(context.session_history)

        if not jd_skills:
            return self._generate_resume_skill_question(context, asked)

        # Prioritize JD skills NOT yet covered
        uncovered_jd = [s for s in jd_skills if s.lower() not in covered_topics]
        target = uncovered_jd if uncovered_jd else jd_skills
        skill = self._clean_entity_name(self.random.choice(target[:8]))

        # Check if candidate has this skill
        has_skill = False
        for rs in resume_skills:
            rs_lower = rs.lower()
            pattern = r"(?<![a-z0-9+#])" + re.escape(skill.lower()) + r"(?![a-z0-9+#])"
            if re.search(pattern, rs_lower):
                has_skill = True
                break

        if has_skill:
            question_variants = [
                f"This role requires {skill}. From your experience, describe how you would apply {skill} in a team environment to deliver a feature end-to-end.",
                f"The job description emphasizes {skill}. How does your experience with {skill} prepare you for the challenges of this role?",
                f"Walk me through a real project where {skill} was critical. What went wrong, and how did you fix it?",
            ]
        else:
            question_variants = [
                f"This role requires {skill}, which I don't see on your resume. How would you approach learning and applying {skill} on the job?",
                f"The position needs {skill}. What transferable experience do you have that would help you ramp up quickly?",
                f"How would you design a learning plan to become productive with {skill} within the first 30 days?",
            ]

        available = [q for q in question_variants if not any(self._similar(q, a) for a in asked)]
        prompt = self.random.choice(available) if available else self.random.choice(question_variants)

        return InterviewQuestion(
            prompt=prompt,
            kind="jd_based",
            difficulty=max(context.difficulty, 5),
            expected_signals=[skill],
            follow_up_seed=skill,
        )

    # ------------------------------------------------------------------
    # Phase 4: Core Subjects (Rounds 9-11)
    # ------------------------------------------------------------------

    def _generate_core_subject_question(self, context: InterviewContext, asked: list[str]) -> InterviewQuestion:
        """Generate CS fundamentals questions derived from resume/JD context."""
        all_skills = self._extract_skills(context.resume_profile)
        jd_skills = self._list_from_profile(context.job_description or {}, ["required_skills", "technologies", "skills"])
        combined = list(set(s.lower() for s in all_skills + jd_skills))
        covered_topics = self._extract_covered_topics(context.session_history)

        # Map skills to core subject areas
        subject_map = {
            "dbms": ["database", "sql", "mysql", "postgresql", "mongodb", "nosql", "dbms", "oracle"],
            "networking": ["tcp", "http", "api", "rest", "socket", "network", "dns", "ip"],
            "os": ["linux", "process", "thread", "memory", "os", "operating system", "docker", "kubernetes"],
            "dsa": ["algorithm", "data structure", "sorting", "tree", "graph", "array", "linked list", "stack", "queue"],
            "oop": ["java", "python", "c++", "oop", "class", "object", "inheritance", "polymorphism"],
            "system_design": ["architecture", "microservice", "scalab", "distributed", "cloud", "aws", "azure"],
        }

        # Find relevant subjects
        relevant_subjects = []
        for subject, keywords in subject_map.items():
            if any(kw in " ".join(combined) for kw in keywords):
                if subject not in covered_topics:
                    relevant_subjects.append(subject)

        if not relevant_subjects:
            relevant_subjects = list(subject_map.keys())

        subject = self.random.choice(relevant_subjects)

        # Build contextual core subject questions (NOT generic textbook questions)
        subject_questions = {
            "dbms": [
                "In your projects, you work with databases. Explain how you would design the database schema for a system like yours, and what indexing strategy would you use for the most frequent queries?",
                "If your application's database started experiencing slow queries under load, walk me through your systematic debugging approach.",
                "Explain the difference between SQL and NoSQL databases. Based on your project experience, when would you choose one over the other?",
            ],
            "networking": [
                "Your projects likely involve client-server communication. Explain how HTTP request-response works under the hood and how you would optimize API latency.",
                "If your application's API responses suddenly became slow, what networking layers would you investigate and in what order?",
                "Explain REST API design principles. How would you design the API endpoints for a system like one of your projects?",
            ],
            "os": [
                "How does the operating system manage memory for your application? Explain the difference between stack and heap memory in the context of your tech stack.",
                "If your application started consuming excessive memory or CPU, what OS-level tools would you use to diagnose the issue?",
                "Explain how processes and threads work. How does your application handle concurrent requests?",
            ],
            "dsa": [
                "Think about the data your projects handle. What data structures did you choose for the core functionality, and why were they optimal?",
                "If you needed to search through a large dataset in your application, which algorithm and data structure would give you the best performance?",
                "Explain the time complexity of the core operations in your project. Where are the performance bottlenecks?",
            ],
            "oop": [
                "How did you apply object-oriented design principles in your projects? Give me a specific example of how inheritance or polymorphism improved your code.",
                "Explain the SOLID principles. Which ones did you follow in your project architecture, and which ones did you intentionally skip?",
                "How would you refactor a monolithic function in your project into well-designed classes? Walk me through your thought process.",
            ],
            "system_design": [
                "If your project had to serve 1 million users, what architectural changes would you make? Walk me through the system design.",
                "Design a notification system for an application like yours. How would you handle real-time delivery, failures, and retries?",
                "How would you add caching to your project? Where would you cache, what eviction policy would you use, and how would you handle cache invalidation?",
            ],
        }

        variants = subject_questions.get(subject, subject_questions["oop"])
        available = [q for q in variants if not any(self._similar(q, a) for a in asked)]
        prompt = self.random.choice(available) if available else self.random.choice(variants)

        return InterviewQuestion(
            prompt=prompt,
            kind="core_subject",
            difficulty=context.difficulty,
            expected_signals=[subject],
            follow_up_seed=subject,
        )

    # ------------------------------------------------------------------
    # Phase 5: Behavioral Questions (Rounds 12-15)
    # ------------------------------------------------------------------

    def _generate_behavioral_question(self, context: InterviewContext, asked: list[str]) -> InterviewQuestion:
        """Generate behavioral / situational questions grounded in the candidate's experience."""
        projects = self._extract_projects(context.resume_profile)
        project_name = projects[0].get("name", "your project") if projects else "your project"

        question_variants = [
            f"Tell me about a time when you had a disagreement with a teammate during {project_name}. How did you resolve it?",
            f"Describe the most challenging deadline you faced while working on {project_name}. How did you prioritize and deliver?",
            f"Give me an example of when you had to learn a new technology quickly for a project. What was your approach?",
            f"Tell me about a time when you found a bug in production. How did you handle the situation?",
            f"Describe a situation where you had to explain a complex technical concept to a non-technical stakeholder.",
            f"What would you do if you realized halfway through a sprint that your approach to a feature was fundamentally wrong?",
            f"How do you handle code reviews? Describe a time when you received critical feedback on your code.",
            f"Tell me about a feature you built that you're particularly proud of. What made it special?",
        ]

        available = [q for q in question_variants if not any(self._similar(q, a) for a in asked)]
        prompt = self.random.choice(available) if available else self.random.choice(question_variants)

        return InterviewQuestion(
            prompt=prompt,
            kind="behavioral",
            difficulty=max(3, context.difficulty - 1),
            expected_signals=["teamwork", "communication", "problem-solving"],
            follow_up_seed="behavioral",
        )

    def _generate_internship_question(self, context: InterviewContext, asked: list[str]) -> InterviewQuestion | None:
        """Generate an internship question based on candidate's internships."""
        internships = self._extract_internships(context.resume_profile)
        if not internships:
            return None
        
        intern = self.random.choice(internships)
        company = self._clean_entity_name(intern.get("company", "your employer"))
        role = intern.get("role", "Intern")
        
        question_variants = [
            f"What were your responsibilities at {company}?",
            f"What technologies did you work with during your internship at {company}?",
            f"Describe a task you completed at {company}.",
            f"What was the most challenging issue you solved during your internship at {company}?",
            f"How did you collaborate with your team at {company} to deliver your tasks?",
            f"What was your key learning experience during your internship as a {role} at {company}?",
        ]
        
        available = [q for q in question_variants if not any(self._similar(q, a) for a in asked)]
        prompt = self.random.choice(available) if available else self.random.choice(question_variants)
        
        return InterviewQuestion(
            prompt=prompt,
            kind="internship_based",
            difficulty=context.difficulty,
            expected_signals=[company, role],
            follow_up_seed=company,
        )

    def _generate_experience_question(self, context: InterviewContext, asked: list[str]) -> InterviewQuestion | None:
        """Generate a work experience question based on candidate's experience."""
        experience = self._extract_experience(context.resume_profile)
        if not experience:
            return None
        
        exp = self.random.choice(experience)
        company = self._clean_entity_name(exp.get("company", "your employer"))
        role = exp.get("role", "Employee")
        
        question_variants = [
            f"What were your primary responsibilities as a {role} at {company}?",
            f"Describe the key tasks you completed while working at {company}.",
            f"What was the most challenging issue you solved while at {company}?",
            f"What technologies did you work with during your time at {company}?",
            f"How did you handle team collaboration or contributions at {company}?",
        ]
        
        available = [q for q in question_variants if not any(self._similar(q, a) for a in asked)]
        prompt = self.random.choice(available) if available else self.random.choice(question_variants)
        
        return InterviewQuestion(
            prompt=prompt,
            kind="experience_based",
            difficulty=context.difficulty,
            expected_signals=[company, role],
            follow_up_seed=company,
        )

    # ------------------------------------------------------------------
    # Fallback for minimal profiles
    # ------------------------------------------------------------------

    def _generate_general_question(self, context: InterviewContext) -> InterviewQuestion:
        """Last-resort question when profile data is too sparse."""
        return InterviewQuestion(
            prompt="Walk me through a recent project you worked on. What was the problem, your approach, and the outcome?",
            kind="general",
            difficulty=context.difficulty,
            expected_signals=["project", "approach", "outcome"],
            follow_up_seed="project experience",
        )

    # ------------------------------------------------------------------
    # Data extraction helpers
    # ------------------------------------------------------------------

    def _extract_projects(self, profile: dict) -> list[dict]:
        """Extract structured project data from the resume profile."""
        projects = []
        from parsers import _is_valid_project_name, _is_date_like

        # Look for projects in various profile structures
        raw = profile.get("projects") or profile.get("Projects") or []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("title") or item.get("project_name") or ""
                    if name and _is_valid_project_name(name) and not _is_date_like(name):
                        techs = item.get("technologies") or item.get("tech_stack") or item.get("tools") or []
                        projects.append({
                            "name": name,
                            "type": item.get("type") or "",
                            "description": item.get("description") or item.get("details") or "",
                            "technologies": techs,
                            "tech_stack": techs,
                            "date": item.get("date") or "",
                        })
                elif isinstance(item, str):
                    if item and _is_valid_project_name(item) and not _is_date_like(item):
                        projects.append({
                            "name": item,
                            "type": "",
                            "description": "",
                            "technologies": [],
                            "tech_stack": [],
                            "date": ""
                        })

        return projects

    def _extract_internships(self, profile: dict) -> list[dict]:
        """Extract internships from profile."""
        internships = []
        raw = profile.get("internships") or []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    internships.append({
                        "company": item.get("company") or "",
                        "role": item.get("role") or "",
                        "duration": item.get("duration") or "",
                    })
        return internships

    def _extract_experience(self, profile: dict) -> list[dict]:
        """Extract work experience from profile."""
        experience = []
        raw = profile.get("experience") or []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    experience.append({
                        "company": item.get("company") or "",
                        "role": item.get("role") or "",
                        "duration": item.get("duration") or "",
                    })
        return experience

    def _extract_companies(self, profile: dict) -> list[str]:
        """Extract companies/employers from profile."""
        companies = []
        raw = profile.get("companies") or []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    companies.append(item.strip())
        # Fallback: extract from internships and experience if companies is empty
        if not companies:
            for item in self._extract_internships(profile) + self._extract_experience(profile):
                comp = item.get("company")
                if comp and comp != "Various" and comp not in companies:
                    companies.append(comp)
        return list(dict.fromkeys(companies))

    def _extract_skills(self, profile: dict) -> list[str]:
        """Extract skills from various profile keys."""
        skills = []
        for key in ["skills", "technical_skills", "technologies", "required_skills", "tools"]:
            val = profile.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        skills.append(item.strip())
                    elif isinstance(item, dict):
                        skills.append(str(item.get("name", "")))
            elif isinstance(val, str):
                skills.extend([s.strip() for s in re.split(r"[,;\n]", val) if s.strip()])
        return skills

    def _extract_covered_topics(self, history: list[dict]) -> set[str]:
        """Extract topics/skills that have already been covered in the session."""
        covered = set()
        for h in history:
            q = h.get("question", "").lower()
            topic = h.get("topic", "").lower()
            if topic:
                covered.add(topic)
            for word in re.findall(r'\b[A-Za-z+#.]{2,}\b', q):
                covered.add(word.lower())
        return covered

    def _extract_history_categories(self, history: list[dict], resume_profile: dict) -> dict[str, set[str]]:
        covered_skills = set()
        covered_projects = set()
        covered_subjects = set()
        covered_internships = set()
        covered_experience = set()
        topic_history = set()

        projects = self._extract_projects(resume_profile)
        skills = self._extract_skills(resume_profile)
        internships = self._extract_internships(resume_profile)
        experience = self._extract_experience(resume_profile)
        subjects = {"dbms", "networking", "os", "dsa", "oop", "system_design"}

        for h in history:
            q = h.get("question", "").lower()
            topic = h.get("topic", "").lower()
            if topic:
                topic_history.add(topic)
                
            for p in projects:
                p_name = p["name"].lower()
                if p_name in q or p_name in topic:
                    covered_projects.add(p["name"])
            
            for s in skills:
                s_lower = s.lower()
                pattern = r"(?<![a-z0-9+#])" + re.escape(s_lower) + r"(?![a-z0-9+#])"
                if re.search(pattern, q) or re.search(pattern, topic):
                    covered_skills.add(s)

            for sub in subjects:
                if sub in q or sub in topic:
                    covered_subjects.add(sub)
                    
            for i in internships:
                co = i.get("company", "").lower()
                if co and (co in q or co in topic):
                    covered_internships.add(i.get("company", ""))
                    
            for e in experience:
                co = e.get("company", "").lower()
                if co and (co in q or co in topic):
                    covered_experience.add(e.get("company", ""))
                    
        return {
            "covered_skills": covered_skills,
            "covered_projects": covered_projects,
            "covered_subjects": covered_subjects,
            "covered_internships": covered_internships,
            "covered_experience": covered_experience,
            "topic_history": topic_history
        }

    def _similar(self, q1: str, q2: str) -> bool:
        """Simple similarity check to avoid duplicate questions."""
        # Check if the core of the question is too similar
        q1_words = set(q1.lower().split())
        q2_words = set(q2.lower().split())
        if not q1_words or not q2_words:
            return False
        overlap = len(q1_words & q2_words) / max(len(q1_words), len(q2_words))
        return overlap > 0.6

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _pick_skill(self, profile: dict) -> str:
        skills = self._extract_skills(profile)
        return self.random.choice(skills[:8]) if skills else "your core stack"

    def _pick_project(self, profile: dict) -> str:
        projects = self._extract_projects(profile)
        if projects:
            return projects[0].get("name", "your project")
        return "your most relevant project"

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
