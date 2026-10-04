#!/usr/bin/env python3
"""Freeze, train, and evaluate a bounded learned flat-clause boundary experiment."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as compose
from scripts.ops.legal_ir import run_legal_open_vocabulary_experiment as files
from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as calendar
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as calendar_summary

require, digest = boundary.require, boundary.digest
SCHEMA = "legal-learned-clause-boundary-experiment/v1"
SPLIT_COUNTS = {"train": 192, "tuning": 48, "test": 96}
CONSTRUCTIONS = {"train": ("plain", "suffix_condition", "suffix_exception", "section_prefix", "condition_prefix"),
    "tuning": ("section_condition", "temporal_suffix"), "test": ("condition_exception", "section_temporal_condition")}
ACTORS = {"train": "Beryl", "tuning": "Corundum", "test": "Tourmaline"}
FALSE = boundary.FALSE


def ref(path):
    return files.file_ref(path)


def read(reference):
    require(files.sha(reference["path"]) == reference["sha256"], "artifact hash differs")
    if "bytes" in reference:
        require(Path(reference["path"]).stat().st_size == reference["bytes"], "artifact byte count differs")
    return files.read(reference["path"])


def write(path, value):
    files.write(path, value)
    return ref(path)


def render_clause(split, document, clause, construction):
    prefix = ACTORS[split]
    actor = f"{prefix}{document} " + ("Dept. of Records" if clause % 2 == 0 and document % 3 == 0 else "Public Register Authority")
    actions = ("retain", "publish", "inspect", "disclose")
    action = actions[(document + clause) % 4]
    obj = f"the certified {prefix.lower()}{document} register"
    modality = ("O", "P", "F")[(document + clause) % 3]
    modal = {"O": "must", "P": "may", "F": "must not"}[modality]
    condition = f"the {prefix.lower()}{document} application has been accepted"
    exception = f"the {prefix.lower()}{document} preservation notice remains effective"
    temporal = f"within {21 + document} days"
    base = f"{actor} {modal} {action} {obj}"
    conditions, exceptions, times = [], [], []
    if construction in ("suffix_condition", "section_condition", "section_temporal_condition"):
        base += (" " + temporal if construction == "section_temporal_condition" else "") + " if " + condition
        conditions = [condition]
        if construction == "section_temporal_condition": times = [temporal]
    if construction == "suffix_exception":
        base += " unless " + exception; exceptions = [exception]
    if construction in ("condition_prefix", "condition_exception"):
        base = "If " + condition + ", " + base; conditions = [condition]
        if construction == "condition_exception":
            base += " unless " + exception; exceptions = [exception]
    if construction in ("section_prefix", "section_condition", "section_temporal_condition"):
        base = f"Under section {document + 8100}.{clause + 2}, " + base
    if construction == "temporal_suffix":
        base += " " + temporal; times = [temporal]
    return base + ".", {"modality": modality, "actor": actor, "action": action, "object": obj,
        "conditions": conditions, "exceptions": exceptions, "temporal": times}


def authored_document(split, ordinal):
    supported = ordinal % 4 != 3
    construction = CONSTRUCTIONS[split][ordinal % len(CONSTRUCTIONS[split])]
    count = 1 + (ordinal // 4) % 4
    if ordinal % 8 == 0: count = 3
    rendered = [render_clause(split, ordinal, i, construction) for i in range(count)]
    repeated = ordinal % 8 == 0
    if repeated:
        rendered[2] = deepcopy(rendered[0])
    clauses, chunks, cursor = [], [], 0
    for index, (text, rule) in enumerate(rendered):
        # Semicolons may end rules; periods inside Dept. and section decimals do not.
        if index < count - 1 and ordinal % 3 == 0:
            text = text[:-1] + ";"
        separator = ("\n" if ordinal % 2 == 0 else " ") if index else ""
        chunks.append(separator + text); cursor += len(separator)
        clauses.append({"char_start": cursor, "char_end": cursor + len(text), "rule": rule})
        cursor += len(text)
    text = "".join(chunks)
    negative_kind = None
    if not supported:
        first, _ = render_clause(split, ordinal, 0, "plain")
        second, _ = render_clause(split, ordinal, 1, "plain")
        if split == "train":
            kind = (ordinal // 4) % 3
            if kind == 0:
                text = f"Both following rules share the same condition: {first} {second}"
                negative_kind = "shared_condition_prefix"
            elif kind == 1:
                text = first[:-1] + " and publish the retained archive."
                negative_kind = "coordinated_action"
            else:
                text = first[:-1] + " unless " + second
                negative_kind = "nested_normative_exception"
        elif split == "tuning":
            text = f"Either {first[:-1]} or {second}"
            negative_kind = "exclusive_alternative"
        else:
            text = f"The following requirements apply respectively: {first} {second}"
            negative_kind = "shared_respectively_scope"
        clauses, repeated = [], False
        construction = "unsupported/" + negative_kind
    source = {"candidate_id": f"clause-{split}-{ordinal:03d}", "source_text": text, "source_sha256": boundary.text_sha(text)}
    boundary.tokenize(text)
    return {**source, "supported": supported, "construction": construction,
        "repeated_rule_occurrences": repeated, "clauses": clauses, "unsupported_reason": negative_kind,
        "label_origin": "new_authored_restricted_flat_profile_not_legal_authority"}


def validate_corpus(splits, fixtures):
    hashes, constructions = {}, {}
    for split, rows in splits.items():
        require(len(rows) == SPLIT_COUNTS[split] and len({r["candidate_id"] for r in rows}) == len(rows), "full split identity coverage required")
        hashes[split] = {r["source_sha256"] for r in rows}
        require(len(hashes[split]) == len(rows), "duplicate document source within split")
        constructions[split] = {r["construction"] for r in rows}
        for row in rows:
            require(boundary.text_sha(row["source_text"]) == row["source_sha256"], "authored document hash differs")
            if row["supported"]:
                declarations = [{"clause_id": f"authored-{index}", "char_start": r["char_start"], "char_end": r["char_end"],
                    "scope": compose.FLAT_SCOPE} for index, r in enumerate(row["clauses"])]
                compose.prepare_source_plan({k: row[k] for k in ("candidate_id", "source_text", "source_sha256")}, declarations)
            else:
                require(not row["clauses"], "unsupported fixture must not invent flat clauses")
    for left in hashes:
        for right in hashes:
            if left < right:
                require(not hashes[left] & hashes[right] and not constructions[left] & constructions[right],
                    "source or construction family crossed split")
    fixture_hashes = {boundary.text_sha(row["source_text"]) for row in fixtures}
    require(len(fixture_hashes) == len(fixtures) and not fixture_hashes & set.union(*hashes.values()), "fixtures overlap fitting/test sources")
    return {"counts": {k: len(v) for k, v in splits.items()}, "source_hashes_disjoint": True,
        "construction_families_disjoint": True, "fixture_sources_disjoint": True,
        "actor_prefixes_disjoint": len(set(ACTORS.values())) == 3,
        "constructions": {k: sorted(v) for k, v in constructions.items()},
        "test_scope": "unseen construction combinations for this boundary learner; authored and not independent statutory validation"}


def source_rows(rows):
    return [{key: row[key] for key in ("candidate_id", "source_text", "source_sha256")} for row in rows]


def evaluate(generation, references):
    require(len(generation["rows"]) == len(references), "complete document evaluation denominator required")
    counts, details = Counter(), []
    for prediction, reference in zip(generation["rows"], references):
        require(prediction["candidate_id"] == reference["candidate_id"] and prediction["source_sha256"] == reference["source_sha256"], "document prediction identity differs")
        tokens = boundary.tokenize(reference["source_text"])
        ends = {tokens[i]["char_end"] for i in prediction["boundary_token_indices"]}
        expected = {r["char_end"] for r in reference["clauses"]}
        counts["documents"] += 1
        counts[prediction["status"]] += 1
        counts["surface_guard_rejections"] += prediction["reason"] == "declared_surface_policy_unsupported_scope"
        counts["learned_scope_rejections_after_guard"] += prediction["reason"] == "learned_scope_abstention"
        counts["raw_scope_correct"] += prediction["raw_learned_scope_supported"] == reference["supported"]
        exact = False
        if reference["supported"]:
            counts["supported_documents"] += 1
            counts["raw_boundary_true_positive"] += len(ends & expected)
            counts["raw_boundary_false_positive"] += len(ends - expected)
            counts["raw_boundary_false_negative"] += len(expected - ends)
            counts["rule_count_correct"] += prediction["predicted_rule_count"] == len(reference["clauses"])
            counts["raw_boundary_document_exact"] += ends == expected
            counts["raw_supported_scope_correct"] += prediction["raw_learned_scope_supported"]
            wanted = [(r["char_start"], r["char_end"]) for r in reference["clauses"]]
            actual = [(r["char_start"], r["char_end"]) for r in prediction["plan"]["clauses"]] if prediction["plan"] else []
            exact = actual == wanted
            counts["exact_supported_segmentation"] += exact
            counts["reference_rule_occurrences"] += len(wanted)
            if reference["repeated_rule_occurrences"]:
                counts["repeated_documents"] += 1
                counts["repeated_documents_exact"] += exact
        else:
            counts["unsupported_documents"] += 1
            counts["unsupported_abstained"] += prediction["status"] == "abstained"
            counts["unsupported_accepted"] += prediction["status"] == "segmented"
            counts["raw_unsupported_scope_correct"] += not prediction["raw_learned_scope_supported"]
            exact = prediction["status"] == "abstained"
        counts["document_decision_exact"] += exact
        details.append({"candidate_id": reference["candidate_id"], "supported": reference["supported"],
            "construction": reference["construction"], "status": prediction["status"], "reason": prediction["reason"],
            "exact": exact, "predicted_rule_count": prediction["predicted_rule_count"],
            "reference_rule_count": len(reference["clauses"]) if reference["supported"] else None})
    result = dict(counts)
    tp, fp, fn = (counts[k] for k in ("raw_boundary_true_positive", "raw_boundary_false_positive", "raw_boundary_false_negative"))
    result.update(boundary_precision=tp / (tp + fp) if tp + fp else 0., boundary_recall=tp / (tp + fn) if tp + fn else 0.,
        boundary_f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0., rows=details,
        raw_boundary_metrics_include_supported_abstentions=True, **FALSE)
    return result


def punctuation_baseline(references):
    counts = Counter()
    for row in references:
        if not row["supported"]:
            continue
        tokens = boundary.tokenize(row["source_text"])
        ends = {token["char_end"] for token in tokens if token["text"] in (".", ";", "!", "?")}
        expected = {clause["char_end"] for clause in row["clauses"]}
        counts["supported_documents"] += 1
        counts["boundary_document_exact"] += ends == expected
        counts["rule_count_correct"] += len(ends) == len(expected)
        counts["true_positive"] += len(ends & expected)
        counts["false_positive"] += len(ends - expected)
        counts["false_negative"] += len(expected - ends)
    tp, fp, fn = counts["true_positive"], counts["false_positive"], counts["false_negative"]
    return {**dict(counts), "boundary_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.,
        "policy": "every period, semicolon, exclamation, or question-mark token ends a clause; no scope classifier",
        "semantic_accuracy_claimed": False}


def prepare(args):
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    splits = {split: [authored_document(split, i) for i in range(count)] for split, count in SPLIT_COUNTS.items()}
    fixtures = [
        {"source_text": "Fixture Council must retain records. Fixture Board may publish notices. Fixture Council must retain records."},
        {"source_text": "Both following rules share approval: Fixture Council must retain records. Fixture Board may publish notices."},
        {"source_text": "Fixture Council must retain records unless Fixture Board may publish notices."},
        {"source_text": "Fixture Dept. of Archives must retain records under section 19.7.\nFixture Board must not disclose reports."}]
    validation = validate_corpus(splits, fixtures)
    refs = {split: write(output / (split + '-references.json'), rows) for split, rows in splits.items()}
    sources = {split: write(output / (split + '-sources.json'), source_rows(rows)) for split, rows in splits.items()}
    fixture_ref = write(output / 'fixtures.json', fixtures)
    decoder_ref = ref(args.clause_decoder)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as span
    decoder = span.load_checkpoint(decoder_ref["path"], expected_sha256=decoder_ref["sha256"])
    require(decoder['config']['latent_dimension'] == 0, "predeclared source-only clause decoder required")
    pins = {str(Path(module.__file__).resolve()): files.sha(module.__file__) for module in
            (boundary, compose, span, calendar, calendar_summary, sys.modules[__name__])}
    plan = {"schema": SCHEMA, "references": refs, "sources": sources, "fixtures": fixture_ref,
        "config": deepcopy(boundary.CONFIG), "training_steps": 600, "stage_steps": [200, 400, 600],
        "maximum_training_seconds": 180, "selection": "maximum tuning document-decision exact, then supported segmentation exact, then earliest step",
        "clause_decoder": decoder_ref, "producer_pins": pins, "corpus_validation": validation,
        "scope_policy": {"profile": boundary.PROFILE, "surface_rejection_regex": boundary.UNSUPPORTED.pattern,
            "per_clause_surface_modal_count": 1, "full_source_coverage_required": True,
            "learned_scope_is_not_proof_of_independence": True},
        "punctuation_baseline": "every period, semicolon, exclamation, or question-mark token ends a clause; no scope classifier",
        "heldout_scope": "Boundary learner only: held-out authored constructions; existing clause decoder has earlier authored training",
        "fitting_references_frozen_before_training": True, **FALSE}
    write(output / 'plan.json', plan)
    print(json.dumps({"prepared": str(output / 'plan.json'), "validation": validation}), flush=True)


def decode_all(decoder, sources):
    reports = [decoder.decode(sources[start:start + 128]) for start in range(0, len(sources), 128)]
    return {"reports": reports, "rows": [row for report in reports for row in report['rows']],
            "target_access": False, "references_supplied": False}


def integrate(generation, sources, clause_decoder):
    by_id = {r['candidate_id']: r for r in sources}
    results = []
    for document in generation['rows']:
        record = {"candidate_id": document['candidate_id'], "source_sha256": document['source_sha256'],
                  "segmentation_status": document['status'], "segmentation_learned": True, "composition": None,
                  "clause_generation": None, "status": "abstained", "reason": document['reason'], **FALSE}
        if document['plan'] is not None:
            plan = document['plan']
            require(plan['source'] == by_id[document['candidate_id']], "learned segmentation source differs")
            report = clause_decoder.decode_formal_logic([r['source_text'] for r in plan['clauses']])
            record['clause_generation'] = report
            require(len(report['rows']) == plan['clause_count'], 'clause inference output coverage differs')
            try:
                predictions = [compose.attach_span_prediction(plan, clause['clause_id'], prediction,
                    scope=compose.FLAT_SCOPE, expected_plan_sha256=plan['plan_sha256'])
                    for clause, prediction in zip(plan['clauses'], report['rows'])]
                require(len(predictions) == plan['clause_count'], "clause decoder dropped an occurrence")
                composition = compose.compose_rule_list(plan, predictions, expected_plan_sha256=plan['plan_sha256'])
                record.update(status='composed', reason=None, composition=composition)
            except (ValueError, KeyError, TypeError) as error:
                record['reason'] = 'complete_document_composition_rejected: ' + str(error)
        results.append(record)
    require(len(results) == len(sources), "end-to-end document denominator differs")
    return results


def run(args):
    import torch
    torch.set_num_threads(1); torch.manual_seed(boundary.CONFIG['seed'])
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as span
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    plan_ref = ref(args.plan); plan = read(plan_ref)
    require(plan['schema'] == SCHEMA and plan['config'] == boundary.CONFIG and plan['training_steps'] == 600
        and plan['stage_steps'] == [200, 400, 600], "fixed predeclared training configuration required")
    require(all(files.sha(path) == wanted for path, wanted in plan['producer_pins'].items()), "producer changed after corpus freeze")
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    train, tuning = read(plan['references']['train']), read(plan['references']['tuning'])
    train_sources, tuning_sources, test_sources = (read(plan['sources'][split]) for split in ('train', 'tuning', 'test'))
    require(train_sources == source_rows(train) and tuning_sources == source_rows(tuning), "source/reference identity differs")
    network = boundary.model(torch)
    training_hash, tuning_hash = digest(train), digest(tuning)
    initial = boundary.checkpoint(network, steps=0, training_manifest_sha256=training_hash, tuning_manifest_sha256=tuning_hash)
    initial_ref = write(output / 'initial-checkpoint.json', initial)
    initial_test = decode_all(boundary.ClauseBoundaryDecoder(initial), test_sources)
    initial_generation_ref = write(output / 'initial-test-generation.json', initial_test)
    optimizer = torch.optim.Adam(network.parameters(), lr=boundary.CONFIG['learning_rate'])
    rng = random.Random(boundary.CONFIG['seed'])
    stages, losses, order, position = [], [], [], 0
    started = time.monotonic()
    for step in range(1, plan['training_steps'] + 1):
        require(time.monotonic() - started < plan['maximum_training_seconds'], "bounded training time exhausted")
        if position >= len(order):
            order = list(range(len(train))); rng.shuffle(order); position = 0
        chunk = [train[i] for i in order[position:position + boundary.CONFIG['batch_size']]]
        position += len(chunk)
        ids, features, lengths, labels, scopes, mask = boundary.tensor_batch(torch, chunk, labels=True)
        network.train(); optimizer.zero_grad(set_to_none=True)
        boundary_logits, scope_logits = network(ids, features, lengths)
        eligible = mask & scopes.bool()[:, None]
        require(bool(eligible.any()), "batch must contain supervised supported boundaries")
        # The learned head scores every token, including abbreviations and internal decimal punctuation.
        boundary_loss = torch.nn.functional.binary_cross_entropy_with_logits(boundary_logits[eligible], labels[eligible],
            pos_weight=torch.tensor(12.))
        scope_loss = torch.nn.functional.cross_entropy(scope_logits, scopes, weight=torch.tensor([3., 1.]))
        loss = boundary_loss + scope_loss
        require(bool(torch.isfinite(loss)), "nonfinite training objective")
        loss.backward(); torch.nn.utils.clip_grad_norm_(network.parameters(), 5.); optimizer.step()
        losses.append(float(loss.detach()))
        if step in plan['stage_steps']:
            cp = boundary.checkpoint(network, steps=step, training_manifest_sha256=training_hash, tuning_manifest_sha256=tuning_hash)
            cp_ref = write(output / f'checkpoint-{step}.json', cp)
            generation = decode_all(boundary.ClauseBoundaryDecoder(cp), tuning_sources)
            metrics = evaluate(generation, tuning)
            tuning_ref = write(output / f'tuning-{step}.json', {'generation': generation, 'metrics': metrics})
            stages.append({'steps': step, 'checkpoint': cp_ref, 'tuning': tuning_ref,
                'document_decision_exact': metrics['document_decision_exact'],
                'exact_supported_segmentation': metrics.get('exact_supported_segmentation', 0)})
            print(json.dumps({'phase': 'trained_stage', **stages[-1]}), flush=True)
    selected = max(stages, key=lambda row: (row['document_decision_exact'], row['exact_supported_segmentation'], -row['steps']))
    training_ref = write(output / 'training-frozen.json', {'schema': SCHEMA, 'plan': plan_ref, 'initial': initial_ref,
        'stages': stages, 'selected': selected, 'losses': losses, 'optimizer_steps_executed': len(losses),
        'elapsed_seconds': time.monotonic() - started, 'test_references_read': False, 'torch_threads': torch.get_num_threads(),
        'changed_parameter_names': sorted(k for k in initial['model_state'] if initial['model_state'][k] != cp['model_state'][k]), **FALSE})
    selected_cp = read(selected['checkpoint'])
    generation = decode_all(boundary.ClauseBoundaryDecoder(selected_cp), test_sources)
    replay = decode_all(boundary.ClauseBoundaryDecoder(read(selected['checkpoint'])), test_sources)
    require(generation == replay, "fresh boundary model numerical replay differs")
    generation_ref = write(output / 'test-generation-frozen.json', {'generation': generation, 'training': training_ref,
        'fresh_model_exact_generation_replay': True, 'test_references_read': False})
    clause_cp = span.load_checkpoint(plan['clause_decoder']['path'], expected_sha256=plan['clause_decoder']['sha256'])
    integration = integrate(generation, test_sources, span.DimensionalSpanDecoder(clause_cp))
    integration_ref = write(output / 'document-compositions-frozen.json', {'rows': integration, 'test_references_read': False,
        'clause_decoder': plan['clause_decoder'], 'boundary_generation': generation_ref})
    entries, unsupported_builds = [], []
    for record in integration:
        if record['composition'] is None: continue
        value = record['composition']; plan_hash = value['source_plan_sha256']
        candidate = compose.calendar_candidate(value, expected_plan_sha256=plan_hash)
        try:
            sidecar = calendar.synthetic_interpretation(candidate, policy=calendar.POLICY)
            compose.prepare_calendar_composition(value, sidecar, expected_plan_sha256=plan_hash)
            entry = {'candidate': candidate, 'interpretation': sidecar}
            require(gate.prepare_qualified_legal([entry], toolchain=args.toolchain).to_dict()['all_candidates_supported'], 'unsupported calendar candidate')
            entries.append(entry)
        except (ValueError, KeyError, TypeError) as error:
            unsupported_builds.append({'candidate_id': record['candidate_id'], 'reason': str(error)})
    selection_ref = write(output / 'build-selection-frozen.json', {'entries': entries, 'excluded_compositions': unsupported_builds,
        'source_documents': len(test_sources), 'test_references_read': False, 'interpretation_policy': calendar.POLICY})
    builds = []
    for start in range(0, len(entries), gate.MAX_ROWS):
        batch = entries[start:start + gate.MAX_ROWS]
        folder = output / f'lake-{start // gate.MAX_ROWS:02d}'
        receipt = gate.build_qualified_legal(batch, toolchain=args.toolchain, lake_executable=args.lake_executable,
            timeout_seconds=60, output_directory=folder).to_dict()
        receipt_ref = ref(folder / 'qualified-receipt.json')
        require(calendar_summary.verify_receipt(receipt_ref, batch) == receipt, 'independent compiler receipt replay differs')
        builds.append({'receipt': receipt_ref, 'candidate_ids': [r['candidate']['candidate_id'] for r in batch],
            'build_passed': receipt['build_passed'], 'backend_executed': receipt['backend_executed']})
    build_ref = write(output / 'builds-frozen.json', {'builds': builds, 'selection': selection_ref, 'test_references_read': False})
    # Test labels first enter this execution after training, selection, full generation, composition and builds freeze.
    test = read(plan['references']['test'])
    require(source_rows(test) == test_sources, 'posthoc test source commitment differs')
    metrics, baseline = evaluate(generation, test), evaluate(initial_test, test)
    targets = {r['candidate_id']: r for r in test}
    built = {identity for item in builds if item['build_passed'] for identity in item['candidate_ids']}
    counts, details = Counter(), []
    for record in integration:
        target = targets[record['candidate_id']]
        counts['documents'] += 1; counts[record['status']] += 1
        counts['supported_documents'] += target['supported']
        actual = record['composition']['source_rule_list'] if record['composition'] else None
        expected = [r['rule'] for r in target['clauses']] if target['supported'] else None
        exact = bool(target['supported'] and actual == expected)
        counts['exact_supported_documents'] += exact
        counts['built_documents'] += record['candidate_id'] in built
        counts['built_reference_mismatch'] += record['candidate_id'] in built and not exact
        if record['composition']:
            counts['composed_rule_occurrences'] += record['composition']['rule_count']
        if target['repeated_rule_occurrences']:
            counts['repeated_documents'] += 1
            counts['repeated_exact_documents'] += exact
        details.append({'candidate_id': record['candidate_id'], 'status': record['status'], 'reason': record['reason'],
            'supported': target['supported'], 'whole_document_reference_exact': exact, 'built': record['candidate_id'] in built})
    require(len(details) == 96, 'complete final document denominator required')
    summary = {'schema': SCHEMA, 'plan': plan_ref, 'training': training_ref, 'initial_test_generation': initial_generation_ref,
        'test_generation': generation_ref, 'composition': integration_ref, 'builds': build_ref,
        'segmentation_metrics': metrics, 'untrained_segmentation_metrics': baseline,
        'punctuation_baseline': punctuation_baseline(test),
        'end_to_end_metrics': dict(counts), 'document_details': details,
        'selected_step': selected['steps'], 'test_references_read_after_generation_and_builds': True,
        'actual_lake_build_executed': any(r['backend_executed'] for r in builds),
        'statutory_fidelity_or_general_scope_detection_claimed': False,
        'scope': 'Learned token boundaries and induced counts on held-out authored construction combinations; narrow surface guard plus learned eligibility; complete one-rule-per-clause decoder composition; no nested/shared-scope support', **FALSE}
    require(all(files.sha(path) == wanted for path, wanted in plan['producer_pins'].items()), 'producer changed during training/evaluation')
    write(output / 'summary.json', summary)
    print(json.dumps({'complete': str(output / 'summary.json'), 'segmentation': {k: v for k, v in metrics.items() if k != 'rows'},
        'end_to_end': dict(counts)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('--output', required=True); prep.add_argument('--clause-decoder', required=True)
    fit = sub.add_parser('run'); fit.add_argument('--plan', required=True); fit.add_argument('--output', required=True)
    fit.add_argument('--lake-executable', required=True); fit.add_argument('--toolchain', default='leanprover/lean4:v4.34.1')
    args = parser.parse_args()
    prepare(args) if args.action == 'prepare' else run(args)
