# OCR / PDF deepen pass results

**Date:** 2026-09-04 (PT)  
**Pipeline:** `pdf_extract_lib.py` (pdfplumber → pymupdf → pdftotext → tesseract OCR) + honest heading splits (≥2 matches)  
**Mode:** SERIALIZED after RAM pressure (one country, `OMP_THREAD_LIMIT=1`, OCR dpi=120)  
**Order:** FJ → LA → LK → ET → SV → TN  

## Results table

| CC | Before L/A (staging/live approx) | After L/A | OCR count | Uploaded | URL | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| FJ | 38/444 live | **37/444** | 8 (this pass) | yes | https://huggingface.co/datasets/endomorphosis/ipfs_fiji_laws | Text deepen on updates PDFs; Hindi garbage constitution quarantined (justified −1 law) |
| LA | 2/0 not uploaded (junk) | **8/198** | 8 | yes (created) | https://huggingface.co/datasets/endomorphosis/ipfs_laos_laws | Site-chrome/annex quarantined; OCR lao+eng gazette PDFs; honest Article/ມາດຕາ |
| LK | 8/33 live | **15/66** | 12 meta / 6 deepen | yes | https://huggingface.co/datasets/endomorphosis/ipfs_srilanka_laws | documents.gov.lk / parliament.lk; OCR image-heavy Acts |
| ET | 64/80 staging · 58/19 live | **64/88** | 8 used / 1 meta | yes | https://huggingface.co/datasets/endomorphosis/ipfs_ethiopia_laws | Negarit/MoJ reextract + amh+eng OCR; Article/አንቀጽ splits where honest |
| SV | 106/5770 staging · 26/642 live | **106/6172** | 5 this pass / 19 meta | yes | https://huggingface.co/datasets/endomorphosis/ipfs_elsalvador_laws | Asamblea/Diario OCR (spa+eng); Art. splits; prior historical garbage quarantine retained |
| TN | 248/12908 staging · 41/21 live | **388/20181** | 0 this serial pass (prior OCR elsewhere) | yes | https://huggingface.co/datasets/endomorphosis/ipfs_tunisia_laws | Major honest الفصل/المادة resplits (+ fasl_inline); JORT reextract; 14 PNG junk quarantined earlier |

## Per-country detail

### FJ
- Report: `legal-corpora/fj/raw/ocr_deepen_report.json` — updated_text=16, ocr_used=8, arts retained 444
- Quarantine: Hindi constitution scan (`fj_hindi_garbage_scan`)

### LA
- Collector: `scrapers/deepen_la_ocr.py` — ok=8, ocr_used=8, arts=198
- Quarantined prior junk: `la-73._11.12.2024`, `la-4645_-1` (site chrome / annex)

### LK
- Instruments grew via `collect_lk.py` then `ocr_deepen_pass.py` (OCR×6 deepen)
- Constitution + Acts; many short Acts still lack ≥2 Section heads (honest — not invented)

### ET
- Text improved on 14 PDFs; OCR forced when native encoding/split weak
- Arts 80→88; many gazettes still lack line-start Article markers after extract

### SV
- Arts 5770→6172; thin Asamblea PDFs OCR’d (spa+eng)
- Large decretos without Art. headings left unsplit (honest)

### TN
- Biggest gain from applying honest fasl splits to existing JO text (30+ resplits this pass)
- Laws 248→388 / arts 12908→20181 (instruments already present; packaging now includes full set with splits)
- README Snapshot matches parquet (388 / 20181)

## Constraints honored
- Official / Wayback-of-official only; no WAF bypass; no cylaw; no WARC dumps
- Honest splits only (≥2 heading matches)
- Did not touch IS / SN / RW / UG; did not expand FI/HR/SK
- Disk free remained ≫20G (~108G)
- Serialized after RAM kill; single tesseract (`OMP_THREAD_LIMIT=1`)

## Scripts / logs
- `scrapers/ocr_deepen_pass.py`, `scrapers/deepen_la_ocr.py`, `scrapers/pdf_extract_lib.py`
- Logs: `logs/ocr_deepen_*_serial.log`, `logs/deepen_la_ocr_serial.log`, `logs/upload_*_ocr.log`
