"""Read-only Leanstral source-profile discovery with a closed production gate.

The installed llama.cpp GET protocol reports input hidden width, but does not
attest embeddings mode, native output width, pooling, device or microbatch
geometry. No trained 4096D head is supplied here. Production remains refused
until a native owner integrates the operation-bound verification requirements.
This module never reads model tensors, starts a service, or submits inference.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Protocol
import urllib.error
import urllib.parse
import urllib.request

DIMENSION = 4096
PROFILE_ID = "leanstral-119b-nvfp4-source4096:last:l2:untruncated:v1"
PRODUCER_ID = "leanstral-source4096-profile-discovery@1"
MODEL_CID = "bafkreicgnd6su3jhmtpckbejqurdb2lchdvvydluswdg5m5zy3cpvroh3i"
MODEL_SHA256 = "4668fd2a6d2764de250489852230e96238eb5c0d7495866eb3b9c6c4fac5c7da"
MODEL_FILENAME = "Leanstral-1.5-119B-A6B-NVFP4.gguf"
MAX_RESPONSE_BYTES = 128 * 1024
MAX_SOURCE_BYTES = 64 * 1024
MAX_TOKENS = 512
GET_PATHS = ("/health", "/props", "/v1/models")


class LeanstralEmbeddingUnavailable(ValueError):
    """Current discovery cannot authorize a source-embedding operation."""


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _finite(value):
    if type(value) not in {int, float}:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _pairs(rows):
    result = {}
    for key, value in rows:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def _decode(raw):
    _require(type(raw) is bytes and len(raw) <= MAX_RESPONSE_BYTES,
             "bounded native JSON bytes required")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                      parse_constant=_constant)


@dataclass(frozen=True, slots=True)
class Leanstral4096Profile:
    """A requested source profile; no metadata, execution or freshness claim."""

    profile_id: str = PROFILE_ID
    producer_id: str = PRODUCER_ID
    dimension: int = DIMENSION
    model_alias: str = "leanstral_local"
    declared_model_cid: str = MODEL_CID
    declared_model_sha256: str = MODEL_SHA256
    model_filename: str = MODEL_FILENAME
    pooling: str = "last"
    normalization: str = "l2"
    max_tokens_including_special_tokens: int = MAX_TOKENS
    tokenizer_add_special: bool = True
    tokenizer_parse_special: bool = False
    client_concurrency: int = 1

    def __post_init__(self):
        canonical = {
            "profile_id": PROFILE_ID, "producer_id": PRODUCER_ID,
            "dimension": DIMENSION, "model_alias": "leanstral_local",
            "declared_model_cid": MODEL_CID, "declared_model_sha256": MODEL_SHA256,
            "model_filename": MODEL_FILENAME, "pooling": "last", "normalization": "l2",
            "max_tokens_including_special_tokens": MAX_TOKENS,
            "tokenizer_add_special": True, "tokenizer_parse_special": False,
            "client_concurrency": 1,
        }
        observed = asdict(self)
        _require(all(type(observed[key]) is type(value) and observed[key] == value
                     for key, value in canonical.items()), "exact separate 4096D source profile required")

    def to_dict(self):
        return {"schema": "leanstral-source4096-requested-profile/v1", **asdict(self),
                "declared_model_content_verified": False, "trained_decoder_head": False,
                "source_semantics_verified": False, "proof_authority": False}


@dataclass(frozen=True, slots=True)
class NativeOwnerVerificationRequirements:
    """Required trusted integration contract, never an accepted witness.

    JSON with these fields cannot satisfy the production gate. The owner must
    acquire one admitted operation and perform native entry/closing checks on
    the same sealed owner, PID and thread, without reusable freshness tokens.
    """

    schema: str = "leanstral-source4096-owner-verification-requirements/v1"
    implementation_status: str = "trusted_native_owner_integration_required"
    fields: tuple[str, ...] = (
        "operation_seal", "operation_owner_identity", "caller_pid", "caller_thread_id",
        "service_pid", "service_process_birth", "service_executable_identity",
        "declared_model_cid", "declared_model_sha256", "actual_native_model_metadata",
        "native_model_content_verification_scope", "backend_build_identity",
        "backend_source_identity", "launch_configuration_sha256", "embedding_mode",
        "native_input_dimension", "native_output_dimension", "pooling", "normalization",
        "tokenizer_identity", "context_allocation", "physical_microbatch_tokens",
        "actual_execution_device", "admitted_single_client_operation", "cancellation_signal",
        "source_sha256", "token_input_sha256", "untruncated_token_count",
        "native_tokens_evaluated", "entry_callback", "closing_callback",
        "process_tree_and_device_cleanup",
    )

    def to_dict(self):
        return {"schema": self.schema, "implementation_status": self.implementation_status,
                "required_fields": list(self.fields), "caller_json_is_witness": False,
                "caller_booleans_are_authority": False, "persistent_freshness_token": False,
                "one_use_same_owner_pid_thread": True, "entry_and_close_required": True,
                "input_hidden_width_is_output_attestation": False,
                "declared_model_digest_is_actual_content_verification": False,
                "backend_slots_are_client_concurrency": False, "proof_authority": False}


class ReadOnlyTransport(Protocol):
    def get(self, path: str) -> bytes:
        """Return bounded native JSON; this discovery protocol has no POST."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ValueError("native discovery redirects are not permitted")


