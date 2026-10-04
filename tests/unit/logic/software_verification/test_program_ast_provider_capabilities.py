"""Negotiate the selected optional provider without executing a trial parse.

These tests use controlled provider declarations. They assert no automatic import
selection changes and no semantic identity changes; declarations do not attest
that arbitrary third-party callback implementations obey their advertised API.
"""
import functools
import hashlib
import inspect
import json
import pickle
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic import software_verification as public
from ipfs_datasets_py.logic.software_verification import source_adapters as source
from ipfs_datasets_py.logic.software_verification import pipeline
from ipfs_datasets_py.logic.backends import process, resource_admission

TEXT = "# exact source: λ\ndef successor(x: int) -> int:\n    return x + 1\n"
OMITTED = object()
ROUTES = ("adapter", "object", "pipeline", "pipeline-helper", "public", "public-helper")


def run(route, mirror=OMITTED, *, include_supervisor_evidence=True):
    options = {"path": "source.py", "language": "python", "revision": "snapshot:capability"}
    if mirror is not OMITTED:
        options["mirror"] = mirror
    if route == "adapter":
        return source.adapt_source_to_software_verification(TEXT, preserve_type_annotations=True,
            include_supervisor_evidence=include_supervisor_evidence, **options)
    if route == "object":
        return source.SourceSoftwareVerificationAdapter(preserve_type_annotations=True,
            include_supervisor_evidence=include_supervisor_evidence).adapt(TEXT, **options)
    configuration = {"execute_solvers": False, "include_supervisor_evidence": include_supervisor_evidence}
    contracts = [pipeline.ContractSpec("successor", postconditions=("result == x + 1",),
                                      contract_id="contract:capability")]
    module = public if route.startswith("public") else pipeline
    if route.endswith("helper"):
        return module.run_source_to_verification_pipeline(TEXT, contracts=contracts, **configuration, **options)
    return module.SourceToVerificationPipeline(**configuration).run(TEXT, contracts=contracts, **options)


