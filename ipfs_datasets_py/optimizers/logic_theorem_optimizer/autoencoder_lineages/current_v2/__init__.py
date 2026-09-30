"""Current numerical runtime with an explicit 384-dimensional profile.

Evaluation and projection training default to raw learned reconstruction with
sample memory disabled. This does not establish semantic embedding provenance,
formalization, or Lake admission. Original modal_autoencoder APIs are unchanged.
"""

from .._contract import LineageModelContract, load_local_checkpoint, validate_vector
from ...modal_autoencoder import AdaptiveModalAutoencoder as _Implementation
from ...modal_autoencoder import ModalAutoencoderTrainingState as TrainingState
from ...legal_samples import LegalSample
from ...legal_samples import build_us_code_sample as _build_sample

DIMENSION = 384
LINEAGE_ID = "current_legal_v2"


class Autoencoder(LineageModelContract, _Implementation):
    DIMENSION = DIMENSION
    LINEAGE_ID = LINEAGE_ID
    _implementation_class = _Implementation
    _training_state_class = TrainingState
    _raw_reconstruction_default = True
    _implementation_scope = "current numerical implementation; shared current canonical compiler, bridges, and proof infrastructure"


def load_checkpoint(path, *, expected_sha256, **model_options):
    """Read an explicit local JSON checkpoint without changing its bytes."""
    return load_local_checkpoint(Autoencoder, path, expected_sha256=expected_sha256, **model_options)


def build_sample(*, embedding_vector, embedding_model, **sample_options):
    """Build a sample with explicit vector provenance; never generate mock vectors."""
    validate_vector(embedding_vector, DIMENSION, "embedding_vector")
    return _build_sample(embedding_vector=embedding_vector, embedding_model=embedding_model, **sample_options)


__all__ = ["Autoencoder", "TrainingState", "LegalSample", "DIMENSION", "LINEAGE_ID", "load_checkpoint", "build_sample"]
