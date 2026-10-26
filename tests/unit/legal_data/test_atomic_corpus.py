"""Atomic legal units. Subsection markers stay on the parent section."""

from __future__ import annotations

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.structure import (
    normalize_legal_text,
    split_structured_units,
)
from ipfs_datasets_py.processors.legal_scrapers.world_law.atomic_corpus import (
    expand_legal_record,
    render_atomic,
)


def test_short_text_and_null_text_stay_one_row() -> None:
    kept = expand_legal_record({"entry_cid": "keep", "text": "Les lois", "provenance": {}})
    assert len(kept) == 1
    assert kept[0]["entry_cid"] == "keep"
    assert kept[0]["text"] == "Les lois"
    assert kept[0]["provenance"]["atomic"] is True
    empty = expand_legal_record(
        {"entry_cid": "null-text", "text": None, "provenance": {"content_complete": False}}
    )
    assert len(empty) == 1
    assert empty[0]["text"] is None
    assert empty[0]["entry_cid"] == "null-text"
    assert empty[0]["provenance"]["atomic"] is False
    assert empty[0]["provenance"]["content_complete"] is False


def test_chrome_only_text_is_not_an_atom() -> None:
    assert expand_legal_record({"entry_cid": "chrome", "text": "The incident id is 42", "provenance": {}}) == []


def test_parenthesized_subsections_stay_on_the_section() -> None:
    text = (
        "Title 18 Crimes\n"
        "Chapter 1 General\n"
        "Section 1 Theft of property.\n"
        "(a) first limb of the offence here.\n"
        "(b) second limb of the offence.\n"
        "Section 2 Fraud against the public revenue.\n"
    )
    atoms = expand_legal_record(
        {
            "entry_cid": "parent",
            "citation": "18 USC",
            "text": text,
            "language": "en",
            "provenance": {},
        }
    )
    assert len(atoms) == 2
    assert "first limb" in atoms[0]["text"]
    assert "second limb" in atoms[0]["text"]
    assert atoms[0]["text"].startswith("Section 1")
    assert atoms[1]["text"].startswith("Section 2")
    assert "(b)" not in atoms[1]["text"]
    assert atoms[0]["provenance"]["title"] == "18"
    assert atoms[0]["provenance"]["chapter"] == "1"
    assert atoms[0]["provenance"]["statute"] == "18 USC"
    assert atoms[0]["provenance"]["section"] == "1"
    assert atoms[0]["provenance"]["subsection"] == "a, b"
    assert atoms[1]["provenance"]["section"] == "2"
    assert "subsection" not in atoms[1]["provenance"]
    assert atoms[0]["entry_cid"] != atoms[1]["entry_cid"]
    assert atoms[0]["entry_cid"] != "parent"


def test_a_bare_numbered_list_stays_one_instrument() -> None:
    text = (
        "(1) A person commits theft if they dishonestly appropriate property.\n"
        "(2) It is immaterial whether the appropriation is made with a view to gain.\n"
    )
    atoms = expand_legal_record({"entry_cid": "parent", "text": text, "provenance": {}})
    assert len(atoms) == 1
    assert atoms[0]["entry_cid"] == "parent"
    assert "(1)" in atoms[0]["text"]
    assert "(2)" in atoms[0]["text"]
    assert atoms[0]["provenance"]["subsection"] == "1, 2"
    assert "section" not in atoms[0]["provenance"]


def test_canon_abbreviation_splits_two_canons() -> None:
    text = (
        "Can. 1 Die Canones dieses Codex betreffen allein die lateinische Kirche.\n"
        "Can. 2 Der Codex regelt die Liturgie in diesem Buch nicht.\n"
    )
    units = split_structured_units(normalize_legal_text(text), language="de")
    assert len(units) >= 2
    assert [unit.number for unit in units[:2]] == ["1", "2"]
    atoms = expand_legal_record({"entry_cid": "codex", "text": text, "language": "de", "provenance": {}})
    assert len(atoms) == 2
    assert atoms[0]["text"].startswith("Can. 1")
    assert atoms[1]["text"].startswith("Can. 2")
    assert atoms[0]["provenance"]["statute"] == "1"
    assert atoms[1]["provenance"]["statute"] == "2"
    assert atoms[0]["entry_cid"] != "codex"
    bare = split_structured_units(
        "A person can 2 days later ask the court for relief under this Act.\n"
        "The court can 3 times extend that period when the Act allows it.\n",
        language="en",
    )
    assert bare == []