def evidence(text):
    data = {"language": "python", "status": "success", "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "blob_identity": "fixture:provider", "parser": "controlled-declaration", "facts": []}
    return SimpleNamespace(**data, to_dict=lambda: dict(data))


def make_provider(events, shape):
    if shape == "named-keyword":
        def adapter(text, *, path, language, max_source_bytes, mirror=True):
            events.append(("adapt", mirror))
            return evidence(text)
    elif shape == "named-positional-or-keyword":
        def adapter(text, mirror=True, *, path, language, max_source_bytes):
            events.append(("adapt", mirror))
            return evidence(text)
    elif shape == "legacy":
        def adapter(text, *, path, language, max_source_bytes):
            events.append(("adapt", "legacy"))
            return evidence(text)
    elif shape == "kwargs":
        def adapter(text, **kwargs):
            # Accepting arbitrary keywords cannot establish that the provider
            # honors this control: this deliberately ignores them all.
            events.append(("adapt", "ignored-controls"))
            return evidence(text)
    elif shape == "positional-only":
        def adapter(text, mirror=True, /, **kwargs):
            events.append(("adapt", mirror))
            return evidence(text)
    else:
        raise AssertionError(shape)
    return adapter


def select(monkeypatch, adapter, events):
    def detect(path, language):
        events.append(("detect", path))
        return "python"
    def load():
        events.append(("load", None))
        return adapter, detect
    monkeypatch.setattr(source, "_load_program_ast_adapter", load)
    return detect


def patch_signature(monkeypatch, callback):
    monkeypatch.setattr(source, "inspect", SimpleNamespace(**{**vars(inspect), "signature": callback}))


@pytest.fixture(autouse=True)
def deny_external_effects(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("capability negotiation must not launch native work or consult the shared pool")
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", denied)
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", denied)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("shape", ["legacy", "kwargs", "positional-only"])
def test_disabled_mirroring_refuses_incompatible_provider_before_detection(monkeypatch, route, shape):
    events = []
    select(monkeypatch, make_provider(events, shape), events)
    with pytest.raises(source.ProgramASTProviderCompatibilityError, match="mirror") as caught:
        run(route, False)
    assert isinstance(caught.value, TypeError)
    assert events == [("load", None)]
    assert TEXT not in str(caught.value)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("shape", ["named-keyword", "named-positional-or-keyword"])
def test_disabled_mirroring_calls_selected_keyword_capable_provider_once(monkeypatch, route, shape):
    events = []
    select(monkeypatch, make_provider(events, shape), events)
    result = run(route, False)
    assert events == [("load", None), ("detect", "source.py"), ("adapt", False)]
    assert result.program is not None


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("mirror", [OMITTED, True], ids=["default", "enabled"])
def test_default_legacy_calls_do_not_require_signature_introspection(monkeypatch, route, mirror):
    events = []
    select(monkeypatch, make_provider(events, "legacy"), events)
    # The module-level inspect patchpoint is replaced as an object, leaving
    # pytest and dataclass introspection in the rest of the process untouched.
    patch_signature(monkeypatch, lambda *a, **k: pytest.fail("default inspected provider"))
    result = run(route, mirror)
    assert result.program is not None
    assert events == [("load", None), ("detect", "source.py"), ("adapt", "legacy")]


@pytest.mark.parametrize("route", ROUTES)
def test_internal_type_error_is_preserved_without_retry_or_capability_relabel(monkeypatch, route):
    events = []
    expected = TypeError("provider parser failed after entry")
    def adapter(text, *, path, language, max_source_bytes, mirror=True):
        events.append(("adapt", mirror))
        raise expected
    select(monkeypatch, adapter, events)
    with pytest.raises(TypeError) as caught:
        run(route, False)
    assert caught.value is expected
    assert not isinstance(caught.value, source.ProgramASTProviderCompatibilityError)
    assert events == [("load", None), ("detect", "source.py"), ("adapt", False)]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("invalid", [None, 0, 1, "false"], ids=["none", "zero", "one", "string"])
def test_exact_boolean_validation_precedes_loader_and_capability_work(monkeypatch, route, invalid):
    monkeypatch.setattr(source, "_load_program_ast_adapter", lambda: pytest.fail("invalid control loaded provider"))
    patch_signature(monkeypatch, lambda *a, **k: pytest.fail("invalid control inspected"))
    with pytest.raises(ValueError, match="exact boolean"):
        run(route, invalid)


@pytest.mark.parametrize("route", ROUTES)
def test_native_only_never_loads_or_inspects_optional_provider(monkeypatch, route):
    monkeypatch.setattr(source, "_load_program_ast_adapter", lambda: pytest.fail("native-only loaded provider"))
    patch_signature(monkeypatch, lambda *a, **k: pytest.fail("native-only inspected"))
    values = [run(route, mode, include_supervisor_evidence=False).to_dict() for mode in (OMITTED, True, False)]
    assert values[0] == values[1] == values[2]


@pytest.mark.parametrize("route", ROUTES)
def test_absent_provider_preserves_native_semantic_fallback(monkeypatch, route):
    monkeypatch.setattr(source, "_load_program_ast_adapter", lambda: (None, None))
    actual = run(route, False)
    expected = run(route, False, include_supervisor_evidence=False)
    assert actual.to_dict() == expected.to_dict()


@pytest.mark.parametrize("route", ROUTES)
def test_capability_report_does_not_enter_semantic_wire(monkeypatch, route):
    events = []
    select(monkeypatch, make_provider(events, "named-keyword"), events)
    report = source.inspect_program_ast_provider()
    baseline = run(route).to_dict()
    assert baseline == run(route, True).to_dict() == run(route, False).to_dict()
    encoded = json.dumps(baseline, sort_keys=True)
    assert "mirror_false" not in encoded and "provider_capability" not in encoded
    assert "ProgramASTProviderCompatibility" not in encoded
    assert isinstance(report, dict) and report


@pytest.mark.parametrize("flavor", ["bound-method", "partial"])
def test_ordinary_method_and_partial_preserve_keyword_support(monkeypatch, flavor):
    events = []
    if flavor == "bound-method":
        class Provider:
            def adapt(self, text, *, path, language, max_source_bytes, mirror=True):
                events.append(("adapt", mirror))
                return evidence(text)
        adapter = Provider().adapt
    else:
        def adapt(tag, text, *, path, language, max_source_bytes, mirror=True):
            events.append((tag, mirror))
            return evidence(text)
        adapter = functools.partial(adapt, "adapt")
    select(monkeypatch, adapter, events)
    assert run("adapter", False).program is not None
    assert events == [("load", None), ("detect", "source.py"), ("adapt", False)]


def test_wrapped_inner_support_does_not_authorize_an_ambiguous_outer_callback(monkeypatch):
    events = []
    inner = make_provider(events, "named-keyword")
    @functools.wraps(inner)
    def wrapper(*args, **kwargs):
        pytest.fail("ambiguous wrapper was called")
    select(monkeypatch, wrapper, events)
    with pytest.raises(source.ProgramASTProviderCompatibilityError):
        run("adapter", False)
    assert events == [("load", None)]


def test_named_outer_support_is_used_even_when_wrapped_inner_is_legacy(monkeypatch):
    events = []
    legacy = make_provider(events, "legacy")
    @functools.wraps(legacy)
    def wrapper(text, *, path, language, max_source_bytes, mirror=True):
        events.append(("adapt", mirror))
        return evidence(text)
    select(monkeypatch, wrapper, events)
    assert run("adapter", False).program is not None
    assert events[-1] == ("adapt", False)


@pytest.mark.parametrize("error", [ValueError("unavailable signature"), TypeError("unsupported callable")], ids=["value-error", "type-error"])
def test_uninspectable_provider_is_refused_without_detector_or_trial_call(monkeypatch, error):
    events = []
    adapter = make_provider(events, "named-keyword")
    select(monkeypatch, adapter, events)
    def signature(callback, **kwargs):
        assert callback is adapter
        assert kwargs == {"follow_wrapped": False, "eval_str": False}
        raise error
    patch_signature(monkeypatch, signature)
    with pytest.raises(source.ProgramASTProviderCompatibilityError):
        run("adapter", False)
    assert events == [("load", None)]


def test_signature_annotations_are_not_evaluated(monkeypatch):
    events = []
    adapter = make_provider(events, "named-keyword")
    adapter.__annotations__ = {"mirror": "raise_if_evaluated()", "return": "raise_if_evaluated()"}
    select(monkeypatch, adapter, events)
    actual_signature = inspect.signature
    observed = []
    def signature(callback, **kwargs):
        observed.append(kwargs)
        return actual_signature(callback, **kwargs)
    patch_signature(monkeypatch, signature)
    assert run("adapter", False).program is not None
    assert observed == [{"follow_wrapped": False, "eval_str": False}]


def test_one_request_uses_one_captured_provider_pair(monkeypatch):
    events = []
    selected = make_provider(events, "named-keyword")
    def loader():
        events.append(("load", None))
        if len(events) > 1:
            pytest.fail("negotiation reloaded a different provider")
        return selected, lambda *args: (events.append(("detect", None)) or "python")
    monkeypatch.setattr(source, "_load_program_ast_adapter", loader)
    assert run("adapter", False).program is not None
    assert events == [("load", None), ("detect", None), ("adapt", False)]


def test_provider_replacement_does_not_reuse_old_capability(monkeypatch):
    events = []
    current = [make_provider(events, "named-keyword")]
    monkeypatch.setattr(source, "_load_program_ast_adapter", lambda: (current[0], lambda *args: "python"))
    assert run("adapter", False).program is not None
    current[0] = make_provider(events, "legacy")
    with pytest.raises(source.ProgramASTProviderCompatibilityError):
        run("adapter", False)
    current[0] = make_provider(events, "named-keyword")
    assert run("adapter", False).program is not None
    assert events == [("adapt", False), ("adapt", False)]


@pytest.mark.parametrize("shape,status,reason", [
    ("named-keyword", "supported", "explicit_keyword_parameter"),
    ("named-positional-or-keyword", "supported", "explicit_keyword_parameter"),
    ("legacy", "unsupported", "mirror_parameter_missing"),
    ("kwargs", "unknown", "variadic_keywords_only"),
    ("positional-only", "unsupported", "mirror_parameter_positional_only"),
])
def test_diagnostic_exact_status_and_selected_identity_without_calling_provider(monkeypatch, shape, status, reason):
    events = []
    adapter = make_provider(events, shape)
    detector = select(monkeypatch, adapter, events)
    before_path = tuple(sys.path)
    before_modules = {key: value for key, value in sys.modules.items() if key.startswith("ipfs_accelerate_py")}
    report = source.inspect_program_ast_provider()
    assert set(report) == {"schema", "status", "reason", "adapter", "detector", "scope"}
    assert report["schema"] == "program-ast-provider-inspection@1"
    assert (report["status"], report["reason"]) == (status, reason)
    assert report["scope"] == "Callable signature declaration only; no detector/parser invocation or side-effect attestation."
    for key, callback in (("adapter", adapter), ("detector", detector)):
        assert report[key] == {"module": callback.__module__, "qualname": callback.__qualname__,
                               "origin": callback.__code__.co_filename}
        assert Path(report[key]["origin"]).resolve() == Path(__file__).resolve()
    assert events == [("load", None)]
    assert tuple(sys.path) == before_path
    assert {key: value for key, value in sys.modules.items() if key.startswith("ipfs_accelerate_py")} == before_modules
    json.dumps(report)  # No callable object or executable descriptor enters the report.


@pytest.mark.parametrize("detector_present", [False, True])
def test_unavailable_diagnostic_is_explicit_without_detector_execution(monkeypatch, detector_present):
    calls = []
    def detector(*args):
        pytest.fail("inspection executed orphaned detector")
    monkeypatch.setattr(source, "_load_program_ast_adapter",
        lambda: (calls.append("load") or (None, detector if detector_present else None)))
    report = source.inspect_program_ast_provider()
    assert report["status"] == "unavailable" and report["reason"] == "optional_provider_unavailable"
    assert report["adapter"] is None
    assert (report["detector"] is not None) is detector_present
    assert calls == ["load"]


def test_non_callable_adapter_is_rejected_before_detector_or_signature(monkeypatch):
    events = []
    select(monkeypatch, 42, events)
    patch_signature(monkeypatch, lambda *a, **k: pytest.fail("non-callable inspected"))
    report = source.inspect_program_ast_provider()
    assert (report["status"], report["reason"]) == ("unsupported", "adapter_not_callable")
    with pytest.raises(source.ProgramASTProviderCompatibilityError) as caught:
        run("adapter", False)
    assert caught.value.diagnostic == report
    assert events == [("load", None), ("load", None)]


@pytest.mark.parametrize("shape,status,reason", [
    ("var-positional", "unsupported", "mirror_parameter_not_keyword_capable"),
    ("var-keyword", "unknown", "variadic_keywords_only"),
])
def test_a_variadic_parameter_named_mirror_does_not_declare_support(monkeypatch, shape, status, reason):
    calls = []
    if shape == "var-positional":
        def adapter(text, *mirror, path, language, max_source_bytes):
            pytest.fail("variadic mirror executed")
    else:
        def adapter(text, **mirror):
            pytest.fail("variadic mirror executed")
    select(monkeypatch, adapter, calls)
    report = source.inspect_program_ast_provider()
    assert (report["status"], report["reason"]) == (status, reason)
    with pytest.raises(source.ProgramASTProviderCompatibilityError):
        run("adapter", False)
    assert calls == [("load", None), ("load", None)]


@pytest.mark.parametrize("error", [ValueError("unreadable"), TypeError("uninspectable")], ids=["value-error", "type-error"])
def test_signature_failure_reports_unknown_not_a_trial_execution(monkeypatch, error):
    events = []
    select(monkeypatch, make_provider(events, "named-keyword"), events)
    def fail(*args, **kwargs):
        raise error
    patch_signature(monkeypatch, fail)
    report = source.inspect_program_ast_provider()
    assert (report["status"], report["reason"]) == ("unknown", "signature_unavailable")
    assert events == [("load", None)]


def test_absent_detector_uses_existing_local_language_detection(monkeypatch):
    events = []
    monkeypatch.setattr(source, "_load_program_ast_adapter", lambda: (make_provider(events, "named-keyword"), None))
    report = source.inspect_program_ast_provider()
    assert report["status"] == "supported" and report["detector"] is None
    result = source.adapt_source_to_software_verification(TEXT, path="source.py", mirror=False)
    assert result.language == "python" and result.program is not None
    assert events == [("adapt", False)]


def test_diagnostic_is_fresh_and_mutating_it_cannot_authorize_a_later_call(monkeypatch):
    events = []
    select(monkeypatch, make_provider(events, "legacy"), events)
    first = source.inspect_program_ast_provider()
    first["status"] = "supported"
    first["adapter"]["origin"] = "untrusted/replacement.py"
    second = source.inspect_program_ast_provider()
    assert second["status"] == "unsupported" and second["adapter"]["origin"] != first["adapter"]["origin"]
    with pytest.raises(source.ProgramASTProviderCompatibilityError) as caught:
        run("adapter", False)
    assert caught.value.diagnostic == second
    assert events == [("load", None)]*3


def test_compatibility_error_preserves_standard_typeerror_pickle_contract(monkeypatch):
    events = []
    select(monkeypatch, make_provider(events, "legacy"), events)
    with pytest.raises(source.ProgramASTProviderCompatibilityError) as caught:
        run("adapter", False)
    error = caught.value
    restored = pickle.loads(pickle.dumps(error))
    assert type(restored) is type(error) and isinstance(restored, TypeError)
    assert restored.args == error.args and restored.diagnostic == error.diagnostic


def test_diagnostic_does_not_render_arbitrary_default_values(monkeypatch):
    events = []
    class ExplosiveDefault:
        def __repr__(self):
            pytest.fail("inspection rendered a callback default")
    def adapter(text, *, path, language, max_source_bytes, mirror=ExplosiveDefault()):
        pytest.fail("inspection called provider")
    select(monkeypatch, adapter, events)
    report = source.inspect_program_ast_provider()
    assert report["status"] == "supported"
    assert events == [("load", None)]


def test_diagnostic_identity_fields_are_bounded_and_metadata_failures_are_observational(monkeypatch):
    events = []
    adapter = make_provider(events, "named-keyword")
    adapter.__module__ = "m"*700
    adapter.__qualname__ = "q"*700
    select(monkeypatch, adapter, events)
    report = source.inspect_program_ast_provider()
    assert report["status"] == "supported"
    for value in report["adapter"].values():
        assert value is None or isinstance(value, str) and len(value) <= 512
    assert events == [("load", None)]
