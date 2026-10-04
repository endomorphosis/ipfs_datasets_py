"""Bounded, source-only clause context for private authored-paragraph experiments.

Literal blank-line segmentation and exact cached text lookup are intentionally
narrow. No parser, formula, reference count, or training label selects a vector.
"""
from copy import deepcopy
import hashlib
import math

from . import decoder_distillation_experiment as core

SCHEMA = "source-clause-context/v1"
MAX_CLAUSES = 8
SEGMENT_KEYS = {"source_text", "source_sha256", "embedding_sha256", "vector",
                "char_start", "char_end", "byte_start", "byte_end"}
_require = core._require


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source(row, *, closed=False):
    _require(type(row) is dict and (not closed or set(row) == {"id", "source_text"})
        and type(row.get("id")) is str and 0 < len(row["id"]) <= 512,
        "bounded source-only identity required")
    text = row.get("source_text")
    _require(type(text) is str and 0 < len(text) <= 131072 and text.strip(), "bounded nonempty source text required")
    pieces = text.split("\n\n")
    _require(1 <= len(pieces) <= MAX_CLAUSES and all(piece.strip() for piece in pieces),
        "one to eight nonempty literal source clauses required")
    return text, pieces


def _vector(vector):
    dimension = len(vector) if type(vector) is list else 0
    _require(dimension in (8, 384, 768), "supported cached clause vector dimension required")
    core._vector(vector, dimension)
    _require(abs(sum(float(value)**2 for value in vector)-1.) <= 1e-4,
        "normalized cached semantic clause vector required")
    return dimension


def _descriptor(text, vectors):
    pieces = text.split("\n\n")
    segments = []
    char = byte = 0
    for piece, vector in zip(pieces, vectors):
        segments.append(dict(source_text=piece, source_sha256=_sha(piece), embedding_sha256=core.digest(vector),
            vector=deepcopy(vector), char_start=char, char_end=char+len(piece), byte_start=byte,
            byte_end=byte+len(piece.encode("utf-8"))))
        char += len(piece)+2; byte += len(piece.encode("utf-8"))+2
    return dict(source_sha256=_sha(text), segments=segments)


def validate_context(row, descriptor):
    """Validate one descriptor using only the row's identity and source text."""
    text, pieces = _source(row)
    _require(type(descriptor) is dict and set(descriptor) == {"source_sha256", "segments"}
        and descriptor["source_sha256"] == _sha(text), "clause context source binding differs")
    segments = descriptor["segments"]
    _require(type(segments) is list and len(segments) == len(pieces), "source clause inventory differs")
    dimension = None
    for piece, segment in zip(pieces, segments):
        _require(type(segment) is dict and set(segment) == SEGMENT_KEYS
            and segment["source_text"] == piece, "closed source clause descriptor required")
        current = _vector(segment["vector"])
        _require(dimension is None or dimension == current, "mixed clause vector dimensions")
        dimension = current
        for name in ("char_start", "char_end", "byte_start", "byte_end"):
            _require(type(segment[name]) is int, "integer clause offsets required")
    _require(descriptor == _descriptor(text, [segment["vector"] for segment in segments]),
        "clause text, vector digest, or offsets differ")
    return dimension


def build_source_contexts(source_rows, cache_rows):
    """Join closed source rows to closed semantic-cache rows by exact text only."""
    _require(type(source_rows) is list and 1 <= len(source_rows) <= 4096
        and type(cache_rows) is list and 1 <= len(cache_rows) <= 4096, "bounded source/cache rows required")
    lookup, ids = {}, set()
    dimension = None
    for row in cache_rows:
        _require(type(row) is dict and set(row) == {"id", "source_text", "input"}, "closed source-only cache row required")
        text, pieces = _source(row)
        _require(len(pieces) == 1 and row["id"] not in ids and text not in lookup,
            "unique single-clause source cache required")
        current = _vector(row["input"])
        _require(dimension is None or current == dimension, "mixed cache dimensions")
        dimension = current; ids.add(row["id"]); lookup[text] = row["input"]
    result = {}
    for row in source_rows:
        text, pieces = _source(row, closed=True)
        _require(row["id"] not in result, "duplicate source row ID")
        _require(all(piece in lookup for piece in pieces), "source clause missing from exact-text semantic cache")
        result[row["id"]] = _descriptor(text, [lookup[piece] for piece in pieces])
    _require(len(core._raw(result)) <= 67108864, "source context allocation exceeds64MiB")
    validate_contexts(source_rows, result)
    return result