class NativeReadOnlyTransport:
    """Bounded GET-only transport to the existing local service."""

    def __init__(self, base_url="http://172.17.0.1:8080", *, timeout_seconds=3.0):
        parsed = urllib.parse.urlsplit(base_url)
        _require(parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "172.17.0.1"}
                 and parsed.port == 8080 and parsed.path in {"", "/"}
                 and not parsed.username and not parsed.password and not parsed.query
                 and not parsed.fragment, "exact local service origin required")
        _require(type(timeout_seconds) in {int, float} and math.isfinite(timeout_seconds)
                 and 0 < timeout_seconds <= 5, "bounded GET timeout required")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def get(self, path):
        _require(path in GET_PATHS, "discovery permits only health, props and models GETs")
        request = urllib.request.Request(self.base_url + path, method="GET",
                                         headers={"Accept": "application/json"})
        with self._opener.open(request, timeout=self.timeout_seconds) as response:
            _require(response.status == 200, "native GET did not succeed")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        _require(len(raw) <= MAX_RESPONSE_BYTES, "native GET response exceeds byte bound")
        _decode(raw)
        return raw


def inspect_embedding_capability(transport: ReadOnlyTransport, *, profile=None):
    """Observe current native metadata; always refuse current production.

    A healthy endpoint, model ID or 4096-wide input alone never establishes an
    embedding capability. Controlled transports produce protocol observations,
    not native execution or qualification evidence.
    """
    profile = Leanstral4096Profile() if profile is None else profile
    _require(type(profile) is Leanstral4096Profile, "typed requested profile required")
    producer_before = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    raw_responses = {path: transport.get(path) for path in GET_PATHS}
    responses = {path: _decode(raw) for path, raw in raw_responses.items()}
    health, props, models = (responses[path] for path in GET_PATHS)
    reasons = ["trusted_native_owner_integration_required"]
    _require(type(health) is dict and type(props) is dict and type(models) is dict,
             "native discovery objects required")
    if health.get("status") != "ok":
        reasons.append("native_service_not_healthy")
    rows = models.get("data")
    _require(type(rows) is list and all(type(row) is dict for row in rows), "native model list required")
    selected = [row for row in rows if row.get("id") == profile.model_alias]
    metadata = {}
    if len(selected) != 1 or selected[0].get("owned_by") != "llamacpp":
        reasons.append("native_model_identity_absent_or_ambiguous")
    else:
        metadata = selected[0].get("meta")
        _require(type(metadata) is dict, "native model metadata required")
        if type(metadata.get("n_embd")) is not int or metadata["n_embd"] != DIMENSION:
            reasons.append("native_input_hidden_width_differs")
    path = props.get("model_path")
    expected_tail = "/models/cid-v1/" + MODEL_CID + "/" + MODEL_FILENAME
    if type(path) is not str or not path.endswith(expected_tail) or props.get("model_alias") != profile.model_alias:
        reasons.append("native_model_path_or_alias_differs")
    for field in ("embedding", "pooling_type", "embd_normalize", "n_embd_out", "device", "n_ubatch"):
        if field not in props:
            reasons.append("native_" + field + "_unattested")
    if "embedding" in props and props["embedding"] is not True:
        reasons.append("native_embeddings_mode_disabled_or_invalid")
    settings = props.get("default_generation_settings", {})
    _require(type(settings) is dict, "native generation settings metadata object required")
    producer_after = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    _require(producer_before == producer_after, "source-profile producer changed during GET discovery")
    return {"schema": "leanstral-source4096-capability-observation/v1", "status": "unavailable",
            "qualified": False, "production_allowed": False, "reason_codes": reasons,
            "requested_profile": profile.to_dict(), "owner_requirements": NativeOwnerVerificationRequirements().to_dict(),
            "observed_native_input_dimension": metadata.get("n_embd"),
            "observed_native_output_dimension": None, "observed_backend_total_slots": props.get("total_slots"),
            "client_concurrency": 1, "observed_backend_build_info": props.get("build_info"),
            "observed_model_path": path,
            "observed_context_allocation": settings.get("n_ctx"),
            "transport_scope": "bounded_native_http_gets" if type(transport) is NativeReadOnlyTransport else "controlled_protocol_only",
            "response_pins": {path: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                              for path, raw in raw_responses.items()},
            "producer_sha256_before": producer_before, "producer_sha256_after": producer_after,
            "model_weights_read": False, "model_content_hash_verified": False,
            "embedding_requests": 0, "generation_requests": 0, "tokenizer_requests": 0,
            "training_executed": False, "trained_decoder_head": False,
            "source_semantics_verified": False, "execution_attestation": False,
            "proof_authority": False, "completion_authority": False}


