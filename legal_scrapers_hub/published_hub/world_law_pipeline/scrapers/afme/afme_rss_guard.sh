#!/bin/bash
# usage: afme_rss_guard.sh <pid> : kill afme crawl python processes above 512000 KB RSS while <pid> lives
while kill -0 $1 2>/dev/null; do
  for p in $(pgrep -f "^[^ ]*python[^ ]* (-W ignore )?afme_[a-z0-9_]+\.py"); do r=$(ps -o rss= -p $p 2>/dev/null | tr -d ' '); [ -n "$r" ] && [ "$r" -gt 491520 ] && { kill $p; echo "$(date) rss_guard killed $p rss=$r" >> /workspace/world_law/out/afme/_rss_guard.log; }; done
  sleep 10
done
