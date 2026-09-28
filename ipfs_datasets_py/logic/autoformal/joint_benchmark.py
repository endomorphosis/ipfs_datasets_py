"""Run ingestion, the autoencoder, and the compiler together.

Census disagreements are sealed into the accelerate supervisor while later
sentences are still being scored. A claimed goal carries the repair-packet
schema, the holdout scores, and the stitch keys. Nothing here is an admit,
and the compiler is not imported.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .family_supervision import FAMILY_NAMES, census_autoencoder_span, supervisor_repair_goals
from .supervisor_queue import SCHEMA, enqueue_repairs

_PACKET_KEYS = (
    "allowed_edit_paths",
    "code_identity",
    "model_identity",
    "preserve",
    "regression_tests",
    "release_id",
    "replace",
    "schema",
)


def packet_schema_gaps(packet: Mapping[str, Any]) -> list[str]:
    """Names of repair-packet fields a supervisor job still lacks."""

    missing = [key for key in _PACKET_KEYS if not packet.get(key)]
    if packet.get("schema") != SCHEMA:
        missing.append("schema_version")
    row = packet.get("row") if isinstance(packet.get("row"), Mapping) else {}
    capture = row.get("capture") if isinstance(row.get("capture"), Mapping) else {}
    for key in ("text", "source_span_id", "reason"):
        if not str(row.get(key) or "").strip():
            missing.append(f"row.{key}")
    scores = capture.get("holdout_scores") if isinstance(capture.get("holdout_scores"), Mapping) else {}
    if not scores:
        missing.append("row.capture.holdout_scores")
    if not isinstance(capture.get("threshold"), Mapping) or not capture.get("threshold"):
        missing.append("row.capture.threshold")
    families = list(capture.get("training_families") or [])
    if families != list(FAMILY_NAMES):
        missing.append("row.capture.training_families")
    if not isinstance(capture.get("stitch"), Mapping):
        missing.append("row.capture.stitch")
    if packet.get("admitted") is not False:
        missing.append("admitted")
    if packet.get("formalized") is not False:
        missing.append("formalized")
    return missing


def _claim_ready(
    source: Any,
    seen: set[str],
    *,
    generate: Callable[..., str] | None = None,
    scratch_root: Path | None = None,
) -> dict[str, Any] | None:
    from .supervisor_queue import read_packet

    page = source.list_tasks(status="ready", limit=20)
    for record in page.tasks:
        if record.task_cid in seen:
            continue
        body = dict(record.body or {})
        path = str(body.get("packet_path") or "")
        digest = str(body.get("packet_sha256") or "")
        if not path or not digest:
            continue
        packet = read_packet(Path(path), digest)
        gaps = packet_schema_gaps(packet)
        capture = packet["row"].get("capture") if isinstance(packet.get("row"), Mapping) else {}
        from .supervisor_router import row_for_packet

        receipt = {
            "admitted": False,
            "formalized": False,
            "operation": "supervisor_schema_check",
            "schema_gaps": gaps,
            "schema_ready": not gaps,
            "wrote_compiler": False,
        }
        source.compare_and_set_status(
            record.task_cid,
            int(record.revision),
            "in_progress",
            receipt,
        )
        seen.add(record.task_cid)
        return {
            "admitted": False,
            "formalized": False,
            "schema_gaps": gaps,
            "repair_row": row_for_packet(packet) if generate is not None and not gaps else {},
            "autoencoder_output": str((capture or {}).get("autoencoder_output") or ""),
            "schema_ready": not gaps,
            "source_span_id": str((packet.get("row") or {}).get("source_span_id") or ""),
            "task_cid": record.task_cid,
            "wrote_compiler": False,
        }
    return None


def run_joint_benchmark(
    spans: Sequence[Mapping[str, Any]],
    *,
    database: Path,
    packet_directory: Path,
    scores: Mapping[str, Any],
    decode: Callable[[str], str],
    round_index: int = 0,
    release_id: str = "joint-benchmark",
    code_identity: str = "uscode-formal-compiler",
    model_identity: str = "router-not-yet-called",
    pause_seconds: float = 0.05,
    generate: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Ingest spans while a supervisor claims each disagreement.

    ``decode`` is the autoencoder text for that span. Scoring stays outside
    the database lock so the supervisor can claim during the next census.
    """

    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import DatabaseTaskSource

    database.parent.mkdir(parents=True, exist_ok=True)
    packet_directory.mkdir(parents=True, exist_ok=True)
    claimed: list[dict[str, Any]] = []
    seen: set[str] = set()
    lock = threading.Lock()
    stop = threading.Event()
    supervisor_started = threading.Event()
    overlap = {"first_claim": 0.0, "last_census": 0.0}

    def supervise() -> None:
        supervisor_started.set()
        while not stop.is_set():
            with lock:
                item = _claim_ready(source, seen, generate=generate, scratch_root=packet_directory)
            if item is None:
                time.sleep(0.01)
                continue
            item["claimed_at"] = time.perf_counter()
            if overlap["first_claim"] == 0.0:
                overlap["first_claim"] = item["claimed_at"]
            _finish_repair(item)
            claimed.append(item)
        while True:
            with lock:
                item = _claim_ready(source, seen, generate=generate, scratch_root=packet_directory)
            if item is None:
                break
            item["claimed_at"] = time.perf_counter()
            if overlap["first_claim"] == 0.0:
                overlap["first_claim"] = item["claimed_at"]
            _finish_repair(item)
            claimed.append(item)

    def _finish_repair(item: dict[str, Any]) -> None:
        repair_row = item.pop("repair_row", None)
        autoencoder_output = str(item.pop("autoencoder_output", "") or "")
        if generate is None or not repair_row:
            item["agrees_with_autoencoder"] = False
            item["census_rerun"] = False
            item["router_called"] = False
            return
        from .supervisor_router import repair_and_recensus

        repair = repair_and_recensus(
            repair_row,
            generate=generate,
            scratch=packet_directory / str(item["task_cid"]),
            autoencoder_output=autoencoder_output,
        )
        item["agrees_with_autoencoder"] = repair.get("agrees_with_autoencoder") is True
        item["census_rerun"] = repair.get("census_rerun") is True
        item["reason"] = str(repair.get("reason") or "")
        item["router_called"] = repair.get("router_called") is True
        # Completion requires the validator's evidence. A scratch reply is not
        # that evidence, so the task goes back to ready for the supervisor drain.
        with lock:
            current = source.get(str(item["task_cid"]))
            if current is None:
                return
            try:
                source.compare_and_set_status(
                    current.task_cid,
                    int(current.revision),
                    "ready",
                    {
                        "admitted": False,
                        "agrees_with_autoencoder": item["agrees_with_autoencoder"],
                        "census_rerun": item["census_rerun"],
                        "formalized": False,
                        "operation": "supervisor_router_repair",
                        "reason": item["reason"],
                        "wrote_compiler": False,
                    },
                )
            except Exception as exc:
                item["release_error"] = type(exc).__name__

    rows: list[dict[str, Any]] = []
    enqueued = 0
    with DatabaseTaskSource(database) as source:
        worker = threading.Thread(target=supervise, name="joint-supervisor", daemon=True)
        worker.start()
        supervisor_started.wait(timeout=2)
        for span in spans:
            text = str(span.get("text") or "")
            span_id = str(span.get("source_span_id") or "")
            row = census_autoencoder_span(
                text,
                span_id,
                decode(text),
                scores,
                round_index=round_index,
            )
            row["legal_id"] = str(span.get("legal_id") or "")
            rows.append(row)
            overlap["last_census"] = time.perf_counter()
            if row.get("agrees") is True:
                continue
            goals = supervisor_repair_goals(
                [row],
                release_id=release_id,
                code_identity=code_identity,
                model_identity=model_identity,
            )
            if not goals["repair_packets"]:
                continue
            with lock:
                queued = enqueue_repairs(source, goals["repair_packets"], packet_directory=packet_directory)
            enqueued += int(queued.get("task_count") or 0)
            time.sleep(pause_seconds)
        stop.set()
        worker.join(timeout=600)
    return {
        "admitted": False,
        "claimed": claimed,
        "enqueued": enqueued,
        "formalized": False,
        "overlapped": overlap["first_claim"] != 0.0 and overlap["first_claim"] < overlap["last_census"],
        "repair_schema": SCHEMA,
        "rows": rows,
        "schema_ready": bool(claimed) and all(item["schema_ready"] for item in claimed),
        "uploaded": False,
        "wrote_compiler": False,
    }
