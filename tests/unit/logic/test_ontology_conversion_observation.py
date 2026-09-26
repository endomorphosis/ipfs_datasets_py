"""Conversion observations preserve recipient/procedure fallback behavior."""

import pytest

from ipfs_datasets_py.logic.autoformal.procedure_slot import procedure_from_sentence
from ipfs_datasets_py.logic.autoformal.recipient_reference import recipient_surface_from_sentence
from ipfs_datasets_py.logic.common.converters import ConversionResult, ConversionStatus
from ipfs_datasets_py.logic.deontic import DeonticConverter
from ipfs_datasets_py.logic.integration.deontic_logic_core import DeonticFormula, DeonticOperator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_ontology_observation as observation


TEXT = "The agency shall send notice to the requester"
EMPTY_PROCEDURE = {"events": [], "procedure_id": "", "surface": "", "admitted": False}
PROCEDURE = {"events": ["notice", "hearing"], "procedure_id": "notice->hearing",
             "surface": "notice -> hearing", "admitted": False}


def _output():
    output = DeonticFormula(operator=DeonticOperator.OBLIGATION, proposition="notify")
    output.parser_elements = [{"action_recipient": "  designated   beneficiary ",
                               "procedure": {"events": ["notice", "hearing"]}}]
    return output


@pytest.fixture
def observed(monkeypatch):
    events = []
    monkeypatch.setattr(observation, "observation_active", lambda: True)
    monkeypatch.setattr(observation, "note_conversion_result",
                        lambda stage, **values: events.append({"stage": stage, **values}))
    return events


def _return_results(monkeypatch, results):
    pending = iter(results)
    calls = []

    def convert(self, text, *args, **kwargs):
        assert type(self) is DeonticConverter
        calls.append(text)
        return next(pending)

    monkeypatch.setattr(DeonticConverter, "convert", convert)
    return calls


@pytest.mark.parametrize("helper,stage,fallback,recovered", [
    (recipient_surface_from_sentence, "recipient_conversion", "requester", "designated beneficiary"),
    (procedure_from_sentence, "procedure_conversion", EMPTY_PROCEDURE, PROCEDURE),
])
def test_failed_conversion_retains_fallback_then_recovery(monkeypatch, observed, helper, stage, fallback, recovered):
    failed = ConversionResult(status=ConversionStatus.FAILED,
                              errors=["Conversion error: transient failure\nUnicode: é"])
    ready = ConversionResult(output=_output(), status=ConversionStatus.SUCCESS)
    calls = _return_results(monkeypatch, [failed, ready])
    assert helper(TEXT) == fallback
    assert helper(TEXT) == recovered
    assert calls == [TEXT, TEXT]
    assert observed == [
        {"stage": stage, "status": "failed", "successful": False,
         "error_count": 1, "warning_count": 0, "supported": True},
        {"stage": stage, "status": "success", "successful": True,
         "error_count": 0, "warning_count": 0, "supported": True},
    ]
    assert failed.output is None and failed.errors == ["Conversion error: transient failure\nUnicode: é"]
    assert ready.output.parser_elements[0]["action_recipient"] == "  designated   beneficiary "


@pytest.mark.parametrize("helper,expected", [
    (recipient_surface_from_sentence, "designated beneficiary"), (procedure_from_sentence, PROCEDURE),
])
@pytest.mark.parametrize("status", list(ConversionStatus))
def test_native_status_and_warning_counts_do_not_change_extracted_output(monkeypatch, observed, helper, expected, status):
    result = ConversionResult(output=_output(), status=status, warnings=["first", "second"])
    _return_results(monkeypatch, [result])
    assert helper(TEXT) == expected
    assert observed[0]["status"] == status.value
    assert observed[0]["successful"] is result.success
    assert observed[0]["warning_count"] == 2
    assert observed[0]["error_count"] == 0
    assert observed[0]["supported"] is True
    assert result.warnings == ["first", "second"]


class _UnsafeList(list):
    def __iter__(self):
        raise AssertionError("custom metadata must not be inspected")

    def __len__(self):
        raise AssertionError("custom metadata must not be counted")


