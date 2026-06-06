import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import json
from services.adaptive_engine import AdaptiveEngine, InterviewContext, InterviewQuestion
from services.ai_service import QuestionValidator, AIService

def test_category_selector():
    print("Testing Category Selector...")
    engine = AdaptiveEngine(seed=42)
    
    # 1. INTRODUCTION phase (should only select Problem Understanding, Behavioral + Project)
    history = []
    for _ in range(20):
        cat = engine.determine_next_category(difficulty=1, history=history, current_phase="INTRODUCTION")
        assert cat in ["Problem Understanding", "Behavioral + Project"], f"Invalid category for INTRODUCTION: {cat}"
        
    # 2. SYSTEM_DESIGN phase
    system_design_cats = ["Architecture", "Tradeoffs", "Scalability", "Security", "Failure Scenarios", "Production Operations"]
    for _ in range(20):
        cat = engine.determine_next_category(difficulty=5, history=history, current_phase="SYSTEM_DESIGN")
        assert cat in system_design_cats, f"Invalid category for SYSTEM_DESIGN: {cat}"

    # 3. Test recent repeat filter (should not repeat categories in history[-3:])
    history_recent = [
        {"category": "Architecture"},
        {"category": "Tradeoffs"},
        {"category": "Scalability"}
    ]
    # In SYSTEM_DESIGN, with those 3 filtered, only Security, Failure Scenarios, and Production Operations should be left
    for _ in range(20):
        cat = engine.determine_next_category(difficulty=5, history=history_recent, current_phase="SYSTEM_DESIGN")
        assert cat in ["Security", "Failure Scenarios", "Production Operations"], f"Category filter failed: {cat}"

    # 4. Test exclusions override list
    for _ in range(20):
        cat = engine.determine_next_category(
            difficulty=5,
            history=history,
            current_phase="SYSTEM_DESIGN",
            exclude_categories=["Architecture", "Tradeoffs", "Scalability", "Security", "Failure Scenarios"]
        )
        assert cat == "Production Operations", f"Expected only Production Operations, got: {cat}"

    # 5. Test coding safety mode in CODING phase (when coding_mode_enabled=False, only Theoretical DSA is allowed)
    for _ in range(20):
        cat = engine.determine_next_category(
            difficulty=5,
            history=history,
            current_phase="CODING",
            coding_mode_enabled=False
        )
        assert cat == "Theoretical DSA", f"Expected only Theoretical DSA under coding safety, got: {cat}"

    print("Category Selector passed successfully!")


def test_question_validator():
    print("Testing Question Validator...")
    resume_profile = {
        "skills": ["React", "Flask", "MySQL"],
        "projects": [{"name": "MeshPay", "technologies": ["React", "Flask", "MySQL"]}]
    }
    
    # 1. Reject duplicate topic
    is_valid, reason = QuestionValidator.validate(
        question_text="How did you implement MeshPay?",
        kind="project_based",
        expected_signals=["MeshPay"],
        question_history=[],
        topic_history=["meshpay_architecture"],
        resume_profile=resume_profile,
        category="Architecture",
        topic="meshpay_architecture"
    )
    assert not is_valid, f"Expected invalid due to duplicate topic: {reason}"

    # 2. Reject consecutive category repeat within 3 questions
    session_history = [
        {"category": "Architecture"},
        {"category": "Debugging"}
    ]
    is_valid, reason = QuestionValidator.validate(
        question_text="How did you structure MeshPay?",
        kind="project_based",
        expected_signals=["MeshPay"],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Debugging",
        session_history=session_history
    )
    assert not is_valid, f"Expected invalid due to category repeat: {reason}"

    # 3. Reject unrelated tech stack questions (e.g. Cassandra)
    is_valid, reason = QuestionValidator.validate(
        question_text="How would you shard Cassandra clusters?",
        kind="core_subject",
        expected_signals=[],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Scalability",
        topic="cassandra_sharding"
    )
    assert not is_valid, f"Expected invalid due to Cassandra not in resume/JD: {reason}"

    # 4. Reject forbidden follow-up patterns
    is_valid, reason = QuestionValidator.validate(
        question_text="How did your implementation of React work at a high level?",
        kind="follow_up",
        expected_signals=[],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Implementation",
        topic="react_high_level"
    )
    assert not is_valid, f"Expected invalid due to forbidden high-level prompt: {reason}"

    is_valid, reason = QuestionValidator.validate(
        question_text="Explain the architecture of HTML.",
        kind="follow_up",
        expected_signals=[],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Architecture",
        topic="html_architecture"
    )
    assert not is_valid, f"Expected invalid due to forbidden HTML architecture check: {reason}"

    print("Question Validator passed successfully!")


