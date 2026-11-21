"""Loads config.toml and the .env file (no extra packages needed)."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Read KEY=value lines from .env into the environment (real env vars win)."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            os.environ.setdefault(key, value)


def load_config(path: str | Path | None = None) -> dict:
    load_dotenv()
    p = Path(path) if path else ROOT / "config.toml"
    with open(p, "rb") as f:
        return tomllib.load(f)


def effective_risk(cfg: dict, mode: str) -> dict:
    """Live mode uses the tighter [live] limits; everything else uses [risk]."""
    risk = dict(cfg["risk"])
    if mode == "live":
        for key, value in cfg.get("live", {}).items():
            if key != "enabled":
                risk[key] = value
    return risk


def resolve_path(p: str | None) -> str | None:
    if not p:
        return None
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return str(path)
