# Sourced by county chain scripts (2026-10-26 21:20 PDT). Disk guard: free MiB on /workspace must stay >= 46080 (45 GiB).
GUARD_MIN_MIB=10240  # lowered 2026-11-02 10:06 PST per Benjamin (10 GB fleet floor; was 20480 since 2026-10-27)
free_mib() { df -Pm /workspace | awk 'NR==2{print $4}'; }
g() { f=$(free_mib); if [ "$f" -lt "$GUARD_MIN_MIB" ]; then echo "STOP disk guard: ${f} MiB free < ${GUARD_MIN_MIB} MiB $(date)"; exit 0; fi; }
