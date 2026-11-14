from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from app.database import get_connection_pool
from app.arena.scenario_models import TERMINAL_STAGES, Scenario


class ScenarioLoadError(ValueError):
    pass


def _validate_graph(scenario: Scenario, source: str) -> None:
    stages = {stage.id: stage for stage in scenario.stages}
    stage_ids = [stage.id for stage in scenario.stages]
    if len(stages) != len(stage_ids):
        raise ScenarioLoadError(f"{source}: có stage id bị trùng.")
    if scenario.start_stage_id not in stages:
        raise ScenarioLoadError(f"{source}: start_stage_id '{scenario.start_stage_id}' không tồn tại.")

    edges: dict[str, set[str]] = {stage_id: set() for stage_id in stages}
    for stage in scenario.stages:
        intents = [transition.on_intent for transition in stage.transitions]
        if len(intents) != len(set(intents)):
            raise ScenarioLoadError(f"{source}: stage '{stage.id}' có transition intent bị trùng.")

        targets = [item.next_stage_id for item in stage.transitions]
        targets.extend((stage.default_next_stage_id, stage.timeout_next_stage_id))
        for target in targets:
            if target not in stages and target not in TERMINAL_STAGES:
                raise ScenarioLoadError(f"{source}: stage '{stage.id}' trỏ đến '{target}' không tồn tại.")
            if target in stages:
                edges[stage.id].add(target)

        if stage.timeout_next_stage_id == stage.id:
            raise ScenarioLoadError(f"{source}: timeout của stage '{stage.id}' không được quay về chính nó.")

    reachable: set[str] = set()
    stack = [scenario.start_stage_id]
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(edges[current] - reachable)
    unreachable = set(stages) - reachable
    if unreachable:
        raise ScenarioLoadError(f"{source}: stage không thể tới từ điểm bắt đầu: {sorted(unreachable)}.")

    # Require every stage to have at least one route to a terminal outcome.
    can_finish = {
        stage.id for stage in scenario.stages
        if any(
            transition.next_stage_id in TERMINAL_STAGES for transition in stage.transitions
        ) or stage.default_next_stage_id in TERMINAL_STAGES or stage.timeout_next_stage_id in TERMINAL_STAGES
    }
    changed = True
    while changed:
        changed = False
        for stage_id, targets in edges.items():
            if stage_id not in can_finish and targets & can_finish:
                can_finish.add(stage_id)
                changed = True
    if set(stages) - can_finish:
        raise ScenarioLoadError(
            f"{source}: các stage sau không có đường tới kết thúc: {sorted(set(stages) - can_finish)}."
        )

    red_flag_ids = [flag.id for flag in scenario.red_flags]
    if len(red_flag_ids) != len(set(red_flag_ids)):
        raise ScenarioLoadError(f"{source}: red_flag id bị trùng.")
    for flag in scenario.red_flags:
        if flag.stage_id not in stages:
            raise ScenarioLoadError(f"{source}: red_flag '{flag.id}' trỏ đến stage không tồn tại.")

    scoring_keys: set[tuple[str | None, str]] = set()
    for rule in scenario.scoring.rules:
        if rule.stage_id is not None and rule.stage_id not in stages:
            raise ScenarioLoadError(f"{source}: scoring rule trỏ đến stage '{rule.stage_id}' không tồn tại.")
        key = (rule.stage_id, rule.intent.value)
        if key in scoring_keys:
            raise ScenarioLoadError(f"{source}: scoring rule bị trùng cho {key}.")
        scoring_keys.add(key)

    if scenario.status == "draft" and scenario.published_at is not None:
        raise ScenarioLoadError(f"{source}: kịch bản draft phải có published_at = null.")
    if scenario.status == "published" and scenario.published_at is None:
        raise ScenarioLoadError(f"{source}: kịch bản published cần có published_at.")


def _load_one(raw: dict, source: str) -> Scenario:
    try:
        scenario = Scenario.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ScenarioLoadError(f"{source}: sai schema — {details}") from exc
    _validate_graph(scenario, source)
    return scenario


@lru_cache(maxsize=1)
def load_scenarios() -> dict[str, Scenario]:
    scenarios: dict[str, Scenario] = {}
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT scenario_name, payload
            FROM scenarios
            WHERE status = 'published'
            ORDER BY scenario_name
            """
        )
        rows = cursor.fetchall()

    for row in rows:
        scenario = _load_one(row["payload"], f"PostgreSQL scenario {row['scenario_name']}")
        if scenario.id in scenarios:
            continue
        scenarios[scenario.id] = scenario

    if not scenarios:
        raise ScenarioLoadError("Chưa có kịch bản published trong PostgreSQL.")
    return scenarios


def reload_scenarios() -> None:
    load_scenarios.cache_clear()
