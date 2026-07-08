"""Conversational LLM trading copilot AI module.

Replaces the stub `LLMTradingAssistant` defined in orchestrator.py with
a full implementation that wires up an OpenAI-compatible chat-completion
call. Supports the openai/anthropic/vllm/ollama providers declared in
Settings, and falls back to a deterministic template reply when the
provider is 'none'.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from platform.ai.orchestrator import AIContext, AIModule, AIPrediction
from platform.core.config import get_settings


def build_system_prompt(context: dict[str, Any]) -> str:
    """Compose a system prompt that orients the LLM to the platform state."""
    return (
        "You are ATLAS, a conversational trading copilot embedded in a "
        "multi-asset trading platform. Answer concisely and, when relevant, "
        "propose concrete trading actions. You have access to the following "
        "live context:\n\n"
        f"{json.dumps(context, default=str, indent=2)}\n\n"
        "Always consider open positions, recent trades, account state, and "
        "market regime before replying. Flag risk concerns explicitly."
    )


async def call_llm(provider: str, api_key: str, base_url: str, model: str,
                   messages: list[dict[str, str]], timeout: int) -> str:
    """Call an OpenAI-compatible chat-completions endpoint.

    Works across openai/anthropic/vllm/ollama because all four expose an
    OpenAI-shaped `/v1/chat/completions` route (Anthropic via its
    compatibility layer, vLLM/Ollama natively).
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        if provider == "anthropic":
            headers["x-api-key"] = api_key
    base = base_url or "https://api.openai.com/v1"
    payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.5}
    if provider == "anthropic":
        payload["max_tokens"] = 1024
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(base.rstrip("/") + "/chat/completions",
                                 headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def _fallback_reply(message: str, context: dict[str, Any]) -> str:
    """Local template reply used when no LLM provider is configured."""
    pos = context.get("open_positions", [])
    summary = context.get("account_summary", {})
    regime = context.get("market_regime", "unknown")
    return (
        f"(LLM disabled) Echo: {message}. Open positions: {len(pos)}. "
        f"Equity: {summary.get('equity', 'n/a')}. Regime: {regime}."
    )


class LLMTradingAssistant(AIModule):
    """Conversational LLM trading copilot.

    Reads `message` and `context_bundle` ({open_positions, recent_trades,
    account_summary, market_regime}) from ctx.features. Builds a system
    prompt describing the platform context, then dispatches a chat
    completion to the configured LLM provider. Falls back to a local
    template reply when provider == 'none' or on error.
    """
    name = "llm_assistant"
    version = "1.1.0"

    async def analyze(self, ctx: AIContext) -> AIPrediction:
        message = ctx.features.get("message", "") or ""
        context = ctx.features.get("context_bundle", {}) or {}
        settings = get_settings()
        provider = settings.llm_provider
        if provider == "none" or not message:
            reply = _fallback_reply(message, context) if message else ""
            return AIPrediction(
                module=self.name, symbol=ctx.symbol, direction="neutral",
                confidence=0.2, horizon="n/a",
                payload={"reply": reply, "suggested_actions": [],
                         "citations": [], "provider": provider},
            )
        try:
            reply = await call_llm(
                provider=provider,
                api_key=settings.llm_api_key.get_secret_value(),
                base_url=str(settings.llm_base_url) if settings.llm_base_url else "",
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": build_system_prompt(context)},
                    {"role": "user", "content": message},
                ],
                timeout=settings.llm_timeout_seconds,
            )
            confidence = 0.8
        except Exception as exc:  # noqa: BLE001
            reply = _fallback_reply(message, context) + f"\n[LLM error: {exc}]"
            confidence = 0.3
        return AIPrediction(
            module=self.name, symbol=ctx.symbol, direction="neutral",
            confidence=confidence, horizon="n/a",
            payload={
                "reply": reply,
                "suggested_actions": [],
                "citations": [],
                "provider": provider,
                "model": settings.llm_model,
            },
        )
