#!/bin/bash
# Waits for probe.py, then full JDIH crawl (resumable via _state/done.jsonl)
cd /workspace/world_law/pipeline/scrapers/id_jdih
while pgrep -f "id_jdih/probe.py" >/dev/null; do sleep 60; done
/workspace/world_law/pipeline/venv/bin/python -W ignore jdih_crawl.py --workers 12
