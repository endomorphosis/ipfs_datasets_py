"""Project security IR facts into a Codex-friendly feature loop bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..claims import default_claims
from ..ir.cid import calculate_model_cid
from ..ir.schema import SecurityModelIR, validate_ir
from .source_code_extractor import SourceCodeExtractor

DEFAULT_INGESTION_PRINCIPLES = (
    'deterministic canonicalization before proof generation',
    'bounded claims must name explicit assumptions',
    'seed autoformalization requires human review before production proof use',
    'unsupported or UNKNOWN prover results never imply security',
    'code ingestion and proof regression should share the same projected feature bundle',
)


class SecurityIRFeatureLoopProjector:
    """Project security IR facts into a portable program-synthesis feature bundle."""

    def __init__(self, *, source_extractor: SourceCodeExtractor | None = None) -> None:
        self._source_extractor = source_extractor or SourceCodeExtractor()

    def project_model(self, model: SecurityModelIR | Mapping[str, Any]) -> dict[str, Any]:
        """Project a validated security IR model into a deterministic feature bundle."""

        validated = validate_ir(model)
        autoformalization = validated.metadata.get('autoformalization', {})
        languages = self._languages(autoformalization)
        return {
            'projection_kind': 'security-ir-feature-loop/v1',
            'model_id': validated.model_id,
            'model_cid': calculate_model_cid(validated),
            'ingestion_principles': list(DEFAULT_INGESTION_PRINCIPLES),
            'feature_counts': {
                'entities': len(validated.entities),
                'policies': len(validated.policies),
                'events': len(validated.events),
                'invariants': len(validated.invariants),
                'assumptions': len(validated.assumptions),
            },
            'features': {
                'languages': languages,
                'source_inputs': self._source_inputs(autoformalization),
                'entity_names': self._names(validated.entities),
                'principal_ids': self._ids(validated.principals),
                'capability_ids': self._ids(validated.capabilities),
                'policy_names': sorted(policy.get('name', policy.get('id', '')) for policy in validated.policies if policy.get('name') or policy.get('id')),
                'critical_events': sorted(event.get('event', event.get('id', '')) for event in validated.events if event.get('critical')),
                'invariant_descriptions': sorted(
                    invariant.get('description', invariant.get('id', ''))
                    for invariant in validated.invariants
                    if invariant.get('description') or invariant.get('id')
                ),
                'assumption_ids': self._assumption_ids(validated.assumptions),
                'prover_targets': sorted(validated.prover_targets),
            },
            'codex_program_synthesis': {
                'scope': 'security_ir_autoformalization',
                'review_status': autoformalization.get('review_status', 'hand-authored-model'),
                'review_gaps': list(autoformalization.get('gaps', [])),
                'required_report_statuses': ['PROVED', 'DISPROVED', 'UNKNOWN', 'NOT_MODELED'],
                'claims': [
                    {
                        'claim_id': claim.claim_id,
                        'severity': claim.severity,
                        'required_assumptions': list(claim.required_assumptions),
                    }
                    for claim in default_claims()
                ],
                'policy_sources': {
                    policy.get('name', policy.get('id', f'policy:{index}')): sorted(str(source) for source in policy.get('sources', []))
                    for index, policy in enumerate(validated.policies)
                },
            },
        }

    def project_path(self, path: str | Path, *, model_id: str | None = None) -> dict[str, Any]:
        """Autoformalize supported source inputs and project them into the feature loop."""

        model = self._source_extractor.extract_ir_from_path(path, model_id=model_id)
        return self.project_model(model)

    @staticmethod
    def _languages(autoformalization: Mapping[str, Any]) -> list[str]:
        languages = autoformalization.get('languages')
        if isinstance(languages, list):
            return sorted(str(language) for language in languages)
        language = autoformalization.get('language')
        if language:
            return [str(language)]
        return []

    @staticmethod
    def _source_inputs(autoformalization: Mapping[str, Any]) -> list[str]:
        source_files = autoformalization.get('source_files')
        if isinstance(source_files, list):
            return sorted(str(item) for item in source_files)
        module_path = autoformalization.get('module_path')
        if module_path:
            return [str(module_path)]
        return []

    @staticmethod
    def _names(entries: list[dict[str, Any]]) -> list[str]:
        return sorted(str(entry['name']) for entry in entries if entry.get('name'))

    @staticmethod
    def _ids(entries: list[dict[str, Any]]) -> list[str]:
        return sorted(str(entry['id']) for entry in entries if entry.get('id'))

    @staticmethod
    def _assumption_ids(assumptions: list[dict[str, Any] | str]) -> list[str]:
        assumption_ids: list[str] = []
        for assumption in assumptions:
            if isinstance(assumption, str):
                assumption_ids.append(assumption)
            else:
                assumption_ids.append(str(assumption.get('id', '')))
        return sorted(
            (assumption_id for assumption_id in assumption_ids if assumption_id),
            key=lambda assumption_id: (assumption_id[:1], int(assumption_id[1:]) if assumption_id[1:].isdigit() else assumption_id[1:]),
        )
