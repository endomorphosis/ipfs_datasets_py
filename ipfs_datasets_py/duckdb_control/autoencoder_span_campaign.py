"""Fenced, multi-host span assignments on the existing registry owner.

Only the owner opens DuckDB. Scoped Quack clients exchange bounded assignments,
leases, and immutable Hub report references. A report is pending evidence until
an owner-supplied verifier downloads, replays and checks it for the campaign's
immutable purpose. Feature pretraining never qualifies or admits a span. No network or
training starts at import. Native Quack remains loopback; remote hosts use an
explicit private tunnel. This module never weakens qualification or admits law.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
import re
import tempfile
from typing import Any, Mapping
import uuid

from .autoencoder_registry import AutoencoderRegistry, RegistryError, _artifact, _json, _token
from .autoencoder_quack import RegistryTransportClient, _TransientQuackGateway, SCHEMA as WIRE_SCHEMA
from .autoencoder_quack_wire import _request as encode_request, parse_request
from .contracts import canonical_json_bytes

SCHEMA = "autoencoder-shared-span-campaign-v1"
COMMANDS = frozenset({"ClaimSpan", "RenewSpan", "ReportSpan", "ReadSpan", "ReadCampaign", "AcknowledgeWeights"})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_MAX_RECORD = 24 * 1024
_MAX_OBSERVATION = 8 * 1024 * 1024
_FEATURE_PURPOSE = "feature_pretraining"


class SpanCampaignError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise SpanCampaignError(message)


def _digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _copy(value, bound=48 * 1024):
    # The shared control codec has a 1 MiB cap; complete census observations
    # may be larger, but only these locally staged bytes use the 8 MiB bound.
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SpanCampaignError("campaign value must be ordinary finite JSON") from exc
    _require(len(raw) <= bound, "campaign value exceeds byte bound")
    return json.loads(raw)


def _reference(value, repository):
    schemas = ({"repository", "revision", "path", "sha256", "bytes"},
               {"repository_id", "commit_sha", "path_in_repo", "sha256", "bytes"})
    _require(type(value) is dict and set(value) in schemas,
             "report requires a closed immutable Hub descriptor")
    repository_id = value.get("repository", value.get("repository_id"))
    revision = value.get("revision", value.get("commit_sha"))
    _require(repository_id == repository, "report repository is outside campaign scope")
    _require(type(revision) is str and re.fullmatch(r"[0-9a-f]{40}", revision),
             "report revision must be an immutable Hub commit")
    path = value.get("path", value.get("path_in_repo"))
    _require(type(path) is str and 0 < len(path) <= 1024 and path == str(PurePosixPath(path))
             and not path.startswith("/") and "\\" not in path
             and all(part not in {"", ".", ".."} for part in path.split("/")), "invalid report path")
    descriptor = _artifact({key: value[key] for key in ("sha256", "bytes")})
    _require(0 < descriptor["bytes"] <= 16 * 1024 * 1024, "report descriptor exceeds manifest byte bound")
    return _copy(value)


def _weight_reference(value, artifact, repository, _depth=0, *, training_purpose="formalization"):
    _require(_depth <= 8, "weight reference ancestry exceeds depth bound")
    required = {"kind", "repository_id", "commit_sha", "path_in_repo", "sha256", "bytes", "materialized_checkpoint"}
    _require(type(value) is dict and required <= set(value) and not set(value) - required - {"anchor_reference"},
             "weights require an immutable portable reference")
    kinds = {"anchor", "feature_sparse"} if training_purpose == _FEATURE_PURPOSE else {"anchor", "sparse"}
    _require(value["kind"] in kinds, "invalid weight reference kind for training purpose")
    if value["kind"] == "feature_sparse":
        _require("anchor_reference" in value, "feature sparse weights require an exact parent reference")
    _require(type(value["bytes"]) is int and 0 < value["bytes"] <= 512 * 1024 * 1024, "invalid weight byte bound")
    _reference({"repository": value["repository_id"], "revision": value["commit_sha"], "path": value["path_in_repo"],
                "sha256": value["sha256"], "bytes": min(value["bytes"], 16 * 1024 * 1024)}, repository)
    _require(_artifact(value["materialized_checkpoint"]) == artifact, "materialized weight descriptor differs")
    if value["kind"] == "anchor":
        _require({key: value[key] for key in ("sha256", "bytes")} == artifact, "anchor differs from full weights")
    if "anchor_reference" in value:
        anchor = value["anchor_reference"]
        if type(anchor) is dict and "kind" in anchor:
            _weight_reference(anchor, _artifact(anchor.get("materialized_checkpoint", {})), repository,
                              _depth + 1, training_purpose=training_purpose)
            return _copy(value)
        _require(type(anchor) is dict and set(anchor) == {"repository_id", "commit_sha", "path_in_repo", "sha256", "bytes"}, "invalid anchor reference")
        _require(type(anchor["bytes"]) is int and 0 < anchor["bytes"] <= 512 * 1024 * 1024, "invalid anchor byte bound")
        _reference({"repository": anchor["repository_id"], "revision": anchor["commit_sha"], "path": anchor["path_in_repo"],
                    "sha256": anchor["sha256"], "bytes": min(anchor["bytes"], 16 * 1024 * 1024)}, repository)
    return _copy(value)


def _source_observation(observed, artifact):
    """Export small immutable source locators, never the full census payload."""
    provenance = observed.get("provenance", {})
    fallback = provenance.get("observations", []) if type(provenance) is dict else []
    observations = observed.get("observations", fallback)
    _require(type(observations) is list, "source observations must be an array")
    fields = ("repository_id", "revision", "manifest_in_repo", "fingerprint", "manifest_sha256", "census_sha256")
    locators = {}
    for item in observations:
        if type(item) is not dict or not ({"repository_id", "manifest_in_repo"} & set(item)):
            continue
        _require(set(fields) <= set(item), "Hub source observation is missing immutable locator fields")
        repository = item["repository_id"]
        _require(type(repository) is str and len(repository) <= 256 and _REPOSITORY.fullmatch(repository),
                 "invalid source observation repository")
        for name in ("fingerprint", "manifest_sha256", "census_sha256"):
            _require(type(item[name]) is str and _HEX.fullmatch(item[name]), "invalid source observation " + name)
        _reference({"repository_id": repository, "commit_sha": item["revision"],
                    "path_in_repo": item["manifest_in_repo"], "sha256": item["manifest_sha256"], "bytes": 1}, repository)
        locator = {key: item[key] for key in fields}
        locators[_digest(locator)] = locator
    keys = sorted(locators)
    return _copy({"artifact": _artifact(artifact), "hub_locators": [locators[key] for key in keys[:4]],
                  "observation_count": len(observations), "locator_count": len(keys),
                  "locators_truncated": len(keys) > 4, "source_authority_authenticated": False}, 8 * 1024)


class AutoencoderSpanCampaign:
    """One immutable campaign policy and a resumable shared work queue.

    ``validator(assignment, report_descriptor)`` is a trusted owner callback,
    never a wire argument. It returns ``{'artifact': <owner CAS descriptor>,
    'result': <owner verification result>}``. Formalization results explicitly record
    ``admitted=False``, ``owner_verified=True``, and a ``span_disposition`` of
    ``qualified`` or ``needs_repair``. Neither submission nor completion promotes
    weights. Explicit ``policy.training_purpose='feature_pretraining'`` instead
    requires verified raw feature/target/replay evidence and all legal success
    flags false. It uses a separate, immutable campaign and portable weight kind.
    ``advance_generation`` is an explicit, owner-only CAS operation; selecting a
    feature generation never promotes an inference head or formalizes a span.
    """

    def __init__(self, registry: AutoencoderRegistry, *, campaign_id: str,
                 variant_id: str, base_version_id: str, policy: Mapping[str, Any],
                 result_repository: str, seed_weight_reference: Mapping[str, Any]):
        _require(type(registry) is AutoencoderRegistry, "campaign requires the actual registry owner")
        registry._ensure_owner()
        for name, value in (("campaign_id", campaign_id), ("variant_id", variant_id), ("base_version_id", base_version_id)):
            _token(value, name)
        _require(type(policy) is dict, "campaign policy must be an object")
        self.training_purpose = policy.get("training_purpose", "formalization")
        _require(type(self.training_purpose) is str and self.training_purpose in {"formalization", _FEATURE_PURPOSE},
                 "invalid training purpose")
        _require(type(result_repository) is str and _REPOSITORY.fullmatch(result_repository), "invalid result repository")
        version = registry.get_version(base_version_id)
        _require(version["variant_id"] == variant_id, "campaign seed belongs to another variant")
        self.registry, self.campaign_id, self.variant_id = registry, campaign_id, variant_id
        self.result_repository = result_repository
        reference = _weight_reference(seed_weight_reference, version["artifact"], result_repository,
                                      training_purpose=self.training_purpose)
        # Keep vectors in immutable artifacts or independently verified local
        # inputs. The registry and wire retain their existing 64/128 KiB bounds.
        policy_bound = 40 * 1024 if self.training_purpose == _FEATURE_PURPOSE else 16 * 1024
        binding_bound = 60 * 1024 if self.training_purpose == _FEATURE_PURPOSE else 48 * 1024
        self.binding = _copy({"schema": SCHEMA, "campaign_id": campaign_id, "variant_id": variant_id,
                              "base_version_id": base_version_id, "policy": _copy(policy, policy_bound),
                              "result_repository": result_repository, "seed_weight_reference": reference}, binding_bound)
        self.binding_sha256 = _digest(self.binding)
        self.seed = {"generation": 1, "version_id": base_version_id, "artifact": version["artifact"], "weight_reference": reference}
        registry._mutate("span-campaign-bind:" + _digest(campaign_id), "BindSpanCampaign", self.binding,
                         lambda cx: {**self.binding, "binding_sha256": self.binding_sha256})

    def _operation(self, worker_id, operation_id):
        _token(worker_id, "worker_id")
        _token(operation_id, "operation_id")
        return "span-campaign:" + _digest({"campaign": self.campaign_id, "worker": worker_id, "operation": operation_id})

    def _scope(self, run):
        spec = run["spec"]
        _require(spec.get("schema") == SCHEMA and spec.get("campaign_id") == self.campaign_id
                 and spec.get("binding_sha256") == self.binding_sha256
                 and run["variant_id"] == self.variant_id, "run is outside campaign scope")
        return run

    def _generation(self, cx):
        row = cx.execute("SELECT receipt FROM autoencoder_control.operations WHERE "
            "json_extract_string(receipt,'$.command')='AdvanceSpanGeneration' AND "
            "json_extract_string(receipt,'$.campaign_id')=? AND "
            "json_extract_string(receipt,'$.binding_sha256')=? ORDER BY "
            "CAST(json_extract(receipt,'$.generation') AS BIGINT) DESC LIMIT 1",
            [self.campaign_id, self.binding_sha256]).fetchone()
        return _copy(self.seed if row is None else {key: json.loads(row[0])[key]
                     for key in ("generation", "version_id", "artifact", "weight_reference")})

    def _assignment(self, run):
        self._scope(run)
        return {"schema": SCHEMA, "campaign_id": self.campaign_id, "binding_sha256": self.binding_sha256,
                "work_id": run["spec"].get("work_id", run["run_id"]),
                "run_id": run["run_id"], "record": run["spec"]["record"], "policy": self.binding["policy"],
                "observation_artifact": run["spec"].get("observation_artifact"),
                "source_observation": run["spec"].get("source_observation"),
                "generation": run["spec"].get("assigned_generation"), "base_version_id": run["base_version_id"],
                "variant_id": self.variant_id, "result_repository": self.result_repository}

    def register_records(self, records):
        """Append source work; repeated census observations do not retrain it."""
        _require(type(records) in (list, tuple) and len(records) <= 10000, "register at most 10000 records per call")
        run_ids = []
        for supplied in records:
            _require(type(supplied) is dict and type(supplied.get("sample")) is dict
                     and type(supplied["sample"].get("text")) is str
                     and bool(supplied["sample"]["text"].strip()), "record must contain nonempty sample text")
            observed = _copy(supplied, _MAX_OBSERVATION)
            _require(type(observed.get("record_id")) is str and _HEX.fullmatch(observed["record_id"].removeprefix("sha256:")),
                     "record_id must be a full SHA-256")
            core = {"record_id": observed["record_id"], "sample": observed["sample"]}
            text = observed["sample"]["text"]
            source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            _require(observed.get("text", text) == text and observed.get("source_text_sha256", source_hash) == source_hash,
                     "provided source text or hash differs from the sample")
            source_id = observed.get("source_span_id", observed["record_id"])
            _require(type(source_id) is str and bool(source_id.strip()) and len(source_id) <= 2048,
                     "source_span_id must be a bounded nonempty string")
            record = {**core, "source_span_id": source_id, "text": text, "source_text_sha256": source_hash}
            for key in ("legal_id", "document_id"):
                if key in observed:
                    _require(type(observed[key]) is str and len(observed[key]) <= 2048, key + " must be a bounded string")
                    record[key] = observed[key]
            record = _copy(record, _MAX_RECORD)
            identity = _digest({"binding_sha256": self.binding_sha256, "record": core})
            run_id = "span-" + identity
            manifest = {"schema": SCHEMA, "campaign_id": self.campaign_id,
                        "binding_sha256": self.binding_sha256, "record": record}
            with tempfile.NamedTemporaryFile(dir=self.registry.artifact_root, suffix=".span.json") as stream:
                stream.write(canonical_json_bytes(manifest))
                stream.flush()
                descriptor = self.registry.stage_artifact(stream.name)
            with tempfile.NamedTemporaryFile(dir=self.registry.artifact_root, suffix=".observation.json") as stream:
                stream.write(json.dumps(observed, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False, allow_nan=False).encode("utf-8"))
                stream.flush()
                observation_artifact = self.registry.stage_artifact(stream.name)
            source_observation = _source_observation(observed, observation_artifact)
            # Existing generic Quack guard refuses job_spec_artifact runs. Only
            # this campaign profile can claim them; the manifest is real CAS data.
            spec = {**manifest, "kind": "source_work", "job_spec_artifact": descriptor,
                    "observation_artifact": observation_artifact, "source_observation": source_observation}
            # Preserve the first source observation in the immutable assignment.
            # Subsequent observation bytes are append-only audit artifacts. The
            # same record identity may never silently change stable source data.
            with self.registry._lock:
                with self.registry._transaction() as cx:
                    present = cx.execute("SELECT 1 FROM autoencoder_control.runs WHERE run_id=?", [run_id]).fetchone()
                    existing = self._scope(self.registry._run(cx, run_id)) if present else None
                if existing is not None:
                    _require(existing["spec"]["record"] == record, "stable source fields changed under an existing record identity")
                    spec = existing["spec"]
                self.registry.create_run("span-register:" + identity, run_id, self.variant_id,
                                         self.seed["version_id"], spec)
            observation = {"campaign_id": self.campaign_id, "work_id": run_id,
                           "observation_artifact": observation_artifact, "source_observation": source_observation}
            self.registry._mutate("span-observation:" + _digest(observation), "ObserveSpanSource", observation,
                                  lambda cx, value=observation: {**value, "authority": "source_observation_only"})
            run_ids.append(run_id)
        return run_ids

    def acknowledge_weights(self, operation_id, worker_id, generation, version_id, artifact):
        _require(type(generation) is int and generation >= 0, "invalid generation")
        descriptor = _artifact(artifact)
        payload = {"campaign_id": self.campaign_id, "binding_sha256": self.binding_sha256,
                   "worker_id": worker_id, "generation": generation, "version_id": version_id, "artifact": descriptor}
        def apply(cx):
            current = self._generation(cx)
            _require(all(current[key] == payload[key] for key in ("generation", "version_id", "artifact")),
                     "weights acknowledgement differs from current generation")
            return {**payload, "verification": "worker_reported_local_hash", "qualified": False}
        return self.registry._mutate(self._operation(worker_id, operation_id), "AcknowledgeSpanWeights", payload, apply)

    def _has_ack(self, cx, worker_id, generation):
        rows = cx.execute("SELECT receipt FROM autoencoder_control.operations WHERE "
            "json_extract_string(receipt,'$.command')='AcknowledgeSpanWeights' AND "
            "json_extract_string(receipt,'$.campaign_id')=? AND json_extract_string(receipt,'$.worker_id')=? AND "
            "CAST(json_extract(receipt,'$.generation') AS BIGINT)=?",
            [self.campaign_id, worker_id, generation["generation"]]).fetchall()
        expected = {"binding_sha256": self.binding_sha256, **{key: generation[key] for key in ("generation", "version_id", "artifact")}}
        return any(all(json.loads(row[0]).get(key) == value for key, value in expected.items()) for row in rows)

    def claim_next(self, operation_id, worker_id, lease_seconds=300):
        payload = {"campaign_id": self.campaign_id, "worker_id": worker_id, "lease_seconds": lease_seconds}
        def apply(cx):
            generation = self._generation(cx)
            _require(self._has_ack(cx, worker_id, generation), "worker must acknowledge current weights before claiming")
            rows = cx.execute("SELECT run_id FROM autoencoder_control.runs WHERE "
                "json_extract_string(spec,'$.schema')=? AND json_extract_string(spec,'$.campaign_id')=? "
                "AND json_extract_string(spec,'$.kind')='source_work' "
                "AND status IN ('queued','failed','running') ORDER BY run_id", [SCHEMA, self.campaign_id]).fetchall()
            for (work_id,) in rows:
                work = self._scope(self.registry._run(cx, work_id))
                if self.registry._live(work["lease"]) or (work["result"] or {}).get("report_pending"):
                    continue
                run_id = "span-attempt-" + _digest({"work_id": work_id, "generation": generation["generation"]})
                found = cx.execute("SELECT 1 FROM autoencoder_control.runs WHERE run_id=?", [run_id]).fetchone()
                if found is None:
                    spec = {**work["spec"], "kind": "generation_attempt", "work_id": work_id,
                            "assigned_generation": generation["generation"]}
                    cx.execute("INSERT INTO autoencoder_control.runs VALUES (?,?,?,?, 'queued',0,0,NULL,NULL)",
                               [run_id, self.variant_id, generation["version_id"], _json(spec)])
                run = self._scope(self.registry._run(cx, run_id))
                _require(run["base_version_id"] == generation["version_id"] and run["status"] != "completed",
                         "generation attempt was already completed or base differs")
                lease = self.registry._new_lease({"run_id": run_id, "attempt": run["attempt"] + 1},
                                                worker_id, run["fence"] + 1, lease_seconds)
                for identity in (work_id, run_id):
                    cx.execute("UPDATE autoencoder_control.runs SET status='running',attempt=?,fence=?,lease=?,result=NULL WHERE run_id=?",
                               [lease["attempt"], lease["fence"], _json(lease), identity])
                run = self.registry._run(cx, run_id)
                return {"status": "claimed", "lease": lease, "assignment": {**self._assignment(run), "worker_id": worker_id},
                        "weights": generation, "qualified": False}
            return {"status": "empty", "weights": generation, "qualified": False}
        return self.registry._mutate(self._operation(worker_id, operation_id), "ClaimSpan", payload, apply)

    def _worker_run(self, worker_id, lease):
        _require(type(lease) is dict and lease.get("worker_id") == worker_id, "lease belongs to another worker")
        return self._scope(self.registry.get_run(lease.get("run_id")))

    def renew(self, operation_id, worker_id, lease, lease_seconds=300):
        run = self._worker_run(worker_id, lease)
        payload = {"campaign_id": self.campaign_id, "lease": lease, "lease_seconds": lease_seconds}
        def apply(cx):
            current = self.registry._run(cx, run["run_id"])
            self.registry._check_lease(lease, current["lease"])
            _require(current["status"] == "running", "run is not running")
            renewed = self.registry._new_lease({"run_id": run["run_id"], "attempt": lease["attempt"]}, worker_id, lease["fence"], lease_seconds)
            for identity in (run["run_id"], run["spec"]["work_id"]):
                cx.execute("UPDATE autoencoder_control.runs SET lease=? WHERE run_id=?", [_json(renewed), identity])
            return {"lease": renewed}
        return self.registry._mutate(self._operation(worker_id, operation_id), "RenewSpan", payload, apply)

    def report(self, operation_id, worker_id, lease, report_descriptor):
        self._worker_run(worker_id, lease)
        descriptor = _reference(report_descriptor, self.result_repository)
        payload = {"campaign_id": self.campaign_id, "lease": lease, "report_descriptor": descriptor}
        def apply(cx):
            run = self._scope(self.registry._run(cx, lease["run_id"]))
            self.registry._check_lease(lease, run["lease"])
            _require(run["status"] == "running" and not (run["result"] or {}).get("report_pending"), "run is not accepting reports")
            pending = {"admitted": False, "report_pending": True, "report_descriptor": descriptor,
                       "report_lease": lease, "assignment": {**self._assignment(run), "worker_id": worker_id}}
            for identity in (run["run_id"], run["spec"]["work_id"]):
                cx.execute("UPDATE autoencoder_control.runs SET status='awaiting_verification',result=? WHERE run_id=?", [_json(pending), identity])
            return {"run_id": run["run_id"], "status": "awaiting_verification", "report_descriptor": descriptor,
                    "qualified": False, "formalized": False}
        return self.registry._mutate(self._operation(worker_id, operation_id), "ReportSpan", payload, apply)

    def read(self, run_id, *, worker_id=None):
        run = self._scope(self.registry.get_run(run_id))
        if worker_id is not None:
            original_worker = ((run["result"] or {}).get("report_lease") or {}).get("worker_id")
            with self.registry._transaction() as cx:
                prior = cx.execute("SELECT 1 FROM autoencoder_control.operations WHERE "
                    "json_extract_string(receipt,'$.command')='ClaimSpan' AND "
                    "json_extract_string(receipt,'$.lease.run_id')=? AND "
                    "json_extract_string(receipt,'$.lease.worker_id')=? LIMIT 1", [run_id, worker_id]).fetchone()
            _require((run["lease"] is not None and run["lease"]["worker_id"] == worker_id) or original_worker == worker_id or prior is not None,
                     "run is outside worker assignment")
        scoped_lease = run["lease"] if worker_id is None or (run["lease"] or {}).get("worker_id") == worker_id else None
        return {"admitted": False, "formalized": False, "run_id": run_id, "status": run["status"],
                "attempt": run["attempt"], "assignment": self._assignment(run), "result": run["result"],
                "lease_live": self.registry._live(scoped_lease), "lease": scoped_lease}

    def status(self):
        with self.registry._transaction() as cx:
            rows = cx.execute("SELECT status,count(*) FROM autoencoder_control.runs WHERE "
                "json_extract_string(spec,'$.schema')=? AND json_extract_string(spec,'$.campaign_id')=? "
                "AND json_extract_string(spec,'$.kind')='source_work' GROUP BY status",
                [SCHEMA, self.campaign_id]).fetchall()
            generation = self._generation(cx)
            acknowledgements = cx.execute("SELECT DISTINCT json_extract_string(receipt,'$.worker_id') FROM "
                "autoencoder_control.operations WHERE json_extract_string(receipt,'$.command')='AcknowledgeSpanWeights' "
                "AND json_extract_string(receipt,'$.campaign_id')=?", [self.campaign_id]).fetchall()
            synced = [row[0] for row in acknowledgements if self._has_ack(cx, row[0], generation)]
        configured = self.binding["policy"].get("known_workers", [])
        if not (type(configured) is list and all(type(worker) is str for worker in configured)):
            configured = []
        known = sorted({row[0] for row in acknowledgements} | set(configured))
        return {"schema": SCHEMA, "campaign_id": self.campaign_id, "binding_sha256": self.binding_sha256,
                "policy": self.binding["policy"],
                "weights": generation, "counts": dict(rows), "acknowledged_current_workers": sorted(synced),
                "known_workers": known, "workers_needing_sync": sorted(set(known) - set(synced)), "admitted": False,
                "formalized": False, "remote_copy_attestation": "worker_reported_local_hash"}

    def verify_reports(self, validator, *, max_reports=1):
        """Drain pending evidence on the owner, outside the Quack pump.

        Callback exceptions leave the report reserved and unverified. Retrying
        requires a deterministic/idempotent verifier. A newer canonical parent
        invalidates an in-flight sibling: it is requeued, never silently merged.
        """
        _require(callable(validator) and type(max_reports) is int and 1 <= max_reports <= 64,
                 "verification requires a callback and bounded report count")
        with self.registry._transaction() as cx:
            ids = [row[0] for row in cx.execute("SELECT run_id FROM autoencoder_control.runs WHERE "
                "json_extract_string(spec,'$.schema')=? AND json_extract_string(spec,'$.campaign_id')=? AND "
                "json_extract_string(spec,'$.kind')='source_work' AND "
                "json_extract(result,'$.report_pending')=true ORDER BY run_id LIMIT ?",
                [SCHEMA, self.campaign_id, max_reports]).fetchall()]
        completed = []
        for work_id in ids:
            work = self._scope(self.registry.get_run(work_id))
            pending = _copy(work["result"], 128 * 1024)
            run_id = pending["assignment"]["run_id"]
            run = self._scope(self.registry.get_run(run_id))
            old = self.registry.get_run_completion(run_id)
            if old is not None:
                receipt = old["completion_receipt"]
                disposition = old["run"]["result"]["span_disposition"]
                self._finish_work(work_id, receipt, disposition)
                completed.append({**receipt, "span_disposition": disposition})
                continue
            verified = validator(_copy(pending["assignment"], 128 * 1024), _copy(pending["report_descriptor"]))
            _require(type(verified) is dict and set(verified) == {"artifact", "result"}, "invalid owner verification result")
            artifact = self.registry.verify_artifact(verified["artifact"])
            result = _copy(verified["result"], 16 * 1024)
            if self.training_purpose == _FEATURE_PURPOSE:
                parent = self.registry.get_version(pending["assignment"]["base_version_id"])
                self._verify_feature_result(result, artifact, parent["artifact"])
            else:
                _require(result.get("training_purpose", "formalization") == "formalization"
                         and result.get("admitted") is False and result.get("owner_verified") is True
                         and result.get("span_disposition") in {"qualified", "needs_repair", "training_exhausted"},
                         "owner must verify exact qualification disposition")
            key = _digest({"run_id": run_id, "pending": pending})
            with self.registry._transaction() as cx:
                current = self._generation(cx)
            # An owner-only fresh lease fences the original remote host and lets
            # durable pending reports survive expiration and process restart.
            owner_worker = "span-verifier-" + self.binding_sha256[:24]
            run = self.registry.get_run(run_id)
            if run["lease"] and run["lease"]["worker_id"] == owner_worker and self.registry._live(run["lease"]):
                lease = run["lease"]
            else:
                takeover = {"report": key, "owner_generation": self.registry.owner_generation, "previous_lease": run["lease"]}
                def release(cx):
                    current_run = self.registry._run(cx, run_id)
                    _require(current_run["result"] == pending and current_run["lease"] == takeover["previous_lease"],
                             "pending report changed during verification")
                    cx.execute("UPDATE autoencoder_control.runs SET lease=NULL WHERE run_id=?", [run_id])
                    return {"run_id": run_id, "status": "owner_verification"}
                self.registry._mutate("span-verify-release:" + _digest(takeover), "PrepareSpanVerification", takeover, release)
                owner_claim = self.registry.claim_run("span-verify-claim:" + _digest(takeover), run_id, owner_worker, 300)
                lease = owner_claim["lease"]
            if current["version_id"] != pending["assignment"]["base_version_id"]:
                previous = ({"owner_candidate_feature_updated": result["span_disposition"] == "feature_updated"}
                            if self.training_purpose == _FEATURE_PURPOSE
                            else {"owner_candidate_qualified": result.get("qualified", False)})
                result = {**result, **previous, "span_disposition": "rebase_required",
                          "qualified": False}
            result = {**result, "campaign_id": self.campaign_id, "binding_sha256": self.binding_sha256,
                      "source_assignment": pending["assignment"], "remote_report": pending["report_descriptor"],
                      "report_lease": pending["report_lease"]}
            receipt = self.registry.complete_run("span-verify-complete:" + key, lease, artifact, result)
            self._finish_work(work_id, receipt, result["span_disposition"])
            completed.append({**receipt, "span_disposition": result["span_disposition"]})
        return completed

    def _verify_feature_result(self, result, artifact, parent_artifact):
        """Check the trusted owner's evidence contract, never worker assertions.

        The owner callback performs raw evaluation, exact sparse replay and
        target checks. These booleans are not remotely callable authority;
        its retained evidence must also exist unchanged in the owner's CAS.
        """
        _require(result.get("training_purpose") == _FEATURE_PURPOSE
                 and result.get("owner_verified") is True
                 and all(result.get(key) is False for key in ("qualified", "admitted", "formalized"))
                 and result.get("span_disposition") in {"feature_updated", "feature_no_update"},
                 "owner must verify feature disposition with all legal success flags false")
        _require(all(result.get(key) is True for key in (
            "sparse_replay_verified", "raw_objective_verified", "shared_target_supervision_verified")),
            "feature result requires owner-verified replay, raw objective and shared targets")
        epochs = result.get("optimizer_accepted_epochs")
        _require(type(epochs) is int and epochs >= 0, "feature accepted epochs must be a nonnegative integer")
        updated = result["span_disposition"] == "feature_updated"
        _require((epochs > 0) == updated and (artifact != parent_artifact) == updated,
                 "feature disposition, accepted epochs and exact parent artifact differ")
        self.registry.verify_artifact(result.get("feature_evidence_artifact", {}))

    def _finish_work(self, work_id, receipt, disposition):
        payload = {"work_id": work_id, "completion": receipt, "span_disposition": disposition}
        def apply(cx):
            work = self._scope(self.registry._run(cx, work_id))
            _require((work["result"] or {}).get("report_pending") and
                     work["result"]["assignment"]["run_id"] == receipt["run_id"], "work completion differs from pending report")
            status = "queued" if disposition == "rebase_required" else "source_completed"
            cx.execute("UPDATE autoencoder_control.runs SET status=?,lease=NULL,result=? WHERE run_id=?",
                       [status, _json({"admitted": False, **payload}), work_id])
            return {"work_id": work_id, "status": status, "span_disposition": disposition}
        self.registry._mutate("span-finish-work:" + _digest(payload), "FinishSpanWork", payload, apply)

    def advance_generation(self, operation_id, version_id, *, expected_generation, expected_version_id, weight_reference):
        """Explicit owner policy selection; conflicting siblings cannot merge."""
        _token(operation_id, "operation_id")
        _require(type(expected_generation) is int and expected_generation >= 0, "invalid expected generation")
        version = self.registry.get_version(version_id)
        producer_run = version["metadata"].get("producer_run")
        completion = self.registry.get_run_completion(producer_run) if type(producer_run) is str else None
        _require(completion is not None and completion["candidate_version"]["version_id"] == version_id,
                 "generation version must be the exact owner-completed candidate")
        reference = _weight_reference(weight_reference, version["artifact"], self.result_repository,
                                      training_purpose=self.training_purpose)
        payload = {"campaign_id": self.campaign_id, "binding_sha256": self.binding_sha256,
                   "version_id": version_id, "expected_generation": expected_generation,
                   "expected_version_id": expected_version_id, "weight_reference": reference}
        def apply(cx):
            current = self._generation(cx)
            _require(current["generation"] == expected_generation and current["version_id"] == expected_version_id,
                     "canonical generation CAS conflict")
            result = version["metadata"].get("result", {})
            run_id = version["metadata"].get("producer_run")
            run = self._scope(self.registry._run(cx, run_id))
            disposition = "feature_updated" if self.training_purpose == _FEATURE_PURPOSE else "qualified"
            _require(version["variant_id"] == self.variant_id and version["parent_version_id"] == current["version_id"]
                     and run["status"] == "completed" and result == run["result"]
                     and result.get("owner_verified") is True and result.get("span_disposition") == disposition
                     and result.get("binding_sha256") == self.binding_sha256,
                     "generation requires an owner-verified " + disposition + " child of current weights")
            self.registry.verify_artifact(version["artifact"])
            extra = {}
            if self.training_purpose == _FEATURE_PURPOSE:
                self._verify_feature_result(result, version["artifact"], current["artifact"])
                _require(reference["kind"] == "feature_sparse", "feature updates require a feature sparse reference")
                anchor = reference["anchor_reference"]
                parent_artifact = anchor.get("materialized_checkpoint", {key: anchor[key] for key in ("sha256", "bytes")})
                _require(_artifact(parent_artifact) == current["artifact"], "feature sparse reference has another parent")
                _require(result.get("weight_reference") == reference, "feature reference differs from owner-verified result")
                extra = {"training_purpose": _FEATURE_PURPOSE, "qualified": False, "admitted": False}
            return {**payload, "generation": current["generation"] + 1, "artifact": version["artifact"],
                    **extra, "formalized": False, "head_promotion_performed": False}
        return self.registry._mutate("span-advance:" + _digest({"campaign": self.campaign_id, "operation": operation_id}),
                                     "AdvanceSpanGeneration", payload, apply)

    def requeue_stale_feature_candidate(self, operation_id, version_id, *, expected_generation, expected_version_id):
        """Rebase work whose verified sibling lost canonical feature selection.

        This closes the case where several reports were verified before one was
        selected. Old attempts and sparse artifacts remain immutable; the next
        claim requires an acknowledgement and starts from the current full state.
        """
        _require(self.training_purpose == _FEATURE_PURPOSE, "stale feature requeue requires feature purpose")
        _token(operation_id, "operation_id")
        _require(type(expected_generation) is int and expected_generation >= 1, "invalid expected generation")
        version = self.registry.get_version(version_id)
        producer_run = version["metadata"].get("producer_run")
        completion = self.registry.get_run_completion(producer_run) if type(producer_run) is str else None
        _require(completion is not None and completion["candidate_version"]["version_id"] == version_id,
                 "requeue requires an exact owner-completed feature candidate")
        parent = self.registry.get_version(version["parent_version_id"])
        payload = {"campaign_id": self.campaign_id, "binding_sha256": self.binding_sha256,
                   "version_id": version_id, "expected_generation": expected_generation,
                   "expected_version_id": expected_version_id}
        def apply(cx):
            current = self._generation(cx)
            _require(current["generation"] == expected_generation and current["version_id"] == expected_version_id,
                     "canonical generation CAS conflict")
            run = self._scope(self.registry._run(cx, producer_run))
            result = version["metadata"].get("result", {})
            _require(run["status"] == "completed" and run["spec"].get("kind") == "generation_attempt"
                     and result == run["result"] and result.get("binding_sha256") == self.binding_sha256
                     and version["parent_version_id"] != current["version_id"]
                     and version_id != current["version_id"], "feature candidate is not a stale unselected child")
            selected = cx.execute("SELECT 1 FROM autoencoder_control.operations WHERE "
                "json_extract_string(receipt,'$.command')='AdvanceSpanGeneration' AND "
                "json_extract_string(receipt,'$.campaign_id')=? AND "
                "json_extract_string(receipt,'$.binding_sha256')=? AND "
                "json_extract_string(receipt,'$.version_id')=? LIMIT 1",
                [self.campaign_id, self.binding_sha256, version_id]).fetchone()
            _require(selected is None, "previously selected feature generation cannot be requeued")
            self._verify_feature_result(result, version["artifact"], parent["artifact"])
            work_id = run["spec"]["work_id"]
            work = self._scope(self.registry._run(cx, work_id))
            _require(work["status"] == "source_completed" and
                     (work["result"] or {}).get("completion") == completion["completion_receipt"],
                     "stale feature work has already changed")
            retained = {**payload, "completion": completion["completion_receipt"],
                        "span_disposition": "rebase_required", "admitted": False, "qualified": False,
                        "formalized": False, "training_purpose": _FEATURE_PURPOSE}
            cx.execute("UPDATE autoencoder_control.runs SET status='queued',lease=NULL,result=? WHERE run_id=?",
                       [_json(retained), work_id])
            return {**retained, "work_id": work_id, "status": "queued"}
        return self.registry._mutate("span-requeue-feature:" + _digest({"campaign": self.campaign_id, "operation": operation_id}),
                                     "RequeueStaleFeatureSpan", payload, apply)


class SpanCampaignQuackGateway(_TransientQuackGateway):
    """One private worker identity; never a file handle or arbitrary SQL API."""

    def __init__(self, campaign: AutoencoderSpanCampaign, worker_id: str):
        _require(type(campaign) is AutoencoderSpanCampaign, "actual owner campaign required")
        _token(worker_id, "worker_id")
        self.campaign, self.worker_id = campaign, worker_id
        super().__init__()

    def _before_start(self):
        self.campaign.registry._ensure_owner()

    def dispatch(self, envelope):
        request = parse_request(encode_request(dict(envelope)))
        command, payload, operation = request["command"], request["payload"], request["operation_id"]
        fields = {"ClaimSpan": ({}, {"lease_seconds"}), "RenewSpan": ({"lease"}, {"lease_seconds"}),
                  "ReportSpan": ({"lease", "report_descriptor"}, set()), "ReadSpan": ({"run_id"}, set()),
                  "ReadCampaign": (set(), set()), "AcknowledgeWeights": ({"generation", "version_id", "artifact"}, set())}
        _require(command in fields and type(payload) is dict, "command is outside span campaign vocabulary")
        required, optional = fields[command]
        _require(set(required) <= set(payload) and not set(payload) - set(required) - optional, "closed span command schema differs")
        if command == "ClaimSpan":
            return self.campaign.claim_next(operation, self.worker_id, **payload)
        if command == "RenewSpan":
            return self.campaign.renew(operation, self.worker_id, **payload)
        if command == "ReportSpan":
            return self.campaign.report(operation, self.worker_id, **payload)
        if command == "ReadSpan":
            return self.campaign.read(payload["run_id"], worker_id=self.worker_id)
        if command == "ReadCampaign":
            return self.campaign.status()
        return self.campaign.acknowledge_weights(operation, self.worker_id, **payload)


class SpanCampaignTransportClient(RegistryTransportClient):
    @staticmethod
    def _request_envelope(command, payload, operation_id):
        _require(command in COMMANDS, "command is outside span campaign vocabulary")
        _token(operation_id, "operation_id")
        return parse_request(encode_request({"schema": WIRE_SCHEMA, "request_id": str(uuid.uuid4()),
                             "operation_id": operation_id, "command": command, "payload": dict(payload)}))
