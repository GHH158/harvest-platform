from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from .roles import ROLE_PERSPECTIVE_PROMPT_VERSION

ROLE_BLIND_PROTOCOL_VERSION = "m2-blind-v2"
ROLE_BLIND_PARTICIPANTS = ("aoi", "kei", "lin")


def candidate_role_ids(case_id: str) -> tuple[str, ...]:
    """Return a stable but non-obvious candidate order for one blind-test case.

    v2 deliberately uses a fresh seed namespace because the first ad-hoc run
    printed role ids beside anonymous candidates and therefore exposed its key.
    """

    role_ids = list(ROLE_BLIND_PARTICIPANTS)
    random.Random(f"{ROLE_BLIND_PROTOCOL_VERSION}:{case_id}").shuffle(role_ids)
    return tuple(role_ids)


def summarize_role_traces(
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_calls: int,
) -> dict[str, Any]:
    traces = list(rows)
    statuses = Counter(str(row.get("status")) for row in traces)
    providers = Counter(str(row.get("model_provider") or "unknown") for row in traces)
    prompt_versions = sorted({str(row.get("prompt_version") or "missing") for row in traces})
    subjects = Counter(str(row.get("subject_key") or "missing") for row in traces)
    issues: list[str] = []
    if len(traces) != expected_calls:
        issues.append(f"期望 {expected_calls} 条 role preview trace，实际 {len(traces)} 条。")
    if prompt_versions != [ROLE_PERSPECTIVE_PROMPT_VERSION]:
        issues.append(
            f"trace 的 prompt_version 应全部为 {ROLE_PERSPECTIVE_PROMPT_VERSION}，实际为 {prompt_versions}。"
        )
    unexpected_subjects = sorted(set(subjects) - set(ROLE_BLIND_PARTICIPANTS))
    if unexpected_subjects:
        issues.append(f"trace 出现非参与者主体：{unexpected_subjects}。")
    for role_id in ROLE_BLIND_PARTICIPANTS:
        expected_for_role = expected_calls // len(ROLE_BLIND_PARTICIPANTS)
        if subjects[role_id] != expected_for_role:
            issues.append(f"角色 {role_id} 应有 {expected_for_role} 条 trace，实际 {subjects[role_id]} 条。")
    return {
        "expected_calls": expected_calls,
        "recorded_traces": len(traces),
        "statuses": dict(sorted(statuses.items())),
        "providers": dict(sorted(providers.items())),
        "prompt_versions": prompt_versions,
        "subjects": dict(sorted(subjects.items())),
        "complete": not issues,
        "issues": issues,
    }