@pytest.mark.parametrize("field,value", [
    ("errors", None), ("warnings", None), ("errors", _UnsafeList()),
    ("warnings", _UnsafeList()), ("status", "success"),
])
@pytest.mark.parametrize("helper,expected", [
    (recipient_surface_from_sentence, "designated beneficiary"), (procedure_from_sentence, PROCEDURE),
])
def test_malformed_native_metadata_is_unknown_without_touching_output(monkeypatch, observed, field, value, helper, expected):
    result = ConversionResult(output=_output(), status=ConversionStatus.SUCCESS)
    setattr(result, field, value)
    _return_results(monkeypatch, [result])
    assert helper(TEXT) == expected
    assert observed[0]["supported"] is False
    assert observed[0]["status"] is None
    assert observed[0]["successful"] is None
    assert observed[0]["error_count"] is None
    assert observed[0]["warning_count"] is None


@pytest.mark.parametrize("helper,expected", [
    (recipient_surface_from_sentence, "designated beneficiary"), (procedure_from_sentence, PROCEDURE),
])
def test_custom_result_metadata_is_not_inspected(monkeypatch, observed, helper, expected):
    class CustomResult:
        output = _output()

        @property
        def status(self):
            raise AssertionError("custom result status must not be inspected")

    _return_results(monkeypatch, [CustomResult()])
    assert helper(TEXT) == expected
    assert observed[0]["supported"] is False
    assert observed[0]["error_count"] is None


def test_no_observer_does_not_read_conversion_metadata(monkeypatch):
    result = ConversionResult(output=_output(), status=ConversionStatus.SUCCESS)
    result.errors = _UnsafeList()
    _return_results(monkeypatch, [result])
    monkeypatch.setattr(observation, "observation_active", lambda: False)
    monkeypatch.setattr(observation, "note_conversion_result",
                        lambda *args, **kwargs: pytest.fail("inactive observer called"))
    assert recipient_surface_from_sentence(TEXT) == "designated beneficiary"


def test_native_tuple_metadata_is_counted_without_retaining_values(monkeypatch, observed):
    result = ConversionResult(output=_output(), status=ConversionStatus.PARTIAL,
                              warnings=("tuple warning",))
    _return_results(monkeypatch, [result])
    assert procedure_from_sentence(TEXT) == PROCEDURE
    assert observed[0]["warning_count"] == 1 and observed[0]["supported"] is True
    assert "tuple warning" not in repr(observed)


def test_metadata_contents_are_not_read_for_counts(monkeypatch, observed):
    class Unreadable:
        def __str__(self):
            raise AssertionError("metadata contents must not be read")

        def __repr__(self):
            raise AssertionError("metadata contents must not be read")

    result = ConversionResult(output=_output(), status=ConversionStatus.FAILED,
                              errors=[Unreadable()], warnings=[Unreadable()])
    _return_results(monkeypatch, [result])
    assert procedure_from_sentence(TEXT) == PROCEDURE
    assert observed[0]["error_count"] == observed[0]["warning_count"] == 1
    assert observed[0]["supported"] is True


def test_real_observer_records_failure_then_recovery_without_qualifying_reuse(monkeypatch):
    failed = ConversionResult(status=ConversionStatus.FAILED, errors=["transient"])
    recovered = ConversionResult(output=_output(), status=ConversionStatus.SUCCESS)
    calls = _return_results(monkeypatch, [failed, recovered])
    with observation.observe_ontology_captures(producer_identity={"kind": "test"}) as observer:
        assert procedure_from_sentence(TEXT) == EMPTY_PROCEDURE
        assert procedure_from_sentence(TEXT) == PROCEDURE
    recorded = observer.to_dict()
    assert calls == [TEXT, TEXT]
    assert recorded["reuse_qualified"] is False
    assert [row["status"] for row in recorded["conversions"]] == ["failed", "success"]
    assert [row["error_count"] for row in recorded["conversions"]] == [1, 0]
    assert "transient" not in repr(recorded)


def test_raised_conversion_exception_still_escapes_and_emits_no_returned_result(monkeypatch, observed):
    error = RuntimeError("direct conversion exception")

    def convert(self, text):
        raise error

    monkeypatch.setattr(DeonticConverter, "convert", convert)
    with pytest.raises(RuntimeError) as captured:
        procedure_from_sentence(TEXT)
    assert captured.value is error
    assert observed == []
