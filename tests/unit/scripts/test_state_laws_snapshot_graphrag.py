"""Snapshot GraphRAG inventory, assembler, and tiny builder canary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    EXACT_51_JURISDICTION_CODES,
)
from ipfs_datasets_py.processors.legal_data.state_laws_snapshot_graphrag import (
    DEFAULT_SNAPSHOT_HUB_REPO_ID,
    REMAINING_TMP_LAWS_STATES,
    SnapshotGraphragError,
    apply_skillcenter_snapshot_release,
    assemble_corpus,
    assemble_jurisdiction,
    inventory_all,
    inventory_jurisdiction,
    map_jsonld_to_oul_row,
    map_normalized_statute_to_oul_row,
    publish_snapshot_research_hf,
    refuse_authorizing_for_publication,
    refuse_live_dest,
    refuse_official_current_bundle_repo,
)
from scripts.ops.legal_data.assemble_state_laws_snapshot_corpus import main as assemble_main
from scripts.ops.legal_data.build_state_laws_snapshot_sparse_graphrag import (
    main as build_main,
    run_snapshot_build,
)
from scripts.ops.legal_data.inventory_state_laws_snapshot_graphrag_inputs import (
    main as inventory_main,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _normalized(code: str, section: str, text: str) -> dict:
    return {
        "state_code": code,
        "title_number": "1",
        "chapter_number": "1",
        "section_number": section,
        "section_name": f"Section {section}",
        "full_text": text,
        "source_url": f"https://example.invalid/{code.lower()}/{section}",
        "metadata": {"repealed": False},
        "structured_data": {"status": "in_force"},
    }


def test_inventory_lists_all_51_and_binds_remaining_seven(tmp_path: Path) -> None:
    tmp_laws = tmp_path / "tmp_laws"
    tmp_laws.mkdir()
    vaquill = tmp_path / "vaquill"
    jsonld = tmp_path / "jsonld"
    jsonld.mkdir()
    (tmp_laws / "Arkansas_Law_v2026-08.cleaned.jsonl.gz").write_bytes(b"ar-dump")
    _write_jsonl(
        vaquill / "AR" / "statutes.jsonl",
        [_normalized("AR", "1-1-1", "Arkansas text shall be indexed.")],
    )
    for code in EXACT_51_JURISDICTION_CODES:
        if code == "AR":
            continue
        if code in REMAINING_TMP_LAWS_STATES:
            _write_jsonl(
                vaquill / code / "statutes.jsonl",
                [_normalized(code, "1-1-1", f"{code} dump text shall be indexed.")],
            )
            continue
        payload = {
            "stateCode": code,
            "sectionNumber": "1",
            "text": f"{code} local jsonld shall be indexed as research text.",
        }
        # Usable JSON-LD: over stub byte floor and 200 records.
        lines = [json.dumps({**payload, "sectionNumber": str(i)}) for i in range(220)]
        (jsonld / f"STATE-{code}.jsonld").write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = inventory_all(tmp_laws=tmp_laws, vaquill_root=vaquill, jsonld_root=jsonld)
    assert report["authorizing_for_publication"] is False
    assert report["current_bundle"] is False
    assert report["satisfies_exact_51_gate"] is False
    assert report["jurisdiction_count"] == 51
    by_code = {row["jurisdiction_code"]: row for row in report["states"]}
    for code in REMAINING_TMP_LAWS_STATES:
        assert by_code[code]["chosen_source"] == "tmp_laws"
        assert by_code[code]["source_kind"] == "vaquill_jsonl"
    assert by_code["DC"]["chosen_source"] == "lcr_jsonld"
    assert report["remaining_seven_all_tmp_laws"] is True
    assert report["all_51_have_source"] is True


def test_inventory_refuses_jsonld_as_chosen_source_for_georgia(tmp_path: Path) -> None:
    jsonld = tmp_path / "jsonld"
    jsonld.mkdir()
    (jsonld / "STATE-GA.jsonld").write_text(
        json.dumps({"stateCode": "GA", "sectionNumber": "1", "text": "stub"}) + "\n",
        encoding="utf-8",
    )
    vaquill = tmp_path / "vaquill"
    _write_jsonl(
        vaquill / "GA" / "statutes.jsonl",
        [_normalized("GA", "1-1-1", "Georgia dump from tmp_laws shall be used.")],
    )
    row = inventory_jurisdiction(
        "GA",
        tmp_laws=tmp_path / "missing-dumps",
        vaquill_root=vaquill,
        jsonld_root=jsonld,
        ingest_manifest={},
    )
    assert row["chosen_source"] == "tmp_laws"
    assert "STATE-GA.jsonld" not in (row.get("source_path") or "")


def test_map_jsonld_refuses_remaining_states() -> None:
    with pytest.raises(SnapshotGraphragError, match="REFUSING JSON-LD for remaining-state GA"):
        map_jsonld_to_oul_row(
            {"stateCode": "GA", "sectionNumber": "1", "text": "should not map"}
        )


def test_hierarchy_tokens_strip_semicolons_for_legal_id() -> None:
    row = map_jsonld_to_oul_row(
        {
            "stateCode": "AL",
            "chapterNumber": "Salaries; Officers Generally",
            "sectionNumber": "36-6-1",
            "text": "Officers of the state shall receive the salaries provided by law.",
        }
    )
    assert row is not None
    assert ":" not in (row["hierarchy"]["chapter"] or "")
    assert ";" not in (row["hierarchy"]["chapter"] or "")
    assert row["hierarchy"]["chapter"] == "salaries-officers-generally"
    assert row["hierarchy"]["section"] == "36-6-1"


def test_map_normalized_statute_to_oul_row() -> None:
    row = map_normalized_statute_to_oul_row(
        _normalized("NY", "5-101", "New York dump text shall be indexed.")
    )
    assert row is not None
    assert row["jurisdiction_code"] == "NY"
    assert row["hierarchy"]["section"] == "5-101"
    assert row["snapshot_source_kind"] == "tmp_laws"
    assert row["text"].startswith("New York")


def test_snapshot_hub_publish_refuses_official_current_bundle(tmp_path: Path) -> None:
    with pytest.raises(SnapshotGraphragError, match="official current-bundle"):
        refuse_official_current_bundle_repo("justicedao/ipfs_state_laws")
    assert refuse_official_current_bundle_repo(DEFAULT_SNAPSHOT_HUB_REPO_ID) == (
        DEFAULT_SNAPSHOT_HUB_REPO_ID
    )
    release = tmp_path / "hf-release"
    release.mkdir()
    (release / "manifest.json").write_text("{}\n", encoding="utf-8")
    dry = publish_snapshot_research_hf(release, dry_run=True)
    assert dry["status"] == "dry_run"
    assert dry["current_bundle"] is False
    assert dry["authorizing_for_publication"] is False
    with pytest.raises(SnapshotGraphragError, match="official current-bundle"):
        publish_snapshot_research_hf(
            release, repo_id="justicedao/ipfs_federal_register", dry_run=True
        )


def test_refuse_authorizing_and_live_dest(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="REFUSING Hub authorization"):
        refuse_authorizing_for_publication(True)
    with pytest.raises(SnapshotGraphragError, match="live acquisition"):
        refuse_live_dest(tmp_path / "legal-corpora-reindex-20260831-ny-live-v12-evidence")
    with pytest.raises(SnapshotGraphragError, match="live acquisition"):
        refuse_live_dest(tmp_path / "acquisition-evidence" / "NY")


def test_assembler_uses_tmp_laws_for_remaining_and_refuses_existing_dest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vaquill = tmp_path / "vaquill"
    _write_jsonl(
        vaquill / "AR" / "statutes.jsonl",
        [_normalized("AR", "10-2-101", "The General Assembly shall meet in regular session.")],
    )
    inventory_row = {
        "jurisdiction_code": "AR",
        "chosen_source": "tmp_laws",
        "source_kind": "vaquill_jsonl",
        "source_path": str(vaquill / "AR" / "statutes.jsonl"),
        "source_sha256": "abc",
        "dump_sha256": "def",
    }
    dest = tmp_path / "corpus"
    receipt = assemble_jurisdiction(inventory_row, dest_root=dest)
    assert receipt["authorizing_for_publication"] is False
    assert receipt["row_count"] == 1
    assert (dest / "AR" / "rows.jsonl").is_file()

    with pytest.raises(SnapshotGraphragError, match="remaining states must use"):
        assemble_jurisdiction(
            {
                "jurisdiction_code": "GA",
                "chosen_source": "lcr_jsonld",
                "source_kind": "lcr_jsonld",
                "source_path": str(tmp_path / "STATE-GA.jsonld"),
            },
            dest_root=dest,
        )

    monkeypatch.setattr(
        "sys.argv",
        ["assemble_state_laws_snapshot_corpus.py", "--authorizing-for-publication"],
    )
    with pytest.raises(SystemExit, match="REFUSING Hub authorization"):
        assemble_main()


def test_inventory_main_refuses_authorizing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["inventory_state_laws_snapshot_graphrag_inputs.py", "--authorizing-for-publication"],
    )
    with pytest.raises(SystemExit, match="REFUSING Hub authorization"):
        inventory_main()


def test_snapshot_builder_tiny_fixture_does_not_authorize(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    for code, section, text in (
        ("AR", "10-2-101", "The General Assembly of Arkansas shall meet in regular session."),
        ("DC", "2-531", "A public body of the District of Columbia shall disclose public records."),
    ):
        row = map_normalized_statute_to_oul_row(_normalized(code, section, text))
        assert row is not None
        _write_jsonl(corpus / code / "rows.jsonl", [row])

    receipt = run_snapshot_build(
        corpus_root=corpus,
        output_dir=tmp_path / "release",
        codes=["AR", "DC"],
        prefer_real_embeddings=False,
    )
    assert receipt["authorizing_for_publication"] is False
    assert receipt["authorizing_hub_upload"] is False
    assert receipt["current_bundle"] is False
    assert receipt["satisfies_exact_51_gate"] is False
    assert receipt["exact_51_gate_used_as_publication_authority"] is False
    assert receipt["admitted_section_count"] >= 2
    assert receipt["mode"] == "snapshot_research"
    assert not str(receipt.get("hf_manifest") or "").startswith("packager_skipped")
    assert (tmp_path / "release" / "snapshot_build_receipt.json").is_file()
    assert (tmp_path / "release" / "hf-release" / "manifest.json").is_file()
    assert receipt["skillcenter_layout"]["default_config"] == "corpus"
    assert receipt["skillcenter_layout"]["viewer_safe_default_exact_51"] is False
    assert (tmp_path / "release" / "hf-release" / "scripts" / "query_open_us_law_hf.py").is_file()
    configs = json.loads(
        (tmp_path / "release" / "hf-release" / "dataset_configs.json").read_text(
            encoding="utf-8"
        )
    )
    names = [item["config_name"] for item in configs["configs"]]
    assert names[0] == "corpus"
    assert "state_statutes_exact_51" not in names
    assert "bm25_documents" in names
    assert "vector_meta_index" in names
    assert receipt["embedding_checkpoint_format"] == "parquet_parts"
    parquet_dir = tmp_path / "release" / "checkpoints" / "embeddings"
    assert (parquet_dir / "manifest.json").is_file()
    assert (parquet_dir / "part-000000.parquet").is_file()
    assert not (tmp_path / "release" / "checkpoints" / "embeddings_checkpoint.json").exists()


def test_snapshot_builder_resumes_complete_parquet_without_reembed(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "corpus"
    for code, section, text in (
        ("AR", "10-2-101", "The General Assembly of Arkansas shall meet in regular session."),
        ("DC", "2-531", "A public body of the District of Columbia shall disclose public records."),
    ):
        row = map_normalized_statute_to_oul_row(_normalized(code, section, text))
        assert row is not None
        _write_jsonl(corpus / code / "rows.jsonl", [row])
    dest = tmp_path / "release"
    first = run_snapshot_build(
        corpus_root=corpus,
        output_dir=dest,
        codes=["AR", "DC"],
        prefer_real_embeddings=False,
    )
    part0 = dest / "checkpoints" / "embeddings" / "part-000000.parquet"
    first_mtime = part0.stat().st_mtime_ns
    second = run_snapshot_build(
        corpus_root=corpus,
        output_dir=dest,
        codes=["AR", "DC"],
        prefer_real_embeddings=False,
    )
    assert part0.stat().st_mtime_ns == first_mtime
    assert second["admitted_chunk_count"] == first["admitted_chunk_count"]
    assert second["authorizing_for_publication"] is False
    assert (dest / "hf-release" / "manifest.json").is_file()
    assert (dest / "checkpoints" / "corpus" / "identity.json").is_file()
    assert (dest / "checkpoints" / "graph" / "identity.json").is_file()
    bm25_parts = sorted((dest / "bm25-work" / "postings" / "postings.sorted.parquet").glob("part-*.parquet"))
    assert bm25_parts
    bm25_mtime = [part.stat().st_mtime_ns for part in bm25_parts]
    third = run_snapshot_build(
        corpus_root=corpus,
        output_dir=dest,
        codes=["AR", "DC"],
        prefer_real_embeddings=False,
    )
    reused = sorted((dest / "bm25-work" / "postings" / "postings.sorted.parquet").glob("part-*.parquet"))
    assert [part.stat().st_mtime_ns for part in reused] == bm25_mtime
    assert third["bm25_index_root_cid"] == second["bm25_index_root_cid"]
    assert third["graph_cid"] == second["graph_cid"]


def test_skillcenter_layout_overlay_does_not_advertise_exact_51(tmp_path: Path) -> None:
    release = tmp_path / "hf-release"
    release.mkdir()
    (release / "README.md").write_text(
        "---\nconfig_name: state_statutes_exact_51\n---\nold body\n",
        encoding="utf-8",
    )
    query = tmp_path / "query_open_us_law_hf.py"
    query.write_text("print('query')\n", encoding="utf-8")
    overlay = apply_skillcenter_snapshot_release(release, query_script=query)
    assert overlay["default_config"] == "corpus"
    assert overlay["viewer_safe_default_exact_51"] is False
    assert overlay["authorizing_for_publication"] is False
    configs = json.loads((release / "dataset_configs.json").read_text(encoding="utf-8"))
    assert configs["default_config"] == "corpus"
    readme = (release / "README.md").read_text(encoding="utf-8")
    assert "state_statutes_exact_51" not in readme.split("---", 2)[1]
    assert "Publicus/skillcenter-ir" in readme
    assert (release / "scripts" / "query_open_us_law_hf.py").is_file()


def test_build_main_refuses_authorizing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["build_state_laws_snapshot_sparse_graphrag.py", "--authorizing-for-publication"],
    )
    with pytest.raises(SystemExit, match="REFUSING Hub authorization"):
        build_main()
