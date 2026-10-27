from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

RULES_PATH = Path(__file__).with_name("rules.yaml")


@lru_cache(maxsize=4)
def load_rules(path: str | None = None) -> dict[str, Any]:
    target = Path(path) if path else RULES_PATH
    with target.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("rules.yaml must be a mapping")
    return data


def clear_rules_cache() -> None:
    load_rules.cache_clear()
