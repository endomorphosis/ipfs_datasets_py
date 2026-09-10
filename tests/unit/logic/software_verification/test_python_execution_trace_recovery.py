"""Control interruptions must not become completed trace records."""

import sys

import pytest

from ipfs_datasets_py.logic.software_verification.python_execution_trace import PythonExecutionTracer


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_interruption_propagates_and_restores_tracer_for_the_next_record(interruption):
    tracer = PythonExecutionTracer()
    previous_trace, previous_profile = sys.gettrace(), sys.getprofile()

    def interrupt():
        raise interruption()

    with pytest.raises(interruption):
        tracer.record(interrupt)
    assert sys.gettrace() is previous_trace
    assert sys.getprofile() is previous_profile
    assert tracer.record(lambda: 7).result == 7


def test_recovery_preserves_private_frame_and_record_redaction():
    """Retain the additional privacy checks from the rejected rescue proposal."""
    canary = "sk_live_not_a_real_key"
    key_canary = "k-live"

    def leak(password, api_key):
        token = password
        return token

    record = PythonExecutionTracer().record(leak, canary, key_canary)
    secret_keys = {"password", "api_key", "token"}
    assert secret_keys.intersection(record.redacted_dimensions)
    for frame in record.frames:
        summary = repr(dict(frame.state_summary))
        assert canary not in summary
        assert key_canary not in summary
    for projection in (record.to_dict(), record.to_public_dict()):
        assert canary not in repr(projection)
        assert key_canary not in repr(projection)
