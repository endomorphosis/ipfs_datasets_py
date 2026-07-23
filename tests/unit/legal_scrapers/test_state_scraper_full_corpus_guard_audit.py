import importlib.util
import sys
from pathlib import Path


def _load_audit_module():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "ops" / "legal_data" / "audit_state_scraper_full_corpus_guards.py"
    spec = importlib.util.spec_from_file_location("audit_state_scraper_full_corpus_guards", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_full_corpus_guard_audit_accepts_unbounded_api_walk():
    audit = _load_audit_module()
    repo_root = Path(__file__).resolve().parents[3]
    path = (
        repo_root
        / "ipfs_datasets_py"
        / "processors"
        / "legal_scrapers"
        / "state_scrapers"
        / "south_dakota.py"
    )

    findings = audit.audit_file(state="SD", path=path, repo_root=repo_root)

    assert findings == []


def test_full_corpus_guard_audit_flags_unguarded_seed_return(tmp_path):
    audit = _load_audit_module()
    scraper = tmp_path / "unsafe_state.py"
    scraper.write_text(
        """
class UnsafeScraper:
    async def scrape_code(self, code_name, code_url, max_statutes=None):
        seed_rows = await self._scrape_seed_sections(code_name)
        if seed_rows:
            return seed_rows
        return []
""",
        encoding="utf-8",
    )

    findings = audit.audit_file(state="ZZ", path=scraper, repo_root=tmp_path)

    assert len(findings) == 1
    assert findings[0].kind == "unguarded_seed_or_recovery_return"
    assert findings[0].severity == "error"
