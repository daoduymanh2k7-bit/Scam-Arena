from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


class Scenario(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9-]+$")
    label: str = Field(min_length=1, max_length=120)
    script: list[str] = Field(min_length=1, max_length=20)


class ScenarioLoadError(ValueError):
    pass


DEFAULT_SCENARIO_DIR = Path(__file__).resolve().parents[3] / "data" / "scenarios"


def _scenario_dir() -> Path:
    configured = os.getenv("SCENARIO_DIR")
    return Path(configured) if configured else DEFAULT_SCENARIO_DIR


@lru_cache(maxsize=1)
def load_scenarios() -> dict[str, Scenario]:
    directory = _scenario_dir()
    if not directory.is_dir():
        raise ScenarioLoadError(f"Không tìm thấy thư mục kịch bản: {directory}")

    scenarios: dict[str, Scenario] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            scenario = Scenario.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ScenarioLoadError(f"Kịch bản {path.name} không hợp lệ: {exc}") from exc
        if scenario.key in scenarios:
            raise ScenarioLoadError(f"Trùng mã kịch bản: {scenario.key}")
        scenarios[scenario.key] = scenario

    if not scenarios:
        raise ScenarioLoadError(f"Chưa có kịch bản JSON trong {directory}")
    return scenarios
