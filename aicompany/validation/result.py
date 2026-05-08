from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    verdict: str                           # "approved" | "rejected"
    summary: str = ""
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    proposed_fix: Any = None               # str (requirements) or dict (plan); None if approved

    @property
    def approved(self) -> bool:
        return self.verdict == "approved"

    @property
    def rejected(self) -> bool:
        return self.verdict == "rejected"

    @classmethod
    def from_lead_output(cls, text: str) -> "ValidationResult":
        """Parse lead's JSON output into a ValidationResult.

        Accepts a ```json fenced block or bare JSON.
        Normalises any verdict other than "approved" → "rejected".
        Returns a rejected result with an error summary on parse failure.
        """
        try:
            from ..utils import extract_json_block
            data = extract_json_block(text)
            if not isinstance(data, dict):
                raise ValueError("Lead output is not a JSON object")
            verdict = data.get("verdict", "rejected")
            if verdict != "approved":
                verdict = "rejected"
            return cls(
                verdict=verdict,
                summary=data.get("summary", ""),
                issues=data.get("issues", []),
                suggestions=data.get("suggestions", []),
                proposed_fix=data.get("proposed_fix"),
            )
        except Exception as exc:
            return cls(
                verdict="rejected",
                summary=f"Failed to parse validation output: {exc}",
                issues=["Lead output was not valid JSON"],
                proposed_fix=None,
            )
