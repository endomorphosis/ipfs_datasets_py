"""Private witness rendering helpers for ProveKit.

The current knowledge-of-axioms circuit consumes scalar field commitments, not
raw legal text. This module therefore renders ProveKit ``Prover.toml`` files
with public field inputs plus matching private scalar witnesses, while keeping
private axiom text out of returned metadata, logs, exceptions, and cache keys.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence

from .public_inputs import (
    ProveKitPublicInputRecord,
    build_provekit_public_input_record,
)


KNOWLEDGE_OF_AXIOMS_FIELD_ORDER = (
    "theorem_hash_field",
    "axioms_commitment_field",
    "circuit_ref_field",
    "circuit_version",
    "ruleset_id_field",
    "compiler_guidance_ref_field",
    "compiler_guidance_version",
    "hash_backend_field",
)
PROVEKIT_PROVER_TOML_FILENAME = "Prover.toml"
PRIVATE_WITNESS_REDACTION = "<redacted:provekit-private-witness>"


@dataclass(frozen=True)
class ProveKitWitnessWorkspace:
    """Private temporary workspace containing a rendered Prover.toml."""

    directory: str
    prover_toml_path: str
    public_input_record: ProveKitPublicInputRecord
    private_witness_digest: str

    def to_backend_artifacts(
        self,
        *,
        prover_key_path: str | Path,
        verifier_key_path: Optional[str | Path] = None,
        proof_path: str | Path,
    ) -> dict[str, Any]:
        """Return backend artifact metadata without private witness contents."""

        artifacts: dict[str, Any] = {
            "program_dir": self.directory,
            "input_path": self.prover_toml_path,
            "prover_key_path": str(Path(prover_key_path)),
            "proof_path": str(Path(proof_path)),
            "private_witness_digest": self.private_witness_digest,
        }
        if verifier_key_path is not None:
            artifacts["verifier_key_path"] = str(Path(verifier_key_path))
        return {"provekit_artifacts": artifacts}


def build_knowledge_of_axioms_witness_values(
    record: ProveKitPublicInputRecord,
) -> dict[str, int]:
    """Return public and private scalar inputs for the current Noir circuit."""

    public_fields = record.to_noir_field_inputs()
    values: dict[str, int] = {}
    for key in KNOWLEDGE_OF_AXIOMS_FIELD_ORDER:
        values[key] = int(public_fields[key])
    for key in KNOWLEDGE_OF_AXIOMS_FIELD_ORDER:
        values[f"witness_{key}"] = int(public_fields[key])
    return values


def render_knowledge_of_axioms_prover_toml(
    record: ProveKitPublicInputRecord,
) -> str:
    """Render deterministic Prover.toml content for the first ProveKit circuit."""

    values = build_knowledge_of_axioms_witness_values(record)
    lines = []
    for key in KNOWLEDGE_OF_AXIOMS_FIELD_ORDER:
        lines.append(f'{key} = "{values[key]}"')
    for key in KNOWLEDGE_OF_AXIOMS_FIELD_ORDER:
        witness_key = f"witness_{key}"
        lines.append(f'{witness_key} = "{values[witness_key]}"')
    return "\n".join(lines) + "\n"


@contextmanager
def provekit_witness_workspace(
    *,
    theorem: str,
    private_axioms: Sequence[str],
    metadata: Optional[Mapping[str, Any]] = None,
    derivation_witness: Optional[Mapping[str, Any] | Sequence[Any]] = None,
    base_dir: Optional[str | Path] = None,
) -> Iterator[ProveKitWitnessWorkspace]:
    """Create a private temporary ProveKit witness workspace.

    The workspace and its ``Prover.toml`` are removed when the context exits.
    The returned object contains paths and public commitments only.
    """

    private_values = _collect_private_strings(private_axioms, derivation_witness)
    temp_dir: Optional[tempfile.TemporaryDirectory[str]] = None
    setup_complete = False
    try:
        temp_dir = tempfile.TemporaryDirectory(
            prefix="ipfs-datasets-provekit-",
            dir=str(base_dir) if base_dir is not None else None,
        )
        directory = Path(temp_dir.name)
        directory.chmod(0o700)

        record = build_provekit_public_input_record(
            theorem=theorem,
            private_axioms=private_axioms,
            metadata=metadata,
        )
        prover_toml = render_knowledge_of_axioms_prover_toml(record)
        prover_toml_path = directory / PROVEKIT_PROVER_TOML_FILENAME
        _write_private_file(prover_toml_path, prover_toml)

        setup_complete = True
        yield ProveKitWitnessWorkspace(
            directory=str(directory),
            prover_toml_path=str(prover_toml_path),
            public_input_record=record,
            private_witness_digest=private_witness_digest(
                private_axioms=private_axioms,
                derivation_witness=derivation_witness,
            ),
        )
    except Exception as exc:
        if setup_complete:
            raise
        message = redact_private_witness_text(str(exc), private_values)
        raise RuntimeError(f"ProveKit witness workspace failed: {message}") from None
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def private_witness_digest(
    *,
    private_axioms: Sequence[str],
    derivation_witness: Optional[Mapping[str, Any] | Sequence[Any]] = None,
) -> str:
    """Return a stable digest of private witness material for diagnostics."""

    payload = {
        "private_axioms": list(private_axioms),
        "derivation_witness": derivation_witness,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def redact_private_witness_text(text: str, private_values: Iterable[str]) -> str:
    """Redact private values from exception/log text."""

    redacted = str(text)
    for value in sorted({str(v) for v in private_values if str(v)}, key=len, reverse=True):
        redacted = redacted.replace(value, PRIVATE_WITNESS_REDACTION)
    return redacted


def _write_private_file(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)


def _collect_private_strings(
    private_axioms: Sequence[str],
    derivation_witness: Optional[Mapping[str, Any] | Sequence[Any]],
) -> tuple[str, ...]:
    values = [str(value) for value in private_axioms]
    if derivation_witness is not None:
        values.extend(_strings_from_jsonish(derivation_witness))
    return tuple(values)


def _strings_from_jsonish(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        out: list[str] = []
        for key, nested in value.items():
            out.append(str(key))
            out.extend(_strings_from_jsonish(nested))
        return out
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        out: list[str] = []
        for nested in value:
            out.extend(_strings_from_jsonish(nested))
        return out
    return []


__all__ = [
    "KNOWLEDGE_OF_AXIOMS_FIELD_ORDER",
    "PRIVATE_WITNESS_REDACTION",
    "PROVEKIT_PROVER_TOML_FILENAME",
    "ProveKitWitnessWorkspace",
    "build_knowledge_of_axioms_witness_values",
    "private_witness_digest",
    "provekit_witness_workspace",
    "redact_private_witness_text",
    "render_knowledge_of_axioms_prover_toml",
]
