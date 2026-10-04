"""Integrity-checked runtime for the frozen experimental boundary decoder.

Adds owned-checkpoint and producer/weight checks around the unchanged numerical
model. This wrapper provides receipt integrity, not legal-scope qualification.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

from . import legal_clause_boundary_decoder as boundary

SCHEMA = 'guarded-legal-clause-boundary-runtime/v1'


def _pins():
    return {str(Path(path).resolve()): hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in (__file__, boundary.__file__)}


class GuardedClauseBoundaryDecoder:
    def __init__(self, checkpoint):
        self._checkpoint = deepcopy(checkpoint)
        self._checkpoint_digest = boundary.digest(self._checkpoint)
        self._decoder = boundary.ClauseBoundaryDecoder(self._checkpoint)
        self._model_state_digest = boundary.digest(self._checkpoint['model_state'])
        self._producer_pins = _pins()
        self._verify()

    @property
    def checkpoint(self):
        return deepcopy(self._checkpoint)

    @property
    def checkpoint_sha256(self):
        return self._checkpoint_digest

    def _verify(self):
        boundary.require(_pins() == self._producer_pins, 'guarded boundary runtime producer changed')
        boundary.require(boundary.digest(self._checkpoint) == self._checkpoint_digest
            and boundary.digest(self._decoder.checkpoint) == self._checkpoint_digest
            and self._decoder.checkpoint_sha256 == self._checkpoint_digest, 'owned boundary checkpoint changed')
        state = {key: tensor.detach().cpu().tolist() for key, tensor in self._decoder.network.state_dict().items()}
        boundary.require(boundary.digest(state) == self._model_state_digest, 'boundary inference model state changed')
        return self._model_state_digest

    def decode(self, sources, *, source_profile=boundary.PROFILE):
        owned_sources = deepcopy(sources)
        before = self._verify()
        result = self._decoder.decode(owned_sources, source_profile=source_profile)
        after = self._verify()
        boundary.require(result['checkpoint_sha256'] == self._checkpoint_digest, 'reported boundary checkpoint changed')
        return {**result, 'runtime_integrity': {'schema': SCHEMA, 'checkpoint_sha256': self._checkpoint_digest,
            'source_inputs_sha256': boundary.digest(owned_sources), 'model_state_sha256_before': before,
            'model_state_sha256_after': after, 'model_state_unchanged': True, 'producer_pins': deepcopy(self._producer_pins),
            'numerical_model_unchanged': True, 'source_semantics_verified': False}}