def test_division_and_anhang_headings_split() -> None:
    divisions = split_structured_units(
        normalize_legal_text(
            "Division 1 Collection of tax by instalment under this Act.\n"
            "Division 2 Powers of entry and search under this Act.\n"
        ),
        language="en",
    )
    assert [unit.number for unit in divisions] == ["1", "2"]
    assert all(unit.kind == "part" for unit in divisions)
    bare = split_structured_units(
        normalize_legal_text(
            "The division of 2 parcels requires consent under this Act before either owner sells.\n"
            "The division of 3 parcels requires the same consent under this Act.\n"
        ),
        language="en",
    )
    assert bare == []
    annexes = split_structured_units(
        normalize_legal_text(
            "Anhang I Technische Vorschriften fuer diese Anlage stehen hier.\n"
            "Anhang II Weitere technische Vorschriften fuer diese Anlage.\n"
        ),
        language="de",
    )
    assert [unit.number for unit in annexes] == ["I", "II"]
    assert all(unit.kind == "section" for unit in annexes)
    sections = split_structured_units(
        normalize_legal_text(
            "القسم 3 تسري هذه الأحكام على العقود المبرمة في الإقليم.\n"
            "القسم 4 تسري هذه الأحكام على العقود الأخرى في الإقليم.\n"
        ),
        language="ar",
    )
    assert [unit.number for unit in sections] == ["3", "4"]
    assert all(unit.kind == "section" for unit in sections)
    not_a_heading = split_structured_units(
        normalize_legal_text(
            "تسري أحكام القسم 3 على كل عقد مبرم في هذا الإقليم قبل نفاذ هذا القانون.\n"
            "تسري أحكام القسم 4 على كل عقد آخر مبرم في هذا الإقليم بعد نفاذ هذا القانون.\n"
        ),
        language="ar",
    )
    assert not_a_heading == []
    subchapters = split_structured_units(
        normalize_legal_text(
            "SUBCAPÍTULO III Collection of tax by instalment under this Act.\n"
            "SUBCAPÍTULO IV Powers of entry and search under this Act.\n"
        ),
        language="es",
    )
    assert [unit.number for unit in subchapters] == ["III", "IV"]
    assert all(unit.kind == "chapter" for unit in subchapters)
    not_subchapter = split_structured_units(
        normalize_legal_text(
            "El subcapítulo de esta ley no crea un capítulo nuevo para los contratos públicos.\n"
            "El subcapítulo de esta ley tampoco crea un capítulo nuevo para los contratos privados.\n"
        ),
        language="es",
    )
    assert not_subchapter == []


def test_sampled_chrome_lines_drop_and_provisions_stay() -> None:
    article = "Article 1 The present Act applies throughout the territory and binds every person."
    chrome = (
        "Government Gazette 3 June 2011",
        "Government of Gibraltar (www.gibraltarlaws.gov.gi)",
        "Page 74 Act No.14 of 2014",
        "Act No.14 of 2014 Page 71",
        "Page 42 sur 200",
        "22 Government Gazette 28 July 2023 8156",
        "Page 54 of 1 06",
        "Partagez cette page sur vos réseaux sociaux :",
        "du Lundi au Vendredi JOURNAL OFFICIEL DE LA REPUBLIQUE D’HAITI Fritzner Beauzile",
        "to The Uganda Gazette nr. 74 Volume XCVIX dated 29th December, 2006",
        "เว็บไซตของกลุมงานราชกิจจานุเบกษาที่ https://ratchakitcha.soc.go.th",
        "PROVINCIAL GAZETTE EXTRAORDINARY, 22 MARCH 2011 nr. 2532 13",
        "14 nr. 2532 PROVINCIAL GAZETTE EXTRAORDINARY, 22 MARCH 2011",
        "People's Republic of Korea 1972 (rev. 1998) Page 3",
        "Page 2 of2",
        "Page 2 0f2",
        "To: The Hon. Frank Blas, Jr., Speaker Page 2 of 2",
        "Sommaire page",
        "Fan Page",
        "Home Page",
        "PRINTED JULY 13, 2009",
    )
    kept = (
        "(2) Notice of every such appointment shall be published in the Gazette.",
        "published in the Gazette prohibit all vessels or specified classes of vessels,",
        "de 5 à 20 ans.",
        "The Clerk shall publish notice of each appointment to a position in the Gazette",
        "“fish market” means any gazetted, licensed premises,",
        "(c) a green belt gazetted the Council; or",
        "Copyright and patent rights shall be protected by law.",
        "Provincial Gazette Extraordinary nr. 1554;",
        article,
    )
    for line in chrome:
        cleaned = normalize_legal_text(line + "\n" + article)
        assert line not in cleaned.splitlines()
        assert article in cleaned.splitlines()
    for line in kept:
        cleaned = normalize_legal_text(line + "\nArticle 2 Beta provision applies here.")
        assert line in cleaned.splitlines()


