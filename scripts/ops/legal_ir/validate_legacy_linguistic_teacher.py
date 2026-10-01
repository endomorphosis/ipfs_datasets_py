#!/usr/bin/env python3
"""Audit preserved 8D features, bounded caching and separately attributed targets.

No downloads, uploads, checkpoint replacement or service changes. Historical
parity, compiler-assisted targets and actual numeric Lake checks are distinct
evidence. A copied source, a low vector loss or a successful schema is not legal
semantic qualification. Run from the canonical checkout in a fresh process.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import resource
import statistics
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[3]
SOURCE = Path("/home/barberb/.cache/huggingface/hub/datasets--justicedao--ipfs_uscode/snapshots/5016b86a273ce5e4ffd066c5ae9f5fe494dd417e/uscode_parquet/laws.parquet")
TEACHER_SHA = "7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be"
FALSE_AUTHORITY = dict(admitted=False, formalized=False, roundtrip_ok=False,
                       semantic_qualification=False, independent_formula_generation=False)
FLAGS = dict(bridge_names=[], legal_ir_evaluate_provers=False,
             legal_ir_parallel_workers=1, metric_disk_cache=False,
             use_sample_memory=False, temperature=0, compute_device="cpu")


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _payload_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _compact_daemon_summary(result, artifact):
    """Retain the expanded historical IR once, reference it from the summary."""
    rows = []
    for row in result["long_span_ir_rows"]:
        rows.append({key: value for key, value in row.items() if key != "historical_modal_ir"})
    return {**result, "long_span_ir_rows": rows,
            "full_evidence_artifact": {"path": str(artifact), "sha256": _sha(artifact),
                                       "bytes": Path(artifact).stat().st_size}}


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    _require(spec is not None and spec.loader is not None, f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fixture_cases(panel):
    """Keep reference labels as diagnostics; no fixture is independent proof."""
    cases = list(json.loads(Path(panel).read_text())["cases"])
    for filename in ("pilot_cases.json", "holdout_cases.json"):
        path = REPO / "tests/fixtures/semantic_roundtrip" / filename
        for row in json.loads(path.read_text()):
            cases.append(dict(id=f"{filename}:{row['id']}", text=row["source_text"],
                              title="fixture", section=row["id"],
                              source_kind="existing_semantic_roundtrip_fixture",
                              source_ref=str(path.relative_to(REPO)),
                              reference_gold_ir=row.get("gold_ir"),
                              coverage=["typed_deontic_reference"]))
    seen, unique = {}, []
    for case in cases:
        key = " ".join(case["text"].split())
        if key not in seen:
            seen[key] = case
            unique.append(case)
        elif case.get("reference_gold_ir") is not None:
            # Deduplicate expensive work, not reference evidence.
            kept = seen[key]
            kept.setdefault("reference_gold_ir", case["reference_gold_ir"])
            kept.setdefault("additional_references", []).append(dict(
                id=case["id"], source_ref=case["source_ref"], reference_gold_ir=case["reference_gold_ir"]))
    return unique


def _sentence_candidates(text):
    """Punctuation-bounded excerpts, no length truncation or rewriting.

    The first historical-notes boundary limits candidate selection, while full
    original offsets and the section hash remain available. This is a sampling
    heuristic, not an assertion that the selected passage is operative law or
    a linguistically complete sentence; headings and abbreviations can occur.
    """
    boundary = min([len(text), *(match.start() for match in re.finditer(
        r"\b(?:Editorial Notes|Statutory Notes and Related Subsidiaries)\b", text))])
    for match in re.finditer(r"[^.!?]+[.!?](?=\s|$)", text[:boundary]):
        start, end = match.span()
        raw = match.group()
        start += len(raw) - len(raw.lstrip())
        sentence = text[start:end]
        if (40 <= len(sentence) <= 500 and re.search(r"\b(?:shall|must|may)\b", sentence, re.I)
                and not re.search(r"\b(?:amended|struck out|short title|may be cited)\b", sentence, re.I)):
            yield start, end, sentence


def _real_cases(path, count, *, maximum_sections=60077):
    if not count:
        return [], {"requested": 0, "sample_count": 0, "downloaded": False}
    import pyarrow.parquet as pq
    path = Path(path)
    _require(path.is_file(), f"local US Code source missing: {path}")
    before = path.stat()
    source_hash = _sha(path)
    file = pq.ParquetFile(path)
    cases, scanned, titles = [], 0, set()
    for batch in file.iter_batches(batch_size=64, columns=["title_number", "section_number", "text", "source_url"]):
        for row in batch.to_pylist():
            scanned += 1
            text = str(row["text"] or "")
            candidate = (next(_sentence_candidates(text), None)
                         if str(row["title_number"]) not in titles else None)
            if candidate:
                start, end, excerpt = candidate
                cases.append(dict(id=f"uscode-local:{row['title_number']}:{row['section_number']}:{start}",
                                  title=str(row["title_number"]), section=str(row["section_number"]),
                                  text=excerpt, source_kind="local_uscode_punctuation_bounded_excerpt",
                                  source_ref=str(row["source_url"]),
                                  section_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                                  section_start_char=start, section_end_char=end,
                                  coverage=["unreviewed_real_uscode"],
                                  independently_reviewed_gold=False))
                titles.add(str(row["title_number"]))
            if len(cases) >= count or scanned >= maximum_sections:
                break
        if len(cases) >= count or scanned >= maximum_sections:
            break
    after = path.stat()
    _require((before.st_size, before.st_mtime_ns, before.st_ino) ==
             (after.st_size, after.st_mtime_ns, after.st_ino), "US Code source changed during sampling")
    _require(len(cases) == count, f"only {len(cases)} eligible local US Code excerpts found")
    return cases, dict(path=str(path), sha256=source_hash, sections_scanned=scanned,
                       section_count=file.metadata.num_rows, sample_count=len(cases),
                       titles=sorted(titles), downloaded=False,
                       selection="first punctuation-bounded modal excerpt per distinct title; deterministic file order",
                       sentence_boundaries_independently_validated=False)


def _timings(operation, repeat, count):
    seconds, last = [], None
    for _ in range(repeat):
        start = time.perf_counter()
        last = operation()
        seconds.append(time.perf_counter() - start)
    return dict(replicate_seconds=seconds, median_seconds=statistics.median(seconds),
                median_seconds_per_span=statistics.median(seconds) / count,
                sample_count=count), last


def _predictions(model, samples):
    rows = []
    for sample in samples:
        encoded = model.encode(sample, use_sample_memory=False)
        decoded = model.decode(encoded)
        _require(len(decoded) == 8 and all(math.isfinite(value) for value in decoded),
                 "non-finite or non-8D reconstruction")
        rows.append(dict(encoded=encoded, decoded=decoded))
    return rows


def _configuration_hashes(jevops):
    root = REPO / "ipfs_datasets_py"
    files = [Path(__file__), Path(jevops) / "jevops/statement_lock.py",
             REPO / "scripts/ops/legal_ir/legacy_teacher_history.py"]
    for relative in ("logic/legal_ir/canonical_compiler.py", "logic/legal_ir/canonical_decompiler.py",
                     "logic/deontic/utils/deontic_parser.py", "logic/autoformal/__init__.py",
                     "optimizers/logic_theorem_optimizer/autoencoder_lineages/_contract.py"):
        files.append(root / relative)
    lineage = root / "optimizers/logic_theorem_optimizer/autoencoder_lineages/legacy_v1"
    files.extend(sorted(lineage.glob("*.py")))
    for folder in ("_snapshot", "_linguistic_snapshot", "_daemon_snapshot"):
        files.extend(sorted((lineage / folder).glob("*.py")))
        files.append(lineage / folder / "MANIFEST.json")
    return {str(path): _sha(path) for path in files}


def _historical_daemon_probe(state, cases, directory):
    """Compare real retained weights and two long IR outputs with local Git."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import Autoencoder
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.daemon_teacher import HistoricalDaemonAutoencoder
    helper = _import_file("_legacy_teacher_history_for_weights", REPO / "scripts/ops/legal_ir/legacy_teacher_history.py")
    wrappers = helper.load_daemon_wrappers()
    original = Autoencoder(state=state, feature_codec=wrappers["historical"], compute_device="cpu",
                           **wrappers["historical_constructor_fallbacks"])
    preserved = HistoricalDaemonAutoencoder(state=state, compute_device="cpu")
    by_id = {case["id"]: case for case in cases}
    numeric, ir_rows = [], []
    for case_id in ("obligation", "prohibition"):
        case = by_id[case_id]
        sample = preserved.build_sample(title=case.get("title", "fixture"), section=case_id,
                                        text=case["text"], citation=case.get("citation", case_id))
        old_time, old = _timings(lambda: _predictions(original, [sample]), 1, 1)
        new_time, new = _timings(lambda: _predictions(preserved, [sample]), 1, 1)
        _require(old == new, f"preserved full-daemon retained teacher changed prediction: {case_id}")
        numeric.append(dict(case_id=case_id, original=old[0], preserved=new[0], exact=True,
                            original_timing=old_time, preserved_timing=new_time))
    for case_id in ("uscode_10_167_packet_519_text", "uscode_38_8112_packet_519_text"):
        case = by_id[case_id]
        sample = preserved.build_sample(title=case["title"], section=case_id, text=case["text"],
                                        citation=case.get("citation", case_id))
        arguments = dict(document_id=sample.sample_id, citation=sample.citation,
                         source=sample.source, source_embedding=sample.embedding_vector)
        old_time, old = _timings(lambda: wrappers["historical"].encode(sample.text, **arguments), 1, 1)
        new_time, new = _timings(lambda: preserved.feature_codec.encode(sample.text, **arguments), 1, 1)
        _require(old.modal_ir.to_dict() == new.modal_ir.to_dict(), f"preserved daemon lost historical long-span IR: {case_id}")
        _require(old.decoded_embedding == new.decoded_embedding, f"preserved daemon lost wrapper vector: {case_id}")
        old_inference_time, old_prediction = _timings(lambda: _predictions(original, [sample]), 1, 1)
        new_inference_time, new_prediction = _timings(lambda: _predictions(preserved, [sample]), 1, 1)
        _require(old_prediction == new_prediction,
                 f"preserved full-daemon retained teacher changed long-span prediction: {case_id}")
        numeric.append(dict(case_id=case_id, source_kind=case["source_kind"],
                            source_text_chars=len(case["text"]), original=old_prediction[0],
                            preserved=new_prediction[0], exact=True,
                            original_timing=old_inference_time, preserved_timing=new_inference_time,
                            measurement_order="single numerical inference after wrapper IR extraction; no speedup assumption"))
        original_ir, preserved_ir = old.modal_ir.to_dict(), new.modal_ir.to_dict()
        ir_rows.append(dict(case_id=case_id, source_text=case["text"],
                            historical_modal_ir=original_ir,
                            historical_modal_ir_sha256=_payload_sha(original_ir),
                            preserved_modal_ir_sha256=_payload_sha(preserved_ir),
                            preserved_ir_identical_payload_stored_once=True,
                            exact=True, original_timing=old_time, preserved_timing=new_time))
        print(json.dumps({"historical_daemon_ir": case_id, "exact": True}), flush=True)
    result = dict(numerical_rows=numeric, long_span_ir_rows=ir_rows,
                  numerical_sample_count=len(numeric), long_span_ir_sample_count=len(ir_rows),
                  source_revision=helper.BASELINE, preserved_profile=preserved.describe(),
                  historical_constructor_fallbacks=wrappers["historical_constructor_fallbacks"],
                  producer_configuration_verified=False, numerical_state_shared_read_only=True,
                  trained=False, use_sample_memory=False, legacy_wrapper_flogic_enabled=True,
                  legacy_flogic_consistency_is_not_admission=True,
                  legal_ir_bridge_names=[], legal_ir_evaluate_provers=False,
                  external_prover_availability_reproduced=False, **FALSE_AUTHORITY)
    artifact = directory / "retained-teacher-historical-daemon.json"
    _write(artifact, result)
    return _compact_daemon_summary(result, artifact)


