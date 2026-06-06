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
}


def _as_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


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
        elif hasattr(config, key):
            setattr(config, key, value)


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
