"""Replay gap spans and score whether the autoencoder output compiles.

This loop does not use the cross-entropy or cosine objective. A compile
success is an engineering receipt. It does not admit the span or promote a
checkpoint. A non-empty reconstruction that still fails the compiler becomes
one open supervisor goal per failure class.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Mapping, Sequence


_EXAMPLE_LIMIT = 8
_TEXT_LIMIT = 240
_CAMPAIGN_CID = "goal:compile-replay:campaign"
_CAMPAIGN_ALIAS = "AFTD-GCR000"
_PLAN_CID = "plan:compile-replay:campaign"


def codec_reconstruct(text: str) -> str:
    """Convert span text to modal IR and back to legal text.

    This is the codec round trip. It does not call the embedding objective.
    """

    from .repair_report import codec_capture

    return str(codec_capture(text).get("decoded_text") or "")


def compile_miss(compiled: bool) -> float:
    """Loss is 1 when the reconstructed span does not compile, else 0."""

    return 0.0 if compiled else 1.0


def _merge_citations(entry: dict[str, Any], row: Mapping[str, Any]) -> None:
    """Keep Bluebook symbols from every span in the class on one goal."""

    repair = dict(entry.get("repair") or {})
    incoming = dict(row.get("repair") or {})
    citations = [str(item) for item in repair.get("citations") or [] if str(item)]
    for item in list(incoming.get("citations") or []):
        symbol = str(item or "")
        if symbol and symbol not in citations and len(citations) < 8:
            citations.append(symbol)
    if not citations:
        return
    repair["citations"] = citations
    fix = str(repair.get("fix") or incoming.get("fix") or "")
    missing = [symbol for symbol in citations if symbol not in fix]
    if missing:
        repair["fix"] = (fix + " Use the resolved citation symbols: " + ", ".join(missing) + ".").strip()
    entry["repair"] = repair


def failure_class(reason: str) -> str:
    """Class key is the diagnostic code plus fields. Trailing prose is not part of the class."""

    text = " ".join(str(reason or "").split())
    if not text:
        return "compiler_disagreement"
    return text.split(" ", 1)[0]


class FailureClassLedger:
    """One open goal per compiler failure class. A repeated class is not a new goal."""

    def __init__(self) -> None:
        self._classes: dict[str, dict[str, Any]] = {}
        self.duplicate_observations = 0

    def observe(self, row: Mapping[str, Any]) -> dict[str, Any]:
        output = str(row.get("output_text") or "").strip()
        if not output or row.get("compiled") is True:
            return {
                "admitted": False,
                "created": False,
                "duplicate": False,
                "formalized": False,
                "recorded": False,
                "wrote_compiler": False,
            }
        key = failure_class(str(row.get("compiler_reason") or row.get("compiler_status") or row.get("reason") or ""))
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        entry = self._classes.get(key)
        created = entry is None
        if entry is None:
            entry = {
                "example_outputs": [],
                "example_span_ids": [],
                "failure_class": key,
                "goal_cid": f"goal:compile-replay:{digest[:32]}",
                "goal_id": f"AFTD-GCR{digest[:12]}",
                "legal_ids": [],
                "members": set(),
                "repair": dict(row.get("repair") or {}),
                "source_span_id": f"compile-replay-{digest[:32]}",
                "task_id": f"AFTD-CR-{digest[:20]}",
            }
            self._classes[key] = entry
        else:
            self.duplicate_observations += 1
        span = str(row.get("source_span_id") or "")
        member = span or ("text:" + hashlib.sha256(output.encode("utf-8")).hexdigest()[:16])
        span_duplicate = member in entry["members"]
        if not span_duplicate:
            entry["members"].add(member)
            entry["member_count"] = len(entry["members"])
            if len(entry["example_span_ids"]) < _EXAMPLE_LIMIT:
                if span:
                    entry["example_span_ids"].append(span)
                entry["example_outputs"].append(output[:_TEXT_LIMIT])
            legal_id = str(row.get("legal_id") or "")
            if legal_id and legal_id not in entry["legal_ids"] and len(entry["legal_ids"]) < _EXAMPLE_LIMIT:
                entry["legal_ids"].append(legal_id)
            _merge_citations(entry, row)
        return {
            "admitted": False,
            "created": created,
            "duplicate": not created,
            "failure_class": key,
            "formalized": False,
            "goal_cid": entry["goal_cid"],
            "recorded": True,
            "span_duplicate": span_duplicate,
            "wrote_compiler": False,
        }

    def class_count(self) -> int:
        return len(self._classes)

    def restore(self, goals: Sequence[Mapping[str, Any]]) -> None:
        """Rebuild class rows from a Quack payload. Does not open a catalog."""

        for item in goals:
            if not isinstance(item, Mapping):
                continue
            key = failure_class(str(item.get("failure_class") or ""))
            spans = [str(span) for span in item.get("example_span_ids") or [] if str(span)]
            outputs = [str(text) for text in item.get("example_outputs") or []]
            legal_ids = [str(value) for value in item.get("legal_ids") or [] if str(value)]
            digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
            self._classes[key] = {
                "example_outputs": outputs[:_EXAMPLE_LIMIT],
                "example_span_ids": spans[:_EXAMPLE_LIMIT],
                "failure_class": key,
                "goal_cid": str(item.get("goal_cid") or f"goal:compile-replay:{digest[:32]}"),
                "goal_id": str(item.get("goal_id") or f"AFTD-GCR{digest[:12]}"),
                "legal_ids": legal_ids[:_EXAMPLE_LIMIT],
                "member_count": int(item.get("member_count") or len(spans)),
                "members": set(spans),
                "repair": dict(item.get("repair") or {}),
                "source_span_id": str(item.get("source_span_id") or f"compile-replay-{digest[:32]}"),
                "task_id": str(item.get("task_id") or f"AFTD-CR-{digest[:20]}"),
            }

    def public_goals(self) -> list[dict[str, Any]]:
        goals = []
        for key in sorted(self._classes):
            entry = self._classes[key]
            goals.append(
                {
                    "admitted": False,
                    "example_outputs": list(entry["example_outputs"]),
                    "example_span_ids": list(entry["example_span_ids"]),
                    "failure_class": key,
                    "formalized": False,
                    "goal_cid": entry["goal_cid"],
                    "goal_id": entry["goal_id"],
                    "legal_ids": list(entry["legal_ids"]),
                    "member_count": int(entry.get("member_count") or len(entry["members"])),
                    "citations": list((entry.get("repair") or {}).get("citations") or []),
                    "repair": dict(entry.get("repair") or {}),
                    "source_span_id": entry["source_span_id"],
                    "task_id": entry["task_id"],
                    "wrote_compiler": False,
                }
            )
        return goals


def replay_gap(
    span: Mapping[str, Any],
    reconstruct: Callable[[str], str],
    compile_one: Callable[[str], Mapping[str, Any]],
    goals: FailureClassLedger | None = None,
    capture: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one failed span through a reconstructor and the compiler."""

    from .repair_report import repair_report

    source = str(span.get("text") or "")
    captured = dict(capture(source) or {}) if capture is not None else {}
    output = str(captured.get("decoded_text") or reconstruct(source) or "")
    result = dict(compile_one(output) or {})
    status = str(result.get("compiler_status") or result.get("status") or "")
    compiled = status in {"compiled", "roundtrip_ok"} and bool(str(result.get("decompiled") or "").strip())
    repair = repair_report(compiler=result, autoencoder=captured)
    row = {
        "admitted": False,
        "autoencoder": repair["autoencoder"],
        "compiled": compiled,
        "compiler_reason": str(result.get("reason") or ""),
        "compiler_status": status,
        "decompiled": str(result.get("decompiled") or ""),
        "formalized": False,
        "legal_id": str(span.get("legal_id") or ""),
        "loss": compile_miss(compiled),
        "objective": "compile_replay",
        "output_text": output,
        "passed_autoencoder": bool(output.strip()),
        "reason": str(span.get("reason") or ""),
        "repair": repair,
        "source_span_id": str(span.get("source_span_id") or ""),
        "wrote_compiler": False,
    }
    if goals is not None:
        goals.observe(row)
    return row


