# Historical decoder and replay handoffs

These ten Markdown/JSON files are exact recoveries of previously committed
handoffs. Their commits are ancestors of datasets main
`795d960170214d03e2eaf4c0a13ad4eb922c5c08`, but that tree had omitted the files.
They document the experiments and contracts at their recorded dates. Statements
about pending work, current defaults, implementation compatibility, test counts,
and publication status describe those historical snapshots; they are not a new
qualification of today's runtime or models.

| Historical handoff | Original source revision | Scope |
| --- | --- | --- |
| [Decoder formats](decoder_format_handoff.md) ([JSON](decoder_format_handoff.json)) | `73db2c8f3edb9fbdfc5decb0e8f12bb4e86e10f3` | Separate family, width role, output format, task, codec and checkpoint identities. |
| [Decoder profile inventory](decoder_profile_inventory_handoff.md) ([JSON](decoder_profile_inventory_handoff.json)) | `73db2c8f3edb9fbdfc5decb0e8f12bb4e86e10f3` | Authenticated retained profiles and inventory bindings. |
| [Cell routing](cell_routing_handoff.md) ([JSON](cell_routing_handoff.json)) | `7732a5808828083afb1cd19d126d987991136375` | Independent family/dimension cells and explicit routing. |
| [Cached runtime routing](runtime_routing_handoff.md) ([JSON](runtime_routing_handoff.json)) | `7732a5808828083afb1cd19d126d987991136375` | Bounded original cached-input replay and isolation contracts. |
| [Numerical replay](numerical_replay_handoff.md) ([JSON](numerical_replay_handoff.json)) | `7732a5808828083afb1cd19d126d987991136375` | Original checkpoint replay and separate IR/surface reconstruction gaps. |

The [current progress integration guide](../../progress_integration.md) records
the later owner recovery and active interfaces. The current checkpoint hub keeps
its later Legal inference optimization and explicit profile APIs. The current
long-span source-value trainer retains subsequent learning-rate, modality and
auxiliary-loss work. Recovering these references does not replace either owner.

The numerical replay handoff deliberately used an archived UI codec to satisfy
an old checkpoint's source identity. That historical codec must stay isolated
from the modern strict complete-field UI decoder. Its retained dirty worktree is
preserved. The handoff's automatic compiler-worker compatibility limitation also
describes its historical source pair; compare the current worker helper and
resource-contract tests before drawing conclusions about current behavior.

Contextual LegalIR replay, original-text scoring, source-v2 continuation, native
768D alignment and the grouped span heads have different input and output
contracts. A successful replay or restored document does not make their weights
interchangeable. In particular, the grouped source-conditioned checkpoints do
not establish new 8D/384D/768D latent training, independent legal accuracy or
proof admission.

The restoration receipt is retained with the integration audit under
`artifacts/autoencoder-consolidation-20261006-02/historical-handoff-restoration.json`
in the parent workspace. It records each original Git blob and SHA256; the ten
recovered files themselves have not been rewritten.
