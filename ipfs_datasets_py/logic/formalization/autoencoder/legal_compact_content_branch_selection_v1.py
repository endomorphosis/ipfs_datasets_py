"""Pure score-ranked selection using the pinned bounded witness core.

Current scores determine only candidate order. A stored closed DEAD_END
certificate removes a choice; UNKNOWN, unqueried or omitted certificates retain
it. The first retained score-ranked choice is selected without injecting any
witness suffix. No search engine, model call or historical profile is added.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import stat

SCHEMA = "legal-compact-content-branch-selection/v1"
POLICY = "score-ranked-dead-end-only-branch-selection/v1"
DEFAULT_MAX_PREFIX_INSPECTIONS = 256
MAX_PREFIX_INSPECTIONS = 1024
MAX_SEARCH_DEPTH = 512
MAX_FRONTIER_NODES = 512
MAX_REPORT_BYTES = 2 * 1024**2
MAX_REPORT_ITEMS = 100000
MAX_CERTIFICATE_BYTES = 1024**2
MAX_CERTIFICATE_ITEMS = 50000
_CORE_SHA = "38387c5573c42a03f41c99f6fbedf6a70f0755f3ac564990cafa481498c52e7f"
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()


class BranchSelectionError(ValueError):
    """Input, dependency custody or a contradictory witness observation failed."""


def _need(value, message):
    if not value:
        raise BranchSelectionError(message)


def _owners():
    path = _SELF_PATH.with_name("legal_compact_content_completion_budget_v3.py")
    info = path.lstat()
    _need(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode)
          and info.st_nlink == 1 and 0 < info.st_size <= 131072
          and hashlib.sha256(path.read_bytes()).hexdigest() == _CORE_SHA,
          "pinned canonical witness core required")
    core = importlib.import_module(__package__ + ".legal_compact_content_completion_budget_v3")
    _need(type(core.__file__) is str and Path(core.__file__).absolute() == path,
          "witness-core module origin differs")
    legacy, scope, helper, tokens, pins = core._owners()
    _need(helper._source(path, _CORE_SHA) in pins, "witness-core source pin absent")
    _need(helper.MAX_REPORT_BYTES == MAX_REPORT_BYTES and helper.MAX_JSON_ITEMS == MAX_REPORT_ITEMS,
          "inherited report byte/item contract differs")
    return core, legacy, scope, helper, tokens, pins + [helper._source(_SELF_PATH, _SELF_SHA)]


def _operation(original, work):
    core, legacy, scope, helper, tokens, pins = _owners()
    failure = None

    def fence():
        current = _owners()
        _need(current[:5] == (core, legacy, scope, helper, tokens) and current[5] == pins,
              "branch-selection source custody changed")

    def guarded(data, inner_legacy, inner_helper, inner_tokens, inherited_pins):
        fence()
        _need((inner_legacy, inner_helper, inner_tokens) == (legacy, helper, tokens)
              and inherited_pins == pins[:-1], "selector and witness owners disagree")
        result = work(data, core, legacy, helper, tokens, pins)
        helper._wire(result, MAX_REPORT_BYTES)
        fence()
        return result

    try:
        result = core._operation(original, guarded)
        fence()
        return result
    except BaseException as error:
        failure = error
        raise
    finally:
        helper._finish(failure, fence)


def _fits(report, core, helper):
    # All values are operation-owned ordinary snapshots or pinned-core reports.
    # Measure prospective whole output before admitting a certificate, instead
    # of turning an otherwise valid storage cutoff into a serialization error.
    if core._item_count(report) > MAX_REPORT_ITEMS:
        return False
    pending = [(report, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > helper.MAX_JSON_DEPTH:
            return False
        if type(value) is dict:
            pending.extend((x, depth + 1) for x in value.keys())
            pending.extend((x, depth + 1) for x in value.values())
        elif type(value) is list:
            pending.extend((x, depth + 1) for x in value)
    raw = json.dumps(report, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return len(raw) <= MAX_REPORT_BYTES


def select_token(logits, prefix_ids, context_raw, *, expected_context_sha256, codec,
        expected_codec_sha256, remaining_new_tokens,
        max_prefix_inspections=DEFAULT_MAX_PREFIX_INSPECTIONS,
        max_search_depth=MAX_SEARCH_DEPTH, max_frontier_nodes=MAX_FRONTIER_NODES):
    """Select at most one current-score token; reject only stored dead proofs.

    The mandatory old-policy root and every candidate's actual witness queries
    share one allowance. A zero residual allowance keeps choices unqueried.
    Search/report limits keep UNKNOWN. A witness suffix is never selected or
    appended; an all-dead retained mask returns no_selection.
    """
    original = dict(logits=logits, prefix_ids=prefix_ids, context_raw=context_raw,
        expected_context_sha256=expected_context_sha256, codec=codec,
        expected_codec_sha256=expected_codec_sha256, remaining_new_tokens=remaining_new_tokens,
        max_prefix_inspections=max_prefix_inspections, max_search_depth=max_search_depth,
        max_frontier_nodes=max_frontier_nodes)

    def work(data, core, legacy, helper, tokens, pins):
        helper._scores(data["logits"])
        core._bounded(data["max_prefix_inspections"], 1, MAX_PREFIX_INSPECTIONS,
                      "max_prefix_inspections")
        core._bounded(data["max_search_depth"], 0, MAX_SEARCH_DEPTH, "max_search_depth")
        core._bounded(data["max_frontier_nodes"], 1, MAX_FRONTIER_NODES, "max_frontier_nodes")
        options = {key: data[key] for key in
            ("context_raw", "expected_context_sha256", "codec", "expected_codec_sha256")}
        baseline = legacy.allowed_token_ids(data["prefix_ids"],
            remaining_new_tokens=data["remaining_new_tokens"], **options)
        _need(baseline["schema"] == legacy.PREFIX_SCHEMA and baseline["policy"] == legacy.POLICY
              and baseline["owner_pins"] == pins[:-2]
              and baseline["offered_ids"] == data["prefix_ids"]
              and baseline["remaining_new_tokens"] == data["remaining_new_tokens"]
              and baseline["context_raw_sha256"] == data["expected_context_sha256"]
              and baseline["codec_sha256"] == data["expected_codec_sha256"]
              and baseline["authority"] and all(x is False for x in baseline["authority"].values())
              and type(baseline["training_mask"]) is type(baseline["evaluation_gold_mask"]) is int
              and baseline["training_mask"] == baseline["evaluation_gold_mask"] == 0
              and baseline["global_completability_proven"] is False,
              "original root observation identity differs")
        old = baseline["allowed_token_ids"]
        _need(type(old) is list and old == sorted(set(old))
              and all(type(x) is int and 0 <= x < 537 for x in old)
              and set(old) <= set(baseline["scope_prefix_report"]["allowed_token_ids"]),
              "original root choices differ")
        ranked = sorted(old, key=lambda token: (-data["logits"][token], token))
        raw_id = helper._argmax(data["logits"], list(range(537)))
        baseline_id = helper._argmax(data["logits"], old) if old else None
        score_sha = hashlib.sha256(helper._wire(data["logits"], MAX_REPORT_BYTES)).hexdigest()
        rows = [dict(token_id=token, rank=rank, queried=False, search_status=None,
            observed_search_status=None, disposition="keep_unqueried",
            reason="not_queried_after_first_retained", actual_prefix_inspections=0,
            certificate_index=None, certificate_sha256=None, certificate_retained=False)
            for rank, token in enumerate(ranked)]
        certificates, removed = [], []
        actual, calls, cert_bytes, cert_items, omitted = 1, 0, 0, 0, 0
        selected, stop = None, baseline["reason"] or baseline["status"]

        def report():
            allowed = [token for token in old if token not in removed]
            return dict(schema=SCHEMA, policy=POLICY,
                status="selected" if selected is not None else "no_selection", reason=stop,
                selected_token_id=selected,
                selected_score=data["logits"][selected] if selected is not None else None,
                raw_argmax_token_id=raw_id, raw_argmax_score=data["logits"][raw_id],
                baseline_argmax_token_id=baseline_id,
                baseline_argmax_score=data["logits"][baseline_id] if baseline_id is not None else None,
                offered_prefix_ids=list(data["prefix_ids"]),
                next_prefix_ids=list(data["prefix_ids"]) + ([] if selected is None else [selected]),
                logits=list(data["logits"]), logits_sha256=score_sha,
                allowed_token_ids=allowed, removed_token_ids=sorted(removed),
                candidate_order=list(ranked), candidate_results=rows, certificates=certificates,
                baseline_prefix_report=baseline, proof_stop_reason=stop,
                root_prefix_inspections=1, candidate_prefix_inspections=actual-1,
                actual_prefix_inspections=actual,
                remaining_prefix_inspections=data["max_prefix_inspections"]-actual,
                witness_calls=calls, certificate_bytes=cert_bytes, certificate_items=cert_items,
                certificate_byte_scope="sum_canonical_certificate_payload_bytes",
                certificate_item_scope="sum_recursive_certificate_payload_items",
                omitted_certificates=omitted,
                max_prefix_inspections=data["max_prefix_inspections"],
                max_search_depth=data["max_search_depth"], max_frontier_nodes=data["max_frontier_nodes"],
                report_caps=dict(bytes=MAX_REPORT_BYTES, items=MAX_REPORT_ITEMS,
                    certificate_bytes=MAX_CERTIFICATE_BYTES, certificate_items=MAX_CERTIFICATE_ITEMS,
                    depth=helper.MAX_JSON_DEPTH),
                codec_sha256=baseline["codec_sha256"], context_raw_sha256=baseline["context_raw_sha256"],
                context_sha256=baseline["context_sha256"], owner_pins=pins,
                tie_breaker="lowest_token_id", selection_performed=selected is not None,
                tokens_appended=int(selected is not None),
                unknown_and_unqueried_choices_retained=True, stop_at_first_retained=True,
                argmax_over_resulting_retained_set=True, scores_rank_queries_only=True,
                witness_suffix_injected=False, model_or_future_score_queries=False,
                global_completability_proven=False,
                authority=dict(baseline["authority"]), training_mask=0, evaluation_gold_mask=0)

        _need(_fits(report(), core, helper), "original root and score report exceed selector envelope")
        for row in rows:
            token = row["token_id"]
            allowance = data["max_prefix_inspections"] - actual
            if allowance == 0:
                row["reason"] = "prefix_inspection_limit"
                selected, stop = token, "retained_unqueried_budget_limit"
                break
            _need(data["remaining_new_tokens"] > 0, "original candidate exceeds output allowance")
            offered = list(data["prefix_ids"]) + [token]
            result = core.find_completion_witness(offered, remaining_new_tokens=data["remaining_new_tokens"]-1,
                max_prefix_inspections=allowance, max_search_depth=data["max_search_depth"],
                max_frontier_nodes=data["max_frontier_nodes"], **options)
            used = result["actual_prefix_inspections"]
            _need(type(used) is int and 1 <= used <= allowance
                  and result["schema"] == core.SCHEMA and result["policy"] == core.POLICY
                  and result["owner_pins"] == pins[:-1] and result["offered_ids"] == offered
                  and result["remaining_new_tokens"] == data["remaining_new_tokens"]-1
                  and result["max_prefix_inspections"] == allowance
                  and result["max_search_depth"] == data["max_search_depth"]
                  and result["max_frontier_nodes"] == data["max_frontier_nodes"]
                  and result["context_raw_sha256"] == data["expected_context_sha256"]
                  and result["codec_sha256"] == data["expected_codec_sha256"]
                  and result["status"] in {"WITNESS", "DEAD_END", "UNKNOWN"}
                  and result["authority"] and all(x is False for x in result["authority"].values())
                  and type(result["training_mask"]) is type(result["evaluation_gold_mask"]) is int
                  and result["training_mask"] == result["evaluation_gold_mask"] == 0
                  and result["model_or_future_score_queries"] is False
                  and result["generated_token_selection_performed"] is False
                  and result["global_completability_proven"] is False,
                  "witness result identity or accounting differs")
            kind = result["status"]
            if kind == "DEAD_END":
                _need(result["frontier_closed"] is True
                      and result["exhaustive_relative_to_original_policy"] is True
                      and result["unresolved_frontier_root_count"] == 0
                      and result["pending_nodes"] == result["unexpanded_parents"] == []
                      and result["unrecorded_inspections"] == 0 and result["witness"] is None,
                      "dead choice requires a complete original-policy certificate")
            elif kind == "WITNESS":
                witness = result["witness"]
                _need(type(witness) is dict and witness["syntactic_only"] is True
                      and witness["model_generated_completion"] is False
                      and witness["token_ids"][:len(offered)] == offered
                      and witness["token_ids"][-1] == tokens.EOS_ID,
                      "typed witness provenance or offered prefix differs")
            else:
                _need(result["frontier_closed"] is False
                      and result["exhaustive_relative_to_original_policy"] is False
                      and result["unresolved_frontier_root_count"] > 0 and result["witness"] is None,
                      "unknown choice must retain an unresolved original frontier")
            actual += used
            calls += 1
            blob = helper._wire(result, MAX_REPORT_BYTES)
            size, items = len(blob), core._item_count(result)
            digest = hashlib.sha256(blob).hexdigest()
            row.update(queried=True, observed_search_status=kind, search_status=kind,
                disposition={"DEAD_END":"remove_proven_dead_end", "WITNESS":"keep_witness",
                             "UNKNOWN":"keep_unknown"}[kind],
                reason=result["reason"], actual_prefix_inspections=used,
                certificate_index=len(certificates), certificate_sha256=digest,
                certificate_retained=True)
            certificates.append(result)
            cert_bytes += size
            cert_items += items
            if kind == "DEAD_END":
                removed.append(token)
            else:
                selected = token
            stop = "retained_" + kind.lower() if kind != "DEAD_END" else "all_candidates_proven_dead"
            fits = (cert_bytes <= MAX_CERTIFICATE_BYTES and cert_items <= MAX_CERTIFICATE_ITEMS
                    and _fits(report(), core, helper))
            if not fits:
                certificates.pop()
                cert_bytes -= size
                cert_items -= items
                if kind == "DEAD_END":
                    removed.pop()
                row.update(search_status="UNKNOWN", disposition="keep_unknown",
                    reason="certificate_report_limit", certificate_index=None, certificate_retained=False)
                selected, stop = token, "retained_unknown_certificate_report_limit"
                omitted += 1
                break
            if selected is not None:
                break
        retained = [token for token in old if token not in removed]
        expected = helper._argmax(data["logits"], retained) if retained else None
        _need(selected == expected, "first retained rank and resulting-mask argmax differ")
        final = report()
        _need(_fits(final, core, helper), "bounded selector result envelope differs")
        return final

    return _operation(original, work)


__all__ = ["BranchSelectionError", "select_token"]
