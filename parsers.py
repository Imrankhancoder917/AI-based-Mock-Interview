from __future__ import annotations

import re
import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests


RESUME_SECTION_ALIASES = {
    "skills": {"skills", "technical skills", "core skills", "competencies", "proficiencies"},
    "projects": {"projects", "selected projects", "project experience", "portfolio"},
    "certifications": {"certifications", "certificates", "licenses", "accreditations"},
    "education": {"education", "academic background", "academics", "qualifications"},
    "experience": {"experience", "work experience", "professional experience", "employment history", "work history"},
}

JD_SECTION_ALIASES = {
    "required_skills": {"requirements", "required skills", "what you need", "qualifications"},
    "responsibilities": {"responsibilities", "what you'll do", "what you will do", "role", "about the role"},
    "technologies": {"tech stack", "technologies", "tools", "preferred technologies", "stack"},
}

SKILL_TOKENS = {
    "python", "flask", "fastapi", "django", "sql", "sqlalchemy", "postgresql", "mysql", "mongodb",
    "aws", "azure", "gcp", "docker", "kubernetes", "react", "javascript", "typescript", "html", "css",
    "node.js", "nodejs", "rest", "graphql", "git", "ci/cd", "machine learning", "nlp", "llm",
}


@dataclass
class ParsedDocument:
    extracted_text: str
    sections: dict[str, list[str]]


def _lazy_imports():
    import fitz  # type: ignore
    from docx import Document  # type: ignore
    from PIL import Image  # type: ignore
    return fitz, Document, Image


def _clean_lines(text: str) -> list[str]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return [line for line in lines if line]


