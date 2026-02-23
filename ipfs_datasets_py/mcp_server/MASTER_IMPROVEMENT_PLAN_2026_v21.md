# MASTER IMPROVEMENT PLAN 2026 — v21

**Branch:** `copilot/create-refactoring-plan-again`
**Date:** 2026-02-23
**Status:** ✅ v21 Complete — 51 new tests, **3,283 total**

---

## 1. Session Summary (v21)

| Session | Component | Change | Tests |
|---------|-----------|--------|-------|
| DG169 | `policy_audit_log.py` | `import_jsonl()` skips `__metadata__` header lines | 7 |
| DH170 | `compliance_checker.py` | `merge(include_protected_rules=False)` — skips non-removable rules by default | 6 |
| DI171 | `nl_ucan_policy_compiler.py` | `compile_explain_iter()` — yields explanation lines lazily | 6 |
| DJ172 | `logic/CEC/nl/portuguese_parser.py` (**NEW**) | `PortugueseParser` + `get_portuguese_deontic_keywords()` | 8 |
| DK173 | `ucan_delegation.py` | `DelegationManager.merge_and_publish_async(other, pubsub)` | 6 |
| DL174 | `policy_audit_log.py` + `ucan_delegation.py` | Full E2E: merge → export_jsonl(metadata) → import_jsonl round-trip | 4 |
| DM175 | `compliance_checker.py` | `diff()` + `merge()` combined idempotency E2E | 6 |
| DN176 | `nl_policy_conflict_detector.py` + `api.py` | `_NL_DEONTIC_KEYWORDS` (Dutch inline) + `detect_all_languages()` covers **6 languages** | 8 |

---

## 2. Production Changes (v21)

### `ipfs_datasets_py/mcp_server/policy_audit_log.py`

- **DG169** — `import_jsonl()` now skips lines whose top-level JSON key is
  `"__metadata__"` (written by `export_jsonl(metadata=...)` — CZ162). The
  skip is DEBUG-logged and does **not** count towards the return value.  Full
  round-trip `export_jsonl(metadata=...)` → `import_jsonl()` works
  transparently.

### `ipfs_datasets_py/mcp_server/compliance_checker.py`

- **DH170** — `merge(other, *, include_protected_rules: bool = False)` — New
  keyword-only flag `include_protected_rules`.  Default `False`: rules with
  `removable=False` are **skipped** (they are treated as built-in/protected
  and should not be propagated across checker boundaries).  Set
  `include_protected_rules=True` to copy all rules regardless of the `removable` flag.

### `ipfs_datasets_py/logic/integration/nl_ucan_policy_compiler.py`

- **DI171** — `compile_explain_iter(sentences, policy_id=None)` → `Iterator[str]`
  Added `Iterator` to the `typing` import.  Compiles once and yields the
  explanation string split on `\n`.  Collected lines joined with `"\n"` equal
  `result.explain().rstrip("\n")`.

### `ipfs_datasets_py/logic/CEC/nl/portuguese_parser.py` *(NEW)*

- **DJ172** — New module providing:
  - `_PT_PERMISSION_KEYWORDS`, `_PT_PROHIBITION_KEYWORDS`, `_PT_OBLIGATION_KEYWORDS`
  - `_PT_DEONTIC_KEYWORDS: Dict[str, List[str]]`
  - `get_portuguese_deontic_keywords() -> Dict[str, List[str]]`
  - `PortugueseClause(text, deontic_type, matched_keyword)` dataclass
  - `PortugueseParser.parse(text) -> List[PortugueseClause]` — keyword-based,
    no external NLP deps

### `ipfs_datasets_py/logic/CEC/nl/nl_policy_conflict_detector.py`

- **DJ172** — `"pt"` added to `_I18N_KEYWORD_LOADERS` pointing to
  `portuguese_parser:get_portuguese_deontic_keywords`.
- **DN176** — `_NL_DEONTIC_KEYWORDS: Dict[str, List[str]]` (Dutch inline,
  no external module).  `_load_i18n_keywords("nl")` returns inline table
  directly (same pattern as `"en"`).

### `ipfs_datasets_py/logic/api.py`

