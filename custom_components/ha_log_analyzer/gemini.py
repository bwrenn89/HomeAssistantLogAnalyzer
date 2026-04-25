"""Conversation/Gemini response parsing helpers."""

from __future__ import annotations

import json
import re
from typing import Any

PROMPT = """
You are an SRE assistant analyzing Home Assistant logs.
Find distinct unresolved issues and suggest concrete fixes.

Return JSON only:
{
  "issues": [
    {
      "title": "short title",
      "severity": "low|medium|high|critical",
      "description": "what is happening and impact",
      "suggested_fix": "clear and actionable fix",
      "signature_hint": "stable text used for dedup"
    }
  ]
}

Rules:
- No markdown.
- Group repeated errors.
- If no unresolved issues, return {"issues":[]}.
"""


def _extract_json(payload: str) -> dict[str, Any]:
    payload = payload.strip()
    if payload.startswith("{"):
        return json.loads(payload)

    match = re.search(r"\{.*\}", payload, re.DOTALL)
    if not match:
        raise ValueError("Gemini did not return JSON.")
    return json.loads(match.group(0))


def normalize_issues_from_text(text: str) -> list[dict[str, str]]:
    """Parse model output JSON and normalize issue dictionaries."""
    parsed = _extract_json(text)
    issues = parsed.get("issues", [])
    clean: list[dict[str, str]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        clean.append(
            {
                "title": str(issue.get("title", "Unknown issue")),
                "severity": str(issue.get("severity", "medium")),
                "description": str(issue.get("description", "")),
                "suggested_fix": str(issue.get("suggested_fix", "")),
                "signature_hint": str(issue.get("signature_hint", "")),
            }
        )
    return clean
