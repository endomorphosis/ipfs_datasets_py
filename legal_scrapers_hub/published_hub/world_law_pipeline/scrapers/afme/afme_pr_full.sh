#!/bin/bash
cd /workspace/world_law/out; export ARCHIVE_LANE=afme
exec .afme_venv/bin/python -W ignore afme_pr_lexjuris.py afme/PR
