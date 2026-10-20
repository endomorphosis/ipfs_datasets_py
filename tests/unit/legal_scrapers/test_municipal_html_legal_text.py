"""Municipal HTML chunks drop letterhead before the text is embedded."""

from ipfs_datasets_py.processors.legal_scrapers.country_laws_ir.html_legal import (
    extract_municipal_legal_text,
)


def test_italy_letterhead_is_dropped_and_circular_kept():
    html = """
    <div class="chunk-content">
      <p>AUTONOME PROVINZ BOZEN - SÜDTIROL</p>
      <p>Tel. 0471 41 78 01</p>
      <p>natur.raum@provinz.bz.it</p>
      <p>Steuernr./Mwst.Nr. 00390090215</p>
      <p>Rundschreiben der Abteilung</p>
      <p>Die Baumasse wird nach der Verordnung berechnet. Artikel 1 gilt für alle Neubauten.</p>
    </div>
    """
    text = extract_municipal_legal_text(html, "Tel. 0471 letterhead " + "x" * 500)
    assert "Tel." not in text
    assert "@" not in text
    assert "Steuernr" not in text
    assert "Rundschreiben" in text
    assert "Artikel 1" in text


def test_french_attendance_gives_way_to_the_decision():
    html = """
    <div class="chunk-content"><p>
    MAIRIE DE BESANÇON Étaient présents : Mme A, M. B, Mme C.
    Secrétaire : Dupont. Procurations de vote : Martin.
    Résumé: Le présent rapport accorde une subvention.
    Article 1 : La Ville verse 60 000 euros au Comité des Fêtes.
    </p></div>
    """
    fallback = "MAIRIE DE BESANÇON Étaient présents " + ("nom " * 80)
    text = extract_municipal_legal_text(html, fallback)
    assert "Étaient présents" not in text
    assert "Secrétaire" not in text
    assert "Résumé" in text
    assert "Article 1" in text


def test_swedish_cover_and_toc_are_dropped():
    html = """
    <div class="chunk-content">
      <p>Tierps kommun │815 80 TIERP │Telefon: 0293-21 80 00 │www.tierp.se</p>
      <p>Dokumentnamn:</p>
      <p>Diarienummer:</p>
      <p>KS/2025:537</p>
      <p>Innehållsförteckning</p>
      <p>Gemensam samverkan ................................................ 4</p>
      <p>Kommunen och civilsamhället samverkar enligt dessa principer för att stärka föreningslivet.</p>
    </div>
    """
    text = extract_municipal_legal_text(html, "Telefon www Dokumentnamn " + "y" * 400)
    assert "Telefon" not in text
    assert "www.tierp" not in text
    assert "Innehållsförteckning" not in text
    assert "........" not in text
    assert "samverkar" in text


def test_indonesian_page_number_is_removed_and_statute_kept():
    html = """
    <div class="chunk-content"><p>
    1 PERATURAN DAERAH KABUPATEN BANGGAI NOMOR 1 TAHUN 2011
    Menimbang : a. bahwa penyertaan modal daerah perlu diatur.
    Memutuskan : Menetapkan PERATURAN DAERAH TENTANG PENYERTAAN MODAL.
    </p></div>
    """
    text = extract_municipal_legal_text(html, "")
    assert not text.startswith("1 ")
    assert "PERATURAN DAERAH" in text
    assert "Menimbang" in text


def test_short_form_is_kept_when_it_is_the_instrument():
    html = '<div class="chunk-content"><p>' + ("REQUÉRANT coordonnées Nom prénom " * 30) + "</p></div>"
    fallback = "REQUÉRANT coordonnées Nom prénom " * 30
    text = extract_municipal_legal_text(html, fallback)
    assert "REQUÉRANT" in text
    assert len(text) > 200


def test_overstrip_falls_back_to_plain_text():
    html = "<div class='chunk-content'><p>Tel. 1</p><p>www.example.gov</p></div>"
    fallback = "Article 1 The council adopts the budget for the year. " * 20
    text = extract_municipal_legal_text(html, fallback)
    assert text == fallback.strip()
