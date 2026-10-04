# Native AST printable text validation

The sole production change replaces per-character Python iteration with the
built-in whole-string printable check after the existing exact-string gate.
The explicit nonempty condition preserves allowed-empty fields. Type, empty,
surrounding whitespace, length, NFC, control and internal-whitespace rejection
order remains unchanged. The internal-whitespace loop is not modified. No
serialized identity, source/proof gate, cache or scheduler policy changes.

All 237 focused tests pass with zero failures, errors or skips and unchanged
source/test pins. The 148 new cases include one exhaustive loop comparing the
ordered validator to its released implementation for all 1,114,112 Unicode code
points embedded between printable characters. Other cases cover exact-string
subclass rejection, allowed empty strings, normalization, Unicode controls,
surrogates, noncharacters and competing errors. Existing native AST/frontend
and persistent-store controls account for the remaining 89 cases.

Six untraced fresh subprocesses compare the exact archived 28b4a43c owner with
the new owner, using the same pinned public Bottle source. An explicit pre-import
hook selects the archived owner without rewriting a checkout. Each subprocess
constructs an actual ASTRecord, measures from_dict reconstruction, persists it
in its own native file-backed DuckDB, closes the connection and measures a fresh
connection read with canonical relational reconstruction. All six retain exact
payload bytes/CID parity and unchanged producer pins.

Three samples per mode give median from_dict CPU 0.171803 to 0.149861 seconds
(12.77% lower), wall 0.166682 to 0.142109 seconds (14.74% lower). Reopened store
read CPU is 0.769129 to 0.750952 seconds (2.36% lower), wall 0.769174 to 0.751402
seconds (2.31% lower). Persistence CPU instead rises 2.225285 to 2.248488 seconds
(1.04%); there is no demonstrated overall publication improvement. These small
host component observations establish neither a general speedup nor a Docker,
full-task, token-efficiency, RSS or admission-recovery result. The databases are
fresh per process; content memo state is process-local and the read follows that
process's extraction/persistence. This is not a cold OS-cache experiment.

Exact scripts/commands/exits, before/final source snapshots, test reports and the
public source fixture are retained. Private DuckDB stores, model weights,
credentials and hidden benchmark verifier bodies are excluded. The separate
pending Docker generation must establish its own result under unchanged limits.
