"""Opt-in prepared calls for the source-bound legacy feature training session.

Only repeated baseline/training evaluations are removed. Every proposal uses
the existing sparse update, objective, regression checks and transaction. Views
and the last accepted tuning evaluation are reused within one ``advance`` only;
there is no persistent prediction cache or change to linguistic decoding.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import time

from . import active_training as active
from . import feature_training_session as reference

SCHEMA = "legacy-prepared-feature-training/v1"
_require, _number = active._require, active._number


def _source_identity():
    info = Path(__file__).stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


_SOURCE_IDENTITY = _source_identity()
_SOURCE_HASH = reference._sha(Path(__file__).read_bytes())
_require(_source_identity() == _SOURCE_IDENTITY, "prepared trainer source changed during import")
_SOURCES = dict(reference._SOURCES, prepared_feature_training=_SOURCE_HASH)


def _sources_unchanged():
    reference._sources_unchanged()
    _require(_source_identity() == _SOURCE_IDENTITY, "prepared trainer source changed since import")


class PreparedFeatureTrainingSession(reference.FeatureTrainingSession):
    """Same persistent schedule with one preparation pass per private call.

    Complete inputs, profile/source provenance and expected weights are checked
    before every proposal. Inputs and producer identity are checked again before
    a candidate can commit. A rejected or late proposal rolls back exactly as
    in the reference session. There is no reuse across calls or checkpoint loads.
    """

    def __init__(self, *args, **kwargs):
        _sources_unchanged()
        super().__init__(*args, **kwargs)

    def _check(self):
        _sources_unchanged()
        return super()._check()

    def _check_producers_and_inputs(self, data):
        # A proposal is speculative here, so checking its weights against the
        # previous committed identity would reject every legitimate update.
        _sources_unchanged()
        self.model._require_profile()
        _require(reference._raw(reference._binding(self.model, self._training, self._tuning))
                 == reference._raw(data["binding"]),
                 "feature session input or model configuration changed")

    def advance(self, *, max_proposals=6, max_seconds=60):
        started = time.monotonic()
        _number(max_seconds, "max_seconds", 0, 600, inclusive_low=False)
        _require(type(max_proposals) is int and 1 <= max_proposals <= 256,
                 "max_proposals must be in 1..256")
        _require(self._lock.acquire(blocking=False), "feature session already has an active operation")
        deadline = started + max_seconds
        expired = lambda: time.monotonic() >= deadline
        reports = []
        before = best = None
        stopped = "call_proposal_budget"
        try:
            data = self._check()
            config, progress = data["config"], data["progress"]
            remaining = min(max_proposals, config["proposal_budget"] - progress["proposals_used"])
            if remaining and progress["terminal_reason"] is None:
                if expired():
                    stopped = "deadline"
                else:
                    before = best = active._evaluation(self.model, self._tuning)
                    if not expired():
                        active._evaluation(self.model, self._training)
                    if expired():
                        stopped = "deadline"
            for _ in range(remaining):
                if progress["terminal_reason"] is not None or stopped == "deadline":
                    break
                self._check()
                if expired():
                    stopped = "deadline"
                    break
                rate = progress["next_learning_rate"]
                transaction = self.model.state.transaction(label="prepared-active-family:1:1").begin()
                accepted, delta = False, None
                reason = "zero_update"
                try:
                    norms = self.model._apply_projection_update_batch(
                        self._training, update_targets=("family_logits",), learning_rate=rate,
                        l2_regularization=0.0, update_backend="python_sparse_batch")
                    _require(norms["finite"], "nonfinite legacy feature proposal")
                    self.model._invalidate_state_dependent_evaluator_caches()
                    if expired():
                        reason = "deadline_after_proposal"
                    elif norms["nonzero_update"]:
                        candidate = active._evaluation(self.model, self._tuning)
                        self._check_producers_and_inputs(data)
                        regressions = active.frozen._evaluation_regressions_for_training(
                            best, candidate, **active._GUARDS)
                        delta = (active.frozen._evaluation_objective_for_training(best, **active._OBJECTIVE)
                                 - active.frozen._evaluation_objective_for_training(candidate, **active._OBJECTIVE))
                        _require(math.isfinite(delta), "nonfinite proposal objective")
                        if expired():
                            reason = "deadline_after_evaluation"
                        elif not regressions and delta > 0.0:
                            transaction.commit()
                            accepted, reason, best = True, "strict", candidate
                        else:
                            reason = "regression_or_no_strict_improvement"
                finally:
                    if transaction.active:
                        transaction.rollback()
                    self.model._invalidate_state_dependent_evaluator_caches()
                # Match the reference's post-proposal producer/input check even
                # when zero/late proposals skipped candidate evaluation.
                self._check_producers_and_inputs(data)
                late = reason.startswith("deadline")
                progress["proposals_used"] += 1
                progress["accepted_updates"] += int(accepted)
                progress["rejected_proposals"] += int(not accepted)
                if not late:
                    progress["consecutive_rejections"] = 0 if accepted else progress["consecutive_rejections"] + 1
                    progress["next_learning_rate"] = (min(config["max_learning_rate"], rate * config["growth_factor"])
                        if accepted else max(config["min_learning_rate"], rate * config["shrink_factor"]))
                reports.append(dict(proposal_index=progress["proposals_used"], accepted=accepted,
                    learning_rate=rate, next_learning_rate=progress["next_learning_rate"], reason=reason,
                    objective_delta=delta, update_norm=norms["update_norm"],
                    cross_entropy_after=None if best is None else best.cross_entropy_loss))
                if progress["proposals_used"] >= config["proposal_budget"]:
                    progress["terminal_reason"] = "proposal_budget"
                elif not late and not accepted and rate <= config["min_learning_rate"]:
                    progress["terminal_reason"] = "minimum_learning_rate"
                elif progress["consecutive_rejections"] >= config["max_consecutive_rejections"]:
                    progress["terminal_reason"] = "plateau"
                progress["model_state_identity"] = self.model.state.state_identity()
                self._state = reference._raw(data)
                if late:
                    stopped = "deadline"
                    break
            self._check()
            if progress["terminal_reason"]:
                stopped = progress["terminal_reason"]
            return dict(schema=SCHEMA + "/advance", runtime_sources=dict(_SOURCES), state=self.state,
                proposal_reports=reports, proposal_count=len(reports),
                accepted_updates=sum(row["accepted"] for row in reports),
                before=None if before is None else before.to_dict(), after=None if best is None else best.to_dict(),
                stopped_reason=stopped, elapsed_seconds=time.monotonic() - started,
                deadline_scope="per-call setup included; inflight operations soft; lifetime proposals persist",
                preparation_scope="baseline and training evaluation once per advance; no cross-call reuse",
                legal_ir_bridge_names=[], legal_ir_target_count=0, legal_ir_evaluate_provers=False,
                legal_ir_parallel_workers=1, training_executed=bool(reports), **reference._FALSE)
        except BaseException:
            self._failed = True
            raise
        finally:
            self._lock.release()

    def save(self, directory):
        """Publish a new runtime envelope around an unchanged reference bundle.

        The final prepared-session marker is exclusive and source-bound. A
        failed new generation can remain incomplete; prior generations remain
        intact. This is atomic local publication, not power-loss durability.
        """
        started = time.monotonic()
        _require(self._lock.acquire(blocking=False), "feature session already has an active operation")
        try:
            self._check()
            root = Path(directory)
            root.mkdir(parents=True, exist_ok=False)
            # Preserve the reference checkpoint writer and schema exactly, with
            # its own lock, while this session's private writer lock stays held.
            original = reference.FeatureTrainingSession(self.model, self._training,
                validation_samples=self._tuning, **self.state["config"])
            original._state = self._state
            saved = original.save(root / "reference")
            self._check()
            payload = reference._raw(dict(schema=SCHEMA + "/checkpoint", runtime_sources=dict(_SOURCES),
                reference_directory="reference", reference_sha256=saved["sha256"], **reference._FALSE))
            pending = root / "prepared-session.pending.json"
            with pending.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self._check()
            os.link(pending, root / "prepared-session.json")
            pending.unlink()
            return dict(path=str(root.resolve()), sha256=reference._sha(payload), bytes=len(payload),
                elapsed_seconds=time.monotonic()-started, model_core_bytes=saved["model_core_bytes"],
                publication_scope="local completed prepared-session checkpoint generation", **reference._FALSE)
        finally:
            self._lock.release()


def load_training_session(directory, *, expected_sha256, samples, validation_samples):
    """Load an explicitly pinned prepared generation, without scheduler overrides."""
    _sources_unchanged()
    _require(type(expected_sha256) is str and reference._HASH.fullmatch(expected_sha256),
             "explicit prepared-session SHA-256 required")
    root = Path(directory)
    _require(root.is_dir() and not root.is_symlink(), "prepared session requires a regular generation directory")
    raw = reference.linguistic._read(root / "prepared-session.json", reference.linguistic._MAX_MANIFEST_BYTES)
    _require(reference._sha(raw) == expected_sha256, "prepared session manifest digest differs")
    envelope = reference._unique_json(raw)
    _require(type(envelope) is dict and set(envelope) == {"schema", "runtime_sources", "reference_directory",
             "reference_sha256", *reference._FALSE}, "prepared session checkpoint fields differ")
    _require(envelope["schema"] == SCHEMA + "/checkpoint" and envelope["runtime_sources"] == _SOURCES
             and envelope["reference_directory"] == "reference"
             and all(envelope[name] is False for name in reference._FALSE),
             "prepared session source/schema/authority differs")
    original = reference.load_training_session(root / "reference", expected_sha256=envelope["reference_sha256"],
                                               samples=samples, validation_samples=validation_samples)
    result = PreparedFeatureTrainingSession(original.model, samples, validation_samples=validation_samples,
                                            **original.state["config"])
    result._state = original._state
    result._check()
    _require(reference.linguistic._read(root / "prepared-session.json", reference.linguistic._MAX_MANIFEST_BYTES) == raw,
             "prepared session changed during load")
    return result


__all__ = ["PreparedFeatureTrainingSession", "load_training_session", "SCHEMA"]