class CompileReplayMemory:
    """Remember reconstructions that compiled. Does not update embedding losses."""

    def __init__(self) -> None:
        self.attempts = 0
        self.compiled = 0
        self.accepted: dict[str, str] = {}

    def observe(self, row: Mapping[str, Any]) -> None:
        self.attempts += 1
        if row.get("compiled") is True:
            self.compiled += 1
            span_id = str(row.get("source_span_id") or "")
            if span_id:
                self.accepted[span_id] = str(row.get("output_text") or "")

    def receipt(self) -> dict[str, Any]:
        return {
            "accepted": len(self.accepted),
            "admitted": False,
            "attempts": self.attempts,
            "compiled": self.compiled,
            "formalized": False,
            "objective": "compile_replay",
            "wrote_compiler": False,
        }


def replay_until_compiled(
    span: Mapping[str, Any],
    candidates: Sequence[str],
    compile_one: Callable[[str], Mapping[str, Any]],
    memory: CompileReplayMemory,
    goals: FailureClassLedger | None = None,
) -> dict[str, Any]:
    """Try the source, then candidate reconstructions. Keep the first that compiles."""

    span_id = str(span.get("source_span_id") or "")
    remembered = memory.accepted.get(span_id)
    if remembered:
        row = replay_gap(span, lambda _text: remembered, compile_one, goals)
        memory.observe(row)
        return row
    row = replay_gap(span, lambda text: text, compile_one, goals)
    if row["compiled"]:
        memory.observe(row)
        return row
    for candidate in candidates:
        trial = replay_gap(span, lambda _text, candidate=candidate: candidate, compile_one, goals)
        if trial["compiled"]:
            memory.observe(trial)
            return trial
    memory.observe(row)
    return row


