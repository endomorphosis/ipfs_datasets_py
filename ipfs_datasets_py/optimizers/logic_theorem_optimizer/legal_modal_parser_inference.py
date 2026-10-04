"""Private compiled-cue cache for the unchanged deterministic Legal parser."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import importlib
from pathlib import Path
import re
from types import FunctionType


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()
_PARSER_MODULES = (
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_modal_parser",
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1._snapshot.legal_modal_parser",
)


@lru_cache(maxsize=4096)
def _compile(pattern, flags=0):
    return re.compile(pattern, flags)


@lru_cache(maxsize=4096)
def _escaped(implementation, text):
    return implementation(text)


class _CompiledRegex:
    """Delegate regex semantics; retain compiled cue patterns independently."""
    compile = staticmethod(_compile)

    @staticmethod
    def escape(text):
        # Escape immutable built-in cue strings once. Keep the implementation
        # in the key so replacing the regex dependency is immediately visible;
        # subclasses can override translate and must be evaluated every time.
        if type(text) in (str, bytes):
            return _escaped(re.escape, text)
        return re.escape(text)

    def __getattr__(self, name):
        return getattr(re, name)


_REGEX = _CompiledRegex()


def inference_implementation():
    if _source_sha256() != _SOURCE_AT_IMPORT:
        raise ValueError("compiled-cue parser implementation changed since import")
    return {"schema": "legal-compiled-cue-parser/v1", "source_sha256": _SOURCE_AT_IMPORT,
            "original_parser_code_preserved": True, "compiled_pattern_cache_limit": 4096,
            "escaped_cue_cache_limit": 4096}


@lru_cache(maxsize=2)
def _parser_class(module_name):
    if module_name not in _PARSER_MODULES:
        raise ValueError("unknown Legal parser implementation")
    base = importlib.import_module(module_name).LegalModalParser

    class CompiledCueParser(base):
        def extract_cues(self, text):
            inference_implementation()
            original = base.extract_cues
            # Keep the original function's exact code, filters and ordering.
            # Its private globals differ only in the regex-cache dependency;
            # refresh them each call so registry/global changes remain visible.
            namespace = original.__globals__.copy()
            namespace["re"] = _REGEX
            extraction = FunctionType(original.__code__, namespace,
                                      original.__name__, original.__defaults__, original.__closure__)
            return extraction(self, text)

    return CompiledCueParser


def build_parser(module_name=_PARSER_MODULES[0], **options):
    inference_implementation()
    return _parser_class(module_name)(**options)
