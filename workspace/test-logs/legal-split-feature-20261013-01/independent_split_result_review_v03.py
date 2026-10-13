"""Independent direct recount of exposed references and frozen saved outputs.

No production/analyzer scorer is imported. Models/checkpoints remain opaque.
Reference access follows complete53+87 inventories and qualified released-runtime fences.
"""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import re
from datetime import datetime, timezone
import hashlib
import importlib.abc
import json
import math
import os
import struct
import sys

N = Path(__file__).resolve().parent
OLD = N.parent / "legal-targeted-loss-20261012-01"
PRIOR = N.parent / "legal-permission-retention-20261012-01"
STATES = ("baseline","all-parameters","span-heads-only","saved-score-hybrid","split-baseline","split-features")
OUTPUT = N / "result-independent-review-v01.json"
PACKET_ALLOWED = False
ARTIFACTS = {}
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
CELLS = ("split-features",)
COUNTS = dict(old_tune=96, fresh_tune=36, fresh_challenge=36, old_authored_eval=72,
              authored_dev=72, authored_eval=72, law=8)
MODALITIES = ("O", "P", "F")
SCORE_ROW_FIELDS = ('id','class_name','group_id','pair_id','pair_variant','raw_decoded',
    'reference_non_temporal_sha256','raw_exact_ir','joint_exact_ir','role_exact','joint_role_exact',
    'modality_exact','joint_modality_exact','expected_temporal_presence','predicted_temporal_presence',
    'temporal_presence_correct','temporal_false_positive','temporal_false_negative','temporal_ambiguous')


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers", "ipfs_datasets_py"}:
            raise ValueError("production/numerical/model import forbidden")
        return None


def require(value, message):
    if not value:
        raise ValueError(message)


def audit(event, args):
    require(not event.startswith(("subprocess.", "socket.", "os.exec", "os.spawn")) and event not in {
        "os.system", "os.fork", "os.posix_spawn", "os.kill", "os.killpg", "fcntl.flock",
        "os.remove", "os.rmdir", "os.mkdir", "os.rename", "os.replace", "os.unlink"}, "process/network/resource/mutation forbidden")
    if event == "open":
        path, mode, flags = args
        target = Path(os.fsdecode(path)).absolute() if isinstance(path, (str, bytes, os.PathLike)) else None
        require(PACKET_ALLOWED or target is None or "reference-packet" not in target.name,
                "packet gate closed until both frozen bundles verified")
        writing = isinstance(mode, str) and any(c in mode for c in "wax+")
        writing |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        require(not writing or target == OUTPUT, "only exclusive owned review may be written")
    if event in {"os.chmod","os.chown","os.truncate","os.utime","os.link","os.symlink"}:
        require(event == "os.chmod" and Path(args[0]).absolute() == OUTPUT and args[1] == 0o444, "only own review freeze allowed")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def f32(value):
    require(type(value) in (float, int) and math.isfinite(value), "finite saved scalar required")
    result = struct.unpack("<f", struct.pack("<f", value))[0]
    require(math.isfinite(result), "finite binary32 scalar required")
    return result


def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and path.is_file() and not path.is_symlink(), "canonical file required")
    require("private-runtime-snapshots" not in path.parts and path.name not in {
        "resources-start.json", "resources-final.json", "disk-reservations.json"}, "private bodies excluded")
    before = path.stat(); raw = path.read_bytes(); after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            and len(raw) == before.st_size <= 128 * 1024 * 1024, "source changed or oversized")
    result = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    key = str(path)
    require(key not in ARTIFACTS or ARTIFACTS[key] == result, "previous artifact identity changed")
    ARTIFACTS[key] = result
    return dict(path=key, **result)


def read(path):
    path = Path(path)
    require("checkpoint" not in path.name, "actual model JSON parsing forbidden")
    before = pin(path); raw = path.read_bytes()
    require(len(raw) <= 16 * 1024 * 1024 and hashlib.sha256(raw).hexdigest() == before["sha256"]
            and pin(path) == before, "parsed raw bytes differ from captured identity")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key"); result[key] = value
        return result
    def finite(value):
        result = float(value); require(math.isfinite(result), "nonfinite JSON number"); return result
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def same(descriptor):
    require(pin(descriptor["path"]) == descriptor, "raw descriptor differs")


def modal_bytes(vector):
    require(type(vector) is list and len(vector) == 3
            and all(type(v) is float and f32(v) == v for v in vector), "three actual binary32 logits required")
    return b"".join(struct.pack("<f", v) for v in vector)


