"""AI REST router — query module predictions + LLM assistant."""

from __future__ import annotations

from platform.ai.orchestrator import AIContext, get_ai_orchestrator
from platform.core.dependencies import CurrentUser, get_current_user

from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/ai", tags=["ai"])


class AnalyzeRequest(BaseModel):
    symbol: str
    timeframe: str = "M15"
    features: dict = {}


class AnalysisOut(BaseModel):
    symbol: str
    modules: dict[str, dict]
    composite_score: float


@router.post("/analyze", response_model=AnalysisOut)
async def analyze(
    req: AnalyzeRequest,
    user: CurrentUser = Depends(get_current_user),
) -> AnalysisOut:
    orch = get_ai_orchestrator()
    ctx = AIContext(
        org_id=user.org_id, symbol=req.symbol, timeframe=req.timeframe, features=req.features
    )
    results = await orch.analyze(ctx)
    score = orch.composite_score(results)
    return AnalysisOut(
        symbol=req.symbol,
        modules={name: p.model_dump() for name, p in results.items()},
        composite_score=score,
    )


class ChatRequest(BaseModel):
    message: str
    context: dict = {}


@router.post("/assistant/chat")
async def chat(req: ChatRequest, user: CurrentUser = Depends(get_current_user)) -> dict[str, str]:
    """Free-form chat with the LLM trading assistant.

    In production: backend builds a context bundle (recent trades, open positions,
    market regime, risk state) and calls the configured LLM provider (see
    `platform/ai/modules/llm_assistant.py`).
    """
    from platform.core.config import get_settings

    settings = get_settings()
    if settings.llm_provider == "none":
        return {"reply": "LLM assistant is disabled. Set LLM_PROVIDER in .env."}
    # TODO: real LLM call
    return {"reply": f"(stub) You said: {req.message}"}
