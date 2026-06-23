"""
BaseAgent — thin wrapper around Claude API for structured JSON output.
All production agents inherit from this.
"""
from __future__ import annotations
import json
import re
from typing import TypeVar, Type
from pydantic import BaseModel
import anthropic
import config

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


class BaseAgent:
    name: str = "BaseAgent"
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096
    system_prompt: str = ""

    def _call(self, user_message: str, output_schema: Type[T]) -> T:
        schema_json = json.dumps(output_schema.model_json_schema(), indent=2)
        full_system = (
            f"{self.system_prompt}\n\n"
            "## Output Format\n"
            "Respond with a single JSON object that strictly matches this schema. "
            "No markdown, no explanation — pure JSON only.\n\n"
            f"```json\n{schema_json}\n```"
        )

        response = _get_client().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=full_system,
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text.strip()

        # Strip markdown code fences if present
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
        if match:
            raw = match.group(1).strip()

        data = json.loads(raw)
        return output_schema.model_validate(data)

    def run(self, *args, **kwargs):
        raise NotImplementedError