- **DJ172/DN176** — `detect_all_languages()` now covers **6 languages**:
  `("fr", "es", "de", "en", "pt", "nl")`.  English and Dutch use inline
  tables; Portuguese uses `portuguese_parser.py`; FR/ES/DE use their
  respective parser modules.

### `ipfs_datasets_py/mcp_server/ucan_delegation.py`

- **DK173** — `DelegationManager.merge_and_publish_async(other, pubsub)` —
  async coroutine.  Uses `await pubsub.publish_async(...)` when pubsub has a
  coroutine `publish_async`; falls back to synchronous `publish()` otherwise.
  Exceptions swallowed at DEBUG.  Payload identical to `merge_and_publish()`.

---

## 3. Key Invariants (v21)

| Component | Invariant |
|-----------|-----------|
| `import_jsonl()` (DG169) | Lines with `"__metadata__"` key are skipped silently; return value excludes them |
| `ComplianceChecker.merge(include_protected_rules=False)` (DH170) | Non-removable rules NOT copied by default; `include_protected_rules=True` overrides |
| `compile_explain_iter()` (DI171) | Returns `types.GeneratorType`; collected lines == `explain().rstrip("\n")` |
| `PortugueseParser` (DJ172) | No external deps; `parse(text)` returns `List[PortugueseClause]` |
| `merge_and_publish_async()` (DK173) | Async coroutine; prefers `publish_async` over `publish`; exceptions swallowed |
| `detect_all_languages()` (DN176) | Returns 6-language report `{"fr","es","de","en","pt","nl"}`; old `>= {"fr","es","de","en"}` tests still pass |
| `detect_i18n_conflicts(text, "nl")` (DN176) | Uses `_NL_DEONTIC_KEYWORDS` inline; no external module required |

---

## 4. Test Coverage (v21)

| Test class | Session | Tests |
|-----------|---------|-------|
| `TestDG169ImportJsonlSkipsMetadata` | DG169 | 7 |
| `TestDH170MergeCopyDisabled` | DH170 | 6 |
| `TestDI171CompileExplainIter` | DI171 | 6 |
| `TestDJ172PortugueseParser` | DJ172 | 8 |
| `TestDK173MergeAndPublishAsync` | DK173 | 6 |
| `TestDL174FullRoundTrip` | DL174 | 4 |
| `TestDM175DiffMergeIdempotency` | DM175 | 6 |
| `TestDN176DutchKeywords` | DN176 | 8 |
| **v21 total** | | **51** |

---

## 5. Cumulative Totals

| Version | Tests added | Running total |
|---------|------------|---------------|
| v13 | 77 | 2,805 |
| v14 | 114 | 2,884 (MCP+logic split) |
| v15 | 69 | 2,953 |
| v16 | 63 | 3,016 |
| v17 | 57 | 3,073 |
| v18 | 39 | 3,112 |
| v19 | 59 | 3,171 |
| v20 | 61 | 3,232 |
| **v21** | **51** | **3,283** |

---

## 6. v22 Candidates

| Session | Target | Effort | Priority |
|---------|--------|--------|----------|
| DO177 | `detect_all_languages()` — add `"it"` (Italian) inline keywords | Low | 🟡 Med |
| DP178 | `PortugueseParser.parse()` — sentence-level splitting + multi-clause extraction | Med | 🟡 Med |
| DQ179 | `DelegationManager.merge_and_publish_async()` — include pubsub event type `RECEIPT_DISSEMINATE` | Low | 🟢 Low |
| DR180 | `PolicyAuditLog.import_jsonl()` — `max_entries` clipping test across large files | Low | 🟡 Med |
| DS181 | `ComplianceChecker.merge(include_protected_rules=True)` — deep copy rules to avoid mutation | Med | 🟡 Med |
| DT182 | `compile_explain_iter()` — `max_lines=None` parameter to truncate output | Low | 🟢 Low |
| DU183 | `detect_i18n_conflicts()` — `"nl"` obligation keyword test | Low | 🟢 Low |
| DV184 | `DelegationManager.get_metrics()` — `active_token_count` (non-revoked only) | Med | 🔴 High |
| DW185 | `logic/api.py` — `compile_explain_iter` re-export | Low | 🟢 Low |
| DX186 | Full E2E with 6-language `detect_all_languages()` + real conflict text | Med | 🔴 High |
