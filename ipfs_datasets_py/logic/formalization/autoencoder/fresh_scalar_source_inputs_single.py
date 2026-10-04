"""One explicitly identified source width, with the original native validation.

This does not relax the historical three-width schema or synthesize missing
representations. Resource admission and comparison sealing belong to the caller.
"""
from copy import deepcopy

from . import clause_source_context as clauses
from . import fresh_scalar_source_inputs as source

SCHEMA = "fresh-scalar-source-inputs-single/v1"


def assemble(plan, report, *, dimension):
    source._require(type(dimension) is int and dimension in (8, 384, 768),
                    "explicit native source dimension required")
    owned = source._plan(plan)
    source._require(source._validate_report(owned, report) == dimension,
                    "native production dimension differs")
    vectors = {row["source_sha256"]: row["vector"] for row in report["vectors"]}
    source._require(len(vectors) == len(owned["source_inputs"]),
                    "native source vectors must be unique and complete")
    rows = [dict(row, input=deepcopy(vectors[source.authored.text_sha(row["source_text"])]))
            for row in owned["source_rows"]]
    cache, seen = [], set()
    for row in owned["source_rows"]:
        for text in row["source_text"].split("\n\n"):
            digest = source.authored.text_sha(text)
            if digest not in seen:
                seen.add(digest)
                cache.append(dict(id="clause:" + digest, source_text=text,
                                  input=deepcopy(vectors[digest])))
    contexts = clauses.build_source_contexts(owned["source_rows"], cache)
    checked = clauses.validate_contexts(rows, contexts)
    source._require(checked["dimension"] == dimension, "assembled context width differs")
    result = dict(
        schema=SCHEMA, complete=True, dimension=dimension,
        rows=rows, clause_cache=cache, source_contexts=contexts,
        representation=deepcopy(report["representation"]),
        production_sha256=report["production_sha256"],
        source_plan_sha256=owned["plan_sha256"],
        source_rows_sha256=owned["source_rows_sha256"],
        sealed_comparison_sha256=owned["sealed_comparison_sha256"],
        source_aliases=deepcopy(owned["source_aliases"]),
        comparison_seal_verified=False, **source.FALSE,
    )
    result["inputs_sha256"] = source.digest(result)
    return result
