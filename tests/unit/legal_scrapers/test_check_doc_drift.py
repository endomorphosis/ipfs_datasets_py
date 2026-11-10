"""LCM-075: docs must quote landed kind, adapter, and view version constants.

The checker fails when a doc omits a constant or cites a different string.
It does not rewrite a doc to hide a mismatch.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_CHECKER = (
    Path(__file__).resolve().parents[3]
    / "ipfs_datasets_py/processors/legal_scrapers/legal_corpus/check_doc_drift.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("lcm_check_doc_drift", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_view_reader_uses_the_pinned_version_not_the_label() -> None:
    checker = _load()
    text = """
export const LAW_KIND_VERSION = pinned(
  KIND_VERSIONS.law,
  'legal-corpus.law@1',
  'KIND_VERSIONS.law',
);
export const ACT_SOURCE_SCHEMA_IDS = [
  'public-law-change-processor-v1',
  'public-law-change-fixture-v1',
] as const;
export const QUERY_PLACE = 'argument' as const;
const LAW_VERIFY_SCHEMA_PIN = 'country-laws-normalize-verify/v1';
"""
    rows = checker.read_view_text("law.ts", text, "view-site")
    found = {(row.name, row.value) for row in rows}
    assert ("LAW_KIND_VERSION", "legal-corpus.law@1") in found
    assert ("ACT_SOURCE_SCHEMA_IDS", "public-law-change-processor-v1") in found
    assert ("ACT_SOURCE_SCHEMA_IDS", "public-law-change-fixture-v1") in found
    assert ("LAW_VERIFY_SCHEMA_PIN", "country-laws-normalize-verify/v1") in found
    assert all(row.name != "QUERY_PLACE" for row in rows)
    assert all(row.value != "KIND_VERSIONS.law" for row in rows)


def test_omission_and_different_citation_fail_without_crossing_families() -> None:
    checker = _load()
    constants = [
        checker.VersionConstant("kinds", "kinds/law_v1.py", "INTERFACE_ID", "legal-corpus.law@1"),
        checker.VersionConstant("adapters", "adapters/us_code_v1.py", "INTERFACE_ID", "legal-corpus.law@1"),
        checker.VersionConstant("view-site", "law.ts", "LAW_KIND_VERSION", "legal-corpus.law@1"),
    ]
    documents = {
        "kinds": "`INTERFACE_ID` `legal-corpus.law@1`",
        "adapters": "`INTERFACE_ID` `legal-corpus.law@9` and `legal-corpus.law@1`",
        "view-site": "the view doc names no version",
    }
    findings = checker.find_drift(constants, documents)
    omitted = [item for item in findings if item.kind == "omitted"]
    different = [item for item in findings if item.kind == "different_string"]
    assert [item.document for item in omitted] == ["view-site"]
    assert omitted[0].value == "legal-corpus.law@1"
    assert [item.document for item in different] == ["adapters"]
    assert different[0].name == "INTERFACE_ID"
    assert different[0].value == "legal-corpus.law@1"
    assert different[0].cited == "legal-corpus.law@9"
    assert all(item.document != "kinds" for item in findings)


def test_a_different_citation_fails_while_the_real_string_is_still_present() -> None:
    checker = _load()
    constants = [
        checker.VersionConstant("kinds", "kinds/law_v1.py", "INTERFACE_ID", "legal-corpus.law@1"),
    ]
    documents = {
        "kinds": "`INTERFACE_ID` `legal-corpus.law@1` `INTERFACE_ID` `legal-corpus.law@2`",
    }
    findings = checker.find_drift(constants, documents)
    assert len(findings) == 1
    assert findings[0].kind == "different_string"
    assert findings[0].value == "legal-corpus.law@1"
    assert findings[0].cited == "legal-corpus.law@2"


@pytest.mark.parametrize("citation", [
    "| `INTERFACE_ID` | `legal-corpus.law@9` |",
    "`INTERFACE_ID` is `legal-corpus.law@9`",
    "`INTERFACE_ID` to `legal-corpus.law@9`",
])
def test_wrong_citation_reports_expected_and_actual(citation: str) -> None:
    checker = _load()
    constant = checker.VersionConstant(
        "kinds", "kinds/law_v1.py", "INTERFACE_ID", "legal-corpus.law@1",
    )
    findings = checker.find_drift(
        [constant], {"kinds": citation + "\nAlso `legal-corpus.law@1`."},
    )
    assert len(findings) == 1
    assert findings[0].kind == "different_string"
    assert findings[0].value == "legal-corpus.law@1"
    assert findings[0].cited == "legal-corpus.law@9"
    assert "legal-corpus.law@1\tcited=legal-corpus.law@9" in checker.format_finding(findings[0])


def test_another_modules_version_cannot_hide_a_wrong_citation() -> None:
    checker = _load()
    constants = [
        checker.VersionConstant("kinds", "kinds/law_v1.py", "INTERFACE_ID", "legal-corpus.law@1"),
        checker.VersionConstant(
            "kinds", "kinds/regulation_v1.py", "INTERFACE_ID", "legal-corpus.regulation@1",
        ),
    ]
    documents = {"kinds": (
        "## Law\n`kinds/law_v1.py` assigns `INTERFACE_ID` `legal-corpus.regulation@1`.\n"
        "## Regulation\n`kinds/regulation_v1.py` assigns `INTERFACE_ID` `legal-corpus.regulation@1`.\n"
        "Other text still mentions `legal-corpus.law@1`.\n"
    )}
    findings = checker.find_drift(constants, documents)
    assert any(
        item.kind == "different_string" and item.module == "kinds/law_v1.py"
        and item.value == "legal-corpus.law@1" and item.cited == "legal-corpus.regulation@1"
        for item in findings
    )


@pytest.mark.parametrize("family", ["kinds", "adapters", "view-site", "view-swissknife"])
def test_missing_version_makes_the_command_fail(family: str, monkeypatch, capsys) -> None:
    checker = _load()
    constants = [checker.VersionConstant(family, "example.py", "SCHEMA_VERSION", "example@1")]
    findings = checker.find_drift(constants, {family: "The version was omitted."})
    monkeypatch.setattr(checker, "check_landed", lambda: findings)
    assert checker.main() == 1
    assert "example@1" in capsys.readouterr().out


def test_matching_versions_make_the_command_succeed(monkeypatch, capsys) -> None:
    checker = _load()
    monkeypatch.setattr(checker, "check_landed", lambda: ())
    assert checker.main() == 0
    assert capsys.readouterr().out == "ok\n"


def test_matching_citations_pass() -> None:
    checker = _load()
    constants = [
        checker.VersionConstant("kinds", "kinds/law_v1.py", "INTERFACE_ID", "legal-corpus.law@1"),
        checker.VersionConstant(
            "view-swissknife",
            "law.ts",
            "LAW_SOURCE_VIEW_ID",
            "worldwide-legal-search.law-source@1",
        ),
    ]
    documents = {
        "kinds": "`kinds/law_v1.py` assigns `INTERFACE_ID` `legal-corpus.law@1`.",
        "view-swissknife": (
            "`law.ts` exports `LAW_SOURCE_VIEW_ID` "
            "`worldwide-legal-search.law-source@1`."
        ),
    }
    assert checker.find_drift(constants, documents) == ()


def test_absent_document_is_an_omission() -> None:
    checker = _load()
    constants = [
        checker.VersionConstant("adapters", "adapters/court_v1.py", "SOURCE_SCHEMA_ID", "unversioned"),
    ]
    findings = checker.find_drift(constants, {})
    assert len(findings) == 1
    assert findings[0].kind == "omitted"
    assert findings[0].name == "document"
    assert findings[0].document == "adapters"


def test_checker_does_not_write_docs() -> None:
    source = _CHECKER.read_text(encoding="utf-8")
    assert "write_text" not in source
    assert ".write(" not in source
    assert "open(" not in source


def test_landed_docs_quote_the_module_constants() -> None:
    checker = _load()
    assert checker.check_landed() == ()
