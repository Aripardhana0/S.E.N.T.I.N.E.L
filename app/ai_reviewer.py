"""AI Reviewer: review technical consistency through OpenRouter.

AI never overrides the deterministic risk manager. When the AI provider is not
available, this module returns a concrete rule-based explanation instead of a
generic template.
"""
import json
import logging

import httpx

from app.config import config

logger = logging.getLogger("ai_reviewer")

SYSTEM_PROMPT = """Anda adalah reviewer trading BTC Futures yang disiplin.
Tugas Anda:
1. Evaluasi konsistensi setup terhadap trend regime, indikator, entry, SL, TP, RR, dan alasan entry.
2. Dukung long saat uptrend/pullback valid, short saat downtrend/pullback valid, dan breakout saat volume/ADX/body mendukung.
3. Tolak atau watch jika RR lemah, entry mengejar harga, SL tidak logis, indikator konflik, atau volatilitas terlalu liar.
4. Jangan override risk manager. Jika risk manager menolak, verdict harus reject.
5. Reason wajib spesifik: sebutkan minimal 2 faktor angka/kondisi dari payload, bukan kalimat template.
6. Return JSON HANYA.

Confidence: "low", "medium", atau "high".
"""


def _concrete_reason(setup: dict, risk_result: dict, prefix: str) -> str:
    parts = [
        prefix,
        (
            f"{setup.get('setup_type', 'setup')} {setup.get('side', '-')}; "
            f"regime={setup.get('trend_regime', '-')}, "
            f"RR={setup.get('risk_reward', '-')}, "
            f"RSI={setup.get('rsi', '-')}, ADX={setup.get('adx', '-')}, "
            f"volume_ratio={setup.get('volume_ratio', '-')}."
        ),
    ]
    if setup.get("entry_reason"):
        parts.append(f"Entry reason: {setup['entry_reason']}")
    if risk_result.get("learning_notes"):
        parts.append(f"Learning: {risk_result['learning_notes']}")
    if risk_result.get("reason") and risk_result.get("reason") != "OK":
        parts.append(f"Risk: {risk_result['reason']}")
    return " ".join(parts)


def _fallback(setup: dict, risk_result: dict, prefix: str) -> dict:
    verdict = "watch" if risk_result.get("allowed") else "reject"
    return {
        "verdict": verdict,
        "reason": _concrete_reason(setup, risk_result, prefix),
        "risk_notes": risk_result.get("reason", ""),
        "confidence": "low",
    }


def review(setup: dict, risk_result: dict) -> dict:
    """Ask AI to review a trade plan. Always returns a valid dict."""
    if not risk_result.get("allowed"):
        return _fallback(setup, risk_result, "Risk manager menolak setup.")
    if not config.has_openrouter():
        logger.warning("OPENROUTER_API_KEY kosong, pakai fallback review.")
        return _fallback(setup, risk_result, "OpenRouter tidak aktif; review rule-based.")

    user_payload = {
        "setup": setup,
        "risk_manager": risk_result,
        "instructions": (
            'Return JSON: {"verdict":"approve|reject|watch","reason":"specific reason",'
            '"risk_notes":"specific risk notes","confidence":"low|medium|high"}'
        ),
    }
    body = {
        "model": config.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        "temperature": 0.15,
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
                headers=headers,
                json=body,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            reason = parsed.get("reason") or _concrete_reason(
                setup, risk_result, "AI tidak mengirim reason, fallback detail."
            )
            return {
                "verdict": parsed.get("verdict", "watch"),
                "reason": reason,
                "risk_notes": parsed.get("risk_notes", ""),
                "confidence": parsed.get("confidence", "low"),
            }
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as exc:
        logger.error("AI review gagal: %s", exc)
        return _fallback(setup, risk_result, "AI request gagal; review rule-based.")