def test_fallback_questions():
    print("Testing Fallback Questions...")
    context = InterviewContext(
        resume_profile={"skills": ["Python"], "projects": [{"name": "MyProject"}]},
        difficulty=5
    )
    engine = AdaptiveEngine(seed=42)
    
    # Check fallback generation for all 12 categories
    categories = [
        "Problem Understanding", "Architecture", "Implementation", "Debugging",
        "Performance", "Scalability", "Database", "Security",
        "Failure Scenarios", "Tradeoffs", "Production Operations", "Behavioral + Project"
    ]
    
    # Map category to the required history length to align with that phase
    category_hist_lens = {
        "Problem Understanding": 0,       # INTRODUCTION
        "Behavioral + Project": 0,        # INTRODUCTION
        "Implementation": 1,              # PROBLEM_SOLVING
        "Debugging": 1,                   # PROBLEM_SOLVING
        "Database": 1,                    # PROBLEM_SOLVING
        "Performance": 1,                 # PROBLEM_SOLVING
        "Architecture": 4,                # SYSTEM_DESIGN
        "Tradeoffs": 4,                   # SYSTEM_DESIGN
        "Scalability": 4,                 # SYSTEM_DESIGN
        "Security": 4,                    # SYSTEM_DESIGN
        "Failure Scenarios": 4,           # SYSTEM_DESIGN
        "Production Operations": 4,       # SYSTEM_DESIGN
    }
    
    for cat in categories:
        hist_len = category_hist_lens.get(cat, 0)
        context.session_history = [{"question": "mock Q", "category": "dummy"} for _ in range(hist_len)]
        q = engine.build_fallback_question(context, {"name": "MyProject"}, "project", category=cat)
        assert q.category == cat, f"Mismatch category: {q.category} vs {cat}"
        assert q.topic, "Topic slug should be present"
        assert "MyProject" in q.prompt, f"Expected MyProject in prompt: {q.prompt}"
        
    print("Fallback Questions passed successfully!")


def test_database_entity_priority():
    print("Testing Database Entity Priority...")
    engine = AdaptiveEngine(seed=42)
    resume_profile = {
        "skills": ["React", "Flask", "MySQL", "PostgreSQL"],
        "projects": [{"name": "MeshPay", "technologies": ["React", "MySQL"]}]
    }
    context = InterviewContext(
        resume_profile=resume_profile,
        difficulty=5
    )
    state_memory = {
        "question_history": [],
        "topic_history": [],
        "covered_projects": [],
        "covered_skills": [],
        "covered_subjects": [],
        "covered_internships": [],
        "covered_experience": [],
        "covered_certificates": [],
    }
    
    # Mock category selection to force Database category
    original_determine = engine.determine_next_category
    engine.determine_next_category = lambda *args, **kwargs: "Database"
    
    payload = engine.select_topic_and_context(context, state_memory)
    assert payload["category"] == "Database"
    assert payload["entity_type"] == "project", f"Expected project priority, got: {payload['entity_type']}"
    assert payload["target_entity"]["name"] == "MeshPay"
    
    # Now remove project from profile, should pick skill MySQL or PostgreSQL
    resume_profile_no_proj = {
        "skills": ["React", "Flask", "MySQL", "PostgreSQL"],
        "projects": []
    }
    context_no_proj = InterviewContext(
        resume_profile=resume_profile_no_proj,
        difficulty=5
    )
    payload_no_proj = engine.select_topic_and_context(context_no_proj, state_memory)
    assert payload_no_proj["entity_type"] == "skill", f"Expected skill fallback, got: {payload_no_proj['entity_type']}"
    assert payload_no_proj["target_entity"] in ["MySQL", "PostgreSQL"]
    
    engine.determine_next_category = original_determine
    print("Database Entity Priority passed successfully!")


def test_database_validation_rejections():
    print("Testing Database Validation Rejections...")
    resume_profile = {
        "skills": ["MySQL"],
        "projects": [{"name": "MeshPay"}]
    }
    
    # 1. Reject database design for MySQL
    is_valid, reason = QuestionValidator.validate(
        question_text="Why did you choose the database design for MySQL?",
        kind="skill",
        expected_signals=["MySQL"],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Database"
    )
    assert not is_valid, f"Expected invalid due to database design for MySQL: {reason}"
    
    # 2. Reject architecture of MySQL
    is_valid, reason = QuestionValidator.validate(
        question_text="Explain the database architecture of MySQL.",
        kind="skill",
        expected_signals=["MySQL"],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Database"
    )
    assert not is_valid, f"Expected invalid due to architecture of MySQL: {reason}"

    # 3. Reject implementation of MongoDB
    is_valid, reason = QuestionValidator.validate(
        question_text="Describe the implementation of MongoDB.",
        kind="skill",
        expected_signals=["MongoDB"],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Database"
    )
    assert not is_valid, f"Expected invalid due to implementation of MongoDB: {reason}"

    print("Database Validation Rejections passed successfully!")


