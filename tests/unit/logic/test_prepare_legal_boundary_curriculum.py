"""Authored boundary curriculum invariants and real sealed-input access audit."""
from collections import Counter
from copy import deepcopy
import builtins
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.ops.legal_ir import prepare_legal_boundary_curriculum as corpus


@pytest.fixture(scope="module")
def panels():
    return corpus.make_panels()


@pytest.fixture(scope="module")
def frozen(tmp_path_factory):
    path = tmp_path_factory.mktemp("boundary-curriculum") / "corpus"
    corpus.freeze(path)
    return path / "manifest.json"


def test_complete_balanced_source_case_and_modality_inventory(panels):
    values, ledger = panels
    corpus.validate_panels(values, ledger)
    for name, rows in values.items():
        assert len(rows) == corpus.COUNTS[name]
        assert sum(r["supported"] for r in rows) == corpus.SUPPORTED[name]
        rules = [c["rule"] for r in rows for c in r["clauses"]]
        assert len(set(Counter(r["modality"] for r in rules).values())) == 1
        for f in corpus.FIELDS[3:]: assert {bool(r[f]) for r in rules} == {False, True}


@pytest.mark.parametrize("family", corpus.FRESH_FAMILIES)
def test_fresh_coordinates_bind_two_qualifiers_and_single_modal(family):
    row = corpus.render("fresh", 7, family)
    corpus.mixed.validate_row(row)
    assert sum(bool(row["canonical_ir"]["rules"][0][f]) for f in corpus.FIELDS[3:]) == 2
    assert len(corpus.documents.boundary.MODAL.findall(row["source_text"])) == 1
    assert not corpus.documents.boundary.UNSUPPORTED.search(row["source_text"])


def test_repeated_occurrences_and_internal_periods_are_not_boundaries(panels):
    rows, _ = panels
    repeated = [r for r in rows["train"] if r["repeated_rule_occurrences"]]
    assert repeated
    for row in repeated:
        first, third = row["clauses"][0], row["clauses"][2]
        assert first["rule"] == third["rule"]
        assert first["char_start"] != third["char_start"]
    row = next(r for r in rows["train"] if r["supported"] and "Dept." in r["source_text"] and "section " in r["source_text"])
    ends = {c["char_end"] for c in row["clauses"]}
    periods = {t["char_end"] for t in corpus.documents.boundary.tokenize(row["source_text"]) if t["text"] == "."}
    assert periods - ends


def test_fresh_facet_absence_and_family_denominators(panels):
    rows = panels[0]["fresh"]
    assert Counter(r["construction"] for r in rows if r["supported"]) == {f: 12 for f in corpus.FRESH_FAMILIES}
    rules = [c["rule"] for r in rows for c in r["clauses"]]
    assert len(rules) == 180
    assert all(sum(bool(r[f]) for r in rules) == 120 for f in corpus.FIELDS[3:])


def test_scope_guards_never_receive_flat_references(panels):
    for rows in panels[0].values():
        for row in rows:
            if not row["supported"]:
                assert not row["clauses"]
                assert row["unsupported_reason"] in corpus.GUARDS
                assert not row["repeated_rule_occurrences"]


def test_tensor_batch_uses_complete_authored_occurrence_ends(panels):
    import torch
    rows = [r for r in panels[0]["train"] if r["repeated_rule_occurrences"]][:3]
    ids, features, lengths, ends, scopes, mask = corpus.documents.boundary.tensor_batch(torch, rows, labels=True)
    for i, row in enumerate(rows):
        assert ends[i].sum().item() == len(row["clauses"])
        assert scopes[i].item() == 1
        assert mask[i].sum().item() == lengths[i].item()


def test_corrupt_occurrence_coordinates_refused(panels):
    row = deepcopy(next(r for r in panels[0]["train"] if r["supported"]))
    row["clauses"][0]["char_end"] -= 1
    with pytest.raises(ValueError): corpus.validate_document(row)


def test_corrupt_coordinate_annotation_refused(panels):
    row = panels[0]["fresh"][0]
    annotation = deepcopy(next(a for a in panels[1]["document_rows"] if a["candidate_id"] == row["candidate_id"]))
    annotation["clause_coordinates"][0]["facet_spans"]["actor"][0] += 1
    with pytest.raises(ValueError): corpus.validate_document(row, annotation)


