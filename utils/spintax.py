"""
Spintax Engine — content variation for engagement messages.
Supports nested spintax: {Hi|Hey|{What's up|Yo}} {friend|buddy}!
"""
from __future__ import annotations
import random
import re

_SPINTAX_RE = re.compile(r"\{([^{}]+)\}")


def spin(text: str) -> str:
    """Resolve all spintax in text, picking random alternatives."""
    def _pick(match):
        options = match.group(1).split("|")
        return random.choice(options).strip()

    result = text
    max_depth = 10
    for _ in range(max_depth):
        new_result = _SPINTAX_RE.sub(_pick, result)
        if new_result == result:
            break
        result = new_result
    return result


def spin_batch(text: str, count: int) -> list[str]:
    """Generate multiple unique variations of a spintax template."""
    seen = set()
    results = []
    max_attempts = count * 5
    for _ in range(max_attempts):
        if len(results) >= count:
            break
        variant = spin(text)
        if variant not in seen:
            seen.add(variant)
            results.append(variant)
    return results


def estimate_variations(text: str) -> int:
    """Estimate the number of possible unique outputs."""
    total = 1
    for match in _SPINTAX_RE.finditer(text):
        options = match.group(1).split("|")
        total *= len(options)
    return total


def validate(text: str) -> tuple[bool, str]:
    """Check if spintax syntax is valid (balanced braces)."""
    depth = 0
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth < 0:
            return False, f"Unmatched '}}' at position {i}"
    if depth != 0:
        return False, f"Unclosed '{{' — {depth} still open"
    return True, ""