def replay_gaps(
    spans: Sequence[Mapping[str, Any]],
    reconstruct: Callable[[str], str],
    compile_one: Callable[[str], Mapping[str, Any]],
    *,
    observe: Callable[[Mapping[str, Any]], None] | None = None,
    goals: FailureClassLedger | None = None,
    capture: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Replay a batch. ``observe`` may update a model; this module does not."""

    ledger = goals if goals is not None else FailureClassLedger()
    rows = [replay_gap(span, reconstruct, compile_one, ledger, capture=capture) for span in spans]
    for row in rows:
        if observe is not None:
            observe(row)
    compiled = sum(1 for row in rows if row["compiled"])
    return {
        "admitted": False,
        "compiled": compiled,
        "duplicate_observations": ledger.duplicate_observations,
        "failure_classes": ledger.class_count(),
        "failure_goals": ledger.public_goals(),
        "formalized": False,
        "loss": compile_miss(False) if not rows else sum(row["loss"] for row in rows) / len(rows),
        "objective": "compile_replay",
        "replayed": len(rows),
        "rows": rows,
        "wrote_compiler": False,
    }


def _intent_safe(value: Any) -> Any:
    """Supervisor goal JSON rejects floats. Scores are stored as decimal text."""

    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, Mapping):
        return {str(key): _intent_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_intent_safe(item) for item in value]
    return value


def compiler_failure_population(ledger: FailureClassLedger) -> dict[str, Any]:
    """Population for DatabaseTaskSource. One task per failure class. Does not claim."""

    from .supervisor_dispatch import attach_dispatch
    from .supervisor_loop import OBJECTIVE_ID, _mode, supervisor_population
    from .supervisor_todo import BOARD_NAMESPACE, SCHEMA, _budget, preserve_replace_for

    classes = ledger.public_goals()
    tasks = []
    goals = [
        {
            "admitted": False,
            "failure_mode": "",
            "formalized": False,
            "goal_alias": _CAMPAIGN_ALIAS,
            "goal_cid": _CAMPAIGN_CID,
            "goal_id": _CAMPAIGN_ALIAS,
            "kind": "campaign",
            "objective_id": OBJECTIVE_ID,
            "ordinal": 1,
            "parent_goal_cid": "",
            "priority": "P0",
            "resolves": [item["goal_id"] for item in classes],
            "source_span_ids": [],
            "status": "open",
            "title": "Compile-replay compiler failure classes",
            "wrote_compiler": False,
        }
    ]
    edges = []
    for index, item in enumerate(classes, start=1):
        mode = _mode(item["failure_class"])
        budget = _budget(mode)
        decision = preserve_replace_for({"reason": mode, "dropped": (item.get("repair") or {}).get("compiler", {}).get("fields") or []})
        replace = list(decision["replace"])
        repair = _intent_safe(dict(item.get("repair") or {}))
        fix = str(repair.get("fix") or "")
        if fix and fix not in replace:
            replace.append(fix)
        specific = f"compiler failure class {item['failure_class']}"
        if specific not in replace:
            replace.append(specific)
        exemplar = str((item["example_outputs"] or [""])[0])
        acceptance = fix or "Correct this compiler failure class."
        tasks.append(
            {
                "acceptance": (
                    acceptance
                    + " Do not mark the law formalized or admitted."
                    + " Do not import a compiler patch from this replay."
                ),
                "acceptance_criteria": [
                    acceptance + " Do not mark formalized or admitted."
                ],
                "autoencoder": dict((repair.get("autoencoder") or {})),
                "compiler_report": dict(repair.get("compiler") or {}),
                "edit_paths": list(repair.get("edit_paths") or []),
                "lake": dict(repair.get("lake") or {}),
                "repair": repair,
                "symbols": list(repair.get("symbols") or []),
                "admitted": False,
                "board_namespace": BOARD_NAMESPACE,
                "completion": "evidence",
                "example_outputs": list(item["example_outputs"]),
                "example_span_ids": list(item["example_span_ids"]),
                "failure_class": item["failure_class"],
                "failure_mode": item["failure_class"],
                "formalized": False,
                "goal_cid": item["goal_cid"],
                "goal_id": item["goal_id"],
                "is_schedulable": True,
                "legal_id": str((item["legal_ids"] or [""])[0]),
                "match_is_not_admit": True,
                "member_count": int(item["member_count"]),
                "objective_id": OBJECTIVE_ID,
                "ordinal": index,
                "plan_cid": _PLAN_CID,
                "preserve": list(decision["preserve"]),
                "priority": str(budget["priority"]),
                "reason": item["failure_class"],
                "replace": replace,
                "schema": SCHEMA,
                "source_span_id": item["source_span_id"],
                "source_text": exemplar,
                "status": "ready",
                "task_id": item["task_id"],
                "text": exemplar,
                "title": f"Correct {item['failure_class']}"[:220],
                "validation_commands": [
                    {"argv": ["python3", "-m", "pytest", "tests/unit/logic/test_gap_compile_replay.py", "-q"]}
                ],
                "wrote_compiler": False,
            }
        )
        goals.append(
            {
                "admitted": False,
                "citations": list(repair.get("citations") or []),
                "edit_paths": list(repair.get("edit_paths") or []),
                "error": str(repair.get("error") or ""),
                "example_outputs": list(item["example_outputs"]),
                "example_span_ids": list(item["example_span_ids"]),
                "failure_class": item["failure_class"],
                "failure_mode": item["failure_class"],
                "fix": fix,
                "formalized": False,
                "goal_alias": item["goal_id"],
                "lake": dict(repair.get("lake") or {}),
                "repair": repair,
                "symbols": list(repair.get("symbols") or []),
                "goal_cid": item["goal_cid"],
                "goal_id": item["goal_id"],
                "kind": "architecture-decision",
                "legal_ids": list(item["legal_ids"]),
                "member_count": int(item["member_count"]),
                "objective_id": OBJECTIVE_ID,
                "ordinal": index + 1,
                "parent_goal_cid": _CAMPAIGN_CID,
                "preserve": list(decision["preserve"]),
                "priority": str(budget["priority"]),
                "replace": replace,
                "resolves": [item["task_id"]],
                "source_span_ids": list(item["example_span_ids"]),
                "status": "open",
                "title": f"Compiler class {item['failure_class']}"[:220],
                "wrote_compiler": False,
            }
        )
        edges.append(
            {
                "child": item["goal_cid"],
                "child_goal_cid": item["goal_cid"],
                "edge_kind": "goal_decomposition",
                "parent": _CAMPAIGN_CID,
                "parent_goal_cid": _CAMPAIGN_CID,
            }
        )
    tree = {
        "edges": edges,
        "goal_edges": edges,
        "goals": goals,
        "objective_id": OBJECTIVE_ID,
        "plan_cid": _PLAN_CID,
        "tasks": tasks,
    }
    attach_dispatch(tree)
    return supervisor_population(tree)


def _ducklake_extension_present() -> bool:
    """Load DuckLake on a private connection. Do not attach it to the supervisor catalog."""

    try:
        import duckdb
    except ImportError:
        return False
    connection = duckdb.connect(
        ":memory:",
        config={
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
            "allow_unsigned_extensions": "false",
            "enable_external_access": "true",
        },
    )
    try:
        connection.execute("LOAD quack")
        connection.execute("LOAD ducklake")
        return True
    except Exception:
        return False
    finally:
        connection.close()


def upsert_failure_goals_through_quack(
    ledger: FailureClassLedger,
    database_path: str | Path,
) -> dict[str, Any]:
    """Upsert class goals through the supervisor owner's Quack inbox.

    The client sends the failure classes and does not open the catalog. The
    owner writes the supervisor population on its DuckDB connection. DuckLake
    can be loaded beside Quack and is not attached as a production catalog.
    """

    import sys
    import threading
    import uuid
    from pathlib import Path

    outer = Path(__file__).resolve().parents[4] / "ipfs_accelerate"
    sys.path.insert(0, str(outer))
    loaded = sys.modules.get("ipfs_accelerate_py")
    origin = str(getattr(loaded, "__file__", "") or "")
    if loaded is not None and "ipfs_datasets/ipfs_accelerate_py" in origin.replace("\\", "/"):
        for name in list(sys.modules):
            if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
                del sys.modules[name]

    from ipfs_accelerate_py.agent_supervisor.task_sources.database_task_source import (
        DatabaseTaskSource,
    )
    from ipfs_accelerate_py.agent_supervisor.task_sources.duckdb_state import (
        discover_live_quack_endpoint,
    )
    from ipfs_accelerate_py.agent_supervisor.task_sources.intent_repository import (
        IntentRepository,
    )
    from ipfs_datasets_py.duckdb_control.span_cache_quack import (
        GOAL_COMMAND,
        SupervisorGoalQuackGateway,
        SupervisorGoalTransportClient,
        handoff_paths,
    )
    from ipfs_datasets_py.ducklake.quack_catalog import (
        assert_no_production_activation,
        owner_extension_load_plan,
        promotion_gate_status,
    )

    path = Path(database_path)
    goals = ledger.public_goals()
    if not goals:
        return {
            "admitted": False,
            "classes": 0,
            "formalized": False,
            "ingested": False,
            "transport": "quack",
            "wrote_compiler": False,
        }
    assert_no_production_activation()
    discovery = discover_live_quack_endpoint(path)
    if discovery.found:
        raise RuntimeError(
            "supervisor database already has a live Quack owner; "
            "refusing a second catalog opener"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with DatabaseTaskSource(path) as prepared:
        del prepared
    import duckdb

    connection = duckdb.connect(
        str(path),
        config={
            "allow_unsigned_extensions": "false",
            "autoload_known_extensions": "false",
            "autoinstall_known_extensions": "false",
            "enable_external_access": "true",
        },
    )
    ducklake_loaded = False
    try:
        connection.execute("LOAD quack")
        connection.execute("LOAD ducklake")
        connection.execute("LOAD httpfs")
        ducklake_loaded = True
    except Exception:
        ducklake_loaded = False
    status = promotion_gate_status()
    plan = owner_extension_load_plan()

    def apply(payload: list[dict[str, Any]]) -> dict[str, Any]:
        restored = FailureClassLedger()
        restored.restore(payload)
        repository = IntentRepository(
            bound_connection=connection,
            install_schema=False,
            owner_id="compile-replay-quack-owner",
            session_id="compile-replay",
        )
        source = DatabaseTaskSource(intent=repository, install_schema=False)
        try:
            receipt = submit_compiler_failure_goals(restored, source)
        finally:
            source.close()
        goal_rows = int(connection.execute("SELECT count(*) FROM goals").fetchone()[0])
        open_rows = int(
            connection.execute(
                "SELECT count(*) FROM goals WHERE lower(status) = 'open'"
            ).fetchone()[0]
        )
        return {
            "admitted": False,
            "catalog_owner": "supervisor-duckdb",
            "classes": int(receipt["classes"]),
            "control_plane": "duckdb+quack",
            "ducklake_activation_held": bool(status["activation_held"]),
            "ducklake_held_by": [str(item) for item in status["held_by"]],
            "ducklake_loaded": ducklake_loaded,
            "explicit_load_order": [str(item) for item in plan["explicit_load_order"]],
            "formalized": False,
            "goal_cids": [str(item) for item in receipt["goal_cids"]],
            "goal_count": int(receipt.get("goal_count") or 0),
            "goal_rows": goal_rows,
            "ingested": True,
            "open_goal_rows": open_rows,
            "production_mutation_enabled": False,
            "transport": "quack",
            "wrote_compiler": False,
        }

    gateway = SupervisorGoalQuackGateway()
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            gateway.serve(apply)
            stop.wait(0.01)

    thread = threading.Thread(target=serve, name="supervisor-goal-owner")
    try:
        gateway.start()
        published = gateway.publish(path)
        thread.start()
        _endpoint_path, token_path = handoff_paths(path)
        token = token_path.read_text(encoding="utf-8").strip()
        with SupervisorGoalTransportClient(published["endpoint"], token) as client:
            reply = client.request(
                GOAL_COMMAND,
                {"goals": goals},
                "failure-goals-" + uuid.uuid4().hex,
                timeout=60,
            )
        reply["listen_uri"] = published["endpoint"]
        reply["admitted"] = False
        reply["formalized"] = False
        reply["wrote_compiler"] = False
        return reply
    finally:
        stop.set()
        if thread.ident is not None:
            thread.join(timeout=2)
        try:
            gateway.close()
        finally:
            connection.close()


def submit_compiler_failure_goals(ledger: FailureClassLedger, source: Any | None) -> dict[str, Any]:
    """Upsert class goals into the accelerate supervisor. Does not claim or import a patch."""

    classes = ledger.public_goals()
    receipt: dict[str, Any] = {
        "admitted": False,
        "classes": len(classes),
        "formalized": False,
        "goal_cids": [item["goal_cid"] for item in classes],
        "ingested": False,
        "wrote_compiler": False,
    }
    if not classes or source is None:
        return receipt
    from .supervisor_loop import ingest_population

    ingested = ingest_population(source, compiler_failure_population(ledger))
    receipt.update(ingested)
    receipt["admitted"] = False
    receipt["classes"] = len(classes)
    receipt["formalized"] = False
    receipt["goal_cids"] = [item["goal_cid"] for item in classes]
    receipt["ingested"] = True
    receipt["wrote_compiler"] = False
    return receipt