def recount(saved, rows, metadata, raw, joint):
    require(len(rows) == len(raw["occurrences"]) == len(raw["inference"]["rows"]) == len(joint["rows"]) == saved["rows"], "complete panel coverage required")
    require(metadata is None or len(metadata) == len(rows), "complete metadata required")
    counters = {key: Counter() for key in ("head_first_argmax", "raw_decoded", "joint_decoded")}
    modal_classes = {}; modal_rows = []; ties = near = 0
    totals = Counter(); roles = {key: Counter() for key in ("raw", "joint")}
    classes = {}; pairs = {}; compact = {}
    for index, (source, occurrence, actual, chosen) in enumerate(zip(rows, raw["occurrences"], raw["inference"]["rows"], joint["rows"], strict=True)):
        key = source["id"]; source_hash = hashlib.sha256(source["source_text"].encode()).hexdigest()
        require(key == occurrence["id"] == chosen["id"] and source_hash == occurrence["source_sha256"]
                == actual["source_sha256"] == chosen["result"]["source_sha256"], "exact source/ID/hash join required")
        require(chosen["result"]["scores_sha256"] == digest(occurrence["scores"]), "selector score hash differs")
        vector = occurrence["scores"]["modality_logits"]; modal_bytes(vector)
        ordered = sorted(range(3), key=lambda i: (-vector[i], i))
        head = dict(first_argmax=MODALITIES[ordered[0]], maximum_tied=vector.count(vector[ordered[0]]) != 1,
                    within_ambiguity_guard=f32(vector[ordered[0]] - vector[ordered[1]]) <= 1e-7,
                    margin_binary32=f32(vector[ordered[0]] - vector[ordered[1]]))
        ties += head["maximum_tied"]; near += head["within_ambiguity_guard"]
        raw_ir = actual["canonical_ir"] if actual["status"] == "decoded" else None
        joint_ir = chosen["result"].get("canonical_ir")
        observed = dict(head_first_argmax=head["first_argmax"], raw_decoded=None if raw_ir is None else raw_ir["rules"][0]["modality"],
                        joint_decoded=None if joint_ir is None else joint_ir["rules"][0]["modality"])
        reference = source.get("canonical_ir"); target = None if reference is None else reference["rules"][0]
        meta = None if metadata is None else metadata[index]
        require(meta is None or meta["id"] == key, "metadata ID join differs")
        class_name = None if meta is None else meta["class_name"]
        if target is not None:
            for mode, value in observed.items():
                counters[mode][target["modality"] + "->" + (value or "abstained")] += 1
                if class_name is not None:
                    bucket = modal_classes.setdefault(class_name, {k: Counter() for k in counters})
                    bucket[mode][target["modality"] + "->" + (value or "abstained")] += 1
        modal_rows.append(dict(id=key, source_sha256=source_hash, class_name=class_name,
            reference_modality=None if target is None else target["modality"], head=head, observed_modalities=observed,
            raw_reason=actual.get("reason"), joint_reason=chosen["result"].get("reason")))
        if target is None:
            continue
        record = dict(id=key, raw_exact_ir=raw_ir == reference, joint_exact_ir=joint_ir == reference,
            raw_decoded=raw_ir is not None, observed_modalities=observed, reference_modality=target["modality"])
        totals["raw_exact_IR"] += record["raw_exact_ir"]; totals["joint_exact_IR"] += record["joint_exact_ir"]
        totals["raw_abstentions"] += raw_ir is None; totals["joint_abstentions"] += chosen["result"]["status"] != "selected"
        for mode, ir in (("raw", raw_ir), ("joint", joint_ir)):
            rule = None if ir is None else ir["rules"][0]
            totals["modality_exact" if mode == "raw" else "joint_modality_exact"] += rule is not None and rule["modality"] == target["modality"]
            for field in FIELDS:
                roles[mode][field] += rule is not None and rule[field] == target[field]
        values = occurrence["scores"]["presence_logits"]["temporal"]
        expected = bool(target["temporal"])
        predicted = None if abs(f32(values[1] - values[0])) <= 1e-7 else values[1] > values[0]
        record.update(temporal_presence_correct=predicted is expected, temporal_false_positive=predicted is True and not expected,
                      temporal_false_negative=predicted is False and expected, temporal_ambiguous=predicted is None)
        record.update(class_name=meta['class_name'],group_id=meta['group_id'],pair_id=meta['pair_id'],pair_variant=meta['pair_variant'],
            reference_non_temporal_sha256=digest({k:v for k,v in target.items() if k!='temporal'}),
            role_exact={f:raw_ir is not None and raw_ir['rules'][0][f]==target[f] for f in FIELDS},
            joint_role_exact={f:joint_ir is not None and joint_ir['rules'][0][f]==target[f] for f in FIELDS},
            modality_exact=raw_ir is not None and raw_ir['rules'][0]['modality']==target['modality'],
            joint_modality_exact=joint_ir is not None and joint_ir['rules'][0]['modality']==target['modality'],
            expected_temporal_presence=expected,predicted_temporal_presence=predicted)
        for field in ("temporal_presence_correct", "temporal_false_positive", "temporal_false_negative"):
            totals[field] += record[field]
        bucket = classes.setdefault(class_name, dict(rows=0, raw_decoded=0, raw_exact_ir=0, joint_exact_ir=0,
            temporal_presence_correct=0, temporal_false_positive=0, temporal_false_negative=0, temporal_ambiguous=0,
            reference_temporal_present=0))
        bucket["rows"] += 1; bucket["reference_temporal_present"] += expected
        for field in bucket:
            if field not in ("rows", "reference_temporal_present"):
                bucket[field] += record[field]
        if meta["pair_id"] is not None:
            pairs.setdefault(meta["pair_id"], []).append(record)
        compact[key] = record
    permission = {mode: dict(reference_P_rows=sum(v for k, v in values.items() if k.startswith("P->")),
        P_to_P=values.get("P->P", 0), P_to_O=values.get("P->O", 0), P_to_F=values.get("P->F", 0),
        P_abstentions=values.get("P->abstained", 0)) for mode, values in counters.items()}
    modalities = dict(rows=len(rows), reference_scored=all("canonical_ir" in row for row in rows),
        modality_confusions={k: dict(v) for k, v in counters.items()}, permission_counts=permission,
        by_class={k: {mode: dict(v) for mode, v in values.items()} for k, values in modal_classes.items()},
        head_maximum_ties=ties, head_within_ambiguity_guard=near,
        head_scope="First O,P,F argmax of saved logits, including every abstained row; tied/ambiguous head is reported explicitly, not promoted to decoded IR",
        row_observations=modal_rows)
    require(saved["modalities"] == modalities, "independent head/decoded modality recount differs")
    require(saved["semantic_accuracy"] is None, "no legal semantic accuracy permitted")
    if not compact:
        require(saved["raw_exact_IR"] is None and saved["joint_exact_IR"] is None
            and saved["raw_decoded"] == sum(row["status"] == "decoded" for row in raw["inference"]["rows"])
            and saved["joint_selected"] == sum(row["result"]["status"] == "selected" for row in joint["rows"]), "unreviewed law8 must remain unscored")
        return compact
    metrics = {k: totals[k] for k in ("raw_exact_IR", "joint_exact_IR", "raw_abstentions", "joint_abstentions", "modality_exact", "joint_modality_exact", "temporal_presence_correct")}
    metrics.update(temporal_false_positives=totals["temporal_false_positive"], temporal_false_negatives=totals["temporal_false_negative"],
        raw_exact_rate=totals["raw_exact_IR"] / len(rows), joint_exact_rate=totals["joint_exact_IR"] / len(rows),
        role_exact_counts=dict(roles["raw"]), joint_role_exact_counts=dict(roles["joint"]), classes=classes)
    for k, v in metrics.items():
        require(saved[k] == v, "independent panel recount differs: " + saved["state"] + "/" + saved["panel"] + "/" + k)
    pair_stats = []
    for pair_id, members in sorted(pairs.items()):
        require(len(members) == 2, "complete authored pair required")
        a, b = members
        pair_stats.append(dict(pair_id=pair_id, row_ids=[v["id"] for v in members], comparisons=1,
            raw_both_exact=int(a["raw_exact_ir"] and b["raw_exact_ir"]), joint_both_exact=int(a["joint_exact_ir"] and b["joint_exact_ir"]),
            temporal_both_correct=int(a["temporal_presence_correct"] and b["temporal_presence_correct"]),
            all_raw_exact=all(v["raw_exact_ir"] for v in members), all_temporal_correct=all(v["temporal_presence_correct"] for v in members)))
    require(saved["pairwise_consistency"] == pair_stats, "independent pair consistency differs")
    if 'score_rows' in saved:
        require(saved['score_rows'] == [{key:record[key] for key in SCORE_ROW_FIELDS} for record in compact.values()],
            'Independent retained hybrid per-row score payloads differ')
    return compact


