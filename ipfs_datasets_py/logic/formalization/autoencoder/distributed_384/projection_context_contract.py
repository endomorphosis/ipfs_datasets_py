"""Portable caller declarations bound to one unchanged candidate and source.

A digest establishes identity, not semantic truth or permission to train. The
numerical v1 plans and their published producer pins remain unchanged.
"""
from copy import deepcopy
import hashlib

from .contracts import DOMAINS, FALSE, digest, raw, require

SCHEMA = "distributed-384-projection-context/v1"
MAX_CONTEXT_BYTES = 8 * 1024 * 1024


def _source_hash(source_text):
    require(type(source_text) is str and source_text.strip()
        and len(source_text.encode()) <= 1048576, "bounded nonempty exact source text required")
    return hashlib.sha256(source_text.encode()).hexdigest()


def bind_context(domain, target, source_text, inputs):
    require(type(domain) is str and domain in DOMAINS, "supported context domain required")
    require(type(target) is dict and type(inputs) is dict, "typed candidate and context input objects required")
    record = dict(schema=SCHEMA, domain_id=domain, source_sha256=_source_hash(source_text),
                  candidate_sha256=digest(target), inputs=deepcopy(inputs), **FALSE)
    require(len(raw(record)) <= MAX_CONTEXT_BYTES, "projection context exceeds byte bound")
    record["context_sha256"] = digest(record)
    return record


def validate_context(context, domain, target, source_text):
    require(type(context) is dict and set(context) == {"schema", "domain_id", "source_sha256",
        "candidate_sha256", "inputs", "context_sha256", *FALSE}, "closed bound projection context required")
    expected = bind_context(domain, target, source_text, context["inputs"])
    require(raw(context) == raw(expected), "projection context source, candidate, domain, identity or authority differs")
    return deepcopy(context["inputs"])
