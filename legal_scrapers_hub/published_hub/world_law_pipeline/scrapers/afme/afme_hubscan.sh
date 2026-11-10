#!/bin/bash -l
# login shell so HF_TOKEN is in env (never printed). Detached, checkpointed.
cd /workspace/world_law/out; export ARCHIVE_LANE=afme
exec /workspace/world_law/pipeline/venv/bin/python -u afme_hubscan.py
