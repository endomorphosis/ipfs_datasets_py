"""Bounded v8 source-campaign verification before model construction.

Metadata roles authorize the entire batch before any selected source or producer
leaf is opened. Job descriptors supply paths; campaign artifacts supply only
identities. Verification establishes integrity, not native execution or proofs.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import os
import stat
import sys
import threading
from types import FunctionType

from .autoencoder_training_worker import (
    CAMPAIGN_SCHEMA_VERSION, MAX_CAMPAIGN_METADATA_BYTES, MAX_CORPUS_MANIFEST_BYTES,
    MAX_PRODUCED_RECORD_PROJECTION_BYTES, TrainingJobSpec, TrainingJobValidationError,
    _json_bytes, _parse_json,
)


def _reference(artifact):
    return {"sha256": artifact.sha256, "bytes": artifact.bytes}


def _load(loader, artifact, **kwargs):
    return loader(artifact.path, expected_sha256=artifact.sha256,
                  expected_size_bytes=artifact.bytes, **kwargs)


def _resolver(artifacts, expected, label):
    supplied = {(item.sha256, item.bytes) for item in artifacts}
    required = {(item["sha256"], item["bytes"]) for item in expected}
    if supplied != required or len(supplied) != len(artifacts):
        raise TrainingJobValidationError(f"selected campaign {label} differ from the exact projection closure")
    by_sha = {item.sha256: item for item in artifacts}

    def resolve(reference):
        item = by_sha.get(reference["sha256"])
        if item is None or item.bytes != reference["bytes"]:
            raise TrainingJobValidationError(f"selected campaign {label} missing from job binding")
        return Path(item.path)

    return resolve



def _scope_modules():
    # This deliberately bounded producer set is an operation-local drift guard,
    # not a full-package attestation and not another per-job source manifest.
    from . import autoencoder_corpus_index, autoencoder_corpus_manifest
    from . import autoencoder_embedding_production, autoencoder_embedding_receipt_set
    from . import autoencoder_produced_record_projection, autoencoder_source_partitions
    from . import autoencoder_uscode_import, autoencoder_uscode_inventory
    from . import autoencoder_training_worker, legal_ir_eval_splits
    return (sys.modules[__name__], autoencoder_uscode_inventory, autoencoder_source_partitions,
        autoencoder_embedding_receipt_set, autoencoder_produced_record_projection,
        autoencoder_corpus_manifest, autoencoder_corpus_index, autoencoder_embedding_production,
        autoencoder_uscode_import, autoencoder_training_worker, legal_ir_eval_splits)


def _scope_source_sha256(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise TrainingJobValidationError("campaign scope producer path contains aliases")
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        named = path.stat(follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 4 * 1024**2
                or identity(before) != identity(named) or path.resolve() != path):
            raise TrainingJobValidationError("campaign scope producer is not a bounded stable source file")
        digest, size = hashlib.sha256(), 0
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > before.st_size:
                raise TrainingJobValidationError("campaign scope producer source changed while hashing")
            digest.update(block)
        after = os.fstat(stream.fileno())
        named = path.stat(follow_symlinks=False)
        if (size != before.st_size or identity(before) != identity(after)
                or identity(before) != identity(named) or path.resolve() != path):
            raise TrainingJobValidationError("campaign scope producer source or path changed while hashing")
        return digest.hexdigest()


def _scope_function_identity(value):
    # Decorated loaders such as _verified_file retain their wrapped function.
    # Check that code too, not only contextlib's stable wrapper bytecode.
    chain, seen = [], set()
    while value is not None:
        if not isinstance(value, FunctionType) or id(value) in seen or len(chain) >= 8:
            raise TrainingJobValidationError("unsupported campaign scope producer wrapper chain")
        seen.add(id(value))
        chain.append((id(value), id(value.__code__), id(value.__defaults__),
            tuple(sorted((name, id(item)) for name, item in (value.__kwdefaults__ or {}).items()))))
        value = getattr(value, "__wrapped__", None)
    return tuple(chain)


def _scope_symbol_identity(value):
    if isinstance(value, FunctionType):
        return ("function", _scope_function_identity(value))
    if isinstance(value, (staticmethod, classmethod)):
        return ("method", id(value), _scope_function_identity(value.__func__))
    if isinstance(value, property):
        return ("property", id(value), tuple(_scope_function_identity(item) if item else None
                                            for item in (value.fget, value.fset, value.fdel)))
    if isinstance(value, type):
        return ("class", id(value), tuple(sorted((name, _scope_symbol_identity(item))
            for name, item in vars(value).items()
            if isinstance(item, (FunctionType, staticmethod, classmethod, property)))))
    raise TrainingJobValidationError("unsupported campaign scope producer symbol")


def _scope_code_identity():
    result = []
    for module in _scope_modules():
        path = Path(module.__file__)
        # Every module in this bounded set belongs to this optimizer package.
        # This never changes import resolution or retargets an editable install.
        if path.resolve().parent != Path(__file__).resolve().parent:
            raise TrainingJobValidationError("campaign scope producer loaded from another source tree")
        symbols = tuple(sorted((name, _scope_symbol_identity(value))
            for name, value in vars(module).items()
            if isinstance(value, FunctionType)
            or (isinstance(value, type) and value.__module__ == module.__name__)))
        result.append((module.__name__, id(module), str(path), _scope_source_sha256(path), symbols))
    return tuple(result)


def _root_decoded_fields(root):
    values = (root, root.partitions, root.partitions.inventory,
              root.limits, root.partitions.limits, root.partitions.inventory.limits)
    return tuple((value, type(value), tuple(vars(value).items())) for value in values)


@dataclass(frozen=True)
class _CampaignRootScope:
    """One lexical owner's decoded roots; never serialized or shared by jobs.

    Every use still hashes current root bytes. Only constructors are amortized;
    manifests, projections, roles and selected artifacts remain fresh per job.
    Frozen-field checks detect accidental internal mutation, not arbitrary
    hostile Python execution. The external audit owns whole-package provenance.
    """
    _owner: object
    _artifact_root: str = field(init=False, repr=False)
    _thread: object = field(init=False, repr=False)
    _token: object = field(default_factory=object, init=False, repr=False)
    _entered: bool = field(default=False, init=False, repr=False)
    _active: bool = field(default=False, init=False, repr=False)
    _code: tuple = field(default=(), init=False, repr=False)
    _bindings: tuple = field(default=(), init=False, repr=False)
    _root: object = field(default=None, init=False, repr=False)
    _decoded: tuple = field(default=(), init=False, repr=False)
    _limits: tuple = field(default=(), init=False, repr=False)
    _limit_fields: tuple = field(default=(), init=False, repr=False)
    _identity: tuple = field(default=(), init=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "_artifact_root", str(self._owner.artifact_root))
        object.__setattr__(self, "_thread", threading.current_thread())

    def __reduce__(self):
        raise TypeError("campaign root scopes cannot be serialized")

    def __enter__(self):
        if self._entered or threading.current_thread() is not self._thread:
            raise TrainingJobValidationError("campaign root scope can enter only once on its creating thread")
        object.__setattr__(self, "_entered", True)
        try:
            from .autoencoder_uscode_inventory import InventoryLimits
            from .autoencoder_source_partitions import SourcePartitionLimits
            from .autoencoder_embedding_receipt_set import ReceiptSetLimits
            limits = (InventoryLimits(), SourcePartitionLimits(), ReceiptSetLimits())
            object.__setattr__(self, "_limits", limits)
            object.__setattr__(self, "_limit_fields", tuple(
                (value, type(value), tuple(vars(value).items())) for value in limits))
            object.__setattr__(self, "_identity", (self._owner, self._artifact_root,
                self._thread, self._token, limits))
            object.__setattr__(self, "_code", _scope_code_identity())
            object.__setattr__(self, "_active", True)
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is None:
                self.check()
        finally:
            self.close()
        return False

    def close(self):
        object.__setattr__(self, "_active", False)
        for name, value in (("_root", None), ("_decoded", ()), ("_code", ()),
                            ("_limits", ()), ("_limit_fields", ())):
            object.__setattr__(self, name, value)

    def check(self, spec=None):
        try:
            if (not self._active or threading.current_thread() is not self._thread
                    or str(self._owner.artifact_root) != self._artifact_root):
                raise TrainingJobValidationError("campaign root scope expired or belongs to another owner/thread")
            if len(self._identity) != 5 or any(current is not original for current, original in zip(
                    (self._owner, self._artifact_root, self._thread, self._token, self._limits), self._identity)):
                raise TrainingJobValidationError("campaign root scope operation identity changed")
            if self._code != _scope_code_identity():
                raise TrainingJobValidationError("campaign root scope producer code changed")
            if any(type(value) is not expected or not _same_fields(value, fields)
                   for value, expected, fields in (*self._limit_fields, *self._decoded)):
                raise TrainingJobValidationError("campaign root scope decoded metadata or limits changed")
            if self._root is not None and (not self._decoded or self._root is not self._decoded[0][0]):
                raise TrainingJobValidationError("campaign root scope decoded root was replaced")
            if spec is not None and self._bindings and self._bindings != self._key(spec):
                raise TrainingJobValidationError("campaign root scope differs from exact job root paths or identities")
        except BaseException:
            self.close()
            raise

    def _key(self, spec):
        if type(spec) is not TrainingJobSpec or spec.schema_version != CAMPAIGN_SCHEMA_VERSION:
            raise TrainingJobValidationError("campaign root scope requires an exact v8 job")
        return tuple((value.path, value.sha256, value.bytes, MAX_CAMPAIGN_METADATA_BYTES)
            for value in (spec.source_inventory_artifact, spec.source_partitions_artifact,
                          spec.embedding_receipt_set_artifact))

    def roots_for(self, spec):
        self.check(spec)
        try:
            key = self._key(spec)
            if self._root is None:
                from .autoencoder_uscode_inventory import load_uscode_source_inventory
                from .autoencoder_source_partitions import load_source_partitions
                from .autoencoder_embedding_receipt_set import load_embedding_receipt_set
                inventory = _load(load_uscode_source_inventory, spec.source_inventory_artifact,
                                  limits=self._limits[0])
                partitions = _load(load_source_partitions, spec.source_partitions_artifact,
                                   inventory=inventory, limits=self._limits[1])
                root = _load(load_embedding_receipt_set, spec.embedding_receipt_set_artifact,
                             partitions=partitions, limits=self._limits[2])
                # Public constructors retain all nested checks. Keep only the
                # final root-owned graph, not the redundant initial copies.
                object.__setattr__(self, "_root", root)
                object.__setattr__(self, "_bindings", key)
                object.__setattr__(self, "_decoded", _root_decoded_fields(root))
            self.check(spec)
            from .autoencoder_uscode_import import _verified_file
            for path, digest, size, maximum in self._bindings:
                with _verified_file(Path(path), {"sha256": digest, "bytes": size}, maximum):
                    pass
            self.check(spec)
            return self._root.partitions.inventory, self._root.partitions, self._root
        except BaseException:
            self.close()
            raise


@contextmanager
def _root_scope_operation(root_scope, *, check_enter=True):
    if root_scope is not None:
        if type(root_scope) is not _CampaignRootScope:
            raise TrainingJobValidationError("an exact lexical campaign root scope is required")
        if check_enter:
            root_scope.check()
    try:
        yield
        if root_scope is not None:
            root_scope.check()
    except BaseException:
        if root_scope is not None:
            root_scope.close()
        raise


@dataclass(frozen=True)
class _PreparedUse:
    """One in-process operation, not a transferable verification authority."""
    spec_sha256: str
    thread_id: int
    metadata: tuple
    fields: tuple
    decoded: tuple
    consumed: bool = False
    scope_token: object = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class _PreparedCampaign:
    manifest: object
    partitions: object
    receipt_set: object
    projection: object
    _membership_raw: bytes
    _selected_raw: bytes
    leaf_resolver: object
    source_resolver: object
    _use: _PreparedUse = field(repr=False, compare=False)
    _scope: object = field(default=None, repr=False, compare=False)

    def __reduce__(self):
        raise TypeError("prepared campaign contexts cannot be serialized")

    @property
    def membership(self):
        return _parse_json(self._membership_raw)

    @property
    def selected(self):
        return _parse_json(self._selected_raw)


def _prepared_fields(prepared):
    return tuple((name, value) for name, value in vars(prepared).items() if name != "_use")


def _decoded_fields(prepared):
    # The codecs expose frozen dataclasses, bytes, tuples and mapping proxies.
    # Capture their immediate fields without traversing the campaign's rows or
    # decoding its JSON again. This also rejects ordinary dataclass replacement
    # and direct cached-field substitution in this trusted internal interface.
    objects = (prepared.manifest, prepared.partitions, prepared.partitions.inventory,
               prepared.receipt_set, prepared.receipt_set.partitions,
               prepared.receipt_set.partitions.inventory, prepared.projection)
    return tuple((value, tuple(vars(value).items())) for value in objects)


def _same_fields(value, original):
    return set(vars(value)) == {name for name, _ in original} and all(
        vars(value)[name] is item for name, item in original)


def _new_prepared(spec, manifest, partitions, receipt_set, projection, membership,
                  selected, leaf_resolver, source_resolver, *, scope=None):
    metadata = tuple((artifact.path, artifact.sha256, artifact.bytes, bound)
        for artifact, bound in (
            (spec.source_inventory_artifact, MAX_CAMPAIGN_METADATA_BYTES),
            (spec.source_partitions_artifact, MAX_CAMPAIGN_METADATA_BYTES),
            (spec.embedding_receipt_set_artifact, MAX_CAMPAIGN_METADATA_BYTES),
            (spec.produced_record_projection_artifact, MAX_PRODUCED_RECORD_PROJECTION_BYTES),
            (spec.corpus_manifest_artifact, MAX_CORPUS_MANIFEST_BYTES)))
    use = _PreparedUse(spec.canonical_sha256, threading.get_ident(), metadata, (), ())
    prepared = _PreparedCampaign(manifest, partitions, receipt_set, projection,
        _json_bytes(membership), _json_bytes(selected), leaf_resolver, source_resolver, use, scope)
    object.__setattr__(use, "scope_token", scope._token if scope is not None else None)
    object.__setattr__(use, "fields", _prepared_fields(prepared))
    object.__setattr__(use, "decoded", _decoded_fields(prepared))
    return prepared


def _claim_prepared(spec, prepared):
    if (type(spec) is not TrainingJobSpec or type(prepared) is not _PreparedCampaign
            or type(prepared._use) is not _PreparedUse):
        raise TrainingJobValidationError("an exact in-process prepared campaign is required")
    use = prepared._use
    if threading.get_ident() != use.thread_id:
        raise TrainingJobValidationError("prepared campaign belongs to another thread")
    if use.consumed:
        raise TrainingJobValidationError("prepared campaign has already been consumed")
    # Any same-thread attempt consumes the context, including mismatched jobs
    # and failures. Callers must preflight again instead of retrying stale state.
    object.__setattr__(use, "consumed", True)
    _verify_prepared_identity(spec, prepared, use)
    return use


def _verify_prepared_identity(spec, prepared, use):
    if (spec.canonical_sha256 != use.spec_sha256
            or len(vars(prepared)) != len(use.fields) + 1
            or any(vars(prepared).get(name) is not value for name, value in use.fields)
            or any(not _same_fields(value, original) for value, original in use.decoded)):
        raise TrainingJobValidationError("prepared campaign differs from its exact job or decoded metadata")
    if prepared._scope is not None:
        if (type(prepared._scope) is not _CampaignRootScope
                or prepared._scope._token is not use.scope_token):
            raise TrainingJobValidationError("prepared campaign has an invalid root scope")
        prepared._scope.check(spec)


def _verify_metadata_bytes(use):
    from .autoencoder_uscode_import import _verified_file

    # Bound checks and streaming digests only: do not parse these roots again.
    # Both passes re-open the exact spec paths, retaining existing no-follow and
    # regular-file checks. No descriptor or summary substitutes for current bytes.
    for path, digest, size, maximum in use.metadata:
        with _verified_file(Path(path), {"sha256": digest, "bytes": size}, maximum):
            pass


def preflight_campaign_job_inputs(spec):
    """Authorize metadata and budgets before opening any selected leaf/source.

    The returned context is private in-process state, not transport evidence.
    Callers that stage or hash selected artifacts must call this before that I/O.
    """
    return _preflight_campaign_job_inputs(spec)


def _preflight_campaign_job_inputs(spec, *, root_scope=None):
    with _root_scope_operation(root_scope):
        from .autoencoder_corpus_manifest import load_corpus_manifest
        from .autoencoder_corpus_index import _summary
        from .autoencoder_embedding_receipt_set import load_embedding_receipt_set
        from .autoencoder_produced_record_projection import load_produced_record_projection, _manifest as bounded_manifest
        from .autoencoder_source_partitions import load_source_partitions
        from .autoencoder_uscode_inventory import load_uscode_source_inventory

        if type(spec) is not TrainingJobSpec or spec.schema_version != CAMPAIGN_SCHEMA_VERSION:
            raise TrainingJobValidationError("source campaign verification requires the v8 job schema")
        try:
            if root_scope is None:
                inventory = _load(load_uscode_source_inventory, spec.source_inventory_artifact)
                partitions = _load(load_source_partitions, spec.source_partitions_artifact, inventory=inventory)
                receipt_set = _load(load_embedding_receipt_set, spec.embedding_receipt_set_artifact, partitions=partitions)
            else:
                if type(root_scope) is not _CampaignRootScope:
                    raise TrainingJobValidationError("an exact lexical campaign root scope is required")
                inventory, partitions, receipt_set = root_scope.roots_for(spec)
            # Constructor checks every training and validation role from metadata.
            # Both groups must be authorized before any source/leaf resolver runs.
            projection = _load(load_produced_record_projection, spec.produced_record_projection_artifact,
                               receipt_set=receipt_set)
            selected = projection.selected_artifacts()
            leaf_resolver = _resolver(spec.embedding_receipt_artifacts, selected["leaf_receipts"], "receipts")
            source_resolver = _resolver(spec.corpus_source_artifacts, selected["source_artifacts"], "sources")
            projection_metadata = projection.to_dict()
            if projection_metadata["corpus_manifest"] != _reference(spec.corpus_manifest_artifact):
                raise TrainingJobValidationError("corpus manifest differs from exact campaign projection binding")
            manifest = bounded_manifest(_load(load_corpus_manifest, spec.corpus_manifest_artifact), projection.limits)
            if (projection_metadata["dataset_snapshot_id"] != manifest.dataset_snapshot_id
                    or projection_metadata["split_snapshot_id"] != manifest.split_snapshot_id
                    or projection_metadata["training_record_ids"] != list(manifest._training_record_ids)
                    or projection_metadata["validation_record_ids"] != list(manifest._validation_record_ids)
                    or [row["record_summary"] for row in projection_metadata["records"]] != [_summary(row) for row in manifest.records]):
                raise TrainingJobValidationError("corpus manifest differs from exact projected snapshots, ordered roles or records")
            if {(ref["sha256"], ref["bytes"]) for ref in manifest.source_refs} != {
                    (ref["sha256"], ref["bytes"]) for ref in selected["source_artifacts"]}:
                raise TrainingJobValidationError("corpus manifest sources differ from exact campaign projection closure")
            membership = manifest.verify_job_records(spec.samples, spec.validation_samples,
                dataset_snapshot_id=spec.dataset_snapshot_id, split_snapshot_id=spec.split_snapshot_id)
            if (manifest.mode != "corpus" or set(manifest.language_counts) != {"en"}
                    or spec.variant.source_language != "en" or set(manifest.source_kind_counts) != {"us_code"}):
                raise TrainingJobValidationError("v8 requires corpus mode with the qualified English us_code frontend")
            return _new_prepared(spec, manifest, partitions, receipt_set, projection, membership,
                                 selected, leaf_resolver, source_resolver, scope=root_scope)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, UnicodeError) as exc:
            if type(root_scope) is _CampaignRootScope:
                root_scope.close()
            if isinstance(exc, TrainingJobValidationError):
                raise
            raise TrainingJobValidationError("source campaign input verification failed") from exc


def verify_campaign_job_inputs(spec):
    """Verify a v8 manifest against exact roots and its selected byte closure."""
    return _verify_prepared_campaign_job_inputs(spec, preflight_campaign_job_inputs(spec))


def _verify_prepared_campaign_job_inputs(spec, prepared):
    """Consume one exact preflight within its creating owner operation/thread.

    This private API avoids a second root decode. It retains fresh bounded root
    hashes on both sides of selected-byte verification and changes no wire data.
    A prepared context is never evidence for another job or a later operation.
    """
    # Recover only the originally captured scope for failure invalidation.
    # Looking at a replaced prepared._scope must not run guards before claim.
    scope = None
    if (type(prepared) is _PreparedCampaign and type(prepared._use) is _PreparedUse
            and type(prepared._use.fields) is tuple):
        for item in prepared._use.fields:
            if (type(item) is tuple and len(item) == 2 and type(item[0]) is str
                    and item[0] == "_scope" and type(item[1]) is _CampaignRootScope):
                scope = item[1]
                break
    try:
        use = _claim_prepared(spec, prepared)
    except BaseException:
        if scope is not None:
            scope.close()
        raise
    with _root_scope_operation(scope):
        try:
            _verify_metadata_bytes(use)
            verification = prepared.projection.verify_batch(prepared.manifest,
                receipt_resolver=prepared.leaf_resolver, source_resolver=prepared.source_resolver)
            source_summary = prepared.manifest.validate_sources(prepared.source_resolver)
            _verify_metadata_bytes(use)
            _verify_prepared_identity(spec, prepared, use)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, UnicodeError) as exc:
            if isinstance(exc, TrainingJobValidationError):
                raise
            raise TrainingJobValidationError("source campaign selected-byte verification failed") from exc
        return {**prepared.membership, "verification_mode": "manifest_source_bytes_source_campaign_and_record_projection",
                "dataset_and_split_identity_verified": True, "source_validation": source_summary,
                "frontend": "legacy_us_code", "global_holdout_verified": False,
                "source_campaign_verified": True,
                "source_campaign_verification": {
                    "source_inventory": _reference(spec.source_inventory_artifact),
                    "source_partitions": _reference(spec.source_partitions_artifact),
                    "embedding_receipt_set": _reference(spec.embedding_receipt_set_artifact),
                    "source_partition_verification": prepared.partitions.verification_summary(),
                    "receipt_set_verification": prepared.receipt_set.summary()},
                "produced_record_projection_verified": True,
                "produced_record_projection_verification": {**verification, "selected_artifacts": prepared.selected}}