def test_second_wave_chrome_lines_drop_and_provisions_stay() -> None:
    article = "Article 1 The present Act applies throughout the territory and binds every person."
    chrome = (
        "8 Journal officiel de la République du Congo Edition spéciale nr. 3-2022",
        "Du jeudi 5 mai 2022 Journal officiel de la République du Congo 9",
        "Verificació :www.castellbisbal.cat/verificaciosignatura",
        "Document electrònic verificable a http://www.santfeliu.cat/sde",
        "st.martisa@santmartisarroca.cat 1 www.santmartisarroca.cat",
        "21 Avril 2021 JOURNAL OFFICIEL DE LA REPUBLIQUE TOGOLAISE 17",
        "18 JOURNAL OFFICIEL DE LA REPUBLIQUE TOGOLAISE 21 Avril 2021",
        "6 Section Page",
        "& Section Page",
        "Pour plus d'informations veuillez consulter le site https://www.arptc.gouv.cd/",
        "1448 - (24) I SÉRIE - NÚMERO 66",
        "LEGISLATIONS TRANSLATED INTO",
        "KENYA GAZETTE SUPPLEMENT",
        "Kenya Gazette Supplement nr. 21 (Kisumu County Acts nr. 6)",
        "Kenya Gazette Supplement nr. 2(Kisumu County Acts nr. 1)",
        "PRINTED AND PUBLISHED BY THE GOVERNMENT PRINTER, NAIROBI",
        "Published in Kenya Gazette 85",
        "Published in Kenya Gazette Vol. CXIX-nr. 85 on 30 June 2017",
        "https: //www.gob.pe/munichorrillos",
        "CS14 (page 2)",
        "Printed under the authority of the Cook Islands Parliament-2020.",
    )
    kept = (
        "au Journal officiel République du Congo.",
        "(2)All appointments under this section shall be notified in the Gazette.",
        "New. Zealand Gazette 1923 p. 519, 520 Regulations relating to the holding of",
        "Les lois sont revêtues du sceau de l’État et publiées au Journal officiel.",
        "published in the Kenya Gazette or County",
        "la Directiva N2 002-2021-PCM/SGTD URL: https://elperuano.pe/Verificador",
        "CONVOCA https://viladecans.convoca.online/",
        article,
    )
    for line in chrome:
        cleaned = normalize_legal_text(line + "\n" + article)
        assert line not in cleaned.splitlines(), line
        assert article in cleaned.splitlines()
    for line in kept:
        cleaned = normalize_legal_text(line + "\nArticle 2 Beta provision applies here.")
        assert line in cleaned.splitlines(), line


def test_third_wave_chrome_lines_drop_and_provisions_stay() -> None:
    article = "Article 1 The present Act applies throughout the territory and binds every person."
    chrome = (
        "c Law 20 of 2012 Page 5",
        "Page 6 Law 20 of 2012",
        "Gazette nr. 41 dated 17th May, 2013.",
        "68 JOURNAL OFFICIEL DE LA REPUBLIQUE DU MALI",
        "13 Décembre 2024 JOURNAL OFFICIEL DE LA REPUBLIQUE DU MALI 69",
        "Terça-Feira, 3 de Fevereiro de 2026 Série I, nr. 4 D",
        "Journal Officiel Amtsblatt",
        "326. SERIES I nr. 31",
        "Panaji, 28th October, 1976 (Karlika 6,1898l SERIES I nr. 31",
        "l:orvi UN ION GAZETTE EXTRAORDINARY, 30TH MAY, 1930.",
        "ii UNION GAZETTE EXT?AQRDINARY, 2ND JUNE, 1931.",
        "vJii UNION' GAZETTE EXTRAORDINARY, 24.th MAROH, 1932.",
        ">.XXviii UNION GAZETTE EXTRAORDINARY, liTH JUNE, 1934.",
        "10 JOURNAL OFFICIEL DE LA REPUBLIQUE ALGERIENNE nr. 19",
        "https://edicioneslegales.com.ec/ Pág. 63 de 392",
        "Regulation Citation Page",
    )
    kept = (
        "Law 3 of 2012.",
        "Ministro da Agricultura e Pescas, publicado na 2.a série do",
        "publicado na Série II do Jornal da República. recursos endógenos;",
        "(1) Mémorial 1960, page 1565.",
        "Government may, by notification in the Official Gazette, specify in this behalf;",
        "Gazette Series I nr. 3 dated 19th April, 1975 under",
        "Published in the UNION GAZETTE EXTRAORDINARY, 2ND JUNE, 1931.",
        "in the Gazette, which proclamation shall be issued by him upon",
        "Regulations. 8. The Minister may by notice in the Gazette make regulations-",
        "Art. 43. - Le présent arrêté sera publié au Journal officiel",
        "Chapitre 4 présent arrêté au Journal officiel, sont tenus de se conformer",
        "Copyright Act or under the terms of a licence from the Government of Anguilla.",
        "shall from time to time appoint by notice in the Gazette.",
        "“Registry Map” means the map or series of maps referred to in section 14;",
        "Legal Supplement Part A to the “Trinidad and Tobago Gazette’’, Vol. 39,",
        "published in the Gazette and in at least two daily newspapers",
        article,
    )
    for line in chrome:
        cleaned = normalize_legal_text(line + "\n" + article)
        assert line not in cleaned.splitlines(), line
        assert article in cleaned.splitlines()
    for line in kept:
        cleaned = normalize_legal_text(line + "\nArticle 2 Beta provision applies here.")
        assert line in cleaned.splitlines(), line


