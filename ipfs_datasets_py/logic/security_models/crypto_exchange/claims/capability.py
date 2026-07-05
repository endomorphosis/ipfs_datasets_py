"""Capability and delegation safety claims."""

from __future__ import annotations

from typing import Any

from .base import SecurityClaim
from ..compilers.to_z3 import Z3Compilation, claim_not_modeled, z3_import
from ..ir.schema import SecurityModelIR


class CapabilityDelegationMonotonicityClaim(SecurityClaim):
    """Delegation must not amplify authority."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='capability_delegation_no_authority_increase',
            description='Capability delegation cannot increase authority.',
            required_assumptions=['A1', 'A7'],
            severity='high',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        capabilities = self.iter_capabilities(model)
        if not capabilities:
            return claim_not_modeled(self, 'capabilities are not modeled')
        z3 = z3_import()
        assertions: list[Any] = []
        checks: list[Any] = []
        violations: list[dict[str, Any]] = []
        capability_by_id = {str(capability.get('id')): capability for capability in capabilities if capability.get('id') is not None}
        for index, capability in enumerate(capabilities):
            capability_id = str(capability.get('id', f'capability:{index}'))
            delegated = int(capability.get('delegated_authority', 0))
            parent = int(capability.get('delegator_authority', capability.get('parent_authority', 0)))
            parent_id = capability.get('parent_capability_id')
            parent_capability = capability_by_id.get(str(parent_id)) if parent_id is not None else None
            parent_exists = parent_id is None or parent_capability is not None
            parent_actions = set(capability.get('parent_actions', parent_capability.get('delegated_actions', parent_capability.get('actions', [])) if parent_capability else []))
            delegated_actions = set(capability.get('delegated_actions', capability.get('actions', [])))
            parent_resources = set(capability.get('parent_resources', parent_capability.get('delegated_resources', parent_capability.get('resources', [])) if parent_capability else []))
            delegated_resources = set(capability.get('delegated_resources', capability.get('resources', [])))
            expiry_ok = True
            if not bool(capability.get('allow_expiry_extension', False)):
                parent_expiry = capability.get('parent_expiry', parent_capability.get('expiry') if parent_capability else None)
                expiry = capability.get('expiry')
                if parent_expiry is not None and expiry is not None:
                    expiry_ok = int(expiry) <= int(parent_expiry)
            parent_active = True
            if parent_capability is not None:
                parent_active = not bool(parent_capability.get('revoked_before_action', False)) and not bool(parent_capability.get('expired', False))
            condition_values = {
                'authority_ok': delegated <= parent,
                'parent_exists': parent_exists,
                'actions_ok': not parent_actions or delegated_actions.issubset(parent_actions),
                'resources_ok': not parent_resources or delegated_resources.issubset(parent_resources),
                'caveats_ok': not bool(capability.get('caveats_relax_authority', capability.get('caveats_widen_authority', False))),
                'expiry_ok': expiry_ok,
                'parent_active': parent_active,
            }
            condition_vars = []
            for name, value in condition_values.items():
                condition_var = z3.Bool(f'capability_{index}_{name}')
                assertions.append(condition_var == value)
                condition_vars.append(condition_var)
            checks.append(z3.And(*condition_vars))
            if not all(condition_values.values()):
                violations.append({'capability_id': capability_id, 'conditions': condition_values})
        policy_record = self.policy_record(model, 'delegation_monotonicity')
        evidence_refs = self.evidence_refs(policy_record, *capabilities)
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(*(checks or [z3.BoolVal(False)])),
            compiler_artifact={
                'kind': 'capability_delegation',
                'violations': violations,
                'capability_ids': [item['capability_id'] for item in violations],
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
            violation_scope_explanation='Each delegated capability is constrained by the modeled parent scope.',
        )


class RevokedCapabilityClaim(SecurityClaim):
    """Revoked capabilities must not authorize future actions."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='revoked_capability_no_future_authorization',
            description='Revoked capability cannot authorize future action.',
            required_assumptions=['A10'],
            severity='high',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        capability_events = [
            event for event in model.events
            if event.get('event') in {'capability_revoked', 'capability_reinstated', 'privileged_action'}
        ]
        capabilities = self.iter_capabilities(model)
        if not capability_events and not capabilities:
            return claim_not_modeled(self, 'capability revocation data is not modeled')
        z3 = z3_import()
        assertions: list[Any] = []
        checks: list[Any] = []
        violations: list[dict[str, Any]] = []
        revocations = [event for event in capability_events if event.get('event') == 'capability_revoked']
        reinstatements = [event for event in capability_events if event.get('event') == 'capability_reinstated']
        actions = [event for event in capability_events if event.get('event') == 'privileged_action']
        for index, action in enumerate(actions):
            capability_id = action.get('capability_id')
            action_time = action.get('timestamp')
            prior_revocations = [
                event for event in revocations
                if event.get('capability_id') == capability_id and (event.get('timestamp') is None or action_time is None or event.get('timestamp') <= action_time)
            ]
            prior_reinstatements = [
                event for event in reinstatements
                if event.get('capability_id') == capability_id and (event.get('timestamp') is None or action_time is None or event.get('timestamp') <= action_time)
            ]
            not_revoked = len(prior_revocations) <= len(prior_reinstatements)
            condition_var = z3.Bool(f'revocation_{index}_not_revoked')
            assertions.append(condition_var == not_revoked)
            checks.append(condition_var)
            if not not_revoked:
                violations.append(
                    {
                        'event_id': str(action.get('id', f'action:{index}')),
                        'capability_id': str(capability_id),
                    }
                )
        for index, capability in enumerate(capabilities):
            capability_id = str(capability.get('id', f'capability:{index}'))
            privileged_action = bool(capability.get('privileged_action_attempted', False))
            revoked = bool(capability.get('revoked_before_action', False))
            expired = bool(capability.get('expired', False))
            if privileged_action and (revoked or expired):
                condition_var = z3.Bool(f'capability_{index}_legacy_not_revoked')
                assertions.append(condition_var == False)
                checks.append(condition_var)
                violations.append({'event_id': f'legacy:{capability_id}', 'capability_id': capability_id})
        policy_enabled = self.policy_enabled(model, 'revocation_enforced')
        if not policy_enabled:
            violations.append({'event_id': 'policy:revocation_enforced', 'capability_id': '<policy>'})
        policy_record = self.policy_record(model, 'revocation_enforced')
        evidence_refs = self.evidence_refs(policy_record, *capability_events, *capabilities)
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(z3.BoolVal(policy_enabled), *(checks or [z3.BoolVal(True)])),
            compiler_artifact={
                'kind': 'capability_revocation',
                'violating_event_ids': [item['event_id'] for item in violations],
                'capability_ids': [item['capability_id'] for item in violations],
                'violations': violations,
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
            violation_scope_explanation='Each privileged action must occur before revocation or after explicit reinstatement.',
        )
