# Four-width decoder generalization follow-up

Completed 740 decoder-head updates over frozen source representations. The 8D
covariance candidate worsened development loss and object fidelity and was
rejected. Both 4096D arms remained 0/12 exact on the exposed development cohort;
TRAIN-input scaling was not adopted. These experiments do not compare the
quality of different widths on a common architecture or prove convergence.

Prepared 48 TRAIN-only authored paragraphs from 90 original TRAIN rules, covering
180 clauses and 216 unique source inputs per verified local 384D/768D encoder.
Both local forward passes completed; no new 384D/768D head training is claimed.
The 8D diagnostic normalization omission is corrected; previous training and
selection were unaffected, and original evidence is preserved.

`results.json` records full control metrics, timing scopes, field counts and
explicit failed/rejected attempts. The detailed operator guide is
`docs/autoencoders/four_width_training.md`. Only an actual `lake build <Lib>`
provides Lean admission. These runs execute no Lake build or bridge-on evaluate,
grant no logic-family qualification, promote no checkpoint, and do not formalize
the Constitution. No model weights were downloaded and context remains 512.

The manifest identifies ordered gzip-tar parts. Concatenate the parts in listed
order to read the tar stream; verify each part and member against `manifest.json`.
Files are regular data members, with retained source-path aliases and symlink
metadata; do not execute archived scripts or extract over a live checkout.
The archive includes frozen executed sources, raw predictions, per-update
observations, control panels, source derivations, encoder/token receipts,
independent audits and resource terminal records. Failed attempts remain visible.

Unchanged external dependencies are referenced through the prior published
`decoder-conditioning-20261004` archive at commit
d466db01a32c419a765e5cef046991ddedc3c279. Pretrained model files and private native
backend binaries remain external. Recorded native-owner receipts are evidence;
they cannot substitute for a new live native execution capability.