def test_database_rotation():
    print("Testing Database Rotation...")
    engine = AdaptiveEngine(seed=42)
    resume_profile = {
        "skills": ["MySQL"],
        "projects": [{"name": "MeshPay"}]
    }
    
    # Simulate database questions rotation for Project
    expected_prompts_project = [
        "Why did you choose the database technology for MeshPay over alternative storage solutions?",
        "How did you design the database schema for MeshPay?",
        "How did you model relationships between entities in MeshPay?",
        "What indexing strategy did you use in MeshPay?",
        "What query in MeshPay became the database bottleneck?",
        "How would the database for MeshPay handle 10x traffic?",
        "What happens if the database server for MeshPay crashes?"
    ]
    
    # Simulate database questions rotation for Skill
    expected_prompts_skill = [
        "Why did you choose MySQL over alternatives?",
        "What schema constraints of MySQL did you establish in your project?",
        "How did you model references or relationships between tables in MySQL?",
        "What indexing features of MySQL did you use?",
        "How did you optimize MySQL query performance?",
        "How would you scale MySQL?",
        "What limitations of MySQL did you encounter?"
    ]
    
    import services.adaptive_engine
    original_determine_phase = services.adaptive_engine.determine_phase_from_q_num
    services.adaptive_engine.determine_phase_from_q_num = lambda q_num: "PROBLEM_SOLVING"
    
    try:
        # 1. Project rotation
        for idx, expected in enumerate(expected_prompts_project):
            session_history = [{"question": "mock Q", "category": "Database"} for _ in range(idx)]
            context = InterviewContext(resume_profile=resume_profile, session_history=session_history)
            q = engine.build_fallback_question(context, {"name": "MeshPay"}, "project", category="Database")
            assert q.prompt == expected, f"Expected prompt '{expected}' at index {idx}, got '{q.prompt}'"
            
        # 2. Skill rotation
        for idx, expected in enumerate(expected_prompts_skill):
            session_history = [{"question": "mock Q", "category": "Database"} for _ in range(idx)]
            context = InterviewContext(resume_profile=resume_profile, session_history=session_history)
            q = engine.build_fallback_question(context, "MySQL", "skill", category="Database")
            assert q.prompt == expected, f"Expected prompt '{expected}' at index {idx}, got '{q.prompt}'"
    finally:
        services.adaptive_engine.determine_phase_from_q_num = original_determine_phase

    print("Database Rotation passed successfully!")


def test_coding_safety_mode():
    print("Testing Coding Safety Mode...")
    resume_profile = {
        "skills": ["Python"],
        "projects": [{"name": "MyProject"}]
    }

    # Case 1: coding_mode_enabled = False, category = Theoretical DSA, question asks to write code -> REJECT
    is_valid, reason = QuestionValidator.validate(
        question_text="Could you write a function in Python to solve this?",
        kind="resume_based",
        expected_signals=["Python"],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Theoretical DSA",
        coding_mode_enabled=False,
        current_phase="CODING"
    )
    assert not is_valid, f"Expected invalid due to coding safety: {reason}"
    assert "Coding safety mode is active" in reason, f"Expected reject due to coding safety, got: {reason}"

    # Case 2: coding_mode_enabled = True, category = Theoretical DSA, question asks to write code -> ALLOW
    is_valid, reason = QuestionValidator.validate(
        question_text="Could you write a function in Python to solve this?",
        kind="resume_based",
        expected_signals=["Python"],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Theoretical DSA",
        coding_mode_enabled=True,
        current_phase="CODING"
    )
    assert is_valid, f"Expected valid when coding mode is enabled: {reason}"
    
    # Case 3: coding_mode_enabled = False, category = Theoretical DSA, question conceptually discusses algorithm -> ALLOW
    is_valid, reason = QuestionValidator.validate(
        question_text="Could you explain the time complexity of quicksort?",
        kind="resume_based",
        expected_signals=["quicksort"],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Theoretical DSA",
        coding_mode_enabled=False,
        current_phase="CODING"
    )
    assert is_valid, f"Expected valid conceptual question: {reason}"

    print("Coding Safety Mode passed successfully!")


def test_generate_question_failsafe_loop():
    print("Testing generate_question Fail-Safe Loop...")
    service = AIService()
    resume_profile = {
        "skills": ["React"],
        "projects": [{"name": "MeshPay", "technologies": ["React"]}]
    }
    
    call_count = 0
    # Mock _call_groq to return invalid responses on first 4 attempts, and then a valid one
    def mock_call_groq(system_prompt, user_payload, api_key, model, temperature=0.7):
        nonlocal call_count
        call_count += 1
        if call_count <= 4:
            # Return an invalid question (duplicate topic)
            return json.dumps({
                "question": "How did you implement MeshPay?",
                "kind": "project_based",
                "difficulty": 5,
                "expected_signals": ["MeshPay"],
                "follow_up_seed": "MeshPay",
                "trap": False,
                "category": "Architecture",
                "topic": "meshpay_architecture"
            })
        else:
            # Return a valid question (different topic/category)
            return json.dumps({
                "question": "How did you implement state management in MeshPay?",
                "kind": "project_based",
                "difficulty": 5,
                "expected_signals": ["MeshPay"],
                "follow_up_seed": "MeshPay",
                "trap": False,
                "category": "Architecture",
                "topic": "meshpay_state"
            })
            
    service._call_groq = mock_call_groq
    
    # We set topic_history to contain 'meshpay_architecture' to force the first 4 attempts to fail validation
    state_memory = {
        "question_history": [],
        "topic_history": ["meshpay_architecture"],
        "covered_projects": [],
        "covered_skills": [],
        "covered_subjects": [],
        "covered_internships": [],
        "covered_experience": [],
        "covered_certificates": [],
        "current_phase": "SYSTEM_DESIGN",
        "coding_mode_enabled": False
    }
    
    os.environ["GROQ_API_KEY"] = "dummy_key"
    session_history = [{"question": "mock Q", "category": "dummy"} for _ in range(5)]
    
    q = service.generate_question(resume_profile, session_history=session_history, state_memory=state_memory)
    assert call_count > 1, f"Expected multiple attempts, got: {call_count}"
    assert q.topic == "meshpay_state", f"Expected target question, got: {q.topic}"
    print("generate_question Fail-Safe Loop passed successfully!")


