# Deterministic campaign batch generation

Implementation is complete. All 348 offline regressions and the archived
multi-batch generation/restart probe passed in one guarded capture. All 67
independent closeout checks passed. This report does not claim native training
throughput or expanded formalization.

The campaign plan can already dispatch registered jobs, but callers still have
to assemble their source projections and register every batch. The new layer
derives bounded jobs directly from the frozen source inventory, source
partitions and embedding receipt set. An existing verified v8 job supplies the
fixed registered parent, model variant, training configuration and optional
shared-target and Arrow-weight references. The generator uses the existing
registry and plan APIs, with no SQL schema change or additional writable queue.

Selection uses the frozen split assignments and successful embedding
dispositions. Physical aliases of one input share the lowest source entry CID.
Training inputs are sorted by input identity with fixed batch boundaries;
a bounded validation slice is shared across batches. Canary and holdout
members stay outside these jobs. Failed and unattempted embeddings remain in
coverage accounting. Pagination reports deferred successful members, and the
final short batch stays short. A page that exceeds its byte bound fails without
changing its membership or boundaries.

The recipe binds the exact template job, parent, variant, source roots, output
location, selection policy and generator source hash. The template transitively
binds training configuration, source guards and optional shared artifacts. The
`start_batch` and `max_batches` arguments are excluded from the recipe identity;
training and validation batch sizes remain bound. Jobs bind their global batch
ordinal and exact manifest/projection identities. Registry operation IDs remain
stable across repeated and overlapping pages. Registration happens only after
the complete selected page has passed preparation checks and all existing run
and operation identities have been checked. If registration stops partway
through, a retry reconciles the exact existing operations and creates only
missing runs. Regeneration preserves completed, running and failed run states;
it cannot authorize retrying interrupted training.

The generator's supplied resolvers read only page-selected sources and leaves.
Registered template verification also reads its own already-staged closure,
which may include records outside a later page. A producer receipt can
contain selected training records and unrelated records in the same leaf;
using the whole-leaf conversion API would unnecessarily require every source
file. The generator verifies the leaf metadata and exact selected records
without treating unavailable unselected sources as a selected-batch failure.
It rechecks earlier selected bytes after later resolver calls and verifies both
original selected paths and staged CAS copies before registration and return.
Existing output paths cannot be adopted by an unrelated run. Output-directory
aliases, changed helper source, conflicting operations and changed immutable
template bindings fail verification. These checks protect observed boundaries;
they do not make concurrent filesystem mutation atomic.

The API is `prepare_campaign_batches(owner, template_run_id, *, receipt_resolver,
source_resolver, output_root, training_batch_size=128, validation_batch_size=16,
start_batch=0, max_batches=128)`. The output root must already exist as an
absolute directory without aliases. Resolvers provide only the exact requested
leaf/source descriptors. The returned report contains recipe and page identities,
generation and plan artifact descriptors, registered job descriptors and coverage.
The generation artifact records every eligible unique input's source aliases,
split, embedding status and disposition. It is preparation evidence, not an
execution or completion receipt.

Each page is bounded to 128 jobs; each job has at most 128 training records and
256 total records. Aggregate selected receipt bytes, source bytes, job JSON
bytes and the generation manifest each have a 64 MiB limit. Caller-owned
resource admission is still required. Failed preparation may leave immutable
staged artifacts; this API performs no garbage collection or publication.

Configured targets and Arrow weights retain their exact template descriptors.
Generation verifies those bytes but does not construct new targets or qualify
their runtime membership. The report explicitly sets
`target_membership_verified=false`; configured membership is deferred to the
normal worker. A template's small target bundle must not be assumed to cover
newly generated samples. Arrow remains optional and v8 vectors remain inline.

This removes manual batch assembly and duplicate registration after restart.
Its opportunity cost is additional preparation and verification before training.
In the qualification recorded here, selection reused one decoded set of roots,
while generated jobs and plan sealing loaded them independently. Those selection
graphs were released before sealing. The later
[root-reuse change](autoencoder_campaign_root_reuse.md) retains one checked root
graph through sealing within the same call, while keeping fresh per-job
verification. Preparation cost remains separate from optimizer work. A registry
row or sealed generation manifest does not establish target
membership, native optimizer quality, source authority, or a Lean admit.

The [regression receipt](../../../workspace/test-logs/federal-corpus-audits/campaign-batches-20260926/capture-r1/tests/tests-receipt.json)
records 348 passing tests with no failures, errors or skips in 150.804655 seconds
for the pytest invocation. The 32 new cases cover deterministic overlapping
pages, partial registration and lost responses, exact dispositions, selected-only
source reads, corruption, bounds, source/output drift and preservation of prior
run states. The existing campaign-plan, campaign-coordinator, produced-projection
and receipt-set suites also passed. Test model updates are explicit injections;
the new optional-target test covers descriptor transport, with target membership
qualification deferred. The existing campaign-plan suite exercises complete
synthetic target hydration, transport and replay; it does not qualify target
membership for the newly generated archived-source batches.

