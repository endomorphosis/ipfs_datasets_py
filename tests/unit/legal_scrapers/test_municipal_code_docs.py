"""Parsers for sedelectronica board rows and Saturnweb act types."""

from ipfs_datasets_py.processors.legal_scrapers.municipal.code_docs import (
    list_sede_board,
    parse_saturn_notices,
    parse_saturnweb_types,
    query_param,
    sede_targets,
    saturn_targets,
)

BOARD = """
<script><![CDATA[var unrelated = 1]]></script>
<table>
<tr>
<td class="class_name"><a class="doc2">
<a href="https://town.sedelectronica.es/preview-document/abc" title="Ordenanza de espacios">Aviso corto</a>
</a></td>
<td class="class_folderCode"><span>859/2025</span></td>
<td class="class_folderName"><span>Disposiciones Normativas</span></td>
<td class="class_boardCategory"><span>Ordenanzas y reglamentos</span></td>
<td class="class_description"><span>Texto de la ordenanza</span></td>
<td class="class_dateFrom"><span><span>26/08/2026</span></span></td>
</tr>
<tr><td class="class_name"><span>sin enlace</span></td></tr>
</table>
<button onclick="var wcall=wicketAjaxGet('../../?x=TOKEN',null,null, function(){});return !wcall;">
Mostrar más
</button>
"""

MORE = """
<ajax-response><component><![CDATA[
<table><tr>
<td class="class_name"><a href="/preview-document/def" title="Segunda ordenanza">Segunda</a></td>
<td class="class_folderCode"><span>1/2024</span></td>
<td class="class_folderName"><span>Disposiciones Normativas</span></td>
<td class="class_boardCategory"><span>Ordenanzas y reglamentos</span></td>
<td class="class_description"><span>Otra</span></td>
<td class="class_dateFrom"><span>01/01/2024</span></td>
</tr></table>
]]></component></ajax-response>
"""


def test_sede_board_follows_show_more_and_skips_empty_rows() -> None:
    calls: list[str] = []

    def fetch(url: str, *, ajax: bool = False) -> tuple[int, str]:
        calls.append(url)
        if ajax:
            return 200, MORE
        return 200, BOARD

    listed = list_sede_board("Town.sedelectronica.es", fetch, max_pages=4)
    assert listed["ok"] is True
    assert listed["pages"] == 2
    assert listed["more_remaining"] is False
    assert [doc["url"] for doc in listed["documents"]] == [
        "https://town.sedelectronica.es/preview-document/abc",
        "https://town.sedelectronica.es/preview-document/def",
    ]
    first = listed["documents"][0]
    assert first["title"] == "Ordenanza de espacios"
    assert first["label"] == "Aviso corto"
    assert first["expediente"] == "859/2025"
    assert first["procedure"] == "Disposiciones Normativas"
    assert first["published"] == "26/08/2026"
    assert calls[1].endswith("/?x=TOKEN")


def test_saturnweb_types_skip_the_blank_option() -> None:
    html = """
    <select>
      <option selected="selected" value="-1"></option>
      <option value="2">DELIBERA DI CONSIGLIO COMUNALE</option>
      <option value="47">VALIDIT&#192; BIENNALE</option>
    </select>
    """
    types = parse_saturnweb_types(html)
    assert types == [
        {"id": "2", "name": "DELIBERA DI CONSIGLIO COMUNALE"},
        {"id": "47", "name": "VALIDITÀ BIENNALE"},
    ]


def test_saturn_notice_row_keeps_one_record_per_publication() -> None:
    html = """
    <table>
    <tr><th>N° Albo</th></tr>
    <tr>
      <td><a href="Dettaglio.aspx?Pub=2154&amp;RicCro=1&amp;CE=crt1555"><span>423</span><br />2026</a></td>
      <td><a href="Dettaglio.aspx?Pub=2154&amp;RicCro=1&amp;CE=crt1555">23/09/2026 <br />08/10/2026</a></td>
      <td><a href="Dettaglio.aspx?Pub=2154&amp;RicCro=1&amp;CE=crt1555">DELIBERA DI GIUNTA N° 65<br/>Oggetto: <span>USO PALESTRA</span></a></td>
      <td><a href="Dettaglio.aspx?Pub=2154&amp;RicCro=1&amp;CE=crt1555">UFFICIO SEGRETERIA</a></td>
    </tr>
    </table>
    """
    page = "https://www.servizipubblicaamministrazione.it/servizi/saturnweb/Pubblicazioni.aspx?RicCro=1&CE=crt1555"
    notices = parse_saturn_notices(html, page)
    assert len(notices) == 1
    notice = notices[0]
    assert notice["pub"] == "2154"
    assert notice["number"] == "423"
    assert notice["year"] == "2026"
    assert notice["published_from"] == "23/09/2026"
    assert notice["published_until"] == "08/10/2026"
    assert notice["subject"] == "USO PALESTRA"
    assert notice["requester"] == "UFFICIO SEGRETERIA"
    assert notice["url"].endswith("Dettaglio.aspx?Pub=2154&RicCro=1&CE=crt1555")


def test_targets_use_vendor_and_ce_query() -> None:
    assert query_param("https://example/Home.aspx?Ce=prml1574", "ce") == "prml1574"
    rows = [
        {
            "qid": "Q1",
            "name": "Town",
            "code_links": [
                {"vendor": "sedelectronica", "host": "town.sedelectronica.es", "url": "https://town.sedelectronica.es/"},
                {"vendor": "saturnweb", "host": "www.servizipubblicaamministrazione.it", "url": "https://www.servizipubblicaamministrazione.it/servizi/saturnweb/Home.aspx?CE=abc1"},
            ],
        },
        {"qid": "Q2", "name": "Other", "code_links": [{"vendor": "halley", "url": "https://halleyweb.com/x"}]},
    ]
    assert sede_targets(rows) == [{"qid": "Q1", "name": "Town", "host": "town.sedelectronica.es"}]
    assert saturn_targets(rows) == [{"qid": "Q1", "name": "Town", "ce": "abc1"}]
