#!/bin/bash
cd /workspace/world_caselaw/amea; W="python3 scrapers/caselaw/wayback_generic.py"
$W --prefix www.saflii.org/za/cases/ --cc za --src amea-saflii-wb --include '/za/cases/[A-Z]+/[0-9]{4}/[0-9]+\.html$' --policy 'robots-allowed;ai-train=no;use=reference' --lang en >> logs/amea-saflii-wb.log 2>&1
$W --prefix kararlarbilgibankasi.anayasa.gov.tr/BB/ --cc tr --src amea-tr-aym-wb --include '/BB/[0-9]{4}/[0-9]+(\?Dil=)?$' --court 'Anayasa Mahkemesi (Constitutional Court of Türkiye)' --court-id tr-anayasa-mahkemesi --lang tr >> logs/amea-tr-aym-wb.log 2>&1
$W --prefix supremedecisions.court.gov.il/Home/Download --cc il --src amea-il-supreme-wb --include 'HebrewVerdicts' --court 'Supreme Court of Israel' --court-id il-supreme-court --lang he >> logs/amea-il-supreme-wb.log 2>&1
$W --prefix sjconsulta.csjn.gov.ar/sjconsulta/documentos/ --cc ar --src amea-ar-csjn-wb --include 'documentos/' --court 'Corte Suprema de Justicia de la Nación' --court-id "$(grep -o '"court_id": "ar-[^"]*corte[^"]*"' /workspace/world_courts/data/ar/ar_courthouses.jsonl | head -1 | cut -d'"' -f4)" --lang es >> logs/amea-ar-csjn-wb.log 2>&1
