# Legal autoformalization

This module owns the path from source-bound law text and cached spans to scoped term/entity/definition graphs and a checked Lean4 corpus. Start with the [handoff](docs/HANDOFF.md) for what is complete, what remains open and where to make the next change.

| Need | Canonical document |
| --- | --- |
| Continue the work or hand it to another coding agent | [Current status and next work](docs/HANDOFF.md) |
| Locate existing implementations and stage contracts | [Architecture and owner map](docs/ARCHITECTURE.md) |
| Plan the8D,384D,768D and genuine4096D source lanes | [Four-width delivery plan](docs/HANDOFF.md#four-source-widths) |
| Avoid repeating training and diagnostics | [Training and experiment history](docs/TRAINING_HISTORY.md) |
| Run bounded work and retain evidence consistently | [Operations](docs/OPERATIONS.md) |
| Find current owners and selected evidence | [Work catalog](docs/work_catalog.json) |
| Find original reports, retired plans and migration provenance | [Archive and migration map](docs/ARCHIVE.md) |
| Inspect the existing task records | [Backlog](docs/BACKLOG.json) |

The [work catalog](docs/work_catalog.json) is the single maintained owner/evidence index; [BACKLOG.json](docs/BACKLOG.json) holds the original 24 whole task records. Run `python ipfs_datasets_py/logic/autoformal/work_catalog.py --component definition-use-native` for one owner, `--tasks` for compact task output or `--task LIR-14` for one task, from the repository root. Full historical task records remain available in that one backlog; do not load the complete file into an agent's context by default. Task-level API guides live in [docs/guides](docs/guides/). Shared numerical training engines remain with their existing optimizer owners. The six [experimental profile adapters](docs/guides/experimental_autoencoder_profiles.md) and [parent native extension](docs/guides/legal_corpus_definition_use_native_v2.md#literal-parent-conditional-native-profile) are maintained here, with retained focused migration engineering qualification. Their checkpoint replay, runtime availability and statutory qualifications remain separate. They introduce no new default runtime or generic numerical backend.

New reusable LegalIR code belongs in this package, with regression tests in `tests/unit/logic/autoformal`. Update these documents in place. Dated run directories hold observations and frozen inputs; they are not alternative production implementations. A prepared graph, authenticated review or successful Lean compilation grants only the authority explicitly recorded by that stage.
