"""Capability and delegation safety claims."""

from __future__ import annotations

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
        violations: list[str] = []
        for capability in capabilities:
            capability_id = str(capability.get('id', '<unknown>'))
            delegated = int(capability.get('delegated_authority', 0))
            parent = int(capability.get('delegator_authority', capability.get('parent_authority', 0)))
            if delegated > parent:
                violations.append(capability_id)
                continue
            parent_actions = set(capability.get('parent_actions', []))
            delegated_actions = set(capability.get('delegated_actions', capability.get('actions', [])))
            if parent_actions and not delegated_actions.issubset(parent_actions):
                violations.append(capability_id)
                continue
            parent_resources = set(capability.get('parent_resources', []))
            delegated_resources = set(capability.get('delegated_resources', capability.get('resources', [])))
            if parent_resources and not delegated_resources.issubset(parent_resources):
                violations.append(capability_id)
                continue
            if bool(capability.get('caveats_relax_authority', capability.get('caveats_widen_authority', False))):
                violations.append(capability_id)
                continue
            if not bool(capability.get('allow_expiry_extension', False)):
                parent_expiry = capability.get('parent_expiry')
                expiry = capability.get('expiry')
                if parent_expiry is not None and expiry is not None and int(expiry) > int(parent_expiry):
                    violations.append(capability_id)
        z3 = z3_import()
        policy_record = self.policy_record(model, 'delegation_monotonicity')
        evidence_refs = self.evidence_refs(policy_record, *capabilities)
        return Z3Compilation(
            claim=self,
            assertions=[],
            property_formula=z3.And(
                z3.BoolVal(self.policy_enabled(model, 'delegation_monotonicity')),
                z3.Not(z3.BoolVal(bool(violations))),
            ),
            compiler_artifact={
                'kind': 'capability_delegation',
                'violations': violations,
                'capability_ids': [capability.get('id') for capability in capabilities],
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
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
        capabilities = self.iter_capabilities(model)
        if not capabilities:
            return claim_not_modeled(self, 'capability revocation data is not modeled')
        violations: list[str] = []
        for capability in capabilities:
            capability_id = str(capability.get('id', '<unknown>'))
            privileged_action = bool(capability.get('privileged_action_attempted', False))
            revoked = bool(capability.get('revoked_before_action', False))
            expired = bool(capability.get('expired', False))
            if privileged_action and (revoked or expired):
                violations.append(capability_id)
        z3 = z3_import()
        policy_record = self.policy_record(model, 'revocation_enforced')
        evidence_refs = self.evidence_refs(policy_record, *capabilities)
        return Z3Compilation(
            claim=self,
            assertions=[],
            property_formula=z3.And(
                z3.BoolVal(self.policy_enabled(model, 'revocation_enforced')),
                z3.Not(z3.BoolVal(bool(violations))),
            ),
            compiler_artifact={
                'kind': 'capability_revocation',
                'violations': violations,
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
        )
