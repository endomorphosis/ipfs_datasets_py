"""Claim registry for the crypto exchange verification framework."""

from .base import SecurityClaim
from .capability import CapabilityDelegationMonotonicityClaim, RevokedCapabilityClaim
from .deposit import NoDepositCreditedBeforeFinalityClaim
from .hsm import NoSigningAfterWalletFreezeClaim
from .ledger import (
    AuditEventExistsForCriticalTransitionClaim,
    GlobalAssetConservationClaim,
    NoOverReservedInternalAccountClaim,
)
from .withdrawal import NoUnauthorizedWithdrawalClaim


def default_claims() -> list[SecurityClaim]:
    """Return the initial claim set for the framework."""

    return [
        NoUnauthorizedWithdrawalClaim(),
        NoOverReservedInternalAccountClaim(),
        GlobalAssetConservationClaim(),
        NoDepositCreditedBeforeFinalityClaim(),
        NoSigningAfterWalletFreezeClaim(),
        CapabilityDelegationMonotonicityClaim(),
        RevokedCapabilityClaim(),
        AuditEventExistsForCriticalTransitionClaim(),
    ]


__all__ = [
    'AuditEventExistsForCriticalTransitionClaim',
    'CapabilityDelegationMonotonicityClaim',
    'NoDepositCreditedBeforeFinalityClaim',
    'GlobalAssetConservationClaim',
    'NoOverReservedInternalAccountClaim',
    'NoSigningAfterWalletFreezeClaim',
    'NoUnauthorizedWithdrawalClaim',
    'RevokedCapabilityClaim',
    'SecurityClaim',
    'default_claims',
]