def _inventory(rows, contexts):
    clauses, seen = [], {}
    for row in rows:
        for segment in contexts[row["id"]]["segments"]:
            sha = segment["source_sha256"]
            identity = dict(id="clause:"+sha, source_sha256=sha)
            _require(sha not in seen or seen[sha] == segment["embedding_sha256"],
                "same source clause has inconsistent cached vector")
            if sha not in seen:
                seen[sha] = segment["embedding_sha256"]; clauses.append(identity)
    return clauses


def validate_contexts(rows, contexts):
    """Validate a whole split; neither paragraph vectors nor labels are read."""
    _require(type(rows) is list and 1 <= len(rows) <= 4096 and type(contexts) is dict,
        "bounded explicit source context inventory required")
    ids = [row.get("id") if type(row) is dict else None for row in rows]
    _require(all(type(value) is str for value in ids) and len(set(ids)) == len(ids)
        and set(contexts) == set(ids), "exact source context row identities required")
    dimensions = {validate_context(row, contexts[row["id"]]) for row in rows}
    _require(len(dimensions) == 1, "mixed context dimensions")
    normalized = [" ".join(row["source_text"].casefold().split()) for row in rows]
    _require(len(set(normalized)) == len(rows), "duplicate normalized paragraph source")
    return dict(schema=SCHEMA, dimension=next(iter(dimensions)), contexts_sha256=core.digest(contexts),
        source_inventory=[dict(id=row["id"], source_sha256=_sha(row["source_text"])) for row in rows],
        clause_inventory=_inventory(rows, contexts), reference_labels_accessed=False,
        source_segmentation="literal_blank_line_exact_cache_text", admitted=False, qualified=False)


def validate_training_contexts(training_rows, validation_rows, source_contexts):
    _require(type(source_contexts) is dict and set(source_contexts) == {"train", "validation"},
        "closed explicit training/validation clause context envelope required")
    train = validate_contexts(training_rows, source_contexts["train"])
    validation = validate_contexts(validation_rows, source_contexts["validation"])
    _require(train["dimension"] == validation["dimension"], "split context dimensions differ")
    for getter in (lambda row: row["id"], lambda row: " ".join(row["source_text"].casefold().split())):
        _require(not {getter(row) for row in training_rows} & {getter(row) for row in validation_rows},
            "training/validation paragraph context overlap")
    def clause_sets(rows, contexts):
        segments = [segment for row in rows for segment in contexts[row["id"]]["segments"]]
        return ({" ".join(segment["source_text"].casefold().split()) for segment in segments},
                {segment["embedding_sha256"] for segment in segments})
    left = clause_sets(training_rows, source_contexts["train"])
    right = clause_sets(validation_rows, source_contexts["validation"])
    _require(all(not a & b for a, b in zip(left, right)), "training/validation clause source or vector overlap")
    return dict(schema="training-source-clause-context/v1", training=train, validation=validation,
        training_clause_inventory=train["clause_inventory"], validation_clause_inventory=validation["clause_inventory"],
        contexts_sha256=core.digest(source_contexts), reference_labels_accessed=False, admitted=False, qualified=False)


def unique_training_clauses(training_rows, validation_rows, source_contexts):
    """Unique first-observed training sources, for training-only feature statistics."""
    validate_training_contexts(training_rows, validation_rows, source_contexts)
    result, seen = [], set()
    for row in training_rows:
        for segment in source_contexts["train"][row["id"]]["segments"]:
            sha = segment["source_sha256"]
            if sha not in seen:
                seen.add(sha)
                result.append(dict(id="clause:"+sha, source_text=segment["source_text"],
                    source_sha256=sha, input=deepcopy(segment["vector"])))
    return result


