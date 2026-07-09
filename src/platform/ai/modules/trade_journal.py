"""LLM-based trade journaling AI module.

Generates a retrospective journal entry for a closed trade. When an LLM
provider is configured (provider != 'none'), a chat-completion call to
an OpenAI-compatible endpoint produces a reflective entry. Otherwise a
deterministic template journal is used as a fallback.
"""

from __future__ import annotations

import json
from platform.ai.orchestrator import AIContext, AIModule, AIPrediction
from platform.core.config import get_settings
from typing import Any

import httpx


def build_prompt(trade: dict[str, Any]) -> str:
    """Build the user-facing prompt describing a closed trade for journaling."""
    return (
        "Journal the following closed trade as a reflective trading log entry. "
        "Identify the key decision, what went well, what to improve, and assign "
        "a letter grade (A-F). Be concise (≤ 200 words).\n\n"
        f"Trade: {json.dumps(trade, default=str)}"
    )


def template_journal(trade: dict[str, Any]) -> str:
    """Deterministic fallback journal entry used when the LLM is disabled."""
    try:
        pnl = float(trade.get("pnl", 0))
    except (TypeError, ValueError):
        pnl = 0.0
    side = trade.get("side", "?")
    symbol = trade.get("symbol", "?")
    duration = trade.get("duration", "n/a")
    result = "profit" if pnl > 0 else "loss" if pnl < 0 else "breakeven"
    return (
        f"Closed {side} {symbol} for a {result} of {pnl} over {duration}. "
        f"Review entry timing, stop placement, and exit discipline."
    )


def _grade_from_pnl(pnl: float) -> str:
    if pnl > 0:
        return "A" if pnl > 0 else "B"
    if pnl < 0:
        return "D"
    return "C"


class TradeJournalAI(AIModule):
    """LLM-powered trade journaling assistant.

    Reads `closed_trade` ({entry, exit, pnl, duration, symbol, side}) from
    ctx.features. Calls an OpenAI-compatible LLM when one is configured
    to produce a reflective journal entry; falls back to a deterministic
    template when the provider is 'none'. The payload includes the entry,
    extracted lessons, and a letter grade.
    """

    name = "trade_journal"
    version = "1.0.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        trade = ctx.features.get("closed_trade", {}) or {}
        if not trade:
            return AIPrediction(
                module=self.name,
                symbol=ctx.symbol,
                direction="neutral",
                confidence=0.1,
                horizon="n/a",
                payload={"journal_entry": "", "lessons": [], "grade": ""},
            )
        settings = get_settings()
        try:
            pnl_val = float(trade.get("pnl", 0))
        except (TypeError, ValueError):
            pnl_val = 0.0
        if settings.llm_provider == "none":
            journal = template_journal(trade)
            grade = _grade_from_pnl(pnl_val)
            lessons = ["Review entry timing and risk controls"]
            return self._build(journal, lessons, grade, ctx)
        try:
            headers = {"Content-Type": "application/json"}
            api_key = settings.llm_api_key.get_secret_value()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            payload = {
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": "You are a trading coach writing journals."},
                    {"role": "user", "content": build_prompt(trade)},
                ],
                "temperature": 0.4,
            }
            base = (
                str(settings.llm_base_url) if settings.llm_base_url else "https://api.openai.com/v1"
            )
            url = base.rstrip("/") + "/chat/completions"
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            journal = data["choices"][0]["message"]["content"]
            grade = "A" if pnl_val > 0 else ("D" if pnl_val < 0 else "C")
            lessons = ["LLM-generated lesson — review coach notes"]
        except Exception as exc:
            journal = template_journal(trade) + f"\n[LLM error: {exc}]"
            grade = _grade_from_pnl(pnl_val)
            lessons = ["LLM call failed — using template"]
        return self._build(journal, lessons, grade, ctx)

    @staticmethod
    def _build(journal: str, lessons: list[str], grade: str, ctx: AIContext) -> AIPrediction:
        return AIPrediction(
            module="trade_journal",
            symbol=ctx.symbol,
            direction="neutral",
            confidence=0.7,
            horizon="n/a",
            payload={"journal_entry": journal, "lessons": lessons, "grade": grade},
        )
