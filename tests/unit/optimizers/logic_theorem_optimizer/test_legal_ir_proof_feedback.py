"""Compatibility collection path for the Legal IR proof-feedback contract.

The implementation lives in the logic integration package because it is the
trust boundary shared by all optimizers.  The backlog validation contract uses
the optimizer test path, so collect that authoritative suite here as well.
"""

from tests.unit.logic.integration.test_legal_ir_proof_feedback import *  # noqa: F401,F403
