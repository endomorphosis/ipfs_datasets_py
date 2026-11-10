#!/usr/bin/env bash
# Detached launcher for wayback_resume_loop.py (single instance via flock inside). Safe to rerun.
L=/workspace/world_law/staging/national/_logs/archive
cd /workspace/world_law/pipeline/scrapers/national/archive
nohup setsid /workspace/world_law/pipeline/venv/bin/python -u wayback_resume_loop.py >> $L/wayback_resume_loop.log 2>&1 < /dev/null &
echo $!
