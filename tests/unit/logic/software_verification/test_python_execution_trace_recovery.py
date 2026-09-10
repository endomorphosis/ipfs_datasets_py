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
