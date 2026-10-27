from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import Settings, get_settings
from app.llm.secrets import mask_secrets

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


@dataclass
class LlmResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    success: bool
    error_message: str | None = None
    stub: bool = False


def estimate_cost_usd(
    settings: Settings, input_tokens: int, output_tokens: int
) -> float:
    inp = (input_tokens / 1_000_000.0) * float(settings.llm_input_cost_per_mtok)
    out = (output_tokens / 1_000_000.0) * float(settings.llm_output_cost_per_mtok)
    return round(inp + out, 8)


def complete_text(
    *,
    system: str,
    user: str,
    settings: Settings | None = None,
    max_tokens: int = 300,
) -> LlmResult:
    """Call Anthropic Messages API. Masks secrets in prompts. Never logs the API key."""
    settings = settings or get_settings()
    system_m = mask_secrets(system)
    user_m = mask_secrets(user)
    model = settings.llm_model.strip() or "claude-sonnet-4-20250514"

    if not settings.anthropic_configured():
        # Local/dev stub so Step 5 works without a key
        stub = (
            "[Summary] Likely root cause could not be requested from Anthropic "
            "(ANTHROPIC_API_KEY unset). Based on the finding alone: "
            f"{user_m[:240].strip()}"
        )
        return LlmResult(
            text=stub[:500],
            model=f"stub:{model}",
            input_tokens=max(1, len(user_m) // 4),
            output_tokens=max(1, len(stub) // 4),
            cost_usd=0.0,
            success=True,
            stub=True,
        )

    # Key stays in local var only — never logged / never returned
    api_key = settings.anthropic_api_key.strip()
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_m,
        "messages": [{"role": "user", "content": user_m}],
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(ANTHROPIC_URL, headers=headers, json=payload)
        if resp.status_code >= 400:
            logger.warning(
                "Anthropic API error status=%s (key redacted)", resp.status_code
            )
            return LlmResult(
                text="",
                model=model,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                success=False,
                error_message=f"Anthropic HTTP {resp.status_code}",
            )
        data = resp.json()
        blocks = data.get("content") or []
        text_parts = [
            b.get("text", "")
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        text = "\n".join(p for p in text_parts if p).strip()
        usage = data.get("usage") or {}
        in_tok = int(usage.get("input_tokens") or 0)
        out_tok = int(usage.get("output_tokens") or 0)
        return LlmResult(
            text=text,
            model=str(data.get("model") or model),
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=estimate_cost_usd(settings, in_tok, out_tok),
            success=True,
        )
    except Exception as exc:
        logger.warning("Anthropic call failed: %s", type(exc).__name__)
        return LlmResult(
            text="",
            model=model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            success=False,
            error_message=f"{type(exc).__name__}",
        )
    finally:
        del api_key
        headers.pop("x-api-key", None)
