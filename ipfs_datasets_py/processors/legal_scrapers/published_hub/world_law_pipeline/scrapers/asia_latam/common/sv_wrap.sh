#!/bin/bash
# sv_wrap.sh <exitfile> <logfile> cmd... : run cmd (resumes from its own checkpoint), append output to log, record exit code.
EXITF="$1"; LOGF="$2"; shift 2
"$@" >> "$LOGF" 2>&1
echo $? > "$EXITF"