def all_head_bytes(scores, source):
    require(set(scores) == {'schema','tokens','modality_logits','presence_logits','start_logits','end_logits'}
        and scores['schema'] == 'joint-source-span-scores/v1', 'Closed saved four-head scores required')
    tokens = [dict(text=m.group(), start=m.start(), end=m.end())
              for m in re.finditer(r'\w+|[^\w\s]', source, re.UNICODE)]
    require(scores['tokens'] == tokens and 1 <= len(tokens) <= 128, 'Exact complete source-token offsets required')
    chunks = [modal_bytes(scores['modality_logits'])]
    for field in ('presence_logits','start_logits','end_logits'):
        names = FIELDS[2:] if field == 'presence_logits' else FIELDS
        require(type(scores[field]) is dict and set(scores[field]) == set(names), 'Closed facet score names required')
        for name in names:
            values = scores[field][name]
            require(type(values) is list and len(values) == (2 if field == 'presence_logits' else len(tokens))
                and all(type(value) is float and f32(value) == value for value in values), 'Complete binary32 facet scores required')
            chunks.extend(struct.pack('<f', value) for value in values)
    return b''.join(chunks)


def load_frozen(manifest, expected_count, expected_cells):
    inventories, summaries, plans = {}, {}, {}
    for entry in manifest['cells']:
        for role in ('plan','summary','guardian_terminal','pre_admission'): same(entry[role])
        terminal = read(entry['guardian_terminal']['path'])
        require(type(terminal['returncode']) is int and type(terminal['child_returncode']) is int
            and terminal['returncode'] == terminal['child_returncode'] == 0 and terminal['artifacts_durable'] is True
            and terminal['resource_reservation_released'] is True, 'Durable released terminal required')
        cell = entry['cell']['id']
        require(cell in expected_cells and cell not in summaries, 'Closed distinct frozen cell inventory required')
        require(len(entry['results']) == (34 if cell == 'span-heads-only' else 53), 'Exact cell result count differs')
        for path, expected in entry['results'].items():
            require(path not in inventories and {k: pin(path)[k] for k in ('bytes','sha256')} == expected,
                'Complete raw frozen result inventory differs')
            inventories[path] = expected
        root = Path(entry['summary']['path']).parent
        require({str(path) for path in root.iterdir()} == set(entry['results']), 'Frozen result directory membership differs')
        summaries[cell], plans[cell] = read(entry['summary']['path']), read(entry['plan']['path'])
    require(len(inventories) == expected_count and set(summaries) == set(expected_cells), 'Complete frozen bundle required')
    return inventories, summaries, plans


