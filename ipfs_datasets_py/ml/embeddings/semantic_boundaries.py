"""Source-preserving adjacent-vector grouping, never semantic validation.

Callers own structural atoms and the pinned embedding/tokenizer runtime. Model
failure is explicit; this module never substitutes hash vectors or calls an LLM.
"""
from __future__ import annotations

import hashlib
import json
import math
from numbers import Real


class SemanticBoundaryError(ValueError):
    """Invalid source partition, embedding contract, or explicit runtime failure."""


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _normalized_vectors(raw, count):
    try:
        rows = list(raw)
        if len(rows) != count:
            raise ValueError("count")
        dimension, result = None, []
        for row in rows:
            row = list(row)
            if not row or any(isinstance(x, bool) or not isinstance(x, Real) for x in row):
                raise ValueError("values")
            vector = [float(x) for x in row]
            if any(not math.isfinite(x) for x in vector):
                raise ValueError("nonfinite")
            norm = math.hypot(*vector)
            if not math.isfinite(norm) or norm == 0 or (dimension is not None and len(vector) != dimension):
                raise ValueError("dimension_or_norm")
            dimension = len(vector)
            result.append([x / norm for x in vector])
        return result
    except (TypeError, ValueError, OverflowError):
        raise SemanticBoundaryError("invalid_embedding_vectors") from None


def group_semantic_atoms(text, atoms, *, embedder, max_chars=2048, min_chars=128,
                         max_embedding_chars=1024, similarity_threshold=0.5,
                         barriers=(), embedding_eligible=None,
                         on_embedding_error="raise"):
    """Group a complete contiguous source partition using adjacent cosine scores.

    ``atoms`` contains exclusive ``(start_char, end_char)`` intervals covering
    exactly ``text``. ``barriers`` identifies atom indexes before which merging
    is forbidden. Oversize or tokenizer-ineligible atoms remain opaque standalone
    groups. ``embedding_eligible`` must return bool and should check the real
    model's untruncated token count; a character bound alone cannot guarantee it.

    A small current group may absorb its next neighbor despite low similarity to
    reach ``min_chars``; structural barriers and ``max_chars`` always take priority.
    Set ``on_embedding_error='structural'`` for an explicitly reported fallback.
    Returned exact atom selectors, normalized vectors and input indexes support
    decision replay without running the caller's sentence splitter again.
    """
    if (type(text) is not str or not callable(embedder)
            or any(type(x) is not int or x < 1 for x in (max_chars, max_embedding_chars))
            or type(min_chars) is not int or not 0 <= min_chars <= max_chars
            or isinstance(similarity_threshold, bool) or not isinstance(similarity_threshold, Real)
            or not math.isfinite(similarity_threshold) or not -1 <= similarity_threshold <= 1
            or on_embedding_error not in {"raise", "structural"}
            or embedding_eligible is not None and not callable(embedding_eligible)):
        raise SemanticBoundaryError("invalid_grouping_configuration")
    atoms = list(atoms)
    cursor = 0
    for atom in atoms:
        if (not isinstance(atom, (tuple, list)) or len(atom) != 2
                or any(type(x) is not int for x in atom)
                or atom[0] != cursor or not cursor < atom[1] <= len(text)):
            raise SemanticBoundaryError("atoms_must_exactly_partition_source")
        cursor = atom[1]
    if cursor != len(text):
        raise SemanticBoundaryError("atoms_must_exactly_partition_source")
    barriers = list(barriers)
    if any(type(x) is not int or not 1 <= x < len(atoms) for x in barriers):
        raise SemanticBoundaryError("invalid_structural_barrier")
    barriers = set(barriers)
    opaque, inputs, indexes = {}, [], []
    for i, (start, end) in enumerate(atoms):
        part = text[start:end]
        reason = "atom_exceeds_max_chars" if len(part) > max_chars else (
            "atom_exceeds_embedding_chars" if len(part) > max_embedding_chars else None)
        if reason is None and embedding_eligible is not None:
            eligible = embedding_eligible(part)
            if type(eligible) is not bool:
                raise SemanticBoundaryError("embedding_eligibility_must_be_boolean")
            if not eligible:
                reason = "atom_exceeds_embedding_token_budget"
        if reason:
            opaque[i] = reason
        else:
            indexes.append(i)
            inputs.append(part)
    vectors, error, status = [], None, "not_required"
    if inputs:
        try:
            vectors = _normalized_vectors(embedder(inputs), len(inputs))
            status = "embedded"
        except Exception as exc:
            if on_embedding_error == "raise":
                raise SemanticBoundaryError("embedding_failed:" + type(exc).__name__) from None
            error, status = type(exc).__name__, "structural_fallback"
    by_index = dict(zip(indexes, vectors))
    groups, boundaries = [], []
    for i, (start, end) in enumerate(atoms):
        score, merge, reason = None, False, "first_atom"
        if i:
            if i - 1 in by_index and i in by_index:
                score = max(-1.0, min(1.0, math.fsum(a * b for a, b in zip(by_index[i - 1], by_index[i]))))
            if i in barriers:
                reason = "structural_barrier"
            elif i in opaque or i - 1 in opaque:
                reason = "opaque_atom_boundary"
            elif end - groups[-1]["start_char"] > max_chars:
                reason = "max_chars"
            elif status == "structural_fallback":
                merge, reason = True, "explicit_structural_fallback"
            elif end - start + groups[-1]["end_char"] - groups[-1]["start_char"] <= max_chars:
                if score is not None and score >= similarity_threshold:
                    merge, reason = True, "adjacent_similarity"
                elif groups[-1]["end_char"] - groups[-1]["start_char"] < min_chars:
                    merge, reason = True, "minimum_size_join"
                else:
                    reason = "similarity_below_threshold"
            boundaries.append({"before_atom": i, "cosine_similarity": score,
                               "merged": merge, "reason": reason})
        if merge:
            groups[-1]["end_char"] = end
            groups[-1]["atom_indexes"].append(i)
        else:
            groups.append({"start_char": start, "end_char": end, "atom_indexes": [i],
                "opaque": i in opaque, "exceeds_max_chars": end - start > max_chars})
    return {"schema": "source-semantic-boundaries/v1", "groups": groups, "boundaries": boundaries,
        "atoms": [{"start_char": start, "end_char": end} for start, end in atoms],
        "embedding_status": status, "embeddings_used": status == "embedded",
        "embedding_error_type": error, "embedding_input_atom_indexes": indexes,
        "embedding_input_sha256": _sha(inputs), "normalized_vectors": vectors,
        "normalized_vectors_sha256": _sha(vectors),
        "opaque_atoms": [{"atom_index": i, "reason": reason} for i, reason in opaque.items()],
        "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "config": {"max_chars": max_chars, "min_chars": min_chars,
            "max_embedding_chars": max_embedding_chars, "similarity_threshold": float(similarity_threshold),
            "barriers": sorted(barriers), "on_embedding_error": on_embedding_error,
            "token_budget_checked": embedding_eligible is not None},
        "semantic_correctness_verified": False, "proof_authority": False}
