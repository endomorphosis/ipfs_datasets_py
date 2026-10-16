#!/usr/bin/env python3
"""Native-owned replay of retained unreviewed source/typed correspondence.

Only run inside the existing owned-validation launcher. Original request and
source bytes are inputs; reports are explicitly new current-checkout outputs.
Python syntax/parser and generated Lean text are not actual Lean execution.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "retained-source-typed-norm-join-probe/v1"
SELECTED_CHECK = "retained-two-source-three-typed-norm-join-cases"
MiB = 1024 * 1024
MAX_INPUT = 4 * MiB
MAX_OUTPUT = 32 * MiB
AUTHOR_ROOT = Path("/home/barberb/lift_coding/artifacts/legal-corpus-contracts-20261013-01/datasets")
ARTIFACTS = Path("/home/barberb/lift_coding/artifacts")
JOIN_ROOT = ARTIFACTS / "legal-corpus-source-typed-join-20261015-01/source-typed-proposals-01"
SCOPE_ROOT = ARTIFACTS / "legal-corpus-norm-scope-20261015-01/norm-proposals-01"
STATUTORY_ROOT = ARTIFACTS / "legal-corpus-statutory-component-20261015-01/real-definition-01"
ANCHORS = {
    "join_manifest": "5ea709a31a71ce9f90fb7fe8988dc8d0b4364872311f864308171424fcf87fc6",
    "scope_manifest": "481aa642384c5a9f186251907f8cb0c722e1233ee8e898615d9c19ad5b0beeb6",
    "statutory_manifest": "3c035af7fbaebb49d6657122931068370ddf729f701c10bb7231af0e9f67f2a4",
}
SOURCE_PATHS = (
    "ipfs_datasets_py/logic/CEC/native/dcec_cleaning.py",
    "ipfs_datasets_py/logic/CEC/native/dcec_core.py",
    "ipfs_datasets_py/logic/CEC/native/dcec_integration.py",
    "ipfs_datasets_py/logic/CEC/native/dcec_parsing.py",
    "ipfs_datasets_py/logic/CEC/native/dcec_prototypes.py",
    "ipfs_datasets_py/logic/TDFOL/tdfol_core.py",
    "ipfs_datasets_py/logic/TDFOL/tdfol_parser.py",
    "ipfs_datasets_py/logic/autoformal/corpus_contracts.py",
    "ipfs_datasets_py/logic/autoformal/corpus_source.py",
    "ipfs_datasets_py/logic/autoformal/family_qualification.py",
    "ipfs_datasets_py/logic/autoformal/legal_canonical_calendar.py",
    "ipfs_datasets_py/logic/autoformal/legal_canonical_qualified.py",
    "ipfs_datasets_py/logic/autoformal/legal_context_obligations.py",
    "ipfs_datasets_py/logic/autoformal/legal_family_routes.py",
    "ipfs_datasets_py/logic/autoformal/legal_official_document_views.py",
    "ipfs_datasets_py/logic/autoformal/legal_official_source_custody.py",
    "ipfs_datasets_py/logic/autoformal/legal_relational_norm_v1.py",
    "ipfs_datasets_py/logic/autoformal/legal_source_norm_scope_v1.py",
    "ipfs_datasets_py/logic/autoformal/legal_source_sampling.py",
    "ipfs_datasets_py/logic/autoformal/legal_source_typed_norm_join_v1.py",
    "ipfs_datasets_py/logic/autoformal/legal_statutory_context.py",
    "ipfs_datasets_py/logic/autoformal/legal_statutory_context_v2.py",
    "ipfs_datasets_py/logic/families/namespaces.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/native_family_lean_emitters.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/native_legal_qualified_lean.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/native_qualified_lean.py",
    "ipfs_datasets_py/logic/intent_ir/formalize/modal_projections.py",
    "ipfs_datasets_py/logic/ir_core/provenance.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_statement_scope.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_statement_scope_bridge.py",
    "ipfs_datasets_py/logic/parsers/legacy_modal.py",
    "ipfs_datasets_py/logic/syntax_core/ast.py",
    "ipfs_datasets_py/logic/syntax_core/contracts.py",
    "ipfs_datasets_py/logic/syntax_core/signatures.py",
    "ipfs_datasets_py/utils/cid_utils.py",
)
AUTHORITY = dict.fromkeys((
    "source_meaning_verified", "source_meaning_selected", "complete_norm_formalized",
    "review_performed", "governing_use_verified", "graph_admitted", "Lean_admitted",
    "proof_authority", "training_gold_qualified", "evaluation_gold_qualified",
    "model_promoted", "teacher_promoted", "execution_authority",
), False)


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical(value):
    return sha(wire(value))


def parse(raw):
    def pairs(entries):
        result = {}
        for key, value in entries:
            need(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def open_regular(path):
    path = Path(path)
    need(path.is_absolute() and path.name and ".." not in path.parts, "absolute original path required")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    parent = os.open("/", flags)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                       dir_fd=parent)
    finally:
        os.close(parent)


def checked(path, expected=None, expected_bytes=None, maximum=MAX_INPUT):
    fd = open_regular(path)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and 0 < before.st_size <= maximum, "bounded single-link regular file required")
        need(expected_bytes is None or before.st_size == expected_bytes, "original input length differs")
        chunks, count = [], 0
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
            count += len(block)
            need(count <= maximum, "file grew beyond bound")
        raw = b"".join(chunks)
        need(count == before.st_size and (expected is None or sha(raw) == expected)
             and fingerprint(os.fstat(fd)) == fingerprint(before), "original file bytes or identity changed")
        closing = open_regular(path)
        try:
            need(fingerprint(os.fstat(closing)) == fingerprint(before), "original file path substituted")
        finally:
            os.close(closing)
        return raw, fingerprint(before)
    finally:
        os.close(fd)


def original_paths():
    paths = {
        "join_manifest": JOIN_ROOT / "manifest.json",
        "scope_manifest": SCOPE_ROOT / "manifest.json",
        "statutory_manifest": STATUTORY_ROOT / "manifest.json",
        "join_implementation_receipt": JOIN_ROOT.parent / "implementation-receipt.json",
        "scope_implementation_receipt": SCOPE_ROOT.parent / "implementation-receipt.json",
        "relational_implementation_receipt": ARTIFACTS / "legal-corpus-relational-norm-20261015-01/implementation-receipt.json",
    }
    for section in ("7213", "7214"):
        for name, filename in (("html", "source.html"), ("sampling", "sampling-report.json"),
                               ("replay", "replay-inputs.json"), ("descriptor", "descriptor.json")):
            paths[section + "_" + name] = STATUTORY_ROOT / "sources" / section / filename
        for name, filename in (("scope_request", "request.json"), ("scope_declaration", "declaration.json"),
                               ("scope_report", "report.json")):
            paths[section + "_" + name] = SCOPE_ROOT / section / filename
    for alternative in ("A", "B"):
        for name, filename in (("typed_request", "typed-request.json"), ("typed_report", "typed-syntax-report.json"),
                               ("join_request", "join-request.json"), ("join_report", "join-report.json")):
            paths["7213" + alternative + "_" + name] = JOIN_ROOT / ("7213-" + alternative) / filename
    for name, filename in (("join_request", "join-request.json"), ("join_report", "join-report.json")):
        paths["7214pending_" + name] = JOIN_ROOT / "7214-source-only-pending" / filename
    return paths


class Exports:
    def __init__(self, path):
        self.path = Path(path)
        need(self.path.is_absolute() and self.path.name == "exports"
             and self.path.resolve(strict=True) == self.path, "native exports directory required")
        info = self.path.stat()
        need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
             and not list(self.path.iterdir()), "empty private0700 exports required")
        temporary = Path(os.environ.get("TMPDIR", ""))
        need(temporary.is_absolute() and temporary.resolve(strict=True).parent == self.path.parent
             and temporary.name == "tmp", "native attempt TMPDIR required")
        self.identity = fingerprint(info)[:5]
        self.rows, self.total = {}, 0

    def save(self, name, raw):
        need(Path(name).name == name and name not in self.rows
             and self.total + len(raw) <= MAX_OUTPUT, "exclusive bounded flat export required")
        fd = os.open(self.path / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        self.total += len(raw)
        self.rows[name] = {"path": name, "bytes": len(raw), "sha256": sha(raw)}
        return self.rows[name]

    def json(self, name, value):
        return self.save(name, wire(value) + b"\n")

    def verify(self):
        need(fingerprint(self.path.stat())[:5] == self.identity, "exports directory substituted")
        need({path.name for path in self.path.iterdir()} == set(self.rows), "unlisted export appeared")
        for row in self.rows.values():
            checked(self.path / row["path"], row["sha256"], row["bytes"], MAX_OUTPUT)
        fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def scope_projection(report):
    value = copy.deepcopy(report)
    value.pop("producer_pins")
    value.pop("report_sha256")
    return value


def typed_projection(report):
    value = copy.deepcopy(report)
    value.pop("producer_pins")
    value["native_fragment"].pop("producer_pins")
    return value


def join_projection(report):
    value = copy.deepcopy(report)
    value.pop("producer_pins")
    value["source_scope_report"] = scope_projection(value["source_scope_report"])
    for field in ("scope_report_full_canonical_sha256", "relational_report_full_canonical_sha256"):
        if value["input_pins"][field] is not None:
            value["input_pins"][field] = "explicit-current-producer-generation-commitment"
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-descriptor", required=True)
    parser.add_argument("--expected-input-descriptor-sha256", required=True)
    parser.add_argument("--output-directory", required=True)
    options = parser.parse_args()
    os.umask(0o077)
    raw_descriptor, descriptor_identity = checked(options.input_descriptor,
        options.expected_input_descriptor_sha256, maximum=64 * 1024)
    descriptor = parse(raw_descriptor)
    need(type(descriptor) is dict and set(descriptor) == {"schema", "inputs"}
         and descriptor["schema"] == "retained-source-typed-norm-join-inputs/v1", "closed original descriptor required")
    paths = original_paths()
    need(type(descriptor["inputs"]) is list and len(descriptor["inputs"]) == len(paths) == 30,
         "complete30 original inputs required")
    refs, identities, original_raw = {}, {}, {}
    for (name, path), row in zip(paths.items(), descriptor["inputs"], strict=True):
        need(type(row) is dict and set(row) == {"name", "path", "bytes", "sha256"}
             and row["name"] == name and row["path"] == str(path)
             and type(row["bytes"]) is int and row["bytes"] > 0, "closed fixed original input role required")
        need(type(row["sha256"]) is str and len(row["sha256"]) == 64
             and all(character in "0123456789abcdef" for character in row["sha256"]), "original SHA256 required")
        raw, identity = checked(path, row["sha256"], row["bytes"])
        refs[name] = {key: row[key] for key in ("path", "bytes", "sha256")}
        identities[name], original_raw[name] = identity, raw
    for name, expected in ANCHORS.items():
        need(refs[name]["sha256"] == expected, "immutable original manifest anchor differs")

    def value(name):
        return parse(original_raw[name])

    join_manifest, scope_manifest, statutory_manifest = (value(name) for name in ANCHORS)
    need(join_manifest["prior_scope_manifest"] == refs["scope_manifest"]
         and scope_manifest["prior_statutory_manifest"] == refs["statutory_manifest"], "original manifest ancestry differs")
    expected_refs = {}
    for row in join_manifest["files"] + join_manifest["original_inputs"] + scope_manifest["files"]:
        expected_refs[row["path"]] = {key: row[key] for key in ("path", "bytes", "sha256")}
    for row in scope_manifest["inputs"]:
        for pin in row["pins"]:
            expected_refs[pin["path"]] = {key: pin[key] for key in ("path", "bytes", "sha256")}
    for intake in statutory_manifest["original_source_intakes"]:
        for pin in intake["retained_files"].values():
            expected_refs[pin["path"]] = {key: pin[key] for key in ("path", "bytes", "sha256")}
    for name, ref in refs.items():
        if name not in {"join_manifest", "statutory_manifest", "join_implementation_receipt"}:
            need(expected_refs.get(ref["path"]) == ref, "selected original manifest reference differs: " + name)
    sources = {}
    for name in (*SOURCE_PATHS, "scripts/ops/legal_ir/probe_retained_typed_norm_join.py"):
        path = ROOT / name
        raw, identity = checked(path)
        sources[str(path)] = {"bytes": len(raw), "sha256": sha(raw), "identity": identity}

    def custody():
        _, identity = checked(options.input_descriptor, options.expected_input_descriptor_sha256,
                              len(raw_descriptor), 64 * 1024)
        need(identity == descriptor_identity, "input descriptor identity substituted")
        for name, ref in refs.items():
            _, identity = checked(ref["path"], ref["sha256"], ref["bytes"])
            need(identity == identities[name], "original input identity substituted: " + name)
        for path, ref in sources.items():
            _, identity = checked(path, ref["sha256"], ref["bytes"])
            need(identity == ref["identity"], "current selected producer substituted")

    checks, calls, refusals = [], [], []

    def passed(name):
        need(name not in checks, "duplicate named check")
        checks.append(name)

    def call(name, operation):
        custody()
        started = time.monotonic()
        try:
            return operation()
        finally:
            custody()
            calls.append({"operation": name, "seconds": time.monotonic() - started})

    def refusal(name, operation):
        try:
            call(name, operation)
        except ValueError as error:
            refusals.append({"name": name, "refused": True, "exception": type(error).__name__,
                             "message": str(error)[:512]})
            passed(name)
        else:
            raise AssertionError("required refusal returned a result: " + name)

    passed("original_manifest_chain_and_30_file_custody")
    exports = Exports(options.output_directory)
    exports.save("retained-input-descriptor.json", raw_descriptor)
    for name, raw in original_raw.items():
        exports.save("original-" + name + (".html" if name.endswith("_html") else ".json"), raw)
    forbidden = {"torch", "numpy", "transformers", "tensorflow", "symai", "requests", "huggingface_hub", "openai"}
    blocked = []

    class NoOptionalModels:
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in forbidden:
                blocked.append("import:" + fullname)
                raise AssertionError("optional model or network package import refused: " + fullname)
            return None

    def no_external_actions(event, arguments):
        if event in {"subprocess.Popen", "os.system", "os.fork", "os.posix_spawn", "socket.connect", "socket.getaddrinfo"}:
            blocked.append(event)
            raise AssertionError("process or network action refused: " + event)

    sys.meta_path.insert(0, NoOptionalModels())
    sys.addaudithook(no_external_actions)
    sys.path.insert(0, str(ROOT))
    prefix = "ipfs_datasets_py.logic.autoformal."
    owner_names = ("legal_source_norm_scope_v1", "legal_relational_norm_v1", "legal_source_typed_norm_join_v1")
    owners = call("import_current_public_owners", lambda: [importlib.import_module(prefix + name) for name in owner_names])
    scope, relational, join = owners
    for name, owner in zip(owner_names, owners, strict=True):
        need(Path(owner.__file__).resolve() == ROOT / "ipfs_datasets_py/logic/autoformal" / (name + ".py"),
             "public owner imported from a different checkout")

    def check_report_producers(report, old_report):
        old = old_report["producer_pins"]
        expected = {}
        for path in old:
            relative = Path(path).relative_to(AUTHOR_ROOT)
            need(str(relative) in SOURCE_PATHS, "historical producer is outside the fixed declared source list")
            new_path = str(ROOT / relative)
            expected[new_path] = sources[new_path]["sha256"]
        need(report["producer_pins"] == expected, "current report producer map differs from fixed original owner roles")

    scopes, replay_inputs, scope_refs, populations, generation = {}, {}, {}, {}, []
    for section, expected_count, expected_length in (("7213", 26, 193), ("7214", 41, 163)):
        original = value(section + "_scope_report")
        replay = value(section + "_replay")
        need(set(replay) == {"descriptor", "expected_descriptor_sha256", "expected_raw_sha256",
                            "expected_raw_bytes", "expected_sampling_report_sha256"}, "original replay shape differs")
        need(replay["descriptor"] == value(section + "_descriptor"), "independent original acquisition descriptor differs")
        raw_html = original_raw[section + "_html"]
        need(replay["expected_raw_sha256"] == sha(raw_html) and replay["expected_raw_bytes"] == len(raw_html), "original raw source pins differ")
        need(replay["expected_descriptor_sha256"] == canonical(replay["descriptor"]), "original descriptor canonical commitment differs")
        sampled = value(section + "_sampling")
        need(canonical(sampled) == replay["expected_sampling_report_sha256"], "original complete sampling commitment differs")
        units = [row for row in sampled["records"] if row["schema"] == "legal-source-structured-sample-unit/v1"]
        need(len(units) == expected_count and sum(row["candidate_input"] for row in units) == 1,
             "complete original source-unit population differs")
        populations[section] = {"source_units": len(units), "candidate_statute_paragraphs": 1,
                               "retained_controls": len(units) - 1}
        replay = {**replay, "selected_unit_ref": original["input_pins"]["selected_unit_ref"],
            "sampling_report": sampled, "raw_html": raw_html,
            "scope_request_raw": original_raw[section + "_scope_request"],
            "scope_declaration_raw": original_raw[section + "_scope_declaration"],
            "expected_scope_request_sha256": refs[section + "_scope_request"]["sha256"],
            "expected_scope_declaration_sha256": refs[section + "_scope_declaration"]["sha256"]}
        fresh = call("prepare_current_scope_" + section, lambda replay=replay: scope.prepare_sampled_norm_scope_v1(**replay))
        fresh_sha = call("hash_current_scope_" + section, lambda fresh=fresh: scope.sampled_norm_scope_report_sha256(fresh))
        need(fresh_sha == canonical(fresh), "full scope canonical commitment differs")
        call("validate_current_scope_" + section, lambda fresh=fresh, replay=replay, fresh_sha=fresh_sha:
            scope.validate_sampled_norm_scope_v1(fresh, expected_report_sha256=fresh_sha, **replay))
        check_report_producers(fresh, original)
        need(wire(scope_projection(fresh)) == wire(scope_projection(original)), "current scope changed more than producer generation")
        need(fresh_sha != canonical(original), "new root scope report must retain its distinct producer generation")
        need(len(fresh["scope_request"]["source_text"]) == expected_length and len(fresh["anchor_mappings"]) == 11
             and len(fresh["scope_declaration"]["unresolved"]) == 6
             and len(fresh["source_context_packet"]["dependency_slots"]) == 6, "original complete paragraph, anchors, issues or context differ")
        scopes[section], replay_inputs[section], scope_refs[section] = fresh, replay, fresh_sha
        exports.json(section + "-current-scope-report.json", fresh)
        generation.append({"kind": "scope", "section": section, "original_file": refs[section + "_scope_report"],
            "original_full_canonical_sha256": canonical(original), "current_full_canonical_sha256": fresh_sha,
            "comparison_excludes_only": ["/producer_pins", "/report_sha256"], "all_remaining_fields_equal": True})
    passed("two_complete_original_populations_67_units_65_controls")
    passed("current_scopes_preserve_exact_paragraphs_22_anchors_12_issues_and_open_context")

    typed, typed_refs = {}, {}
    for alternative in ("A", "B"):
        name = "7213" + alternative
        raw = original_raw[name + "_typed_request"]
        fresh = call("prepare_current_typed_" + alternative, lambda raw=raw, name=name:
            relational.prepare_relational_norm_v1(raw, expected_request_sha256=refs[name + "_typed_request"]["sha256"]))
        full_sha = call("hash_current_typed_" + alternative, lambda fresh=fresh: relational.relational_norm_report_sha256(fresh))
        validated = call("validate_current_typed_" + alternative, lambda fresh=fresh, raw=raw, name=name, full_sha=full_sha:
            relational.validate_relational_norm_v1(fresh, raw,
                expected_request_sha256=refs[name + "_typed_request"]["sha256"], expected_report_sha256=full_sha))
        need(validated == fresh and full_sha == canonical(fresh), "current typed public replay differs")
        original = value(name + "_typed_report")
        check_report_producers(fresh, original)
        need(wire(typed_projection(fresh)) == wire(typed_projection(original)), "current syntax changed more than producer generation")
        need(full_sha != canonical(original) and fresh["source_binding"] is None and fresh["source_bound"] is False
             and fresh["native_fragment"]["exact_native_ast_roundtrip"] is True,
             "external typed syntax contract or current generation differs")
        typed[alternative], typed_refs[alternative] = fresh, full_sha
        exports.json(name + "-current-typed-report.json", fresh)
        generation.append({"kind": "typed", "alternative": alternative, "original_file": refs[name + "_typed_report"],
            "original_full_canonical_sha256": canonical(original), "current_full_canonical_sha256": full_sha,
            "comparison_excludes_only": ["/producer_pins", "/native_fragment/producer_pins"], "all_remaining_fields_equal": True})
    passed("original_typed_requests_preserve_native_ast_and_generated_text_only")
    need(typed["A"]["native_formula"] != typed["B"]["native_formula"], "competing original modal placements collapsed")

    joined, join_kwargs, report_refs = {}, {}, []
    for section, alternative, role in (("7213", "A", "7213A"), ("7213", "B", "7213B"), ("7214", None, "7214pending")):
        fresh_typed = typed.get(alternative)
        raw = original_raw[role + "_join_request"]
        kwargs = {"expected_join_request_sha256": refs[role + "_join_request"]["sha256"],
            "expected_scope_report_sha256": scope_refs[section],
            "expected_relational_report_sha256": typed_refs.get(alternative), "scope_replay_inputs": replay_inputs[section],
            "relational_request_raw": original_raw[role + "_typed_request"] if alternative else None,
            "expected_relational_request_sha256": refs[role + "_typed_request"]["sha256"] if alternative else None}
        fresh = call("prepare_current_join_" + role, lambda section=section, fresh_typed=fresh_typed, raw=raw, kwargs=kwargs:
            join.prepare_source_typed_norm_join_v1(scopes[section], fresh_typed, raw, **kwargs))
        full_sha = call("hash_current_join_" + role, lambda fresh=fresh: join.source_typed_norm_join_sha256(fresh))
        validated = call("validate_current_join_" + role, lambda fresh=fresh, section=section, fresh_typed=fresh_typed,
                         raw=raw, full_sha=full_sha, kwargs=kwargs:
            join.validate_source_typed_norm_join_v1(fresh, scopes[section], fresh_typed, raw,
                                                  expected_report_sha256=full_sha, **kwargs))
        original = value(role + "_join_report")
        need(validated == fresh and full_sha == canonical(fresh), "current join public replay differs")
        check_report_producers(fresh, original)
        need(wire(join_projection(fresh)) == wire(join_projection(original)), "current join changed more than explicit producer-generation commitments")
        need(full_sha != canonical(original) and fresh["original_unresolved"] == original["original_unresolved"],
             "original unresolved issues or current report identity differ")
        need(fresh["provenance_ledger"] == original["provenance_ledger"], "original ordered provenance rows changed")
        if alternative:
            arguments = [row for row in fresh["provenance_ledger"] if "predicate_argument" in row]
            need(len(fresh["provenance_ledger"]) == 19 and len(arguments) == 6
                 and all(row["binding_quantifier"]["variable_name"] == row["variable_name"] for row in arguments)
                 and len(fresh["introduced_unresolved"]) == 1, "argument, binder, node or introduced-issue accounting differs")
        else:
            need(fresh["typed_candidate"] is None and fresh["provenance_ledger"] == []
                 and fresh["introduced_unresolved"] == [], "pending source acquired fabricated typed content")
        need(all(flag is False for flag in fresh["authority"].values())
             and fresh["training_mask"] == fresh["evaluation_gold_mask"] == 0
             and all(mask == 0 for mask in fresh["masks"].values()), "correspondence authority or mask changed")
        need(all(fresh[field] is None for field in ("formal_norm_ast", "lowered_IR", "native_output_for_source", "graph", "lookup", "governing_use"))
             and all(fresh[field] == 0 for field in ("human_reviews", "signatures_constructed", "admissions", "model_calls", "training_calls", "native_processes")),
             "partial correspondence acquired unsupported output or action")
        joined[role], join_kwargs[role] = fresh, kwargs
        reference = exports.json(role + "-current-join-report.json", fresh)
        report_refs.append({"case": role, "report": reference, "full_canonical_sha256": full_sha,
            "typed_provenance_rows": len(fresh["provenance_ledger"]), "typed_candidate_present": alternative is not None})
        generation.append({"kind": "join", "case": role, "original_file": refs[role + "_join_report"],
            "original_full_canonical_sha256": canonical(original), "current_full_canonical_sha256": full_sha,
            "comparison_excludes_only": ["/producer_pins", "/source_scope_report/producer_pins", "/source_scope_report/report_sha256",
                "/input_pins/scope_report_full_canonical_sha256", "/input_pins/relational_report_full_canonical_sha256"],
            "all_remaining_fields_equal": True})
    passed("two_partial_hypotheses_preserve_38_provenance_entries_12_argument_occurrences")
    need(joined["7213A"]["source_custody"] == joined["7213B"]["source_custody"], "alternatives lost shared physical custody")
    passed("competing_alternatives_share_one_physical_7213_paragraph")
    passed("7214_stays_source_only_pending_without_typed_target")
    passed("all_source_meaning_review_gold_build_and_model_authority_stays_false")
    exports.json("producer-generation-comparison.json", {"schema": "retained-typed-norm-producer-comparison/v1",
        "original_root": str(AUTHOR_ROOT), "current_root": str(ROOT), "comparisons": generation,
        "original_reports_rewritten": False, "current_reports_are_new_producer_generation": True,
        "comparison_projection_is_not_an_authenticated_original_or_runtime_adapter": True})
    passed("new_current_root_generation_has_explicit_original_lineage")

    for role, section, alternative in (("7213A", "7213", "A"), ("7213B", "7213", "B"), ("7214pending", "7214", None)):
        saved = parse(checked(exports.path / (role + "-current-join-report.json"),
                              exports.rows[role + "-current-join-report.json"]["sha256"],
                              exports.rows[role + "-current-join-report.json"]["bytes"], MAX_OUTPUT)[0])
        regenerated = call("saved_byte_same_process_join_replay_" + role, lambda saved=saved, section=section,
                           alternative=alternative, role=role:
            join.validate_source_typed_norm_join_v1(saved, scopes[section], typed.get(alternative),
                original_raw[role + "_join_request"], expected_report_sha256=canonical(saved), **join_kwargs[role]))
        need(wire(regenerated) == wire(joined[role]), "saved-byte current join replay differs")
    passed("saved_byte_public_replay_same_process")

    base_kwargs = join_kwargs["7213A"]
    refusal("refuse_wrong_independent_join_request_pin", lambda:
        join.prepare_source_typed_norm_join_v1(scopes["7213"], typed["A"], original_raw["7213A_join_request"],
            **{**base_kwargs, "expected_join_request_sha256": "0" * 64}))
    damaged_source = {**replay_inputs["7213"], "raw_html": original_raw["7213_html"] + b" "}
    refusal("refuse_changed_original_source_bytes", lambda: scope.prepare_sampled_norm_scope_v1(**damaged_source))
    shortened_request = value("7213_scope_request")
    shortened_request["source_text"] = shortened_request["source_text"][:-1]
    shortened_raw = wire(shortened_request)
    shortened_replay = {**replay_inputs["7213"], "scope_request_raw": shortened_raw,
                        "expected_scope_request_sha256": sha(shortened_raw)}
    refusal("refuse_resealed_shortened_source_request", lambda: scope.prepare_sampled_norm_scope_v1(**shortened_replay))
    incomplete_join = value("7213A_join_request")
    incomplete_join["node_correspondences"].pop()
    incomplete_raw = wire(incomplete_join)
    refusal("refuse_resealed_missing_typed_node_correspondence", lambda:
        join.prepare_source_typed_norm_join_v1(scopes["7213"], typed["A"], incomplete_raw,
            **{**base_kwargs, "expected_join_request_sha256": sha(incomplete_raw)}))
    refusal("refuse_other_original_modal_alternative_as_same_typed_report", lambda:
        join.prepare_source_typed_norm_join_v1(scopes["7213"], typed["A"], original_raw["7213A_join_request"],
            **{**base_kwargs, "relational_request_raw": original_raw["7213B_typed_request"],
               "expected_relational_request_sha256": refs["7213B_typed_request"]["sha256"]}))
    escalated = copy.deepcopy(joined["7213A"])
    escalated["training_mask"] = 1
    refusal("refuse_resealed_training_mask_escalation", lambda:
        join.validate_source_typed_norm_join_v1(escalated, scopes["7213"], typed["A"], original_raw["7213A_join_request"],
            expected_report_sha256=canonical(escalated), **base_kwargs))
    omitted_issue = copy.deepcopy(scopes["7213"])
    omitted_issue["scope_declaration"]["unresolved"].pop()
    refusal("refuse_resealed_omission_of_original_unresolved_issue", lambda:
        join.prepare_source_typed_norm_join_v1(omitted_issue, typed["A"], original_raw["7213A_join_request"],
            **{**base_kwargs, "expected_scope_report_sha256": canonical(omitted_issue)}))
    refusal("refuse_partial_typed_inputs_for_pending_7214", lambda:
        join.prepare_source_typed_norm_join_v1(scopes["7214"], typed["A"], original_raw["7214pending_join_request"],
                                             **join_kwargs["7214pending"]))
    need(len(refusals) == 8, "all eight negative controls required")
    exports.json("refusal-controls.json", {"schema": "retained-typed-norm-refusals/v1", "controls": refusals,
        "originals_modified": False, "semantic_targets_created": False})
    custody()
    passed("original_assets_and_current_producer_bytes_unchanged_at_close")
    need(not blocked and not forbidden.intersection(sys.modules), "unexpected optional import or external action")
    exports.verify()
    receipt = {"schema": SCHEMA, "selected_check": SELECTED_CHECK, "all_checks_passed": True,
        "input_descriptor_sha256": options.expected_input_descriptor_sha256, "original_inputs": refs,
        "producer_sources": {path: {key: row[key] for key in ("bytes", "sha256")} for path, row in sources.items()},
        "source_repository": str(ROOT), "named_checks": checks, "named_check_count": len(checks),
        "refusal_count": len(refusals), "public_operation_calls": calls,
        "source_populations": populations, "source_unit_count": 67, "retained_control_count": 65,
        "distinct_physical_selected_paragraphs": 2, "partial_typed_hypotheses": 2, "source_only_pending_cases": 1,
        "typed_provenance_row_entries": 38, "predicate_argument_row_entries": 12,
        "original_unresolved_issues_distinct": 12, "original_open_context_slots_distinct": 12,
        "alternative_entries_are_not_independent_examples": True, "case_reports": report_refs,
        "reports_are_new_current_root_generations": True, "historical_reports_or_inputs_rewritten": False,
        "same_process_saved_byte_replay": True, "new_process_cold_replay": False,
        "whole_627_source_packet_replayed": False, "historical_101_560_units_replayed": False,
        "organizer_team_exposed_to_original_hypotheses": True, "independent_holdout": False,
        "model_calls": 0, "encoder_calls": 0, "training_calls": 0, "native_builds": 0,
        "solver_or_Lean_process_calls": 0, "human_reviews": 0, "signatures_or_keys_created": 0,
        "accepted_meanings": 0, "accepted_governing_use_edges": 0,
        "python_native_parser_and_generated_Lean_text_exercised": True,
        "authority": AUTHORITY, "training_mask": 0, "evaluation_gold_mask": 0,
        "blocked_external_or_optional_attempts": blocked, "source_cohort_is_complete_import_closure": False,
        "output_limit_bytes": MAX_OUTPUT, "outputs_before_receipt": list(exports.rows.values()),
        "limits": ["Actual source custody plus caller-authored partial hypotheses; no accepted meaning or independent review.",
            "The six context slots and named unresolved issues are not exhaustive legal dependency or ambiguity inventories.",
            "Relational source_binding stays null; generated syntax text is not statutory native output or a Lean build.",
            "Two alternative envelopes share one physical paragraph and cannot be independent training/evaluation cases.",
            "Original historical reports stay under their original absolute producer paths; comparison projections do not rewrite them.",
            "Only selected two-page populations are replayed; the historical627-unit packet remains separate metadata."]}
    receipt_ref = exports.json("probe-receipt.json", receipt)
    index_ref = exports.json("file-index.json", {"schema": "retained-typed-norm-file-index/v1",
        "files": list(exports.rows.values()), "self_file": "file-index.json",
        "closed_export_names": sorted([*exports.rows, "file-index.json"]),
        "listed_bytes_excluding_self": exports.total, "aggregate_byte_limit": MAX_OUTPUT})
    exports.verify()
    custody()
    print(json.dumps({"schema": SCHEMA, "selected_check": SELECTED_CHECK, "all_checks_passed": True,
        "receipt": receipt_ref, "file_index": index_ref, "export_files": len(exports.rows),
        "export_bytes": exports.total, "named_checks": len(checks), "refusals": len(refusals),
        "physical_paragraphs": 2, "typed_hypotheses": 2, "source_only_pending": 1,
        "authority": AUTHORITY, "training_mask": 0, "evaluation_gold_mask": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
