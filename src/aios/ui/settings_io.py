"""Load and persist the ``ui`` section of the user config.

Only the ``ui:`` block in ``~/.config/aiosdeck/config.yaml`` is written back —
sibling sections (``routing:``, ``model:``, ...) are preserved verbatim.
Writes are atomic (tempfile + ``os.replace``), mirroring the backlog writer.
PyYAML is a soft dependency: without it, load returns empty and save is a
logged no-op, so importers never crash in constrained environments.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from aios.config.loader import YAML_AVAILABLE

if YAML_AVAILABLE:
    import yaml  # noqa: PLC0415

logger = logging.getLogger("aios.ui.settings")

_UI_KEYS = ("theme", "accent_intensity", "compact", "refresh_interval")


def default_config_path() -> Path:
    """Resolve the user config path: ``~/.config/aiosdeck/config.yaml``."""
    return Path.home() / ".config" / "aiosdeck" / "config.yaml"


def load_ui_section(config_path: Path | str) -> dict[str, Any]:
    """Return the current ``ui:`` section as a dict (``{}`` when absent)."""
    data = _load_yaml(Path(config_path))
    section = data.get("ui")
    return section if isinstance(section, dict) else {}


def save_ui_section(config_path: Path | str, ui: dict[str, Any]) -> Path:
    """Persist the ``ui`` section, preserving every other configuration block.

    Writes atomically to ``config_path``.  When PyYAML is unavailable this is
    a logged no-op and the file is left untouched.

    Returns
    -------
    Path
        The config path that would be written (or the input path on no-op).
    """
    config_path = Path(config_path)
    if not YAML_AVAILABLE:
        logger.warning("PyYAML not installed, skipping save to %s", config_path)
        return config_path

    data = _load_yaml(config_path)
    data["ui"] = _clean_ui(ui)
    text = _dump_yaml(data)

    parent = config_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".yml", prefix=".tmp", dir=str(parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, str(config_path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return config_path


def _clean_ui(ui: dict[str, Any]) -> dict[str, Any]:
    return {key: ui[key] for key in _UI_KEYS if key in ui}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not YAML_AVAILABLE or not path.exists():
        return {}
    try:
        with open(path) as f:
            loaded = yaml.safe_load(f)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:  # noqa: BLE001
        logger.warning("Failed to parse %s; treating as empty", path, exc_info=True)
        return {}


def _dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False)