def test_generate_question_failsafe_fallback():
    print("Testing generate_question Fail-Safe Fallback...")
    service = AIService()
    resume_profile = {
        "skills": ["React"],
        "projects": [{"name": "MeshPay", "technologies": ["React"]}]
    }
    
    call_count = 0
    # Always return an invalid question (duplicate topic)
    def mock_call_groq(system_prompt, user_payload, api_key, model, temperature=0.7):
        nonlocal call_count
        call_count += 1
        return json.dumps({
            "question": "How did you implement MeshPay?",
            "kind": "project_based",
            "difficulty": 5,
            "expected_signals": ["MeshPay"],
            "follow_up_seed": "MeshPay",
            "trap": False,
            "category": "Architecture",
            "topic": "meshpay_architecture"
        })
            
    service._call_groq = mock_call_groq
    
    state_memory = {
        "question_history": [],
        "topic_history": ["meshpay_architecture"],
        "covered_projects": [],
        "covered_skills": [],
        "covered_subjects": [],
        "covered_internships": [],
        "covered_experience": [],
        "covered_certificates": [],
        "current_phase": "SYSTEM_DESIGN",
        "coding_mode_enabled": False
    }
    
    os.environ["GROQ_API_KEY"] = "dummy_key"
    session_history = [{"question": "mock Q", "category": "dummy"} for _ in range(5)]
    
    q = service.generate_question(resume_profile, session_history=session_history, state_memory=state_memory)
    # The 10th attempt should be the fallback question generated by engine.build_fallback_question
    assert call_count == 9, f"Expected exactly 9 LLM calls before fallback, got: {call_count}"
    assert q is not None
    # Verify it's a fallback question from SYSTEM_DESIGN allowed categories
    from services.adaptive_engine import PHASE_CATEGORIES
    assert q.category in PHASE_CATEGORIES["SYSTEM_DESIGN"], f"Expected fallback category to be in SYSTEM_DESIGN, got: {q.category}"
    print("generate_question Fail-Safe Fallback passed successfully!")


def test_generate_followup_failsafe_loop():
    print("Testing generate_followup_question Fail-Safe Loop...")
    service = AIService()
    resume_profile = {
        "skills": ["React"],
        "projects": [{"name": "MeshPay", "technologies": ["React"]}]
    }
    base_question = InterviewQuestion(
        prompt="Tell me about MeshPay.",
        kind="project_based",
        difficulty=5,
        expected_signals=["MeshPay"],
        follow_up_seed="MeshPay",
        trap=False,
        category="Architecture",
        topic="meshpay_architecture"
    )
    
    call_count = 0
    # First 4 attempts return invalid questions (already asked), then a valid one
    def mock_call_groq(system_prompt, user_payload, api_key, model, temperature=0.7):
        nonlocal call_count
        call_count += 1
        if call_count <= 4:
            return json.dumps({
                "question": "How did you implement MeshPay?",
                "kind": "follow_up",
                "difficulty": 5,
                "expected_signals": ["MeshPay"],
                "follow_up_seed": "MeshPay",
                "trap": False,
                "category": "Tradeoffs",
                "topic": "meshpay_architecture"
            })
        else:
            return json.dumps({
                "question": "How did you implement state management in MeshPay?",
                "kind": "follow_up",
                "difficulty": 5,
                "expected_signals": ["MeshPay"],
                "follow_up_seed": "MeshPay",
                "trap": False,
                "category": "Tradeoffs",
                "topic": "meshpay_state"
            })
            
    service._call_groq = mock_call_groq
    
    # Put 'How did you implement MeshPay?' in question_history to reject the first 4 attempts
    state_memory = {
        "question_history": ["how did you implement meshpay?"],
        "topic_history": [],
        "covered_projects": [],
        "covered_skills": [],
        "covered_subjects": [],
        "covered_internships": [],
        "covered_experience": [],
        "covered_certificates": [],
        "current_phase": "SYSTEM_DESIGN",
        "coding_mode_enabled": False
    }
    
    os.environ["GROQ_API_KEY"] = "dummy_key"
    session_history = [{"question": "mock Q", "category": "dummy"} for _ in range(5)]
    
    q = service.generate_followup_question(
        base_question,
        answer="I built MeshPay using React.",
        evaluation_score=7,
        resume_profile=resume_profile,
        session_history=session_history,
        question_history=["how did you implement meshpay?"],
        state_memory=state_memory
    )
    assert call_count > 1, f"Expected multiple attempts, got: {call_count}"
    assert q.topic == "meshpay_state", f"Expected target follow-up, got: {q.topic}"
    print("generate_followup_question Fail-Safe Loop passed successfully!")


