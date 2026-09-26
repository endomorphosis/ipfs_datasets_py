"""Immutable campaign membership over bounded embedding-production receipts.

The root accounts for every eligible source input, including unattempted inputs
and physical aliases. Leaf provenance remains unchanged. Metadata-only loading
does not reverify leaf/source files; full closure and selected-record checks are
explicit operations. Declared native execution is not authenticated inference,
and this codec grants neither training-job nor Lean admission authority.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from types import MappingProxyType

from . import autoencoder_embedding_production as production
from . import autoencoder_uscode_import as importer
from .autoencoder_source_partitions import SourcePartitions
from .autoencoder_corpus_index import SPLITS, _freeze
from .autoencoder_uscode_inventory import _fsync_directory


SCHEMA_VERSION = "autoencoder-embedding-receipt-set-v1"
STATUSES = ("unattempted", *production.STATUSES)
_FIELDS = {"schema_version", "source_partitions", "profile", "members", "inputs"}
_INPUT_FIELDS = {"input_id", "receipt_sha256", "result_index", "status"}


class ReceiptSetError(ValueError):
    """Invalid, incomplete or ambiguously owned producer membership."""


@dataclass(frozen=True)
class ReceiptSetLimits:
    max_receipts: int = 1024
    max_inputs: int = 65536
    max_root_bytes: int = 64 * 1024**2
    max_total_receipt_bytes: int = 4 * 1024**3

    def __post_init__(self):
        for name, bound in (("max_receipts", 1024), ("max_inputs", 65536),
                            ("max_root_bytes", 64 * 1024**2), ("max_total_receipt_bytes", 4 * 1024**3)):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= bound:
                raise ReceiptSetError(f"{name} exceeds receipt-set bounds")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    try:
        return production._canonical(value)
    except (ValueError, TypeError) as exc:
        raise ReceiptSetError("invalid canonical receipt-set JSON") from exc


def _keys(value, fields, label):
    try:
        return production._keys(value, fields, label)
    except (ValueError, TypeError) as exc:
        raise ReceiptSetError("invalid " + label) from exc


def _ref(value, maximum=production.MAX_BYTES):
    value = _keys(value, {"sha256", "bytes"}, "artifact reference")
    try:
        production._digest(value["sha256"], "artifact SHA-256")
        production._integer(value["bytes"], "artifact bytes", 1, maximum)
    except (ValueError, TypeError) as exc:
        raise ReceiptSetError("invalid artifact reference") from exc
    return value


def _profile(value):
    value = _keys(value, {"model", "execution", "model_assets", "producer"}, "producer profile")
    try:
        model = _keys(value["model"], {"model_id", "revision", "dimension"}, "model")
        if (model != {"model_id": production.MODEL_ID, "revision": production.MODEL_REVISION,
                      "dimension": production.DIMENSION} or type(model["dimension"]) is not int):
            raise ReceiptSetError("unqualified producer model")
        production._execution(value["execution"])
        production._assets(value["model_assets"])
        production._producer(value["producer"])
    except (ValueError, TypeError, KeyError) as exc:
        raise ReceiptSetError("invalid producer profile") from exc
    return value


def _partitions(value):
    if type(value) is not SourcePartitions:
        raise ReceiptSetError("verified source partitions required")
    try:
        return SourcePartitions(value.to_bytes(), value.inventory, value.limits)
    except (ValueError, TypeError) as exc:
        raise ReceiptSetError("invalid source partitions") from exc


def _aliases(partitions, limits):
    aliases = {}
    for split in SPLITS:
        for entry in partitions.entry_cids_for(split, require_nonempty=False):
            binding = partitions.binding_for(entry)
            aliases.setdefault(binding["input_id"], []).append(entry)
    if not 1 <= len(aliases) <= limits.max_inputs:
        raise ReceiptSetError("eligible input universe exceeds receipt-set bound")
    return aliases


def _descriptors(artifacts, limits):
    if type(limits) is not ReceiptSetLimits or type(artifacts) not in (list, tuple) or not 1 <= len(artifacts) <= limits.max_receipts:
        raise ReceiptSetError("receipt descriptor count exceeds bound")
    refs = [_ref(item) for item in artifacts]
    if len({item["sha256"] for item in refs}) != len(refs):
        raise ReceiptSetError("duplicate receipt identity")
    if sum(item["bytes"] for item in refs) > limits.max_total_receipt_bytes:
        raise ReceiptSetError("declared receipt bytes exceed aggregate bound")
    return sorted(refs, key=lambda item: item["sha256"])


def _load_member(ref, resolver):
    if not callable(resolver):
        raise ReceiptSetError("receipt resolver required")
    try:
        return production.load_embedding_production_receipt(resolver(dict(ref)),
            expected_sha256=ref["sha256"], expected_size_bytes=ref["bytes"])
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise ReceiptSetError("receipt leaf verification failed") from exc


def _facts(receipt):
    data = receipt.to_dict()
    profile = {key: data[key] for key in ("model", "execution", "model_assets", "producer")}
    rows = [(row["input_id"], row["status"]) for row in data["results"]]
    sources = [item["source"]["artifact"] for item, row in zip(data["inputs"], data["results"])
               if row["status"] != "missing_input"]
    return profile, rows, sources


def _add_sources(target, sources):
    for ref in sources:
        if target.setdefault(ref["sha256"], dict(ref)) != ref:
            raise ReceiptSetError("same source digest has inconsistent byte sizes")


def _rehash(refs, resolver, label):
    if not callable(resolver):
        raise ReceiptSetError(label + " resolver required")
    try:
        for ref in refs:
            with importer._verified_file(Path(resolver(dict(ref))).absolute(), ref, production.MAX_BYTES):
                pass
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise ReceiptSetError(label + " changed before closure") from exc


def _captured_resolver(resolver):
    """Resolve each exact reference once, then recheck the captured local path.

    Final closure reads must not invoke arbitrary callbacks after earlier files
    were checked. File hashes are still verified afresh; this caches paths only.
    """
    if not callable(resolver):
        raise ReceiptSetError("artifact resolver required")
    captured = {}

    def resolve(value):
        ref = _ref(value)
        key = ref["sha256"]
        if key not in captured:
            if len(captured) >= 65536:
                raise ReceiptSetError("resolved artifact count exceeds receipt-set input bound")
            captured[key] = (ref, Path(resolver(dict(ref))).absolute())
        expected, path = captured[key]
        if ref != expected:
            raise ReceiptSetError("same resolved digest has inconsistent byte sizes")
        return path

    return resolve


@dataclass(frozen=True)
class EmbeddingReceiptSet:
    _raw: bytes
    partitions: SourcePartitions = field(repr=False, compare=False)
    limits: ReceiptSetLimits = ReceiptSetLimits()
    _sha256: str = field(init=False, repr=False)
    _profile_raw: bytes = field(init=False, repr=False)
    _members: object = field(init=False, repr=False, compare=False)
    _member_inputs: object = field(init=False, repr=False, compare=False)
    _coverage: object = field(init=False, repr=False, compare=False)
    _aliases: object = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if (type(self.limits) is not ReceiptSetLimits or type(self._raw) is not bytes
                or not 1 <= len(self._raw) <= self.limits.max_root_bytes):
            raise ReceiptSetError("receipt-set root exceeds byte bound")
        try:
            data = _keys(production._parse(self._raw), _FIELDS, "receipt set")
            if data["schema_version"] != SCHEMA_VERSION or _json(data) != self._raw:
                raise ReceiptSetError("unsupported or noncanonical receipt-set root")
            partitions = _partitions(self.partitions)
            expected_partition = {"sha256": partitions.sha256, "bytes": len(partitions.to_bytes())}
            if _ref(data["source_partitions"]) != expected_partition:
                raise ReceiptSetError("receipt set differs from its exact source partitions")
            profile = _profile(data["profile"])
            aliases = _aliases(partitions, self.limits)
            members = data["members"]
            if type(members) is not list or not 1 <= len(members) <= self.limits.max_receipts:
                raise ReceiptSetError("receipt member count exceeds bound")
            refs, member_counts = [], {}
            for member in members:
                member = _keys(member, {"artifact", "input_count"}, "receipt member")
                ref = _ref(member["artifact"])
                production._integer(member["input_count"], "receipt input count", 1, production.MAX_RECORDS)
                refs.append(ref)
                member_counts[ref["sha256"]] = member["input_count"]
            if refs != _descriptors(refs, self.limits):
                raise ReceiptSetError("receipt members must have sorted unique identities")
            rows = data["inputs"]
            if type(rows) is not list or len(rows) != len(aliases):
                raise ReceiptSetError("root must account for every eligible unique input")
            covered, ordinals, ids = {}, {key: {} for key in member_counts}, []
            for row in rows:
                row = _keys(row, _INPUT_FIELDS, "input disposition")
                input_id, status = row["input_id"], row["status"]
                if type(input_id) is not str or input_id not in aliases or type(status) is not str or status not in STATUSES:
                    raise ReceiptSetError("foreign input or invalid input disposition")
                ids.append(input_id)
                if status == "unattempted":
                    if row["receipt_sha256"] is not None or row["result_index"] is not None:
                        raise ReceiptSetError("unattempted input cannot claim a producer result")
                else:
                    leaf, position = row["receipt_sha256"], row["result_index"]
                    if (type(leaf) is not str or leaf not in member_counts or type(position) is not int
                            or not 0 <= position < member_counts[leaf] or position in ordinals[leaf]):
                        raise ReceiptSetError("input result ownership is absent, ambiguous or out of range")
                    ordinals[leaf][position] = (input_id, status)
                covered[input_id] = row
            if ids != sorted(aliases):
                raise ReceiptSetError("input universe must be exhaustive, unique and sorted")
            if any(set(ordinals[key]) != set(range(count)) for key, count in member_counts.items()):
                raise ReceiptSetError("root omits a declared receipt result")
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            if isinstance(exc, ReceiptSetError):
                raise
            raise ReceiptSetError("invalid receipt-set metadata") from exc
        object.__setattr__(self, "partitions", partitions)
        object.__setattr__(self, "_sha256", _sha(self._raw))
        object.__setattr__(self, "_profile_raw", _json(profile))
        object.__setattr__(self, "_members", _freeze({ref["sha256"]: ref for ref in refs}))
        object.__setattr__(self, "_member_inputs", MappingProxyType({
            key: tuple(values[i] for i in range(member_counts[key])) for key, values in ordinals.items()}))
        object.__setattr__(self, "_coverage", _freeze(covered))
        object.__setattr__(self, "_aliases", MappingProxyType({key: tuple(values) for key, values in aliases.items()}))

    @property
    def sha256(self):
        return self._sha256

    def to_bytes(self):
        return self._raw

    def to_dict(self):
        return production._parse(self._raw)

    @property
    def native_execution_profile(self):
        return production._parse(self._profile_raw)["execution"]["kind"] == "native"

    def selected_leaf_artifacts(self, entry_cids):
        """Detached references for a bounded successful selection; no file I/O."""
        if (type(entry_cids) not in (list, tuple) or not 1 <= len(entry_cids) <= production.MAX_RECORDS
                or any(type(item) is not str for item in entry_cids)
                or len(set(entry_cids)) != len(entry_cids)):
            raise ReceiptSetError("leaf selection requires bounded unique source entries")
        selected = set()
        try:
            for entry in entry_cids:
                binding = self.binding_for(entry)
                if binding["status"] != "embedded":
                    raise ReceiptSetError("leaf selection requires embedded inputs")
                selected.add(binding["receipt_sha256"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ReceiptSetError("invalid source selection for leaf references") from exc
        return tuple(dict(self._members[key]) for key in sorted(selected))

    def summary(self):
        unique = Counter(row["status"] for row in self._coverage.values())
        physical = Counter()
        for key, entries in self._aliases.items():
            physical[self._coverage[key]["status"]] += len(entries)
        sources = self.partitions.verification_summary()
        return {"schema_version": SCHEMA_VERSION, "receipt_set_sha256": self.sha256,
                "receipt_set_bytes": len(self._raw), "source_partitions_sha256": self.partitions.sha256,
                "leaf_count": len(self._members), "declared_receipt_bytes": sum(ref["bytes"] for ref in self._members.values()),
                "physical_row_count": sources["physical_row_count"], "eligible_row_count": sources["eligible_row_count"],
                "excluded_row_count": sources["physical_row_count"] - sources["eligible_row_count"],
                "eligible_unique_input_count": len(self._coverage),
                "unique_status_counts": {status: unique[status] for status in STATUSES},
                "physical_status_counts": {status: physical[status] for status in STATUSES},
                "all_inputs_attempted": unique["unattempted"] == 0,
                "all_inputs_embedded": unique["embedded"] == len(self._coverage),
                "native_execution_profile": self.native_execution_profile,
                "current_leaf_bytes_verified": False, "current_source_bytes_verified": False,
                "runtime_cryptographically_attested": False, "source_authority_authenticated": False,
                "global_holdout_verified": False, "training_eligible": False, "admitted": False}

    def binding_for(self, entry_cid):
        binding = self.partitions.binding_for(entry_cid)
        return {**binding, **dict(self._coverage[binding["input_id"]])}

    def _checked_member(self, leaf, receipt_resolver):
        receipt = _load_member(self._members[leaf], receipt_resolver)
        profile, rows, sources = _facts(receipt)
        if _json(profile) != self._profile_raw or tuple(rows) != self._member_inputs[leaf]:
            raise ReceiptSetError("receipt profile or complete result membership differs from sealed root")
        return receipt, sources

    def verify_all(self, *, receipt_resolver, source_resolver):
        receipt_resolver = _captured_resolver(receipt_resolver)
        source_resolver = _captured_resolver(source_resolver)
        sources, verified = {}, 0
        for leaf in self._members:
            receipt, source_refs = self._checked_member(leaf, receipt_resolver)
            try:
                verified += receipt.validate_sources(source_resolver)["source_inputs_verified"]
            except (ValueError, TypeError, KeyError, OSError) as exc:
                raise ReceiptSetError("receipt source closure verification failed") from exc
            _add_sources(sources, source_refs)
        _rehash(self._members.values(), receipt_resolver, "receipt leaf")
        _rehash(sources.values(), source_resolver, "nonmissing source")
        return {**self.summary(), "all_leaf_bytes_verified": True, "current_leaf_bytes_verified": True,
                "nonmissing_source_inputs_verified": verified,
                "source_verification_scope": "all nonmissing declared receipt inputs; missing_input is not proof of absence"}

    def verify_records(self, records, *, entry_cids, operation, receipt_resolver, source_resolver):
        if not self.native_execution_profile:
            raise ReceiptSetError("injected fixture sets cannot verify native corpus records")
        try:
            self.partitions.authorize(operation, entry_cids)
            projection = self.partitions.project_records(records, entry_cids=entry_cids)
            receipt_resolver = _captured_resolver(receipt_resolver)
            source_resolver = _captured_resolver(source_resolver)
            selected, sources = {}, {}
            for record, row in zip(records, projection["records"]):
                coverage = self._coverage[row["input_id"]]
                provenance = row["record_summary"]["embedding_provenance"]
                leaf = coverage["receipt_sha256"]
                if (coverage["status"] != "embedded" or provenance is None
                        or provenance["artifact_sha256"] != leaf):
                    raise ReceiptSetError("record does not bind its selected successful leaf receipt")
                selected.setdefault(leaf, []).append(record)
                _add_sources(sources, [row["record_summary"]["source"]["artifact"]])
            verified = 0
            for leaf, subset in selected.items():
                receipt, _ = self._checked_member(leaf, receipt_resolver)
                checked = receipt.verify_records(subset, resolver=source_resolver)
                verified += checked["supplied_records_verified"]
            # Later resolver calls must not hide mutation of earlier verified
            # files. Keep the closure scoped to the requested records: other
            # inputs in a selected leaf need not be staged for this batch.
            _rehash((self._members[leaf] for leaf in selected), receipt_resolver, "selected receipt leaf")
            _rehash(sources.values(), source_resolver, "selected source")
        except (ValueError, TypeError, KeyError, OSError) as exc:
            if isinstance(exc, ReceiptSetError):
                raise
            raise ReceiptSetError("selected source/record/leaf verification failed") from exc
        return {"receipt_set_sha256": self.sha256, "source_projection": projection,
                "supplied_records_verified": verified, "selected_leaf_count": len(selected),
                "source_selectors_verified": True, "unselected_leaf_bytes_reverified": False,
                "unselected_source_bytes_reverified": False, "native_execution_profile": True,
                "runtime_cryptographically_attested": False, "global_holdout_verified": False,
                "training_eligible": False, "admitted": False}

    def save(self, destination):
        result = importer._write_exclusive(Path(destination), self._raw)
        _fsync_directory(Path(destination).parent)
        return result


def build_embedding_receipt_set(partitions, receipt_artifacts, *, receipt_resolver, source_resolver,
                                 limits=ReceiptSetLimits()):
    refs = _descriptors(receipt_artifacts, limits)
    partitions = _partitions(partitions)
    aliases = _aliases(partitions, limits)
    receipt_resolver = _captured_resolver(receipt_resolver)
    source_resolver = _captured_resolver(source_resolver)
    coverage = {key: {"input_id": key, "receipt_sha256": None, "result_index": None, "status": "unattempted"}
                for key in aliases}
    profile, members, sources = None, [], {}
    for ref in refs:
        receipt = _load_member(ref, receipt_resolver)
        current_profile, rows, source_refs = _facts(receipt)
        if profile is None:
            profile = current_profile
        elif _json(profile) != _json(current_profile):
            raise ReceiptSetError("receipt set requires one exact producer profile")
        for position, (input_id, status) in enumerate(rows):
            if input_id not in coverage:
                raise ReceiptSetError("receipt input is outside eligible frozen source membership")
            if coverage[input_id]["status"] != "unattempted":
                raise ReceiptSetError("overlapping producer inputs require an explicit retry choice before sealing")
            coverage[input_id] = {"input_id": input_id, "receipt_sha256": ref["sha256"],
                                  "result_index": position, "status": status}
        try:
            receipt.validate_sources(source_resolver)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            raise ReceiptSetError("receipt source closure verification failed") from exc
        _add_sources(sources, source_refs)
        members.append({"artifact": ref, "input_count": len(rows)})
    _rehash(refs, receipt_resolver, "receipt leaf")
    _rehash(sources.values(), source_resolver, "nonmissing source")
    raw = _json({"schema_version": SCHEMA_VERSION,
                 "source_partitions": {"sha256": partitions.sha256, "bytes": len(partitions.to_bytes())},
                 "profile": profile, "members": members,
                 "inputs": [coverage[key] for key in sorted(coverage)]})
    return EmbeddingReceiptSet(raw, partitions, limits)


def load_embedding_receipt_set(path, *, expected_sha256, partitions, expected_size_bytes=None,
                               limits=ReceiptSetLimits()):
    if type(limits) is not ReceiptSetLimits:
        raise ReceiptSetError("invalid receipt-set limits")
    try:
        production._digest(expected_sha256, "receipt set SHA-256")
        path = Path(path).absolute()
        size = path.lstat().st_size if expected_size_bytes is None else expected_size_bytes
        production._integer(size, "root bytes", 1, limits.max_root_bytes)
        with importer._verified_file(path, {"sha256": expected_sha256, "bytes": size}, limits.max_root_bytes) as stream:
            raw = stream.read(size + 1)
        return EmbeddingReceiptSet(raw, partitions, limits)
    except (ValueError, TypeError, OSError) as exc:
        if isinstance(exc, ReceiptSetError):
            raise
        raise ReceiptSetError("receipt-set artifact verification failed") from exc


__all__ = ["ReceiptSetError", "ReceiptSetLimits", "EmbeddingReceiptSet",
           "build_embedding_receipt_set", "load_embedding_receipt_set"]
