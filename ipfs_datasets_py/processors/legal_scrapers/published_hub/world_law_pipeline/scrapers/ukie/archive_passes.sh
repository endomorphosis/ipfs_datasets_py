# Sourced by run_*.sh (needs $PY, cwd = scrapers/ukie). 2026-10-18 ArchiveDeferred handling.
# archive_later_passes PLACES_FILE [MAX_PASSES]: places the archive queue left 'deferred' (429/5xx cool-down,
# requeued with a not_before in archive_deferrals) get up to MAX_PASSES (default 6) later --archive-queue passes.
# Each pass starts only once the earliest not_before is reached (`councils.py next-due`); there is no per-request
# retry or sleep inside the worker: a pass skips (requeues) anything still cooling down and moves on.
archive_later_passes() {
  _pf=$1; _max=${2:-6}; _n=0
  while [ $_n -lt $_max ]; do
    _w=$($PY councils.py next-due --places-file "$_pf") || break
    [ "$_w" = none ] && break
    echo "$(date '+%FT%T%z') archive later pass $((_n+1))/$_max: earliest deferred place due in ${_w}s"
    [ "$_w" -gt 0 ] && sleep "$_w"
    $PY -u councils.py run --archive-queue --archive-docs 8 --places-file "$_pf"
    _n=$((_n+1))
  done
  _w=$($PY councils.py next-due --places-file "$_pf")
  [ "$_w" = none ] || echo "$(date '+%FT%T%z') still deferred after $_max later passes (next due in ${_w}s): rerun the archive queue later"
}

# ukie_archive_exclusive: one ukie archive job at a time (2026-10-19). Holds an flock on
# _state/ukie_archive.lock for the rest of the calling script (fd 9) and refuses to start while any other
# councils.py run WITHOUT --no-archive (an archive-using ukie worker started without this lock) is alive.
ukie_archive_exclusive() {
  exec 9>>/workspace/world_law/staging/ukie/_state/ukie_archive.lock
  if ! flock -n 9; then echo "$(date '+%FT%T%z') another ukie archive job holds ukie_archive.lock: not starting"; exit 75; fi
  _o=$(pgrep -af "councils.py run" | grep -v -- "--no-archive" | grep -v "^$$ ")
  if [ -n "$_o" ]; then echo "$(date '+%FT%T%z') ukie archive worker already running: $_o"; exit 75; fi
}
