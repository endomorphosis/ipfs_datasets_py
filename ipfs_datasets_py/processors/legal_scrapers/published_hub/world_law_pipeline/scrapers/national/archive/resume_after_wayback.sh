#!/usr/bin/env bash
# SUPERSEDED (v4, 2026-10-15): the one-shot watcher relaunched everything on the first breaker close and exited
# rc=0 while items were still deferred. Use the persistent waiter instead (single instance, safe to rerun).
exec /workspace/world_law/pipeline/scrapers/national/archive/wayback_resume_loop.sh