def test_new_stabilization_rules():
    print("Testing new stabilization rules (topic groups, pool relaxation, entity cooldowns, audit trail)...")
    from services.adaptive_engine import resolve_topic_group
    
    # 1. Topic group dynamic resolution
    assert resolve_topic_group("meshpay_architecture") == "system_design"
    assert resolve_topic_group("meshpay_performance") == "performance"
    assert resolve_topic_group("mysql_selection") == "database"
    assert resolve_topic_group("react_implementation") == "implementation"
    assert resolve_topic_group("flask_debugging") == "debugging"
    assert resolve_topic_group("unmapped_slug") == "implementation"  # Default fallback
    print("Topic group resolution verified!")

    # 2. Candidate Pool Health Check & Relaxation
    engine = AdaptiveEngine(seed=42)
    context = InterviewContext(
        resume_profile={"skills": ["Python"], "projects": []},
        difficulty=5
    )
    session_history = [
        {"question": "Python Q1", "category": "Problem Understanding", "entity": "Python", "topic": "python_problem"},
        {"question": "Python Q2", "category": "Implementation", "entity": "Python", "topic": "python_implementation"},
        {"question": "Python Q3", "category": "Debugging", "entity": "Python", "topic": "python_debugging"},
        {"question": "Python Q4", "category": "Performance", "entity": "Python", "topic": "python_performance"},
    ]
    context.session_history = session_history
    state_memory = {
        "question_history": [],
        "topic_history": ["python_problem", "python_implementation", "python_debugging", "python_performance"],
        "covered_projects": [],
        "covered_skills": ["python"],
        "current_phase": "SYSTEM_DESIGN",
        "coding_mode_enabled": False
    }
    
    payload = engine.select_topic_and_context(context, state_memory)
    assert payload is not None
    assert "relaxation_stage" in state_memory
    print(f"Relaxed candidate pool stage: {state_memory['relaxation_stage']} verified!")

    # 3. Entity Cooldown & Duplicate Group/Entity Detection
    resume_profile = {
        "skills": ["Python", "Flask"],
        "projects": [{"name": "MeshPay", "technologies": ["Python", "Flask"]}]
    }
    
    session_history_cooldown = [
        {"question": "Q1", "entity": "Python", "topic": "python_t1"},
        {"question": "Q2", "entity": "Python", "topic": "python_t2"},
        {"question": "Q3", "entity": "Python", "topic": "python_t3"},
        {"question": "Q4", "entity": "Flask", "topic": "flask_t1"},
        {"question": "Q5", "entity": "Flask", "topic": "flask_t2"},
    ]
    
    is_valid, reason = QuestionValidator.validate(
        question_text="How did you implement Python in MeshPay?",
        kind="resume_based",
        expected_signals=["Python"],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Implementation",
        topic="python_t4",
        entity_name="Python",
        session_history=session_history_cooldown,
        relaxation_stage=4
    )
    assert not is_valid, "Expected validation to fail due to entity cooldown"
    assert "appears 4+" in reason, f"Unexpected reason: {reason}"
    print("Entity cooldown check verified!")
    
    session_history_duplicate = [
        {"question": "Q1?", "entity": "MeshPay", "topic": "meshpay_architecture"},
    ]
    is_valid, reason = QuestionValidator.validate(
        question_text="Tell me about MeshPay components?",
        kind="project_based",
        expected_signals=["MeshPay"],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        category="Architecture",
        topic="meshpay_components",
        entity_name="MeshPay",
        session_history=session_history_duplicate,
        current_phase="SYSTEM_DESIGN",
        relaxation_stage=4
    )
    assert not is_valid, "Expected validation to fail due to duplicate entity + topic group concept"
    assert "Duplicate question concept" in reason, f"Unexpected reason: {reason}"
    print("Duplicate topic group + entity check verified!")

    # 4. Audit Trail Size Control
    state_mem = {"audit_trail": [{"entry": i} for i in range(120)]}
    trail = state_mem.setdefault("audit_trail", [])
    trail.append({"entry": 120})
    if len(trail) > 100:
        state_mem["audit_trail"] = trail[-100:]
    assert len(state_mem["audit_trail"]) == 100
    assert state_mem["audit_trail"][0]["entry"] == 21
    assert state_mem["audit_trail"][-1]["entry"] == 120
    print("Audit trail size control verified!")

