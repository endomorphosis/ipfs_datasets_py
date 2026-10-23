"""Wave 13 per-PDF extraction child — runs ONE PDF under a hard memory cap
and writes {text, pages, meta_title} JSON to the output path.

The wave-12 in-process chain (fitz full-doc -> pdfplumber) was killed
twice by single scanned gazette PDFs (bih163713.pdf, swa203987.pdf)
whose extraction ballooned past the VM's RAM. Here the parent walker
spawns this child per file with RLIMIT_AS applied BEFORE any PDF work,
so a hostile file kills only its own extraction; the parent records
the ledger disposition `blocker_extract_fail` and moves on.

Chain (wave-12 semantics, memory-tamed):
 1. fitz, page-wise get_text (never holds all page objects).
 2. if <300 chars: pdftotext subprocess (its own memory space).
 3. if still <300 chars AND file < 8 MB: pdfplumber (the memory-risky
    step, size-gated out for the big scanned gazettes).
"""
import json, os, resource, subprocess, sys

RLIMIT_BYTES = int(os.environ.get('W13_EXTRACT_RLIMIT_MB', '1024')) << 20

def main():
    resource.setrlimit(resource.RLIMIT_AS, (RLIMIT_BYTES, RLIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (900, 900))
    pdf_path, out_path = sys.argv[1], sys.argv[2]
    size = os.path.getsize(pdf_path)
    text, pages, meta_title = '', 0, ''
    try:
        import fitz
        doc = fitz.open(pdf_path)
        pages = len(doc)
        meta_title = (doc.metadata or {}).get('title') or ''
        parts = []
        for i in range(pages):
            pg = doc.load_page(i)
            parts.append(pg.get_text())
        text = '\n'.join(parts)
        doc.close()
    except Exception as e:
        sys.stderr.write(f'fitz: {type(e).__name__}: {e}\n')
    if len(text.strip()) < 300:
        try:
            out = subprocess.run(['pdftotext', '-layout', pdf_path, '-'],
                                 capture_output=True, timeout=300)
            t2 = out.stdout.decode('utf-8', 'replace')
            if len(t2) > len(text):
                text = t2
        except Exception as e:
            sys.stderr.write(f'pdftotext: {type(e).__name__}: {e}\n')
    if len(text.strip()) < 300 and size < 8_000_000:
        try:
            import io, pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                pages = pages or len(pdf.pages)
                t = '\n'.join((pg.extract_text() or '') for pg in pdf.pages)
            if len(t.strip()) > len(text.strip()):
                text = t
        except Exception as e:
            sys.stderr.write(f'pdfplumber: {type(e).__name__}: {e}\n')
    with open(out_path, 'w') as f:
        json.dump({'text': text, 'pages': pages, 'meta_title': meta_title}, f)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
