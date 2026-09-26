"""The model proposes normalizer rules. The script, not the model, rewrites rows."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from country_laws_ir.normalize_loop import (
    _patterns_from_model_text,
    _scan_job,
    accept_line_patterns,
    apply_done,
    apply_pack,
    improve_from_reports,
    propose_line_patterns,
    router_candidates,
    run_parallel,
    scan_done,
    scan_pack,
)
from country_laws_ir.structure import normalize_legal_text


def _write_pack(directory: Path, slug: str, bodies: list[str]) -> Path:
    path = directory / f"{slug}_corpus.parquet"
    pq.write_table(
        pa.table({"body": pa.array(bodies), "language": pa.array(["en"] * len(bodies))}),
        path,
    )
    return path


def test_scan_counts_rows_and_repeated_short_lines(tmp_path: Path):
    legal = "Article 1 The present Act applies throughout the territory and binds every person."
    path = _write_pack(
        tmp_path,
        "malta",
        [f"Translated copy for the office shelf\nArticle 6:\n{legal}"] * 3,
    )
    stats = scan_pack(path)
    assert stats["n"] == 3
    assert stats["n_unstable"] == 0
    assert any(item["line"] == "Translated copy for the office shelf" for item in stats["leftovers"])
    assert all(not item["line"].startswith("Article ") for item in stats["leftovers"])


def test_accept_line_patterns_rejects_a_rule_that_deletes_a_provision():
    keep = "Article 1 The present Act applies throughout the territory and binds every person."
    accepted = accept_line_patterns(
        [r"^Desk copy \d+$", f"^{keep}$"],
        ["Desk copy 9", keep],
    )
    assert accepted == [r"^Desk copy \d+$"]


def test_learned_pattern_is_applied_by_the_row_script(tmp_path: Path, monkeypatch):
    pattern_file = tmp_path / "learned.json"
    pattern_file.write_text(json.dumps({"patterns": []}), encoding="utf-8")
    monkeypatch.setenv("COUNTRY_LAWS_LEARNED_PATTERNS", str(pattern_file))
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "malta.json").write_text(
        json.dumps({"leftovers": [{"line": "Desk copy 9", "count": 12}]}),
        encoding="utf-8",
    )
    calls: list[str] = []

    def generate_text(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(
            {
                "line_patterns": [
                    r"^Desk copy \d+$",
                    "The minister shall grant a pardon that was not in the source.",
                ]
            }
        )

    result = improve_from_reports(reports, generate_text)
    assert calls and "Do not write legal text." in calls[0]
    assert result["accepted"] == [r"^Desk copy \d+$"]
    text = normalize_legal_text(
        "Desk copy 9\n"
        "Article 1 The present Act applies throughout the territory and binds every person."
    )
    assert "Desk copy" not in text
    assert "present Act applies" in text


def test_apply_rewrites_rows_without_calling_a_model(tmp_path: Path):
    legal = "Article 1 The present Act applies throughout the territory and binds every person."
    path = _write_pack(tmp_path, "fiji", [f"Page | 3\n{legal}"])
    out = tmp_path / "out" / "fiji_corpus.parquet"
    stats = apply_pack(path, out)
    written = pq.read_table(out).column("body")[0].as_py()
    assert stats["n"] == 1
    assert stats["n_changed"] == 1
    assert written == normalize_legal_text(f"Page | 3\n{legal}")
    assert "Page | 3" not in written
    assert legal in written


def test_scan_jobs_run_in_parallel(tmp_path: Path):
    legal = "Article 1 The present Act applies throughout the territory and binds every person."
    stamp = "Serial Number: 1005 16/12/2009\n" + legal
    malta = _write_pack(tmp_path, "malta", [stamp, stamp, stamp])
    fiji = _write_pack(tmp_path, "fiji", [stamp, stamp, stamp])
    reports = tmp_path / "reports"
    rows = run_parallel(
        [("fiji", str(fiji), str(reports)), ("malta", str(malta), str(reports))],
        _scan_job,
        workers=2,
    )
    assert [row["slug"] for row in rows] == ["fiji", "malta"]
    assert all(row["n"] == 3 and not row.get("error") for row in rows)
    assert (reports / "fiji.json").is_file()
    assert (reports / "malta.json").is_file()


def test_resume_skips_a_finished_scan_and_records_progress(tmp_path: Path):
    legal = "Article 1 The present Act applies throughout the territory and binds every person."
    stamp = "Serial Number: 1005 16/12/2009\n" + legal
    malta = _write_pack(tmp_path, "malta", [stamp, stamp, stamp])
    fiji = _write_pack(tmp_path, "fiji", [stamp, stamp, stamp])
    reports = tmp_path / "reports"
    progress = tmp_path / "progress.jsonl"
    jobs = [("fiji", str(fiji), str(reports)), ("malta", str(malta), str(reports))]
    run_parallel(jobs, _scan_job, workers=2, progress_path=progress)
    assert scan_done(reports, "fiji") and scan_done(reports, "malta")
    again = run_parallel([jobs[0]], _scan_job, workers=1, progress_path=progress)
    assert again[0]["slug"] == "fiji"
    lines = [json.loads(line) for line in progress.read_text(encoding="utf-8").splitlines()]
    assert {line["slug"] for line in lines[:2]} == {"fiji", "malta"}
    assert lines[2]["slug"] == "fiji"
    broken = reports / "malta.json"
    broken.write_text("{", encoding="utf-8")
    assert not scan_done(reports, "malta")
    partial = tmp_path / "out" / "fiji_corpus.parquet"
    partial.parent.mkdir()
    partial.write_bytes(b"PAR1not-closed")
    assert not apply_done(partial.parent, "fiji")


def test_repeated_gazette_banners_drop_and_publication_sentences_stay():
    text = normalize_legal_text(
        "geral@sme.ao www.sme.ao\n"
        "II SÉRIE - NÚMERO 01 Quinta-Feira, 16 deNovembro de 2017\n"
        "I-SÉRIE - NÚMERO 13\n"
        "I SÉRIE - nr. 139 - DE 22 DE JULHO DE 2011 3651\n"
        "Page 3/4\n"
        "[ Printed by Authority of the\n"
        "Printed in Belize by the Government Printer\n"
        "Secrétariat Général du Gouvernement www.joradp.dz\n"
        "Site: www.portodecabinda.co.ao\n"
        "Justice Sector Support Program (JSSP) - Translated May 6,\n"
        "Serial Number: 1005 16/12/2009\n"
        "Copyright Government of Botswana\n"
        "Ministry/Program/Subprogram Page\n"
        "This page was intentionally left blank.\n"
        "Official Gazette nr. Special of 25/10/2024\n"
        "Official Gazette nr. 21bis of 25/05/2015\n"
        "This is page 1 of 1 Page of the above Table.\n"
        "New provisions are printed in italics.\n"
        "Parliamentary Series nr. 116\n"
        "LEXIS FINDER - www.lexis.com.ec\n"
        "www.slvesnik.com.mk contact@slvesnik.com.mk\n"
        "Try reloading the page or downloading the PDF.\n"
        "published in the Gazette.\n"
        "Série I, nr. 22B\n"
        "Journal Officiel de la Republique du Tchad Juillet 2022\n"
        "Journal officiel du Faso.\n"
        "Journal Officiel - Banque de Données Juridiques - 2015\n"
        "(809) 533-3522 | www.pgr.gob.do\n"
        "Volume: 52 Issue No: 231 Government Gazette\n"
        "TONGA GOVERNMENT GAZETTE SUPPLEMENT\n"
        "MINISTRY OF LEGAL AFFAIRS www.legalaffairs.gov.tt\n"
        "4 www.lawcommission.gov.np\n"
        "www.cnlegis.gov.mg 3/3\n"
        "www.diputados.bo LA PAZ - BOLIVIA\n"
        ">>>/Rotate 0/StructParents 0/Tabs/S/Type/Page>>\n"
        "Subject. Reference. Page.\n"
        "Unofficial translated\n"
        "De Blank Page (blanco pagina) instellingen zijn minimaal:\n"
        "E-mail : douane@douane.gov.km - Site web: www.douane.gov.km\n"
        "www.example.com is the official register under this Act.\n"
        "Série I, nr. 48 B\n"
        "2017 Parliamentary Series No.320\n"
        "Copyright\n"
        "COPYRIGHT AND DESIGNS ACT 2004\n"
        "Copyright Act 1968\n"
        "Powered by TCPDF (www.tcpdf.org)\n"
        "[The inclusion of this page is authorised by S.I. 14/1959]\n"
        "ins = inserted SIG = Solomon Islands Gazette\n"
        "gaz = gazette\n"
        "Site web : www.iort.gov.tn\n"
        "Web Sites : www.documents.gov.lk\n"
        "Pour l'acquisition de votre abonnement au Journal Officiel :\n"
        "Edité par la Direction de l'Edition du Journal Officiel\n"
        "Lycée : séries ES, L et S\n"
        "publié au Journal Officiel de la République Tunisienne.\n"
        "enregistré et publié au Journal officiel."
        "na II Série do Diário da República.\n"
        "no Diário da República nr. 154, de 16 de Agosto, I Série.\n"
        "Article 1 The present Act applies throughout the territory and binds every person."
    )
    for gone in (
        "sme.ao",
        "deNovembro",
        "NÚMERO 13",
        "JULHO DE 2011",
        "Page 3/4",
        "Printed by Authority",
        "Government Printer",
        "joradp",
        "portodecabinda",
        "JSSP",
        "Serial Number",
        "Government of Botswana",
        "Subprogram Page",
        "intentionally left blank",
        "Official Gazette",
        "above Table",
        "printed in italics",
        "Parliamentary Series",
        "lexis.com.ec",
        "slvesnik",
        "reloading the page",
        "nr. 22B",
        "du Tchad",
        "du Faso",
        "Banque de Données",
        "pgr.gob.do",
        "Issue No",
        "GAZETTE SUPPLEMENT",
        "legalaffairs",
        "lawcommission",
        "cnlegis",
        "diputados",
        "/Type/Page",
        "Reference. Page",
        "Unofficial translated",
        "Blank Page",
        "douane.gov.km",
        "nr. 48 B",
        "Parliamentary Series",
        "DESIGNS ACT",
        "Copyright Act 1968",
        "TCPDF",
        "inclusion of this page",
        "Solomon Islands Gazette",
        "gaz = gazette",
        "iort.gov.tn",
        "documents.gov.lk",
        "abonnement",
        "Direction de l'Edition",
    ):
        assert gone not in text, gone
    assert "published in the Gazette." in text
    assert "www.example.com is the official register" in text
    assert "Lycée : séries ES, L et S" in text
    assert "publié au Journal Officiel de la République Tunisienne." in text
    assert "enregistré et publié au Journal officiel." in text
    assert not any(line.strip() == "Copyright" for line in text.splitlines())
    assert "na II Série do Diário da República." in text
    assert "I Série." in text
    assert "present Act applies" in text


def test_router_skips_lines_the_script_already_drops_and_publication_sentences():
    chosen = router_candidates(
        [
            {"line": "Page | 3", "count": 90},
            {"line": "published in the Gazette.", "count": 80},
            {"line": "Desk copy 9", "count": 4},
            {"line": "series,", "count": 70},
        ]
    )
    assert [item["line"] for item in chosen] == ["Desk copy 9"]


def test_model_text_without_json_still_yields_a_whole_line_pattern():
    raw = "a heading pattern:\n^Printed by the Government Printer\\.$\n"
    assert _patterns_from_model_text(raw) == [r"^Printed by the Government Printer\.$"]
    assert _patterns_from_model_text('{"line_patterns": ["^Page \\\\d+$"]}') == [r"^Page \d+$"]
    assert "^...$" not in _patterns_from_model_text("example ^...$ only")


def test_prompt_stays_inside_the_local_model_budget():
    captured: list[str] = []

    def generate_text(prompt: str) -> str:
        captured.append(prompt)
        return '{"line_patterns": []}'

    propose_line_patterns(
        [{"count": 3, "line": "X" * 400} for _ in range(10)],
        generate_text,
        char_budget=1600,
    )
    assert captured
    assert len(captured[0]) <= 1600
    assert "Do not write legal text." in captured[0]


def test_improve_walks_families_and_rejects_a_rule_that_hits_a_publication(tmp_path: Path, monkeypatch):
    pattern_file = tmp_path / "learned.json"
    pattern_file.write_text(json.dumps({"patterns": []}), encoding="utf-8")
    monkeypatch.setenv("COUNTRY_LAWS_LEARNED_PATTERNS", str(pattern_file))
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "malta.json").write_text(
        json.dumps(
            {
                "leftovers": [
                    {"line": "Printer stamp 4", "count": 50},
                    {"line": "Printer stamp 8", "count": 20},
                    {"line": "Desk copy 9", "count": 4},
                    {"line": "published in the Gazette.", "count": 500},
                ]
            }
        ),
        encoding="utf-8",
    )
    prompts: list[str] = []

    def generate_text(prompt: str) -> str:
        prompts.append(prompt)
        if "Printer stamp" in prompt:
            return '{"line_patterns": []}'
        return json.dumps(
            {
                "line_patterns": [
                    r"^.*Gazette.*$",
                    r"^Desk copy \d+$",
                ]
            }
        )

    result = improve_from_reports(reports, generate_text, max_passes=4)
    assert len(prompts) == 2
    assert all("published in the Gazette." not in prompt for prompt in prompts)
    assert "Printer stamp 4" in prompts[0]
    assert "Printer stamp 8" in prompts[0]
    assert "Desk copy 9" not in prompts[0]
    assert result["accepted"] == [r"^Desk copy \d+$"]
    assert result["unresolved"] == 2
    assert result["remaining"] == 0
    text = normalize_legal_text(
        "Desk copy 9\n"
        "published in the Gazette.\n"
        "Article 1 The present Act applies throughout the territory and binds every person."
    )
    assert "Desk copy" not in text
    assert "published in the Gazette." in text


def test_hyphen_join_stays_stable_after_a_chrome_line_drops():
    text = "appli-\n1|Page\ncable rule applies throughout the territory."
    once = normalize_legal_text(text)
    assert once == normalize_legal_text(once)
    assert "applicable rule" in once
    header = 'nota del Minis-\nISMAEL HERRAIZ\nterio de Relaciones.'
    once = normalize_legal_text(header)
    assert once == normalize_legal_text(once)
    assert "MinisISMAEL" not in once
    assert "ISMAEL HERRAIZ" in once
    assert "Comisión" in normalize_legal_text("adscripto a la Co-\nmisión Nacional de obras.")