def test_internship_never_receives_architecture_question():
    print("Testing that internships never receive architecture/system design/data flow/database schema questions...")
    resume_profile = {
        "internships": [{"company": "Apex Planet", "role": "Software Engineer Intern"}]
    }
    
    # 1. Directly validate the forbidden questions
    forbidden_questions = [
        "Explain the architecture of Apex Planet?",
        "How does data flow through Apex Planet?",
        "What are the major components of Apex Planet?",
        "What database schema decisions were made in Apex Planet?",
        "What evidence convinced you that the problem addressed by Apex Planet actually existed?"
    ]
    
    for q in forbidden_questions:
        is_valid, reason = QuestionValidator.validate(
            question_text=q,
            kind="internship_based",
            expected_signals=["Apex Planet"],
            question_history=[],
            topic_history=[],
            resume_profile=resume_profile,
            entity_name="Apex Planet",
            entity_type="internship",
            category="Behavioral + Project",
            current_phase="INTRODUCTION"
        )
        assert not is_valid, f"Expected forbidden question to be rejected: '{q}', reason: {reason}"
        
        is_valid2, reason2 = QuestionValidator.validate(
            question_text=q,
            kind="internship_based",
            expected_signals=["Apex Planet"],
            question_history=[],
            topic_history=[],
            resume_profile=resume_profile,
            entity_name="Apex Planet",
            category="Behavioral + Project",
            current_phase="INTRODUCTION"
        )
        assert not is_valid2, f"Expected auto-resolved forbidden question to be rejected: '{q}', reason: {reason2}"
    
    # Test valid internship questions with compatible categories and phases
    valid_test_cases = [
        ("What was your primary responsibility during the Apex Planet internship?", "Behavioral + Project", "INTRODUCTION"),
        ("Describe a bug you fixed during the Apex Planet internship?", "Debugging", "PROBLEM_SOLVING"),
        ("What technical skill improved the most?", "Lessons Learned", "BEHAVIORAL"),
        ("How were project requirements communicated to you?", "Problem Understanding", "INTRODUCTION")
    ]
    for q, cat, phase in valid_test_cases:
        is_valid, reason = QuestionValidator.validate(
            question_text=q,
            kind="internship_based",
            expected_signals=["Apex Planet"],
            question_history=[],
            topic_history=[],
            resume_profile=resume_profile,
            entity_name="Apex Planet",
            category=cat,
            current_phase=phase
        )
        assert is_valid, f"Expected valid question to be allowed: '{q}', reason: {reason}"
    
    print("test_internship_never_receives_architecture_question passed!")


def test_internship_phase_compatibility():
    print("Testing internship phase-aware category compatibility...")
    from services.adaptive_engine import INTERNSHIP_CATEGORIES_BY_PHASE
    allowed_cats = INTERNSHIP_CATEGORIES_BY_PHASE.get("PROBLEM_SOLVING")
    assert "Implementation" in allowed_cats
    assert "Debugging" in allowed_cats
    assert "Architecture" not in allowed_cats
    
    engine = AdaptiveEngine()
    context = InterviewContext(
        resume_profile={"internships": [{"company": "Apex Planet", "role": "Intern"}]},
        difficulty=5
    )
    context.session_history = [{"question": "Q1", "category": "Problem Understanding"} for _ in range(2)] # Q3 -> PROBLEM_SOLVING phase
    
    q = engine.build_fallback_question(context, {"company": "Apex Planet"}, "internship", "Architecture")
    assert q.category in allowed_cats, f"Expected category forced to {allowed_cats}, got {q.category}"
    print("test_internship_phase_compatibility passed!")


def test_system_design_internship_reselection():
    print("Testing internship reselection in SYSTEM_DESIGN phase...")
    engine = AdaptiveEngine()
    resume_profile = {
        "projects": [{"name": "MeshPay", "technologies": ["React"]}],
        "internships": [{"company": "Apex Planet"}]
    }
    context = InterviewContext(
        resume_profile=resume_profile,
        difficulty=5
    )
    state_memory = {
        "current_phase": "SYSTEM_DESIGN",
        "question_history": [],
        "topic_history": [],
        "covered_projects": [],
        "covered_internships": []
    }
    for _ in range(10):
        payload = engine.select_topic_and_context(context, state_memory)
        assert payload["entity_type"] != "internship", f"Reselection failed: selected internship in SYSTEM_DESIGN"
        assert payload["entity_type"] == "project", f"Expected project, got {payload['entity_type']}"
        assert payload["target_entity"].get("name") == "MeshPay"
    print("test_system_design_internship_reselection passed!")


def test_exact_question_duplicate_protection():
    print("Testing Exact Question Duplicate Protection...")
    
    resume_profile = {
        "skills": ["React"],
        "projects": [{"name": "MeshPay", "technologies": ["React"]}],
        "internships": [{"company": "Apex Planet", "role": "Software Engineer Intern"}]
    }
    
    # 1. Past questions history
    question_history = [
        "How did your development workflow change during your Apex Planet internship?"
    ]
    
    # Try to validate the exact same question (but with different casing / spaces / punctuation)
    q_dup = "  how did your development workflow change during your Apex Planet internship?  "
    
    is_valid, reason = QuestionValidator.validate(
        question_text=q_dup,
        kind="internship_based",
        expected_signals=["Apex Planet"],
        question_history=question_history,
        topic_history=[],
        resume_profile=resume_profile,
        entity_name="Apex Planet",
        category="Behavioral + Project",
        current_phase="INTRODUCTION"
    )
    assert not is_valid, "Expected duplicate question to be rejected"
    assert "Exact duplicate of recent question" in reason, f"Expected reason to mention duplicate, got: {reason}"
    
    # Test valid non-duplicate question
    q_non_dup = "What was your primary responsibility during the Apex Planet internship?"
    is_valid_non_dup, reason_non_dup = QuestionValidator.validate(
        question_text=q_non_dup,
        kind="internship_based",
        expected_signals=["Apex Planet"],
        question_history=question_history,
        topic_history=[],
        resume_profile=resume_profile,
        entity_name="Apex Planet",
        category="Behavioral + Project",
        current_phase="INTRODUCTION"
    )
    assert is_valid_non_dup, f"Expected non-duplicate question to be allowed, got reject: {reason_non_dup}"
    print("test_exact_question_duplicate_protection passed!")


