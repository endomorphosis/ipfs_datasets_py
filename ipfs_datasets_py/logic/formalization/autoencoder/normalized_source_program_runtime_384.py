"""Opt-in hybrid AST-normalized source views with unchanged learned decoders.

Only embedding input is normalized. The numeric model still predicts every IR
candidate, and source qualification sees the original untouched text. This is
an explicitly different input contract from raw-source decoder inference.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from .security.source_normalization_384 import HYBRID_PROFILE, INPUT_VIEW, normalize_source
from .source_program_runtime_384 import FALSE


class NormalizedSourceProgramDecoder384:
    """Embed deduplicated canonical views, decode, then check original sources."""
    def __init__(self, decoder):
        if decoder.describe().get("domain_id") != "security_ir":
            raise ValueError("SecurityIR source decoder required")
        self.decoder = decoder

    def describe(self):
        return {**self.decoder.describe(), "hybrid_profile": HYBRID_PROFILE,
            "input_view": INPUT_VIEW, "embedding_input": "guarded_normalized_source_or_unchanged_unsupported_source",
            "source_qualification_input": "original_untouched_source",
            "target_dependent_normalization": False, "prediction_repair_performed": False,
            "raw_decoder_quality_metric": False, **FALSE}

    def infer_texts(self, texts, *, snapshot_path=None, **options):
        from .source_embeddings_384 import embed_texts
        if type(texts) not in (list, tuple) or not 1 <= len(texts) <= 128 or any(
                type(text) is not str or not text.strip() or len(text) > 16384 for text in texts):
            raise ValueError("one to 128 bounded nonempty source texts required")
        sources = list(texts)
        normalizations = [normalize_source(text) for text in sources]
        unique_views, positions, view_indices = [], {}, []
        for receipt in normalizations:
            view = receipt["normalized_source_text"]
            if view not in positions:
                positions[view] = len(unique_views)
                unique_views.append(view)
            view_indices.append(positions[view])
        vectors = embed_texts(unique_views, snapshot_path=snapshot_path)
        if len(vectors) != len(unique_views):
            raise ValueError("normalized embedding view count differs")
        # No target, AST signature or normalization metadata is a model feature.
        # Provenance text remains original so qualification cannot bless a
        # correct view while quietly losing the original source semantics.
        inputs = [dict(id="input-" + str(index), source_text=text,
            embedding=deepcopy(vectors[view_indices[index]])) for index, text in enumerate(sources)]
        report = deepcopy(self.decoder.infer(inputs, **options))
        by_id = {row["id"]: receipt for row, receipt in zip(inputs, normalizations)}
        if len(report["rows"]) != len(inputs) or {row["id"] for row in report["rows"]} != set(by_id):
            raise ValueError("normalized decoder output identity mismatch")
        for row in report["rows"]:
            receipt = by_id[row["id"]]
            if row["source_sha256"] != receipt["original_source_sha256"]:
                raise ValueError("normalized decoder original source hash mismatch")
            row.update(source_normalization=deepcopy(receipt), input_view=INPUT_VIEW,
                hybrid_profile=HYBRID_PROFILE, target_dependent_normalization=False,
                prediction_repair_performed=False, **FALSE)
        report.update(input_view=INPUT_VIEW, hybrid_profile=HYBRID_PROFILE,
            input_count=len(inputs), unique_embedding_views=len(unique_views),
            embedding_views_reused=len(inputs) - len(unique_views),
            normalization_status_counts=dict(Counter(row["status"] for row in normalizations)),
            normalization_applied_count=sum(row["normalization_applied"] for row in normalizations),
            target_dependent_normalization=False, prediction_repair_performed=False,
            original_sources_used_for_qualification=True, raw_decoder_quality_metric=False, **FALSE)
        return report


def load_normalized_source_program_decoder_384(path, *, expected_sha256, decoder="structured"):
    """Load an exact checkpoint and explicitly opt into the hybrid input view."""
    from .source_program_runtime_384 import load_source_program_decoder_384
    loaded = load_source_program_decoder_384(path, expected_sha256=expected_sha256, decoder=decoder)
    return NormalizedSourceProgramDecoder384(loaded)


__all__ = ["NormalizedSourceProgramDecoder384", "load_normalized_source_program_decoder_384"]
