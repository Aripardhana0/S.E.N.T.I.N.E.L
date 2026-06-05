"""AI Reviewer: gunakan OpenRouter untuk review konsistensi trade plan.
AI TIDAK bisa override risk manager — hanya memberikan opini."""
import json
import logging

import httpx

from app.config import config

logger = logging.getLogger("ai_reviewer")

SYSTEM_PROMPT = """Anda adalah AI trading reviewer yang berpengalaman dalam analisis teknikal BTC.
Tugas Anda:
1. Analisis setup trading yang diberikan (entry, SL, TP, RR, indikator).
2. Review konsistensi dengan analisis teknikal (downtrend, pullback, support/resistance).
3. Berikan verdict: "approve", "reject", atau "watch".
4. Jangan pernah mencoba override risk manager — hasil risk manager sudah DETERMINISTIC.
5. Return JSON HANYA, tanpa penjelasan tambahan.

Confidence: "low" (ragu), "medium" (cukup yakin), "high" (sangat yakin).
"""

_FALLBACK = {
    "verdict": "watch",
    "reason": "AI review tidak tersedia (fallback)",
    "risk_notes": "",
    "confidence": "low",
}

def review(setup: dict, risk_result: dict) -> dict:
    """Minta AI menilai konsistensi trade plan. Selalu kembalikan dict valid."""
    if not config.has_openrouter():
        logger.warning("OPENROUTER_API_KEY kosong, lewati AI review.")
        return dict(_FALLBACK)

    user_payload = {
        "setup": setup,
        "risk_manager": risk_result,
        "instructions": (
            'Return JSON: {"verdict":"approve|reject|watch","reason":"...",'
            '"risk_notes":"...","confidence":"low|medium|high"}'
        ),
    }

    body = {
        "model": config.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
            r = client.post(
                f"{config.OPENROUTER_BASE_URL}/chat/completions",
                headers=headers, json=body,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            # Pastikan field minimum ada.
            return {
                "verdict": parsed.get("verdict", "watch"),
                "reason": parsed.get("reason", ""),
                "risk_notes": parsed.get("risk_notes", ""),
                "confidence": parsed.get("confidence", "low"),
            }
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as e:
        logger.error("AI review gagal: %s", e)
        return dict(_FALLBACK)
