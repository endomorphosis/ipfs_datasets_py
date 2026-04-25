from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers import municipal_corpus_rebuilder as rebuilder


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_rebuild_municipal_laws_corpus_normalizes_raw_parquet_pairs(tmp_path, monkeypatch):
    input_root = tmp_path / "raw" / "american_law" / "data"
    citation_path = input_root / "1008538_citation.parquet"
    html_path = input_root / "1008538_html.parquet"

    shared_cid = "bafkmunicipal1"
    _write_rows(
        citation_path,
        [
            {
                "cid": shared_cid,
                "bluebook_cid": "bafkbluebook1",
                "bluebook_citation": "Buncombe, N.C., County Code, §10-66 (2021)",
                "title": "Sec. 10-66. - Organization of department of permits and inspections",
                "chapter": "Chapter 10 - BUILDINGS AND BUILDING REGULATIONS",
                "state_code": "NC",
                "history_note": "Ord. No. 21-05-06, § 1(Exh. A), 5-4-21",
            },
            {
                "cid": shared_cid,
                "bluebook_cid": "bafkbluebook1",
                "bluebook_citation": "Buncombe, N.C., County Code, §10-66 (2021)",
                "title": "Sec. 10-66. - Organization of department of permits and inspections",
                "chapter": "Chapter 10 - BUILDINGS AND BUILDING REGULATIONS",
                "state_code": "NC",
                "history_note": "Ord. No. 21-05-06, § 1(Exh. A), 5-4-21",
            },
        ],
    )
    _write_rows(
        html_path,
        [
            {
                "cid": shared_cid,
                "doc_id": "DOC-10-66",
                "doc_order": 83,
                "html_title": "<div class=\"chunk-title\">Sec. 10-66. - Organization of department of permits and inspections.</div>",
                "html": "<div><p>The department is hereby established pursuant to G.S. 160D-402(b).</p></div>",
            }
        ],
    )

    def _fake_build_canonical_corpus_artifacts(*args: object, **kwargs: object) -> dict[str, object]:
        canonical_path = str(kwargs["canonical_parquet_path"])
        return {
            "corpus_key": args[0] if args else kwargs.get("corpus_key"),
            "canonical_parquet_path": canonical_path,
            "updated_canonical_parquet_path": canonical_path,
        }

    monkeypatch.setattr(rebuilder, "build_canonical_corpus_artifacts", _fake_build_canonical_corpus_artifacts)
    monkeypatch.setattr(rebuilder, "canonical_corpus_artifact_build_result_to_dict", lambda result: dict(result))

    result = rebuilder.rebuild_municipal_laws_corpus(
        input_root=input_root,
        output_root=tmp_path / "out",
        build_faiss=False,
    )

    assert result.source_row_count == 2
    assert result.row_count == 1
    assert result.state_row_counts == {"NC": 1}
    assert sorted(result.state_parquet_paths) == ["NC"]
    assert len(result.artifact_results) == 2

    canonical_rows = pq.read_table(result.combined_parquet_path).to_pylist()
    assert len(canonical_rows) == 1
    row = canonical_rows[0]
    assert row["ipfs_cid"] == shared_cid
    assert row["state_code"] == "NC"
    assert row["source_id"] == "bafkbluebook1"
    assert row["identifier"] == "Buncombe, N.C., County Code, §10-66 (2021)"
    assert row["name"].startswith("Sec. 10-66.")
    assert "department is hereby established" in row["text"].lower()

    jsonld_payload = json.loads(row["jsonld"])
    assert jsonld_payload["@id"] == f"ipfs://{shared_cid}"
    assert jsonld_payload["legislationJurisdiction"] == "NC"
    assert jsonld_payload["citation"] == "Buncombe, N.C., County Code, §10-66 (2021)"
