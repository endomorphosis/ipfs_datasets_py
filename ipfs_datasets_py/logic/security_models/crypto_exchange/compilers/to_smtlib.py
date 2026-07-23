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
XAMAN_SMTLIB_QUERY_KIND = 'xaman_blocking_acceptance_satisfiability'
SMTLIB_LOGIC = 'QF_LIA'
XAMAN_CRITICAL_SEVERITIES = frozenset({'blocking', 'high'})


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
        'model_cid': _model_cid_for_smtlib(as_security_model_ir(model)),
        'artifact_count': len(manifest_entries),
        'artifacts': manifest_entries,
    }
    (directory / 'manifest.json').write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    return manifest


def compile_ir_claim_to_smtlib(
    claim_record: Mapping[str, Any],
    model: SecurityModelIR | Mapping[str, Any],
    *,
    include_get_model: bool = False,
) -> SMTLIBCompilation:
    """Compile a declarative IR claim into a solver-neutral SMT-LIB2 query.

    Xaman claims are source-artifact claims rather than one of the built-in
    exchange claim classes. The query asks whether the claim has any blocking
    acceptance condition. ``sat`` therefore means the proof consumer must block
    acceptance; ``unsat`` means the claim has no remaining assumption blocker and
    can be interpreted by the differential report as a proof candidate.
    """

    normalized_model = as_security_model_ir(model)
    metadata = _metadata_for_ir_claim(claim_record, normalized_model)
    smtlib = _ir_claim_smtlib(metadata, include_get_model=include_get_model)
    return SMTLIBCompilation(
        claim_id=metadata['claim_id'],
        claim_version=metadata['claim_version'],
        model_id=metadata['model_id'],
        model_cid=metadata['model_cid'],
        model_schema_version=metadata['model_schema_version'],
        smtlib=smtlib,
        metadata=metadata,
        modeled=True,
        not_modeled_reason=None,
    )


def compile_ir_claims_to_smtlib(
    model: SecurityModelIR | Mapping[str, Any],
    *,
    severities: Iterable[str] = XAMAN_CRITICAL_SEVERITIES,
    include_get_model: bool = False,
) -> list[SMTLIBCompilation]:
    """Compile declarative IR claims matching *severities* in model order."""

    normalized_model = as_security_model_ir(model)
    allowed_severities = {severity.strip().lower() for severity in severities}
    return [
        compile_ir_claim_to_smtlib(
            claim_record,
            normalized_model,
            include_get_model=include_get_model,
        )
        for claim_record in normalized_model.claims
        if str(claim_record.get('severity', '')).strip().lower() in allowed_severities
    ]


