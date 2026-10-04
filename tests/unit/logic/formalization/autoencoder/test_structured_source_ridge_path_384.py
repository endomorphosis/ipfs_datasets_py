"""Numerical equivalence and unchanged inference/provenance contracts."""
from copy import deepcopy
import hashlib

import pytest

np = pytest.importorskip("numpy")
from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_ridge_path_384 as subject
from .test_structured_source_384 import parent, rows, inputs


def grouped_rows(domain, split):
    return [{**row, "group_id": split + "-group-" + str(index // 2), "split": split}
        for index, row in enumerate(rows(domain, split))]


@pytest.mark.parametrize("domain", subject.shared.DOMAINS)
def test_all_domains_match_old_weights_predictions_and_inherited_projection(domain, parent, tmp_path):
    training, validation = grouped_rows(domain, "train"), grouped_rows(domain, "validation")
    before = deepcopy((training, validation, parent))
    options = {"ridges": [.0001, .001, .01, .1]}
    old = subject.grouped.train_grouped_source_decoder_384(domain, training, validation,
        parent_projection=parent, config=options)
    new = subject.train_grouped_source_decoder_384(domain, training, validation,
        parent_projection=parent, config=options)
    assert (training, validation, parent) == before
    one, two = old["checkpoint"], new["checkpoint"]
    for name in ("schema", "implementation", "parent_sha256", "parent_binding", "projection_width",
                 "projection_state", "projection_sha256", "input_transform", "target_schema", "config",
                 "training_manifest", "validation_manifest", "lineage"):
        assert one[name] == two[name]
    np.testing.assert_allclose(one["head_state"]["weights"], two["head_state"]["weights"], rtol=1e-8, atol=1e-10)
    assert one["head_state"]["bias"] == two["head_state"]["bias"]
    assert old["metrics"]["history"] == new["metrics"]["history"]
    assert old["metrics"]["selected_ridge"] == new["metrics"]["selected_ridge"] == options["ridges"][0]
    data = inputs(rows(domain, "validation"))
    first = subject.grouped.api.infer_structured_source_decoder_384(one, data)
    second = subject.grouped.api.infer_structured_source_decoder_384(two, data)
    assert [row["candidate_ir"] for row in first["rows"]] == [row["candidate_ir"] for row in second["rows"]]
    assert [row["predicted_classes"] for row in first["rows"]] == [row["predicted_classes"] for row in second["rows"]]
    assert all(not row["target_access"] and not row["teacher_forcing"] for row in second["rows"])
    raw = subject._raw(two); path = tmp_path / "checkpoint.json"; path.write_bytes(raw)
    loaded = subject.grouped.api.load_structured_source_decoder_384(path,
        expected_sha256=hashlib.sha256(raw).hexdigest(), expected_domain=domain)
    assert loaded.infer(data) == second
    metrics, report = new["metrics"], new["report"]
    assert metrics["trainer_id"] == subject.TRAINER_ID
    assert metrics["trainer_sha256"] == subject._pins()["trainer_sha256"]
    assert metrics["factorizations"] == 1 and old["metrics"]["factorizations"] == 4
    assert metrics["factorization_form"] == "dual" and metrics["factorization_dimension"] == 6
    assert metrics["full_fit_seconds"] >= metrics["fit_seconds"] >= metrics["factorization_seconds"] >= 0
    assert report["public_fit_seconds"] >= metrics["full_fit_seconds"]
    assert report["recipe"]["checkpoint_sha256"] == subject.digest(two)
    assert report["recipe_sha256"] == subject.digest(report["recipe"])
    assert report["recipe"]["producer"] == subject._pins()
    assert report["checkpoint_format_modified"] is False
    assert report["training_unique_group_count"] == 3 and report["training_variant_count"] == 6
    assert report["proof_authority"] is False


@pytest.mark.parametrize("population,expected_form,dimension", [(7, "dual", 7), (384, "primal", 384), (517, "primal", 384)])
def test_smaller_factorization_matches_old_dual_objective_for_entire_grid(population, expected_form, dimension):
    rng = np.random.default_rng(1729)
    x = rng.normal(size=(population, 384)); x -= x.mean(0); x /= max(float(np.linalg.norm(x) / population**.5), .01)
    y = rng.normal(size=(population, 5)); y -= y.mean(0)
    with subject.structured._numeric():
        path, metrics = subject._ridge_path(np, x, y)
        assert metrics["factorization_form"] == expected_form
        assert metrics["factorization_dimension"] == dimension
        assert metrics["scalar_class_count"] == 5
        assert metrics["factorizations"] == 1
        for ridge in (.0001, .001, .01, .1):
            expected = x.T @ np.linalg.solve(x @ x.T + ridge * np.eye(population), y)
            actual = subject._weights(np, path, ridge)
            np.testing.assert_allclose(actual, expected, rtol=5e-8, atol=1e-9)
            np.testing.assert_allclose(x @ actual, x @ expected, rtol=5e-8, atol=1e-9)
            # Ridge objective and normal-equation residual are independently
            # checked, including the primal path which old training never used.
            old_loss = np.square(x @ expected-y).sum() + ridge*np.square(expected).sum()
            new_loss = np.square(x @ actual-y).sum() + ridge*np.square(actual).sum()
            assert new_loss == pytest.approx(old_loss, rel=1e-10, abs=1e-10)
            assert np.linalg.norm(x.T @ (x @ actual-y) + ridge*actual) < 1e-8


def test_one_eigendecomposition_serves_all_ridges_and_classes(parent, monkeypatch):
    calls = []
    original = np.linalg.eigh
    def counted(value):
        calls.append(value.shape)
        return original(value)
    monkeypatch.setattr(np.linalg, "eigh", counted)
    monkeypatch.setattr(np.linalg, "solve", lambda *a, **k: pytest.fail("repeated solve used"))
    result = subject.train_grouped_source_decoder_384("intent_ir", grouped_rows("intent_ir", "train"),
        grouped_rows("intent_ir", "validation"), parent_projection=parent)
    assert calls == [(6, 6)]
    assert result["metrics"]["ridge_candidates"] == 4
    assert result["metrics"]["scalar_class_count"] == 4


def matrices():
    rng = np.random.default_rng(42)
    x = rng.normal(size=(4, 384)); x -= x.mean(0)
    y = rng.normal(size=(4, 3)); y -= y.mean(0)
    return x, y


def test_roundoff_negative_eigenvalue_is_explicitly_clipped(monkeypatch):
    original = np.linalg.eigh
    def tiny_negative(gram):
        values, vectors = original(gram)
        values[0] = -1e-14
        return values, vectors
    monkeypatch.setattr(np.linalg, "eigh", tiny_negative)
    with subject.structured._numeric():
        path, report = subject._ridge_path(np, *matrices())
    assert report["minimum_raw_eigenvalue"] == -1e-14
    assert report["roundoff_negative_eigenvalues_clipped"] >= 1
    assert path[1].min() == 0
    assert report["negative_eigenvalue_tolerance"] > 1e-14


@pytest.mark.parametrize("bad", [-1., float("nan"), float("inf")])
def test_materially_invalid_eigenvalue_is_not_silently_clipped(monkeypatch, bad):
    original = np.linalg.eigh
    def altered(gram):
        values, vectors = original(gram); values[0] = bad
        return values, vectors
    monkeypatch.setattr(np.linalg, "eigh", altered)
    with subject.structured._numeric(), pytest.raises(ValueError, match="eigen"):
        subject._ridge_path(np, *matrices())


@pytest.mark.parametrize("change", ["nan", "float32", "wrong_width", "wrong_rows", "empty_classes", "list"])
def test_numerical_input_contract_rejects_invalid_matrices(change):
    x, y = matrices()
    if change == "nan": x[0, 0] = np.nan
    elif change == "float32": x = x.astype(np.float32)
    elif change == "wrong_width": x = x[:, :383]
    elif change == "wrong_rows": y = y[:3]
    elif change == "empty_classes": y = y[:, :0]
    else: x = x.tolist()
    with pytest.raises(ValueError, match="matrices"):
        subject._ridge_path(np, x, y)


@pytest.mark.parametrize("ridge", [0, -1, float("inf"), float("nan"), True, 101])
def test_bad_ridge_rejected(ridge):
    with pytest.raises(ValueError, match="ridge"):
        subject._weights(np, None, ridge)


@pytest.mark.parametrize("key", subject.grouped.EXCLUSION_KEYS)
def test_grouped_leakage_stops_before_any_fit(monkeypatch, key):
    monkeypatch.setattr(subject, "_train_prepared", lambda *a, **k: pytest.fail("leakage reached fitting"))
    train, validation = grouped_rows("intent_ir", "train"), grouped_rows("intent_ir", "validation")
    if key in ("id", "group_id"): validation[0][key] = train[0][key]
    elif key == "source_sha256": validation[0]["source_text"] = train[0]["source_text"]
    elif key == "normalized_source_sha256": validation[0]["source_text"] = train[0]["source_text"].upper().replace(" ", "  ")
    else: validation[0]["embedding"] = deepcopy(train[0]["embedding"])
    with pytest.raises(ValueError, match="overlap"):
        subject.train_grouped_source_decoder_384("intent_ir", train, validation, parent_projection={})


@pytest.mark.parametrize("side,split", [("train", "test"), ("validation", "canary"), ("validation", "tuning")])
def test_wrong_roles_stopped_before_fit(monkeypatch, side, split):
    monkeypatch.setattr(subject, "_train_prepared", lambda *a, **k: pytest.fail("wrong role reached fitting"))
    train, validation = grouped_rows("intent_ir", "train"), grouped_rows("intent_ir", "validation")
    (train if side == "train" else validation)[0]["split"] = split
    with pytest.raises(ValueError, match="expected .* split"):
        subject.train_grouped_source_decoder_384("intent_ir", train, validation, parent_projection={})


@pytest.mark.parametrize("options", [{"ridges": []}, {"ridges": [1., .1]}, {"ridges": [1., 1.]}, {"ridge": .1}])
def test_bad_config_rejected_before_parent_access(options):
    with pytest.raises(ValueError, match="ridge|option"):
        subject.train("intent_ir", [], [], parent_projection={}, config=options)


def test_strict_ui_semantic_preflight_is_preserved(monkeypatch):
    train, validation = rows("ui_ux_ir", "train"), rows("ui_ux_ir", "validation")
    for row in train + validation:
        row["target"]["document"]["privacy_sensitivity"] = "sensitive"
    monkeypatch.setattr(subject.shared, "_parent", lambda *a: pytest.fail("invalid native UI reached parent"))
    with pytest.raises(ValueError, match="closed vocabulary"):
        subject.train("ui_ux_ir", train, validation, parent_projection={})


def test_source_pin_change_during_fit_rejected(parent, monkeypatch):
    first = subject._pins(); second = deepcopy(first); second["trainer_sha256"] = "0"*64
    pins = iter([first, second])
    monkeypatch.setattr(subject, "_pins", lambda: next(pins))
    with pytest.raises(ValueError, match="producer changed"):
        subject.train("intent_ir", rows("intent_ir", "train"), rows("intent_ir", "validation"), parent_projection=parent)


@pytest.mark.parametrize("population", [12, 400])
@pytest.mark.parametrize("ridge", [1e-12, 1e-30, 1e-100])
def test_rank_deficient_roundoff_cannot_produce_finite_but_invalid_weights(population, ridge):
    rng = np.random.default_rng(74)
    x = rng.normal(size=(population, 2)) @ rng.normal(size=(2, 384))
    x -= x.mean(0); x /= float(np.linalg.norm(x) / population**.5)
    y = rng.normal(size=(population, 3)); y -= y.mean(0)
    with subject.structured._numeric():
        path, report = subject._ridge_path(np, x, y)
        assert report["minimum_supported_ridge"] > ridge
        with pytest.raises(ValueError, match="too small for stable"):
            subject._weights(np, path, ridge)
        safe = subject._weights(np, path, .0001)
        assert np.max(np.abs(x.T @ (x @ safe-y)+.0001*safe)) < 1e-8


def test_tiny_config_is_rejected_for_actual_fit(parent):
    with pytest.raises(ValueError, match="too small for stable"):
        subject.train_grouped_source_decoder_384("intent_ir", grouped_rows("intent_ir", "train"),
            grouped_rows("intent_ir", "validation"), parent_projection=parent, config={"ridges": [1e-100]})


@pytest.mark.parametrize("domain", subject.shared.DOMAINS)
@pytest.mark.parametrize("alias", ["signed_zero", "int_float"])
def test_direct_train_numeric_alias_leakage_rejected_before_parent(domain, alias, monkeypatch):
    training, validation = rows(domain, "train"), rows(domain, "validation")
    original = training[0]["embedding"]
    if alias == "signed_zero":
        copied = [value if value != 0 else -0.0 for value in original]
    else:
        copied = [int(value) if value == int(value) else value for value in original]
    assert subject.digest(copied) != subject.digest(original)
    assert np.array_equal(np.asarray(copied), np.asarray(original))
    validation[0]["embedding"] = copied
    monkeypatch.setattr(subject.shared, "_parent", lambda *a: pytest.fail("numeric leakage reached parent/fitting"))
    with pytest.raises(ValueError, match="numeric_embedding_sha256 overlap"):
        subject.train(domain, training, validation, parent_projection={})


def test_direct_train_still_rejects_group_metadata_in_decoder_rows():
    training, validation = rows("intent_ir", "train"), rows("intent_ir", "validation")
    training[0]["group_id"] = "must-not-enter-input"
    with pytest.raises(ValueError, match="closed domain row"):
        subject.train("intent_ir", training, validation, parent_projection={})


@pytest.mark.parametrize("entrypoint", ["direct", "grouped"])
def test_each_public_entrypoint_audits_each_split_exactly_once(parent, monkeypatch, entrypoint):
    calls, exclusions = [], []
    original, exclude = subject.grouped._prepare, subject.grouped._exclude
    def tracked(domain, data, split):
        calls.append((domain, split, len(data)))
        return original(domain, data, split)
    def tracked_exclude(training, validation):
        exclusions.append((training, validation))
        return exclude(training, validation)
    monkeypatch.setattr(subject.grouped, "_prepare", tracked)
    monkeypatch.setattr(subject.grouped, "_exclude", tracked_exclude)
    if entrypoint == "direct":
        subject.train("intent_ir", rows("intent_ir", "train"), rows("intent_ir", "validation"), parent_projection=parent)
    else:
        result = subject.train_grouped_source_decoder_384("intent_ir", grouped_rows("intent_ir", "train"),
            grouped_rows("intent_ir", "validation"), parent_projection=parent)
        report = result["report"]
        assert report["input_audit_passes_per_split"] == 1
        assert report["complete_recipe_seconds"] >= report["public_fit_seconds"] + report["training_validation_audit_seconds"]
        assert report["complete_recipe_training_variants_per_second"] == pytest.approx(6 / report["complete_recipe_seconds"])
    assert calls == [("intent_ir", "train", 6), ("intent_ir", "validation", 6)]
    assert len(exclusions) == 1