def test_armenian_czech_and_nicaragua_headings_split() -> None:
    sections = split_structured_units(
        normalize_legal_text(
            "Բաժին 2. This section applies to contracts made in the territory.\n"
            "Բաժին 3. This section applies to other contracts in the territory.\n"
        ),
        language="hy",
    )
    assert [unit.number for unit in sections] == ["2", "3"]
    assert all(unit.kind == "section" for unit in sections)
    not_section = split_structured_units(
        normalize_legal_text(
            "See բաժին 2 inside this sentence about contracts in the territory.\n"
            "See բաժին 3 inside this sentence about other contracts in the territory.\n"
        ),
        language="hy",
    )
    assert not_section == []
    parts = split_structured_units(
        normalize_legal_text(
            "ՄԱՍ III. Services covered by this part of the instrument.\n"
            "ՄԱՍ IV. Other services covered by this part of the instrument.\n"
        ),
        language="hy",
    )
    assert [unit.number for unit in parts] == ["III", "IV"]
    assert all(unit.kind == "part" for unit in parts)
    not_part = split_structured_units(
        normalize_legal_text(
            "See մաս III inside this sentence about services in the territory.\n"
            "See մաս IV inside this sentence about other services in the territory.\n"
        ),
        language="hy",
    )
    assert not_part == []
    articles = split_structured_units(
        normalize_legal_text(
            "Čl. 3 This article applies to contracts made in the municipality.\n"
            "Čl. 4 This article applies to other contracts in the municipality.\n"
        ),
        language="cs",
    )
    assert [unit.number for unit in articles] == ["3", "4"]
    assert all(unit.kind == "article" for unit in articles)
    not_article = split_structured_units(
        normalize_legal_text(
            "The clause cites čl. 3 and does not start a new article in this Act.\n"
            "The clause cites čl. 4 and does not start a new article in this Act.\n"
        ),
        language="en",
    )
    assert not_article == []
    arto = split_structured_units(
        normalize_legal_text(
            "Arto. 71. This article repeals the earlier tax provisions of this Act.\n"
            "Arto. 72. This article sets the date this Act enters into force.\n"
        ),
        language="es",
    )
    assert [unit.number for unit in arto] == ["71", "72"]
    assert all(unit.kind == "article" for unit in arto)
    not_arto = split_structured_units(
        normalize_legal_text(
            "El arto de esta ley no crea un articulo nuevo para los contratos publicos.\n"
            "El arto de esta ley tampoco crea un articulo nuevo para los contratos privados.\n"
        ),
        language="es",
    )
    assert not_arto == []


