# Request-local primary proof-gate observations

The shared scheduler attaches its existing primary proof-gate sample and final
gate status to timeout/cancellation exceptions. This is process-local bounded
diagnostic metadata, with no new ledger field, sampler call, request text or
lease authority. A cooldown can be reported without inventing a fresh sample;
the request's most recent sample is retained separately when available. The
snapshot does not cover every capacity, fairness or secondary pressure gate
and does not establish what caused host pressure. Admission formulas, pressure
thresholds, polling, cancellation and deadlines remain unchanged.

The supervisor and ordinary qualification probe expose this record separately
from post-unwind host/scheduler samples. A strict bounded projection rejects
malformed fields, unknown reasons and extra keys. Older schedulers explicitly
report an unavailable attached observation. Component tests exercise the actual
shared scheduler with controlled pressure, root/child accounting and cleanup;
the supervisor suite also executes the embedded qualification probe with an
actual native timeout. No live Docker success or benchmark score is claimed.

The datasets suite executes 121 passing tests. The joint package additionally
retains 104 passing supervisor tests, for 225 distinct tests with no skips or
failures. Fresh seal stores and exact producer/test hashes are recorded.
This change follows the frozen runtime's failed retry and cannot retroactively
provide its missing admission-time sample. A fresh archive and native run are
still required before claiming that this diagnostic path is container-qualified.
