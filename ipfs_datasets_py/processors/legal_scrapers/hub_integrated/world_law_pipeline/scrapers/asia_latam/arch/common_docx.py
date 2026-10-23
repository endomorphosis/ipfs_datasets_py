import io, re, zipfile


def docx_text(b):
    try:
        z = zipfile.ZipFile(io.BytesIO(b))
        x = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return ""
    x = re.sub(r"</w:p>", "\n", x)
    return re.sub(r"<[^>]+>", "", x).strip()
