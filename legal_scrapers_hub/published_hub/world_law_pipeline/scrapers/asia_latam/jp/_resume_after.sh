#!/bin/bash
# Waits for the current full crawl to exit, then runs one resume pass (retries error/unreachable/partial seeds with patched fallbacks).
while kill -0 3065808 2>/dev/null; do sleep 300; done
exec ./run_full.sh
