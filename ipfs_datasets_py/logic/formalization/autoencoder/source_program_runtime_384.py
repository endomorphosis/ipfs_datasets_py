"""Opt-in Security decoder consumer with complete source effects and Lake checks.

Uses existing exact-checkpoint loaders and pinned embedding assets. The public
training API and historical benchmark producer bytes are left unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

FALSE = dict(qualified=False, admitted=False, proof_authority=False, execution_authority=False,
    completion_authority=False, source_semantics_verified=False, claim_proved=False,
    security_specification_inferred=False, whole_program_semantics_verified=False,
    publication_performed=False)


class SourceProgramDecoder384:
    """Decode with real loaded weights, then check the unchanged candidate."""
    def __init__(self, runtime, *, checkpoint_sha256):
        if runtime.describe().get("domain_id") != "security_ir":
            raise ValueError("SecurityIR decoder required")
        if type(checkpoint_sha256) is not str or re.fullmatch(r"[a-f0-9]{64}", checkpoint_sha256) is None:
            raise ValueError("exact checkpoint SHA256 required")
        self.runtime = runtime
        self.checkpoint_sha256 = checkpoint_sha256

    def describe(self):
        from .security.source_program_binding_384_v2 import SCHEMA
        return {**self.runtime.describe(), "source_qualification_schema": SCHEMA,
            "checkpoint_sha256": self.checkpoint_sha256, "automatic_lake_build": False, **FALSE}

    def infer(self, rows, **options):
        from .security.source_program_binding_384_v2 import qualify_source_candidate
        # The underlying runtime enforces closed target-free rows and actual
        # 384D vectors. Source strings are evidence, not decoder side features.
        report = deepcopy(self.runtime.infer(rows, **options))
        if report.get("domain_id") != "security_ir":
            raise ValueError("SecurityIR decoder report required")
        sources = {row["id"]: row["source_text"] for row in rows}
        if len(sources) != len(rows) or len(report["rows"]) != len(rows) or {
                row["id"] for row in report["rows"]} != set(sources):
            raise ValueError("decoder source identity mismatch")
        report.update(FALSE)
        for row in report["rows"]:
            row.update(FALSE)
            source = sources[row["id"]]
            if row["source_sha256"] != hashlib.sha256(source.encode()).hexdigest():
                raise ValueError("decoder source hash mismatch")
            if row.get("candidate_ir") is None:
                continue
            qualification = qualify_source_candidate(source, row["candidate_ir"])
            row["source_contract"] = qualification
            row["continue_planning"] = True
            if qualification["status"] != "qualified":
                row["status"] = "fail_open_source_contract_" + qualification["status"]
        report.update(source_contracts_checked=True, checkpoint_sha256=self.checkpoint_sha256)
        return report

    def infer_texts(self, texts, *, snapshot_path=None, **options):
        from .source_embeddings_384 import embed_texts
        vectors = embed_texts(texts, snapshot_path=snapshot_path)
        return self.infer([dict(id="input-" + str(index), source_text=text, embedding=vector)
            for index, (text, vector) in enumerate(zip(texts, vectors))], **options)


def load_source_program_decoder_384(path, *, expected_sha256, decoder="structured"):
    """Load exact local Security weights; select structured or sequence v2."""
    if decoder == "structured":
        from .structured_source_384 import load_checkpoint
    elif decoder == "sequence_v2":
        from .source_training_v2 import load_checkpoint
    else:
        raise ValueError("unsupported source program decoder")
    runtime = load_checkpoint(path, expected_sha256=expected_sha256, expected_domain="security_ir")
    return SourceProgramDecoder384(runtime, checkpoint_sha256=expected_sha256)


def build_decoded_source_program_lake(report, source_rows, *, lake_executable, timeout_seconds=60, output_directory=None):
    """Compile exact decoded candidates with a fresh source qualification replay.

    Source rows contain exactly id/source_text. This API does not train, change
    predictions, or trust an attached source_contract dictionary as evidence.
    """
    from .source_program_lake_384 import build_source_program_lake
    if report.get("domain_id") != "security_ir":
        raise ValueError("SecurityIR decoder report required")
    if type(source_rows) is not list or not source_rows or any(
            type(row) is not dict or set(row) != {"id", "source_text"}
            or type(row["id"]) is not str or type(row["source_text"]) is not str for row in source_rows):
        raise ValueError("closed source rows required")
    sources = {row["id"]: row["source_text"] for row in source_rows}
    if len(sources) != len(source_rows) or len(report["rows"]) != len(source_rows) or {
            row["id"] for row in report["rows"]} != set(sources):
        raise ValueError("decoded source identity mismatch")
    inputs = []
    for row in report["rows"]:
        text = sources[row["id"]]
        if row["source_sha256"] != hashlib.sha256(text.encode()).hexdigest():
            raise ValueError("decoded source hash mismatch")
        inputs.append(dict(id=row["id"], source_text=text, candidate_ir=deepcopy(row["candidate_ir"])))
    return build_source_program_lake(inputs, lake_executable=lake_executable,
        timeout_seconds=timeout_seconds, output_directory=output_directory)


__all__ = ["load_source_program_decoder_384", "SourceProgramDecoder384", "build_decoded_source_program_lake"]
