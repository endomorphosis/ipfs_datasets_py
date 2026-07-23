"""Canonical Abby voice dataset contracts.

The package is intentionally dependency-light.  Arrow and Hugging Face
integrations are imported lazily by :mod:`ipfs_datasets_py.voice.schema`.
"""

from .schema import (
    ABBY_VOICE_AUDIO_V2,
    ABBY_VOICE_PROVENANCE_V2,
    ABBY_VOICE_RESPONSE_V2,
    ABBY_VOICE_TEMPLATE_V2,
    AbbyVoiceAudio,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    AbbyVoiceSchemaError,
    AbbyVoiceTemplate,
    get_arrow_schema,
    get_huggingface_features,
    get_pyarrow_schema,
    migrate_v1_record,
    parse_abby_voice_record,
    schema_columns,
    validate_abby_voice_bundle,
    validate_abby_voice_record,
    validate_bundle,
    validate_publishable,
    validate_rows,
)

__all__ = [
    "ABBY_VOICE_AUDIO_V2",
    "ABBY_VOICE_PROVENANCE_V2",
    "ABBY_VOICE_RESPONSE_V2",
    "ABBY_VOICE_TEMPLATE_V2",
    "AbbyVoiceAudio",
    "AbbyVoiceProvenance",
    "AbbyVoiceResponse",
    "AbbyVoiceSchemaError",
    "AbbyVoiceTemplate",
    "get_arrow_schema",
    "get_huggingface_features",
    "get_pyarrow_schema",
    "migrate_v1_record",
    "parse_abby_voice_record",
    "schema_columns",
    "validate_abby_voice_bundle",
    "validate_abby_voice_record",
    "validate_bundle",
    "validate_publishable",
    "validate_rows",
]
