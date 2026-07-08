"""SMT-LIB2 serialization for crypto exchange security claims."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from ..ir.cid import calculate_artifact_cid, calculate_model_cid
from ..ir.schema import SecurityModelIR, as_security_model_ir
from .to_z3 import Z3Compilation, z3_import

if TYPE_CHECKING:
    from ..claims.base import SecurityClaim


SMTLIB_SCHEMA_VERSION = 'crypto-exchange-smtlib/v1'
SMTLIB_QUERY_KIND = 'violation_satisfiability'
SMTLIB_LOGIC = 'QF_LIA'


@dataclass(frozen=True, slots=True)
class SMTLIBCompilation:
    """Deterministic SMT-LIB2 artifact for a single claim query."""

    claim_id: str
    claim_version: str
    model_id: str
    model_cid: str
    model_schema_version: str
    smtlib: str
    metadata: dict[str, Any]
    modeled: bool
    not_modeled_reason: str | None = None

    @property
    def artifact_cid(self) -> str:
        """Return a deterministic content address for the emitted SMT-LIB text."""

        return calculate_artifact_cid(
            {
                'schema_version': SMTLIB_SCHEMA_VERSION,
                'claim_id': self.claim_id,
                'model_cid': self.model_cid,
                'smtlib': self.smtlib,
            }
        )

    def to_manifest_entry(self, *, path: str | None = None) -> dict[str, Any]:
        """Return a JSON-friendly manifest entry for this artifact."""

        entry = {
            'schema_version': SMTLIB_SCHEMA_VERSION,
            'claim_id': self.claim_id,
            'claim_version': self.claim_version,
            'model_id': self.model_id,
            'model_cid': self.model_cid,
            'model_schema_version': self.model_schema_version,
            'modeled': self.modeled,
            'not_modeled_reason': self.not_modeled_reason,
            'query_kind': self.metadata['query_kind'],
            'assertion_count': self.metadata['assertion_count'],
            'artifact_cid': self.artifact_cid,
        }
        if path is not None:
            entry['path'] = path
        return entry


def compile_claim_to_smtlib(
    claim: 'SecurityClaim',
    model: SecurityModelIR | Mapping[str, Any],
    *,
    include_get_model: bool = False,
) -> SMTLIBCompilation:
    """Compile one claim into an SMT-LIB2 violation satisfiability query.

    Modeled claims are serialized as ``assertions + violation_formula`` followed
    by ``check-sat``. A secure positive model should therefore return ``unsat``;
    a counterexample fixture should return ``sat``. Claims that are not modeled
    produce a metadata-only SMT-LIB file with no ``check-sat`` command so callers
    cannot accidentally interpret the artifact as either proof or disproof.
    """

    normalized_model = as_security_model_ir(model)
    compilation = claim.compile_to_z3(normalized_model)
    return serialize_z3_compilation_to_smtlib(
        compilation,
        normalized_model,
        include_get_model=include_get_model,
    )


def compile_claims_to_smtlib(
    model: SecurityModelIR | Mapping[str, Any],
    claims: Iterable['SecurityClaim'],
    *,
    include_get_model: bool = False,
) -> list[SMTLIBCompilation]:
    """Compile claims into deterministic SMT-LIB2 artifacts in input order."""

    normalized_model = as_security_model_ir(model)
    return [
        compile_claim_to_smtlib(
            claim,
            normalized_model,
            include_get_model=include_get_model,
        )
        for claim in claims
    ]


def emit_smtlib_artifacts(
    model: SecurityModelIR | Mapping[str, Any],
    output_dir: str | Path,
    claims: Iterable['SecurityClaim'],
    *,
    include_get_model: bool = False,
    include_not_modeled: bool = True,
) -> dict[str, Any]:
    """Write one ``.smt2`` file per claim and a deterministic manifest."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = compile_claims_to_smtlib(
        model,
        claims,
        include_get_model=include_get_model,
    )
    manifest_entries: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not artifact.modeled and not include_not_modeled:
            continue
        filename = f'{_safe_filename(artifact.claim_id)}.smt2'
        output_path = directory / filename
        output_path.write_text(artifact.smtlib, encoding='utf-8')
        manifest_entries.append(
            artifact.to_manifest_entry(path=filename)
        )

    manifest = {
        'schema_version': SMTLIB_SCHEMA_VERSION,
        'model_id': as_security_model_ir(model).model_id,
        'model_cid': calculate_model_cid(as_security_model_ir(model)),
        'artifact_count': len(manifest_entries),
        'artifacts': manifest_entries,
    }
    (directory / 'manifest.json').write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    return manifest