def _train_compare(backend, directory):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic import LinguisticAutoencoder
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_cached import CachedLinguisticAutoencoder, load_cached_training_checkpoint
    # The frozen numerical sample cache aliases identical text from different
    # titles/sections. Compare the intended same-input optimizer on fresh cores;
    # metadata-collision repairs belong to their separate regression controls.
    baseline = LinguisticAutoencoder(backend=backend, compute_device="cpu", feature_family_logit_scale=1.0)
    cached = CachedLinguisticAutoencoder(backend=backend, compute_device="cpu", feature_family_logit_scale=1.0)
    train = baseline.build_sample(title="training-fixture", section="1", text="The agency shall submit reports.")
    tuning = baseline.build_sample(title="tuning-fixture", section="2", text="The agency shall submit notices.")
    options = dict(epochs=1, learning_rate=0.01, max_seconds=30, max_line_search_attempts=1,
                   projection_update_backend="python_sparse_batch", projection_max_update_families=4,
                   legal_ir_bridge_names=(), legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
    reports = {}
    before = baseline.state.to_dict()
    for name, model in (("baseline", baseline), ("cached", cached)):
        start = time.perf_counter()
        report = model.train_generalizable_projection([train], validation_samples=[tuning], **options)
        reports[name] = dict(wall_seconds=time.perf_counter() - start, report=report)
        _require(report["accepted_epochs"] == 1, f"{name} accepted no historical epoch")
    _require(baseline.state.to_dict() == cached.state.to_dict(), "cache changed accepted historical sparse state")
    _require(before != cached.state.to_dict(), "accepted training changed no sparse weights")
    _require(not cached.state.decoded_embeddings, "training memorized rows")
    checkpoint = directory / "trained-checkpoint"
    cached.save_training_checkpoint(checkpoint)
    resumed = load_cached_training_checkpoint(checkpoint)
    _require(resumed.state.to_dict() == cached.state.to_dict(), "checkpoint state changed on reload")
    reloaded_predictions, warm_predictions = _predictions(resumed, [train, tuning]), _predictions(cached, [train, tuning])
    if reloaded_predictions != warm_predictions:
        _write(directory / "reload-prediction-mismatch.json", dict(
            reloaded=reloaded_predictions, warm=warm_predictions,
            original_warm=_predictions(baseline, [train, tuning]), **FALSE_AUTHORITY))
    _require(reloaded_predictions == warm_predictions,
             "checkpoint predictions changed on reload")
    second = cached.train_generalizable_projection([train], validation_samples=[tuning], **options)
    replay = resumed.train_generalizable_projection([train], validation_samples=[tuning], **options)
    _require(second["accepted_epochs"] == replay["accepted_epochs"] == 1,
             "resumed historical trainer accepted no epoch")
    _require(cached.state.to_dict() == resumed.state.to_dict(), "resume diverged from uninterrupted training")
    changed = sorted(key for key in before if before[key] != baseline.state.to_dict()[key])
    return dict(first_epoch=reports, second_epoch=second, resumed_epoch=replay,
                changed_sparse_families=changed, first_epoch_state_exact=True,
                reload_state_and_predictions_exact=True, resumed_state_exact=True,
                training_sample_count=1, tuning_sample_count=1,
                fresh_training_cores=True, corpus_observation_caches_reused=False,
                held_out_generalization_canary=False, configuration=options,
                reconstruction_is_semantic_fidelity=False, **FALSE_AUTHORITY)


def _reference_comparison(reference, candidate):
    """Surface-normalized comparisons are diagnostics, never equivalence gold."""
    def normalized(rule):
        result = {}
        for key in ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal"):
            value = rule.get(key, [] if key in {"conditions", "exceptions", "temporal"} else "")
            normalize = lambda item: " ".join(re.findall(r"[a-z0-9]+", str(item).lower().replace("_", " ")))
            result[key] = sorted(normalize(item) for item in value) if isinstance(value, list) else normalize(value)
        return result
    expected, actual = [normalized(row) for row in reference.get("rules", [])], [normalized(row) for row in candidate.get("rules", [])]
    exact = expected == actual
    return dict(surface_normalized_exact=exact, expected_rule_count=len(expected),
                candidate_rule_count=len(actual), expected=expected, candidate=actual,
                reference_independently_reviewed_this_run=False,
                complete_semantic_equivalence_check=False)


def _teacher_observations(model, cases, samples, directory):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_teacher import LegacyLinguisticTeacher
    teacher, rows = LegacyLinguisticTeacher(model), []
    start = time.perf_counter()
    for case, sample in zip(cases, samples):
        corpus = ("constitution" if "constitution" in case["id"].lower() else
                  "us_code" if "uscode" in case["source_kind"].lower() else "authored_fixture")
        result = teacher.observe(sample, corpus=corpus)
        _require(all(result[key] is False for key in FALSE_AUTHORITY), "teacher granted unauthorized authority")
        _require(result["distillation_mask"]["historical_formula"] is False,
                 "historical formulas were silently enabled as training targets")
        if corpus == "constitution":
            _require(not result["distillation_mask"]["compiler_supervised_formula"],
                     "Constitution formula target was enabled")
        reference = case.get("reference_gold_ir")
        rows.append(dict(case_id=case["id"], source_text=case["text"], result=result,
                         reference_comparison=None if reference is None else
                         _reference_comparison(reference, result["corrected_ir"])))
    duration = time.perf_counter() - start
    # These authored assertions are explicit, not inferred from agreement.
    gates = [
        ("Company A shall submit backup report within 10 days unless emergency.", "O", "within_duration", 10),
        ("The agency shall not disclose records.", "F", None, None),
        ("The officer shall retain the file for at least 20 days.", "O", "minimum_duration", 20),
    ]
    gate_rows = []
    for index, (text, modality, kind, quantity) in enumerate(gates):
        sample = model.build_sample(title="teacher-gate", section=str(index), text=text)
        result = teacher.observe(sample, corpus="authored_fixture")
        _require(result["distillation_mask"]["compiler_supervised_formula"], f"teacher gate {index} abstained: {result['reasons']}")
        rule = result["corrected_ir"]["rules"][0]
        _require(rule["modality"] == modality, f"teacher gate {index} lost modality")
        if kind:
            _require(any(record.get("temporal_kind") == kind and record.get("quantity") == quantity
                         for record in result["compiler"]["temporal_records"]), "teacher lost typed temporal quantity")
        if index == 0:
            _require(any("emergency" in value for value in rule["exceptions"]), "teacher lost exception")
        gate_rows.append(result)
    _write(directory / "teacher-observations.json", rows)
    return dict(sample_count=len(rows), elapsed_seconds=duration,
                seconds_per_span=duration / len(rows), target_cache_started_empty=True,
                status_counts=dict(Counter(row["result"]["status"] for row in rows)),
                rejection_reason_counts=dict(Counter(reason for row in rows for reason in row["result"]["reasons"])),
                gate_rows=gate_rows, reference_gold_is_not_new_independent_review=True,
                compiler_supervised_candidates_are_unqualified_weak_labels=True,
                corrected_formula_origin="pinned_canonical_compiler_supervision",
                **FALSE_AUTHORITY)


def _lake_minimum(gates, directory, jevops):
    """Build actual renderer output with an already installed Lean toolchain."""
    lock = _import_file("_legacy_teacher_statement_lock", Path(jevops) / "jevops/statement_lock.py")
    minimum = gates["rows"][2]["rule_with_parser_sidecars"]
    deadline = gates["rows"][0]["rule_with_parser_sidecars"]
    _require(lock.pattern_from_rule(deadline) is None, "deadline incorrectly became a minimum")
    pattern = lock.pattern_from_rule(minimum)
    _require(pattern == {"kind": "threshold", "fail": 19, "meet": 20}, "minimum renderer changed")
    source = lock.render_lean(pattern)
    _require(lock.lock_statement(source, source)["ok"], "generated threshold did not lock")
    _require(not re.search(r"\b(?:sorry|admit|axiom|Mathlib|import)\b", source), "invalid Lean payload")
    toolchain = Path.home() / ".elan/toolchains/leanprover--lean4---v4.26.0/bin"
    lake = toolchain / "lake"
    _require(lake.is_file(), "installed Lean 4.26 Lake is required; downloads are forbidden")
    directory.mkdir()
    (directory / "lean-toolchain").write_text("leanprover/lean4:v4.26.0\n")
    (directory / "lakefile.lean").write_text('import Lake\nopen Lake DSL\npackage «legal»\n@[default_target]\nlean_lib Legal\n')
    (directory / "Legal.lean").write_text(source)
    env = dict(os.environ, PATH=str(toolchain) + os.pathsep + os.environ.get("PATH", ""))
    start = time.perf_counter()
    result = subprocess.run([str(lake), "build", "Legal"], cwd=directory, env=env,
                            capture_output=True, text=True, timeout=60)
    output = result.stdout + result.stderr
    (directory / "build.log").write_text(output)
    ok = result.returncode == 0 and "Built Legal" in output and "error:" not in output
    _require(ok, f"actual lake build Legal failed: {output[-2000:]}")
    return dict(command=[str(lake), "build", "Legal"], returncode=result.returncode,
                lake_ok=ok, lake_executed=True, elapsed_seconds=time.perf_counter() - start,
                source_sha256=hashlib.sha256(source.encode()).hexdigest(), log=output,
                scope="numeric 19/20 boundary from canonical minimum-duration gate; not source-to-formula fidelity",
                deadline_non_renderable=True, **FALSE_AUTHORITY)


def _profile(backend, cases, directory, repeat, teacher_path=None):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic import LinguisticAutoencoder
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_cached import CachedLinguisticAutoencoder
    directory.mkdir()
    baseline = LinguisticAutoencoder(backend=backend, compute_device="cpu", feature_family_logit_scale=1.0)
    cached = CachedLinguisticAutoencoder(backend=backend, compute_device="cpu", feature_family_logit_scale=1.0)
    samples, raw, preparation = {}, {}, {}
    for name, model in (("baseline", baseline), ("cached", cached)):
        start = time.perf_counter()
        samples[name] = [model.build_sample(title=case.get("title", "fixture"), section=case["id"],
                                          text=case["text"], citation=case.get("source_ref", case["id"]))
                         for case in cases]
        raw[name] = [model.linguistic_observation(sample) for sample in samples[name]]
        duration = time.perf_counter() - start
        preparation[name] = dict(elapsed_seconds=duration, seconds_per_span=duration / len(cases),
                                 sample_count=len(cases), cache_started_empty=True,
                                 process_cold=False, includes_build_and_observation=True)
    _require([row.to_dict() for row in samples["baseline"]] == [row.to_dict() for row in samples["cached"]],
             "cache changed samples or linguistic vectors")
    _require(raw["baseline"] == raw["cached"], "cache changed linguistic encoding, features or IR")
    predictions, timings, evaluations = {}, {}, {}
    for name, model in (("baseline", baseline), ("cached", cached)):
        timings[name], predictions[name] = _timings(lambda: _predictions(model, samples[name]), repeat, len(cases))
        timings[name]["measurement_order"] = "first numerical-feature pass after linguistic preparation, followed by warm repeats"
        # At most four rows: evaluation time can grow with bridge-independent view extraction.
        subset = samples[name][:4]
        evaluations[name], result = _timings(lambda: model.evaluate(
            subset, use_sample_memory=False, legal_ir_bridge_names=(),
            legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1).to_dict(), repeat, len(subset))
        evaluations[name]["metrics"] = result
        _require(result.get("legal_ir_target_count", 0) == 0, "bridge-off run unexpectedly built targets")
    _require(predictions["baseline"] == predictions["cached"], "cache changed numerical predictions")
    _require(evaluations["baseline"]["metrics"] == evaluations["cached"]["metrics"], "cache changed evaluation metrics")
    _write(directory / "observations.json", [dict(case=case, observation=observation, prediction=prediction)
        for case, observation, prediction in zip(cases, raw["cached"], predictions["cached"])])
    cache_before_training = cached.feature_codec.cache_info()
    teacher_targets = _teacher_observations(cached, cases, samples["cached"], directory)
    training = _train_compare(backend, directory)
    teacher = None
    if teacher_path:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_cached import load_cached_checkpoint
        path = Path(teacher_path)
        before = path.stat()
        start = time.perf_counter()
        retained = load_cached_checkpoint(path, expected_sha256=TEACHER_SHA,
                                          backend=backend, compute_device="cpu")
        loaded_seconds = time.perf_counter() - start
        retained_samples = [retained.build_sample(title="teacher-audit", section=case["id"],
                                                  text=case["text"]) for case in cases[:8]]
        measured, outputs = _timings(lambda: _predictions(retained, retained_samples), repeat, len(retained_samples))
        # Read-only sharing avoids a second 398 MB JSON deserialization. Neither
        # model is trained; numerical state is the exact same historical object.
        uncached_retained = LinguisticAutoencoder(state=retained.state, backend=backend, compute_device="cpu")
        baseline_measured, baseline_outputs = _timings(
            lambda: _predictions(uncached_retained, retained_samples), repeat, len(retained_samples))
        _require(outputs == baseline_outputs, "cached retained-teacher predictions differ from original runtime")
        historical_daemon = (_historical_daemon_probe(retained.state, cases, directory)
                             if backend == "historical_blank_en" else None)
        after = path.stat()
        _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                 (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                 "retained teacher changed during read-only inference")
        _require(_sha(path) == TEACHER_SHA, "retained teacher checksum changed")
        teacher = dict(path=str(path), sha256=TEACHER_SHA, bytes=before.st_size,
                       loaded_seconds=loaded_seconds, inference=measured, predictions=outputs,
                       baseline_inference=baseline_measured, cached_prediction_parity=True,
                       numerical_state_shared_read_only=True,
                       historical_daemon=historical_daemon,
                       trained=False, file_unchanged=True, checkpoint_original_codec_configuration_verified=False,
                       configuration_assumption=backend, **FALSE_AUTHORITY)
    return dict(backend=backend, sample_count=len(cases), configuration=FLAGS,
                linguistic_identity=baseline.describe()["linguistic_identity"],
                full_observation_and_sample_parity=True, numerical_prediction_parity=True,
                evaluation_metric_parity=True, preparation=preparation, inference=timings,
                bridge_off_evaluate=evaluations, bridge_on_evaluate=None,
                no_bridge_on_speed_claim=True, cache=cache_before_training,
                numerical_feature_cache=cached.describe()["numerical_feature_cache"],
                warm_cache_speedup_not_assumed=True,
                training=training, teacher_targets=teacher_targets,
                retained_teacher=teacher, **FALSE_AUTHORITY)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--panel", type=Path, default=REPO / "tests/fixtures/logic/legacy_teacher_panel.json")
    parser.add_argument("--source-parquet", type=Path, default=SOURCE)
    parser.add_argument("--real-uscode-count", type=int, default=8)
    parser.add_argument("--backend", action="append", choices=("historical_blank_en", "local_en_core_web_sm"))
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--retained-teacher", type=Path)
    parser.add_argument("--jevops-root", type=Path, default=REPO.parents[1] / "JevOps")
    args = parser.parse_args(argv)
    if not 1 <= args.repeat <= 5 or not 0 <= args.real_uscode_count <= 32:
        parser.error("repeat must be 1..5; real-uscode-count must be 0..32")
    args.output_directory.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(REPO))
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    tree = require_workspace_logic_tree()
    hashes = _configuration_hashes(args.jevops_root)
    started = time.perf_counter()
    cases = _fixture_cases(args.panel)
    real, real_source = _real_cases(args.source_parquet, args.real_uscode_count)
    cases.extend(real)
    _write(args.output_directory / "cases.json", cases)
    profiles = []
    for backend in args.backend or ["historical_blank_en", "local_en_core_web_sm"]:
        profiles.append(_profile(backend, cases, args.output_directory / backend, args.repeat,
                                 args.retained_teacher))
        gc.collect()
        print(json.dumps({"backend": backend, "sample_count": len(cases), "parity": True}), flush=True)
    smoke = _import_file("_legacy_teacher_gate_smoke", REPO / "scripts/ops/legal_ir/smoke_legacy_linguistic_autoencoder.py")
    gates = smoke._typed_gates(args.jevops_root)
    lake = _lake_minimum(gates, args.output_directory / "lake-minimum", args.jevops_root)
    _require(hashes == _configuration_hashes(args.jevops_root), "relevant source changed during validation")
    forbidden = [name for name in sys.modules if name.rsplit(".", 1)[-1] in {
        "modal_joint_formula", "modal_latent_formula", "legal_formula_learning", "native_formula_training"}]
    _require(not forbidden, "experimental formula runtime loaded into preserved path")
    result = dict(schema="legacy-linguistic-teacher-validation/v1", operational_ok=True,
                  elapsed_seconds=time.perf_counter() - started, sample_count=len(cases),
                  source_kind_counts=dict(Counter(case["source_kind"] for case in cases)),
                  real_uscode_source=real_source, profiles=profiles, canonical_gates=gates,
                  lake=lake, source_hashes=hashes, resolved_logic_tree=tree,
                  peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                  peak_rss_scope="whole process including sequential retained-teacher loads and full historical IR artifact generation",
                  experimental_formula_modules=[], **FALSE_AUTHORITY)
    _write(args.output_directory / "report.json", result)
    print(json.dumps({"operational_ok": True, "sample_count": len(cases), "lake_ok": lake["lake_ok"],
                      "elapsed_seconds": result["elapsed_seconds"], **FALSE_AUTHORITY}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
