# Dirty-source extraction qualification

The final component passes 49 controls and a separate actual-default 320-file
run, followed by isolated-process replay. See [qualification.json](qualification.json)
for scope, producer hashes, commands, timings and remaining limitations.

The 320-file fixture has 160 dirty files and 20 pages, reopening the native owner
at cursor 128. It publishes one complete source/AST head. Its actual runtime
is 168.164 seconds; fresh-process replay takes 15.140 seconds. These measurements
do not establish a comparison against the earlier incomplete attempts.

All 49 controls use actual Git, AST, DuckDB and process behavior with an explicitly
injected host resource sampler. The scale and independent replay use the actual
default shared resource owner. Recorded telemetry is aggregate and may include
concurrent jobs. The API retains structural authority only.

Historical evidence is preserved under `historical/`: two intentional SIGINT
attempts, a native lease expiry with its lost-fixture limitation, a 300-second
finalization deadline with cursor 320 and no head, and setup/test-observer
failures. Prior producer bodies are distinct from the final qualification.
The callback enhancement keeps per-unit cancellation and moves live source
fences to three transaction publication checkpoints; every former default
caller continues to use the existing no-hook path.

`source-inventory.json` binds final implementation/test files; `inventory.json`
binds all retained evidence except itself. Runtime database/CAS files remain at
the persistent path recorded in the qualification and are not committed here.