def serialize_z3_compilation_to_smtlib(
    compilation: Z3Compilation,
    model: SecurityModelIR | Mapping[str, Any],
    *,
    include_get_model: bool = False,
) -> SMTLIBCompilation:
    """Serialize an existing :class:`Z3Compilation` into SMT-LIB2."""

    normalized_model = as_security_model_ir(model)
    metadata = _metadata_for_compilation(compilation, normalized_model)
    if not compilation.modeled:
        smtlib = _not_modeled_smtlib(metadata)
    else:
        smtlib = _modeled_smtlib(
            compilation,
            metadata,
            include_get_model=include_get_model,
        )
    return SMTLIBCompilation(
        claim_id=metadata['claim_id'],
        claim_version=metadata['claim_version'],
        model_id=metadata['model_id'],
        model_cid=metadata['model_cid'],
        model_schema_version=metadata['model_schema_version'],
        smtlib=smtlib,
        metadata=metadata,
        modeled=bool(metadata['modeled']),
        not_modeled_reason=metadata['not_modeled_reason'],
    )


def _metadata_for_compilation(compilation: Z3Compilation, model: SecurityModelIR) -> dict[str, Any]:
    claim = compilation.claim
    compiler_artifact = dict(compilation.compiler_artifact)
    return {
        'schema_version': SMTLIB_SCHEMA_VERSION,
        'query_kind': SMTLIB_QUERY_KIND,
        'logic': SMTLIB_LOGIC,
        'model_id': model.model_id,
        'model_cid': calculate_model_cid(model),
        'model_schema_version': model.schema_version,
        'claim_id': claim.claim_id,
        'claim_version': claim.claim_version,
        'claim_description': claim.description,
        'severity': claim.severity,
        'required_assumptions': list(claim.required_assumptions),
        'modeled': compilation.modeled,
        'not_modeled_reason': compilation.not_modeled_reason,
        'assertion_count': len(compilation.assertions),
        'compiler_artifact_cid': calculate_artifact_cid(compiler_artifact),
        'compiler_artifact': compiler_artifact,
        'evidence_refs': list(compilation.evidence_refs),
        'soundness_notes': list(compilation.soundness_notes),
        'violation_scope_explanation': compilation.violation_scope_explanation,
    }


def _modeled_smtlib(
    compilation: Z3Compilation,
    metadata: Mapping[str, Any],
    *,
    include_get_model: bool,
) -> str:
    if compilation.violation_formula is None:
        raise ValueError('modeled SMT-LIB compilation requires a violation_formula')
    z3 = z3_import()
    solver = z3.Solver()
    solver.add(*compilation.assertions)
    solver.add(compilation.violation_formula)
    body = _strip_z3_prelude(solver.to_smt2())
    if include_get_model and '(get-model)' not in body:
        body = f'{body.rstrip()}\n(get-model)\n'
    return _header(metadata) + body.rstrip() + '\n'


def _not_modeled_smtlib(metadata: Mapping[str, Any]) -> str:
    reason = str(metadata.get('not_modeled_reason') or 'claim is not modeled')
    lines = [
        _header(metadata).rstrip(),
        '(set-info :status unknown)',
        f'(echo "{_smtlib_string(f"NOT_MODELED: {reason}")}")',
    ]
    return '\n'.join(lines) + '\n'


def _header(metadata: Mapping[str, Any]) -> str:
    metadata_json = json.dumps(metadata, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return '\n'.join(
        [
            '; crypto-exchange SMT-LIB2 artifact',
            f'; cxtp.schema_version: {SMTLIB_SCHEMA_VERSION}',
            f'; cxtp.model_id: {metadata["model_id"]}',
            f'; cxtp.model_cid: {metadata["model_cid"]}',
            f'; cxtp.claim_id: {metadata["claim_id"]}',
            f'; cxtp.claim_version: {metadata["claim_version"]}',
            f'; cxtp.modeled: {str(metadata["modeled"]).lower()}',
            f'; cxtp.metadata: {metadata_json}',
            '(set-info :smt-lib-version 2.6)',
            '(set-info :source "ipfs_datasets_py crypto_exchange SMT-LIB2 compiler")',
            f'(set-logic {SMTLIB_LOGIC})',
        ]
    ) + '\n'


def _strip_z3_prelude(smtlib: str) -> str:
    lines = smtlib.replace('\r\n', '\n').replace('\r', '\n').splitlines()
    stripped: list[str] = []
    for line in lines:
        if line == '; benchmark generated from python API':
            continue
        if line == '(set-info :status unknown)':
            continue
        if line == f'(set-logic {SMTLIB_LOGIC})':
            continue
        stripped.append(line)
    return '\n'.join(stripped).rstrip() + '\n'


def _smtlib_string(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '""')


def _safe_filename(claim_id: str) -> str:
    safe = ''.join(character if character.isalnum() or character in {'-', '_'} else '_' for character in claim_id)
    return safe or 'claim'


__all__ = [
    'SMTLIBCompilation',
    'SMTLIB_LOGIC',
    'SMTLIB_QUERY_KIND',
    'SMTLIB_SCHEMA_VERSION',
    'compile_claim_to_smtlib',
    'compile_claims_to_smtlib',
    'emit_smtlib_artifacts',
    'serialize_z3_compilation_to_smtlib',
]
