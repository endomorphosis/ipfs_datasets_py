"""Protected v2 task construction and structural replay, not proof admission.

The native task envelope stays v1. An explicit v2 repair contract and new
failure key select the new compiler/decompiler; old scopes are not widened.
Expected slots are operator-sealed evidence, never candidate-generated gold.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from ipfs_datasets_py.logic.legal_ir.extended_contracts import (
    DefinitionV2, ExtendedLegalIR, PolicyV2,
)


REASON = "extended_ir_v2"
LEGACY_CONTRACT = "autoformal-extended-repair/v2"
CONTRACT = "autoformal-extended-repair/v3"
BASELINE_REASON = "roundtrip_repair_v2"
BASELINE_CONTRACT = "autoformal-roundtrip-repair/v2"


def _parent_task_cid(digest: str) -> str:
    # Same CIDv1 DAG-JSON/sha2-256 encoding as the native owner, using the
    # datasets package's existing codec. Offline replay does not import a live
    # accelerate checkout; native claim admission still owns task authority.
    from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json
    from .supervisor_queue import SCHEMA
    return cid_for_dag_json({"schema": SCHEMA, "packet_sha256": digest})


def _wire(statement):
    return ExtendedLegalIR((statement,)).to_dict()


def baseline_packet(parent: dict, parent_digest: str, *, census: dict,
                    source_span_id: str, code_identity: str) -> dict:
    """Re-scope one measured failure, retaining only freshly passing preserves.

    The parent task and its original preserve list are immutable. A new task's
    completion never completes its parent or conceals other baseline failures.
    """
    from .supervisor_queue import SCHEMA, canonical_bytes, repair_packets
    if hashlib.sha256(canonical_bytes(parent)).hexdigest() != parent_digest:
        raise ValueError("parent packet differs from sealed lineage")
    old_rows = [parent["row"], *parent["preserve_rows"]]
    rows = census.get("rows")
    if (type(rows) is not list or len(rows) != len(old_rows)
            or [row.get("id") for row in rows] != [row["source_span_id"] for row in old_rows]
            or any(row.get("text") != old["text"] for row, old in zip(rows, old_rows))):
        raise ValueError("fresh census does not bind every parent source row")
    selected = [row for row in rows if row["id"] == source_span_id]
    if len(selected) != 1 or selected[0].get("agrees") is not False or selected[0].get("skipped"):
        raise ValueError("baseline repair must target a reproduced failure")
    observations = {row["id"]: row for row in rows}
    fresh_rows = []
    for old in old_rows:
        observed = observations[old["source_span_id"]]
        if old["source_span_id"] == source_span_id:
            fresh_rows.append({**old, "reason": BASELINE_REASON, "agrees": False,
                               "decompiled": observed["decompiled"], "dropped": observed["dropped"]})
        elif observed.get("agrees") is True and not observed.get("skipped"):
            fresh_rows.append({**old, "reason": "", "agrees": True, "decompiled": observed["decompiled"], "dropped": []})
    item = repair_packets({"rows": fresh_rows}, release_id=parent["release_id"],
                          code_identity=code_identity, model_identity=parent["model_identity"])[0]
    packet = item["packet"]
    packet["revision"] = {
        "schema": BASELINE_CONTRACT,
        "parent_task_cid": _parent_task_cid(parent_digest),
        "parent_packet_sha256": parent_digest,
        "source_sha256": packet["row"]["text_sha256"],
        "baseline_census_sha256": hashlib.sha256(canonical_bytes(census)).hexdigest(),
        "original_failure": selected[0]["reason"],
        "other_unresolved_sources": [row["id"] for row in rows if row["id"] != source_span_id and not row.get("agrees")],
        "parent_task_completed": False,
    }
    item["sha256"] = hashlib.sha256(canonical_bytes(packet)).hexdigest()
    item["task"].update(task_id="AFTD-" + item["sha256"][:20])
    validate_baseline(packet)
    return item


def validate_baseline(packet: dict) -> dict:
    from .supervisor_queue import SCHEMA, RepairQueueError
    revision = packet.get("revision")
    required = {"schema", "parent_task_cid", "parent_packet_sha256", "source_sha256",
                "baseline_census_sha256", "original_failure", "other_unresolved_sources", "parent_task_completed"}
    if (type(revision) is not dict or set(revision) != required or revision["schema"] != BASELINE_CONTRACT
            or packet["row"]["reason"] != BASELINE_REASON or revision["parent_task_completed"] is not False):
        raise RepairQueueError("invalid versioned baseline repair contract")
    for key in ("parent_packet_sha256", "source_sha256", "baseline_census_sha256"):
        digest = revision[key]
        if type(digest) is not str or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise RepairQueueError("invalid baseline lineage digest")
    if (revision["parent_task_cid"] != _parent_task_cid(revision["parent_packet_sha256"])
            or revision["source_sha256"] != packet["row"]["text_sha256"]
            or hashlib.sha256(packet["row"]["text"].encode()).hexdigest() != revision["source_sha256"]):
        raise RepairQueueError("baseline source or parent identity mismatch")
    if (type(revision["original_failure"]) is not str or not revision["original_failure"]
            or type(revision["other_unresolved_sources"]) is not list
            or len(revision["other_unresolved_sources"]) > 128
            or any(type(value) is not str or not value for value in revision["other_unresolved_sources"])):
        raise RepairQueueError("invalid baseline failure inventory")
    return revision


def contract_cases(family: str, *, seed: str = "fixed", contract: str = CONTRACT) -> list[dict]:
    """Public acceptance probes, not statistical holdouts or legal oracles.

    Keep the v2 task contract unchanged. New v3 tasks also check regressions
    independently observed in the first policy repair, without promoting old
    tasks or retroactively changing their sealed acceptance cases. The IR
    schema remains v2: a flat objective list cannot encode a disjunction.
    """
    if contract not in {LEGACY_CONTRACT, CONTRACT}:
        raise ValueError("unsupported extension acceptance contract")
    suffix = int(hashlib.sha256(seed.encode()).hexdigest()[:6], 16) % 10000
    if family == "policy":
        authority = "Council " + str(suffix)
        a, b = 101 + suffix, 207 + suffix
        cases = [
            {"name": "policy_not_obligation", "text":
             f"{authority} supports—\n(1) retaining {a} reports;\n(2) publishing {b} notices.",
             "expected_ir": _wire(PolicyV2(authority, "supports", (f"retaining {a} reports", f"publishing {b} notices")))},
            {"name": "declared_policy", "text":
             f"It is the policy of {authority} to retain {a} reports.",
             "expected_ir": _wire(PolicyV2(authority, "declares_policy", (f"retain {a} reports",)))},
            {"name": "mixed_residue_must_abstain", "text":
             f"It is the policy of {authority} to retain {a} reports. The agency shall destroy the notices.",
             "expected_ir": None},
        ]
        if contract == CONTRACT:
            cases.extend([
                {"name": "unrepresented_list_disjunction_must_abstain", "text":
                 f"{authority} supports—\n(1) retaining reports; or\n(2) publishing notices.",
                 "expected_ir": None},
                {"name": "operative_heading_must_not_disappear", "text":
                 f"§ {a}. Congress supports destroying records.\n{authority} supports retaining reports.",
                 "expected_ir": None},
                {"name": "unpunctuated_atom_is_not_a_connector", "text":
                 f"{authority} supports funding the vendor",
                 "expected_ir": _wire(PolicyV2(authority, "supports", ("funding the vendor",)))},
                {"name": "repeated_conditions_must_all_survive", "text":
                 f"{authority} supports retaining reports.\nConditions: review completed\nConditions: consent obtained",
                 "expected_ir": _wire(PolicyV2(authority, "supports", ("retaining reports",),
                                               conditions=("review completed", "consent obtained")))},
                {"name": "outline_labels_must_not_be_renumbered", "text":
                 f"{authority} supports—\n(1) retaining reports;\n(3) publishing notices.",
                 "expected_ir": None},
                {"name": "duplicate_outline_labels_must_abstain", "text":
                 f"{authority} supports—\n(1) retaining reports;\n(1) publishing notices.",
                 "expected_ir": None},
                {"name": "policy_list_followed_by_permission_must_abstain", "text":
                 f"{authority} supports—\n(1) retaining reports;\n(2) publishing notices. the agency may destroy records.",
                 "expected_ir": None},
            ])
        return cases
    if family == "definition":
        return [
            {"name": "scoped_definition", "text":
             f'For purposes of this section, the term "record {suffix}" means a written account.',
             "expected_ir": _wire(DefinitionV2(f"record {suffix}", "means", "a written account", scope=("this section",)))},
            {"name": "definition_not_norm", "text":
             f'The term "record {suffix}" includes an electronic account.',
             "expected_ir": _wire(DefinitionV2(f"record {suffix}", "includes", "an electronic account"))},
            {"name": "exclusion_is_not_definition_or_prohibition", "text":
             f'The term "record {suffix}" does not include a draft account.',
             "expected_ir": _wire(DefinitionV2(f"record {suffix}", "excludes", "a draft account"))},
            {"name": "mixed_residue_must_abstain", "text":
             f'The term "record {suffix}" means a written account. The agency shall destroy notices.',
             "expected_ir": None},
        ]
    raise ValueError("unsupported extension family")


def extension_packet(parent: dict, parent_digest: str, *, code_identity: str,
                     family: str, expected_ir: dict, preserve_families: tuple[str, ...] = ()) -> dict:
    from .supervisor_queue import SCHEMA, canonical_bytes, repair_packets
    if hashlib.sha256(canonical_bytes(parent)).hexdigest() != parent_digest:
        raise ValueError("parent packet differs from sealed lineage")
    expected = ExtendedLegalIR.from_dict(expected_ir)
    if any(statement.kind != family for statement in expected.statements):
        raise ValueError("expected statement kind differs from extension family")
    contract_cases(family)
    for preserved in preserve_families:
        contract_cases(preserved)
    row = {**parent["row"], "reason": REASON, "agrees": False}
    item = repair_packets({"rows": [row]}, release_id=parent["release_id"],
                          code_identity=code_identity, model_identity=parent["model_identity"])[0]
    packet = item["packet"]
    packet["extension"] = {
        "schema": CONTRACT, "family": family, "expected_ir": expected.to_dict(),
        "preserve_families": list(preserve_families),
        "parent_task_cid": _parent_task_cid(parent_digest),
        "parent_packet_sha256": parent_digest,
        "parent_source_sha256": parent["row"]["text_sha256"],
        "parent_preserve_rows_carried_as_lineage_only": [row["source_span_id"] for row in parent["preserve_rows"]],
    }
    # The new task implements one explicit family, not the old task's entire
    # acceptance scope. No old task is closed or silently superseded by it.
    packet["preserve"] = ["canonical v1 compiler/decompiler files and frozen tests", "all original task evidence and lifecycle", *preserve_families]
    packet["replace"] = ["opt-in legal-surface-ir/v2 compiler and source-withheld decompiler for " + family]
    item["sha256"] = hashlib.sha256(canonical_bytes(packet)).hexdigest()
    item["task"].update(task_id="AFTD-" + item["sha256"][:20], priority="P0",
                        preserve=packet["preserve"], replace=packet["replace"],
                        failure_mode=REASON, estimated_tokens=14000,
                        estimated_validation_seconds=300)
    validate_extension(packet)
    return item


def validate_extension(packet: dict) -> dict:
    from .supervisor_queue import SCHEMA, RepairQueueError
    extension = packet.get("extension")
    required = {"schema", "family", "expected_ir", "preserve_families", "parent_task_cid",
                "parent_packet_sha256", "parent_source_sha256", "parent_preserve_rows_carried_as_lineage_only"}
    if (type(extension) is not dict or set(extension) != required
            or extension["schema"] not in {LEGACY_CONTRACT, CONTRACT}
            or packet["row"]["reason"] != REASON or packet["preserve_rows"]):
        raise RepairQueueError("invalid explicit extension contract")
    digest = extension["parent_packet_sha256"]
    if type(digest) is not str or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise RepairQueueError("invalid parent evidence hash")
    if extension["parent_task_cid"] != _parent_task_cid(digest):
        raise RepairQueueError("parent task identity mismatch")
    if (extension["parent_source_sha256"] != packet["row"]["text_sha256"]
            or hashlib.sha256(packet["row"]["text"].encode()).hexdigest() != extension["parent_source_sha256"]):
        raise RepairQueueError("extension changed source bytes")
    if type(extension["preserve_families"]) is not list or len(extension["preserve_families"]) > 2:
        raise RepairQueueError("invalid preserved extension families")
    for family in [extension["family"], *extension["preserve_families"]]:
        contract_cases(family, contract=extension["schema"])
    expected = ExtendedLegalIR.from_dict(extension["expected_ir"])
    if any(statement.kind != extension["family"] for statement in expected.statements):
        raise RepairQueueError("expected IR kind does not match family")
    return extension


_RENDER_PROGRAM = """
import json, sys
sys.path.insert(0, sys.argv[1])
from ipfs_datasets_py.logic.legal_ir.extended_contracts import ExtendedLegalIR
from ipfs_datasets_py.logic.legal_ir.extended_decompiler import decompile_extended
ir = ExtendedLegalIR.from_dict(json.load(sys.stdin))
text = decompile_extended(ir)
if type(text) is not str or not text.strip() or len(text) > 524288:
    raise ValueError('invalid rendered output')
