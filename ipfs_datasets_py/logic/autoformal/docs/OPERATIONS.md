# Operations and evidence ownership

Reusable implementation belongs in `ipfs_datasets_py.logic.autoformal` or its existing shared numerical/operational owner. Authored regression tests belong in `tests/unit/logic/autoformal`. A run directory may contain frozen inputs and observations; it must not become a second production owner.

Use the [handoff](HANDOFF.md) to choose one bounded next action and the [owner map](ARCHITECTURE.md) to reuse its current API. Inspect existing closed cohorts before creating another training, test or inference request. Stale candidates and failed requests remain evidence, not reusable launch defaults.

## Existing execution owners

- Source custody: `optimizers/logic_theorem_optimizer/autoencoder_source_lease.py`, with the original outer lease and its default300-second acquisition wait where required.
- Owned native validation: `scripts/ops/legal_ir/run_owned_validation.py`, with exact request/source pins, finite resource envelope, admitted child/process supervision, complete artifact seals and original release evidence.
- Numerical operations: existing immutable checkpoint/prepared-session owners, with a separately reviewed finite contract. Inference does not authorize training, target-prefix probes, warmup, generation or extra retries.
- Documentation installation: source-WRITE custody plus checked preimages/CAS when shared source/docs are being installed. A wait timeout before acquisition is an unapplied change, not a completed installation.

Do not replace these with artifact-local schedulers or broad process/resource queries. Retain the original failure and closure status. Unknown native/storage release remains unknown until the responsible owner supplies exact evidence; no other task may infer cleanup from a source-lease release alone.

### Nested tools and source custody

The 17-field validation request preserves the legacy `isolated_process_group` profile. Select `sampled_birth_bound_descendants` explicitly for nested native tools that create separate sessions. `ValidationResourceReservation` in the existing optimizer owner retains resource/storage custody; the existing operations launcher supervises execution and reuses the shared `logic/backends/process.py` birth/pidfd tracker. Legal preparation, review and Lean orchestration remain in `logic/autoformal`.

Attach and retain the isolated direct child before releasing its startup barrier. The tracked profile adds observed descendants outside that group to sampled RSS/process counts without counting group members twice, and retains observed identities across session changes and reparenting. This is cooperative ancestry observation, not kernel containment of unobserved escaping processes. The selected scope stays fixed for cleanup; historical group-only receipts gain no broader qualification.

Keep the original outer source READ through CLI exit and confirmation that observed groups/descendants stopped and native compute was released. On failure, use the original `owned-validation-failure-terminal/v1` emitted after the owner's `__exit__`, including its actual reservation, request hash, process observation and cleanup errors. The earlier `failure.json` cannot establish post-exit release. Retained storage and a failed qualification remain distinct from released compute.

Missing or mismatched terminal evidence, survivors, observation errors or cleanup errors leave source READ held for responsible-owner cleanup. A final custody guard must retain it even if saving or printing diagnostics fails. Source-lease release alone never establishes native or storage release.

## Documentation and migration

Maintain this module's README, handoff, architecture, training history, operations and original task backlog in place. Detailed API guides live in `docs/guides`; old handbook paths redirect here. Update one current plan instead of appending the same paragraph to several dated plans. Preserve historical task identities/dependencies and reference a precise new result rather than duplicate a complete run tree.

The single maintained [work catalog](work_catalog.json) records current owners, selected evidence and references to migration provenance. Historical migration records retain original path/hash/size, canonical destination, action and candidate/postimage identity; do not create another active ownership registry or evidence index. Relative guide links are resolved from their original location and rewritten to the canonical guide destination. Original guide and retired-plan bytes are archived before redirect installation. Historical raw/canonical hashes and absolute producer identities in retained receipts are not silently rewritten.

## Evidence and portability

The [work catalog](work_catalog.json) maps current owners to selected dated observations; [ARCHIVE.md](ARCHIVE.md) explains the preserved historical material. Large reports, checkpoints, source snapshots, raw cache rows and closed native attempts are evidence data; they do not belong in ordinary package imports or an agent's initial context. Preserve original paths where existing pinned manifests depend on them and use catalog descriptors to locate the exact bytes. A local catalog entry is not proof that untracked evidence has been published or will travel in a repository clone.

New evidence should use one explicitly configured evidence root and a versioned manifest referring to canonical implementation owners. Keep paths relative to their declared root where the existing profile supports it. If a historical profile authenticates an absolute producer path, declare that portability limit; relocating the package does not requalify its observations. Do not alter old pins merely to make a relocated path look current.

## Checks for a focused change

Validate candidate Python/JSON/Markdown and relative links without importing numerical/model/native owners. For implementation changes, run only the relevant finite cohort through the existing owner after exact source review; record planned versus actually completed cases/phases and all exclusions. A terminal progress dot is not a qualified case record. Preserve unrun negative branches explicitly.

For parent Lake work, the newer directory-alias fixture is a different transport test from the former interior-file symlink fixture. Enroll its exact current bytes and complete population before another run. A source-only optimization or successful preparation is not a native Lean build or measured speedup.

The work-catalog navigator distinguishes archived prototypes with installed canonical successors from unselected archival material in its summary. Its `--check` mode checks metadata joins as well as named paths and declared APIs. These checks do not import registered owners or qualify experiments.

The earlier `scripts/ops/legal_ir/verify_autoformal_documentation.py` is an unchanged verifier for the superseded documentation layout. Use `python ipfs_datasets_py/logic/autoformal/work_catalog.py --check` for current navigation. Its original manifests, installation records, patches and compressed evidence remain immutable history; do not run the old verifier as the current migration gate.

## Distribution packaging

The canonical module README, catalog/backlog JSON, maintained Markdown guides and
the exact `docs/history/pre-consolidation.zip` archive are declared in both
`setup.py` and `pyproject.toml`, with matching `MANIFEST.in` rules for source
distributions. The narrow patterns preserve this module's navigation resources
without including checkpoint files, runtime workspaces or arbitrary history ZIPs.

The [packaging qualification](../../../../workspace/test-logs/federal-corpus-audits/autoformal-packaging-20261020-01/qualification-summary.json) passed three new packaging controls
and two existing catalog controls. Real setuptools `build_py` copied the selected
package fixture; its source tree was then removed before catalog checking, task
lookup and component lookup. All 168 declared resource files matched, nine decoy
runtime/evidence paths were excluded, and missing installed metadata refused
without a checkout fallback. The tests import the navigator by file and never
execute package initializers or registered numerical owners.

This is a bounded packaging fixture, not a full release wheel/sdist build or an
end-to-end inference qualification. Optional historical evidence links outside the
package still require their separately retained repositories/workspaces. The test
owner recorded source, native and storage release. The regression test is
[`test_autoformal_packaging.py`](../../../../tests/unit/logic/autoformal/test_autoformal_packaging.py).
