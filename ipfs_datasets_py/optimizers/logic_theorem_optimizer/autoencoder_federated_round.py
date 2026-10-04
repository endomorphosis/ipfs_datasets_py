"""Bounded local reference rounds for independently trained Legal modal clients.

Remote workers can call the same worker API and exchange binary update
artifacts. This reference runner executes clients sequentially, with private
models, and writes a complete provisional aggregate. It starts no transport,
publishes nothing and does not select an inference head.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

from .autoencoder_federated import AggregateCandidate, FederatedRound, aggregate_round
from .autoencoder_federated_update_codec import read_client_update, write_client_update
from .autoencoder_federated_worker import train_modal_client


ROUND_REPORT_SCHEMA = "legal-federated-local-round/v1"
_MAX_REPORT_BYTES = 1_048_576


def _raw(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"
    if len(raw) > _MAX_REPORT_BYTES:
        raise ValueError("federated round metadata exceeds the 1 MiB bound")
    return raw


def _write(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


@dataclass(frozen=True, slots=True)
class LocalModalRoundResult:
    """Owned aggregate and persisted artifact receipts, without selection authority."""

    candidate: AggregateCandidate
    directory: str
    _report_json: bytes

    @property
    def report(self):
        return json.loads(self._report_json)

    @property
    def checkpoint_path(self):
        return Path(self.directory) / "aggregate.checkpoint.bin"

    def load_updates(self, round_spec):
        """Rehash and reload all persisted updates against the approved round."""
        if self.report["round_sha256"] != round_spec.round_sha256:
            raise ValueError("saved round differs from the requested federated round")
        return tuple(read_client_update(Path(self.directory) / item["file"], round_spec,
            expected_sha256=item["artifact"]["sha256"],
            expected_cidv1=item["artifact"]["cidv1"])
            for item in self.report["clients"])


def execute_local_modal_round(
    adapter, round_spec: FederatedRound, client_data_paths: dict,
    output_directory: str | Path, *, epochs=1, learning_rate=.01,
    max_seconds=60, max_line_search_attempts=1, compute_device="cpu",
) -> LocalModalRoundResult:
    """Train each approved local client and materialize its shared-model aggregate.

    Every client starts from the adapter's exact base. Approved data byte hashes
    and counts are checked by ``train_modal_client``. The caller provisions a
    fresh directory; failure preserves completed client artifacts for inspection
    and propagates the error, without emitting a completed round report.

    ``max_seconds`` applies separately to each client training call and is soft
    at numerical boundaries. It is not an end-to-end round deadline. Output is
    a complete *modal core* checkpoint, never a packaged formula head.
    """
    # Lazy type import keeps ordinary module import free of model dependencies.
    from .autoencoder_federated_modal import ModalCheckpoint

    if type(adapter) is not ModalCheckpoint:
        raise ValueError("a verified ModalCheckpoint adapter is required")
    round_spec = adapter.validate_round(round_spec)
    approved = {client.client_id for client in round_spec.clients}
    if type(client_data_paths) is not dict or set(client_data_paths) != approved:
        raise ValueError("exactly one data path for every approved client is required")
    if len(approved) > 256:
        raise ValueError("local reference rounds support at most 256 clients")
    if type(epochs) is not int or not 1 <= epochs <= min(64, round_spec.max_local_steps):
        raise ValueError("epochs must fit the approved local-step budget")
    # Bound the policy before creating the output namespace. Worker option and
    # data validation remains authoritative before numerical training starts.
    round_raw = _raw(round_spec.manifest)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    _write(directory / "round.json", round_raw)
    updates, reports = [], []
    for index, client in enumerate(round_spec.clients):
        update, report = train_modal_client(adapter, round_spec, client.client_id,
            client_data_paths[client.client_id], epochs=epochs, learning_rate=learning_rate,
            max_seconds=max_seconds, max_line_search_attempts=max_line_search_attempts,
            compute_device=compute_device)
        filename = f"client-{index:04d}.update.bin"
        artifact = write_client_update(directory / filename, round_spec, update)
        # The actual artifact readers also serve the owner/remote exchange path.
        updates.append(read_client_update(directory / filename, round_spec,
            expected_sha256=artifact["sha256"], expected_cidv1=artifact["cidv1"]))
        reports.append({"client_id": client.client_id, "file": filename,
                        "artifact": artifact, "training": report})
    candidate = aggregate_round(round_spec, adapter.parameters, updates)
    materialized = adapter.materialize(round_spec, candidate,
                                        directory / "aggregate.checkpoint.bin")
    report = {"schema": ROUND_REPORT_SCHEMA, "round_sha256": round_spec.round_sha256,
        "model_id": round_spec.model_id, "lineage_id": round_spec.lineage_id,
        "dimension": round_spec.dimension, "execution": "sequential_private_local_clients",
        "clients": reports, "aggregation": candidate.provenance,
        "candidate_sha256": candidate.candidate_sha256, "checkpoint": materialized,
        "complete": True, "qualified": False, "admitted": False,
        "promotion_performed": False, "publication_performed": False}
    raw = _raw(report)
    _write(directory / "result.json", raw)
    return LocalModalRoundResult(candidate, str(directory), raw)


__all__ = ["LocalModalRoundResult", "ROUND_REPORT_SCHEMA", "execute_local_modal_round"]