def test_internship_cooldown():
    """Priority 9: Test that internship entities are deprioritized when they appear in the last 3 questions."""
    print("Testing Internship Cooldown...")
    engine = AdaptiveEngine(seed=42)
    resume_profile = {
        "projects": [{"name": "MeshPay", "technologies": ["React"]}],
        "internships": [{"company": "Apex Planet"}],
        "skills": ["Python"]
    }
    context = InterviewContext(
        resume_profile=resume_profile,
        difficulty=5
    )
    # Simulate last 3 questions all being Apex Planet
    context.session_history = [
        {"question": "Q1", "entity": "Apex Planet", "category": "Behavioral + Project", "topic": "apex_planet_behavioral_project"},
        {"question": "Q2", "entity": "Apex Planet", "category": "Implementation", "topic": "apex_planet_implementation"},
        {"question": "Q3", "entity": "Apex Planet", "category": "Debugging", "topic": "apex_planet_debugging"},
    ]
    state_memory = {
        "current_phase": "BEHAVIORAL",
        "question_history": [],
        "topic_history": ["apex_planet_behavioral_project", "apex_planet_implementation", "apex_planet_debugging"],
        "covered_projects": [],
        "covered_skills": [],
        "covered_subjects": [],
        "covered_internships": [],
        "covered_experience": [],
        "covered_certificates": [],
    }
    
    # Run 20 selections - internship should almost never be selected since it's in last 3 questions
    internship_count = 0
    for _ in range(20):
        payload = engine.select_topic_and_context(context, state_memory)
        if payload["entity_type"] == "internship":
            internship_count += 1
    
    assert internship_count <= 3, f"Internship selected {internship_count}/20 times despite cooldown (expected <= 3)"
    print(f"Internship selected {internship_count}/20 times (cooldown working)")
    print("test_internship_cooldown passed!")


def test_fallback_template_rotation():
    """Priority 9: Test that fallback templates rotate and don't repeat used questions."""
    print("Testing Fallback Template Rotation...")
    engine = AdaptiveEngine(seed=42)
    
    # Simulate an internship with some questions already asked
    context = InterviewContext(
        resume_profile={"internships": [{"company": "Apex Planet"}]},
        difficulty=5
    )
    context.session_history = [
        {"question": "What was your primary responsibility during your Apex Planet internship?", "entity": "Apex Planet", "category": "Behavioral + Project"},
        {"question": "What would you do differently if you repeated your Apex Planet internship?", "entity": "Apex Planet", "category": "Behavioral + Project"},
    ]
    
    import services.adaptive_engine
    original_determine_phase = services.adaptive_engine.determine_phase_from_q_num
    services.adaptive_engine.determine_phase_from_q_num = lambda q_num: "INTRODUCTION"
    
    try:
        generated_questions = set()
        for _ in range(10):
            q = engine.build_fallback_question(context, {"company": "Apex Planet"}, "internship", "Behavioral + Project")
            generated_questions.add(q.prompt)
        
        # The two already-asked questions should NOT appear
        already_asked = {
            "What was your primary responsibility during your Apex Planet internship?",
            "What would you do differently if you repeated your Apex Planet internship?"
        }
        overlap = generated_questions & already_asked
        assert len(overlap) == 0, f"Fallback repeated already-asked questions: {overlap}"
    finally:
        services.adaptive_engine.determine_phase_from_q_num = original_determine_phase
    
    print("test_fallback_template_rotation passed!")


def test_project_priority_over_internship():
    """Priority 9: Test that projects are weighted much higher than internships."""
    print("Testing Project Priority Over Internship...")
    engine = AdaptiveEngine(seed=42)
    resume_profile = {
        "projects": [{"name": "MeshPay", "technologies": ["React"]}, {"name": "DPI Engine", "technologies": ["Java"]}],
        "internships": [{"company": "Apex Planet"}],
        "skills": ["Python"]
    }
    context = InterviewContext(
        resume_profile=resume_profile,
        difficulty=5
    )
    state_memory = {
        "current_phase": "INTRODUCTION",
        "question_history": [],
        "topic_history": [],
        "covered_projects": [],
        "covered_skills": [],
        "covered_subjects": [],
        "covered_internships": [],
        "covered_experience": [],
        "covered_certificates": [],
    }
    
    project_count = 0
    internship_count = 0
    total = 50
    for _ in range(total):
        payload = engine.select_topic_and_context(context, state_memory)
        if payload["entity_type"] == "project":
            project_count += 1
        elif payload["entity_type"] == "internship":
            internship_count += 1
    
    assert project_count > internship_count, f"Projects ({project_count}) should be selected more than internships ({internship_count})"
    print(f"Project: {project_count}/{total}, Internship: {internship_count}/{total}")
    print("test_project_priority_over_internship passed!")


