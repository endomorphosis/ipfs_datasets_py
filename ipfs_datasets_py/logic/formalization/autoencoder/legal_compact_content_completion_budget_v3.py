"""Bounded pure DFS witnesses over the unchanged compact completion-v1 policy.

Only original public policy edges are traversed. A typed terminal witness proves
syntactic reachability; exhausted finite trees are relative-policy dead ends.
Unvisited work or any search/report cap remains UNKNOWN. No model, target,
selection mask, learned objective or historical owner is changed.
"""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import stat

SCHEMA = "legal-compact-content-branch-witness/v1"
POLICY = "bounded-original-completion-dfs/v1"
DEFAULT_MAX_PREFIX_INSPECTIONS = 256
MAX_PREFIX_INSPECTIONS = 1024
MAX_SEARCH_DEPTH = 512
MAX_FRONTIER_NODES = 512
MAX_REPORT_BYTES = 2 * 1024**2
MAX_TRACE_BYTES = 1024**2
MAX_TRACE_ITEMS = 50000
MASK_BITS, MASK_HEX_WIDTH = 537, 135
_LEGACY_SHA = "0d7362815dad5048652020d03967af4908123d74887e71e1823c62aa958783a7"
_SELF_PATH = Path(__file__).absolute()
_SELF_SHA = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()


class CompletionWitnessError(ValueError):
    """Input, source custody or an original-owner contradiction failed."""


def _need(ok, message):
    if not ok:
        raise CompletionWitnessError(message)


def _owners():
    path = _SELF_PATH.with_name("legal_compact_content_completion_budget_v1.py")
    info = path.lstat()
    _need(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode)
          and info.st_nlink == 1 and 0 < info.st_size <= 131072
          and hashlib.sha256(path.read_bytes()).hexdigest() == _LEGACY_SHA,
          "pinned canonical completion-v1 source required")
    legacy = importlib.import_module(__package__ + ".legal_compact_content_completion_budget_v1")
    _need(type(legacy.__file__) is str and Path(legacy.__file__).absolute() == path,
          "completion-v1 module origin differs")
    scope, helper, tokens, pins = legacy._owners()
    _need(helper._source(path, _LEGACY_SHA) in pins,
          "original completion-v1 pin absent")
    return legacy, scope, helper, tokens, pins + [helper._source(_SELF_PATH, _SELF_SHA)]


def _operation(original, work):
    legacy, scope, helper, tokens, pins = _owners()
    failure = None

    def fence():
        current = _owners()
        _need(current[:4] == (legacy, scope, helper, tokens) and current[4] == pins,
              "completion-witness source custody changed")

    def guarded(data, inner_scope, inner_helper, inner_tokens, old_pins):
        fence()
        _need((inner_scope, inner_helper, inner_tokens) == (scope, helper, tokens)
              and old_pins == pins[:-1], "witness and original owners disagree")
        result = work(data, legacy, helper, tokens, pins)
        helper._wire(result, MAX_REPORT_BYTES)
        fence()
        return result

    try:
        result = legacy._operation(original, guarded)
        fence()
        return result
    except BaseException as error:
        failure = error
        raise
    finally:
        helper._finish(failure, fence)


def _bounded(value, low, high, name):
    _need(type(value) is int and low <= value <= high,
          name + " must be a plain integer in " + str(low) + ".." + str(high))


def _mask(ids):
    return format(sum(1 << item for item in ids), "0" + str(MASK_HEX_WIDTH) + "x")


def _item_count(value):
    if type(value) is dict:
        return 1 + sum(1 + _item_count(item) for item in value.values())
    if type(value) is list:
        return 1 + sum(_item_count(item) for item in value)
    return 1


