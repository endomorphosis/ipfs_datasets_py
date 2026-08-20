"""Protected ISI-043 gates for frontend-authoritative Python inventory."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from textwrap import dedent

from ipfs_datasets_py.logic.software_contracts.python_frontend import (
    PythonASTExtractor,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    SymbolKind,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import (
    analyze_python_source,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import (
    scan_repository_state,
)

PATH = "pkg/authority.py"
REPOSITORY_ID = "repo:python-authority-adversarial"
_FRONTEND_ADDRESSABLE_KINDS = {
    "class",
    "constructor",
    "function",
    "method",
    "variable",
}


def _analyze(source: str):
    return analyze_python_source(source, PATH, REPOSITORY_ID)


def _by_name(source: str):
    return {fact.symbol.qualified_name: fact for fact in _analyze(source).symbols}


def test_inventory_is_a_grouping_of_canonical_frontend_declarations() -> None:
    source = dedent("""\
        FLAG = True

        if FLAG:
            def conditional():
                return "left"
        else:
            def conditional():
                return "right"

        try:
            operation()
        except RuntimeError:
            def recovered():
                return "except"

        match subject:
            case {"value": captured}:
                class Matched:
                    value = captured

        class Holder:
            field: int = 1

            def method(self):
                return self.field
        """)
    frontend = PythonASTExtractor().extract(
        source,
        path=PATH,
        repository_id=REPOSITORY_ID,
    )
    analysis = _analyze(source)

    canonical: dict[str, list[str]] = defaultdict(list)
    for declaration in frontend.symbols:
        if declaration.kind in _FRONTEND_ADDRESSABLE_KINDS:
            canonical[declaration.qualified_name].append(declaration.symbol_id)

    projected = {
        fact.symbol.qualified_name: list(fact.symbol.metadata["frontend_declarations"])
        for fact in analysis.symbols
        if fact.symbol.kind != SymbolKind.MODULE
    }
    assert projected == dict(canonical)
    assert {
        "pkg.authority.conditional",
        "pkg.authority.recovered",
        "pkg.authority.Matched",
    } <= projected.keys()
    assert len(projected["pkg.authority.conditional"]) == 2
    assert all(
        _by_name(source)[name].symbol.confidence != AnalysisConfidence.EXACT
        for name in (
            "pkg.authority.conditional",
            "pkg.authority.recovered",
            "pkg.authority.Matched",
        )
    )
    assert not analysis.diagnostics


def test_nested_child_body_edits_do_not_version_any_parent_projection() -> None:
    def source(inner: int, local_method: int, class_method: int) -> str:
        return dedent(f"""\
            FLAG = True

            def outer():
                if FLAG:
                    def inner():
                        return {inner}

                    class Local:
                        if FLAG:
                            def method(self):
                                return {local_method}
                return inner, Local

            class Container:
                if FLAG:
                    def conditional(self):
                        return {class_method}
            """)

    before = _by_name(source(1, 2, 3))
    after = _by_name(source(11, 22, 33))

    for name in (
        "pkg.authority.outer.inner",
        "pkg.authority.outer.Local.method",
        "pkg.authority.Container.conditional",
    ):
        assert before[name].symbol.version_cid != after[name].symbol.version_cid
    for name in (
        "pkg.authority",
        "pkg.authority.outer",
        "pkg.authority.outer.Local",
        "pkg.authority.Container",
    ):
        assert before[name].symbol.version_cid == after[name].symbol.version_cid


def test_overload_only_edit_changes_public_signature_and_version() -> None:
    before = _by_name(dedent("""\
            from typing import overload

            @overload
            def convert(value: int) -> int: ...

            @overload
            def convert(value: bytes) -> bytes: ...

            def convert(value):
                return value
            """))["pkg.authority.convert"].symbol
    after = _by_name(dedent("""\
            from typing import overload

            @overload
            def convert(value: float) -> float: ...

            @overload
            def convert(value: bytes) -> bytes: ...

            def convert(value):
                return value
            """))["pkg.authority.convert"].symbol

    assert before.stable_id == after.stable_id
    assert before.signature != after.signature
    assert before.version_cid != after.version_cid


def test_module_and_local_aliases_preserve_model_kind_classification() -> None:
    facts = _by_name(dedent("""\
            from dataclasses import dataclass
            from dataclasses import dataclass as record
            from enum import IntEnum
            from enum import IntEnum as IntegerEnum
            from pydantic import BaseModel
            from pydantic import BaseModel as ModelBase
            from typing import TypedDict
            from typing import TypedDict as DictionaryBase

            class DirectEnum(IntEnum):
                VALUE = 1

            class AliasedEnum(IntegerEnum):
                VALUE = 1

            class DirectDictionary(TypedDict):
                value: int

            class AliasedDictionary(DictionaryBase):
                value: int

            @dataclass
            class DirectRecord:
                value: int

            @record
            class AliasedRecord:
                value: int

            class DirectModel(BaseModel):
                value: int

            class AliasedModel(ModelBase):
                value: int

            def local_models():
                from dataclasses import dataclass as local_record
                from enum import IntEnum as LocalIntegerEnum
                from pydantic import BaseModel as LocalModelBase
                from typing import TypedDict as LocalDictionaryBase

                class LocalEnum(LocalIntegerEnum):
                    VALUE = 1

                class LocalDictionary(LocalDictionaryBase):
                    value: int

                @local_record
                class LocalRecord:
                    value: int

                class LocalModel(LocalModelBase):
                    value: int

                return LocalEnum, LocalDictionary, LocalRecord, LocalModel
            """))

    expected_kinds = {
        "DirectEnum": SymbolKind.ENUM,
        "AliasedEnum": SymbolKind.ENUM,
        "DirectDictionary": SymbolKind.TYPED_DICT,
        "AliasedDictionary": SymbolKind.TYPED_DICT,
        "DirectRecord": SymbolKind.DATACLASS,
        "AliasedRecord": SymbolKind.DATACLASS,
        "local_models.LocalEnum": SymbolKind.ENUM,
        "local_models.LocalDictionary": SymbolKind.TYPED_DICT,
        "local_models.LocalRecord": SymbolKind.DATACLASS,
    }
    assert {
        suffix: facts[f"pkg.authority.{suffix}"].symbol.kind
        for suffix in expected_kinds
    } == expected_kinds
    for suffix in (
        "DirectModel",
        "AliasedModel",
        "local_models.LocalModel",
    ):
        assert (
            facts[f"pkg.authority.{suffix}"].symbol.annotations["pydantic_model"]
            is True
        )


def test_aliased_functional_typed_dict_keywords_and_total_are_versioned() -> None:
    def movie(total: bool):
        return _by_name(dedent(f"""\
                from typing import TypedDict as Dictionary

                Movie = Dictionary(
                    "Movie",
                    title=str,
                    year=int,
                    total={total},
                )
                """))["pkg.authority.Movie"].symbol

    optional = movie(False)
    required = movie(True)

    assert optional.kind == required.kind == SymbolKind.TYPED_DICT
    assert dict(optional.annotations["fields"]) == {
        "title": "str",
        "year": "int",
    }
    assert "total" in optional.annotations
    assert optional.annotations["total"] != required.annotations["total"]
    assert optional.stable_id == required.stable_id
    assert optional.version_cid != required.version_cid


def test_nonfatal_frontend_evidence_survives_the_public_scanner(
    tmp_path: Path,
) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    source = dedent("""\
        import importlib

        class Meta(type):
            pass

        def evaluated(text):
            return eval(text)

        def loaded(name):
            return importlib.import_module(name)

        class Generated(metaclass=Meta):
            pass

        def outer():
            value = 0

            def mutate():
                nonlocal value
                value += 1
                return value

            return mutate
        """)
    (package / "uncertain.py").write_text(source, encoding="utf-8")

    state = scan_repository_state(tmp_path, repository_id=REPOSITORY_ID)
    symbols = {symbol.qualified_name: symbol for symbol in state.symbols}
    expected = {
        "pkg.uncertain.evaluated",
        "pkg.uncertain.loaded",
        "pkg.uncertain.Generated",
        "pkg.uncertain.outer.mutate",
    }

    assert expected <= symbols.keys()
    for name in expected:
        assert symbols[name].confidence in {
            AnalysisConfidence.CONSERVATIVE,
            AnalysisConfidence.OPAQUE,
        }
        assert symbols[name].metadata["confidence_reasons"]
    assert not [
        artifact for artifact in state.artifacts if artifact.kind == "python-analysis"
    ]


def test_malformed_input_alone_becomes_a_whole_file_opaque_artifact(
    tmp_path: Path,
) -> None:
    source = "def broken(:\n"
    (tmp_path / "broken.py").write_text(source, encoding="utf-8")

    analysis = analyze_python_source(
        source,
        "broken.py",
        REPOSITORY_ID,
    )
    state = scan_repository_state(tmp_path, repository_id=REPOSITORY_ID)
    opaque = [
        artifact for artifact in state.artifacts if artifact.kind == "python-analysis"
    ]

    assert not analysis.symbols
    assert "python.parse_error" in analysis.diagnostics
    assert not state.symbols
    assert len(opaque) == 1
    assert opaque[0].path == "broken.py"
    assert opaque[0].confidence == AnalysisConfidence.OPAQUE
    assert "python.parse_error" in opaque[0].metadata["diagnostics"]
