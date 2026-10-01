#!/usr/bin/env python3
"""Replay the preserved linguistic codec against local September Git objects.

No downloads, checkpoint mutation, or semantic qualification. The historical
source is executed only after its hash and every frozen dependency have been
verified. The full historical daemon additionally used the modal/BM25/F-logic
wrapper; this script records that distinction rather than claiming to replay it.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[3]
BASELINE = "21f2dc2c52940c8552be1515d893e107d0564387"
REFERENCE = "ddf6b79467b68159650df81befc288c8553df664"
PREFIX = "ipfs_datasets_py/optimizers/logic_theorem_optimizer/"
PACKAGE = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1"
LINEAGE = ROOT / PREFIX / "autoencoder_lineages/legacy_v1"
DEFAULT_PANEL = ROOT / "tests/fixtures/logic/legacy_teacher_panel.json"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def git_blob(revision, path):
    """Read a tracked local object; revisions are resolved before use."""
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"], cwd=ROOT,
        text=True).strip()
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)


def audit_sources():
    manifest = json.loads((LINEAGE / "_snapshot/MANIFEST.json").read_text())
    linguistic = json.loads((LINEAGE / "_linguistic_snapshot/MANIFEST.json").read_text())
    rows = []
    for item in [*manifest["files"], linguistic]:
        path = item["source_path"]
        old, ref = git_blob(BASELINE, path), git_blob(REFERENCE, path)
        expected = item["source_sha256"]
        rows.append({"path": path, "bytes": len(old), "baseline_sha256": _sha(old),
                     "reference_sha256": _sha(ref), "manifest_source_sha256": expected,
                     "exact": _sha(old) == _sha(ref) == expected})
    if not all(row["exact"] for row in rows):
        raise ValueError("historical codec dependency closure differs from pinned snapshot")
    wrapper_path = "ipfs_datasets_py/logic/modal/codec.py"
    old_wrapper = git_blob(BASELINE, wrapper_path)
    wrapper = {
        "path": wrapper_path, "baseline_sha256": _sha(old_wrapper),
        "reference_sha256": _sha(git_blob(REFERENCE, wrapper_path)),
        "current_file_sha256": _sha((ROOT / wrapper_path).read_bytes()),
        "historical_configuration": {"parser_backend": "spacy",
            "spacy_model_name": "definitely_missing_legal_model", "use_flogic": True},
        "full_wrapper_replayed": False,
        "scope": "Bare linguistic codec parity does not establish daemon BM25/F-logic parity",
    }
    daemon_path = PREFIX + "uscode_modal_daemon_runner.py"
    daemon_source = git_blob(BASELINE, daemon_path)
    constructors = [node.value for node in ast.walk(ast.parse(daemon_source))
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "AdaptiveModalAutoencoder"
        and any(kw.arg == "feature_codec" and isinstance(kw.value, ast.Name)
                and kw.value.id == "feature_codec" for kw in node.value.keywords)]
    if len(constructors) != 1:
        raise ValueError("historical daemon constructor is not uniquely identified")
    constructor_fields = {}
    for keyword in constructors[0].keywords:
        fallback = [node for node in ast.walk(keyword.value)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "getattr" and len(node.args) == 3]
        entry = {"expression": ast.unparse(keyword.value)}
        if len(fallback) == 1:
            entry["argument_name"] = ast.literal_eval(fallback[0].args[1])
            entry["fallback_default"] = ast.literal_eval(fallback[0].args[2])
        constructor_fields[keyword.arg] = entry
    wrapper["daemon_source_path"] = daemon_path
    wrapper["daemon_source_sha256"] = _sha(daemon_source)
    wrapper["autoencoder_constructor"] = constructor_fields
    wrapper["producer_configuration_verified"] = False
    wrapper["configuration_limit"] = (
        "These are source expressions and getattr fallbacks, not recovered runtime CLI values. "
        "Several daemon logit scales default to 1.0 while bare numerical constructor defaults to 0.0.")
    return {"baseline_revision": BASELINE, "reference_revision": REFERENCE,
            "baseline_selection": "Latest first-parent commit dated 2026-09-17 UTC; dates were inspected explicitly",
            "numerical_source_files": len(manifest["files"]), "files": rows,
            "source_closure_exact": True, "historical_daemon_wrapper": wrapper}


def load_historical_codec(revision=BASELINE):
    """Execute verified old codec under an isolated name and frozen dependencies.

    No canonical parser, compiler, or decompiler module is replaced in sys.modules.
    Dependencies are the separately hash-verified old numerical snapshot.
    """
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1._linguistic_snapshot import MANIFEST, verify_snapshot
    verify_snapshot()
    source = git_blob(revision, MANIFEST["source_path"])
    if _sha(source) != MANIFEST["source_sha256"]:
        raise ValueError("historical codec source does not match verified manifest")
    text = source.decode()
    for edit in MANIFEST["relocation_edits"]:
        if text.count(edit["before"]) != 1:
            raise ValueError("historical dependency import is not unique")
        text = text.replace(edit["before"], edit["after"])
    if _sha(text.encode()) != MANIFEST["vendored_sha256"]:
        raise ValueError("historical dependency relocation did not reproduce vendored codec")
    name = PACKAGE + "._linguistic_snapshot._git_replay_" + revision[:12]
    module = types.ModuleType(name)
    module.__package__ = PACKAGE + "._linguistic_snapshot"
    module.__file__ = f"git:{revision}:{MANIFEST['source_path']}"
    sys.modules[name] = module
    try:
        exec(compile(text, module.__file__, "exec"), module.__dict__)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def observe(codec, text, *, document_id, citation):
    """Capture the complete deterministic output, without provenance text replay."""
    encoding = codec.encoder.encode(text, document_id=document_id,
                                    citation=citation, source="us_code")
    families = tuple(f.value for f in importlib.import_module(
        PACKAGE + "._snapshot.modal_registry").ModalLogicFamily)
    return {"encoding": encoding.to_dict(),
            "modal_ir": codec.compiler.compile(encoding).to_dict(),
            "decoded_feature_vector": codec.decoder.decode_embedding(encoding, dimensions=8),
            "feature_keys": list(codec.decoder._feature_stream(encoding)),
            "family_logits": codec.decoder.family_logits(encoding, modal_families=families)}


def load_daemon_wrappers():
    """Build old/current wrappers with isolated old helpers and explicit flags.

    This uses the local installed ErgoAI availability, never treats a consistency
    result as an admission, and does not infer original checkpoint CLI settings.
    """
    old_spacy = load_historical_codec(BASELINE)
    namespace = PACKAGE + "._historical_modal_" + BASELINE[:12]
    package = types.ModuleType(namespace)
    package.__path__ = []
    sys.modules[namespace] = package
    frozen_prefix = PACKAGE + "._snapshot."
    normal_prefix = "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
    shared_paths = ["ipfs_datasets_py/knowledge_graphs/migration/formats.py",
        "ipfs_datasets_py/knowledge_graphs/neo4j_compat/legal_ir_projection.py"]
    shared_paths.extend(str(path.relative_to(ROOT)) for path in
                        sorted((ROOT / "ipfs_datasets_py/logic/flogic").glob("*.py")))
    shared = []
    for path in shared_paths:
        old = git_blob(BASELINE, path)
        current = (ROOT / path).read_bytes()
        exact = old == current
        shared.append({"path": path, "baseline_sha256": _sha(old),
                       "current_sha256": _sha(current), "exact": exact})
        if not exact:
            raise ValueError("historical wrapper shared dependency drift: " + path)
    loaded = {}
    for leaf in ("flogic_optimizer", "decompiler", "kg_bridge", "codec"):
        path = ("ipfs_datasets_py/logic/flogic_optimizer.py" if leaf == "flogic_optimizer"
                else "ipfs_datasets_py/logic/modal/" + leaf + ".py")
        raw = git_blob(BASELINE, path)
        if raw != git_blob(REFERENCE, path):
            raise ValueError("September wrapper revisions disagree: " + path)
        source = raw.decode().replace(normal_prefix + "spacy_modal_codec",
                                       old_spacy.__name__)
        source = source.replace(normal_prefix, frozen_prefix)
        # The spaCy alias itself lives under normal_prefix; restore its full
        # isolated name after the generic helper-import relocation.
        source = source.replace(frozen_prefix + "autoencoder_lineages.legacy_v1.",
                                PACKAGE + ".")
        source = source.replace("from ipfs_datasets_py.logic.flogic_optimizer import",
                                "from " + namespace + ".flogic_optimizer import")
        name = namespace + "." + leaf
        module = types.ModuleType(name)
        module.__package__ = namespace
        module.__file__ = f"git:{BASELINE}:{path}"
        sys.modules[name] = module
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        loaded[leaf] = module
        shared.append({"path": path, "baseline_sha256": _sha(raw),
                       "relocated_sha256": _sha(source.encode()), "loaded_from_local_git": True})
    from ipfs_datasets_py.logic.modal.codec import DeterministicModalLogicCodec, ModalLogicCodecConfig
    config = {"parser_backend": "spacy", "spacy_model_name": "definitely_missing_legal_model",
              "use_flogic": True}
    historical = loaded["codec"].DeterministicModalLogicCodec(
        loaded["codec"].ModalLogicCodecConfig(**config))
    current = DeterministicModalLogicCodec(ModalLogicCodecConfig(**config))
    fields = audit_sources()["historical_daemon_wrapper"]["autoencoder_constructor"]
    defaults = {key: value["fallback_default"] for key, value in fields.items()
                if "fallback_default" in value}
    return {"historical": historical, "current": current, "configuration": config,
            "dependency_audit": shared, "historical_constructor_fallbacks": defaults,
            "producer_configuration_verified": False}


def replay_daemon_wrapper(cases):
    """Compare wrappers, not archival checkpoint predictions or admissions."""
    wrappers = load_daemon_wrappers()
    historical, current = wrappers["historical"], wrappers["current"]
    reports = []
    for case in cases:
        outputs, times = {}, {}
        for label, codec in (("historical", historical), ("current", current)):
            before = time.perf_counter()
            result = codec.encode(case["text"], document_id=case["id"],
                                  citation=case.get("citation"), source="us_code")
            times[label] = time.perf_counter() - before
            # No source_embedding passed: compare wrapper-generated feature
            # vectors, not mock vectors or learned checkpoint predictions.
            outputs[label] = {"encoding": result.encoding.to_dict(),
                "modal_ir": result.modal_ir.to_dict(), "source_embedding": result.source_embedding,
                "decoded_embedding": result.decoded_embedding, "family_logits": result.family_logits,
                "family_probabilities": result.family_probabilities,
                "target_family": result.target_family,
                "target_family_distribution": result.target_family_distribution,
                "frame_candidates": result.frame_candidates, "selected_frame": result.selected_frame,
                "kg_triples": result.kg_triples, "decoded_text": result.decoded_text,
                "decoded_modal_text": result.decoded_modal_text.to_dict(), "losses": result.losses}
        checks = {key: outputs["historical"][key] == outputs["current"][key]
                  for key in outputs["historical"]}
        reports.append({"id": case["id"], "source_sha256": _sha(case["text"].encode()),
            "exact": all(checks.values()), "field_checks": checks, "seconds": times,
            "semantic_output_exact": all(value for key, value in checks.items() if key != "losses"),
            "historical_loss_values_exact": all(outputs["current"]["losses"].get(key) == value
                for key, value in outputs["historical"]["losses"].items()),
            "added_loss_fields": sorted(set(outputs["current"]["losses"]) -
                                         set(outputs["historical"]["losses"])),
            "output_sha256": {name: _sha(_json(value)) for name, value in outputs.items()},
            "formula_samples": {name: value["modal_ir"]["formulas"][:3]
                                for name, value in outputs.items()},
            "losses": {name: value["losses"] for name, value in outputs.items()}})
    return {"case_count": len(cases), "configuration": wrappers["configuration"],
        "dependency_audit": wrappers["dependency_audit"],
        "historical_constructor_fallbacks": wrappers["historical_constructor_fallbacks"],
        "all_exact": all(row["exact"] for row in reports), "comparisons": reports,
        "teacher_checkpoint_used": False, "producer_configuration_verified": False,
        "flogic_consistency_enabled": True, "external_prover_availability_reproduced": False,
        "admitted": False, "roundtrip_ok": False,
        "scope": "Full old/current deterministic modal wrapper; excludes autoencoder weights and original runtime CLI"}


def replay_panel(*, panel_path=DEFAULT_PANEL, backends=("historical_blank_en",), max_cases=None,
                 daemon_wrapper=False):
    # Call in a fresh process: importing HACC first must fail rather than silently
    # replacing its modules. The workspace pin enforces the existing contract.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic import LinguisticAutoencoder

    started = time.perf_counter()
    source_audit = audit_sources()
    raw_panel = Path(panel_path).read_bytes()
    panel = json.loads(raw_panel)
    cases = panel["cases"] if max_cases is None else panel["cases"][:max_cases]
    if not cases:
        raise ValueError("replay requires a nonempty panel")
    modules = {ref: load_historical_codec(ref) for ref in (BASELINE, REFERENCE)}
    reports = []
    for backend in backends:
        model = LinguisticAutoencoder(backend=backend, compute_device="cpu")
        current = model.feature_codec
        codecs = {ref: mod.SpaCyModalCodec(encoder=mod.SpaCyLegalEncoder(
            model_name=current.encoder.model_name)) for ref, mod in modules.items()}
        for codec in codecs.values():
            if (codec.encoder.used_fallback_model != current.encoder.used_fallback_model
                    or list(codec.encoder.nlp.pipe_names) != list(current.encoder.nlp.pipe_names)):
                raise ValueError("historical replay backend differs from preserved backend")
        for case in cases:
            outputs, elapsed = {}, {}
            for name, codec in [("preserved", current), *codecs.items()]:
                before = time.perf_counter()
                outputs[name] = observe(codec, case["text"], document_id=case["id"],
                                        citation=case.get("citation", "diagnostic"))
                elapsed[name] = time.perf_counter() - before
            expected = outputs[BASELINE]
            fields = {name: {key: output[key] == expected[key] for key in expected}
                      for name, output in outputs.items()}
            reports.append({"id": case["id"], "backend": backend,
                "source_kind": case.get("source_kind"), "coverage": case.get("coverage", []),
                "source_sha256": _sha(case["text"].encode()),
                "exact": all(all(checks.values()) for checks in fields.values()),
                "field_checks": fields, "output_sha256": {name: _sha(_json(output))
                    for name, output in outputs.items()}, "seconds": elapsed,
                "formula_count": len(expected["modal_ir"]["formulas"]),
                "observed_families": sorted({formula["operator"]["family"]
                    for formula in expected["modal_ir"]["formulas"]})})
    wrapper = replay_daemon_wrapper([cases[i] for i in
        dict.fromkeys([0, min(1, len(cases)-1), min(5, len(cases)-1), min(6, len(cases)-1),
                       max(0, len(cases)-2), len(cases)-1])]) if daemon_wrapper else None
    source_audit["historical_daemon_wrapper"]["full_wrapper_replayed"] = bool(wrapper)
    return {"schema": "legacy-linguistic-historical-replay/v1", "source_audit": source_audit,
        "panel_sha256": _sha(raw_panel), "case_count": len(cases), "backends": list(backends),
        "comparison_count": len(reports), "all_exact": all(row["exact"] for row in reports),
        "elapsed_seconds": time.perf_counter() - started, "comparisons": reports,
        "qualifies_teacher_semantics": False, "admitted": False, "roundtrip_ok": False,
        "teacher_checkpoint_used": False, "historical_dependency_environment_reproduced": False,
        "daemon_wrapper_comparison": wrapper,
        "limits": ["Exact codec parity under today's installed spaCy; old package versions were not recovered",
                   "No learned formula decoder, checkpoint training or neural teacher fidelity claim",
                   "Historical errors are intentionally retained in this comparison",
                   ("Old/current BM25/F-logic wrapper compared separately; original runtime environment and teacher configuration unknown"
                    if wrapper else "No full historical BM25/F-logic wrapper replay"),
                   "No legal-IR bridge timing; reported observations are not a speed benchmark",
                   "Authored cases and historical repository excerpts are not independent semantic gold"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--backend", action="append", choices=("historical_blank_en", "local_en_core_web_sm"))
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--daemon-wrapper", action="store_true")
    args = parser.parse_args()
    if args.max_cases is not None and args.max_cases < 1:
        parser.error("--max-cases must be positive")
    result = replay_panel(panel_path=args.panel, backends=tuple(args.backend or ["historical_blank_en"]),
                          max_cases=args.max_cases, daemon_wrapper=args.daemon_wrapper)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: result[key] for key in ("case_count", "comparison_count", "all_exact", "elapsed_seconds")}))
    return 0 if result["all_exact"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