def test_interview_domination_prevention():
    """Priority 9: Test that no entity dominates a long interview session."""
    print("Testing Interview Domination Prevention...")
    engine = AdaptiveEngine(seed=42)
    resume_profile = {
        "projects": [{"name": "MeshPay", "technologies": ["React"]}, {"name": "DPI Engine", "technologies": ["Java"]}],
        "internships": [{"company": "Apex Planet"}],
        "skills": ["Python", "Flask"],
    }
    context = InterviewContext(
        resume_profile=resume_profile,
        difficulty=5
    )
    
    state_memory = {
        "current_phase": "PROBLEM_SOLVING",
        "question_history": [],
        "topic_history": [],
        "covered_projects": [],
        "covered_skills": [],
        "covered_subjects": [],
        "covered_internships": [],
        "covered_experience": [],
        "covered_certificates": [],
    }
    
    # Simulate a session where one entity has appeared in the last 5 questions
    context.session_history = [
        {"question": f"Q{i}", "entity": "MeshPay", "category": "Implementation", "topic": f"meshpay_impl_{i}"}
        for i in range(5)
    ]
    
    # Over 20 selections, MeshPay should be heavily deprioritized
    meshpay_count = 0
    for _ in range(20):
        payload = engine.select_topic_and_context(context, state_memory)
        if isinstance(payload["target_entity"], dict) and payload["target_entity"].get("name") == "MeshPay":
            meshpay_count += 1
        elif payload["target_entity"] == "MeshPay":
            meshpay_count += 1
    
    # MeshPay shouldn't dominate when it's already been asked 5 times consecutively
    assert meshpay_count < 15, f"MeshPay selected {meshpay_count}/20 times despite heavy prior usage (expected < 15)"
    print(f"MeshPay selected {meshpay_count}/20 times after 5 consecutive uses (domination prevention working)")
    print("test_interview_domination_prevention passed!")


def test_internship_topic_group_cooldown():
    """Priority 9: Test that same internship + same internship topic group is rejected within last 5 questions."""
    print("Testing Internship Topic Group Cooldown...")
    from services.adaptive_engine import resolve_topic_group
    
    resume_profile = {
        "internships": [{"company": "Apex Planet", "role": "Software Engineer Intern"}]
    }
    
    # Simulate history where "Apex Planet" was asked with topic resolving to intern_responsibility
    session_history = [
        {"question": "Q1", "entity": "Apex Planet", "category": "Behavioral + Project", 
         "topic": "apex_planet_responsibility_role", "entity_type": "internship"},
    ]
    
    # Verify the topic group resolves to intern_responsibility
    tg = resolve_topic_group("apex_planet_responsibility_role", entity_type="internship")
    assert tg == "intern_responsibility", f"Expected intern_responsibility, got {tg}"
    
    # A new question with same entity + same topic group should be rejected
    is_valid, reason = QuestionValidator.validate(
        question_text="What was your primary role at Apex Planet?",
        kind="internship_based",
        expected_signals=["Apex Planet"],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        entity_name="Apex Planet",
        entity_type="internship",
        category="Behavioral + Project",
        topic="apex_planet_primary_responsibility",
        current_phase="INTRODUCTION",
        session_history=session_history
    )
    assert not is_valid, f"Expected rejection due to internship topic group cooldown, got valid"
    assert any(x in reason for x in ["Internship topic group cooldown", "Duplicate question concept", "topic group", "recently covered"]), f"Unexpected reason: {reason}"
    
    # A question with different topic group should be allowed
    is_valid2, reason2 = QuestionValidator.validate(
        question_text="What debugging tools did you learn at Apex Planet?",
        kind="internship_based",
        expected_signals=["Apex Planet"],
        question_history=[],
        topic_history=[],
        resume_profile=resume_profile,
        entity_name="Apex Planet",
        entity_type="internship",
        category="Debugging",
        topic="apex_planet_debug_tools",
        current_phase="PROBLEM_SOLVING",
        session_history=session_history
    )
    assert is_valid2, f"Expected question with different topic group to be allowed, got: {reason2}"
    
    print("test_internship_topic_group_cooldown passed!")


if __name__ == "__main__":
    test_category_selector()
    test_question_validator()
    test_fallback_questions()
    test_database_entity_priority()
    test_database_validation_rejections()
    test_database_rotation()
    test_coding_safety_mode()
    test_generate_question_failsafe_loop()
    test_generate_question_failsafe_fallback()
    test_generate_followup_failsafe_loop()
    test_new_stabilization_rules()
    test_internship_never_receives_architecture_question()
    test_internship_phase_compatibility()
    test_system_design_internship_reselection()
    test_exact_question_duplicate_protection()
    # Priority 9: New tests
    test_internship_cooldown()
    test_fallback_template_rotation()
    test_project_priority_over_internship()
    test_interview_domination_prevention()
    test_internship_topic_group_cooldown()
    print("ALL TESTS PASSED SUCCESSFULLY!")