def batch_source_context(torch, rows, contexts, input_transform):
    """Build an explicit padded tensor packet; padding happens after the transform."""
    _require(type(rows) is list and 1 <= len(rows) <= 4096 and type(contexts) is dict,
        "bounded explicit context batch required")
    _require(all(type(row) is dict and row.get("id") in contexts for row in rows), "missing context batch identity")
    dimensions = {validate_context(row, contexts[row["id"]]) for row in rows}
    _require(len(dimensions) == 1, "mixed context batch dimensions")
    dimension = next(iter(dimensions))
    transform = input_transform
    _require(type(transform) is dict and set(transform) == {"mode", "mean", "scale", "origin"}
        and transform["origin"] == "training_only" and transform["mode"] in ("none", "center_rms"),
        "existing explicit training-only input transform required")
    core._vector(transform["mean"], dimension)
    _require(type(transform["scale"]) in (int, float) and math.isfinite(transform["scale"])
        and .01 <= transform["scale"] <= 1e8, "invalid clause input scale")
    _require(transform["mode"] != "none" or (transform["mean"] == [0.]*dimension and transform["scale"] == 1.),
        "identity clause input transform differs")
    vectors = torch.zeros((len(rows), MAX_CLAUSES, dimension), dtype=torch.float32)
    mask = torch.zeros((len(rows), MAX_CLAUSES), dtype=torch.bool)
    mean = torch.tensor(transform["mean"], dtype=torch.float32)
    for index, row in enumerate(rows):
        values = [segment["vector"] for segment in contexts[row["id"]]["segments"]]
        vectors[index, :len(values)] = (torch.tensor(values, dtype=torch.float32)-mean)/transform["scale"]
        mask[index, :len(values)] = True
    _require(bool(torch.isfinite(vectors).all()), "nonfinite transformed clause vectors")
    return dict(vectors=vectors, mask=mask)


def rebind_context(descriptor, *, row_id, order=None):
    """Copy/reorder source clauses for explicit provenance-breaking controls."""
    _require(type(descriptor) is dict and type(descriptor.get("segments")) is list, "clause descriptor required")
    text = "\n\n".join(segment["source_text"] for segment in descriptor["segments"])
    validate_context(dict(id=row_id, source_text=text), descriptor)
    n = len(descriptor["segments"])
    if order is None: order = list(range(n))
    _require(type(order) is list and all(type(value) is int for value in order)
        and sorted(order) == list(range(n)), "exact clause permutation required")
    segments = [descriptor["segments"][index] for index in order]
    text = "\n\n".join(segment["source_text"] for segment in segments)
    return dict(id=row_id, source_text=text), _descriptor(text, [segment["vector"] for segment in segments])


def validate_published_cache(cache_rows, clause_inventory, *, split):
    """Bind the used cache subset to a separately authenticated publication receipt."""
    _require(split in ("train", "validation") and type(clause_inventory) is dict
        and clause_inventory.get("schema") == "source-clause-cache-prerequisite-inventory/v1"
        and clause_inventory.get("passed") is True and clause_inventory.get("complete") is True
        and clause_inventory.get("findings") == [], "clean authenticated clause-cache inventory required")
    mappings = clause_inventory.get("paragraph_source_mappings", {}).get(split)
    _require(type(mappings) is list and mappings, "published source mappings required")
    lookup = {}
    for row in cache_rows:
        _require(type(row) is dict and set(row) == {"id", "source_text", "input"}, "closed source-only cache row required")
        _source(row); _vector(row["input"])
        _require(row["id"] not in lookup, "duplicate cache identity")
        lookup[row["id"]] = row
    used = set()
    for row in mappings:
        for segment in row["segments"]:
            cached = lookup.get(segment["id"])
            _require(cached is not None and _sha(cached["source_text"]) == segment["source_sha256"]
                and core.digest(cached["input"]) == segment["embedding_sha256"], "published clause cache binding differs")
            used.add(segment["id"])
    return dict(schema="published-clause-cache-binding/v1", split=split, used_clauses=len(used),
        cache_rows_sha256=core.digest(cache_rows), inventory_sha256=core.digest(clause_inventory),
        publication_digest_authentication="caller_verifies_published_file_and_archive_member_hashes",
        encoder_executed=False, admitted=False, qualified=False)


def prepare_source_contexts(training_rows, validation_rows, *, cache_rows, clause_inventory):
    """Authenticate split caches, then construct explicit source-only descriptors."""
    _require(type(cache_rows) is dict and set(cache_rows) == {"train", "validation"},
        "closed split clause caches required")
    result = {}
    for split, rows in (("train", training_rows), ("validation", validation_rows)):
        validate_published_cache(cache_rows[split], clause_inventory, split=split)
        source_rows = []
        for row in rows:
            _source(row)
            source_rows.append(dict(id=row["id"], source_text=row["source_text"]))
        result[split] = build_source_contexts(source_rows, cache_rows[split])
    validate_training_contexts(training_rows, validation_rows, result)
    return result
