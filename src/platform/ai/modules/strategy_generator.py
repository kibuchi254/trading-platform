"""LLM-powered strategy code generator AI module.

Takes a natural-language strategy description and asks the LLM to emit
a complete Python `Strategy` subclass. The response is fence-extracted
and compile-checked. The payload carries the generated code, an inferred
class name, and a validation status.
"""

from __future__ import annotations

import re
from platform.ai.orchestrator import AIContext, AIModule, AIPrediction
from platform.core.config import get_settings

import httpx

_NAME_RE = re.compile(r"class\s+(\w+)\s*\(")
_FENCE_RE = re.compile(r"```(?:python)?\n(.*?)\n```", re.DOTALL)


def build_prompt(description: str) -> str:
    """Construct the LLM prompt that requests a complete Strategy subclass."""
    return (
        "You are a quantitative trading engineer. Generate a complete Python "
        "subclass of `Strategy` that implements the user's description. The "
        "class must define `name` (str) and `version` (str) attributes and an "
        "`async def on_bar(self, bar)` method. Only output code, no prose.\n\n"
        f"Description:\n{description}\n\n"
        "```python\n# Your code here\n```"
    )


def validate_strategy_code(code: str) -> tuple[bool, str]:
    """Compile-check the generated code. Returns (ok, message)."""
    if not code or not code.strip():
        return False, "Empty code"
    fence = _FENCE_RE.search(code)
    if fence:
        code = fence.group(1)
    if "class " not in code:
        return False, "Missing class definition"
    try:
        compile(code, "<strategy>", "exec")
        return True, "ok"
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc.msg} (line {exc.lineno})"


class StrategyGeneratorAI(AIModule):
    """LLM-powered strategy code generator.

    Reads `description` (natural language) from ctx.features and asks a
    configured LLM to emit a complete Python Strategy subclass. The
    response is fence-extracted, compile-checked, and returned with a
    validation status. When no LLM is configured, the module reports
    `llm_disabled` so callers can route to a fallback.
    """

    name = "strategy_generator"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        description = ctx.features.get("description", "") or ""
        if not description:
            return AIPrediction(
                module=self.name,
                symbol=ctx.symbol,
                direction="neutral",
                confidence=0.1,
                horizon="n/a",
                payload={
                    "strategy_code": "",
                    "strategy_name": "",
                    "validation_status": "no description",
                },
            )
        settings = get_settings()
        if settings.llm_provider == "none":
            return AIPrediction(
                module=self.name,
                symbol=ctx.symbol,
                direction="neutral",
                confidence=0.3,
                horizon="n/a",
                payload={
                    "strategy_code": "",
                    "strategy_name": "",
                    "validation_status": "llm_disabled",
                },
            )
        try:
            headers = {"Content-Type": "application/json"}
            api_key = settings.llm_api_key.get_secret_value()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            payload = {
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": "You are a Python trading engineer."},
                    {"role": "user", "content": build_prompt(description)},
                ],
                "temperature": 0.2,
            }
            base = (
                str(settings.llm_base_url) if settings.llm_base_url else "https://api.openai.com/v1"
            )
            url = base.rstrip("/") + "/chat/completions"
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            code = data["choices"][0]["message"]["content"]
        except Exception as exc:
            return AIPrediction(
                module=self.name,
                symbol=ctx.symbol,
                direction="neutral",
                confidence=0.2,
                horizon="n/a",
                payload={
                    "strategy_code": "",
                    "strategy_name": "",
                    "validation_status": f"llm_error: {exc}",
                },
            )
        ok, msg = validate_strategy_code(code)
        name_match = _NAME_RE.search(code)
        sname = name_match.group(1) if name_match else "GeneratedStrategy"
        return AIPrediction(
            module=self.name,
            symbol=ctx.symbol,
            direction="neutral",
            confidence=0.8 if ok else 0.3,
            horizon="n/a",
            payload={
                "strategy_code": code,
                "strategy_name": sname,
                "validation_status": "valid" if ok else f"invalid: {msg}",
            },
        )
