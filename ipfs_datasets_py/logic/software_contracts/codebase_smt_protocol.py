"""Pure validation of the bounded codebase SMT verdict/artifact protocol.

This module does not execute tools or grant proof authority. It accepts the
compiler's nonincremental, single-check command profile, then requests only the
artifact appropriate to a clean verdict. Process success, resource limits and
fresh-run/source identity are the execution owner's responsibility.
"""
from __future__ import annotations

from ..parsers.smtlib import SAtom, SList, read_sexprs
from ..syntax_core.contracts import ParseLimits


MAX_PROTOCOL_BYTES = 1024 * 1024
MAX_PROTOCOL_TOKENS = 65_536
MAX_PROTOCOL_DEPTH = 64
_VERDICTS = frozenset({"sat", "unsat", "unknown"})
_PREFIX_COMMANDS = frozenset({
    "set-info", "set-logic", "set-option", "declare-sort", "declare-fun", "declare-const",
    "declare-datatypes", "assert",
})


class SmtProtocolError(ValueError):
    """The compiler script or native response violates the closed protocol."""


def _forms(text: str) -> tuple[SAtom | SList, ...]:
    # Fence before encoding or parser allocation; str subclasses are not a
    # supported source of overridden encoders/iteration behavior.
    if type(text) is not str or not text or len(text) > MAX_PROTOCOL_BYTES:
        raise SmtProtocolError("SMT protocol text must be an exact, bounded, nonempty string")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError as error:
        raise SmtProtocolError("SMT protocol text must be valid UTF-8") from error
    if size > MAX_PROTOCOL_BYTES or "\x00" in text:
        raise SmtProtocolError("SMT protocol text exceeds its byte bound or contains NUL")
    forms, diagnostics = read_sexprs(text, limits=ParseLimits(
        max_input_bytes=MAX_PROTOCOL_BYTES, max_tokens=MAX_PROTOCOL_TOKENS,
        max_depth=MAX_PROTOCOL_DEPTH,
    ))
    if diagnostics or not forms:
        raise SmtProtocolError("SMT protocol text must contain bounded, balanced S-expressions")
    pending = list(forms)
    while pending:
        form = pending.pop()
        if isinstance(form, SList):
            pending.extend(form.items)
        elif form.kind == "quoted" and ("\\" in form.value or "|" in form.value):
            # The general reader tolerates legacy backslash escapes inside
            # quoted identifiers; this native protocol does not.
            raise SmtProtocolError("quoted symbols must use strict SMT-LIB syntax")
    return forms


def _symbol(node: object, value: str | None = None) -> bool:
    return (isinstance(node, SAtom) and node.kind == "symbol"
            and (value is None or node.value == value))


def _command(node: object) -> str:
    if not isinstance(node, SList) or not node.items or not _symbol(node.items[0]):
        raise SmtProtocolError("SMT script requires unquoted command lists")
    return node.items[0].value


def split_smt_script(smtlib: str) -> tuple[str, bool, bool]:
    """Strip only terminal artifact commands from one native compiler script.

    The returned base preserves the exact prefix through its sole check-sat,
    followed by a newline. Comments and strings containing command text have
    no effect. Incremental commands, trailing assertions and duplicate artifact
    requests are rejected rather than rewritten.
    """
    forms = _forms(smtlib)
    checked = False
    check_end = 0
    model_requested = core_requested = False
    for form in forms:
        command = _command(form)
        if command in {"check-sat", "get-model", "get-unsat-core"}:
            if len(form.items) != 1:
                raise SmtProtocolError("check and artifact commands must have no arguments")
            if command == "check-sat":
                if checked:
                    raise SmtProtocolError("SMT script requires exactly one check-sat")
                checked = True
                check_end = form.range.end_char
            elif not checked:
                raise SmtProtocolError("artifact commands must follow check-sat")
            elif command == "get-model":
                if model_requested:
                    raise SmtProtocolError("duplicate get-model request")
                model_requested = True
            else:
                if core_requested:
                    raise SmtProtocolError("duplicate get-unsat-core request")
                core_requested = True
        else:
            if checked or command not in _PREFIX_COMMANDS:
                raise SmtProtocolError("command is outside the native single-check profile")
            arity = {"set-info": 3, "set-logic": 2, "set-option": 3,
                     "declare-sort": 3, "declare-fun": 4, "declare-const": 3, "declare-datatypes": 3,
                     "assert": 2}[command]
            if len(form.items) != arity:
                raise SmtProtocolError("malformed native compiler command")
            if command == "set-option" and not (
                isinstance(form.items[1], SAtom)
                and form.items[1].kind == "keyword"
                and form.items[1].value in {":produce-models", ":produce-unsat-cores"}
                and _symbol(form.items[2], "true")
            ):
                raise SmtProtocolError("option is outside the native compiler profile")
    if not checked:
        raise SmtProtocolError("SMT script requires exactly one check-sat")
    return smtlib[:check_end] + "\n", model_requested, core_requested