print(json.dumps({'text': text}))
"""


def render_fresh(ir: ExtendedLegalIR) -> str:
    """Separate interpreter with IR-only stdin; no compiler-populated memory.

    This is process/data-flow separation, not an OS filesystem/network sandbox.
    The native candidate scope and protected tests remain independent controls.
    """
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run([sys.executable, "-I", "-c", _RENDER_PROGRAM, str(root)],
                            input=json.dumps(ir.to_dict()), text=True, capture_output=True,
                            timeout=20, check=True, cwd=root,
                            env={**os.environ, "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
                                 "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0", "PYTHONDONTWRITEBYTECODE": "1"})
    if len(result.stdout) > 2 * 1024 * 1024:
        raise ValueError("renderer output exceeds evidence bound")
    payload = json.loads(result.stdout)
    if type(payload) is not dict or set(payload) != {"text"} or type(payload["text"]) is not str:
        raise ValueError("renderer protocol mismatch")
    return payload["text"]


def replay_extension(packet: dict, *, compiler=None, renderer=None) -> dict:
    """Exact slots, fresh rendering, full literal coverage and recompilation."""
    from .autoencoder_router import source_surface_diagnostics
    from .supervisor_queue import canonical_bytes
    extension = validate_extension(packet)
    if compiler is None:
        from ipfs_datasets_py.logic.legal_ir.extended_compiler import compile_extended
        compiler = compile_extended
    renderer = renderer or render_fresh
    cases = [{"name": "sealed_source", "text": packet["row"]["text"], "expected_ir": extension["expected_ir"]}]
    for family in dict.fromkeys([extension["family"], *extension["preserve_families"]]):
        cases.extend(contract_cases(family, seed=hashlib.sha256(canonical_bytes(packet)).hexdigest(),
                                    contract=extension["schema"]))
    results = []
    for case in cases:
        reason = ""
        try:
            actual = compiler(case["text"])
            expected = case["expected_ir"]
            if expected is None:
                if actual is not None:
                    reason = "unsupported_residue_was_accepted"
            elif type(actual) is not ExtendedLegalIR or actual.to_dict() != expected:
                reason = "structured_slots_differ_or_abstain"
            else:
                rendered = renderer(actual)
                if type(rendered) is not str or not rendered.strip():
                    raise ValueError("renderer returned no text")
                normalized = " ".join(rendered.casefold().split())
                for statement in actual.to_dict()["statements"]:
                    for key, value in statement.items():
                        if key in {"kind", "modality", "relation", "stance"}:
                            continue
                        atoms = value if isinstance(value, list) else [value]
                        if any(" ".join(atom.casefold().split()) not in normalized for atom in atoms):
                            reason = "semantic_atom_missing_from_rendering"
                diagnostics = source_surface_diagnostics(case["text"], rendered)
                if diagnostics["missing_numeric_surfaces"]:
                    reason = "numeric_surface_missing"
                roundtrip = compiler(rendered)
                if type(roundtrip) is not ExtendedLegalIR or roundtrip.to_dict() != expected:
                    reason = "structural_roundtrip_mismatch"
        except (ValueError, TypeError, KeyError, AttributeError, NotImplementedError,
                OSError, subprocess.SubprocessError) as exc:
            reason = type(exc).__name__
        results.append({"case": case["name"], "passed": not reason, "reason": reason})
    return {"passed": all(row["passed"] for row in results), "checked_count": len(results),
            "failures": [row for row in results if not row["passed"]],
            "gate": "extended_structural_roundtrip_not_legal_equivalence",
            "admitted": False, "formalized": False, "parent_task_completed": False}
