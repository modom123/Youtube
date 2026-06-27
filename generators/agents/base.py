"""
BaseAgent — thin wrapper around Claude API for structured JSON output.
All production agents inherit from this.
"""
from __future__ import annotations
import json
import logging
import re
from typing import TypeVar, Type
from pydantic import BaseModel, ValidationError
import anthropic
import config

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None
_MAX_RETRIES = 3


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _parse_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if match:
        raw = match.group(1).strip()
    return json.loads(raw)


class BaseAgent:
    name: str = "BaseAgent"
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096
    system_prompt: str = ""

    def set_tier(self, subscription_tier: str) -> None:
        """Downgrade model for free-tier users to cut API costs."""
        tier_model = config.TIER_CLAUDE_MODEL.get(subscription_tier)
        if tier_model:
            self.model = tier_model

    def _call(self, user_message: str, output_schema: Type[T]) -> T:
        schema_json = json.dumps(output_schema.model_json_schema(), indent=2)
        full_system = (
            f"{self.system_prompt}\n\n"
            "## Output Format\n"
            "Respond with a single JSON object that strictly matches this schema. "
            "No markdown, no explanation — pure JSON only.\n\n"
            f"```json\n{schema_json}\n```"
        )

        messages = [{"role": "user", "content": user_message}]
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            response = _get_client().messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=full_system,
                messages=messages,
            )
            raw = response.content[0].text.strip()

            try:
                data = _parse_json(raw)
                return output_schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                log.warning(
                    "[%s] attempt %d/%d failed: %s",
                    self.name, attempt + 1, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES - 1:
                    # Feed the error back so Claude can self-correct
                    messages = [
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                f"Your previous response failed validation with this error:\n{exc}\n\n"
                                "Fix the JSON so it matches the schema exactly. "
                                "Make sure all required list fields have at least the minimum number of items. "
                                "Return only the corrected JSON object — no markdown, no explanation."
                            ),
                        },
                    ]

        raise last_error  # all retries exhausted

    def run(self, *args, **kwargs):
        raise NotImplementedError
