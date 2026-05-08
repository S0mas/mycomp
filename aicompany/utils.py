"""Shared utility functions."""
from __future__ import annotations

import json
import re


def extract_json_block(text: str) -> dict | list:
    """Extract and parse a JSON block from markdown-fenced text."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    return json.loads(text)