def test_belize_and_cyprus_chrome_lines_drop_and_provisions_stay() -> None:
    article = "Article 1 The present Act applies throughout the territory and binds every person."
    chrome = (
        "This edition contains a consolidation of the following laws- Page",
        "1445 Λευκωσία, Τηλ.: 22405824, Φαξ: 22303175 - www.mof.gov.cy/gpo",
    )
    kept = (
        "Act 42 of 1999.",
        "Citation. 1. These Rules may be cited as the",
        "Open 12 mid-day close 1.00 p.m.",
        "Διεύθυνση του προφίλ αγοραστή (URL): https://www.eprocurement.gov.cy",
        "Ηλεκτρονική πρόσβαση σε πληροφορίες (URL): https://www.eprocurement.gov.cy",
        "διαγωνισμού, στην ιστοσελίδα www.eprocurement.gov.cy., Λευκωσία, Κύπρος",
        article,
    )
    for line in chrome:
        cleaned = normalize_legal_text(line + "\n" + article)
        assert line not in cleaned.splitlines(), line
        assert article in cleaned.splitlines()
    for line in kept:
        cleaned = normalize_legal_text(line + "\nArticle 2 Beta provision applies here.")
        assert line in cleaned.splitlines(), line


def test_chapter_abbr_and_greek_tmima_split() -> None:
    chapters = split_structured_units(
        normalize_legal_text(
            "Ch. 59. These rules apply to the canteen of the police force.\n"
            "Ch. 109. POLICE (CANTEEN) RULES apply throughout this territory.\n"
        ),
        language="en",
    )
    assert [unit.number for unit in chapters] == ["59", "109"]
    assert all(unit.kind == "chapter" for unit in chapters)
    not_chapter = split_structured_units(
        normalize_legal_text(
            "A reference to Ch. 59 in this sentence does not open a new chapter of this Act.\n"
            "A reference to Ch. 109 in this sentence does not open a new chapter of this Act.\n"
        ),
        language="en",
    )
    assert not_chapter == []
    bare = split_structured_units(
        normalize_legal_text(
            "Ch 59 These rules apply to the canteen of the police force.\n"
            "Ch 109 These rules apply throughout this territory under the Act.\n"
        ),
        language="en",
    )
    assert bare == []
    sections = split_structured_units(
        normalize_legal_text(
            "ΤΜΗΜΑ I: ΑΝΑΘΕΤΟΥΣΑ ΑΡΧΗ για την παρούσα σύμβαση.\n"
            "ΤΜΗΜΑ II: ΑΝΤΙΚΕΙΜΕΝΟ ΤΗΣ ΣΥΜΒΑΣΗΣ για την παρούσα σύμβαση.\n"
        ),
        language="el",
    )
    assert [unit.number for unit in sections] == ["I", "II"]
    assert all(unit.kind == "section" for unit in sections)
    not_section = split_structured_units(
        normalize_legal_text(
            "Η αναθέτουσα αρχή του τμήμα I δεν ανοίγει νέα ενότητα σε αυτή τη γραμμή της σύμβασης.\n"
            "Η αναθέτουσα αρχή του τμήμα II δεν ανοίγει νέα ενότητα σε αυτή τη γραμμή της σύμβασης.\n"
        ),
        language="el",
    )
    assert not_section == []


def test_marginal_section_notes_split() -> None:
    bye_laws = split_structured_units(
        normalize_legal_text(
            "Citation. 1. The title of these Bye-Laws is the street advertisement bye-law.\n"
            "Interpretation. 2. In these Bye-Laws unless the context otherwise requires a definition.\n"
            "Penalty. 5.1 Any person who fails to comply with any of the provisions commits an offence.\n"
        ),
        language="en",
    )
    assert [unit.number for unit in bye_laws] == ["1", "2", "5.1"]
    assert all(unit.kind == "section" for unit in bye_laws)
    prohibited = split_structured_units(
        normalize_legal_text(
            "Prohibited 33. ( 1) A person shall not, without a licence, manufacture or sell liquor.\n"
            "Search 49. ( 1) A magistrate may issue a warrant where the evidence shows an offence.\n"
        ),
        language="en",
    )
    assert [unit.number for unit in prohibited] == ["33", "49"]
    assert all(unit.kind == "section" for unit in prohibited)
    months = split_structured_units(
        normalize_legal_text(
            "March 2023. The minister may publish a notice under this Act after that date.\n"
            "March 2012. The assembly passed the bill with an absolute majority under this Act.\n"
        ),
        language="en",
    )
    assert months == []
    fees = split_structured_units(
        normalize_legal_text(
            "From 0.51 to 1.0 square metres the daily fee applies under this bye-law.\n"
            "From 1.01 to 2.0 square metres the daily fee applies under this bye-law.\n"
        ),
        language="en",
    )
    assert fees == []


