"""Derived pure receipt/source preparation inside the existing custody owner.

This module factors only the pre-numerical inventory preparation from the
fixed receipt-bound CONTENT source owner. The unchanged owner remains the
operation controller and supplies bounded values, input/source/receipt fences,
checkpoint inspection and complete-population validation. This private seam
must execute inside that owner's `_operation`; its return values are not a
portable prepared session and do not carry execution or semantic authority.

The catalog caller separately pins this helper and the unchanged custody
owner. No CONTENT generation, model restoration, encoder or optimizer occurs
here. Historical CONTENT sources, reports and qualification remain unchanged.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from ipfs_datasets_py.logic.formalization.autoencoder import (
    legal_compact_receipt_bound_source_generation_v1 as custody,
)

CUSTODY_SOURCE_SHA256 = "d91475f89dcba669ebc2a778f1dbc18f7eacbc955661f82f0a288de2bb3750f1"


def _prepare_inventory(data, loaded, fence, references, source_checks, frozen, source_resolver, offered=None):
    modules = loaded[2]
    conditioner, source, generation, codec = (modules[key] for key in
        ("conditioning", "source", "generation", "receipt"))
    custody._need(callable(source_resolver), "source resolver required")
    custody._need(type(data["max_new_tokens"]) is int and 1 <= data["max_new_tokens"] <= custody.MAX_NEW_TOKENS,
          "max_new_tokens must be a plain integer in 1..12")
    population = custody._population(data["population_raw"], data["expected_population_sha256"])
    reference_rows = custody._rows(data["rows"], population)
    checkpoint_preflight = custody._checkpoint(data["checkpoint"], data["expected_checkpoint_sha256"], generation)
    fence()
    # Public receipt validation retains full producer input order and status
    # commitments, including unselected inputs; no producer/encoder is invoked.
    receipt_inventory, receipts_by_path = [], {}
    for reference in reference_rows:
        _, witness = custody._read_identity(Path(reference["path"]), reference["sha256"], reference["bytes"], custody.MAX_RECEIPT_BYTES)
        references.append((reference, witness))
        receipt = codec.load_embedding_production_receipt(reference["path"], expected_sha256=reference["sha256"],
            expected_size_bytes=reference["bytes"], resolver=source_resolver)
        source_checks.append(lambda receipt=receipt: receipt.validate_sources(source_resolver))
        payload = custody._copy(receipt.to_dict(), custody.MAX_RECEIPT_BYTES)
        custody._need(receipt.native_execution_profile, "native receipt execution profile required")
        receipts_by_path[reference["path"]] = payload
        receipt_inventory.append({"receipt": reference, "payload_sha256": custody._digest(payload, custody.MAX_RECEIPT_BYTES),
            "input_count": len(payload["inputs"]), "inputs": payload["inputs"],
            "inputs_sha256": custody._digest(payload["inputs"], custody.MAX_RECEIPT_BYTES), "status_counts": payload["status_counts"],
            "results": [{"index": index, "input_id": item["input_id"], "status": item["status"],
                "tokens_record_sha256": custody._digest(item["tokens"]), "vector_record_sha256": custody._digest(item["vector"])}
                for index, item in enumerate(payload["results"])],
            "native_execution_record_present": True, "encoder_executed_by_adapter": False})
        fence()
    conditionings, source_reports, outer_contexts, inner_rows = [], [], [], []
    outer_to_inner, inner_to_outer, inner_occurrences = [], [], []
    # Prepare and replay every outer occurrence, including unavailable vectors,
    # before returning to the caller that owns any later numerical dispatch.
    for index, (row, occurrence) in enumerate(zip(data["rows"], population["rows"])):
        prepared = conditioner.prepare_compact_source_conditioning_v1(row["source_request"], row["receipt_ref"],
            expected_source_request_sha256=row["expected_source_request_sha256"], input_id=row["input_id"],
            source_resolver=source_resolver)
        prepared_sha = conditioner.compact_source_binding_sha256(prepared)
        # The public conditioner hash operation also rechecks its fixed mutable
        # nine-asset manifest; retain that fence through final serialization.
        source_checks.append(lambda prepared=prepared, prepared_sha=prepared_sha:
            custody._need(conditioner.compact_source_binding_sha256(prepared) == prepared_sha,
                  "public conditioning report/fixed asset profile changed during outer operation"))
        custody._need(prepared["occurrence_id"] == occurrence["id"] and prepared["input_id"] == row["input_id"]
              and prepared["input"] == row["source_request"]["input"]
              and prepared["source_span"] == row["source_request"]["input"]["source"]
              and prepared["source_sha256"] == occurrence["source_sha256"]
              and prepared["source_request_sha256"] == row["expected_source_request_sha256"]
              and prepared["receipt"] == row["receipt_ref"], "public conditioning original source join differs")
        payload = receipts_by_path[row["receipt_ref"]["path"]]
        selected = prepared["receipt_input_index"]
        custody._need(type(selected) is int and 0 <= selected < len(payload["inputs"])
              and prepared["input"] == payload["inputs"][selected]
              and prepared["receipt_input_count"] == len(payload["inputs"])
              and prepared["receipt_status_counts"] == payload["status_counts"]
              and prepared["status"] == payload["results"][selected]["status"],
              "public conditioning differs from complete receipt population")
        conditionings.append({"id": row["id"], "report": prepared, "report_sha256": prepared_sha})
        nominated = source.prepare_source_context_v1(row["source_raw"], row["catalog_raw"],
            expected_source_sha256=row["expected_source_sha256"], expected_catalog_sha256=row["expected_catalog_sha256"])
        report_sha = source.source_context_sha256(nominated)
        nominated = source.validate_source_context_v1(nominated, row["source_raw"], row["catalog_raw"],
            expected_report_sha256=report_sha, expected_source_sha256=row["expected_source_sha256"],
            expected_catalog_sha256=row["expected_catalog_sha256"])
        custody._need(source.source_context_sha256(nominated) == report_sha
              and nominated["status"] in ("nominated", "ambiguous", "unavailable"), "public source context replay differs")
        source_reports.append({"id": row["id"], "report": nominated, "report_sha256": report_sha})
        context_raw = custody._wire(nominated["context"], custody.MAX_CATALOG_BYTES) if nominated["status"] == "nominated" else None
        outer_contexts.append({"id": row["id"], "catalog_sha256": row["expected_catalog_sha256"],
            "source_report_sha256": report_sha,
            "compact_context_raw_sha256": hashlib.sha256(context_raw).hexdigest() if context_raw is not None else None,
            "compact_context_sha256": nominated["context_sha256"]})
        if prepared["status"] == "embedded":
            custody._need(type(prepared["conditioning"]) is list and len(prepared["conditioning"]) == 384
                  and prepared["source_receipt_binding_verified"] is True
                  and prepared["source_bytes_verified"] is True,
                  "embedded public receipt vector/custody missing")
            # Preserve native vector values and their original JSON hash. The
            # existing trained caller's unchanged finite384 bound still applies.
            custody._need(all(type(number) is float and math.isfinite(number) and abs(number) <= 1e8
                      for number in prepared["conditioning"])
                  and custody._digest(prepared["conditioning"]) == prepared["conditioning_sha256"],
                  "native conditioning is outside unchanged trained caller profile")
            outer_to_inner.append(len(inner_rows)); inner_to_outer.append(index)
            inner_occurrences.append(occurrence)
            inner_rows.append({"id": row["id"], "source_raw": row["source_raw"], "catalog_raw": row["catalog_raw"],
                "expected_source_sha256": row["expected_source_sha256"],
                "expected_catalog_sha256": row["expected_catalog_sha256"],
                "conditioning": prepared["conditioning"], "expected_conditioning_sha256": prepared["conditioning_sha256"]})
        else:
            custody._need(prepared["status"] in ("missing_input", "token_limit_exceeded")
                  and prepared["conditioning"] is None and prepared["conditioning_sha256"] is None
                  and prepared["native_vector_bits_sha256"] is None
                  and prepared["source_receipt_binding_verified"] is False,
                  "unavailable receipt conditioning must stay null/unbound")
            outer_to_inner.append(None)
        fence()
    mapping = {"outer_to_inner": outer_to_inner, "inner_to_outer": inner_to_outer}
    inner_population, inner_raw = None, None
    if inner_rows:
        selection = {"schema": "legal-receipt-bound-inner-selection/v1",
            "outer_population_sha256": data["expected_population_sha256"],
            "outer_selection_sha256": population["selection_sha256"], "mapping": mapping,
            "conditioning_reports_sha256": custody._digest(conditionings), "source_reports_sha256": custody._digest(source_reports)}
        inner_population = {"schema": population["schema"], "partition": population["partition"],
                            "selection_sha256": custody._digest(selection), "rows": inner_occurrences}
        inner_raw = custody._wire(inner_population, custody.MAX_POPULATION_BYTES)
    settings = {"max_new_tokens": data["max_new_tokens"], "max_new_tokens_limit": custody.MAX_NEW_TOKENS,
        "max_selected_rows": custody.MAX_ROWS, "prefix_ids": [1], "prefix_origin": "bos_seed",
        "context_origin": "caller_supplied_unverified", "conditioning_dimension": 384,
        "conditioning_space": "raw_native_gte_small384", "encoder_executed_by_adapter": False}
    pure = {"population": population, "population_sha256": data["expected_population_sha256"],
        "checkpoint_sha256": data["expected_checkpoint_sha256"], "checkpoint_preflight": checkpoint_preflight,
        "receipt_inventory": receipt_inventory, "source_conditionings": conditionings, "source_reports": source_reports,
        "mapping": mapping, "inner_population": inner_population,
        "inner_population_utf8": inner_raw.decode("utf-8") if inner_raw is not None else None,
        "inner_population_sha256": hashlib.sha256(inner_raw).hexdigest() if inner_raw is not None else None,
        "settings": settings}
    pure["pre_generation_sha256"] = custody._digest(pure)
    frozen.append((pure, custody._wire(pure, custody.MAX_REPORT_BYTES)))
    if offered is not None:
        custody._need(all(key in offered and custody._wire(offered[key]) == custody._wire(pure[key]) for key in custody._PURE_FIELDS),
              "offered report differs from original pre-generation inventory")
    fence()
    return pure, inner_rows, outer_contexts
