from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import ROOT_DIR, get_settings
from app.main import app
from app.role_blind import (
    BLIND_WITHHELD_FIELDS,
    ROLE_BLIND_PROTOCOL_VERSION,
    candidate_role_ids,
    split_perspective_for_blind_review,
    summarize_role_traces,
)
from app.roles import ROLE_MANIFEST_VERSION, ROLE_PERSPECTIVE_PROMPT_VERSION
from fastapi.testclient import TestClient

CANDIDATE_LABELS = ("A", "B", "C")
EXPECTED_CALLS = 30
CONFIRMATION_FLAG = "--confirm-30-external-calls"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the fixed M2 role blind test through the real preview endpoint. "
            "The command applies the current schema before making model calls and writes "
            "the anonymous sheet separately from the answer key."
        )
    )
    parser.add_argument(
        CONFIRMATION_FLAG,
        action="store_true",
        help="Required acknowledgement that this run can make 30 paid external preview calls.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT_DIR / "backend" / "data" / "role-evaluations",
        help="Private artifact directory (default: backend/data/role-evaluations, ignored by git).",
    )
    return parser.parse_args()


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _fixture_cases() -> list[dict[str, str]]:
    fixture_path = ROOT_DIR / "backend" / "tests" / "fixtures" / "role_regression_cases.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _trace_rows(client: TestClient) -> list[dict[str, Any]]:
    response = client.get(
        "/learner/traces",
        params={"call_source": "role_perspective_preview", "limit": 200},
    )
    response.raise_for_status()
    return response.json()


@contextmanager
def _suppress_role_bearing_repository_errors() -> Iterator[None]:
    """Keep a mid-run trace failure from printing subject_key beside A/B/C.

    Trace completeness is checked structurally after the run. Printing the SQL
    parameters here would disclose the answer key before the blind review.
    """

    repository_logger = logging.getLogger("app.repository")
    was_disabled = repository_logger.disabled
    repository_logger.disabled = True
    try:
        yield
    finally:
        repository_logger.disabled = was_disabled


def main() -> int:
    arguments = _arguments()
    if not getattr(arguments, "confirm_30_external_calls"):
        print(
            f"Refusing to call external models without {CONFIRMATION_FLAG}. "
            "Obtain explicit approval for a new 30-call run first.",
            file=sys.stderr,
        )
        return 2
    settings = get_settings()
    if not settings.dashscope_api_key and not settings.deepseek_api_key:
        print("No configured text-model API key; refusing before the first external call.", file=sys.stderr)
        return 2

    cases = _fixture_cases()
    if len(cases) * len(CANDIDATE_LABELS) != EXPECTED_CALLS:
        raise RuntimeError("固定盲测集不再对应 30 次调用，请先审查并更新成本确认。")

    started_at = datetime.now(UTC)
    run_id = f"{started_at:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    blind_path = arguments.output_dir / f"{run_id}-blind.json"
    key_path = arguments.output_dir / f"{run_id}-answer-key.json"
    blind_artifact: dict[str, Any] = {
        "protocol_version": ROLE_BLIND_PROTOCOL_VERSION,
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "manifest_version": ROLE_MANIFEST_VERSION,
        "prompt_version": ROLE_PERSPECTIVE_PROMPT_VERSION,
        "withheld_fields": list(BLIND_WITHHELD_FIELDS),
        "review_note_zh": (
            "按关注角度与表达方式判断每位候选是谁；"
            f"{'、'.join(BLIND_WITHHELD_FIELDS)} 已移入答案键，因为服务端会强制它匹配角色。"
        ),
        "completed_calls": 0,
        "cases": [],
    }
    key_artifact: dict[str, Any] = {
        "protocol_version": ROLE_BLIND_PROTOCOL_VERSION,
        "run_id": run_id,
        "warning_zh": "完成并保存去署名评审前不要打开这个文件。",
        "candidate_roles": {},
        "trace_verification": None,
    }
    _write_private_json(blind_path, blind_artifact)
    _write_private_json(key_path, key_artifact)

    with _suppress_role_bearing_repository_errors(), TestClient(
        app,
        raise_server_exceptions=False,
    ) as client:
        # TestClient enters the real app lifespan, which applies schema.sql. This
        # read then proves decision_trace is queryable before the first paid call.
        before_rows = _trace_rows(client)
        before_ids = {row["id"] for row in before_rows}
        profiles = client.get("/roles")
        profiles.raise_for_status()

        for case_index, case in enumerate(cases, start=1):
            case_result: dict[str, Any] = {
                "id": case["id"],
                "sentence_ja": case["sentence_ja"],
                "question": case["question"],
                "context_zh": case["context_zh"],
                "candidates": {},
            }
            blind_artifact["cases"].append(case_result)
            key_artifact["candidate_roles"][case["id"]] = {}
            for candidate, role_id in zip(
                CANDIDATE_LABELS,
                candidate_role_ids(case["id"]),
                strict=True,
            ):
                response = client.post(
                    f"/roles/{role_id}/preview",
                    json={
                        "sentence_ja": case["sentence_ja"],
                        "question": case["question"],
                        "context_zh": case["context_zh"],
                    },
                )
                withheld: dict[str, Any] = {}
                if response.is_success:
                    shown, withheld = split_perspective_for_blind_review(
                        response.json()["perspective"]
                    )
                    candidate_result: dict[str, Any] = {"status": "ok", "perspective": shown}
                else:
                    candidate_result = {
                        "status": "failed",
                        "http_status": response.status_code,
                        "error_zh": "这位匿名候选没有产生可评审的结构化观点。",
                    }
                case_result["candidates"][candidate] = candidate_result
                key_artifact["candidate_roles"][case["id"]][candidate] = {
                    "role_id": role_id,
                    "withheld": withheld,
                }
                blind_artifact["completed_calls"] += 1
                blind_artifact["updated_at"] = datetime.now(UTC).isoformat()
                _write_private_json(blind_path, blind_artifact)
                _write_private_json(key_path, key_artifact)
                print(f"case {case_index}/{len(cases)} candidate {candidate} finished", flush=True)

        after_rows = _trace_rows(client)
        new_rows = [row for row in after_rows if row["id"] not in before_ids]

    trace_verification = summarize_role_traces(new_rows, expected_calls=EXPECTED_CALLS)
    # A leaked answer key voids the whole run (§5.14), so prove the sheet is clean
    # before it is ever opened rather than trusting the split upstream.
    leaked = sorted(
        {
            field
            for case in blind_artifact["cases"]
            for candidate in case["candidates"].values()
            for field in candidate.get("perspective", {})
            if field in BLIND_WITHHELD_FIELDS
        }
    )
    if leaked:
        raise RuntimeError(
            f"匿名评审表泄漏了答案键字段 {leaked}，本轮作废；修好拆分后必须重新取得调用授权。"
        )
    successful_calls = sum(
        candidate["status"] == "ok"
        for case in blind_artifact["cases"]
        for candidate in case["candidates"].values()
    )
    blind_artifact["finished_at"] = datetime.now(UTC).isoformat()
    blind_artifact["successful_calls"] = successful_calls
    blind_artifact["ready_for_blind_review"] = (
        successful_calls == EXPECTED_CALLS and trace_verification["complete"]
    )
    key_artifact["trace_verification"] = trace_verification
    _write_private_json(blind_path, blind_artifact)
    _write_private_json(key_path, key_artifact)

    print(f"Anonymous review sheet: {blind_path}")
    print(f"Answer key (keep closed until review is saved): {key_path}")
    if not blind_artifact["ready_for_blind_review"]:
        print("Run is incomplete and must not be counted as an M2 blind pass.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
