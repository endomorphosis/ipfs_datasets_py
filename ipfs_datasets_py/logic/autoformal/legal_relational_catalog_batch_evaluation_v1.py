"""Thin original-bound catalog batch facade over the fixed additive core.

The full selected population, raw observations and source commitments are
retained. This is conditional structural accounting, not generation authority.
Public import requires only the standard library.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat

SCHEMA = "legal-relational-catalog-token-batch-evaluation/v1"
PROFILE = "full-selected-catalog-token-output-diagnostics/v1"
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_SOURCE_SPECS = (
    ("ipfs_datasets_py.logic.autoformal.legal_relational_batch_core_v1",
     "logic/autoformal/legal_relational_batch_core_v1.py",
     "bbf3828ff6637e7848e7c6b689d07ae8d4825f7842472cc61ef516e79d8ca97c"),
)
_SELF_PATH = Path(__file__).absolute()
_ROOT = _SELF_PATH.parents[2]


class RelationalCatalogBatchEvaluationError(ValueError):
    """Facade source, original-bound replay or complete report refused."""


def _need(condition, message):
    if not condition:
        raise RelationalCatalogBatchEvaluationError(message)


def _snapshot(path):
    _need(type(path) is Path or isinstance(path, Path), "trusted fixed source path required")
    _need(path.is_absolute(), "absolute trusted fixed source required")
    for parent in (path.parent, *path.parent.parents):
        _need(stat.S_ISDIR(parent.lstat().st_mode), "unaliased trusted source parents required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_SOURCE_BYTES,
              "bounded regular trusted source required")
        raw = stream.read(MAX_SOURCE_BYTES + 1)
        after = os.fstat(stream.fileno())
    identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                              value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
    _need(len(raw) == before.st_size and identity(before) == identity(after) == identity(path.lstat()),
          "trusted source changed during snapshot")
    return hashlib.sha256(raw).hexdigest(), identity(before)

_SELF_SNAPSHOT = _snapshot(_SELF_PATH)
_SELF_PIN = _SELF_SNAPSHOT[0]


def _sources():
    snapshots = {str(_SELF_PATH): _snapshot(_SELF_PATH)}
    _need(snapshots[str(_SELF_PATH)] == _SELF_SNAPSHOT, "catalog facade changed since import")
    for _, relative, expected in _SOURCE_SPECS:
        path = _ROOT / relative
        snapshots[str(path)] = _snapshot(path)
        _need(snapshots[str(path)][0] == expected, "fixed accounting core source differs")
    return snapshots


@contextmanager
def _owner():
    initial = _sources()
    core, modules, closure = None, None, None

    def fence():
        _need(_sources() == initial, "catalog facade/core physical custody changed")
        if core is not None:
            _need(core._SELF_SNAPSHOT == initial[str(_ROOT / _SOURCE_SPECS[0][1])],
                  "accounting core import anchor differs")
            core._fixed_sources("catalog_tokens_v1")
        if closure is not None:
            _need(core._source_snapshots("catalog_tokens_v1", modules) == closure,
                  "catalog facade dependency custody changed")

    try:
        name, relative, _ = _SOURCE_SPECS[0]
        core = importlib.import_module(name)
        _need(type(core.__file__) is str and Path(core.__file__).absolute() == _ROOT / relative,
              "canonical accounting core module required")
        fence()

        def capture():
            nonlocal modules, closure
            modules = core._load_owners("catalog_tokens_v1")
            current = core._source_snapshots("catalog_tokens_v1", modules)
            _need(closure is None or closure == current, "catalog facade source closure changed")
            closure = current
            fence()

        yield core, capture, fence
    except BaseException as primary:
        try:
            fence()
        except BaseException:
            primary.add_note("Closing catalog facade custody check also refused; primary exception preserved.")
        raise
    else:
        fence()


def prepare_relational_catalog_batch_evaluation_v1(population_raw, references_raw, predictions_raw, *,
        expected_population_sha256, expected_references_sha256, expected_predictions_sha256):
    """Select only the fixed catalog profile, then add this facade's own custody."""
    with _owner() as (core, capture, fence):
        report = core.prepare_relational_batch_core_v1(population_raw, references_raw, predictions_raw,
            profile="catalog_tokens_v1", expected_population_sha256=expected_population_sha256,
            expected_references_sha256=expected_references_sha256, expected_predictions_sha256=expected_predictions_sha256)
        capture()
        core.relational_batch_core_sha256(report)
        _need(str(_SELF_PATH) not in report["producer_pins"], "core cannot depend on its catalog facade")
        report["producer_pins"][str(_SELF_PATH)] = _SELF_PIN
        raw = core._wire(report, MAX_OUTPUT_BYTES)
        fence()
        return json.loads(raw)


def relational_catalog_batch_evaluation_sha256(report):
    """Commit the complete bounded facade report; a self-address is not replay."""
    with _owner() as (core, capture, fence):
        offered = core._copy(report, MAX_OUTPUT_BYTES)
        _need(type(offered) is dict and offered.get("schema") == SCHEMA and offered.get("profile") == PROFILE
              and type(offered.get("producer_pins")) is dict
              and offered["producer_pins"].get(str(_SELF_PATH)) == _SELF_PIN,
              "complete closed catalog facade identity required")
        digest = core.relational_batch_core_sha256(offered)
        fence()
        return digest


def validate_relational_catalog_batch_evaluation_v1(report, population_raw, references_raw, predictions_raw, *,
        expected_evaluation_sha256, expected_population_sha256, expected_references_sha256, expected_predictions_sha256):
    """Replay all original inputs, every available reference and every eligible row."""
    with _owner() as (core, capture, fence):
        _need(core._is_sha(expected_evaluation_sha256), "independent complete evaluation SHA256 required")
        offered = core._copy(report, MAX_OUTPUT_BYTES)
        _need(relational_catalog_batch_evaluation_sha256(offered) == expected_evaluation_sha256,
              "independent catalog evaluation pin differs")
        original = core._wire(offered, MAX_OUTPUT_BYTES)
        regenerated = prepare_relational_catalog_batch_evaluation_v1(population_raw, references_raw, predictions_raw,
            expected_population_sha256=expected_population_sha256, expected_references_sha256=expected_references_sha256,
            expected_predictions_sha256=expected_predictions_sha256)
        capture()
        _need(original == core._wire(regenerated, MAX_OUTPUT_BYTES),
              "catalog evaluation differs from full original-bound regeneration")
        fence()
        return regenerated


__all__ = ["RelationalCatalogBatchEvaluationError", "prepare_relational_catalog_batch_evaluation_v1",
           "relational_catalog_batch_evaluation_sha256", "validate_relational_catalog_batch_evaluation_v1"]