def main():
    global PACKET_ALLOWED
    require(not os.path.lexists(OUTPUT), 'Exclusive fresh independent result receipt required')
    sys.dont_write_bytecode = True; sys.meta_path.insert(0, NoModels()); sys.addaudithook(audit)
    own = pin(Path(__file__).resolve())
    source_review = read(N / 'result-observer-source-independent-review-v01.json')
    require(source_review['schema'] == 'split-feature-result-observer-source-independent-review/v1'
        and source_review['passed'] is True and source_review['findings'] == [] and source_review['observer'] == own,
        'Exact clean independent observer source approval required')
    manifest = read(N / 'split-feature-output-freeze-v01.json')
    require(pin(N / 'split-feature-output-freeze-v01.json')['sha256'] == 'bcefd26d2b7ec9d96fd28d46ee3b6e69728d49a4cf13ababe50036a1d648c33b'
        and manifest['schema'] == 'split-feature-output-freeze/v1' and manifest['all_outputs_frozen'] is True
        and manifest['authorizes_authored_eval_scoring'] is True and manifest['new_trained_outputs_scored_before_freeze'] is False
        and manifest['reference_packet_previously_scored'] is True and manifest['independent_blinding'] is False,
        'Truthful new53 exposed-reference freeze required')
    current, summaries, plans = load_frozen(manifest, 53, ('split-features',))
    prior_manifest = read(PRIOR / 'two-cell-output-freeze-v01.json')
    require(pin(PRIOR / 'two-cell-output-freeze-v01.json')['sha256'] == '2a268b4b3f5c03cedb29d8d1df6d5718778fc54da9473fabfb5c2eaefde7d46b'
        and prior_manifest['all_two_outputs_frozen'] is True, 'Exact prior87 freeze required')
    prior, prior_summaries, prior_plans = load_frozen(prior_manifest, 87, ('all-parameters','span-heads-only'))
    require(pin(N / 'runtime-independent-review-v01.json') == dict(path=str(N/'runtime-independent-review-v01.json'), bytes=92760,
        sha256='455b0962c661d38c53ef6866940a9633d2aafdc6e6e9ef23da0cf2dc454b85f7'), 'Exact actual runtime qualification required')
    runtime = read(N / 'runtime-independent-review-v01.json')
    require(runtime['schema'] == 'split-feature-runtime-independent-review/v1' and runtime['passed'] is True
        and runtime['findings'] == [] and runtime['total_actual_returned_optimizer_updates'] == 32
        and runtime['result_file_count'] == 53 and runtime['all_original528_record_bodies_unchanged'] is True,
        'Qualified completed32 released-runtime review required')
    for path, expected in current.items(): require(runtime['artifacts'].get(path) == expected, 'Runtime/new53 raw joins differ')
    same(runtime['terminal_audit'])
    terminal_audit = read(runtime['terminal_audit']['path'])
    require(terminal_audit['schema'] == 'split-feature-terminal-resource-audit/v1'
        and terminal_audit['passed'] is True and terminal_audit['findings'] == []
        and terminal_audit['original_record_count'] == terminal_audit['opening_record_count'] == 528
        and terminal_audit['closing_record_count'] == 529 and terminal_audit['own_record_status'] == 'released'
        and terminal_audit['result_file_count'] == 53 and terminal_audit['trace']['returned_optimizer_updates'] == 32,
        'Concrete original528-preserving terminal audit required')
    prior_result = read(PRIOR / 'result-independent-review-v01.json')
    prior_runtime = read(PRIOR / 'runtime-independent-review-v01.json')
    prior_final = read(PRIOR / 'final-permission-retention-integration-independent-review-v01.json')
    for value in (prior_result, prior_runtime, prior_final):
        require(value['passed'] is True and value['findings'] == [], 'Qualified prior independent reviews required')
    require(pin(PRIOR / 'result-independent-review-v01.json')['sha256'] == '002bbe70e45d1c3b38b27adcc4328d05d640beab5f069b1826b7af55d32fa21e'
        and pin(PRIOR / 'runtime-independent-review-v01.json')['sha256'] == 'eb3dc46a2924941e06837351606a080225cd1c01d951d27603f5e3e6bbe3f2a0'
        and pin(PRIOR / 'final-permission-retention-integration-independent-review-v01.json')['sha256'] == 'b863307c5e6852eb6f6f9f4a7a7fa7629862a9b7982888441317aae2b62c6f87',
        'Exact prior independent receipt raw identities required')
    for path, expected in prior.items():
        require(prior_result['artifacts'].get(path) == prior_runtime['artifacts'].get(path) == expected,
            'Qualified prior87 result/runtime joins differ')
    require(pin(N / 'split-feature-result-analysis-v01.json') == dict(path=str(N/'split-feature-result-analysis-v01.json'), bytes=3104129,
        sha256='5231142d39114f032f06ab17d1ebdbf9735601ab173c5b70220758dbebd076d3'), 'Exact actual analyzed result required')
    analysis = read(N / 'split-feature-result-analysis-v01.json')
    require(analysis['schema'] == 'split-feature-exposed-result-analysis/v1' and analysis['passed'] is True
        and analysis['findings'] == [] and analysis['saved_output_pins'] == current
        and analysis['saved_output_count'] == 53 and analysis['retained_output_count'] == 87,
        'Clean complete actual split result analysis required')
    same(analysis['analyzer']); same(analysis['independent_source_review'])
    require(analysis['analyzer'] == dict(path=str(N/'analyze_split_feature_results_v04.py'), bytes=75056,
        sha256='64214a1983af4057da658b7339afb55c4ce5562ff4b517f3d74547939c283306'),
        'Exact qualified final v04 analyzer source required')
    qualification = read(analysis['independent_source_review']['path'])
    require(qualification['schema'] == 'split-feature-analyzer-source-independent-review/v1'
        and qualification['passed'] is True and qualification['findings'] == []
        and qualification['analyzer'] == analysis['analyzer'], 'Actual analyzer exact independent source qualification differs')
    hybrid = read(N / 'saved-score-hybrid-analysis-v01.json')
    require(pin(N / 'saved-score-hybrid-analysis-v01.json')['sha256'] == '8e4a2dec5d63379c27684255e4f2e040f094d73cd70fc64fc050df1e9437d22f'
        and hybrid['schema'] == 'saved-score-hybrid-exposed-diagnostic/v1' and hybrid['passed'] is True
        and hybrid['findings'] == [] and hybrid['trained_hybrid_model'] is False
        and hybrid['generated_model_checkpoint'] is None and hybrid['default_promotion'] is False,
        'Exact posthoc saved-score hybrid diagnostic required')
    same(hybrid['analyzer']); same(hybrid['independent_source_review'])
    registration = read(N / 'registration-v01.json'); export = read(N / 'training-export-v01.json')
    require(manifest['training_export'] == registration['data_export'] == plans['split-features']['data_export'],
        'Exact registered source export join differs')
    same(manifest['training_export']); same(manifest['registration'])
    for descriptor in registration['source_owner_pins'].values(): same(descriptor)
    require(len(registration['source_owner_pins']) == 33 and digest(export['training_populations']['mixed'])
        == registration['training_manifests']['mixed'] == plans['split-features']['training_manifest_sha256'],
        'Closed source33/common168 manifest required')
    require(manifest['reference_packet'] == prior_manifest['reference_packet'] == registration['reference_packet']
        == dict(path=str(OLD / 'authored-reference-packet-v01.json'), bytes=8262146,
            sha256='b926dbbc459c8d21a51fd8876598c8b3830a979730b44a4b3c8d15d8f613676e'), 'Exact previously exposed reference descriptor required')
    for path, expected in list(ARTIFACTS.items()): require({k: pin(path)[k] for k in ('bytes','sha256')} == expected, 'Pre-packet custody fence differs')
    PACKET_ALLOWED = True
    same(manifest['reference_packet']); packet = read(manifest['reference_packet']['path'])
    require(packet['geometry_review_packet']['semantic_gold'] is False
        and packet['geometry_review_packet']['evaluation_references_visible_to_builder_author'] is True
        and packet['split_contract']['shared_authored_templates'] is True
        and packet['split_contract']['statutory_provision_holdout'] is False
        and all(v is False for v in packet['authority'].values()), 'Exposed authored engineering reference scope required')
    evaluation = packet['geometry_review_packet']['authored_eval']
    eval_rows = [row['model_example'] for row in evaluation]
    eval_meta = [{k: row[k] for k in ('id','class_name','group_id','pair_id','pair_variant')} for row in evaluation]
    require(len(eval_rows) == 72 and [{k:v[k] for k in ('id','source_text','latent')} for v in eval_rows]
        == export['diagnostic_populations']['authored_eval'] and packet['diagnostic_populations'] == export['diagnostic_populations'],
        'Exact source-bound exposed authored references required')
    table = analysis['state_and_panel_results']
    require(len(table) == 42 and {(p['state'],p['panel']) for p in table} == {(s,p) for s in STATES for p in COUNTS},
        'Complete six-state42-panel analysis required')
    require([p for p in table if p['state'] in STATES[:4]] == hybrid['state_and_panel_results'],
        'Exact prior28 summaries differ from hybrid diagnostic')
    maps, captures, selections = {}, {}, {}
    for state in STATES:
        if state == 'saved-score-hybrid':
            descriptors = None
        else:
            summary = summaries['split-features'] if state.startswith('split-') else prior_summaries['all-parameters' if state == 'baseline' else state]
            descriptors = summary['baseline_panels'] if state in ('baseline','split-baseline') else summary['diagnostics']
            require([p['name'] for p in descriptors] == list(COUNTS), 'Complete ordered saved panels required')
        for position, panel in enumerate(COUNTS):
            saved = next(p for p in table if p['state'] == state and p['panel'] == panel)
            require(saved['rows'] == COUNTS[panel], 'Exact per-panel source count required')
            if descriptors is not None:
                descriptor = descriptors[position]
                for role in ('raw','joint'): same(descriptor[role])
                raw, joint = read(descriptor['raw']['path']), read(descriptor['joint']['path'])
                require((descriptor['score'] is None) == (panel in ('authored_eval','law')), 'Child evaluation/law target-access boundary differs')
            else:
                records = hybrid['hybrid_occurrences'][panel]
                raw = dict(occurrences=[{k:r[k] for k in ('id','source_sha256','scores')} for r in records],
                    inference=dict(rows=[r['reconstructed_greedy'] for r in records]))
                joint = dict(rows=[dict(id=r['id'],result=r['joint']) for r in records])
                for index, record in enumerate(records):
                    parent = captures['baseline',panel]['occurrences'][index]
                    adapted = captures['all-parameters',panel]['occurrences'][index]
                    expected = deepcopy(adapted['scores']); expected['modality_logits'] = deepcopy(parent['scores']['modality_logits'])
                    require(canonical(record['scores']) == canonical(expected) and record['id'] == parent['id'] == adapted['id']
                        and record['source_sha256'] == parent['source_sha256'] == adapted['source_sha256']
                        and record['provenance']['actual_model_forward'] is False and record['provenance']['trained_model'] is False
                        and record['provenance']['model_checkpoint'] is None, 'Independent exact donor-component hybrid composition differs')
            rows = eval_rows if panel == 'authored_eval' else export['diagnostic_populations'][panel]
            metadata = eval_meta if panel == 'authored_eval' else export['diagnostic_metadata'].get(panel)
            for source, occurrence in zip(rows, raw['occurrences'], strict=True): all_head_bytes(occurrence['scores'], source['source_text'])
            maps[state,panel] = recount(saved, rows, metadata, raw, joint)
            if descriptors is not None and descriptor['score'] is not None:
                same(descriptor['score']); child_score = read(descriptor['score']['path'])
                require(child_score['rows'] == [{k:r[k] for k in SCORE_ROW_FIELDS} for r in maps[state,panel].values()]
                    and child_score['classes'] == saved['classes'] and child_score['pairwise_consistency'] == saved['pairwise_consistency'],
                    'Independent saved child per-row/class/pair scores differ')
            captures[state,panel], selections[state,panel] = raw, joint
    comparisons = analysis['matched_recoveries_and_regressions']
    require(len(comparisons) == 24 and {(p['reference_state'],p['panel']) for p in comparisons}
        == {(s,p) for s in STATES[:4] for p in list(COUNTS)[:-1]}, 'Complete24 matched reference comparisons required')
    for comparison in comparisons:
        require(comparison['current_state'] == 'split-features', 'Exact new candidate comparison required')
        parent = maps[comparison['reference_state'],comparison['panel']]; current_rows = maps['split-features',comparison['panel']]
        require(set(parent) == set(current_rows), 'Matched complete score identities required')
        for mode in ('raw','joint'):
            for change, left, right in (('regressions',True,False),('recoveries',False,True)):
                expected = [k for k,v in parent.items() if v[mode+'_exact_ir'] is left and current_rows[k][mode+'_exact_ir'] is right]
                require(comparison['differences'][mode+'_'+change] == expected, 'Independent matched regression/recovery IDs differ')
    initial_bytes, modal_before, modal_after = bytearray(), bytearray(), bytearray()
    for panel in COUNTS:
        parent = captures['baseline',panel]; initial = captures['split-baseline',panel]; trained = captures['split-features',panel]
        rows = export['diagnostic_populations'][panel]
        require(len(parent['occurrences']) == len(initial['occurrences']) == len(trained['occurrences']) == COUNTS[panel], 'Full392 source coverage required')
        for source, a, b, c in zip(rows,parent['occurrences'],initial['occurrences'],trained['occurrences'],strict=True):
            require(a['id'] == b['id'] == c['id'] == source['id'] and a['source_sha256'] == b['source_sha256'] == c['source_sha256']
                and canonical(a['scores']) == canonical(b['scores'])
                and all_head_bytes(a['scores'],source['source_text']) == all_head_bytes(b['scores'],source['source_text']),
                'Initial parent392 four-head/source/token equality differs')
            initial_bytes.extend(all_head_bytes(b['scores'],source['source_text']))
            before, after = modal_bytes(b['scores']['modality_logits']), modal_bytes(c['scores']['modality_logits'])
            require(before == after, 'Final392 frozen modality binary32 bytes changed')
            modal_before.extend(before); modal_after.extend(after)
        keys = ('status','reason','canonical_ir','span_diagnostics','minimum_decision_logit_margin')
        require([{k:r.get(k) for k in keys} for r in parent['inference']['rows']]
            == [{k:r.get(k) for k in keys} for r in initial['inference']['rows']]
            and selections['baseline',panel]['rows'] == selections['split-baseline',panel]['rows'], 'Initial parent392 greedy/joint decisions differ')
        parent_metric = next(p for p in table if p['state']=='baseline' and p['panel']==panel)
        fresh_metric = next(p for p in table if p['state']=='split-baseline' and p['panel']==panel)
        require({k:v for k,v in parent_metric.items() if k!='state'} == {k:v for k,v in fresh_metric.items() if k!='state'},
            'Initial parent metrics differ')
    require(analysis['initial_parent_head_parity']['source_rows'] == 392
        and analysis['initial_parent_head_parity']['ordered_all_four_head_binary32_sha256'] == hashlib.sha256(initial_bytes).hexdigest(),
        'Initial complete392 ordered head-byte digest differs')
    require(analysis['trained_modality_retention']['source_rows'] == 392
        and analysis['trained_modality_retention']['bit_equal_count'] == 392
        and analysis['trained_modality_retention']['ordered_parent_and_trained_modality_sha256'] == hashlib.sha256(modal_before).hexdigest(),
        'Final modality392 count/byte digest differs')
    gates = {}
    for state in STATES:
        old = next(p for p in table if p['state']==state and p['panel']=='old_tune')
        permission = old['modalities']['permission_counts']
        gate = old['raw_exact_IR'] == old['joint_exact_IR'] == 96 and permission['raw_decoded']['P_to_O'] == permission['joint_decoded']['P_to_O'] == 0
        observed = analysis['exposed_old96_gate_observations'][state]
        require(observed['raw_exact_IR'] == old['raw_exact_IR'] and observed['joint_exact_IR'] == old['joint_exact_IR']
            and observed['permission_counts'] == permission and observed['exposed_old96_gate_met'] is gate
            and observed['necessary_engineering_gate_only'] is True and observed['model_selection_performed'] is False,
            'Independent old96 gate counts or scope differ')
        gates[state] = observed
    require(analysis['candidate_selected'] is None and analysis['default_promotion'] is False
        and analysis['recorded_actual_new_optimizer_updates'] == 32 and analysis['configured_dimension'] == 384
        and analysis['latent_enabled'] is False and analysis['external_latent_encoder_calls'] == 0
        and analysis['feature_paths_per_source_model_forward'] == 2 and analysis['equal_compute_budget_claimed'] is False
        and analysis['semantic_accuracy'] is None and analysis['independent_statutory_gold'] is False
        and analysis['trained_hybrid_model'] is False and analysis['Lake_executed'] is False, 'Result authority or compute scope differs')
    for path, expected in analysis['artifacts'].items():
        require({k:pin(path)[k] for k in ('bytes','sha256')} == expected, 'Closing exact analysis dependency differs')
    for name in ('run_split_features.py','prepare_split_features.py','run_scope_guardian.py','freeze_split_outputs_v02.py',
            'capture_split_terminal_v01.py','review_split_cell_v03.py','audit_split_terminal_v01.py',
            'root-science-source-independent-review-v01.json','trainer-source-independent-review-v01.json',
            'combined-pure-tests-v01.xml','combined-pure-tests-v01.log','combined-pure-tests-observation-v01.json',
            'split-feature-model-card-v01.md','split-feature-gaps-v01.md'): pin(N / name)
    for relative in ('ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_split_features.py',
            'tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_split_features_contracts.py'): pin(N / 'datasets' / relative)
    for path, expected in list(ARTIFACTS.items()):
        require({k:pin(path)[k] for k in ('bytes','sha256')} == expected, 'Closing complete independent read/result custody differs')
    result = dict(schema='split-feature-result-independent-review/v1',passed=True,findings=[],
        reviewer='permission_protocol_review; independent of analyzer/trainer authors',observed_at_utc=datetime.now(timezone.utc).isoformat(),
        analysis=pin(N/'split-feature-result-analysis-v01.json'),freeze_manifest=pin(N/'split-feature-output-freeze-v01.json'),
        runtime_review=pin(N/'runtime-independent-review-v01.json'),terminal_audit=runtime['terminal_audit'],
        actual_candidate_metrics=[p for p in table if p['state']=='split-features'],external_gate_observations=gates,
        source_states=list(STATES),state_and_panel_count=42,scored_source_rows=2304,unscored_law_source_rows=48,
        matched_regression_recovery_comparisons=24,all53_current_and87_retained_raw_outputs_bound=True,
        initial392_complete_heads_tokens_raw_joint_parent_equal=True,final392_modal_vectors_binary32_equal=True,
        initial_ordered_four_head_binary32_sha256=hashlib.sha256(initial_bytes).hexdigest(),
        parent_ordered_modal_binary32_sha256=hashlib.sha256(modal_before).hexdigest(),trained_ordered_modal_binary32_sha256=hashlib.sha256(modal_after).hexdigest(),
        review_method='Independent direct reference/raw/joint score counts, role/temporal/class/pair metrics, first-argmax and decoded confusions including abstentions,24 matched ID comparisons, old96 gate, donor-component hybrid check, initial392 heads and final392 modal byte checks. No analyzer/scorer predicates imported.',
        packet_access_after_complete53_plus87_and_qualified_runtime_fences=True,reference_packet_previously_exposed=True,
        default_promotion=False,independent_statutory_gold=False,shared_authored_templates=True,semantic_accuracy=None,
        statistical_significance_claimed=False,genuine_latent_semantics_tested=False,broader_logic_families_qualified=False,Lake_executed=False,
        trained_hybrid_model=False,equal_compute_budget_claimed=False,reviewer_model_calls=0,reviewer_checkpoint_JSON_parses=0,
        reviewer_resource_API_calls=0,full_record_bodies_published=False,artifacts=dict(ARTIFACTS),
        limitations=['All384 authored references were previously exposed and share templates; law8 is unreviewed and remains unscored.',
            'The saved hybrid is a posthoc engineering diagnostic, never a trained checkpoint.',
            'Partition, optimizer moments, gradients and branch-state hashes are source-qualified trainer observations; no numerical tensor or checkpoint replay.',
            'Exact parent modality retention preserves existing parent errors and does not guarantee complete IR retention. No checkpoint selection or default promotion.'])
    with OUTPUT.open('x') as stream:
        json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    OUTPUT.chmod(0o444)
    print(json.dumps(dict(passed=True,path=str(OUTPUT),candidate_gates=gates['split-features'])))


if __name__ == '__main__':
    main()

