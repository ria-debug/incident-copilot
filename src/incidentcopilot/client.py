"""Minimal Claude client for the generation step."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class Call:
    output: dict[str, Any] | str
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class ClaudeClient:
    def __init__(self, *, model: str = "claude-opus-5", max_tokens: int = 3000):
        self.model = model
        self.max_tokens = max_tokens
        self._sdk = None

    def _client(self):
        if self._sdk is None:
            import anthropic

            self._sdk = anthropic.Anthropic()
        return self._sdk

    def complete(
        self, *, system: str, user: str, output_schema: dict[str, Any] | None = None
    ) -> Call:
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            # Low effort deliberately: the model's job here is to read the
            # supplied passages and report faithfully, not to reason its way to
            # an answer. Extra thinking on a grounded-extraction task mostly buys
            # inference the passages do not support.
            "output_config": {"effort": "low"},
        }
        if output_schema is not None:
            request["output_config"]["format"] = {"type": "json_schema", "schema": output_schema}

        try:
            resp = self._client().messages.create(**request)
        except Exception as e:  # noqa: BLE001 - reported as a failed answer, not a crash
            return Call(output={}, error=f"{type(e).__name__}: {e}")

        if resp.stop_reason == "refusal":
            return Call(output={}, error="refusal")

        text = next((b.text for b in resp.content if b.type == "text"), "")
        if output_schema is None:
            return Call(
                output=text,
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            )
        try:
            return Call(
                output=json.loads(text),
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            )
        except json.JSONDecodeError as e:
            return Call(output={}, error=f"unparseable_json: {e}")