def emit_ir_smtlib_artifacts(
    model: SecurityModelIR | Mapping[str, Any],
    output_dir: str | Path,
    *,
    severities: Iterable[str] = XAMAN_CRITICAL_SEVERITIES,
    include_get_model: bool = False,
) -> dict[str, Any]:
    """Write SMT-LIB2 artifacts for declarative IR claims and a manifest."""

    normalized_model = as_security_model_ir(model)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = compile_ir_claims_to_smtlib(
        normalized_model,
        severities=severities,
        include_get_model=include_get_model,
    )
    manifest_entries: list[dict[str, Any]] = []
    for artifact in artifacts:
        filename = f'{_safe_filename(artifact.claim_id)}.smt2'
        output_path = directory / filename
        output_path.write_text(artifact.smtlib, encoding='utf-8')
        entry = artifact.to_manifest_entry(path=filename)
        entry.update(
            {
                'logic': artifact.metadata['logic'],
                'severity': artifact.metadata['severity'],
                'risk': artifact.metadata.get('risk', artifact.metadata['severity']),
                'domain': artifact.metadata.get('domain'),
                'xaman_category': artifact.metadata.get('xaman_category'),
                'blocking_assumption_count': len(artifact.metadata.get('blocking_assumption_ids', [])),
                'blocking_assumption_ids': list(artifact.metadata.get('blocking_assumption_ids', [])),
                'supported_theories': list(artifact.metadata.get('supported_theories', [])),
            }
        )
        manifest_entries.append(entry)

    manifest = {
        'schema_version': SMTLIB_SCHEMA_VERSION,
        'task_id': 'PORTAL-CXTP-069',
        'model_id': normalized_model.model_id,
        'model_cid': _model_cid_for_smtlib(normalized_model),
        'model_schema_version': normalized_model.schema_version,
        'query_kind': XAMAN_SMTLIB_QUERY_KIND,
        'logic': SMTLIB_LOGIC,
        'claim_scope': {
            'severities': sorted({severity.strip().lower() for severity in severities}),
            'selection': 'blocking-and-high-xaman-claims',
        },
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
        'model_cid': _model_cid_for_smtlib(model),
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


def _metadata_for_ir_claim(claim_record: Mapping[str, Any], model: SecurityModelIR) -> dict[str, Any]:
    claim_id = _required_claim_string(claim_record, 'id')
    severity = str(claim_record.get('severity') or claim_record.get('risk') or 'medium').strip().lower()
    required_assumptions = _string_list(claim_record.get('required_assumptions', []))
    blocking_assumption_ids = _string_list(claim_record.get('blocking_assumption_ids', []))
    if not blocking_assumption_ids:
        blocking_assumption_ids = list(required_assumptions)
    evidence_refs = [dict(reference) for reference in claim_record.get('evidence_refs', []) if isinstance(reference, Mapping)]
    blocker_symbols = [
        {
            'assumption_id': assumption_id,
            'symbol': f'xaman_blocking_assumption_{index}',
        }
        for index, assumption_id in enumerate(blocking_assumption_ids)
    ]
    compiler_artifact = {
        'claim_id': claim_id,
        'claim_source_status': claim_record.get('source_status'),
        'blocking_assumption_ids': blocking_assumption_ids,
        'required_assumptions': required_assumptions,
        'evidence_fact_ids': _string_list(claim_record.get('evidence_fact_ids', [])),
        'proof_obligation_statement': claim_record.get('proof_obligation_statement'),
        'consumer_policy': claim_record.get('consumer_policy'),
        'query_semantics': 'sat iff at least one blocking assumption prevents production acceptance',
        'blocker_symbols': blocker_symbols,
    }
    return {
        'schema_version': SMTLIB_SCHEMA_VERSION,
        'query_kind': XAMAN_SMTLIB_QUERY_KIND,
        'logic': SMTLIB_LOGIC,
        'supported_theories': [SMTLIB_LOGIC],
        'model_id': model.model_id,
        'model_cid': _model_cid_for_smtlib(model),
        'model_schema_version': model.schema_version,
        'claim_id': claim_id,
        'claim_version': str(claim_record.get('claim_version') or '1.0'),
        'claim_description': str(claim_record.get('description') or ''),
        'severity': severity,
        'risk': str(claim_record.get('risk') or severity).strip().lower(),
        'domain': claim_record.get('domain'),
        'xaman_category': claim_record.get('xaman_category'),
        'required_assumptions': required_assumptions,
        'blocking_assumption_ids': blocking_assumption_ids,
        'modeled': True,
        'not_modeled_reason': None,
        'assertion_count': len(blocker_symbols) + 1,
        'compiler_artifact_cid': calculate_artifact_cid(compiler_artifact),
        'compiler_artifact': compiler_artifact,
        'evidence_refs': evidence_refs,
        'soundness_notes': [
            'This SMT-LIB query models Xaman proof-acceptance blocking conditions, not native cryptographic implementation correctness.',
            'A SAT result for this query classifies the claim as blocked until the listed assumptions are evidenced and rechecked.',
        ],
        'violation_scope_explanation': 'Blocking assumption satisfiability query for Xaman release-gate claims.',
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


def _ir_claim_smtlib(metadata: Mapping[str, Any], *, include_get_model: bool) -> str:
    blocker_symbols = metadata['compiler_artifact']['blocker_symbols']
    lines = [_header(metadata).rstrip()]
    for blocker in blocker_symbols:
        symbol = blocker['symbol']
        assumption_id = _smtlib_string(blocker['assumption_id'])
        lines.append(f'; blocking_assumption: {assumption_id}')
        lines.append(f'(declare-fun {symbol} () Bool)')
        lines.append(f'(assert {symbol})')
    if blocker_symbols:
        disjunction = ' '.join(blocker['symbol'] for blocker in blocker_symbols)
        lines.append(f'(assert (or {disjunction}))')
    else:
        lines.append('(assert false)')
    lines.append('(check-sat)')
    if include_get_model:
        lines.append('(get-model)')
    return '\n'.join(lines) + '\n'


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


def _model_cid_for_smtlib(model: SecurityModelIR | Mapping[str, Any]) -> str:
    """Return the canonical model CID, falling back for mutation fixtures.

    Some counterexample tests intentionally remove events from an otherwise
    complete IR, leaving runtime traces that reference absent events. Those
    fixtures are still useful SMT inputs, but they are no longer valid canonical
    IR. Production artifacts keep using ``calculate_model_cid``; only invalid
    mutation fixtures take the raw deterministic artifact-CID fallback.
    """

    try:
        return calculate_model_cid(model)
    except ValueError:
        if isinstance(model, SecurityModelIR):
            return calculate_artifact_cid(model.to_dict())
        return calculate_artifact_cid(dict(model))


def _required_claim_string(claim_record: Mapping[str, Any], field_name: str) -> str:
    value = claim_record.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'IR claim record must include a non-empty {field_name}')
    return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int)) and str(item).strip()]


__all__ = [
    'SMTLIBCompilation',
    'SMTLIB_LOGIC',
    'SMTLIB_QUERY_KIND',
    'SMTLIB_SCHEMA_VERSION',
    'XAMAN_CRITICAL_SEVERITIES',
    'XAMAN_SMTLIB_QUERY_KIND',
    'compile_claim_to_smtlib',
    'compile_claims_to_smtlib',
    'compile_ir_claim_to_smtlib',
    'compile_ir_claims_to_smtlib',
    'emit_ir_smtlib_artifacts',
    'emit_smtlib_artifacts',
    'serialize_z3_compilation_to_smtlib',
]
