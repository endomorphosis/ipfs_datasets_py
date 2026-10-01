"""Read-only, exact-family/profile coverage audit for native auxiliary heads.

A native projection, a covered numerical feature block, source decoding, and
semantic correctness are different claims. This module audits only the first
two. Callers choose an explicit coverage floor; profiles never alias into
families and one family cannot silently satisfy another. Saved JSON receipts
establish internal consistency, not authentication or checkpoint execution.
"""
from __future__ import annotations

import hashlib
import json

from . import family_training as native
from . import family_training_v2 as native_v2

SCHEMA = "native-family-coverage-audit/v1"
SPLITS = ("training", "tuning", "heldout")
MAX_ROWS = 384
MAX_TOTAL_BYTES = 128 * 1024 * 1024
FALSE = {"qualified": False, "admitted": False, "formalized": False,
         "roundtrip_ok": False, "proof_authority": False,
         "source_semantics_verified": False, "source_decoder_trained": False,
         "checkpoint_executed_by_audit": False, "lake_executed": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _names(value, known, message):
    _require(type(value) in (list, tuple) and len(value) <= len(known)
             and all(type(item) is str and item in known for item in value)
             and len(set(value)) == len(value), message)
    return set(value)


def _numeric_coverage(value, reports):
    """Validate coverage positions against actual ready native targets."""
    _require(type(value) is dict and set(value) == {"projections", "untrained_projection_ids"},
             "closed numerical coverage mapping required")
    ready = {(i, target["projection_id"]): target for i, report in enumerate(reports)
             for target in report["projections"] if target["ready_for_training"]}
    ids = {name for _, name in ready}
    unseen = _names(value["untrained_projection_ids"], ids, "unknown or duplicate untrained projection")
    _require(type(value["projections"]) is list and len(value["projections"]) <= len(ready),
             "bounded numerical projection coverage required")
    rows, seen = [], set()
    for row in value["projections"]:
        _require(type(row) is dict and set(row) == {
            "row", "projection_id", "known_atoms", "unknown_atoms", "has_coverage"},
            "closed numerical coverage row required")
        _require(type(row["row"]) is int and type(row["projection_id"]) is str,
                 "typed numerical coverage location required")
        key = (row["row"], row["projection_id"])
        _require(key in ready and key not in seen and key[1] not in unseen,
                 "numerical coverage must identify one actual ready projection")
        _require(all(type(row[k]) is int and 0 <= row[k] <= 2**53
                     for k in ("known_atoms", "unknown_atoms"))
                 and type(row["has_coverage"]) is bool
                 and row["has_coverage"] == (row["known_atoms"] > 0),
                 "finite nonnegative atom counts and consistent numerical mask required")
        seen.add(key)
        rows.append((key, row, ready[key]))
    missing = sorted({name for _, name in ready if name not in unseen}
                     - {name for _, name in seen})
    return rows, sorted(unseen), missing


def audit_family_training_coverage(domain_id, *, training_reports, tuning_reports,
        heldout_reports, required_families, required_profiles,
        numerical_training_report=None, numerical_heldout_report=None,
        minimum_sources_per_split=1):
    """Inventory every canonical family and enforce a declared coverage floor.

    ``required_profiles`` contains exact ``{family_id, profile}`` mappings.
    At least ``minimum_sources_per_split`` distinct rows must cover each floor
    entry on all three splits. Numerical receipts are optional, but their
    absence cannot pass the combined floor. The native numerical training
    report supplies ``training_coverage`` and ``validation_coverage``; its
    report-list digests must match these exact inputs. An inference report
    supplies ``coverage`` and must name the same domain. Its lack of a source
    report-list digest is explicitly retained as an evidence limitation.

    No source input replay, model loading, training, inference, or Lake runs
    occur here. Source/group split ownership and checkpoint execution remain
    the caller's responsibility. Every returned object is freshly allocated.
    """
    _require(domain_id in native.DOMAINS, "supported explicit domain required")
    _require(type(minimum_sources_per_split) is int and 1 <= minimum_sources_per_split <= MAX_ROWS,
             "bounded positive minimum sources required")
    catalog = native_v2.family_training_catalog_v2(domain_id)
    known = {row["family_id"] for row in catalog["family_inventory"]}
    required = _names(required_families, known, "unique canonical required families required; aliases are not accepted")
    _require(type(required_profiles) in (list, tuple) and len(required_profiles) <= 256,
             "bounded explicit required profile list required")
    profiles = set()
    for row in required_profiles:
        _require(type(row) is dict and set(row) == {"family_id", "profile"}
                 and type(row["family_id"]) is str and row["family_id"] in known
                 and type(row["profile"]) is str and 0 < len(row["profile"]) <= 256
                 and row["profile"] == row["profile"].strip(),
                 "canonical family and exact nonempty profile required")
        pair = (row["family_id"], row["profile"])
        _require(pair not in profiles, "duplicate required family/profile")
        profiles.add(pair)
    _require(required or profiles, "nonempty explicit coverage floor required")
    batches = {"training": training_reports, "tuning": tuning_reports, "heldout": heldout_reports}
    consumed, identities, source_hashes, report_digests = 0, {}, {}, {}
    descriptors = {}
    for split, reports in batches.items():
        _require(type(reports) in (list, tuple) and 1 <= len(reports) <= MAX_ROWS,
                 "bounded nonempty reports required for each split")
        for report in reports:
            _require(type(report) is dict and report.get("domain_id") == domain_id,
                     "one native domain per audit required")
            consumed += len(_raw(report))
            _require(consumed <= MAX_TOTAL_BYTES, "audit input byte bound exceeded")
            if report.get("schema") == native.SCHEMA:
                native.validate_family_training_report(report)
            else:
                native_v2.validate_family_training_report_v2(report)
            for key, observed in (("source_digest", identities), ("source_sha256", source_hashes)):
                value = report.get(key)
                if value is not None:
                    _require(value not in observed, "duplicate or overlapping native source across splits: " + key)
                    observed[value] = split
            for target in report["projections"]:
                name = target["projection_id"]
                descriptor = tuple(target.get(key) for key in
                    ("logic_family", "profile", "representation_kind", "producer_id"))
                _require(name not in descriptors or descriptors[name] == descriptor,
                         "projection descriptor differs across splits")
                descriptors[name] = descriptor
        report_digests[split] = _sha(reports)

    numeric, unseen, omitted = {}, {}, {}
    trained, training_executed = set(), None
    receipt_hashes = {}
    if numerical_training_report is not None:
        receipt = numerical_training_report
        _require(type(receipt) is dict and receipt.get("domain_id") == domain_id,
                 "same-domain numerical training receipt required")
        _require(receipt.get("training_reports_sha256") == report_digests["training"]
                 and receipt.get("validation_reports_sha256") == report_digests["tuning"],
                 "numerical training receipt must bind exact training and tuning reports")
        _require(type(receipt.get("training_executed")) is bool,
                 "explicit numerical training execution flag required")
        _require(all(receipt.get(key) is False for key in ("qualified", "admitted", "formalized")),
                 "numerical evidence cannot grant qualification")
        trained = _names(receipt.get("trained_logic_families"), known,
                         "unique canonical numerical family identities required")
        observed = {target["logic_family"] for report in training_reports
                    for target in report["projections"] if target["ready_for_training"]}
        _require(trained <= observed, "numerical family lacks ready training target")
        training_executed = receipt["training_executed"]
        receipt_hashes["training"] = _sha(receipt)
        for split, key in (("training", "training_coverage"), ("tuning", "validation_coverage")):
            numeric[split], unseen[split], omitted[split] = _numeric_coverage(receipt.get(key), batches[split])
    if numerical_heldout_report is not None:
        receipt = numerical_heldout_report
        _require(type(receipt) is dict and receipt.get("domain_id") == domain_id,
                 "same-domain numerical heldout receipt required")
        _require(all(receipt.get(key) is False for key in ("qualified", "admitted", "formalized")),
                 "numerical evidence cannot grant qualification")
        numeric["heldout"], unseen["heldout"], omitted["heldout"] = _numeric_coverage(receipt.get("coverage"), heldout_reports)
        receipt_hashes["heldout"] = _sha(receipt)
    for receipt in (numerical_training_report, numerical_heldout_report):
        if receipt is not None:
            consumed += len(_raw(receipt))
            _require(consumed <= MAX_TOTAL_BYTES, "audit input byte bound exceeded")

    def coverage(family, profile=None):
        result = {}
        for split, reports in batches.items():
            targets = [(i, target) for i, report in enumerate(reports) for target in report["projections"]
                       if target["logic_family"] == family and (profile is None or target.get("profile") == profile)]
            ready = [(i, target) for i, target in targets if target["ready_for_training"]]
            fitted = [(key, row) for key, row, target in numeric.get(split, [])
                      if target["logic_family"] == family and (profile is None or target.get("profile") == profile)]
            numerical_rows = {key[0] for key, row in fitted if row["has_coverage"]}
            result[split] = {"source_count": len(reports), "target_count": len(targets),
                "ready_target_count": len(ready), "ready_source_count": len({i for i, _ in ready}),
                "projection_ids": sorted({target["projection_id"] for _, target in targets}),
                "numerical_evidence_supplied": split in numeric,
                "numerically_covered_source_count": len(numerical_rows) if split in numeric else None,
                "known_atom_count": sum(row["known_atoms"] for _, row in fitted) if split in numeric else None,
                "unknown_atom_count": sum(row["unknown_atoms"] for _, row in fitted) if split in numeric else None,
                "frontier_reasons": sorted({row["reason"] for report in reports for row in report["frontier"]
                                            if row.get("family_id") == family and type(row.get("reason")) is str})}
        return result

    families = []
    for descriptor in catalog["family_inventory"]:
        family = descriptor["family_id"]
        families.append({**descriptor, "required": family in required,
            "reported_as_numerically_trained": family in trained if numerical_training_report is not None else None,
            "splits": coverage(family)})
    observed_profiles = {(target["logic_family"], target["profile"]) for reports in batches.values()
                         for report in reports for target in report["projections"] if target.get("profile") is not None}
    profile_inventory = [{"family_id": family, "profile": profile, "required": (family, profile) in profiles,
                          "splits": coverage(family, profile)} for family, profile in sorted(observed_profiles | profiles)]
    floor = []
    for family, profile in sorted([(family, "") for family in required] + list(profiles)):
        counts = coverage(family, profile or None)
        missing_native = [split for split, count in counts.items() if count["ready_source_count"] < minimum_sources_per_split]
        missing_numerical = [split for split, count in counts.items()
                             if count["numerically_covered_source_count"] is None
                             or count["numerically_covered_source_count"] < minimum_sources_per_split]
        numerical_passed = not missing_numerical and family in trained and training_executed is True
        floor.append({"family_id": family, "profile": profile or None,
            "missing_native_splits": missing_native, "missing_numerical_splits": missing_numerical,
            "projection_floor_satisfied": not missing_native,
            "numerical_floor_satisfied": numerical_passed,
            "floor_satisfied": not missing_native and numerical_passed})
    missing_requested = sorted({family for reports in batches.values() for report in reports
                                for family in report["requested_families"]} - trained)
    result = {"schema": SCHEMA, "domain_id": domain_id, "minimum_sources_per_split": minimum_sources_per_split,
        "family_inventory": families, "profile_inventory": profile_inventory, "required_floor": floor,
        "projection_floor_satisfied": all(row["projection_floor_satisfied"] for row in floor),
        "floor_satisfied": all(row["floor_satisfied"] for row in floor),
        "numerical_training_executed": training_executed,
        "requested_families_not_reported_as_trained": missing_requested,
        "untrained_projection_ids": unseen, "omitted_numerical_projection_ids": omitted,
        "native_report_list_sha256": report_digests, "numerical_receipt_sha256": receipt_hashes,
        "source_digest_and_exact_text_hash_overlap_checked": True, "group_overlap_checked": False,
        "native_validation_scope": "structural_integrity_and_current_producer_pins_not_typed_input_replay",
        "numerical_validation_scope": "caller_supplied_receipt_internal_consistency_not_authentication_or_model_execution",
        "heldout_numerical_source_binding": "row_positions_and_native_projection_ids_only_no_inference_report_list_digest",
        "training_target_scope": "auxiliary_native_structural_features_not_generated_formulas",
        "all_applicable_families_inferred": False, **FALSE}
    result["audit_sha256"] = _sha(result)
    return result


__all__ = ["SCHEMA", "audit_family_training_coverage"]