def _response_forms(stdout: str) -> tuple[SAtom | SList, ...]:
    # Success acknowledgments and lexical comments are inert. A diagnostic
    # inside a quoted string is data; an actual (error ...) form is rejected.
    forms = _forms(stdout)
    pending = list(forms)
    while pending:
        form = pending.pop()
        if isinstance(form, SList):
            if form.items and _symbol(form.items[0], "error"):
                raise SmtProtocolError("SMT response contains an error diagnostic")
            pending.extend(form.items)
    return tuple(form for form in forms if not _symbol(form, "success"))


def parse_verdict(stdout: str) -> str:
    """Require exactly one clean lowercase verdict and no artifact or noise."""
    forms = _response_forms(stdout)
    if len(forms) != 1 or not _symbol(forms[0]) or forms[0].value not in _VERDICTS:
        raise SmtProtocolError("SMT response requires exactly one clean verdict")
    return forms[0].value


def artifact_script(base: str, verdict: str, model_requested: bool,
                    core_requested: bool) -> str | None:
    """Return a second single-check script requesting only its applicable artifact."""
    if type(verdict) is not str or verdict not in _VERDICTS:
        raise SmtProtocolError("unsupported SMT verdict")
    if type(model_requested) is not bool or type(core_requested) is not bool:
        raise SmtProtocolError("artifact request flags must be exact booleans")
    normalized, existing_model, existing_core = split_smt_script(base)
    if existing_model or existing_core:
        raise SmtProtocolError("artifact script base must not already request artifacts")
    command = ("get-model" if verdict == "sat" and model_requested else
               "get-unsat-core" if verdict == "unsat" and core_requested else None)
    if command is None:
        return None
    script = normalized + f"({command})\n"
    if len(script.encode("utf-8")) > MAX_PROTOCOL_BYTES:
        raise SmtProtocolError("artifact script exceeds its byte bound")
    return script


def validate_artifact_response(stdout: str, expected_verdict: str, kind: str) -> None:
    """Validate one matching verdict plus one model or unsat-core expression.

    Models may use Z3/CVC5's bare list or the explicit ``(model ...)`` wrapper.
    Empty models and cores are valid observations. This checks protocol shape,
    not model truth, core sufficiency, or correspondence to repository behavior.
    """
    if (type(expected_verdict) is not str or type(kind) is not str
            or (expected_verdict, kind) not in {("sat", "model"), ("unsat", "unsat_core")}):
        raise SmtProtocolError("artifact kind must match its conclusive verdict")
    forms = _response_forms(stdout)
    if (len(forms) != 2 or not _symbol(forms[0], expected_verdict)
            or not isinstance(forms[1], SList)):
        raise SmtProtocolError("artifact response requires one matching verdict and one artifact")
    artifact = forms[1]
    if kind == "unsat_core":
        if any(not isinstance(item, SAtom) or item.kind not in {"symbol", "quoted"}
               for item in artifact.items):
            raise SmtProtocolError("unsat core must be a list of assertion symbols")
        return
    definitions = artifact.items
    if definitions and _symbol(definitions[0], "model"):
        definitions = definitions[1:]
    for definition in definitions:
        if (not isinstance(definition, SList) or len(definition.items) != 5
                or not _symbol(definition.items[0], "define-fun")
                or not isinstance(definition.items[1], SAtom)
                or definition.items[1].kind not in {"symbol", "quoted"}
                or not isinstance(definition.items[2], SList)):
            raise SmtProtocolError("model must contain only complete define-fun entries")
        for parameter in definition.items[2].items:
            if (not isinstance(parameter, SList) or len(parameter.items) != 2
                    or not isinstance(parameter.items[0], SAtom)
                    or parameter.items[0].kind not in {"symbol", "quoted"}):
                raise SmtProtocolError("model function parameters must be name/sort pairs")


__all__ = ["SmtProtocolError", "split_smt_script", "parse_verdict",
           "artifact_script", "validate_artifact_response"]
