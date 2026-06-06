"""Runtime settings helpers for dashboard controls.

The dashboard can switch the effective bot mode without restarting the process.
Changes are also written back to .env so the next container restart keeps them.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.config import config
from app.executor import current_mode

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
ENV_EXAMPLE_PATH = Path(__file__).resolve().parents[1] / ".env.example"

MODE_PATCHES = {
    "DRY_RUN": {
        "DRY_RUN": "true",
        "PAPER_TRADE": "true",
        "EXECUTION_ENABLED": "false",
        "BINANCE_DEMO_TRADING": "true",
    },
    "PAPER": {
        "DRY_RUN": "false",
        "PAPER_TRADE": "true",
        "EXECUTION_ENABLED": "false",
        "BINANCE_DEMO_TRADING": "true",
    },
    "BINANCE_DEMO": {
        "DRY_RUN": "false",
        "PAPER_TRADE": "false",
        "EXECUTION_ENABLED": "true",
        "BINANCE_DEMO_TRADING": "true",
    },
    "DISABLED": {
        "DRY_RUN": "false",
        "PAPER_TRADE": "false",
        "EXECUTION_ENABLED": "false",
    },
}

BOOL_KEYS = {
    "AUTO_ENTRY",
    "GUARD_ENABLED",
    "REQUIRE_MANUAL_APPROVAL",
    "EXECUTION_ENABLED",
    "DRY_RUN",
    "PAPER_TRADE",
    "BINANCE_DEMO_TRADING",
    "LEARNING_ENABLED",
}

INT_KEYS = {
    "PRICE_PRECISION",
    "QTY_PRECISION",
    "MAX_TRADES_PER_DAY",
    "MAX_CONSECUTIVE_LOSS",
    "MAX_LEVERAGE",
    "LEARNING_LOOKBACK_DAYS",
    "LEARNING_MIN_TRADES",
    "LEARNING_BLOCK_LOSS_STREAK",
}

FLOAT_KEYS = {
    "GUARD_ATR_SPIKE",
    "GUARD_VOL_SPIKE",
    "GUARD_RANGE_ATR",
    "GUARD_MOVE_PCT",
    "INITIAL_EQUITY",
    "MAX_RISK_PER_TRADE",
    "MAX_DAILY_LOSS",
    "MIN_RR",
    "LEARNING_BLOCK_WINRATE",
    "LEARNING_REDUCE_WINRATE",
    "LEARNING_RISK_MULTIPLIER",
    "LEARNING_RR_BUFFER",
}

SECRET_KEYS = {
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "OPENROUTER_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
}


def _as_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _read_key_values(path: Path) -> tuple[dict[str, str], list[dict]]:
    if not path.exists():
        return {}, []
    values = {}
    sections = []
    current = {"title": "GENERAL", "keys": []}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.strip("# =").strip()
            if title:
                if current["keys"]:
                    sections.append(current)
                current = {"title": title, "keys": []}
            continue
        if not stripped or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        values[key] = value
        current["keys"].append(key)
    if current["keys"]:
        sections.append(current)
    return values, sections


def _key_type(key: str, value: str = "") -> str:
    if key in SECRET_KEYS:
        return "secret"
    if key in BOOL_KEYS or value.lower() in ("true", "false", "yes", "no", "on", "off"):
        return "boolean"
    if key in INT_KEYS:
        return "integer"
    if key in FLOAT_KEYS:
        return "number"
    return "text"


def _known_key_order() -> list[str]:
    env_values, env_sections = _read_key_values(ENV_PATH)
    example_values, example_sections = _read_key_values(ENV_EXAMPLE_PATH)
    keys = []
    for section in env_sections + example_sections:
        for key in section["keys"]:
            if key not in keys:
                keys.append(key)
    for key in list(env_values) + list(example_values):
        if key not in keys:
            keys.append(key)
    return keys


def _write_env(values: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen = set()
    updated = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated.append(line)
            continue
        key, _value = line.split("=", 1)
        key = key.strip()
        if key in values:
            updated.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            updated.append(line)
    for key, value in values.items():
        if key not in seen:
            updated.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _apply_memory(values: dict[str, str]) -> None:
    for key, value in values.items():
        os.environ[key] = value
        if key in BOOL_KEYS:
            setattr(config, key, _as_bool(value))
        elif key in INT_KEYS and hasattr(config, key):
            setattr(config, key, int(value))
        elif key in FLOAT_KEYS and hasattr(config, key):
            setattr(config, key, float(value))
        elif hasattr(config, key):
            setattr(config, key, value)
    if "BINANCE_BASE_URL" in values:
        from app.binance_client import binance_client

        binance_client.base_url = config.BINANCE_BASE_URL


def snapshot() -> dict:
    return {
        "mode": current_mode(),
        "env_path": str(ENV_PATH),
        "dry_run": config.DRY_RUN,
        "paper_trade": config.PAPER_TRADE,
        "execution_enabled": config.EXECUTION_ENABLED,
        "binance_demo_trading": config.BINANCE_DEMO_TRADING,
        "auto_entry": config.AUTO_ENTRY,
        "guard_enabled": config.GUARD_ENABLED,
        "require_manual_approval": config.REQUIRE_MANUAL_APPROVAL,
    }


def set_mode(mode: str) -> dict:
    mode = mode.upper().strip()
    if mode == "DRY":
        mode = "DRY_RUN"
    if mode == "DEMO":
        mode = "BINANCE_DEMO"
    if mode in ("STOP", "OFF"):
        mode = "DISABLED"
    if mode not in MODE_PATCHES:
        raise ValueError("Mode harus DRY_RUN, PAPER, BINANCE_DEMO, atau DISABLED.")
    values = MODE_PATCHES[mode]
    _write_env(values)
    _apply_memory(values)
    return snapshot()


def set_bool(key: str, value: bool) -> dict:
    key = key.upper().strip()
    if key not in BOOL_KEYS:
        raise ValueError(f"Setting {key} tidak boleh diubah dari dashboard.")
    values = {key: "true" if bool(value) else "false"}
    _write_env(values)
    _apply_memory(values)
    return snapshot()


def env_snapshot() -> dict:
    env_values, env_sections = _read_key_values(ENV_PATH)
    example_values, example_sections = _read_key_values(ENV_EXAMPLE_PATH)
    merged = {**example_values, **env_values}
    sections_by_title = {}
    ordered_titles = []
    for section in example_sections + env_sections:
        title = section["title"]
        if title not in sections_by_title:
            sections_by_title[title] = []
            ordered_titles.append(title)
        for key in section["keys"]:
            if key not in sections_by_title[title]:
                sections_by_title[title].append(key)

    assigned = {key for keys in sections_by_title.values() for key in keys}
    loose_keys = [key for key in _known_key_order() if key not in assigned]
    if loose_keys:
        sections_by_title["GENERAL"] = loose_keys
        if "GENERAL" not in ordered_titles:
            ordered_titles.append("GENERAL")

    sections = []
    for title in ordered_titles:
        items = []
        for key in sections_by_title[title]:
            value = merged.get(key, "")
            item_type = _key_type(key, str(value))
            items.append(
                {
                    "key": key,
                    "type": item_type,
                    "value": "" if item_type == "secret" else value,
                    "masked": item_type == "secret",
                    "has_value": bool(value),
                    "placeholder": "unchanged" if item_type == "secret" and value else "",
                }
            )
        if items:
            sections.append({"title": title, "items": items})

    return {
        "env_path": str(ENV_PATH),
        "sections": sections,
        "secret_keys": sorted(SECRET_KEYS),
    }


def update_env_values(values: dict[str, str]) -> dict:
    allowed = set(_known_key_order())
    cleaned = {}
    for key, value in values.items():
        key = key.upper().strip()
        if key not in allowed:
            raise ValueError(f"Setting {key} tidak ada di .env/.env.example.")
        if key in SECRET_KEYS and value == "":
            continue
        value = str(value).strip()
        if key in BOOL_KEYS:
            value = "true" if _as_bool(value) else "false"
        elif key in INT_KEYS:
            value = str(int(value))
        elif key in FLOAT_KEYS:
            value = str(float(value))
        cleaned[key] = value
    if not cleaned:
        return env_snapshot()
    _write_env(cleaned)
    _apply_memory(cleaned)
    return env_snapshot()