def validate_token_response(raw, *, vocabulary_size, max_tokens=MAX_TOKENS):
    """Validate diagnostic /tokenize bytes; never authorize a native operation."""
    _require(type(vocabulary_size) is int and 1 <= vocabulary_size <= 2**24,
             "exact bounded native vocabulary size required")
    _require(type(max_tokens) is int and 1 <= max_tokens <= MAX_TOKENS, "bounded token profile required")
    value = _decode(raw)
    _require(type(value) is dict and set(value) == {"tokens"}, "closed native token response required")
    tokens = value["tokens"]
    _require(type(tokens) is list and 1 <= len(tokens) <= max_tokens
             and all(type(token) is int and 0 <= token < vocabulary_size for token in tokens),
             "untruncated bounded native token IDs required")
    return {"schema": "leanstral-source4096-token-protocol-diagnostic/v1", "tokens": tokens,
            "token_count": len(tokens), "token_input_sha256": hashlib.sha256(_wire(tokens)).hexdigest(),
            "native_execution_verified": False, "production_allowed": False, "proof_authority": False}


def validate_vector_response(raw, *, expected_token_count):
    """Check native OpenAI-compatible shape only; width cannot prove provenance."""
    _require(type(expected_token_count) is int and 1 <= expected_token_count <= MAX_TOKENS,
             "exact bounded token count required")
    value = _decode(raw)
    _require(type(value) is dict and set(value) == {"object", "data", "model", "usage"}
             and value["object"] == "list" and value["model"] == "leanstral_local",
             "closed native embedding protocol required")
    rows = value["data"]
    _require(type(rows) is list and len(rows) == 1 and type(rows[0]) is dict
             and set(rows[0]) == {"object", "embedding", "index"}
             and rows[0]["object"] == "embedding" and type(rows[0]["index"]) is int
             and rows[0]["index"] == 0, "exact single source embedding row required")
    usage = value["usage"]
    _require(type(usage) is dict and set(usage) == {"prompt_tokens", "total_tokens"}
             and all(type(usage[key]) is int and usage[key] == expected_token_count for key in usage),
             "native embedding token accounting differs")
    vector = rows[0]["embedding"]
    _require(type(vector) is list and len(vector) == DIMENSION
             and all(_finite(number) for number in vector),
             "finite actual 4096-wide protocol vector required")
    norm = math.sqrt(sum(number * number for number in vector))
    _require(math.isfinite(norm) and abs(norm - 1.0) <= 1e-5, "nonzero L2-normalized vector required")
    return {"schema": "leanstral-source4096-vector-protocol-diagnostic/v1", "dimension": DIMENSION,
            "vector_sha256": hashlib.sha256(_wire(vector)).hexdigest(),
            "native_output_provenance_verified": False, "device_execution_verified": False,
            "production_allowed": False, "proof_authority": False}


def embed_rows(rows, *, profile=None, owner_verifier=None):
    """Refuse until a reviewed native owner integrates the required witnesses.

    Caller JSON, booleans, vector shape and discovery observations cannot stand
    in for process/model/device identity, admission, or entry/closing fences.
    No tokenizer, embedding or generation request is sent by this function.
    """
    raise LeanstralEmbeddingUnavailable("trusted_native_owner_integration_required")
