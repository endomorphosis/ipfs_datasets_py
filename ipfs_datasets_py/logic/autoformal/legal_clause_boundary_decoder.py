"""Bounded learned clause boundaries for an explicitly restricted flat profile.

The BiGRU predicts token ends and document eligibility. Rule count is the number
of predicted ends, not an independently supervised count classifier. A narrow
conservative surface guard rejects known coordination/shared-scope constructs;
its acceptance does not establish legal independence. Every accepted nonwhite
source character is covered, with repeated occurrences kept at distinct offsets.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from . import legal_rule_list_composition as composition

SCHEMA = "learned-flat-legal-clause-boundaries/v1"
PROFILE = "declared-independent-flat-rule-candidates/v1"
TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
MAX_TOKENS = 512
MAX_BYTES = 40_000
MAX_CLAUSES = 8
CONFIG = {"buckets": 1024, "embedding_size": 24, "hidden_size": 32, "feature_count": 6,
          "learning_rate": .004, "batch_size": 12, "seed": 48317}
FALSE = {"source_semantics_verified": False, "independent_scope_verified": False,
         "qualified": False, "admitted": False, "proof_authority": False}
MODAL = re.compile(r"\b(?:must(?:\s+not)?|may|shall(?:\s+not)?|is\s+(?:required|allowed|permitted)\s+to)\b", re.I)
# This is a declared conservative surface policy, not a complete scope detector.
UNSUPPORTED = re.compile(r"\b(?:and|both|either|respectively|following\s+(?:rules|requirements)|provided\s+that|means)\b", re.I)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                                     allow_nan=False).encode()).hexdigest()


def text_sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def implementation_sha():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def tokenize(text):
    require(type(text) is str and text.strip() and len(text.encode()) <= MAX_BYTES, "bounded nonblank source text required")
    tokens = [{"text": m.group(), "char_start": m.start(), "char_end": m.end()} for m in TOKEN.finditer(text)]
    require(1 <= len(tokens) <= MAX_TOKENS, "source exceeds complete token bound; truncation forbidden")
    return tokens


def encoded(text):
    tokens = tokenize(text)
    ids, features = [], []
    for index, token in enumerate(tokens):
        value = token["text"]
        bucket = int.from_bytes(hashlib.sha256(value.casefold().encode()).digest()[:8], "big") % (CONFIG["buckets"] - 1) + 1
        previous = tokens[index - 1]["char_end"] if index else 0
        gap = text[previous:token["char_start"]]
        ids.append(bucket)
        features.append([float(value[0].isupper()), float(value.isdigit()), float(value.isalpha()),
            float(value in (".", ";", ":", "!", "?")), float("\n" in gap), float(len(value) > 8)])
    return tokens, ids, features


def model(torch):
    class BoundaryModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = torch.nn.Embedding(CONFIG["buckets"], CONFIG["embedding_size"], padding_idx=0)
            self.encoder = torch.nn.GRU(CONFIG["embedding_size"] + CONFIG["feature_count"], CONFIG["hidden_size"],
                                        bidirectional=True, batch_first=True)
            self.boundary = torch.nn.Linear(CONFIG["hidden_size"] * 2, 1)
            self.scope = torch.nn.Linear(CONFIG["hidden_size"] * 2, 2)

        def forward(self, ids, features, lengths):
            raw = torch.cat((self.embedding(ids), features), dim=-1)
            packed = torch.nn.utils.rnn.pack_padded_sequence(raw, lengths.cpu(), batch_first=True, enforce_sorted=False)
            values, hidden = self.encoder(packed)
            values, _ = torch.nn.utils.rnn.pad_packed_sequence(values, batch_first=True, total_length=ids.shape[1])
            scope = self.scope(torch.cat((hidden[-2], hidden[-1]), dim=-1))
            return self.boundary(values).squeeze(-1), scope
    return BoundaryModel()


def tensor_batch(torch, rows, *, labels=False):
    prepared = [encoded(row["source_text"]) for row in rows]
    width = max(len(item[0]) for item in prepared)
    ids = torch.zeros((len(rows), width), dtype=torch.long)
    features = torch.zeros((len(rows), width, CONFIG["feature_count"]), dtype=torch.float32)
    lengths = torch.tensor([len(item[0]) for item in prepared], dtype=torch.long)
    boundaries = torch.zeros((len(rows), width), dtype=torch.float32)
    scope = torch.zeros(len(rows), dtype=torch.long)
    for index, (tokens, token_ids, values) in enumerate(prepared):
        count = len(tokens)
        ids[index, :count] = torch.tensor(token_ids)
        features[index, :count] = torch.tensor(values)
        if labels:
            row = rows[index]
            scope[index] = int(row["supported"])
            if row["supported"]:
                ends = {clause["char_end"] for clause in row["clauses"]}
                require(ends <= {token["char_end"] for token in tokens}, "reference boundaries must be source token ends")
                boundaries[index, :count] = torch.tensor([float(token["char_end"] in ends) for token in tokens])
    mask = torch.arange(width)[None, :] < lengths[:, None]
    return ids, features, lengths, boundaries, scope, mask


def checkpoint(network, *, steps, training_manifest_sha256, tuning_manifest_sha256):
    return {"schema": SCHEMA, "profile": PROFILE, "implementation_sha256": implementation_sha(), "config": deepcopy(CONFIG),
        "model_state": {name: tensor.detach().cpu().tolist() for name, tensor in network.state_dict().items()},
        "optimizer_steps": steps, "training_manifest_sha256": training_manifest_sha256,
        "tuning_manifest_sha256": tuning_manifest_sha256, "optimizer_resumption_supported": False, **FALSE}


def restore(value):
    import torch
    torch.set_num_threads(1)
    require(type(value) is dict and set(value) == {"schema", "profile", "implementation_sha256", "config", "model_state", "optimizer_steps",
        "training_manifest_sha256", "tuning_manifest_sha256", "optimizer_resumption_supported", *FALSE}, "closed boundary checkpoint required")
    require(value["schema"] == SCHEMA and value["profile"] == PROFILE and value["config"] == CONFIG
        and value["implementation_sha256"] == implementation_sha() and value["optimizer_resumption_supported"] is False
        and all(value[key] is False for key in FALSE), "boundary checkpoint contract or producer differs")
    require(type(value["optimizer_steps"]) is int and value["optimizer_steps"] >= 0, "nonnegative trained step count required")
    for key in ("training_manifest_sha256", "tuning_manifest_sha256"):
        require(type(value[key]) is str and re.fullmatch("[0-9a-f]{64}", value[key]), "fitting manifest commitment required")
    network = model(torch)
    expected = network.state_dict()
    require(set(expected) == set(value["model_state"]), "complete boundary tensor inventory required")
    loaded = {}
    for name, exemplar in expected.items():
        tensor = torch.tensor(value["model_state"][name], dtype=exemplar.dtype)
        require(tensor.shape == exemplar.shape and bool(torch.isfinite(tensor).all()), "finite exact boundary tensor shape required")
        loaded[name] = tensor
    network.load_state_dict(loaded, strict=True)
    network.eval()
    return torch, network


def source_plan(source, tokens, end_indices):
    """Turn predicted token ends into a complete occurrence-aware source plan."""
    require(type(end_indices) is list and 1 <= len(end_indices) <= MAX_CLAUSES
        and all(type(index) is int for index in end_indices) and end_indices == sorted(set(end_indices))
        and end_indices[-1] == len(tokens) - 1, "complete ordered terminal boundary coverage required")
    require(tokens == tokenize(source["source_text"]), "source token coordinates differ")
    clauses, previous = [], 0
    for ordinal, end_index in enumerate(end_indices):
        require(previous <= end_index < len(tokens), "invalid clause boundary")
        clauses.append({"clause_id": f"learned-occurrence-{ordinal:02d}", "char_start": tokens[previous]["char_start"],
            "char_end": tokens[end_index]["char_end"], "scope": deepcopy(composition.FLAT_SCOPE)})
        previous = end_index + 1
    return composition.prepare_source_plan(source, clauses)


class ClauseBoundaryDecoder:
    def __init__(self, value):
        self.torch, self.network = restore(value)
        self.checkpoint = deepcopy(value)
        self.checkpoint_sha256 = digest(value)

    def decode(self, sources, *, source_profile=PROFILE):
        require(source_profile == PROFILE, "explicit restricted flat source profile required")
        require(type(sources) is list and 1 <= len(sources) <= 128, "bounded source-only inference batch required")
        for row in sources:
            require(set(row) == {"candidate_id", "source_text", "source_sha256"}
                and row["source_sha256"] == text_sha(row["source_text"]), "closed source-only document and exact source hash required")
        torch = self.torch
        packed = tensor_batch(torch, sources)
        with torch.inference_mode():
            boundary, scope = self.network(*packed[:3])
            scope_probabilities = torch.softmax(scope, dim=-1)
        results = []
        for index, source in enumerate(sources):
            tokens = tokenize(source["source_text"])
            logits = boundary[index, :len(tokens)].tolist()
            ends = [i for i, value in enumerate(logits) if value >= 0.]
            raw_scope = bool(scope[index].argmax().item())
            rejection, plan = None, None
            if UNSUPPORTED.search(source["source_text"]):
                rejection = "declared_surface_policy_unsupported_scope"
            elif not raw_scope:
                rejection = "learned_scope_abstention"
            elif not ends or ends[-1] != len(tokens) - 1:
                rejection = "learned_terminal_coverage_missing"
            elif len(ends) > MAX_CLAUSES:
                rejection = "predicted_rule_count_exceeds_bound"
            else:
                try:
                    plan = source_plan(source, tokens, ends)
                    if any(len(MODAL.findall(clause["source_text"])) != 1 for clause in plan["clauses"]):
                        rejection, plan = "one_surface_modal_per_flat_clause_required", None
                except ValueError:
                    rejection, plan = "predicted_plan_outside_supported_bounds", None
            results.append({"candidate_id": source["candidate_id"], "source_sha256": source["source_sha256"],
                "status": "segmented" if plan is not None else "abstained", "reason": rejection,
                "predicted_rule_count": len(ends), "plan": plan,
                "boundary_token_indices": ends, "boundary_logits": logits,
                "scope_logits": scope[index].tolist(), "scope_supported_probability": float(scope_probabilities[index, 1]),
                "raw_learned_scope_supported": raw_scope, "segmentation_learned": True,
                "rule_count_induced_from_learned_boundaries": True, "target_access": False,
                "complete_document_returned_or_abstained": True, "source_profile": source_profile, **FALSE})
        return {"schema": SCHEMA, "checkpoint_sha256": self.checkpoint_sha256, "rows": results,
            "training_executed": False, "target_access": False, "references_supplied": False, **FALSE}