def _search(data, legacy, helper, tokens, pins):
    _need(type(data["prefix_ids"]) is list, "original plain prefix ID list required")
    _bounded(data["max_prefix_inspections"], 1, MAX_PREFIX_INSPECTIONS,
             "max_prefix_inspections")
    _bounded(data["max_search_depth"], 0, MAX_SEARCH_DEPTH, "max_search_depth")
    _bounded(data["max_frontier_nodes"], 1, MAX_FRONTIER_NODES, "max_frontier_nodes")
    options = {key: data[key] for key in
               ("context_raw", "expected_context_sha256", "codec", "expected_codec_sha256")}
    # Internal prefixes are not repeated in the exported certificate.
    stack = [dict(node_id=0, parent_id=None, via_token_id=None, depth=0,
                  ids=list(data["prefix_ids"]), remaining=data["remaining_new_tokens"])]
    trace, inspections, typed_inspections, trace_bytes, trace_items = [], 0, 0, 0, 0
    next_id, peak_frontier, unexpanded, cutoff, completion = 1, 1, [], None, None
    root_report = None
    while stack:
        if inspections == data["max_prefix_inspections"]:
            cutoff = "prefix_inspection_limit"
            break
        node = stack.pop()
        inspections += 1
        report = legacy.allowed_token_ids(node["ids"], remaining_new_tokens=node["remaining"], **options)
        _need(report["schema"] == legacy.PREFIX_SCHEMA and report["policy"] == legacy.POLICY
              and report["offered_ids"] == node["ids"]
              and report["remaining_new_tokens"] == node["remaining"]
              and report["owner_pins"] == pins[:-1]
              and report["context_raw_sha256"] == data["expected_context_sha256"]
              and report["codec_sha256"] == data["expected_codec_sha256"],
              "original prefix observation identity differs")
        allowed = report["allowed_token_ids"]
        _need(type(allowed) is list and len(allowed) == len(set(allowed))
              and all(type(item) is int and 0 <= item < MASK_BITS for item in allowed)
              and set(allowed) <= set(report["scope_prefix_report"]["allowed_token_ids"]),
              "original allowed choices differ")
        costs = {}
        for row in report["candidate_bounds"]:
            token = row["token_id"]
            _need(token not in costs, "duplicate original candidate bound")
            costs[token] = row["minimum_tokens_with_choice"]
        _need(all(token in costs and type(costs[token]) is int and costs[token] >= 1
                  for token in allowed), "original candidate ordering bound differs")
        ordered = sorted(allowed, key=lambda token: (costs[token], token))
        bound = report["prefix_lower_bound"]
        entry = dict(node_id=node["node_id"], parent_id=node["parent_id"],
            via_token_id=node["via_token_id"], depth=node["depth"],
            remaining_new_tokens=node["remaining"],
            effective_remaining_tokens=report["effective_remaining_tokens"],
            status=report["status"], reason=report["reason"],
            allowed_mask_hex=_mask(allowed), allowed_count=len(allowed),
            bound_status=bound["status"], minimum_additional_tokens=bound["minimum_additional_tokens"],
            owner_report_sha256=hashlib.sha256(helper._wire(report, MAX_REPORT_BYTES)).hexdigest(),
            ordering_sha256=hashlib.sha256(helper._wire(ordered, MAX_REPORT_BYTES)).hexdigest())
        encoded, items = helper._wire(entry, MAX_REPORT_BYTES), _item_count(entry)
        if trace_bytes + len(encoded) + 1 > MAX_TRACE_BYTES or trace_items + items > MAX_TRACE_ITEMS:
            # The actual inspection happened, but its node is unresolved in the
            # lean certificate. Keep it in the explicit pending frontier.
            stack.append(node)
            cutoff = "trace_report_limit"
            break
        trace.append(entry)
        trace_bytes += len(encoded) + 1
        trace_items += items
        if root_report is None:
            root_report = report
        if report["status"] == "complete":
            _need(node["ids"] and node["ids"][-1] == tokens.EOS_ID,
                  "terminal EOS required for original completion")
            decoded = tokens.decode_compact_content_tokens_v1(node["ids"], **options)
            typed_inspections += 1
            _need(decoded["status"] == "valid_candidate" and decoded["generated_ids"] == node["ids"]
                  and decoded["framing"]["eos_terminal"] is True,
                  "original complete prefix and typed decoder disagree")
            completion = dict(node_id=node["node_id"], token_ids=list(node["ids"]),
                suffix_token_ids=list(node["ids"][len(data["prefix_ids"]):]),
                generated_content_sha256=decoded["generated_content_sha256"], counts=decoded["counts"],
                typed_report_sha256=hashlib.sha256(helper._wire(decoded, MAX_REPORT_BYTES)).hexdigest(),
                syntactic_only=True, model_generated_completion=False)
            break
        if not allowed:
            continue
        if node["depth"] == data["max_search_depth"]:
            cutoff = "search_depth_limit"
            unexpanded = [dict(parent_id=node["node_id"], allowed_mask_hex=_mask(allowed),
                               child_count=len(allowed))]
            break
        if len(stack) + len(ordered) > data["max_frontier_nodes"]:
            cutoff = "frontier_limit"
            unexpanded = [dict(parent_id=node["node_id"], allowed_mask_hex=_mask(allowed),
                               child_count=len(allowed))]
            break
        _need(node["remaining"] > 0, "original choice exceeds remaining allowance")
        children = []
        for token in ordered:
            children.append(dict(node_id=next_id, parent_id=node["node_id"], via_token_id=token,
                depth=node["depth"] + 1, ids=node["ids"] + [token], remaining=node["remaining"] - 1))
            next_id += 1
        stack.extend(reversed(children))
        peak_frontier = max(peak_frontier, len(stack))
    status = "WITNESS" if completion is not None else ("UNKNOWN" if cutoff else "DEAD_END")
    reason = "typed_terminal_completion" if completion is not None else (cutoff or "closed_original_policy_frontier")
    pending = [{key: node[key] for key in ("node_id", "parent_id", "via_token_id", "depth", "remaining")}
               for node in stack]
    return dict(schema=SCHEMA, policy=POLICY, status=status, reason=reason,
        offered_ids=list(data["prefix_ids"]), remaining_new_tokens=data["remaining_new_tokens"],
        max_prefix_inspections=data["max_prefix_inspections"], max_search_depth=data["max_search_depth"],
        max_frontier_nodes=data["max_frontier_nodes"], actual_prefix_inspections=inspections,
        recorded_node_count=len(trace), unrecorded_inspections=inspections-len(trace),
        peak_frontier_nodes=peak_frontier, trace=trace, pending_nodes=pending,
        unexpanded_parents=unexpanded,
        unresolved_frontier_root_count=len(pending) + sum(row["child_count"] for row in unexpanded),
        frontier_count_scope="pending nodes and immediate unexpanded children; descendants not enumerated",
        frontier_closed=status == "DEAD_END", exhaustive_relative_to_original_policy=status == "DEAD_END",
        witness=completion, typed_witness_inspections=typed_inspections,
        ordering="depth_first_minimum_tokens_with_choice_then_token_id",
        mask_encoding="135_lowercase_hex_digits_integer_bits_0_through_536",
        trace_bytes=trace_bytes, trace_items=trace_items,
        report_caps=dict(bytes=MAX_REPORT_BYTES, trace_bytes=MAX_TRACE_BYTES, trace_items=MAX_TRACE_ITEMS,
                         nontrace_byte_reserve=MAX_REPORT_BYTES-MAX_TRACE_BYTES,
                         nontrace_item_reserve=100000-MAX_TRACE_ITEMS,
                         original_json_item_cap=100000, original_json_depth_cap=96),
        codec_sha256=data["expected_codec_sha256"], context_raw_sha256=data["expected_context_sha256"],
        owner_pins=pins, branch_search_performed=True, parser_subclassing=False,
        model_or_future_score_queries=False, generated_token_selection_performed=False,
        global_completability_proven=False,
        authority=dict(root_report["authority"] if root_report is not None else legacy._AUTHORITY),
        training_mask=0, evaluation_gold_mask=0)


def find_completion_witness(prefix_ids, context_raw, *, expected_context_sha256, codec,
        expected_codec_sha256, remaining_new_tokens, max_prefix_inspections=DEFAULT_MAX_PREFIX_INSPECTIONS,
        max_search_depth=MAX_SEARCH_DEPTH, max_frontier_nodes=MAX_FRONTIER_NODES):
    """Find a pure typed suffix or report a bounded original-policy frontier.

    Root and every forced/branch inspection consume the same total allowance.
    Search depth counts appended IDs, including EOS; no suffix is generated by a model.
    DEAD_END concerns complete exhaustion of this exact original policy tree only.
    """
    original = dict(prefix_ids=prefix_ids, context_raw=context_raw,
        expected_context_sha256=expected_context_sha256, codec=codec,
        expected_codec_sha256=expected_codec_sha256, remaining_new_tokens=remaining_new_tokens,
        max_prefix_inspections=max_prefix_inspections, max_search_depth=max_search_depth,
        max_frontier_nodes=max_frontier_nodes)
    return _operation(original, _search)


__all__ = ["CompletionWitnessError", "find_completion_witness"]
