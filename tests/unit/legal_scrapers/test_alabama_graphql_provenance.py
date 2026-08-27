"""Alabama ALISON GraphQL provenance projection regressions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    _write_state_jsonld_files,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.alabama import (
    AlabamaScraper,
)
from ipfs_datasets_py.processors.legal_scrapers.state_scrapers.base_scraper import (
    NormalizedStatute,
)


def test_alabama_jsonld_retains_graphql_batch_digest_for_strict_closure(
    tmp_path: Path,
) -> None:
    scraper = AlabamaScraper("AL", "Alabama")
    graphql_body = b'{"data":{"codeItems":{"data":[{"codeId":"14515"}]}}}'
    digest = hashlib.sha256(graphql_body).hexdigest()
    receipt = {
        "content_sha256": digest,
        "official_url": scraper.GRAPHQL_URL,
        "source_transport": "direct",
    }
    ledger = StateLawMultiFetchAcquisitionLedger(
        tmp_path / "evidence",
        jurisdiction="AL",
        parser_name="AlabamaScraper",
    )
    ledger.retain_parser_input(
        official_url=scraper.GRAPHQL_URL,
        body=graphql_body,
        transport_receipt=receipt,
        media_type="application/json",
    )

    statute = NormalizedStatute(
        state_code="AL",
        state_name="Alabama",
        statute_id="Alabama Code § 1-1-1 [ALISON:14515]",
        code_name="Alabama Code",
        section_number="1-1-1",
        section_name="Section 1-1-1 Meaning of Certain Words and Terms.",
        full_text=(
            "The following words have the meanings stated in this section, "
            "unless the context clearly requires otherwise."
        ),
        source_url=f"{scraper.CODE_URL}?section=1-1-1",
        official_cite="Ala. Code § 1-1-1",
        structured_data={
            "content_sha256": digest,
            "source_kind": "official_alison_graphql",
            "source_record_id": "alison:code:14515",
            "transport_receipt": receipt,
        },
    )
    enriched = scraper._enrich_statute_structure(statute)

    jsonld_dir = tmp_path / "jsonld"
    jsonld_dir.mkdir()
    written = _write_state_jsonld_files(
        [
            {
                "state_code": "AL",
                "state_name": "Alabama",
                "statutes": [enriched.to_dict()],
            }
        ],
        jsonld_dir,
    )

    assert len(written) == 1
    canonical_path = Path(written[0])
    payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert payload["sourceUrl"] == f"{scraper.CODE_URL}?section=1-1-1"
    assert payload["provenance"] == {
        "content_sha256": digest,
        "source_record_id": "alison:code:14515",
        "transport_receipt": receipt,
    }

    coverage = ledger.audit_canonical_jsonld_coverage(canonical_path)
    assert coverage["complete"] is True
    assert coverage["covered_by_content_digest"] == 1
    assert coverage["covered_by_official_url"] == 0
    assert coverage["uncovered_unit_count"] == 0