def _normalize_heading(value: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", value.lower()).strip()


def _section_match(heading: str, aliases: set[str]) -> bool:
    normalized = _normalize_heading(heading)
    return any(normalized == alias or normalized.startswith(alias + " ") for alias in aliases)


def _extract_section_blocks(lines: list[str], aliases: dict[str, set[str]]) -> dict[str, list[str]]:
    sections = {key: [] for key in aliases}
    active_key = None

    for line in lines:
        if _section_match(line, set().union(*aliases.values())):
            for section_name, section_aliases in aliases.items():
                if _section_match(line, section_aliases):
                    active_key = section_name
                    break
            continue

        if active_key:
            if re.fullmatch(r"[A-Z][A-Za-z\s/&-]{2,}", line) and len(line.split()) <= 5:
                active_key = None
                continue
            sections[active_key].append(line)

    return {key: value for key, value in sections.items() if value}


def _section_text(lines: list[str], aliases: set[str]) -> str:
    collecting = False
    collected: list[str] = []

    for line in lines:
        if _section_match(line, aliases):
            collecting = True
            continue
        if collecting and re.fullmatch(r"[A-Z][A-Za-z\s/&-]{2,}", line) and len(line.split()) <= 5:
            break
        if collecting:
            collected.append(line)

    return "\n".join(collected).strip()


def _list_from_text(text: str) -> list[str]:
    parts = re.split(r"[\n•·|;/]", text)
    values = []
    for part in parts:
        cleaned = re.sub(r"^[-*]\s*", "", part).strip()
        if cleaned:
            values.append(cleaned)
    return values


def _extract_skills_from_text(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for token in sorted(SKILL_TOKENS, key=len, reverse=True):
        if token in lowered and token not in found:
            found.append(token)
    for match in re.findall(r"\b[A-Za-z][A-Za-z0-9+/.-]{1,}\b", text):
        lowered_match = match.lower()
        if len(lowered_match) > 2 and lowered_match not in found and re.search(r"[A-Z]|\.|/|\+", match):
            found.append(match)
    return found[:20]


def extract_text_from_pdf(file_path: Path) -> str:
    fitz, _, _ = _lazy_imports()
    document = fitz.open(file_path)
    parts = []
    for page in document:
        parts.append(page.get_text("text"))
    return "\n".join(parts)


def extract_text_from_docx(file_path: Path) -> str:
    _, Document, _ = _lazy_imports()
    document = Document(str(file_path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_text_from_image(file_path: Path) -> str:
    _, _, Image = _lazy_imports()
    import easyocr  # type: ignore

    reader = easyocr.Reader(["en"], gpu=False)
    image = Image.open(file_path)
    results = reader.readtext(image, detail=0, paragraph=True)
    return "\n".join(str(item) for item in results)


def parse_document(file_path: Path, doc_type: str) -> ParsedDocument:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        extracted_text = extract_text_from_pdf(file_path)
    elif suffix == ".docx":
        extracted_text = extract_text_from_docx(file_path)
    else:
        extracted_text = extract_text_from_image(file_path)

    lines = _clean_lines(extracted_text)
    section_aliases = RESUME_SECTION_ALIASES if doc_type == "resume" else JD_SECTION_ALIASES
    sections = _extract_section_blocks(lines, section_aliases)

    return ParsedDocument(extracted_text=extracted_text, sections=sections)


def _resume_result(parsed_document: ParsedDocument) -> dict:
    text = parsed_document.extracted_text
    lines = _clean_lines(text)
    sections = parsed_document.sections

    skills_block = sections.get("skills") or []
    skills_text = "\n".join(skills_block) if skills_block else _section_text(lines, RESUME_SECTION_ALIASES["skills"])

    return {
        "document_type": "resume",
        "summary": {
            "skills": _extract_skills_from_text(skills_text or text),
            "projects": _list_from_text("\n".join(sections.get("projects", []))),
            "certifications": _list_from_text("\n".join(sections.get("certifications", []))),
            "education": _list_from_text("\n".join(sections.get("education", []))),
            "experience": _list_from_text("\n".join(sections.get("experience", []))),
        },
    }


def _structure_resume_with_groq(parsed_document: ParsedDocument) -> dict | None:
    """Attempt to structure a resume using Groq. Returns the structured profile dict
    on success or None on failure so callers can fallback to the heuristic extractor.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    model = os.environ.get("SECONDARY_LLM_MODEL", "grok-3-mini")
    if not api_key:
        return None

    prompt = (
        "You are a resume parsing assistant. Extract and normalize the candidate profile from the provided RAW resume text.\n"
        "Return EXACTLY one JSON object and nothing else with the following keys: \n"
        "  name: string or empty string,\n"
        "  skills: array of short strings (programming languages, frameworks, concepts),\n"
        "  projects: array of short project summaries (one-liners),\n"
        "  technologies: array of technology tokens,\n"
        "  experience: array of work entries like 'Company - Role (years) - short note',\n"
        "  education: array of education entries (degree, institution, years),\n"
        "  domains: array of domain/industry tags (payments, healthcare, ml, infra, etc.)\n"
        "Normalize names and technologies. If information is missing, use empty arrays or empty string.\n"
        "Be robust to messy formatting and noisy OCR artifacts. Be deterministic (temperature 0).\n"
        "INPUT_TEXT:\n"
    )

    payload_input = {
        "text": parsed_document.extracted_text,
        "sections": parsed_document.sections,
    }

    full_prompt = prompt + json.dumps(payload_input, ensure_ascii=False)

    endpoints = [
        "https://api.groq.com/v1/responses",
        "https://api.groq.com/openai/v1/responses",
    ]

    for url in endpoints:
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "input": full_prompt, "temperature": 0.0, "max_output_tokens": 800},
                timeout=10,
            )
            resp.raise_for_status()
            body = resp.json()

            # extract candidate text from likely fields
            candidates = []
            if isinstance(body, dict):
                if "output" in body and isinstance(body["output"], str):
                    candidates.append(body["output"])
                if "outputs" in body and isinstance(body["outputs"], list):
                    for o in body["outputs"]:
                        content = o.get("content")
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "output_text":
                                    candidates.append(c.get("text", ""))
                        else:
                            candidates.append(str(content))
                if "choices" in body and isinstance(body["choices"], list):
                    for ch in body["choices"]:
                        if isinstance(ch, dict):
                            msg = ch.get("message") or {}
                            if isinstance(msg, dict):
                                candidates.append(msg.get("content", ""))
                            candidates.append(ch.get("text", ""))

            if not candidates:
                candidates.append(resp.text)

            for txt in candidates:
                if not txt or not isinstance(txt, str):
                    continue
                s = txt.strip()
                if s.startswith("```") and s.endswith("```"):
                    parts = s.split("\n", 1)
                    if len(parts) > 1:
                        s = parts[1].rsplit("\n", 1)[0]
                try:
                    obj = json.loads(s)
                    # Validate required keys
                    if all(k in obj for k in ["name", "skills", "projects", "technologies", "experience", "education", "domains"]):
                        # Ensure types
                        obj["skills"] = obj.get("skills") or []
                        obj["projects"] = obj.get("projects") or []
                        obj["technologies"] = obj.get("technologies") or []
                        obj["experience"] = obj.get("experience") or []
                        obj["education"] = obj.get("education") or []
                        obj["domains"] = obj.get("domains") or []
                        obj["name"] = str(obj.get("name") or "").strip()
                        return {
                            "document_type": "resume",
                            "summary": obj,
                        }
                except Exception:
                    continue
        except Exception:
            continue

    return None


def _jd_result(parsed_document: ParsedDocument) -> dict:
    text = parsed_document.extracted_text
    lines = _clean_lines(text)
    sections = parsed_document.sections
    required_skills_text = "\n".join(sections.get("required_skills", [])) or _section_text(lines, JD_SECTION_ALIASES["required_skills"])
    responsibilities_text = "\n".join(sections.get("responsibilities", [])) or _section_text(lines, JD_SECTION_ALIASES["responsibilities"])
    technologies_text = "\n".join(sections.get("technologies", [])) or _section_text(lines, JD_SECTION_ALIASES["technologies"])

    return {
        "document_type": "jd",
        "summary": {
            "required_skills": _extract_skills_from_text(required_skills_text or text),
            "responsibilities": _list_from_text(responsibilities_text),
            "technologies": _extract_skills_from_text(technologies_text or text),
        },
    }


def parse_uploaded_file(file_path: Path, doc_type: str) -> dict:
    parsed_document = parse_document(file_path, doc_type)
    if doc_type == "resume":
        # Attempt Groq-based structuring; fall back to legacy extractor
        structured = _structure_resume_with_groq(parsed_document)
        if structured is not None:
            return structured
        return _resume_result(parsed_document)
    # For job descriptions, attempt Groq-based structuring first, then fallback
    structured_jd = None
    try:
        # lazy call to Groq structurer; keep errors from bubbling up
        from typing import Any  # pragma: no cover - trivial import
        def _try_struct_jd():
            api_key = os.environ.get("GROQ_API_KEY", "")
            if not api_key:
                return None
            # delegate to helper implemented below
            return _structure_jd_with_groq(parsed_document)

        structured_jd = _try_struct_jd()
    except Exception:
        structured_jd = None

    if structured_jd is not None:
        return structured_jd

    return _jd_result(parsed_document)


def _structure_jd_with_groq(parsed_document: ParsedDocument) -> dict | None:
    """Use Groq to structure a job description into required fields.

    Expected return format (JSON):
    {
      required_skills: ["skill", ...],
      responsibilities: ["..."],
      experience_level: "junior|mid|senior|lead|manager|any",
      domain: "payments|healthcare|ml|infrastructure|etc"
    }

    Returns a dict matching the application's JD summary format or None on failure.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return None

    model = os.environ.get("SECONDARY_LLM_MODEL", "grok-3-mini")

    system_prompt = (
        "You are a talent acquisition assistant. Extract structured fields from the RAW job description text.\n"
        "Return EXACTLY one JSON object with keys: required_skills (array), responsibilities (array), experience_level (string), domain (string).\n"
        "Normalize experience_level to one of: junior, mid, senior, lead, manager, any. If ambiguous, use 'any'.\n"
        "Be deterministic (temperature 0). If information is missing, use empty arrays or 'any' for experience_level.\n"
        "INPUT_TEXT:\n"
    )

    payload_input = {
        "text": parsed_document.extracted_text,
        "sections": parsed_document.sections,
    }

    prompt = system_prompt + json.dumps(payload_input, ensure_ascii=False)

    endpoints = [
        "https://api.groq.com/v1/responses",
        "https://api.groq.com/openai/v1/responses",
    ]

    for url in endpoints:
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "input": prompt, "temperature": 0.0, "max_output_tokens": 400},
                timeout=8,
            )
            resp.raise_for_status()
            body = resp.json()

            candidates = []
            if isinstance(body, dict):
                if "output" in body and isinstance(body["output"], str):
                    candidates.append(body["output"])
                if "outputs" in body and isinstance(body["outputs"], list):
                    for o in body["outputs"]:
                        content = o.get("content")
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "output_text":
                                    candidates.append(c.get("text", ""))
                        else:
                            candidates.append(str(content))
                if "choices" in body and isinstance(body["choices"], list):
                    for ch in body["choices"]:
                        if isinstance(ch, dict):
                            msg = ch.get("message") or {}
                            if isinstance(msg, dict):
                                candidates.append(msg.get("content", ""))
                            candidates.append(ch.get("text", ""))

            if not candidates:
                candidates.append(resp.text)

            for txt in candidates:
                if not txt or not isinstance(txt, str):
                    continue
                s = txt.strip()
                if s.startswith("```") and s.endswith("```"):
                    parts = s.split("\n", 1)
                    if len(parts) > 1:
                        s = parts[1].rsplit("\n", 1)[0]
                try:
                    obj = json.loads(s)
                    # validate keys
                    if all(k in obj for k in ["required_skills", "responsibilities", "experience_level", "domain"]):
                        # normalize types
                        return {
                            "document_type": "jd",
                            "summary": {
                                "required_skills": obj.get("required_skills") or [],
                                "responsibilities": obj.get("responsibilities") or [],
                                "experience_level": str(obj.get("experience_level") or "any"),
                                "domain": str(obj.get("domain") or ""),
                            },
                        }
                except Exception:
                    continue
        except Exception:
            continue

    return None