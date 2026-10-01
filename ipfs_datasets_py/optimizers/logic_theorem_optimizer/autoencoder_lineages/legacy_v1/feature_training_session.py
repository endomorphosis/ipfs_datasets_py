"""Persistent, bounded continuation of the opt-in 8D family-feature trainer.

This controller delegates every proposal to unchanged ``active_training``.
It persists its learning rate and lifetime proposal budget beside an unchanged
historical model bundle. It never replaces the linguistic decoder, supplies
formula targets, downloads weights, or treats reconstruction as legal fidelity.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time

from . import active_training as active
from . import linguistic
from . import linguistic_view_reuse as profiles

SCHEMA = "legacy-feature-training-session/v1"
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_PROFILES = {"cached": profiles.ViewReuseCachedLinguisticAutoencoder,
             "streamed_cached": profiles.ViewReuseStreamedCachedLinguisticAutoencoder,
             "historical_daemon": profiles.ViewReuseHistoricalDaemonAutoencoder}
_FALSE = dict(active._FALSE, independent_generalization_verified=False)
_require, _number = active._require, active._number


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _source_identity():
    stat = Path(__file__).stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


_SOURCE_IDENTITY = _source_identity()
_SOURCE_HASH = _sha(Path(__file__).read_bytes())
_require(_SOURCE_IDENTITY == _source_identity(), "feature session source changed during import")
_SOURCES = {"feature_training_session": _SOURCE_HASH,
            "active_training": active._IMPORTED_SOURCE_SHA256}


def _sources_unchanged():
    _require(_source_identity() == _SOURCE_IDENTITY, "feature session source changed since import")
    _require(active._source_identity() == active._IMPORTED_SOURCE_IDENTITY,
             "active trainer source changed since import")


def _config(*, proposal_budget, learning_rate, min_learning_rate, max_learning_rate,
            growth_factor, shrink_factor, max_consecutive_rejections):
    _require(type(proposal_budget) is int and 1 <= proposal_budget <= 256,
             "lifetime proposal_budget must be in 1..256")
    _require(type(max_consecutive_rejections) is int and 1 <= max_consecutive_rejections <= 16,
             "max_consecutive_rejections must be in 1..16")
    for name, value in (("learning_rate", learning_rate), ("min_learning_rate", min_learning_rate),
                        ("max_learning_rate", max_learning_rate)):
        _number(value, name, 0, 1, inclusive_low=False)
    _require(min_learning_rate <= learning_rate <= max_learning_rate, "learning rate outside explicit bounds")
    _number(growth_factor, "growth_factor", 1, 2)
    _number(shrink_factor, "shrink_factor", 0, 1, inclusive_low=False)
    _require(shrink_factor < 1, "shrink factor must be below one")
    return dict(proposal_budget=proposal_budget, learning_rate=float(learning_rate),
                min_learning_rate=float(min_learning_rate), max_learning_rate=float(max_learning_rate),
                growth_factor=float(growth_factor), shrink_factor=float(shrink_factor),
                max_consecutive_rejections=max_consecutive_rejections)


def _inputs(model, samples, validation_samples):
    _require(type(model) in _PROFILES.values(), "an explicit view-reuse 8D linguistic profile is required")
    model._require_profile()
    _require(model.compute_backend != "torch_cuda", "feature sessions currently require CPU execution")
    _require(type(samples) in (list, tuple) and type(validation_samples) in (list, tuple)
             and 1 <= len(samples) <= 128 and 1 <= len(validation_samples) <= 128,
             "one to 128 explicit training and tuning samples required")
    training, tuning = model._samples(samples), model._samples(validation_samples)
    all_rows = training + tuning
    _require(len({row.sample_id for row in all_rows}) == len(all_rows)
             and len({" ".join(row.text.lower().split()) for row in all_rows}) == len(all_rows),
             "training/tuning IDs and normalized sources must be unique and disjoint")
    return tuple(training), tuple(tuning)


def _binding(model, training, tuning):
    return dict(profile=next(key for key, cls in _PROFILES.items() if type(model) is cls),
                linguistic_identity_sha256=model._linguistic_identity_sha256,
                effective_configuration_sha256=_sha(_raw(model._linguistic_effective_configuration)),
                training_manifest_sha256=active._samples_digest(training),
                tuning_manifest_sha256=active._samples_digest(tuning),
                training_sample_count=len(training), tuning_sample_count=len(tuning))


def _unique_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite checkpoint JSON")))


class FeatureTrainingSession:
    """One private mutable model with persisted rate, input binding and budget.

    ``advance`` spends at most its requested number of proposals from the fixed
    lifetime budget. Rejections continue at the trainer's reduced rate until
    the declared plateau bound or minimum rate is reached. A deadline ends only
    the current call; it does not replenish the lifetime budget. No predictions
    or full weight copies are retained in scheduler state.
    """

    def __init__(self, model, samples, *, validation_samples, proposal_budget=12,
                 learning_rate=.01, min_learning_rate=.0001, max_learning_rate=.35,
                 growth_factor=1.5, shrink_factor=.5, max_consecutive_rejections=4):
        _sources_unchanged()
        self._training, self._tuning = _inputs(model, samples, validation_samples)
        config = _config(proposal_budget=proposal_budget, learning_rate=learning_rate,
                         min_learning_rate=min_learning_rate, max_learning_rate=max_learning_rate,
                         growth_factor=growth_factor, shrink_factor=shrink_factor,
                         max_consecutive_rejections=max_consecutive_rejections)
        _require(model.state._active_state_transaction is None, "model already has an active writer")
        self.model = model
        self._lock = threading.Lock()
        self._failed = False
        self._state = _raw(dict(schema=SCHEMA, sources=dict(_SOURCES),
            binding=_binding(model, self._training, self._tuning), config=config,
            progress=dict(proposals_used=0, accepted_updates=0, rejected_proposals=0,
                          consecutive_rejections=0, next_learning_rate=float(learning_rate),
                          terminal_reason=None, model_state_identity=model.state.state_identity()), **_FALSE))

    @property
    def state(self):
        """Return a detached scheduler snapshot, never live model parameters."""
        return json.loads(self._state)

    def _check(self):
        _sources_unchanged()
        _require(not self._failed, "failed feature session requires reload from a prior completed generation")
        self.model._require_profile()
        data = self.state
        _require(_raw(_binding(self.model, self._training, self._tuning)) == _raw(data["binding"]),
                 "feature session input or model configuration changed")
        _require(self.model.state.state_identity() == data["progress"]["model_state_identity"],
                 "model weights changed outside feature session")
        _require(self.model.state._active_state_transaction is None, "model already has an active writer")
        return data

    def advance(self, *, max_proposals=6, max_seconds=60):
        """Continue strict proposals, retaining counters/rate across calls.

        The monotonic per-call deadline includes setup; underlying inflight
        operations remain soft and late candidates roll back. Exceptional calls
        poison this in-memory controller, so it cannot publish an ambiguous
        scheduler/model pair. Previously saved generations remain usable.
        """
        started = time.monotonic()
        _number(max_seconds, "max_seconds", 0, 600, inclusive_low=False)
        _require(type(max_proposals) is int and 1 <= max_proposals <= 256,
                 "max_proposals must be in 1..256")
        _require(self._lock.acquire(blocking=False), "feature session already has an active operation")
        rows = []
        stopped = "call_proposal_budget"
        before = after = None
        try:
            data = self._check()
            config, progress = data["config"], data["progress"]
            for _ in range(min(max_proposals, config["proposal_budget"] - progress["proposals_used"])):
                if progress["terminal_reason"] is not None:
                    break
                self._check()
                remaining = max_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    stopped = "deadline"
                    break
                result = active.train_active_family_features(self.model, list(self._training),
                    validation_samples=list(self._tuning), epochs=1,
                    learning_rate=progress["next_learning_rate"],
                    min_learning_rate=config["min_learning_rate"], max_learning_rate=config["max_learning_rate"],
                    growth_factor=config["growth_factor"], shrink_factor=config["shrink_factor"],
                    max_line_search_attempts=1, max_seconds=remaining)
                _require(result["proposal_count"] in (0, 1) and result["accepted_epochs"] in (0, 1),
                         "underlying trainer exceeded the single-proposal contract")
                if before is None:
                    before = result["before"]
                after = result["after"]
                if result["proposal_count"]:
                    record = result["epoch_reports"][0]
                    accepted = result["accepted_epochs"]
                    progress["proposals_used"] += 1
                    progress["accepted_updates"] += accepted
                    progress["rejected_proposals"] += 1 - accepted
                    # A late aborted proposal consumes budget, but is not a
                    # measured optimization plateau or a reason to shrink LR.
                    late = record["reason"].startswith("deadline")
                    if not late:
                        progress["consecutive_rejections"] = 0 if accepted else progress["consecutive_rejections"] + 1
                    progress["next_learning_rate"] = result["next_learning_rate"]
                    rows.append(dict(proposal_index=progress["proposals_used"], accepted=bool(accepted),
                        learning_rate=record["learning_rate"], next_learning_rate=progress["next_learning_rate"],
                        reason=record["reason"], objective_delta=record.get("objective_delta"),
                        update_norm=record["update_norms"]["update_norm"],
                        cross_entropy_after=None if after is None else after["cross_entropy_loss"]))
                    if progress["proposals_used"] >= config["proposal_budget"]:
                        progress["terminal_reason"] = "proposal_budget"
                    elif not late and not accepted and record["learning_rate"] <= config["min_learning_rate"]:
                        progress["terminal_reason"] = "minimum_learning_rate"
                    elif progress["consecutive_rejections"] >= config["max_consecutive_rejections"]:
                        progress["terminal_reason"] = "plateau"
                progress["model_state_identity"] = self.model.state.state_identity()
                self._state = _raw(data)
                if result["stopped_reason"].startswith("deadline"):
                    stopped = "deadline"
                    break
            self._check()
            if progress["terminal_reason"]:
                stopped = progress["terminal_reason"]
            return dict(schema=SCHEMA + "/advance", state=self.state, proposal_reports=rows,
                        proposal_count=len(rows), accepted_updates=sum(row["accepted"] for row in rows),
                        before=before, after=after, stopped_reason=stopped,
                        elapsed_seconds=time.monotonic() - started,
                        deadline_scope="per-call setup included; inflight operations soft; lifetime proposals persist",
                        legal_ir_bridge_names=[], legal_ir_target_count=0, legal_ir_evaluate_provers=False,
                        legal_ir_parallel_workers=1, training_executed=bool(rows), **_FALSE)
        except BaseException:
            self._failed = True
            raise
        finally:
            self._lock.release()

    def save(self, directory):
        """Publish one exclusive generation; final manifest is the atomic marker.

        A failed new generation may remain as an incomplete directory. Loading
        requires the final manifest and all bound files. Existing generations
        are never overwritten. The historical save path materializes its own
        bounded JSON weight bundle; this cost occurs only at explicit saves.
        """
        started = time.monotonic()
        _require(self._lock.acquire(blocking=False), "feature session already has an active operation")
        try:
            state = self._check()
            root = Path(directory)
            root.mkdir(parents=True, exist_ok=False)
            self.model.save_training_checkpoint(root / "model")
            self._check()
            model_manifest = linguistic._read(root / "model/manifest.json", linguistic._MAX_MANIFEST_BYTES)
            manifest = dict(schema=SCHEMA + "/checkpoint", session=state,
                            model_manifest_sha256=_sha(model_manifest), model_manifest_bytes=len(model_manifest),
                            model_directory="model", **_FALSE)
            payload = _raw(manifest)
            _require(len(payload) <= linguistic._MAX_MANIFEST_BYTES, "session manifest exceeds byte bound")
            temporary = root / "session.pending.json"
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._check()
            # Hard-link publication is atomic and refuses an existing marker.
            os.link(temporary, root / "session.json")
            temporary.unlink()
            return dict(path=str(root.resolve()), sha256=_sha(payload), bytes=len(payload),
                        elapsed_seconds=time.monotonic() - started,
                        model_core_bytes=_unique_json(model_manifest)["core_bytes"],
                        publication_scope="local completed checkpoint generation", **_FALSE)
        finally:
            self._lock.release()


def load_training_session(directory, *, expected_sha256, samples, validation_samples):
    """Restore an exact completed generation, without rate or budget overrides."""
    _sources_unchanged()
    _require(type(expected_sha256) is str and _HASH.fullmatch(expected_sha256), "explicit session SHA-256 required")
    root = Path(directory)
    _require(root.is_dir() and not root.is_symlink(), "session requires a regular generation directory")
    raw = linguistic._read(root / "session.json", linguistic._MAX_MANIFEST_BYTES)
    _require(_sha(raw) == expected_sha256, "session manifest digest differs")
    manifest = _unique_json(raw)
    _require(type(manifest) is dict and set(manifest) == {"schema", "session", "model_manifest_sha256",
             "model_manifest_bytes", "model_directory", *_FALSE}, "session checkpoint fields differ")
    _require(manifest["schema"] == SCHEMA + "/checkpoint" and manifest["model_directory"] == "model"
             and all(manifest[name] is False for name in _FALSE), "session checkpoint profile or authority differs")
    state = manifest["session"]
    _require(type(state) is dict and set(state) == {"schema", "sources", "binding", "config", "progress", *_FALSE}
             and state["schema"] == SCHEMA and state["sources"] == _SOURCES
             and all(state[name] is False for name in _FALSE), "session source/schema/authority differs")
    _require(type(state["config"]) is dict and set(state["config"]) == {"proposal_budget", "learning_rate",
             "min_learning_rate", "max_learning_rate", "growth_factor", "shrink_factor", "max_consecutive_rejections"},
             "session configuration fields differ")
    config = _config(**state["config"])
    _require(_raw(config) == _raw(state["config"]), "session configuration numeric types differ")
    progress = state["progress"]
    _require(type(progress) is dict and set(progress) == {"proposals_used", "accepted_updates", "rejected_proposals",
             "consecutive_rejections", "next_learning_rate", "terminal_reason", "model_state_identity"},
             "session progress fields differ")
    for key in ("proposals_used", "accepted_updates", "rejected_proposals", "consecutive_rejections"):
        _require(type(progress[key]) is int and 0 <= progress[key] <= config["proposal_budget"], "invalid session counter")
    _require(progress["accepted_updates"] + progress["rejected_proposals"] == progress["proposals_used"]
             and progress["consecutive_rejections"] <= progress["rejected_proposals"], "inconsistent session counters")
    _number(progress["next_learning_rate"], "next_learning_rate", config["min_learning_rate"], config["max_learning_rate"])
    reason = progress["terminal_reason"]
    _require(reason in (None, "proposal_budget", "plateau", "minimum_learning_rate"), "invalid terminal reason")
    _require((progress["proposals_used"] == config["proposal_budget"]) == (reason == "proposal_budget"),
             "lifetime budget exhaustion differs from terminal reason")
    _require(reason != "plateau" or progress["consecutive_rejections"] >= config["max_consecutive_rejections"],
             "plateau counter differs")
    _require(progress["consecutive_rejections"] < config["max_consecutive_rejections"]
             or reason in ("plateau", "proposal_budget", "minimum_learning_rate"), "plateau bound was cleared")
    _require(reason != "minimum_learning_rate" or (progress["next_learning_rate"] == config["min_learning_rate"]
             and progress["consecutive_rejections"] > 0), "minimum-rate terminal reason differs")
    model_manifest = linguistic._read(root / "model/manifest.json", linguistic._MAX_MANIFEST_BYTES)
    _require(len(model_manifest) == manifest["model_manifest_bytes"]
             and _sha(model_manifest) == manifest["model_manifest_sha256"], "model manifest differs from session")
    _require(type(state["binding"]) is dict and state["binding"].get("profile") in _PROFILES,
             "unknown session model profile")
    model = profiles.load_training_checkpoint(root / "model", profile=state["binding"]["profile"])
    session = FeatureTrainingSession(model, samples, validation_samples=validation_samples, **config)
    _require(_raw(session.state["binding"]) == _raw(state["binding"]), "loaded session input/model binding differs")
    session._state = _raw(state)
    session._check()
    _require(linguistic._read(root / "session.json", linguistic._MAX_MANIFEST_BYTES) == raw
             and linguistic._read(root / "model/manifest.json", linguistic._MAX_MANIFEST_BYTES) == model_manifest,
             "session changed during load")
    return session


__all__ = ["SCHEMA", "FeatureTrainingSession", "load_training_session"]
