from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pytest

from ipfs_datasets_py.logic.flogic import FLogicFrame
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1._daemon_snapshot.flogic_optimizer import FLogicSemanticOptimizer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1._daemon_snapshot.codec import DeterministicModalLogicCodec, ModalLogicCodecConfig

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.daemon_frame_scope import ObservationScopedFLogicOptimizer


@pytest.mark.parametrize("triples", [
    [{"subject": "law", "predicate": "modality", "object": "O"}],
    [{"subject": "law", "predicate": "", "object": "O"}],
    [{"subject": "law", "predicate": "selected_ontology_frame", "object": "a"},
     {"subject": "law", "predicate": "selected_ontology_frame", "object": "b"}],
])
def test_preserves_exact_historical_results_and_preloaded_frames(triples):
    old = FLogicSemanticOptimizer()
    bounded = ObservationScopedFLogicOptimizer()
    saved = FLogicFrame(object_id="preloaded", scalar_methods={"source": "earlier"})
    ergo = bounded._get_ergo()
    ergo.add_frame(saved)
    bounded.add_ontology_class("PreloadedClass")
    classes = list(ergo.ontology.classes)
    frames = ergo.ontology.frames
    for _ in range(5):
        expected = old.evaluate("source", "decoded", [.1] * 8, [.2] * 8, triples)
        actual = bounded.evaluate("source", "decoded", [.1] * 8, [.2] * 8, triples)
        assert asdict(actual) == asdict(expected)
        assert ergo.ontology.frames is frames
        assert ergo.ontology.frames == [saved]
        assert ergo.ontology.frames[0] is saved
        assert ergo.ontology.classes == classes
    assert len(old._get_ergo().ontology.frames) == 5


def test_failure_after_appending_discards_temporary_frames(monkeypatch):
    bounded = ObservationScopedFLogicOptimizer()
    ergo = bounded._get_ergo()
    saved = FLogicFrame(object_id="preloaded")
    ergo.add_frame(saved)
    original = ergo.add_frame
    def append_then_fail(frame):
        original(frame)
        raise RuntimeError("simulated append failure")
    monkeypatch.setattr(ergo, "add_frame", append_then_fail)
    with pytest.raises(RuntimeError, match="simulated append failure"):
        bounded._check_flogic_consistency([{"subject": "law", "predicate": "p", "object": "x"}])
    assert ergo.ontology.frames == [saved]


def test_shared_optimizer_serializes_and_discards_each_observation():
    bounded = ObservationScopedFLogicOptimizer()
    triples = [{"subject": "law", "predicate": "p", "object": "x"}]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: bounded.evaluate("source", "decoded", [.1] * 8, [.2] * 8, triples), range(20)))
    assert all(asdict(row) == asdict(rows[0]) for row in rows)
    assert bounded._get_ergo().ontology.frames == []


def test_entire_daemon_codec_result_matches_legacy_across_repeats():
    config = ModalLogicCodecConfig(parser_backend="spacy", spacy_model_name="definitely_missing_legal_model", use_flogic=True)
    old = DeterministicModalLogicCodec(config)
    bounded = DeterministicModalLogicCodec(config, flogic_optimizer=ObservationScopedFLogicOptimizer(config=old.flogic_optimizer.config))
    for text in ("The agency shall submit reports.", "The agency shall not disclose records.",
                 "Company A shall submit backup report within 10 days unless emergency."):
        for _ in range(2):
            options = dict(document_id="fixture", citation="5 USC 1", source="us_code", source_embedding=[.1] * 8)
            expected = old.encode(text, **options).to_dict()
            actual = bounded.encode(text, **options).to_dict()
            assert actual == expected
            assert bounded.flogic_optimizer._get_ergo().ontology.frames == []
    assert len(old.flogic_optimizer._get_ergo().ontology.frames) > 0
