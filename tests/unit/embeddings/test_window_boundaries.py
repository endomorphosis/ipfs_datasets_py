"""Boundary semantics must come from actual supplied vectors, not punctuation."""
import hashlib

import pytest

from ipfs_datasets_py.ml.embeddings import window_boundaries as boundaries


def complete(text, report):
    cursor = 0
    for atom in report["atoms"]:
        assert atom["start_char"] == cursor < atom["end_char"]
        cursor = atom["end_char"]
    assert cursor == len(text)
    assert report["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert report["proof_authority"] is report["execution_authority"] is False


def test_existing_sentence_api_and_exact_layout(monkeypatch):
    calls = []
    native = boundaries.sentence_source_spans_with_diagnostics
    def spy(text):
        calls.append(text)
        return native(text)
    monkeypatch.setattr(boundaries, "sentence_source_spans_with_diagnostics", spy)
    text = "  Read café.\n\nArchive logs.  "
    report = boundaries.prepare_window_atoms(text)
    assert calls == [text]
    complete(text, report)
    assert report["candidates"] == [{"offset": text.index("Archive"), "kind": "sentence", "priority": 1}]
    assert report["sentence_reports"][0]["backend"]


def test_sentences_do_not_cross_supplied_structural_blocks(monkeypatch):
    calls = []
    native = boundaries.sentence_source_spans_with_diagnostics
    def spy(text):
        calls.append(text)
        return native(text)
    monkeypatch.setattr(boundaries, "sentence_source_spans_with_diagnostics", spy)
    text = "First fragment\nSecond fragment."
    cut = text.index("Second")
    report = boundaries.prepare_window_atoms(text, structural_boundaries=[cut, 0, cut, len(text)])
    complete(text, report)
    assert calls == [text[:cut], text[cut:]]
    assert report["structural_boundaries"] == [cut]
    assert report["candidates"] == [{"offset": cut, "kind": "supplied_structure", "priority": 3}]


@pytest.mark.parametrize("format", ["code", "diff", "opaque"])
def test_nonprose_never_uses_sentence_splitter(monkeypatch, format):
    monkeypatch.setattr(boundaries, "sentence_source_spans_with_diagnostics",
        lambda _: pytest.fail("must not parse code/diff/opaque as prose"))
    text = 'call("x.y");\r\nnext();\n'
    report = boundaries.prepare_window_atoms(text, format=format)
    complete(text, report)
    assert report["sentence_reports"] == []
    assert report["candidates"] == [{"offset": text.index("next"), "kind": "line_fallback", "priority": 1}]
    assert all(atom["kind"] == "lexical_line" for atom in report["atoms"])


def test_structural_atoms_keep_internal_lines_separate_from_semantic_inputs():
    text = "first();\nsecond();\nthird();\n"
    strong = text.index("third")
    report = boundaries.prepare_window_boundaries(text, format="code", structural_boundaries=[strong],
        embedder=lambda _: pytest.fail("all joins are structural; no semantic decision"),
        embedding_eligible=lambda _: True)
    complete(text, report)
    assert [text[row["start_char"]:row["end_char"]] for row in report["atoms"]] == [text[:strong], text[strong:]]
    assert report["candidates"] == [
        {"offset": text.index("second"), "kind": "line_fallback", "priority": 1},
        {"offset": strong, "kind": "supplied_structure", "priority": 3}]
    assert report["grouping"] is None
    assert report["semantic_comparison_required"] is False
    assert report["diagnostics"]["all_joins_structural_embedding_skipped"] is True
    assert report["diagnostics"]["semantic_candidates"] == 0


def test_partial_barriers_win_when_other_joins_need_semantic_scoring():
    text = "Read logs. Archive reports.\nNotify operators."
    strong = text.index("Notify")
    report = boundaries.prepare_window_boundaries(text, structural_boundaries=[strong],
        embedder=lambda _: [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]],
        embedding_eligible=lambda _: True)
    assert report["semantic_comparison_required"] is True
    assert report["candidates"] == [
        {"offset": text.index("Archive"), "kind": "semantic", "priority": 2},
        {"offset": strong, "kind": "supplied_structure", "priority": 3}]
    assert report["grouping"]["boundaries"][1]["reason"] == "structural_barrier"


