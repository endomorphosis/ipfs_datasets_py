"""Eight-dimensional legacy numerical runtime from ddf6b794.

The numerical/helper closure is frozen. Canonical legal compilers, bridges and
proof infrastructure are shared with the current pinned workspace; this is not
a replay of the entire historical formalization pipeline.
"""

from pathlib import Path
from .._contract import LineageModelContract, load_local_checkpoint, validate_vector, verify_snapshot

_snapshot_manifest = verify_snapshot(Path(__file__).parent / "_snapshot")

from ._snapshot.modal_autoencoder import AdaptiveModalAutoencoder as _Implementation
from ._snapshot.modal_autoencoder import ModalAutoencoderTrainingState as TrainingState
from ._snapshot.legal_samples import LegalSample
from ._snapshot.legal_samples import build_us_code_sample as _build_sample

DIMENSION = 8
LINEAGE_ID = "legacy_hub_v1"
SOURCE_REVISION = "ddf6b79467b68159650df81befc288c8553df664"


class Autoencoder(LineageModelContract, _Implementation):
    DIMENSION = DIMENSION
    LINEAGE_ID = LINEAGE_ID
    _implementation_class = _Implementation
    _training_state_class = TrainingState
    _raw_reconstruction_default = False
    _implementation_scope = "historical numerical/helper snapshot; shared current canonical compiler, bridges, and proof infrastructure"


def load_checkpoint(path, *, expected_sha256, **model_options):
    """Read an explicit local JSON checkpoint without changing its bytes."""
    return load_local_checkpoint(Autoencoder, path, expected_sha256=expected_sha256, **model_options)


def build_sample(*, embedding_vector, embedding_model, **sample_options):
    """Build a sample with explicit vector provenance; never generate mock vectors."""
    validate_vector(embedding_vector, DIMENSION, "embedding_vector")
    return _build_sample(embedding_vector=embedding_vector, embedding_model=embedding_model, **sample_options)


__all__ = ["Autoencoder", "TrainingState", "LegalSample", "DIMENSION", "LINEAGE_ID", "SOURCE_REVISION", "load_checkpoint", "build_sample"]
