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
            required_assumptions=['cryptographic primitives are unbroken'],
            severity='high',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        if not model.capabilities:
            return claim_not_modeled(self, 'capabilities are not modeled')
        capability = self.find_capability(model)
        z3 = z3_import()
        policy_enabled = z3.Bool('delegation_monotonicity')
        delegated = z3.Int('delegated_authority')
        delegator = z3.Int('delegator_authority')
        assertions = [
            policy_enabled == self.policy_enabled(model, 'delegation_monotonicity'),
            delegated == int(capability.get('delegated_authority', 0)),
            delegator == int(capability.get('delegator_authority', 0)),
        ]
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(policy_enabled, delegated <= delegator),
            violation_formula=z3.Or(z3.Not(policy_enabled), delegated > delegator),
            compiler_artifact={
                'kind': 'capability_delegation',
                'policy_enabled': self.policy_enabled(model, 'delegation_monotonicity'),
                'delegated_authority': int(capability.get('delegated_authority', 0)),
                'delegator_authority': int(capability.get('delegator_authority', 0)),
            },
        )


class RevokedCapabilityClaim(SecurityClaim):
    """Revoked capabilities must not authorize future actions."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='revoked_capability_no_future_authorization',
            description='Revoked capability cannot authorize future action.',
            required_assumptions=['audit logs are append-only or tamper-evident'],
            severity='high',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        if not model.capabilities:
            return claim_not_modeled(self, 'capability revocation data is not modeled')
        capability = self.find_capability(model)
        z3 = z3_import()
        policy_enabled = z3.Bool('revocation_enforced')
        revoked_before_action = z3.Bool('revoked_before_action')
        privileged_action = z3.Bool('privileged_action_attempted')
        assertions = [
            policy_enabled == self.policy_enabled(model, 'revocation_enforced'),
            revoked_before_action == bool(capability.get('revoked_before_action', False)),
            privileged_action == bool(capability.get('privileged_action_attempted', False)),
        ]
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(
                policy_enabled,
                z3.Implies(privileged_action, z3.Not(revoked_before_action)),
            ),
            violation_formula=z3.Or(
                z3.Not(policy_enabled),
                z3.And(privileged_action, revoked_before_action),
            ),
            compiler_artifact={
                'kind': 'capability_revocation',
                'policy_enabled': self.policy_enabled(model, 'revocation_enforced'),
                'revoked_before_action': bool(capability.get('revoked_before_action', False)),
                'privileged_action_attempted': bool(capability.get('privileged_action_attempted', False)),
            },
        )