def test_real_vectors_control_semantic_priority_and_are_replayable():
    text = "Read logs. Archive reports. Notify operators."
    inputs = []
    def embed(parts):
        inputs.extend(parts)
        return [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    report = boundaries.prepare_window_boundaries(text, embedder=embed, embedding_eligible=lambda _: True)
    complete(text, report)
    assert "".join(inputs) == text
    assert report["candidates"] == [
        {"offset": text.index("Archive"), "kind": "sentence", "priority": 1},
        {"offset": text.index("Notify"), "kind": "semantic", "priority": 2}]
    assert report["diagnostics"]["embeddings_used"] is True
    assert report["diagnostics"]["token_budget_checked"] is True
    assert report["diagnostics"]["final_payload_token_budget_checked"] is False
    native = report["grouping"]
    assert native["normalized_vectors_sha256"] and native["embedding_input_sha256"]
    assert native["config"]["min_chars"] == 0
    assert native["config"]["max_chars"] == len(text)
    assert [row["cosine_similarity"] for row in native["boundaries"]] == [1.0, 0.0]


def test_no_embedder_means_structural_only_not_semantic():
    report = boundaries.prepare_window_boundaries("Read logs. Archive reports.")
    assert report["diagnostics"]["embedding_status"] == "structural_only"
    assert report["grouping"] is None
    assert all(row["priority"] == 1 for row in report["candidates"])


@pytest.mark.parametrize("text", ["", "   ", "Single sentence."])
def test_no_pair_skips_embedding(text):
    report = boundaries.prepare_window_boundaries(text,
        embedder=lambda _: pytest.fail("no adjacent pair"), embedding_eligible=lambda _: True)
    complete(text, report)
    assert report["diagnostics"]["embedding_status"] == "not_required"
    assert report["diagnostics"]["single_atom_embedding_skipped"] is True


@pytest.mark.parametrize("failure", ["raise", "nonfinite", "wrong_count", "zero"])
def test_embedding_failure_is_explicit_structural_fallback(failure):
    def embed(parts):
        if failure == "raise":
            raise RuntimeError("provider unavailable")
        if failure == "nonfinite":
            return [[float("nan"), 0.0] for _ in parts]
        if failure == "wrong_count":
            return []
        return [[0.0, 0.0] for _ in parts]
    report = boundaries.prepare_window_boundaries("Read logs. Archive reports.",
        embedder=embed, embedding_eligible=lambda _: True)
    assert report["diagnostics"]["embedding_status"] == "structural_fallback"
    assert report["diagnostics"]["embeddings_used"] is False
    assert report["diagnostics"]["semantic_candidates"] == 0
    assert report["grouping"]["embedding_error_type"]
    assert all(row["priority"] == 1 for row in report["candidates"])


def test_oversize_and_token_ineligible_atoms_are_never_embedded():
    text = "short\n" + "x"*40 + "\nblocked\nlast\n"
    inputs = []
    def embed(parts):
        inputs.extend(parts)
        return [[1.0, 0.0] for _ in parts]
    report = boundaries.prepare_window_boundaries(text, format="opaque", embedder=embed,
        embedding_eligible=lambda part: "blocked" not in part, max_embedding_chars=20)
    assert inputs == ["short\n", "last\n"]
    assert {row["reason"] for row in report["grouping"]["opaque_atoms"]} == {
        "atom_exceeds_embedding_chars", "atom_exceeds_embedding_token_budget"}
    assert all(row["priority"] == 1 for row in report["candidates"])


@pytest.mark.parametrize("kwargs", [
    {"embedder": lambda _: []}, {"embedder": 1}, {"embedding_eligible": 1},
    {"max_embedding_chars": True}, {"max_embedding_chars": 0},
    {"similarity_threshold": True}, {"similarity_threshold": float("nan")},
    {"similarity_threshold": 1.1}])
def test_invalid_embedding_configuration_fails_even_without_pairs(kwargs):
    with pytest.raises(boundaries.WindowBoundaryError):
        boundaries.prepare_window_boundaries("", **kwargs)


@pytest.mark.parametrize("kwargs", [
    {"format": "markdown"}, {"structural_boundaries": None},
    {"structural_boundaries": [True]}, {"structural_boundaries": [-1]},
    {"structural_boundaries": [100]}, {"structural_boundaries": [1.5]}])
def test_invalid_source_offsets_and_format(kwargs):
    with pytest.raises(boundaries.WindowBoundaryError):
        boundaries.prepare_window_atoms("abc", **kwargs)


def test_eligibility_callback_errors_are_not_hidden_by_structural_fallback():
    with pytest.raises(RuntimeError, match="tokenizer failed"):
        boundaries.prepare_window_boundaries("Read logs. Archive reports.", embedder=lambda _: [],
            embedding_eligible=lambda _: (_ for _ in ()).throw(RuntimeError("tokenizer failed")))


def ranked_fixture():
    return boundaries.prepare_window_boundaries('Read logs. Archive reports. Notify operators.',
        embedder=lambda _: [[1., 0.], [.9, .4358898943540673], [1., 0.]],
        embedding_eligible=lambda _: True)


def test_ranked_selection_reuses_all_measured_scores_above_existing_threshold(monkeypatch):
    threshold = ranked_fixture()
    assert threshold['diagnostics']['semantic_candidates'] == 0
    monkeypatch.setattr(boundaries, 'group_semantic_atoms', lambda *args, **kwargs: pytest.fail('no new scores'))
    ranked = boundaries.rank_semantic_boundaries(threshold)
    assert threshold['diagnostics']['semantic_candidates'] == 0
    assert all(row['priority'] == 1 for row in threshold['candidates'])
    assert ranked['diagnostics']['semantic_candidates'] == 2
    assert ranked['diagnostics']['semantic_selection'] == 'ranked'
    assert ranked['diagnostics']['absolute_topic_break_claimed'] is False
    assert ranked['diagnostics']['new_scores_computed'] is False
    assert all(row['kind'] == 'semantic_ranked' and row['priority'] == 2 for row in ranked['candidates'])
    assert [row['semantic_score'] for row in ranked['candidates']] == pytest.approx([.9, .9])
    assert ranked['grouping'] == threshold['grouping']
    assert boundaries.rank_semantic_boundaries(ranked) == ranked


def test_prepare_ranked_invokes_existing_native_grouping_exactly_once(monkeypatch):
    called = []
    native = boundaries.group_semantic_atoms
    def grouped(*args, **kwargs):
        called.append(kwargs['similarity_threshold'])
        return native(*args, **kwargs)
    monkeypatch.setattr(boundaries, 'group_semantic_atoms', grouped)
    ranked = boundaries.prepare_window_boundaries('Read logs. Archive reports.',
        embedder=lambda _: [[1., 0.], [.9, .4358898943540673]],
        embedding_eligible=lambda _: True, semantic_selection='ranked')
    assert called == [.5]
    assert ranked['diagnostics']['semantic_candidates'] == 1
    assert ranked['candidates'][0]['semantic_score'] == pytest.approx(.9)


def test_compact_score_replay_requires_external_bank_binding_and_never_reads_it():
    report = ranked_fixture()
    report['grouping'].pop('normalized_vectors')
    with pytest.raises(boundaries.WindowBoundaryError):
        boundaries.rank_semantic_boundaries(report)
    report['vector_bank_ref'] = {'path': '/not/read/by/pure/helper.json', 'sha256': 'a'*64, 'size_bytes': 999}
    ranked = boundaries.rank_semantic_boundaries(report)
    assert ranked['diagnostics']['vector_bank_pin_binding'] == 'caller_verified'
    assert ranked['diagnostics']['semantic_candidates'] == 2


def test_ranking_preserves_structural_priority_and_skips_unpaired_opaque_atoms():
    text = 'Read logs. Archive reports. Notify operators. Blocked sentence. Last instruction.'
    point = text.index('Notify')
    report = boundaries.prepare_window_boundaries(text, structural_boundaries=[point],
        embedder=lambda parts: [[1., 0.] for _ in parts],
        embedding_eligible=lambda part: 'Blocked' not in part, semantic_selection='ranked')
    assert report['diagnostics']['semantic_candidates'] == 1
    candidate_map = {row['offset']: row for row in report['candidates']}
    assert candidate_map[point] == {'offset': point, 'kind': 'supplied_structure', 'priority': 3}
    assert candidate_map[text.index('Blocked')]['priority'] == 1
    assert candidate_map[text.index('Last')]['priority'] == 1


def test_ranked_without_embeddings_is_explicit_structural_fallback():
    report = boundaries.prepare_window_boundaries('Read logs. Archive reports.', semantic_selection='ranked')
    assert report['diagnostics']['embedding_status'] == 'structural_only'
    assert report['diagnostics']['semantic_candidates'] == 0
    assert all(row['priority'] == 1 for row in report['candidates'])


@pytest.mark.parametrize('mutation', [
    lambda report: report['grouping'].update(source_sha256='a'*64),
    lambda report: report['atoms'][0].update(end_char=1),
    lambda report: report['grouping']['atoms'][0].update(end_char=1),
    lambda report: report['grouping']['boundaries'][0].update(before_atom=2),
    lambda report: report['grouping']['boundaries'][0].update(cosine_similarity=float('nan')),
    lambda report: report['grouping']['boundaries'][0].update(cosine_similarity=True),
    lambda report: report['grouping']['boundaries'][0].update(cosine_similarity=1.01),
    lambda report: report['grouping'].update(embedding_input_atom_indexes=[0, 2]),
    lambda report: report['grouping']['config'].update(barriers=[1]),
    lambda report: report['grouping']['config'].update(token_budget_checked=False),
    lambda report: report['candidates'][0].update(offset=1),
    lambda report: report['candidates'][0].update(priority=3),
])
def test_rank_replay_rejects_mismatched_or_nonfinite_scored_reports(mutation):
    report = ranked_fixture()
    mutation(report)
    with pytest.raises(boundaries.WindowBoundaryError):
        boundaries.rank_semantic_boundaries(report)


def test_invalid_semantic_selection_rejected():
    with pytest.raises(boundaries.WindowBoundaryError):
        boundaries.prepare_window_boundaries('', semantic_selection='guessed')
