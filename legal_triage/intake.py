"""
legal_triage/intake.py
======================
ADK function tool: generate_intake_doc

Builds a structured, markdown-formatted intake summary document that the
user can bring to a legal aid consultation. This is the final Step 5
deliverable in the triage pipeline.

The tool receives the accumulated TriageContext (as a JSON-serialisable dict)
from the orchestrator's session state and uses the intake_drafter.MD prompt
to format all collected information into a portable document.
"""

from __future__ import annotations

import json
import os
import textwrap
import time
from datetime import datetime, timezone
from typing import Any

import openai
from dotenv import load_dotenv

# Load env vars — support both project-root .env.local and legal_triage/.env
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env.local"))
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, "legal_triage", ".env"))
load_dotenv()

_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
_openai_client = openai.Client(api_key=_OPENAI_API_KEY) if _OPENAI_API_KEY else None

_OPENAI_MODELS = ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]


def _strip_markdown_fence(text: str) -> str:
    """Remove a wrapping ``` / ```markdown fence if the model added one."""
    if not text:
        return text
    stripped = text.strip()
    # Whole-string fence
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```"):
            # Drop opening fence line
            lines = lines[1:]
            # Drop closing fence line if present
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines).strip()
    return stripped


def _call_openai(system_prompt: str, user_content: str) -> str:
    """Call OpenAI with model fallback and simple rate-limit handling."""
    if _openai_client is None:
        raise EnvironmentError("OPENAI_API_KEY is not set.")
    last_err: Exception | None = None
    for model in _OPENAI_MODELS:
        for attempt in range(3):
            try:
                resp = _openai_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.2,
                    max_tokens=2048,
                )
                return resp.choices[0].message.content.strip()
            except Exception as exc:
                last_err = exc
                if "429" in str(exc) or "Rate limit" in str(exc):
                    time.sleep(2 ** attempt)
                    break
                raise
    raise RuntimeError(f"All OpenAI models exhausted. Last error: {last_err}")


def _load_intake_drafter_prompt() -> str:
    """Load the intake drafter system prompt from disk."""
    path = os.path.join(_PROJECT_ROOT, "prompts", "intake_drafter.MD")
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# ADK Tool
# ---------------------------------------------------------------------------

def generate_intake_doc(
    user_description: str,
    primary_domain: str,
    sub_type: str,
    urgency: str,
    state: str,
    city: str,
    statutes_json: str,
    orgs_json: str,
    court_self_help_url: str,
) -> dict[str, Any]:
    """
    Generate a structured legal aid intake summary document (Markdown).

    This is the final step of the triage pipeline. It takes everything
    collected from the classifier, jurisdiction resolver, statute lookup, and
    org search, then formats it into a portable document the user can bring
    to a legal aid consultation.

    Args:
        user_description:    The user's original free-text situation description.
        primary_domain:      Top-level legal domain (e.g. "labor", "housing").
        sub_type:            Specific sub-category (e.g. "wage theft / unpaid wages").
        urgency:             Urgency level (low / medium / high / critical).
        state:               State where the legal situation occurred.
        city:                City (or "Not specified").
        statutes_json:       JSON string — list of statute summary dicts from
                             the get_statute_summary MCP tool.
        orgs_json:           JSON string — list of legal aid org dicts from the
                             search_legal_aid_orgs MCP tool.
        court_self_help_url: URL of the relevant court's self-help center
                             (or empty string if unknown).

    Returns:
        dict with keys:
            "status":   "success" | "error"
            "document": Markdown string of the intake summary (on success).
            "error":    Error message string (on failure).
    """
    try:
        statutes: list[dict] = json.loads(statutes_json) if statutes_json else []
        orgs: list[dict] = json.loads(orgs_json) if orgs_json else []
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"Invalid JSON input: {exc}"}

    generated_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build a structured context block for the LLM
    statute_block = ""
    for s in statutes:
        sol = s.get("statute_of_limitations", "Unknown")
        sol_notes = s.get("sol_notes", "")
        statute_block += (
            f"\n**{s.get('statute_name', 'Unknown')} ({s.get('citation', '')})**\n"
            f"Summary: {s.get('plain_language_summary', '')}\n"
            f"Statute of Limitations: {sol}\n"
            f"SOL Notes: {sol_notes}\n"
        )

    org_block = ""
    for org in orgs:
        org_block += (
            f"\n**{org.get('org_name', 'Unknown')}**\n"
            f"Address: {org.get('address', 'See website')}\n"
            f"Phone: {org.get('phone', 'See website')}\n"
            f"Website: {org.get('website', '')}\n"
            f"Issue types: {', '.join(org.get('issue_types', []))}\n"
            f"Eligibility: {org.get('eligibility_notes', '')}\n"
            f"Intake: {org.get('intake_process', '')}\n"
            f"Urgency capable: {org.get('urgency_capable', False)}\n"
        )

    system_prompt = _load_intake_drafter_prompt()

    user_content = textwrap.dedent(f"""
        Generate the full intake summary document using the template in your instructions.

        Context:
        - Generated date: {generated_date}
        - User description: {user_description}
        - Issue type: {primary_domain} — {sub_type}
        - Jurisdiction: {city}, {state}
        - Urgency: {urgency}
        - Court self-help URL: {court_self_help_url or 'Not available'}

        Statutes (from MCP lookup):
        {statute_block.strip() or 'No statutes retrieved.'}

        Legal Aid Organisations (from MCP lookup):
        {org_block.strip() or 'No organisations retrieved.'}

        Follow the document template exactly. Return only the Markdown document — no preamble, no code fences.
    """).strip()

    document = _strip_markdown_fence(_call_openai(system_prompt, user_content))

    return {
        "status": "success",
        "document": document,
    }
