#!/usr/bin/env python3
"""Fixed postfit observer for the paraphrase-modality auxiliary comparison.

Reuse a hash-pinned, isolated copy of the common observer. The new profile
changes only the training runner, arm names and schema identities. All source,
prediction, reference-access, deadline and no-selection gates remain shared.
Importing this module performs no model work or training.
"""
import hashlib
import importlib.util
from pathlib import Path

BASE_FILE = 'scripts/ops/autoencoder/evaluate_training_mixture_styles.py'
BASE_SHA256 = '37c22dbdec537a6b8690feb42c0dfdf083c4934aab159108cdfda03e602e9b84'
TRAINER = 'scripts/ops/autoencoder/benchmark_paraphrase_modality_training.py'
ARMS = ('paraphrase-modality-zero', 'paraphrase-modality-ce')
PLAN_SCHEMA = 'paraphrase-modality-exposed-v3-plan/v1'
RESULT_SCHEMA = 'paraphrase-modality-exposed-v3-results/v1'


def load_observer(*, base_path=None):
    """Return a private configured observer; never mutate a shared module."""
    path = Path(base_path) if base_path is not None else Path(__file__).resolve().parents[3]/BASE_FILE
    if hashlib.sha256(path.read_bytes()).hexdigest() != BASE_SHA256:
        raise ValueError('shared exposed-style observer source pin differs')
    spec = importlib.util.spec_from_file_location('_paraphrase_modality_style_core', path)
    observer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observer)
    observer.TRAINER = TRAINER
    observer.ARMS = ARMS
    observer.RESULT_SCHEMA = RESULT_SCHEMA
    observer.FIXED = dict(observer.FIXED, schema=PLAN_SCHEMA, arms=list(ARMS))
    return observer


def main():
    load_observer().main()


if __name__ == '__main__':
    main()
