"""EAAEF-061: retrieval corpora stay separate and trust-filtered."""

from __future__ import annotations

from ipfs_datasets_py.retrieval.agent_work_corpora import (
    CORPORA,
    CorpusError,
    CorpusRecord,
    separate,
)
import pytest


def test_imported_claims_must_be_filtered() -> None:
    truth = CorpusRecord("repository_truth", "cid:file")
    claim = CorpusRecord("imported_claims", "cid:history")
    grouped = separate(truth, claim)
    assert grouped["repository_truth"] == ("cid:file",)
    assert grouped["imported_claims"] == ("cid:history",)
    assert "model_hypotheses" in CORPORA
    with pytest.raises(CorpusError, match="trust-filtered"):
        CorpusRecord("imported_claims", "cid:x", trust_filtered=False)


def test_unknown_corpus_fails() -> None:
    with pytest.raises(CorpusError, match="unknown"):
        CorpusRecord("vibes", "x")