The [artifact probe](../../../workspace/test-logs/federal-corpus-audits/campaign-batches-20260926/capture-r1/probe/batches-report.json)
used already archived vectors and source bytes
in an isolated registry, with an explicit synthetic checkpoint fixture. The
archived successful embeddings comprise 40 training, seven validation and four
holdout records. The probe generated training batches of 16, 16 and eight,
reused the seven validation records, and excluded the four holdout records. The
13 token-limit failures and 62,775 unattempted unique inputs remain in coverage
accounting. Repeated generation and generation after reopening the owner returned
identical reports, jobs and plan artifacts. The queued runs, template run and
checkpoint head stayed unchanged. Exact source-aware records, vector bits,
configuration, ordered roles and all 62,839 unique input dispositions were
checked against the archived inputs. There are 47 unique selected records and
61 record occurrences across the three jobs, including 21 validation occurrences.

| Preparation or inspection phase | Wall seconds |
|---|---:|
| Verify registered six-record template | 7.512900 |
| Generate and register three batches | 66.121531 |
| Inspect three registered batches | 24.464952 |
| Repeat generation in the same owner | 66.455817 |
| Repeat generation after owner restart | 65.864510 |
| Inspect after owner restart | 23.342495 |

These are individual observations of preparation and verification. They are not
a speed comparison, a per-span compiler measurement or bridge-on evaluation.
The probe used 47 unique stored samples and one probe process (recorded
`worker_count=1`, with no training dispatch), bridge names `[]`, prover evaluation
`false`, and metric disk-cache flag `0`. No bridge evaluate ran.
OS cache state was uncontrolled; no cold-run claim is made.

The generation manifest occupies 23,656,893 bytes because it records every
eligible input's disposition; the dispatch plan occupies 8,477 bytes. Repeating
the same page reused the same CAS identities. CAS deduplication avoids retaining
another copy of those artifacts, but regeneration still serializes, writes
temporary bytes and verifies all inputs. A different page has different
dispositions and a different generation artifact. This storage and preparation
cost should be profiled before scaling page width or worker count.

The [complete audit](../../../workspace/test-logs/federal-corpus-audits/campaign-batches-20260926/capture-r1/audit-receipt.json)
took 435.379912 seconds against a 600-second bound. Its 7,762 package Python files,
905 dependencies, four harness files, archived inputs and protected checkpoints
remained unchanged at the guarded boundaries. The reservation covered one CPU
slot, 1,024 MiB RAM and 700,000,000 disk bytes, including a full 500,000,000-byte
external fixture charge. Pytest removed only successful fixtures under this
run's explicitly named temporary root; ending retained fixture bytes were zero.
Earlier failed fixtures and retained claims were preserved.

The [resource release](../../../workspace/test-logs/federal-corpus-audits/campaign-batches-20260926/capture-r1/resource-release.json)
records 110,334,003 final owned bytes and 610,334,003 total charged bytes.
Reservation `f7ea1cd4cd7b439a9788888ba7a0bfa1` and scheduler lease
`9252bdb87f6f46c091f1bc68cce6a6ef` were released. Enforcement is cooperative with
sampled RSS and disk observations, not a kernel quota or continuous peak measure.

The [independent closeout](evidence/autoencoder_control_plane_plan/campaign-batches-closeout-20260926-r1.json)
reconstructed the archived vectors, record identities, generated dataset/split
identities, exact projections and recipe/job bindings using only the standard
library. It verified the full physical and unique-input census, all selected
artifacts, the captured restart results and the unchanged source/dependency
snapshot. Both child process groups had exited; the released reservation and
all 14 preexisting retained claim rows were exact at closeout. No failed
historical run was reclassified.

No new embedding inference, training, live Quack
service, production DuckLake write or Hugging Face upload is part of this
qualification. Native validation remains deferred. The Constitution remains
unformalized; only `lake build <Lib>` counts as an admit.

The subsequent [bounded preparation profile](autoencoder_campaign_batches_profile.md)
passed its guarded capture and all 33 closeout checks. Shared-root loading
consumed 60.44 of 67.29 instrumented seconds, with eight loads of each root.
The subsequent [operation-local implementation](autoencoder_campaign_root_reuse.md)
passed 682 offline tests and a guarded same-code A/B/B/A comparison. Repeated
preparation of one primed three-job page fell from a 66.324950-second median to
15.117741 seconds (4.387226×, two observations per mode), with exact artifacts
and queued state. All 47 [independent closeout checks](evidence/autoencoder_control_plane_plan/campaign-root-reuse-closeout-20260926-r2.json)
passed. This is neither first-registration nor training throughput; the
historical timings above remain unchanged.
Reuse retains current-byte checks, both-role authorization, per-job membership,
configuration bindings and final drift checks. There is no persistent or leaf
cache. The comparison establishes no per-mode memory saving or broader backend
advantage. In parallel, a complete
offline campaign package must include generation/plan/job artifacts and their
transitive source, target, weight and checkpoint closure, then prove exact
reopening. The [publication design](autoencoder_campaign_publication_plan.md)
defines the first package as a selected page plus its template dependencies;
the larger source campaign needs additional payloads. Restored original jobs
are evidence until an explicit import creates new path-bound execution identities.
Portable path remapping, the owned Quack prepared-handle adapter,
native qualification, remote publication and semantic coverage remain separate
requirements.

Related work: [immutable campaign plans](autoencoder_campaign_plan.md),
[shared-target, sparse and Arrow integration](autoencoder_campaign_workflow.md),
[control-plane plan](../plans/AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md), and
[federal-law training plan](../plans/FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md).
