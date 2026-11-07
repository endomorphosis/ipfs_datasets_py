"""Country-source rows fill a national gap only when they stay queryable laws."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.admit import (
    admit_source_law,
    fill_country_corpus,
    fill_country_parquet,
    fill_source_rows,
    municipal_issuer_law_ids,
    national_gap_plan,
)
from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
    normalize_legal_text,
)

_SHA = "b" * 40
_ACT = (
    "Article 1 This Act applies throughout the territory.\n"
    "Article 2 The minister shall keep the register.\n"
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "fr-1",
        "title": "Loi exemple",
        "text": _ACT,
        "source_url": "https://example.test/fr/loi",
        "language": "fr",
        "jurisdiction": "FR",
        "country": "France",
        "metadata_json": "{}",
    }
    row.update(overrides)
    return row


def test_a_statute_from_a_country_dataset_fills_queryable_atoms() -> None:
    decision = admit_source_law(
        _row(),
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert decision.reason == "law"
    assert len(decision.records) == 2
    assert decision.records[0]["text"].startswith("Article 1")
    assert decision.records[0]["provenance"]["article"] == "1"
    assert decision.records[1]["provenance"]["article"] == "2"
    assert "Article 2" in decision.records[1]["provenance"]["hierarchy_path"]
    assert decision.records[0]["jurisdiction"] == "FR"
    assert decision.records[0]["source_repo"] == "endomorphosis/ipfs_france_laws"
    assert "<" not in str(decision.records[0]["text"])


def test_unrelated_source_rows_are_refused_without_text() -> None:
    cases = {
        "informative": _row(
            title="Search",
            text="Home\nSearch\nContact us\nThis website uses cookies\n",
            source_url="https://example.test/search",
        ),
        "metadata": _row(
            title="Reife- und Diplomprüfung sowie Diplomprüfung in der Bildungsanstalt",
            text="Reife- und Diplomprüfung sowie Diplomprüfung in der Bildungsanstalt",
            jurisdiction="AT",
            language="de",
        ),
        "notice": _row(
            title="Newsletter mbi ceshtjet europiane",
            text="This newsletter tells readers what the assembly discussed this week.",
            metadata_json='{"document_type": "newsletter"}',
        ),
        "not_queryable": _row(title="Code civil", text="Les lois"),
        "empty": _row(text="The incident id is 42"),
        "unofficial": _row(source_official=False),
    }
    for reason, row in cases.items():
        decision = admit_source_law(
            row,
            source_dataset="endomorphosis/ipfs_france_laws",
            source_revision=_SHA,
        )
        assert decision.admitted is False
        assert decision.reason == reason
        assert decision.records == ()


def test_an_operative_provision_and_a_numbered_article_body_are_queryable() -> None:
    provision = admit_source_law(
        _row(
            text="The court shall apply this Act throughout the territory and bind every person.",
        ),
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert provision.admitted is True
    assert provision.records[0]["text"].startswith("The court shall apply")
    numbered = admit_source_law(
        _row(
            id="art-1103",
            article_number="1103",
            title="Article 1103",
            text="Les contrats légalement formés tiennent lieu de loi à ceux qui les ont faits.",
        ),
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert numbered.admitted is True
    assert numbered.records[0]["provenance"]["statute"] == "1103"
    assert "contrats" in str(numbered.records[0]["text"])


def test_a_country_name_uses_the_code_and_a_canton_stays_subnational() -> None:
    bosnia = admit_source_law(
        _row(
            id="ba-1",
            jurisdiction="Bosnia and Herzegovina",
            country="ba",
            language="bs",
            title="Zakon o primjeru",
        ),
        source_dataset="endomorphosis/ipfs_bosnia_laws",
        source_revision=_SHA,
    )
    assert bosnia.admitted is True
    assert bosnia.records[0]["jurisdiction"] == "BA"
    assert bosnia.records[0]["text"].startswith("Article 1")
    salvador = admit_source_law(
        _row(
            jurisdiction="El Salvador",
            country="sv",
            language="es",
            title="Ley de ejemplo",
        ),
        source_dataset="endomorphosis/ipfs_el_salvador_laws",
        source_revision=_SHA,
    )
    assert salvador.admitted is True
    assert salvador.records[0]["jurisdiction"] == "SV"
    canton = admit_source_law(
        _row(jurisdiction="CH-BE", country="Switzerland"),
        source_dataset="endomorphosis/ipfs_switzerland_laws",
        source_revision=_SHA,
    )
    assert canton.admitted is False
    assert canton.reason == "not_national"
    assert canton.records == ()


def test_eu_law_keeps_its_jurisdiction_and_a_subdivision_is_refused() -> None:
    decision = admit_source_law(
        _row(
            id="eu-1",
            jurisdiction="EU",
            country="European Union",
            language="en",
            title="Regulation (EU) 2016/679",
        ),
        source_dataset="endomorphosis/ipfs_eu_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert decision.reason == "law"
    assert decision.records[0]["jurisdiction"] == "EU"
    assert decision.records[0]["text"].startswith("Article 1")
    for code, dataset in (
        ("CH-BE", "endomorphosis/ipfs_switzerland_laws"),
        ("ES-CN", "endomorphosis/ipfs_spain_laws"),
        ("DE-NW", "endomorphosis/ipfs_germany_laws"),
    ):
        refused = admit_source_law(
            _row(jurisdiction=code, country=""),
            source_dataset=dataset,
            source_revision=_SHA,
        )
        assert refused.admitted is False
        assert refused.reason == "not_national"
        assert refused.records == ()


def test_an_eu_fill_records_the_supranational_level(tmp_path: Path) -> None:
    source = tmp_path / "eu" / "part-000000.parquet"
    source.parent.mkdir(parents=True)
    _write_source(
        source,
        ["eu-1"],
        ["Regulation (EU) 2016/679"],
        [_ACT],
        ["en"],
        ["EU"],
    )
    report = fill_country_parquet(
        source,
        tmp_path / "out",
        source_dataset="endomorphosis/ipfs_eu_laws",
        source_revision=_SHA,
    )
    assert report["atoms_written"] == 2
    table = pq.read_table(tmp_path / "out" / "eu" / "part-000000.parquet")
    assert table.column("jurisdiction").to_pylist() == ["EU", "EU"]
    assert table.column("admin_level").to_pylist() == ["supranational", "supranational"]
    assert table.column("text").to_pylist()[0].startswith("Article 1")
    provenance = json.loads(table.column("provenance").to_pylist()[0])
    assert provenance["jsonld"]["legislationJurisdiction"] == "EU"
    assert provenance["jsonld"]["text"].startswith("Article 1")


def test_excluded_and_municipal_sources_do_not_fill_the_national_card() -> None:
    statute = _row(
        jurisdiction="BE",
        country="Belgium",
        text=_ACT,
    )
    excluded = admit_source_law(
        statute,
        source_dataset="endomorphosis/ipfs_belgium_laws",
        source_revision=_SHA,
    )
    municipal = admit_source_law(
        _row(),
        source_dataset="endomorphosis/ipfs_france_municipal_laws",
        source_revision=_SHA,
    )
    assert excluded.reason == "excluded"
    assert excluded.records == ()
    assert municipal.reason == "not_national"
    assert municipal.records == ()


def test_a_named_municipality_does_not_fill_the_national_card() -> None:
    municipal_text = (
        "1. člen Prihodki občinskega proračuna za leto 1993 znašajo: "
        "SIT skupni prihodki 276,023.000."
    )
    municipal = admit_source_law(
        _row(
            id="si-metlika-1",
            title="1. člen",
            language="sl",
            jurisdiction="SI",
            country="Slovenia",
            official_citation=(
                "glasilo-uradni-list-rs/vsebina/1993-01-0716/"
                "odlok-o-proracunu-obcine-metlika-za-leto"
            ),
            text=municipal_text,
        ),
        source_dataset="endomorphosis/ipfs_slovenia_laws",
        source_revision=_SHA,
    )
    spelled = admit_source_law(
        _row(
            id="si-metlika-2",
            title="1. člen",
            language="sl",
            jurisdiction="SI",
            country="Slovenia",
            source_url="",
            instrument_title="Odlok o proračunu občine Metlika",
            text=municipal_text,
        ),
        source_dataset="endomorphosis/ipfs_slovenia_laws",
        source_revision=_SHA,
    )
    assert municipal.reason == "not_national"
    assert municipal.records == ()
    assert spelled.reason == "not_national"
    assert spelled.records == ()

    national_text = (
        "16. člen Pri zastopanju strank lahko odvetnika nadomešča "
        "odvetnik iz iste odvetniške pisarne."
    )
    kept_citations = (
        "glasilo-uradni-list-rs/vsebina/1993-01-0817/zakon-o-odvetnistvu",
        "zakon-o-referendumu-za-ustanovitev-obcin",
        "zakon-o-razpisu-rednih-lokalnih-volitev-v-mestni-obcini-koper",
        "uredba-o-metodologiji-za-izracun-povprecnine-za-financiranje-obcinskih-nalog",
        "pravilnik-o-postopkih-zadolzevanja-obcin",
        "odlok-o-razglasitvi-ustavnega-amandmaja-k-ustavi-republike-slovenije",
    )
    for citation in kept_citations:
        decision = admit_source_law(
            _row(
                id="si-national",
                title="16. člen",
                language="sl",
                jurisdiction="SI",
                country="Slovenia",
                official_citation=citation,
                text=national_text,
            ),
            source_dataset="endomorphosis/ipfs_slovenia_laws",
            source_revision=_SHA,
        )
        assert decision.admitted is True, citation
        assert decision.records[0]["text"].startswith("16. člen Pri zastopanju")
        assert decision.records[0]["provenance"]["article"] == "16"
        assert decision.records[0]["jurisdiction"] == "SI"

    shelter = (
        "3. člen\n"
        "V neposredni vojni nevarnosti, se gradijo zaklonišča dopolnilne zaščite, "
        "kot so zaklonilniki."
    )
    numbered = admit_source_law(
        _row(
            id="si-shelter-3",
            title="3. člen",
            language="sl",
            jurisdiction="SI",
            country="Slovenia",
            official_citation="zakon-o-odvetnistvu",
            text=shelter,
        ),
        source_dataset="endomorphosis/ipfs_slovenia_laws",
        source_revision=_SHA,
    )
    assert numbered.admitted is True
    assert numbered.records[0]["provenance"]["article"] == "3"
    assert numbered.records[0]["text"].startswith("3. člen\nV neposredni")

    named_issuer = (
        "1. člen Skupščina občine Kočevje ustanavlja s tem odlokom javni zavod "
        "in določa njegov sedež v Kočevju."
    )
    budget = (
        "2. člen Postavke v bilanci prihodkov in odhodkov proračuna "
        "Občine Ravne-Prevalje za leto 1997 se spremenijo."
    )
    for citation, text in (
        ("odlok-o-ustanovitvi-gimnazije-kocevje", named_issuer),
        ("0207", budget),
        (
            "pravilnik-o-dolocanju-najemnin",
            "8. člen Izvršni svet Skupščine občine Ljubljana Center lahko "
            "najemniku za določen čas zniža najemnino.",
        ),
    ):
        refused = admit_source_law(
            _row(
                id="si-local",
                title="1. člen",
                language="sl",
                jurisdiction="SI",
                country="Slovenia",
                official_citation=citation,
                text=text,
            ),
            source_dataset="endomorphosis/ipfs_slovenia_laws",
            source_revision=_SHA,
        )
        assert refused.reason == "not_national", citation
        assert refused.records == ()

    aliens = (
        "3. člen Tujec sme vstopiti v državo na za to določenih mejnih prehodih. "
        "Skupščina občine Koper pri tem nima pristojnosti."
    )
    kept_alien = admit_source_law(
        _row(
            id="si-aliens",
            title="3. člen",
            language="sl",
            jurisdiction="SI",
            country="Slovenia",
            official_citation="zakon-o-tujcih",
            text=aliens,
        ),
        source_dataset="endomorphosis/ipfs_slovenia_laws",
        source_revision=_SHA,
    )
    assert kept_alien.admitted is True
    assert kept_alien.records[0]["text"].startswith("3. člen Tujec sme vstopiti")
    assert kept_alien.records[0]["provenance"]["article"] == "3"

    issuer_rows = (
        {
            "law_id": "law-k",
            "official_citation": "odlok-o-ustanovitvi-gimnazije-kocevje",
            "body": named_issuer,
        },
        {
            "law_id": "law-k",
            "official_citation": "odlok-o-ustanovitvi-gimnazije-kocevje",
            "body": "4. člen Ta odlok začne veljati naslednji dan po objavi.",
        },
        {
            "law_id": "law-z",
            "official_citation": "zakon-o-tujcih",
            "body": aliens,
        },
    )
    assert municipal_issuer_law_ids(issuer_rows) == {"law-k"}


def test_a_latvian_punkts_fills_the_article_and_a_municipal_issuer_does_not() -> None:
    national = (
        "3. Regulators 2019.gada 16.augustā par tarifu projektu rīkoja "
        "uzklausīšanas sanāksmi, kurā piedalījās pašvaldību pārstāvji."
    )
    decision = admit_source_law(
        _row(
            id="lv-tariff-3",
            title="3. punkts",
            language="lv",
            jurisdiction="LV",
            country="Latvia",
            official_citation="311189, art. 3. punkts",
            instrument_title=(
                'Par sabiedrības ar ierobežotu atbildību "ZAAO" '
                "sadzīves atkritumu apglabāšanas pakalpojuma tarifu"
            ),
            text=national,
        ),
        source_dataset="endomorphosis/ipfs_latvia_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert decision.records[0]["text"].startswith("3. Regulators 2019.gada")
    assert "pašvaldību pārstāvji" in decision.records[0]["text"]
    assert decision.records[0]["provenance"]["article"] == "3"
    assert decision.records[0]["provenance"]["section"] == "3"
    assert decision.records[0]["jurisdiction"] == "LV"

    pants = admit_source_law(
        _row(
            id="lv-civil-1",
            title="1. pants",
            language="lv",
            jurisdiction="LV",
            country="Latvia",
            official_citation="311200, art. 1. pants",
            instrument_title="Civillikums",
            text=(
                "1. pants Šis likums nosaka civiltiesiskās attiecības "
                "un to dalībnieku tiesības šajā valstī."
            ),
        ),
        source_dataset="endomorphosis/ipfs_latvia_laws",
        source_revision=_SHA,
    )
    assert pants.admitted is True
    assert pants.records[0]["text"].startswith("1. pants Šis likums")
    assert pants.records[0]["provenance"]["article"] == "1"

    cabinet = (
        "1. Šie noteikumi nosaka valsts parāda un pašvaldību parādu "
        "uzskaites klasifikāciju un tās piemērošanu."
    )
    kept_titles = (
        "Noteikumi par valsts parāda un pašvaldību parādu uzskaites klasifikāciju",
        "Par mazuta aizdošanu Preiļu novada domei",
        "Par valsts nekustamā īpašuma nodošanu Jēkabpils pilsētas pašvaldības īpašumā",
        "Ministru kabineta noteikumi par saistošo noteikumu publicēšanu",
        "Centrālās vēlēšanu komisijas rīkojums",
        "Latvijas Pašvaldību savienības nolikums",
    )
    kept_bodies = {
        "Centrālās vēlēšanu komisijas rīkojums": (
            "1. Pamatojoties uz Pilsētas domes, novada domes un pagasta padomes "
            "vēlēšanu likuma 24. panta pirmo daļu, Centrālā vēlēšanu komisija uzdod."
        ),
    }
    for instrument in kept_titles:
        kept = admit_source_law(
            _row(
                id="lv-kept",
                title="1. punkts",
                language="lv",
                jurisdiction="LV",
                country="Latvia",
                official_citation="225418, art. 1. punkts",
                instrument_title=instrument,
                text=kept_bodies.get(instrument, cabinet),
            ),
            source_dataset="endomorphosis/ipfs_latvia_laws",
            source_revision=_SHA,
        )
        assert kept.admitted is True, instrument
        assert kept.records[0]["provenance"]["article"] == "1"
        assert kept.records[0]["text"].startswith("1. ")

    refused_titles = (
        'Par Jēkabpils pilsētas domes saistošo noteikumu Nr.11 "Saistošie noteikumi"',
        "Zaudējis spēku - Pašvaldības nodeva par būvatļaujas saņemšanu",
        "Zaudējis spēku - Par Jūrmalas pašvaldības sociālajiem pabalstiem",
        "Jūrmalas pilsētas pašvaldības nolikums",
        "Lapmežciema pagasta būvvaldes lēmums par būvatļauju",
        "Lapmežciema pagasta padomes saistošie noteikumi",
    )
    for instrument in refused_titles:
        refused = admit_source_law(
            _row(
                id="lv-local",
                title="1. punkts",
                language="lv",
                jurisdiction="LV",
                country="Latvia",
                official_citation="311221, art. 1. punkts",
                instrument_title=instrument,
                text=(
                    "1. Atzīt par spēku zaudējušiem šos saistošos noteikumus "
                    "un noteikt to publicēšanas kārtību."
                ),
            ),
            source_dataset="endomorphosis/ipfs_latvia_laws",
            source_revision=_SHA,
        )
        assert refused.reason == "not_national", instrument
        assert refused.records == ()

    declined = admit_source_law(
        _row(
            id="lv-declined",
            title="3. punktu",
            language="lv",
            jurisdiction="LV",
            country="Latvia",
            official_citation="311189, art. 3. punktu",
            instrument_title="Civillikums",
            text=(
                "3. punktu piemēro šajā pantā noteiktajā kārtībā un apjomā "
                "visā Latvijas Republikas teritorijā."
            ),
        ),
        source_dataset="endomorphosis/ipfs_latvia_laws",
        source_revision=_SHA,
    )
    assert declined.admitted is False
    assert declined.records == ()
    mismatch = admit_source_law(
        _row(
            id="lv-mismatch",
            title="3. punkts",
            language="lv",
            jurisdiction="LV",
            country="Latvia",
            official_citation="311189, art. 3. punkts",
            instrument_title="Civillikums",
            text="31. Šis ir cits numurs un teikums, kas paliek ārpus šī panta.",
        ),
        source_dataset="endomorphosis/ipfs_latvia_laws",
        source_revision=_SHA,
    )
    assert mismatch.admitted is False
    assert mismatch.records == ()

    issuer_rows = (
        {
            "law_id": "law-local",
            "official_citation": "311221, art. 1. punkts",
            "instrument_title": "Jūrmalas pilsētas pašvaldības nolikums",
            "body": "1. Šis nolikums nosaka pašvaldības institūcijas.",
        },
        {
            "law_id": "law-local",
            "official_citation": "311221, art. 4. punkts",
            "instrument_title": "Jūrmalas pilsētas pašvaldības nolikums",
            "body": "4. Šis nolikums stājas spēkā nākamajā dienā pēc publicēšanas.",
        },
        {
            "law_id": "law-cabinet",
            "official_citation": "225418, art. 1. punkts",
            "instrument_title": (
                "Noteikumi par valsts parāda un pašvaldību parādu uzskaites klasifikāciju"
            ),
            "body": cabinet,
        },
    )
    assert municipal_issuer_law_ids(issuer_rows) == {"law-local"}


def test_an_andorran_sole_article_fills_and_a_parish_issuer_does_not() -> None:
    preamble = (
        "Llei de modificació puntual i urgent de la Llei general "
        "d'ordenació del territori i urbanisme. "
        "Atès que el Consell General en la seva sessió del dia 23 de maig "
        "del 2003 ha aprovat la següent:"
    )
    article = (
        "Article únic\n"
        "Es modifica l'article 10 de la Llei general d'ordenació del "
        "territori i urbanisme en els termes que aquesta llei estableix."
    )
    national_text = preamble + "\n" + article
    decision = admit_source_law(
        _row(
            id="ad-llei-7",
            title="Llei 7/2003, del 23 de maig",
            instrument_title="Llei 7/2003, del 23 de maig, de modificació puntual",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            text=national_text,
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert decision.reason == "law"
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == national_text
    assert decision.records[0]["provenance"]["article"] == "únic"
    assert decision.records[0]["provenance"]["section"] == "únic"
    assert decision.records[0]["jurisdiction"] == "AD"
    assert "Consell General" in decision.records[0]["text"]

    unaccented = admit_source_law(
        _row(
            id="ad-unic",
            title="Article unic",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Llei de modificació del text refós",
            text=(
                "Atès que el Consell General ha aprovat el text que segueix "
                "per al conjunt del Principat d'Andorra.\n"
                "Article unic\n"
                "Es modifica el text refós en els termes que aquesta llei fixa."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert unaccented.admitted is True
    assert len(unaccented.records) == 1
    assert unaccented.records[0]["provenance"]["article"] == "unic"
    assert unaccented.records[0]["text"].startswith("Atès que el Consell General")

    adverb = admit_source_law(
        _row(
            id="ad-adverb",
            title="Nota",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Llei qualificada dels Comuns",
            text=(
                "Atès que el Consell General ha examinat el text.\n"
                "Article únicament aplicable als residents\n"
                "Aquesta regla únicament es refereix als residents habituals "
                "del Principat i no crea un article nou."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert adverb.admitted is False
    assert adverb.reason == "not_queryable"
    assert adverb.records == ()

    divided = admit_source_law(
        _row(
            id="ad-two",
            title="Llei 7/2003",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Llei 7/2003, del 23 de maig",
            text=(
                "Article 1 El Consell General aprova aquesta llei per a tot "
                "el territori del Principat.\n"
                "Article 2 Els Comuns apliquen les normes que aquesta llei "
                "estableix en el seu terme."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert divided.admitted is True
    assert [record["provenance"].get("article") for record in divided.records] == ["1", "2"]
    assert "Article 2" not in divided.records[0]["text"]

    sole = (
        "Atès que el Consell General en la seva sessió del dia 23 de maig "
        "del 2003 ha aprovat el text que segueix per al conjunt del Principat.\n"
        "Article 3\n"
        "Les disposicions d'aquesta llei s'apliquen a tot el Principat d'Andorra."
    )
    assert len(sole.split("Article 3")[0]) > 80
    mid = admit_source_law(
        _row(
            id="ad-article-3",
            title="Llei general",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Llei general d'ordenació del territori",
            text=sole,
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert mid.admitted is True
    assert len(mid.records) == 1
    assert mid.records[0]["text"] == sole
    assert mid.records[0]["provenance"]["article"] == "3"
    assert mid.records[0]["provenance"]["section"] == "3"

    edicte = admit_source_law(
        _row(
            id="ad-edicte",
            title="Edicte T.C. del 29-4-2003 pel qual es cita els Srs.",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Edicte T.C. del 29-4-2003 pel qual es cita els Srs.",
            text=(
                "Edicte\n"
                "En Jean Louis Vuillemin, President del Tribunal Superior de "
                "Justícia d'Andorra i de la seva Sala Civil, faig saber que "
                "se cita el Sr. Carles Ferré Casals perquè comparegui."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert edicte.admitted is False
    assert edicte.reason == "not_queryable"
    assert edicte.records == ()

    annex = admit_source_law(
        _row(
            id="ad-annex",
            title="Article Annexe",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Llei de construcció dels locals",
            text=(
                "Preàmbul de la norma que descriu l'annex sense crear un altre article.\n"
                "Article Annexe\n"
                "Els materials utilitzats per a la construcció dels locals no "
                "han de ser nocius per a les persones."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert annex.admitted is False
    assert annex.reason == "not_queryable"
    assert annex.records == ()

    citation = admit_source_law(
        _row(
            id="ad-aute",
            title="Aute del Tribunal Constitucional relatiu al recurs d'empara",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Aute del Tribunal Constitucional relatiu al recurs d'empara",
            text=(
                "Aute del dia 30 de juny del 2003\n"
                "En nom del Poble Andorrà, el Tribunal Constitucional ha examinat "
                "la demanda en dret, reconeguts a\n"
                "l'article 10 de la Constitució, i atès que sol·licita al Tribunal "
                "Constitucional que declari la vulneració denunciada."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert citation.admitted is False
    assert citation.reason == "not_queryable"
    assert citation.records == ()

    street = admit_source_law(
        _row(
            id="ad-street",
            title="Edicte pel qual es fan públiques diverses adjudicacions",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Edicte pel qual es fan públiques diverses adjudicacions",
            text=(
                "Edicte\n"
                "Per acord del consell d'Administració es fan públiques les "
                "adjudicacions definitives següents, referència 2104\n"
                "Designació: 02AO21 Can. C/ dels Barrers Santa Coloma Comú Andorra la Vella."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert street.admitted is False
    assert street.reason == "not_queryable"
    assert street.records == ()

    quoted = admit_source_law(
        _row(
            id="ad-quoted",
            title="Avís pel qual es modifica el contingut d'un article",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Avís pel qual es modifica el contingut d'un article de les Ordinacions",
            text=(
                "La Junta de Govern reunida el passat 13 de novembre del 2003 "
                "acordà la modificació del contingut de l'article 12; la nova "
                "redacció del mateix queda establerta com segueix:\n"
                '"Article 12\n'
                "Totes les transmissions de béns immobles situats a la parròquia "
                "s'han de comunicar a l'administració."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert quoted.admitted is False
    assert quoted.reason == "not_queryable"
    assert quoted.records == ()

    ordinal = admit_source_law(
        _row(
            id="ad-ordinal",
            title="Edicte pel qual es publica la relació de vehicles abandonats",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Edicte pel qual es publica la relació de vehicles abandonats",
            text=(
                "Edicte\n"
                "Vista l'Ordinació d'abandó de vehicles, del 28 de setembre de 1994,\n"
                "article 3r,\n"
                "Pel present, es fa pública la relació dels vehicles referits i "
                "el nom del propietari que consta al registre."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert ordinal.admitted is False
    assert ordinal.reason == "not_queryable"
    assert ordinal.records == ()

    parish = admit_source_law(
        _row(
            id="ad-encamp",
            title="Decret de modificació de l'Ordinació general tributària",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Decret de modificació de l'Ordinació general tributària",
            text=(
                "Decret de modificació de l'Ordinació general tributària\n"
                "El Comú d'Encamp, en la sessió ordinària de Consell de Comú "
                "del dia 7 de maig del 2003, ha acordat la modificació següent.\n"
                "Article 3\n"
                "Els tipus de gravamen de la parròquia s'apliquen segons el "
                "quadre aprovat pel Consell de Comú."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert parish.reason == "not_national"
    assert parish.records == ()

    titled = admit_source_law(
        _row(
            id="ad-sant-julia",
            title="Article 1",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Reglament intern del Comú de Sant Julià de Lòria",
            text=(
                "Article 1\n"
                "Aquest reglament ordena els serveis interns i s'aplica als "
                "treballadors de la casa comunal de la parròquia."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert titled.reason == "not_national"
    assert titled.records == ()

    mention = admit_source_law(
        _row(
            id="ad-caccia",
            title="Ordre ministerial relativa a la temporada de caça",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Ordre ministerial relativa a la temporada de caça de l'isard",
            text=(
                "Ordre ministerial relativa a la temporada de caça\n"
                "Vista la demanda formulada pel Comú d'Encamp de prohibir la "
                "caça en la zona d'activitat humana del Funicamp.\n"
                "Article únic\n"
                "Es prohibeix la caça de l'isard en la zona indicada durant "
                "la temporada que fixa aquesta ordre."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert mention.admitted is True
    assert len(mention.records) == 1
    assert mention.records[0]["provenance"]["article"] == "únic"
    assert "pel Comú d'Encamp" in mention.records[0]["text"]

    comuns = admit_source_law(
        _row(
            id="ad-comuns",
            title="Llei qualificada de competències",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Llei qualificada de delimitació de competències dels Comuns",
            text=(
                "Atès que el Consell General regula les competències dels Comuns "
                "en aquesta matèria per al conjunt del Principat.\n"
                "Article únic\n"
                "Els Comuns exerceixen les competències que aquesta llei els "
                "atribueix en el seu terme parroquial."
            ),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert comuns.admitted is True
    assert comuns.records[0]["provenance"]["article"] == "únic"
    assert "dels Comuns" in comuns.records[0]["text"]

    issuer_rows = (
        {
            "law_id": "law-encamp",
            "instrument_title": "Decret de modificació de l'Ordinació",
            "body": (
                "El Comú d'Encamp, en la sessió ordinària de Consell de Comú, "
                "ha acordat la modificació."
            ),
        },
        {
            "law_id": "law-encamp",
            "instrument_title": "Decret de modificació de l'Ordinació",
            "body": "Article 4 Aquesta ordinació entra en vigor l'endemà de la publicació.",
        },
        {
            "law_id": "law-general",
            "instrument_title": "Llei qualificada de delimitació de competències dels Comuns",
            "body": (
                "Atès que el Consell General regula les competències dels Comuns."
            ),
        },
    )
    assert municipal_issuer_law_ids(issuer_rows) == {"law-encamp"}

    nulled_parish = (
        "Decret\n"
        "El Comú d'Encamp, en la sessió ordinària de Consell de Comú del dia "
        "7 de maig, ha acordat la modificació següent.\n"
        "Article 3\n"
        "Els tipus de gravamen de la parròquia s'apliquen segons el quadre aprovat."
    )
    encoded_parish = admit_source_law(
        _row(
            id="ad-encamp-nulls",
            title="Decret de modificació de l'Ordinació general tributària",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Decret de modificació de l'Ordinació general tributària",
            text="ÿþ" + nulled_parish.encode("utf-16-le").decode("latin-1"),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert encoded_parish.reason == "not_national"
    assert encoded_parish.records == ()

    nulled_national = (
        "Atès que el Consell General en la seva sessió del dia 23 de maig "
        "del 2003 ha aprovat la següent:\n"
        "Article únic\n"
        "Es modifica l'article 10 de la Llei general d'ordenació del "
        "territori i urbanisme en els termes que aquesta llei estableix."
    )
    encoded_national = admit_source_law(
        _row(
            id="ad-llei-nulls",
            title="Llei 7/2003, del 23 de maig",
            language="ca",
            jurisdiction="AD",
            country="Andorra",
            instrument_title="Llei 7/2003, del 23 de maig",
            text="ÿþ" + nulled_national.encode("utf-16-le").decode("latin-1"),
        ),
        source_dataset="endomorphosis/ipfs_andorra_laws",
        source_revision=_SHA,
    )
    assert encoded_national.admitted is True
    assert len(encoded_national.records) == 1
    assert encoded_national.records[0]["provenance"]["article"] == "únic"
    assert "Consell General" in encoded_national.records[0]["text"]
    assert "\x00" not in encoded_national.records[0]["text"]


def test_an_italian_sole_article_fills_and_a_repeal_banner_does_not() -> None:
    preamble = (
        "La Camera dei deputati ed il Senato della Repubblica hanno approvato; "
        "IL PRESIDENTE DELLA REPUBBLICA PROMULGA la seguente legge:"
    )
    statute = (
        preamble
        + "\nArt. 1\n"
        + "Il Governo è autorizzato a far pagare le spese ordinarie e "
        + "straordinarie del Ministero di grazia e giustizia."
    )
    decision = admit_source_law(
        _row(
            id="it-legge-963",
            title="LEGGE 24 ottobre 1955, n. 963",
            instrument_title="LEGGE 24 ottobre 1955, n. 963",
            language="it",
            jurisdiction="IT",
            country="Italy",
            text=statute,
        ),
        source_dataset="endomorphosis/ipfs_italy_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert decision.reason == "law"
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == statute
    assert decision.records[0]["provenance"]["article"] == "1"
    assert decision.records[0]["provenance"]["section"] == "1"
    assert decision.records[0]["jurisdiction"] == "IT"

    unique = (
        preamble
        + "\nArticolo unico.\n"
        + "È autorizzato il pagamento delle spese ordinarie e straordinarie "
        + "del Ministero del commercio per l'esercizio finanziario."
    )
    unico = admit_source_law(
        _row(
            id="it-legge-968",
            title="LEGGE 31 ottobre 1955, n. 968",
            instrument_title="LEGGE 31 ottobre 1955, n. 968",
            language="it",
            jurisdiction="IT",
            country="Italy",
            text=unique,
        ),
        source_dataset="endomorphosis/ipfs_italy_laws",
        source_revision=_SHA,
    )
    assert unico.admitted is True
    assert len(unico.records) == 1
    assert unico.records[0]["text"] == unique
    assert unico.records[0]["provenance"]["article"] == "unico"
    assert unico.records[0]["provenance"]["section"] == "unico"

    banner = (
        preamble
        + "\nArt. 1\n"
        + "((PROVVEDIMENTO ABROGATO DAL D.LGS. 13 DICEMBRE 2010, N. 212))"
    )
    repealed = admit_source_law(
        _row(
            id="it-abrogato",
            title="REGIO DECRETO 21 febbraio 1901, n. 87",
            instrument_title="REGIO DECRETO 21 febbraio 1901, n. 87",
            language="it",
            jurisdiction="IT",
            country="Italy",
            text=banner,
        ),
        source_dataset="endomorphosis/ipfs_italy_laws",
        source_revision=_SHA,
    )
    assert repealed.admitted is False
    assert repealed.reason == "not_queryable"
    assert repealed.records == ()

    quoted = (
        preamble
        + "\n«Art. 8\n"
        + "Il testo citato di un'altra legge resta fuori da questo articolo."
    )
    citation = admit_source_law(
        _row(
            id="it-quoted",
            title="Nota di rinvio",
            instrument_title="Nota di rinvio",
            language="it",
            jurisdiction="IT",
            country="Italy",
            text=quoted,
        ),
        source_dataset="endomorphosis/ipfs_italy_laws",
        source_revision=_SHA,
    )
    assert citation.admitted is False
    assert citation.reason == "not_queryable"
    assert citation.records == ()

    divided = admit_source_law(
        _row(
            id="it-due",
            title="LEGGE 19 luglio 1988, n. 310",
            instrument_title="LEGGE 19 luglio 1988, n. 310",
            language="it",
            jurisdiction="IT",
            country="Italy",
            text=(
                preamble
                + "\nArt. 1\n"
                + "In attesa della riforma, il contributo è corrisposto agli aventi diritto.\n"
                + "Art. 2\n"
                + "La presente legge entra in vigore il giorno successivo alla pubblicazione."
            ),
        ),
        source_dataset="endomorphosis/ipfs_italy_laws",
        source_revision=_SHA,
    )
    assert divided.admitted is True
    assert len(divided.records) == 2
    assert divided.records[0]["provenance"]["article"] == "1"
    assert "Art. 2" not in divided.records[0]["text"]
    assert divided.records[1]["provenance"]["article"] == "2"


def test_a_taiwan_article_line_fills_and_a_deletion_or_chart_does_not() -> None:
    statute = (
        "第 7 條\n"
        "本校置校長一人，少將，綜理校務；教育長、政戰主任各一人，襄助校長處理校務。"
    )
    decision = admit_source_law(
        _row(
            id="tw-org-7",
            title="海軍陸戰隊學校組織規程",
            instrument_title="海軍陸戰隊學校組織規程",
            language="zh-Hant",
            jurisdiction="TW",
            country="Taiwan",
            text=statute,
        ),
        source_dataset="endomorphosis/ipfs_taiwan_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == normalize_legal_text(statute)
    assert "綜理校務" in decision.records[0]["text"]
    assert decision.records[0]["provenance"]["article"] == "7"
    assert decision.records[0]["jurisdiction"] == "TW"

    listed = (
        "第 4 條\n"
        "本校依學校特性及發展方向，辦理下列層次之教育：\n"
        "一、基礎教育。\n"
        "二、進修教育。\n"
        "第 5 條\n"
        "本校置校長一人，綜理校務，並指揮所屬單位。"
    )
    parts = admit_source_law(
        _row(
            id="tw-org-4",
            title="空軍航空技術學院組織規程",
            instrument_title="空軍航空技術學院組織規程",
            language="zh-Hant",
            jurisdiction="TW",
            country="Taiwan",
            text=listed,
        ),
        source_dataset="endomorphosis/ipfs_taiwan_laws",
        source_revision=_SHA,
    )
    assert parts.admitted is True
    assert [record["provenance"]["article"] for record in parts.records] == ["4", "5"]
    assert "一、基礎教育" in parts.records[0]["text"]
    assert "第 5 條" not in parts.records[0]["text"]

    cited = (
        "第 1 條\n"
        "本規程依軍事教育條例第十九條第一項規定訂定之。\n"
        "第 5 條\n"
        "作業程序：\n"
        "一、第三條所定事項，由主計單位辦理。\n"
        "二、第四條所定事項，由人事單位辦理。\n"
        "第 6 條\n"
        "本辦法自發布日施行，並送立法院備查。"
    )
    cited_decision = admit_source_law(
        _row(
            id="tw-cite",
            title="國軍主計人員任職管制辦法",
            instrument_title="國軍主計人員任職管制辦法",
            language="zh-Hant",
            jurisdiction="TW",
            country="Taiwan",
            text=cited,
        ),
        source_dataset="endomorphosis/ipfs_taiwan_laws",
        source_revision=_SHA,
    )
    assert cited_decision.admitted is True
    assert [record["provenance"]["article"] for record in cited_decision.records] == ["1", "5", "6"]
    assert "第十九條第一項規定訂定之" in cited_decision.records[0]["text"]
    joined = "\n".join(record["text"] for record in cited_decision.records)
    assert "一、第三條所定事項" in joined
    assert "二、第四條所定事項" in joined

    medals = (
        "第 2 條\n"
        "勳賞之種類如左:\n"
        "一、國光勳章。\n"
        "二、青天白日勳章。\n"
        "三、寶鼎勳章。"
    )
    medal_decision = admit_source_law(
        _row(
            id="tw-medal",
            title="陸海空軍勳賞條例",
            instrument_title="陸海空軍勳賞條例",
            language="zh-Hant",
            jurisdiction="TW",
            country="Taiwan",
            text=medals,
        ),
        source_dataset="endomorphosis/ipfs_taiwan_laws",
        source_revision=_SHA,
    )
    assert medal_decision.admitted is True
    assert medal_decision.records[0]["text"] == normalize_legal_text(medals)
    assert "國光勳章" in medal_decision.records[0]["text"]
    assert "青天白日勳章" in medal_decision.records[0]["text"]

    omitted = admit_source_law(
        _row(
            id="tw-omitted",
            title="Act of Marriage for Military Personnel",
            instrument_title="Act of Marriage for Military Personnel",
            language="en",
            jurisdiction="TW",
            country="Taiwan",
            text="Article 7\n(Omitted)",
        ),
        source_dataset="endomorphosis/ipfs_taiwan_laws",
        source_revision=_SHA,
    )
    assert omitted.admitted is False
    assert omitted.reason == "not_queryable"
    assert omitted.records == ()

    deleted = admit_source_law(
        _row(
            id="tw-delete",
            title="The Military Police School (MPS) Organization Regulations",
            instrument_title="The Military Police School (MPS) Organization Regulations",
            language="zh-Hant",
            jurisdiction="TW",
            country="Taiwan",
            text="第 8 條\n（刪除）",
        ),
        source_dataset="endomorphosis/ipfs_taiwan_laws",
        source_revision=_SHA,
    )
    assert deleted.admitted is False
    assert deleted.reason == "not_queryable"
    assert deleted.records == ()

    chart = admit_source_law(
        _row(
            id="tw-chart",
            title="國軍退除役官兵輔導委員會榮民森林保育事業管理處編制表",
            instrument_title="國軍退除役官兵輔導委員會榮民森林保育事業管理處編制表",
            language="zh-Hant",
            jurisdiction="TW",
            country="Taiwan",
            text=(
                "國軍退除役官兵輔導委員會榮民森林保育事業管理處編制表\n"
                "編 註:本編制表依據組織規程第 11 條訂定，內容請參閱相關圖表附檔。"
            ),
        ),
        source_dataset="endomorphosis/ipfs_taiwan_laws",
        source_revision=_SHA,
    )
    assert chart.admitted is False
    assert chart.reason == "not_queryable"
    assert chart.records == ()


def test_a_double_encoded_apostrophe_decodes_to_one_apostrophe() -> None:
    raw = "their master&amp;amp;#39;s degree"
    decoded = normalize_legal_text(raw)
    assert decoded == "their master's degree"
    assert normalize_legal_text(decoded) == decoded


def test_a_finnish_section_fills_and_a_repeal_note_does_not() -> None:
    statute = (
        "12 § Jos riita jonkun velallista vastaan nostetun maksuvaatimuksen "
        "otollisuudesta on konkurssin alussa toisen Oikeuden päätettävänä.\n"
        "7 luku Kuinka konkurssi on lopetettava, niin myös tilinteosta"
    )
    decision = admit_source_law(
        _row(
            id="fi-12",
            title="12 §",
            text=statute,
            language="fi",
            jurisdiction="FI",
            country="Finland",
        ),
        source_dataset="endomorphosis/ipfs_finland_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == normalize_legal_text(statute)
    assert "7 luku" in decision.records[0]["text"]
    assert decision.records[0]["provenance"]["section"] == "12"
    assert decision.records[0]["jurisdiction"] == "FI"

    copied = (
        "1 b § Konkurssihakemuksessa on ilmoitettava, millä perusteella "
        "tuomioistuin on toimivaltainen, jos toimivalta ei muutoin ilmene hakemuksesta."
    )
    lettered = admit_source_law(
        _row(
            id="fi-1b",
            title=copied,
            text=copied,
            language="fi",
            jurisdiction="FI",
            country="Finland",
        ),
        source_dataset="endomorphosis/ipfs_finland_laws",
        source_revision=_SHA,
    )
    assert lettered.admitted is True
    assert lettered.records[0]["text"] == copied
    assert lettered.records[0]["provenance"]["section"] == "1 b"

    swedish = (
        "84 a § Konkursombudsmannen följer och övervakar förvaltningen av "
        "konkursbon så som stadgas särskilt.\n"
        "6 kap. Om gäldenärens betalningsskyldighet efter konkursen"
    )
    swedish_row = admit_source_law(
        _row(
            id="fi-sv-84a",
            title="84 a §",
            text=swedish,
            language="sv",
            jurisdiction="FI",
            country="Finland",
        ),
        source_dataset="endomorphosis/ipfs_finland_laws",
        source_revision=_SHA,
    )
    assert swedish_row.admitted is True
    assert swedish_row.records[0]["text"] == normalize_legal_text(swedish)
    assert swedish_row.records[0]["provenance"]["section"] == "84 a"

    repeal = (
        "44 § on kumottu L:lla 26.11.1993/1027 .\n"
        "4 luku Konkurssipesään kuuluva omaisuus"
    )
    repealed = admit_source_law(
        _row(
            id="fi-44",
            title="44 §",
            text=repeal,
            language="fi",
            jurisdiction="FI",
            country="Finland",
        ),
        source_dataset="endomorphosis/ipfs_finland_laws",
        source_revision=_SHA,
    )
    assert repealed.admitted is False
    assert repealed.records == ()

    banner = "8 § on kumottu L:lla 26.11.1993/1027 ."
    shell = admit_source_law(
        _row(
            id="fi-8",
            title=banner,
            text=banner,
            language="fi",
            jurisdiction="FI",
            country="Finland",
        ),
        source_dataset="endomorphosis/ipfs_finland_laws",
        source_revision=_SHA,
    )
    assert shell.admitted is False
    assert shell.reason == "metadata"
    assert shell.records == ()

    both = (
        "5 § Hakemus tehdään kirjallisesti ja siihen liitetään selvitys veloista.\n"
        "6 § on kumottu L:lla sosiaalihuoltolain muuttamisesta 588/2022 ."
    )
    kept = admit_source_law(
        _row(
            id="fi-5",
            title="5 §",
            text=both,
            language="fi",
            jurisdiction="FI",
            country="Finland",
        ),
        source_dataset="endomorphosis/ipfs_finland_laws",
        source_revision=_SHA,
    )
    assert kept.admitted is True
    assert len(kept.records) == 1
    assert kept.records[0]["provenance"]["section"] == "5"
    assert "selvitys veloista" in kept.records[0]["text"]
    assert "on kumottu" not in kept.records[0]["text"]

    citation = (
        "Ympäristöministeriö on 17 päivänä joulukuuta 1993 annetun "
        "aravarajoituslain (1190/1993) 4 §:n 4 momentin mukaan säätänyt, "
        "että hakemus tehdään kirjallisesti."
    )
    cited = admit_source_law(
        _row(
            id="fi-cite",
            title="182/2003 Ympäristöministeriön asetus",
            text=citation,
            language="fi",
            jurisdiction="FI",
            country="Finland",
        ),
        source_dataset="endomorphosis/ipfs_finland_laws",
        source_revision=_SHA,
    )
    assert cited.admitted is False
    assert cited.records == ()


def test_a_czech_gazette_instrument_keeps_its_text_and_not_the_collection_number() -> None:
    statute = (
        "12.\n"
        "Nařízení vlády republiky Československé\n"
        "ze dne 30. prosince 1920\n"
        "ku provedení zákona o úlevách při přijímání legionářů.\n"
        "Vláda nařizuje:\n"
        "Pro dosazení legionářů v úřad je potřebí povolení ústředního úřadu."
    )
    decision = admit_source_law(
        _row(
            id="cs-12",
            title="Nařízení vlády o úlevách při přijímání legionářů",
            text=statute,
            language="cs",
            jurisdiction="CZ",
            country="Czechia",
        ),
        source_dataset="endomorphosis/ipfs_czechia_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == normalize_legal_text(statute)
    assert decision.records[0]["provenance"].get("section") in (None, "")
    assert decision.records[0]["provenance"].get("article") in (None, "")
    assert decision.records[0]["provenance"].get("heading_placement") == "whole_instrument"

    mislabeled = (
        "28.\n"
        "Vyhláška ministerstva vnitra, že se opravují tiskové chyby v nařízení.\n"
        "Ministerstvo vyhlašuje, že řádek 29 má zníti jinak než v původním znění."
    )
    stamped = admit_source_law(
        _row(
            id="cs-28",
            title="Vyhláška o opravě tiskové chyby",
            text=mislabeled,
            language="cs",
            jurisdiction="CZ",
            country="Czechia",
            section_number="28",
            hierarchy_kind="section",
            hierarchy_path="Section 28",
        ),
        source_dataset="endomorphosis/ipfs_czechia_laws",
        source_revision=_SHA,
    )
    assert stamped.admitted is True
    assert stamped.records[0]["text"] == normalize_legal_text(mislabeled)
    assert stamped.records[0]["provenance"].get("section") in (None, "")
    assert stamped.records[0]["provenance"].get("hierarchy_path") in (None, "")

    citation = (
        "160.\n"
        "Nařízení o prodloužení opční lhůty stanovené v § 4 ústavního zákona.\n"
        "Lhůta se prodlužuje do 30. června podle dřívějšího oznámení ministerstva."
    )
    cited = admit_source_law(
        _row(
            id="cs-160",
            title="Nařízení o prodloužení opční lhůty",
            text=citation,
            language="cs",
            jurisdiction="CZ",
            country="Czechia",
        ),
        source_dataset="endomorphosis/ipfs_czechia_laws",
        source_revision=_SHA,
    )
    assert cited.admitted is False
    assert cited.records == ()

    divided = (
        "§ 1\n"
        "Toto nařízení stanoví pravidla pro zápis do evidence.\n"
        "§ 2\n"
        "Ministerstvo vede evidenci podle tohoto nařízení a zveřejňuje zápisy."
    )
    parts = admit_source_law(
        _row(
            id="cs-split",
            title="Nařízení o evidenci",
            text=divided,
            language="cs",
            jurisdiction="CZ",
            country="Czechia",
        ),
        source_dataset="endomorphosis/ipfs_czechia_laws",
        source_revision=_SHA,
    )
    assert parts.admitted is True
    assert [record["provenance"].get("section") for record in parts.records] == ["1", "2"]
    assert "pravidla pro zápis" in parts.records[0]["text"]
    assert "zveřejňuje zápisy" in parts.records[1]["text"]


def test_a_document_id_does_not_admit_a_caption_or_a_label_table() -> None:
    article = admit_source_law(
        _row(
            id="py-115",
            title="Art. 115.",
            article_number="Art. 115.",
            official_identifier="12907",
            language="es",
            jurisdiction="PY",
            country="Paraguay",
            text=(
                "Art. 115.\n"
                "Tabacos, cigarrillos, esencias y similares.\n"
                "Los bienes que se establecen en la siguiente tabla de tributación, "
                "quedarán gravados de acuerdo con la tasa impositiva que sigue."
            ),
        ),
        source_dataset="endomorphosis/ipfs_paraguay_laws",
        source_revision=_SHA,
    )
    assert article.admitted is True
    assert article.records[0]["provenance"]["article"] == "115"
    assert article.records[0]["provenance"]["section"] == "115"
    assert article.records[0]["provenance"].get("statute") != "12907"
    caption = admit_source_law(
        _row(
            title="CAPÍTULO II",
            article_number="CAPÍTULO II",
            official_identifier="12907",
            language="es",
            jurisdiction="PY",
            text="CAPÍTULO II\nAUTORIDAD DE APLICACIÓN Y ÁMBITO DE COMPETENCIA",
        ),
        source_dataset="endomorphosis/ipfs_paraguay_laws",
        source_revision=_SHA,
    )
    assert caption.admitted is False
    assert caption.reason == "not_queryable"
    assert caption.records == ()
    table = admit_source_law(
        _row(
            title="1. Grupi ligjor 3",
            article_number="1",
            official_identifier="122679",
            language="sq",
            jurisdiction="XK",
            text=(
                "1. Grupi ligjor 3\n"
                "mbështetje ligjore\n"
                "Zyrtar për përpunimin e Profesional 2"
            ),
        ),
        source_dataset="endomorphosis/ipfs_kosovo_laws",
        source_revision=_SHA,
    )
    assert table.admitted is False
    assert table.reason == "not_queryable"
    assert table.records == ()


def test_one_leading_heading_becomes_a_query_locator() -> None:
    neni = admit_source_law(
        _row(
            title="Neni 1 Article 1 Član 1",
            article_number="Neni 1",
            official_identifier="10000",
            language="sq",
            jurisdiction="XK",
            text=(
                "Neni 1 Article 1 Član 1\n"
                "Qëllimi Purpose Svrha\n"
                "Kjo rregullore përcakton autoritetet për miratimin e medaljeve."
            ),
        ),
        source_dataset="endomorphosis/ipfs_kosovo_laws",
        source_revision=_SHA,
    )
    assert neni.admitted is True
    assert neni.records[0]["provenance"]["article"] == "1"
    assert neni.records[0]["provenance"]["section"] == "1"
    assert neni.records[0]["provenance"].get("statute") != "10000"
    assert "medaljeve" in str(neni.records[0]["text"])
    ordinance = admit_source_law(
        _row(
            title="2. Application.",
            article_number="paragraph 2",
            official_identifier="Ordinance nr. 16 of 2006",
            language="en",
            text="2. This Ordinance applies to all areas in the City.",
        ),
        source_dataset="endomorphosis/ipfs_uganda_laws",
        source_revision=_SHA,
    )
    assert ordinance.admitted is True
    assert ordinance.records[0]["provenance"]["section"] == "2"
    assert ordinance.records[0]["provenance"]["statute"] == "Ordinance nr. 16 of 2006"
    chapter = admit_source_law(
        _row(
            title="Chapter 1",
            language="en",
            text=(
                "Chapter 1\n"
                "This Act applies throughout the territory and binds every person who resides there."
            ),
        ),
        source_dataset="endomorphosis/ipfs_uganda_laws",
        source_revision=_SHA,
    )
    assert chapter.admitted is True
    assert chapter.records[0]["provenance"]["chapter"] == "1"
    thai = admit_source_law(
        _row(
            title="มาตรา ๒๒",
            article_number="22",
            language="th",
            jurisdiction="TH",
            text=(
                "มาตรา ๒๒ แห่งพระราชบัญญัติล้มละลาย พุทธศักราช ๒๔๘๓\n"
                "และบุคคลผู้เป็นหนี้ลูกหนี้หรือมีทรัพย์สินของลูกหนี้อยู่ในครอบครอง"
            ),
        ),
        source_dataset="endomorphosis/ipfs_thailand_laws",
        source_revision=_SHA,
    )
    assert thai.admitted is True
    assert thai.records[0]["provenance"]["article"] == "22"
    assert thai.records[0]["provenance"]["section"] == "22"
    mislabeled = admit_source_law(
        _row(
            title="Article 81",
            language="ar",
            jurisdiction="TN",
            text=(
                "Article 81.- Le jet de bagages et de marchandises indispensable "
                "à la sécurité de l'aéronef n'engage que la responsabilité du transporteur."
            ),
        ),
        source_dataset="endomorphosis/ipfs_tunisia_laws",
        source_revision=_SHA,
    )
    assert mislabeled.admitted is True
    assert mislabeled.records[0]["provenance"]["article"] == "81"
    assert mislabeled.records[0]["provenance"]["section"] == "81"
    listing = admit_source_law(
        _row(
            title="LISTA 08-2026 PER PUBLIKIMIN E KERKESAVE",
            official_identifier="122759",
            language="sq",
            text=(
                "Agjencia Kosovare për Krahasim dhe Verifikim të Pronës është Agjenci e pavarur.\n"
                "The Agency is an independent Agency established pursuant to Article 142."
            ),
        ),
        source_dataset="endomorphosis/ipfs_kosovo_laws",
        source_revision=_SHA,
    )
    assert listing.admitted is False
    assert listing.reason == "notice"
    assert listing.records == ()
    menu = admit_source_law(
        _row(
            title="สำนักคณะกรรมการ",
            official_identifier="สำนักคณะกรรมการ",
            language="th",
            text="กฎหมาย ช่วยเหลือ รัฐธรรมนูญ พระราชบัญญัติ ประมวลกฎหมาย สนธิสัญญา แสดงกฎหมายปัจจุบัน",
        ),
        source_dataset="endomorphosis/ipfs_thailand_laws",
        source_revision=_SHA,
    )
    assert menu.admitted is False
    assert menu.reason == "not_queryable"
    assert menu.records == ()


def test_a_local_parquet_fill_writes_only_queryable_laws(tmp_path: Path) -> None:
    source = tmp_path / "laws.parquet"
    pq.write_table(
        pa.table(
            {
                "id": ["fr-1", "site", "cap"],
                "title": ["Loi exemple", "Search", "CAPÍTULO II"],
                "body": [
                    _ACT,
                    "Home\nSearch\nContact us\nThis website uses cookies\n",
                    "CAPÍTULO II\nAUTORIDAD DE APLICACIÓN Y ÁMBITO DE COMPETENCIA",
                ],
                "language": ["fr", "fr", "es"],
                "jurisdiction": ["FR", "FR", "PY"],
                "source_url": [
                    "https://example.test/fr/loi",
                    "https://example.test/search",
                    "https://example.test/py/cap",
                ],
                "article_number": ["", "", "CAPÍTULO II"],
                "official_identifier": ["", "", "12907"],
                "source_revision": [_SHA, _SHA, _SHA],
            }
        ),
        source,
    )
    report = fill_country_parquet(
        source,
        tmp_path / "out",
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert report["rows_read"] == 3
    assert report["atoms_written"] == 2
    assert report["atoms_with_locator"] == 2
    assert report["reasons"]["law"] == 1
    assert report["reasons"]["informative"] == 1
    assert report["reasons"]["not_queryable"] == 1
    assert report["coverage"] == "snapshot"
    written = pq.read_table(tmp_path / "out" / "france" / "part-000000.parquet")
    texts = written.column("text").to_pylist()
    assert len(texts) == 2
    assert all(text.startswith("Article ") for text in texts)
    assert "Search" not in "\n".join(texts)
    assert "CAPÍTULO" not in "\n".join(texts)
    assert set(written.column("normalizer_version").to_pylist()) == {"country-source-admit/v1"}
    assert set(written.column("admin_level").to_pylist()) == {"country"}
    provenance = json.loads(written.column("provenance")[0].as_py())
    assert provenance["document_role"] == "law"
    assert provenance["jsonld"]["@type"] == "Legislation"
    assert provenance["jsonld"]["encodingFormat"] == "text/plain"
    saved = json.loads((tmp_path / "out" / "france" / "report.json").read_text(encoding="utf-8"))
    assert saved["atoms_written"] == 2
    try:
        fill_country_parquet(
            source,
            tmp_path / "out",
            source_dataset="endomorphosis/ipfs_belgium_laws",
            source_revision=_SHA,
        )
    except ValueError as exc:
        assert str(exc) == "excluded"
    else:
        raise AssertionError("excluded source was written")
    try:
        fill_country_parquet(
            source,
            tmp_path / "out",
            source_dataset="endomorphosis/ipfs_france_municipal_laws",
            source_revision=_SHA,
        )
    except ValueError as exc:
        assert str(exc) == "not_national"
    else:
        raise AssertionError("municipal source was written")


def test_every_corpus_part_becomes_queryable_atoms(tmp_path: Path) -> None:
    first = tmp_path / "part-000000.parquet"
    second = tmp_path / "part-000001.parquet"
    _write_source(
        first,
        ["fr-1"],
        ["Loi exemple"],
        [_ACT],
        ["fr"],
        ["FR"],
    )
    _write_source(
        second,
        ["fr-2", "site"],
        ["Application", "Search"],
        [
            "The court shall apply this Act to every claim filed in the territory.",
            "Home\nSearch\nContact us\nThis website uses cookies\n",
        ],
        ["fr", "fr"],
        ["FR", "FR"],
    )
    destination = tmp_path / "out" / "france"
    destination.mkdir(parents=True)
    (destination / "part-000009.parquet").write_bytes(b"stale")
    (destination / "report.json").write_text("{}\n", encoding="utf-8")
    report = fill_country_corpus(
        [first, second],
        tmp_path / "out",
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
        flush_atoms=1,
    )
    assert report["rows_read"] == 3
    assert report["atoms_written"] == 3
    assert report["atoms_with_locator"] == 2
    assert report["reasons"]["law"] == 2
    assert report["reasons"]["informative"] == 1
    assert report["corpus_complete"] is True
    assert report["source_files"] == ["part-000000.parquet", "part-000001.parquet"]
    parts = sorted(destination.glob("part-*.parquet"))
    assert [path.name for path in parts] == [
        "part-000000.parquet",
        "part-000001.parquet",
        "part-000002.parquet",
    ]
    texts = []
    for part in parts:
        texts.extend(pq.read_table(part).column("text").to_pylist())
    assert texts[0].startswith("Article 1")
    assert texts[1].startswith("Article 2")
    assert texts[2].startswith("The court shall apply")
    assert "Search" not in "\n".join(texts)
    saved = json.loads((destination / "report.json").read_text(encoding="utf-8"))
    assert saved["atoms_written"] == 3
    governorate = admit_source_law(
        _row(jurisdiction="EG", country="Egypt"),
        source_dataset="endomorphosis/ipfs_egypt_governorate_laws",
        source_revision=_SHA,
    )
    assert governorate.admitted is False
    assert governorate.reason == "not_national"
    assert governorate.records == ()
    try:
        fill_country_corpus(
            [first],
            tmp_path / "out",
            source_dataset="endomorphosis/ipfs_south_africa_provincial_laws",
            source_revision=_SHA,
        )
    except ValueError as exc:
        assert str(exc) == "not_national"
    else:
        raise AssertionError("provincial source was written")


def test_a_french_code_article_fills_when_the_body_omits_the_heading() -> None:
    prose = (
        "Les fonctionnaires promus au grade de garde champêtre chef principal "
        "sont classés à l'échelon comportant un indice égal ou, à défaut, "
        "immédiatement supérieur à celui dont ils bénéficiaient."
    )
    decision = admit_source_law(
        _row(
            id="fr-8-2",
            title="Article 8-2",
            article_number="8-2",
            language="fr",
            jurisdiction="FR",
            country="France",
            instrument_title=(
                "Décret nr. 94-731 du 24 août 1994 portant statut particulier "
                "du cadre d'emplois des gardes champêtres"
            ),
            text=prose,
        ),
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert decision.reason == "law"
    assert len(decision.records) == 1
    assert decision.records[0]["text"].startswith("Les fonctionnaires promus")
    assert decision.records[0]["provenance"]["article"] == "8-2"
    assert decision.records[0]["provenance"]["section"] == "8-2"
    assert decision.records[0]["jurisdiction"] == "FR"

    divided = admit_source_law(
        _row(
            id="fr-divided",
            title="Article 8-2",
            article_number="8-2",
            language="fr",
            jurisdiction="FR",
            country="France",
            instrument_title="Décret nr. 94-731 du 24 août 1994",
            text=(
                "Article 1 Les dispositions du présent décret s'appliquent "
                "sur tout le territoire national.\n"
                "Article 2 Les autres dispositions restent applicables "
                "aux personnes concernées par le présent texte."
            ),
        ),
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert divided.admitted is True
    assert [record["provenance"].get("article") for record in divided.records] == ["1", "2"]

    annex = admit_source_law(
        _row(
            id="fr-annex",
            title="Article Annexe",
            article_number="Annexe",
            language="fr",
            jurisdiction="FR",
            country="France",
            instrument_title="Arrêté du 20 janvier 1994 établissant les normes minimales",
            text=(
                "Les matériaux utilisés pour la construction des locaux de stabulation, "
                "et notamment des boxes et des équipements, ne doivent pas être nocifs."
            ),
        ),
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert annex.admitted is False
    assert annex.reason == "not_queryable"
    assert annex.records == ()

    shell = admit_source_law(
        _row(
            id="fr-shell",
            title="Arrêté du 25 janvier 1994 modifiant l'arrêté du 30 novembre 1988",
            language="fr",
            jurisdiction="FR",
            country="France",
            instrument_title="Arrêté du 25 janvier 1994 modifiant l'arrêté du 30 novembre 1988",
            text=(
                "Arrêté du 25 janvier 1994 modifiant l'arrêté du 30 novembre 1988 "
                "fixant l'échelonnement indiciaire. Le ministre d'Etat, ministre de "
                "la défense, arrête les dispositions suivantes."
            ),
        ),
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert shell.admitted is False
    assert shell.reason == "not_queryable"
    assert shell.records == ()


def _write_source(
    path: Path,
    ids: list[str],
    titles: list[str],
    bodies: list[str],
    languages: list[str],
    jurisdictions: list[str],
) -> None:
    count = len(ids)
    pq.write_table(
        pa.table(
            {
                "id": ids,
                "title": titles,
                "body": bodies,
                "language": languages,
                "jurisdiction": jurisdictions,
                "source_url": ["https://example.test/fr/loi"] * count,
                "article_number": [""] * count,
                "official_identifier": [""] * count,
                "source_revision": [_SHA] * count,
            }
        ),
        path,
    )


def test_fill_keeps_only_laws_and_the_plan_names_thin_sources() -> None:
    filled = fill_source_rows(
        [
            _row(),
            _row(
                id="site",
                title="Search",
                text="Home\nSearch\nContact us\nThis website uses cookies\n",
                source_url="https://example.test/search",
            ),
        ],
        source_dataset="endomorphosis/ipfs_france_laws",
        source_revision=_SHA,
    )
    assert filled["reasons"]["law"] == 1
    assert filled["reasons"]["informative"] == 1
    assert len(filled["admitted"]) == 2
    assert all(row["provenance"]["document_role"] == "law" for row in filled["admitted"])
    plan = {row["code"]: row for row in national_gap_plan({"AE": 1, "BE": 2, "FR": 400, "ZZ": 1})}
    assert plan["AE"]["action"] == "fill"
    assert plan["AE"]["source_dataset"] == "endomorphosis/ipfs_uae_laws"
    assert plan["AE"]["reason"] == "thin_docs"
    assert plan["BE"]["action"] == "skip"
    assert plan["BE"]["reason"] == "excluded"
    assert "FR" not in plan
    assert "ZZ" not in plan


def test_a_polish_section_keeps_its_sentence() -> None:
    written = "§ 1.\nSprawy należy załatwiać w formie pisemnej."
    decision = admit_source_law(
        _row(
            id="pl-1",
            title="§ 1.",
            language="pl",
            jurisdiction="PL",
            country="Poland",
            text=written,
        ),
        source_dataset="endomorphosis/ipfs_poland_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == normalize_legal_text(written)
    assert decision.records[0]["provenance"]["section"] == "1"

    suffixed = "§ 3c.\nSpółka może nabywać własne akcje."
    lettered = admit_source_law(
        _row(
            id="pl-3c",
            title="§ 3c.",
            language="pl",
            jurisdiction="PL",
            country="Poland",
            text=suffixed,
        ),
        source_dataset="endomorphosis/ipfs_poland_laws",
        source_revision=_SHA,
    )
    assert lettered.admitted is True
    assert len(lettered.records) == 1
    assert lettered.records[0]["text"] == normalize_legal_text(suffixed)
    assert lettered.records[0]["provenance"]["section"] == "3c"

    court = "Artykuł 48\nSąd składa się z 28 sędziów."
    article = admit_source_law(
        _row(
            id="pl-art48",
            title="Artykuł 48",
            language="pl",
            jurisdiction="PL",
            country="Poland",
            text=court,
        ),
        source_dataset="endomorphosis/ipfs_poland_laws",
        source_revision=_SHA,
    )
    assert article.admitted is True
    assert len(article.records) == 1
    assert article.records[0]["text"] == normalize_legal_text(court)
    assert article.records[0]["provenance"]["article"] == "48"

    quoted = "§ 2.\nRozporządzenie wchodzi w życie z dniem 1 marca 2015 r.\n”\n."
    commencement = admit_source_law(
        _row(
            id="pl-commence",
            title="§ 2.",
            language="pl",
            jurisdiction="PL",
            country="Poland",
            text=quoted,
        ),
        source_dataset="endomorphosis/ipfs_poland_laws",
        source_revision=_SHA,
    )
    assert commencement.admitted is True
    assert commencement.records[0]["text"] == normalize_legal_text(quoted)
    assert "1 marca 2015 r." in commencement.records[0]["text"]

    refused = {
        "empty": "Art. 8.",
        "repeal": "§ 36.\n(uchylony).",
        "stub": "§ 1 otrzymuje brzmienie:\n„",
        "amend": "§ 1.\nWprowadza się następujące zmiany:\na)",
        "ocr": "§ 1.\nWawn~trtnych z dnia 12 lute~o 1919 r.",
        "citation": "§ 2.\nPrzepis art. 20 § 3 stosuje się odpowiednio.",
        "letters": (
            "Artykuł 5\nWładzami Instytutu są:\n"
            "a)\nWysoka Rada,\nb)\nDyrektor Instytutu,\nc)\nRada Akademicka."
        ),
        "items": (
            "§ 1.\nOrganem samorządu pracowniczego są:\n"
            "1)\nogólne zebranie pracowników zakładu,\n"
            "2)\nzakładowy komitet pracowniczy."
        ),
        "chapter": (
            "§ 9.\nRozporządzenie obowiązuje do dnia 31 grudnia 2018 r.\n"
            "Rozdział 3\nPrzepisy końcowe."
        ),
    }
    for name, text in refused.items():
        outcome = admit_source_law(
            _row(
                id=f"pl-{name}",
                title=name,
                language="pl",
                jurisdiction="PL",
                country="Poland",
                text=text,
            ),
            source_dataset="endomorphosis/ipfs_poland_laws",
            source_revision=_SHA,
        )
        assert outcome.admitted is False, name
        assert outcome.reason == "not_queryable", name
        assert outcome.records == () or outcome.records == [], name


def test_an_indonesian_pasal_keeps_its_sentence() -> None:
    written = (
        "Pasal 11\n"
        "Klasifikasi Informasi Publik meliputi:\n"
        "a. Informasi yang wajib dibuka; dan\n"
        "b. Informasi yang dikecualikan."
    )
    decision = admit_source_law(
        _row(
            id="id-11",
            title="Pasal 11",
            language="id",
            jurisdiction="ID",
            country="Indonesia",
            text=written,
        ),
        source_dataset="endomorphosis/ipfs_indonesia_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == normalize_legal_text(written)
    assert decision.records[0]["provenance"]["article"] == "11"

    lettered_text = (
        "Pasal 3M\n"
        "Organ Badan terdiri atas:\n"
        "a. dewan pengawas; dan\n"
        "b. badan pelaksana."
    )
    lettered = admit_source_law(
        _row(
            id="id-3m",
            title="Pasal 3M",
            language="id",
            jurisdiction="ID",
            country="Indonesia",
            text=lettered_text,
        ),
        source_dataset="endomorphosis/ipfs_indonesia_laws",
        source_revision=_SHA,
    )
    assert lettered.admitted is True
    assert len(lettered.records) == 1
    assert lettered.records[0]["text"] == normalize_legal_text(lettered_text)
    assert lettered.records[0]["provenance"]["article"] == "3M"

    refused = {
        "cukup": "Pasal 26\nCukup jelas.",
        "sudah": "Pasal 67\nSudah jelas.",
        "dihapus": "Pasal 4\nDihapus.",
        "header": "Pasal 12\nSK nr. 1\nPRESIDEN\nREPUBLIK INDONESIA",
        "ellipsis": "Pasal 7\nPembangunan meliputi:\na. industri;\nc. pemasaran . . .\nd. lembaga.",
        "camel": "Pasal 123\nTindakan bagi Korporasi:\na. pengambilalihanKorporasi;\nb. pengawasan.",
        "lihat": "Pasal 3\nLihat bunyi huruf c dari konsiderans.",
        "bab": "Pasal 2\nRuang lingkup usaha mikro.\nBAB II\nPelindungan.",
        "lookalike": "Pasal 8l\nLisensi wajib bersifat non eksklusif.",
        "roman": "Pasal 2\nAsas ini meliputi:\na. adil;\ni. pelindungan.",
        "dup": "Pasal 2\nAsas ini meliputi hal.\na. adil.\na. adil.",
        "lower": "pasal 11\nKlasifikasi informasi ini meliputi hal berikut.",
        "marks": "Pasal 9\nPengawasan dilakukan\nhuk um ;;;\noleh pemerintah pusat.",
        "colon": (
            "Pasal 42\nPembinaan dilaksanakan melalui:\n"
            "a. sosialisasi;\nb. pendidikan dan penyr:luhan."
        ),
    }
    for name, text in refused.items():
        outcome = admit_source_law(
            _row(
                id=f"id-{name}",
                title=name,
                language="id",
                jurisdiction="ID",
                country="Indonesia",
                text=text,
            ),
            source_dataset="endomorphosis/ipfs_indonesia_laws",
            source_revision=_SHA,
        )
        assert outcome.admitted is False, name
        assert outcome.reason == "not_queryable", name
        assert outcome.records == () or outcome.records == [], name


def test_a_korean_commencement_keeps_its_sentence() -> None:
    written = "제1조(시행일) 이 법은 공포한 날부터 시행한다."
    decision = admit_source_law(
        _row(
            id="kr-1",
            title=written,
            language="ko",
            jurisdiction="KR",
            country="Korea",
            text=written,
        ),
        source_dataset="endomorphosis/ipfs_korea_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == normalize_legal_text(written)
    assert decision.records[0]["provenance"]["article"] == "1"

    refused = {
        "omit": "제2조부터 제15조까지 생략",
        "delete": "제14조 삭제 <2007. 12. 14.>",
        "tail": (
            "제1조(시행일) 이 법은 공포한 날부터 시행한다.\n"
            "제2조부터 제5조까지 생략"
        ),
        "ordinance": "제1조(시행일) 이 조례는 공포한 날부터 시행한다.",
    }
    for name, text in refused.items():
        outcome = admit_source_law(
            _row(
                id=f"kr-{name}",
                title=text.splitlines()[0],
                language="ko",
                jurisdiction="KR",
                country="Korea",
                text=text,
            ),
            source_dataset="endomorphosis/ipfs_korea_laws",
            source_revision=_SHA,
        )
        assert outcome.admitted is False, name
        assert outcome.records == () or outcome.records == [], name


def test_a_japanese_whole_statute_keeps_its_text_and_not_an_article_number() -> None:
    age = (
        "明治三十五年法律第五十号\n"
        "明治三十五年法律第五十号(年齢計算ニ関スル法律)\n"
        "年齢ハ出生ノ日ヨリ之ヲ起算ス\n"
        "民法第百四十三条ノ規定ハ年齢ノ計算ニ之ヲ準用ス\n"
        "明治六年第三十六号布告ハ之ヲ廃止ス"
    )
    decision = admit_source_law(
        _row(
            id="jp-age",
            title="明治三十五年法律第五十号(年齢計算ニ関スル法律)",
            language="ja",
            jurisdiction="JP",
            country="Japan",
            text=age,
        ),
        source_dataset="endomorphosis/ipfs_japan_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == normalize_legal_text(age)
    provenance = decision.records[0]["provenance"]
    assert provenance.get("section") in (None, "")
    assert provenance.get("article") in (None, "")
    assert provenance.get("heading_placement") == "whole_instrument"

    gengo = (
        "昭和五十四年法律第四十三号\n"
        "元号法\n"
        "1 元号は、政令で定める。\n"
        "2 元号は、皇位の継承があつた場合に限り改める。\n"
        "附 則 1 この法律は、公布の日から施行する。\n"
        "2 昭和の元号は、本則第一項の規定に基づき定められたものとする。"
    )
    reign = admit_source_law(
        _row(
            id="jp-gengo",
            title="元号法",
            language="ja",
            jurisdiction="JP",
            country="Japan",
            text=gengo,
        ),
        source_dataset="endomorphosis/ipfs_japan_laws",
        source_revision=_SHA,
    )
    assert reign.admitted is True
    assert reign.records[0]["text"] == normalize_legal_text(gengo)
    assert reign.records[0]["provenance"].get("section") in (None, "")
    assert reign.records[0]["provenance"].get("article") in (None, "")
    assert reign.records[0]["provenance"].get("heading_placement") == "whole_instrument"

    first_year = (
        "令和元年法律第七十四号\n"
        "令和元年特定災害関連義援金の交付を受ける権利は、差し押さえることができない。\n"
        "附 則 この法律は、公布の日から施行する。"
    )
    reiwa = admit_source_law(
        _row(
            id="jp-reiwa",
            title="令和元年特定災害関連義援金に係る差押禁止等に関する法律",
            language="ja",
            jurisdiction="JP",
            country="Japan",
            text=first_year,
        ),
        source_dataset="endomorphosis/ipfs_japan_laws",
        source_revision=_SHA,
    )
    assert reiwa.admitted is True
    assert reiwa.records[0]["text"] == normalize_legal_text(first_year)
    assert reiwa.records[0]["provenance"].get("article") in (None, "")

    abolished = (
        "昭和二十七年法律第七十九号\n"
        "教職員の除去に関する政令は、廃止する。\n"
        "附 則 この法律は、公布の日から施行する。"
    )
    repeal_act = admit_source_law(
        _row(
            id="jp-abolish-act",
            title="教職員の除去、就職禁止等に関する政令を廃止する法律",
            language="ja",
            jurisdiction="JP",
            country="Japan",
            text=abolished,
        ),
        source_dataset="endomorphosis/ipfs_japan_laws",
        source_revision=_SHA,
    )
    assert repeal_act.admitted is True
    assert repeal_act.records[0]["text"] == normalize_legal_text(abolished)

    classical = (
        "昭和六年法律第八号\n"
        "各特別会計ハ恩給支払ニ充ツベキ金額ヲ一般会計ニ繰入ルルコトヲ得"
        "国庫ノ分担スル金額ニ付亦同ジ\n"
        "附 則 本法ハ昭和六年度ヨリ之ヲ施行ス"
    )
    pension = admit_source_law(
        _row(
            id="jp-classical",
            title="昭和六年法律第八号(特別会計ノ恩給負担金ヲ一般会計ニ繰入ルルコトニ関スル法律)",
            language="ja",
            jurisdiction="JP",
            country="Japan",
            text=classical,
        ),
        source_dataset="endomorphosis/ipfs_japan_laws",
        source_revision=_SHA,
    )
    assert pension.admitted is True
    assert pension.records[0]["text"] == normalize_legal_text(classical)
    assert pension.records[0]["provenance"].get("section") in (None, "")

    scheduled = (
        "平成十二年法律第三十四号\n"
        "平成十二年四月からの年金額については、改定は、行わない。 "
        "国民年金の額 国民年金法第十六条の二\n"
        "附 則 この法律は、平成十二年四月一日から施行する。"
    )
    schedule = admit_source_law(
        _row(
            id="jp-schedule",
            title="平成十二年度における国民年金法による年金の額等の改定の特例に関する法律",
            language="ja",
            jurisdiction="JP",
            country="Japan",
            text=scheduled,
        ),
        source_dataset="endomorphosis/ipfs_japan_laws",
        source_revision=_SHA,
    )
    assert schedule.admitted is True
    assert schedule.records[0]["text"] == normalize_legal_text(scheduled)
    assert schedule.records[0]["provenance"].get("article") in (None, "")

    refused = {
        "deleted": "明治三十年法律第一号\n第五条\n削除",
        "abolished-line": "明治三十年法律第一号\n第七条\n廃止",
        "cut-off": (
            "大正四年法律第十八号\n"
            "法人ノ業務ヲ執行スル社員ハ五年以下ノ拘禁刑ニ処ス\n"
            "附 則 1 この法律は、刑法等一部改正法施行日から施行する。 "
            "ただし、次の各号に掲げる規定は、当該各号に定める日から施行する。 "
            "一 第五百九条の規定 公布の日"
        ),
        "omitted": (
            "昭和二十九年法律第百九号\n"
            "国の所有に属する物品を交換することができる。\n"
            "一 略\n"
            "附 則 この法律は、公布の日から施行する。"
        ),
        "gap": (
            "昭和二十五年法律第四十一号\n"
            "左に掲げる法律は、廃止する。\n"
            "附 則 1 この法律は、昭和二十五年四月一日から施行する。\n"
            "2 旧法による銀行は、銀行法による銀行とみなす。\n"
            "5 第三項の株主総会終結の時に任期は終了する。"
        ),
        "foreign": (
            "昭和二十二年法律第百七十号\n"
            "政府は、一般会計から特別会計に繰入金をすることができる。\n"
            "附 則 1 この法律は、日本国有鉄道法施行の日から施行する。 "
            "但し、第一条の規定は、公布の日から施行する。"
        ),
        "pasted-article": (
            "昭和六年法律第九号\n"
            "特別会計所属の営繕に要する経費は、一般会計の所属とする。\n"
            "附 則 第十四条\n"
            "本法は、昭和十九年度から施行する。"
        ),
    }
    for name, text in refused.items():
        outcome = admit_source_law(
            _row(
                id=f"jp-{name}",
                title=name,
                language="ja",
                jurisdiction="JP",
                country="Japan",
                text=text,
            ),
            source_dataset="endomorphosis/ipfs_japan_laws",
            source_revision=_SHA,
        )
        assert outcome.admitted is False, name
        assert outcome.records == (), name


def test_a_swedish_section_keeps_its_sentence() -> None:
    written = "8 § Generaldirektören är myndighetschef."
    decision = admit_source_law(
        _row(
            id="se-8",
            title=written,
            language="sv",
            jurisdiction="SE",
            country="Sweden",
            text=written,
        ),
        source_dataset="endomorphosis/ipfs_sweden_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == normalize_legal_text(written)
    assert decision.records[0]["provenance"]["section"] == "8"

    lettered = "12 a § Ärendena avgörs efter föredragning."
    numbered = admit_source_law(
        _row(
            id="se-12a",
            title=lettered,
            language="sv",
            jurisdiction="SE",
            country="Sweden",
            text=lettered,
        ),
        source_dataset="endomorphosis/ipfs_sweden_laws",
        source_revision=_SHA,
    )
    assert numbered.admitted is True
    assert numbered.records[0]["text"] == lettered
    assert numbered.records[0]["provenance"]["section"] == "12 a"

    refused = {
        "repeal": "6 § har upphävts genom förordning (1987:597).",
        "misspelled": "83 § Har uppphävts genom lag (2006:802).",
        "removed": "9 § Har utgått genom lag (2005:836).",
        "lower": "23 § dömes till böter.",
        "empty": "11 §",
        "next": (
            "8 § Generaldirektören är myndighetschef.\n"
            "9 § Myndigheten leds av en styrelse."
        ),
    }
    for name, text in refused.items():
        outcome = admit_source_law(
            _row(
                id=f"se-{name}",
                title=name,
                language="sv",
                jurisdiction="SE",
                country="Sweden",
                text=text,
            ),
            source_dataset="endomorphosis/ipfs_sweden_laws",
            source_revision=_SHA,
        )
        assert outcome.admitted is False, name
        assert outcome.records == () or outcome.records == [], name


def test_an_amharic_numbered_section_stays_one_atom() -> None:
    renewal = (
        "20. የእውቅና እድሳት ፇቃድ ስለመስጠት\n"
        "በአንቀጽ 13፣ 17፣ 18 እና 19 የተዘረዘሩት መሟላታቸውን በማረጋገጥ ኤጀንሲው\n"
        "የእውቅና ፇቃድ እድሳት ይሰጣል።"
    )
    decision = admit_source_law(
        _row(
            id="et-renewal",
            title="20. የእውቅና እድሳት ፇቃድ ስለመስጠት",
            language="am",
            jurisdiction="ET",
            country="Ethiopia",
            text=renewal,
        ),
        source_dataset="endomorphosis/ipfs_ethiopia_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == normalize_legal_text(renewal)
    provenance = decision.records[0]["provenance"]
    assert provenance.get("section") == "20"
    assert provenance.get("article") in (None, "")
    assert "አንቀጽ 13" in decision.records[0]["text"]

    duties = (
        "17. አስተዳደራዊ እርምጃ\n"
        "1) ማንኛውም ክጨርቅ የተሰራ የፊት መሸፇኛ ጭምብል ማምረት ሥራ ላይ\n"
        "የተሰማራ ሰው በዚህ መመሪያ ላይ የተደነገጉ ድንጋጌዎች በአዋጁ መሰረት\n"
        "ከማስጠንቀቂያ ጀምሮ የብቃት ማረጋገጫ ምስክር ወረቀት ሊታገድ ወይም\n"
        "ሊሰረዝ ይችላል።\n"
        "2) ማንኛውም ክጨርቅ የተሰራ የፊት መሸፇኛ ጭምብል ማምረት ሥራ ላይ\n"
        "የተሰማራ ተቋም በዚህ መመሪያ ላይ የተደነገጉ ድንጋጌዎች ከጣሰ በአዋጁ\n"
        "አንቀጽ 65 መሰረት ምርቱ ከገበያ ላይ እንዲሰበሰብ እና እንዲወገድ ይደረጋል።"
    )
    listed = admit_source_law(
        _row(
            id="et-duties",
            title="17. አስተዳደራዊ እርምጃ",
            language="am",
            jurisdiction="ET",
            country="Ethiopia",
            text=duties,
        ),
        source_dataset="endomorphosis/ipfs_ethiopia_laws",
        source_revision=_SHA,
    )
    assert listed.admitted is True
    assert len(listed.records) == 1
    assert listed.records[0]["text"] == normalize_legal_text(duties)
    assert listed.records[0]["provenance"].get("section") == "17"
    assert listed.records[0]["provenance"].get("article") in (None, "")
    assert "1)" in listed.records[0]["text"]
    assert "አንቀጽ 65" in listed.records[0]["text"]

    refused = {
        "cutoff": (
            "20. የእውቅና እድሳት ፇቃድ ስለመስጠት\n"
            "በአንቀጽ 13፣ 17፣ 18 እና 19 የተዘረዘሩት መሟላታቸውን በማረጋገጥ ኤጀንሲው\n"
            "የእውቅና ፇቃድ እድሳት ይሰጣል"
        ),
        "two_headings": (
            "1. አጭር ርዕስ\n"
            "ይህ መመሪያ የሲም ካርድ ምዝገባ መመሪያ ተብሎ ሊጠቀስ ይችላል።\n"
            "2. ትርጓሜ\n"
            "በዚህ መመሪያ ውስጥ የቃሉ ትርጉም በአዋጁ የተሰጠው ትርጉም ይሆናል።"
        ),
        "spaced": (
            "6. የ ተፇጻሚነ ት ወሰን\n"
            "ይህ መመሪያ በሁለም አገ ር አቀፌ ስፖርት ማህበራት ዘ ን ድ ተፇጻ ሚነ ት ይኖረዋል::"
        ),
        "columns": (
            "1. አጭር ርዕስ\n"
            "This directive may be cited as the Directive for the Implementation of Investment Incentives.\n"
            "ይህ መመሪያ የኢንቨስትመንት ማበረታቻን ለማስፈጸም የወጣ መመሪያ ተብሎ ሊጠቀስ ይችላል።"
        ),
        "omitted": (
            "8. ስለ ቅድመ ማሳወቅ\n"
            "ከውጭ ሀገር ወደ ሀገር ውስጥ ለሚገባ ምርት የሚከተለው መረጃ ... ይቀርባል።"
        ),
    }
    for name, text in refused.items():
        outcome = admit_source_law(
            _row(
                id=f"et-{name}",
                title=name,
                language="am",
                jurisdiction="ET",
                country="Ethiopia",
                text=text,
            ),
            source_dataset="endomorphosis/ipfs_ethiopia_laws",
            source_revision=_SHA,
        )
        assert outcome.admitted is False, name
        assert outcome.records == () or outcome.records == [], name


def test_a_croatian_article_keeps_its_sentence() -> None:
    written = (
        "Članak 223.\n"
        "Zastupnički dom može po prigovoru:\n"
        "- potvrditi stegovnu mjeru,\n"
        "- ukinuti stegovnu mjeru.\n"
        "Odluka doma je konačna."
    )
    decision = admit_source_law(
        _row(
            id="hr-223",
            title="Članak 223.",
            language="hr",
            jurisdiction="HR",
            country="Croatia",
            text=written,
        ),
        source_dataset="endomorphosis/ipfs_croatia_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == normalize_legal_text(written)
    assert decision.records[0]["provenance"]["article"] == "223"

    refused = {
        "signature": (
            "Članak 2.\n"
            "Ovaj pravilnik stupa na snagu osmoga dana.\n"
            "Klasa: 011-02/01-04/5\n"
            "Zagreb, 31. siječnja 2001."
        ),
        "empty": "Članak 8.",
        "next": (
            "Članak 4.\n"
            "U članku 13. riječi se brišu.\n"
            "Članak 5.\n"
            "Ovaj članak stupa na snagu."
        ),
    }
    for name, text in refused.items():
        outcome = admit_source_law(
            _row(
                id=f"hr-{name}",
                title=name,
                language="hr",
                jurisdiction="HR",
                country="Croatia",
                text=text,
            ),
            source_dataset="endomorphosis/ipfs_croatia_laws",
            source_revision=_SHA,
        )
        assert outcome.admitted is False, name
        assert outcome.records == () or outcome.records == [], name


def test_a_dutch_article_keeps_its_text_and_its_colon_number() -> None:
    judge = "Artikel 26\nDe rechter mag niet weigeren te beslissen."
    decision = admit_source_law(
        _row(
            id="nl-26",
            title="Artikel 26",
            language="nl",
            jurisdiction="NL",
            country="Netherlands",
            text=judge,
        ),
        source_dataset="endomorphosis/ipfs_netherlands_laws",
        source_revision=_SHA,
    )
    assert decision.admitted is True
    assert len(decision.records) == 1
    assert decision.records[0]["text"] == normalize_legal_text(judge)
    assert decision.records[0]["provenance"]["article"] == "26"
    assert decision.records[0]["provenance"]["section"] == "26"

    credit = "Artikel 4:81a\nEen kredietservicer is een rechtspersoon."
    numbered = admit_source_law(
        _row(
            id="nl-481a",
            title="Artikel 4:81a",
            language="nl",
            jurisdiction="NL",
            country="Netherlands",
            text=credit,
        ),
        source_dataset="endomorphosis/ipfs_netherlands_laws",
        source_revision=_SHA,
    )
    assert numbered.admitted is True
    assert len(numbered.records) == 1
    assert numbered.records[0]["text"] == normalize_legal_text(credit)
    assert numbered.records[0]["provenance"]["article"] == "4:81a"
    assert numbered.records[0]["provenance"]["section"] == "4:81a"

    repeal = admit_source_law(
        _row(
            id="nl-vervallen",
            title="Artikel 5",
            language="nl",
            jurisdiction="NL",
            country="Netherlands",
            text="Artikel 5\nVervallen",
        ),
        source_dataset="endomorphosis/ipfs_netherlands_laws",
        source_revision=_SHA,
    )
    assert repeal.admitted is False
    assert repeal.reason == "not_queryable"

    reserved = admit_source_law(
        _row(
            id="nl-reserved",
            title="Artikel 5:11",
            language="nl",
            jurisdiction="NL",
            country="Netherlands",
            text="Artikel 5:11\nGereserveerd.",
        ),
        source_dataset="endomorphosis/ipfs_netherlands_laws",
        source_revision=_SHA,
    )
    assert reserved.admitted is False

    pointer = admit_source_law(
        _row(
            id="nl-pointer",
            title="Artikel I",
            language="nl",
            jurisdiction="NL",
            country="Netherlands",
            text="Artikel I\nWijzigt de Wet op de accijns.",
        ),
        source_dataset="endomorphosis/ipfs_netherlands_laws",
        source_revision=_SHA,
    )
    assert pointer.admitted is False

    singular = admit_source_law(
        _row(
            id="nl-wijziging",
            title="Artikel 64",
            language="nl",
            jurisdiction="NL",
            country="Netherlands",
            text="Artikel 64\nBevat wijziging in andere regelgeving.",
        ),
        source_dataset="endomorphosis/ipfs_netherlands_laws",
        source_revision=_SHA,
    )
    assert singular.admitted is False

    pending = admit_source_law(
        _row(
            id="nl-not-in-force",
            title="Artikel VIII",
            language="nl",
            jurisdiction="NL",
            country="Netherlands",
            text="Artikel VIII\nVervallen.\nDit onderdeel is nog niet inwerking getreden",
        ),
        source_dataset="endomorphosis/ipfs_netherlands_laws",
        source_revision=_SHA,
    )
    assert pending.admitted is False

    citation = admit_source_law(
        _row(
            id="nl-citation",
            title="Toelichting",
            language="nl",
            jurisdiction="NL",
            country="Netherlands",
            text=(
                "Zie artikel 4:81a van deze wet voor de definitie van de "
                "kredietservicer en de verplichtingen die daarbij horen."
            ),
        ),
        source_dataset="endomorphosis/ipfs_netherlands_laws",
        source_revision=_SHA,
    )
    assert citation.admitted is False
