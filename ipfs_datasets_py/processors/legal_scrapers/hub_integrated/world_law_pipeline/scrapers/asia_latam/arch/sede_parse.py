"""Copied (not imported: the package __init__ pulls heavy deps) from ipfs_datasets_py municipal/code_docs.py:
esPublico Gestiona board parser (_markup, _BoardParser, parse_sede_documents)."""
import re, urllib.parse
from html import unescape
from html.parser import HTMLParser

def _markup(text: str) -> str:
    """Return Wicket ajax fragments, leaving a normal HTML page intact.

    Sede pages include CDATA inside scripts. Treating every CDATA block as
    the document drops the ordenanza table.
    """
    body = text or ""
    if "<ajax-response" not in body:
        return body
    parts = re.findall(r"<!\[CDATA\[(.*?)\]\]>", body, flags=re.S)
    return "\n".join(parts) if parts else body


class _BoardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self._skip = 0
        self._row: dict[str, str] | None = None
        self._cell = ""
        self._cell_text: list[str] = []
        self._capture = False
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
            return
        if self._skip:
            return
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "tr":
            self._row = {
                "url": "",
                "title": "",
                "label": "",
                "expediente": "",
                "procedure": "",
                "category": "",
                "description": "",
                "published": "",
            }
            return
        if self._row is None:
            return
        if tag == "td":
            classes = values.get("class", "").split()
            self._cell = classes[0].lower() if classes else ""
            self._cell_text = []
        elif tag == "a" and "preview-document" in values.get("href", ""):
            self._row["url"] = values.get("href", "")
            self._row["title"] = re.sub(r"\s+", " ", values.get("title", "")).strip()
            self._capture = True
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
            return
        if self._skip or self._row is None:
            return
        if tag == "a" and self._capture:
            self._row["label"] = re.sub(r"\s+", " ", "".join(self._anchor_text)).strip()
            self._capture = False
        elif tag == "td" and self._cell:
            text = re.sub(r"\s+", " ", "".join(self._cell_text)).strip()
            field = _CELL_FIELDS.get(self._cell)
            if field and text:
                self._row[field] = text
            self._cell = ""
        elif tag == "tr":
            if self._row.get("url"):
                if not self._row["title"]:
                    self._row["title"] = self._row["label"]
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._capture:
            self._anchor_text.append(data)
        if self._cell:
            self._cell_text.append(data)


def parse_sede_documents(html: str, page_url: str) -> list[dict[str, str]]:
    parser = _BoardParser()
    try:
        parser.feed(_markup(html))
        parser.close()
    except Exception:
        return []
    documents: list[dict[str, str]] = []
    for row in parser.rows:
        absolute = urllib.parse.urljoin(page_url, row["url"])
        item = dict(row)
        item["url"] = absolute
        documents.append(item)
    return documents