def test_overlap_source_or_clause_refused(panels):
    rows = panels[0]
    existing = rows["train"][2]
    clause = existing["clauses"][0]
    excluded = [existing["source_text"][clause["char_start"]:clause["char_end"]]]
    with pytest.raises(ValueError, match="overlaps"): corpus.previous.verify_disjoint(rows, excluded)


def test_real_exposure_inventory_has_no_fresh_matches(frozen):
    manifest = json.loads(frozen.read_bytes())
    evidence = corpus.read_ref(manifest["artifacts"]["exposure_audit"])
    assert evidence["fresh_clause_layout_matches"] == 0
    assert len(evidence["fresh_clause_evidence"]) == 180
    assert all(not r["matching_pools"] for r in evidence["fresh_clause_evidence"])
    assert {"new_boundary_training_clauses", "new_boundary_tuning_clauses", "exposed_construction_challenge_targets"} <= set(evidence["known_role_masked_layouts"])
    assert manifest["source_overlap_audit"]["normalized_source_or_clause_overlaps"] == 0


def test_loader_never_opens_sealed_targets_or_derived_evidence(frozen, monkeypatch):
    manifest = json.loads(frozen.read_bytes())
    denied = {Path(manifest["artifacts"][key]["path"]).resolve() for key in corpus.SEALED}
    original = builtins.open
    original_path = Path.open
    opened = []
    def checked(path):
        if isinstance(path, (str, bytes, Path)):
            resolved = Path(path).resolve(); opened.append(resolved)
            assert resolved not in denied, "sealed corpus artifact opened"
    def guarded(file, *args, **kwargs): checked(file); return original(file, *args, **kwargs)
    def guarded_path(self, *args, **kwargs): checked(self); return original_path(self, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", guarded)
    monkeypatch.setattr(Path, "open", guarded_path)
    loaded = corpus.load_training_inputs(frozen)
    assert len(loaded["new_train"]) == 384 and len(loaded["replay"]) == 192
    assert len(loaded["new_tuning"]) == len(loaded["fresh_sources"]) == 96
    assert all(set(r) == corpus.SOURCE_KEYS for r in loaded["fresh_sources"])
    assert not set(opened) & denied


def test_os_audit_enforces_actual_loader_seal(frozen):
    code = '''
import json, pathlib, sys
from scripts.ops.legal_ir import prepare_legal_boundary_curriculum as c
path=pathlib.Path(sys.argv[1]); manifest=json.loads(path.read_bytes())
denied={str(pathlib.Path(manifest['artifacts'][key]['path']).resolve()) for key in c.SEALED}
attempts=[]
def hook(event,args):
    if event == 'open' and isinstance(args[0], (str,bytes)):
        p=str(pathlib.Path(args[0]).resolve())
        if p in denied:
            attempts.append(p)
            raise RuntimeError('sealed artifact opened')
sys.addaudithook(hook)
loaded=c.load_training_inputs(path)
assert not attempts
print(json.dumps({'new_train':len(loaded['new_train']), 'denied_attempts':len(attempts)}))
'''
    result = subprocess.run([sys.executable, "-c", code, str(frozen)], cwd=corpus.ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"denied_attempts": 0' in result.stdout


def test_changed_fresh_source_bytes_rejected_without_target_read(frozen, tmp_path):
    manifest = json.loads(frozen.read_bytes())
    source = tmp_path / "sources.json"
    source.write_text("[]")
    manifest["artifacts"]["fresh_sources"]["path"] = str(source)
    altered = tmp_path / "manifest.json"; altered.write_text(json.dumps(manifest))
    with pytest.raises(ValueError): corpus.load_training_inputs(altered)


def test_added_reference_field_to_source_rejected(frozen, tmp_path):
    manifest = json.loads(frozen.read_bytes())
    rows = corpus.read_ref(manifest["artifacts"]["fresh_sources"])
    rows[0]["clauses"] = []
    source = tmp_path / "source.json"; source.write_text(json.dumps(rows))
    manifest["artifacts"]["fresh_sources"] = corpus.file_ref(source)
    path = tmp_path / "manifest.json"; path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="source-only"): corpus.load_training_inputs(path)


def test_frozen_output_is_not_overwritten(frozen):
    with pytest.raises(ValueError, match="already exists"): corpus.freeze(frozen.parent)