def test_greek_enotita_splits() -> None:
    sections = split_structured_units(
        normalize_legal_text(
            "ΕΝΟΤΗΤΑ 3 Αυτή η ενότητα εφαρμόζεται στις δημόσιες συμβάσεις.\n"
            "ΕΝΟΤΗΤΑ 4 Αυτή η ενότητα εφαρμόζεται στις άλλες συμβάσεις.\n"
        ),
        language="el",
    )
    assert [unit.number for unit in sections] == ["3", "4"]
    assert all(unit.kind == "section" for unit in sections)
    not_section = split_structured_units(
        normalize_legal_text(
            "Κατά την ενότητα 3 του παρόντος δεν ανοίγει νέα ενότητα σε αυτή τη γραμμή.\n"
            "Κατά την ενότητα 4 του παρόντος δεν ανοίγει νέα ενότητα σε αυτή τη γραμμή.\n"
        ),
        language="el",
    )
    assert not_section == []


def test_unterabschnitt_and_kerndoel_split() -> None:
    sections = split_structured_units(
        normalize_legal_text(
            "Unterabschnitt 163 Diese Vorschrift gilt fuer den Gemeindehaushalt.\n"
            "Unterabschnitt 180 Diese Vorschrift gilt fuer den anderen Ansatz.\n"
        ),
        language="de",
    )
    assert [unit.number for unit in sections] == ["163", "180"]
    assert all(unit.kind == "section" for unit in sections)
    not_section = split_structured_units(
        normalize_legal_text(
            "Der Verweis auf Unterabschnitt 163 in diesem Satz eroeffnet keinen neuen Abschnitt.\n"
            "Der Verweis auf Unterabschnitt 180 in diesem Satz eroeffnet keinen neuen Abschnitt.\n"
        ),
        language="de",
    )
    assert not_section == []
    goals = split_structured_units(
        normalize_legal_text(
            "Kerndoel 1 De leerling leert informatie te verwerven uit gesproken taal.\n"
            "Kerndoel 2 De leerling leert informatie te verwerven uit geschreven taal.\n"
        ),
        language="nl",
    )
    assert [unit.number for unit in goals] == ["1", "2"]
    assert all(unit.kind == "section" for unit in goals)
    plural = split_structured_units(
        normalize_legal_text(
            "De kerndoelen, bedoeld in dit besluit, worden voor Nederlandse taal vastgesteld.\n"
            "De kerndoelen, bedoeld in dit besluit, worden voor rekenen en wiskunde vastgesteld.\n"
        ),
        language="nl",
    )
    assert plural == []


def test_portuguese_subsecao_splits() -> None:
    sections = split_structured_units(
        normalize_legal_text(
            "SUBSEÇÃO I Das competências do conselho municipal de cultura.\n"
            "SUBSEÇÃO II Dos instrumentos de gestão do sistema municipal.\n"
        ),
        language="pt",
    )
    assert [unit.number for unit in sections] == ["I", "II"]
    assert all(unit.kind == "section" for unit in sections)
    portugal = split_structured_units(
        normalize_legal_text(
            "SUBSECÇÃO I Das competências da câmara municipal.\n"
            "SUBSECÇÃO II Dos instrumentos de gestão municipal.\n"
        ),
        language="pt",
    )
    assert [unit.number for unit in portugal] == ["I", "II"]
    assert all(unit.kind == "section" for unit in portugal)
    citation = split_structured_units(
        normalize_legal_text(
            "O regulamento cita a subseção I apenas como remissão interna do artigo.\n"
            "O regulamento cita a subseção II apenas como remissão interna do artigo.\n"
        ),
        language="pt",
    )
    assert citation == []
    plural = split_structured_units(
        normalize_legal_text(
            "As subseções deste regulamento tratam da competência municipal.\n"
            "As subseções deste regulamento tratam da gestão municipal.\n"
        ),
        language="pt",
    )
    assert plural == []


def test_jsonld_uses_record_dates_and_no_generated_clock() -> None:
    record = expand_legal_record(
        {
            "entry_cid": "parent",
            "citation": "Code civil",
            "title": "Code civil",
            "jurisdiction": "FR",
            "language": "fr",
            "published_date": "1804-03-21",
            "text": (
                "Article 1 Alpha provision applies.\n"
                "Article 2 Beta provision applies."
            ),
            "provenance": {},
        }
    )[0]
    document = render_atomic(record, "jsonld")
    assert document["@type"] == "Legislation"
    assert document["@context"] == "https://schema.org"
    assert document["datePublished"] == "1804-03-21"
    assert "dateModified" not in document
    assert document["text"].startswith("Article 1")
    assert all(isinstance(item["value"], str) for item in document["additionalProperty"])
