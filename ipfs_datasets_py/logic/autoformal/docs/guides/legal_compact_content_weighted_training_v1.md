# Compact LegalIR content-weighted training v1

`ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_weighted_training_v1`
provides a separate, development-only checkpoint contract for a weighted
full-vocabulary training objective. It reuses the existing compact decoder,
tensor/state validators and Adam implementation. It does not change the older
v2 trainer or its checkpoint format.

## Supported profile

The first profile is deliberately closed: the fixed 537-token codec, compact
384-dimensional conditioning, hidden size 8, projection size 4, token embedding
size 8, and the two bound authored fictional retention/inspection rows. The
required donor is the retained checkpoint with SHA-256
`a98a6244222b6379cd4669905b0d14b87e30761fe9cbc795206b16151ba69c7b`.
Its historical Adam state is provenance; each initial arm starts fresh Adam.
This is not a general corpus trainer or qualification of the source encoder,
768D or 4096D profiles.

Public grammar inventories are regenerated from the complete bound targets.
Each shifted target includes EOS; BOS is input only. Every supervised position
uses cross entropy over all 537 tokens. Forced grammar positions have weight
1; genuine choice positions have weight 1 or 4. These are the only supported
policies. The nonuniform loss is the sum of weighted token losses divided by
the sum of weights. There is no conditional allowed-set auxiliary objective.
The all-one policy uses the canonical mean cross-entropy kernel, including its
padding rule, so it can be checked for exact baseline parity.

## API and ownership

1. `policy(choice_weight=1)` and `policy_sha256(...)` select and commit a policy.
2. `create(donor, population_raw, rows, expected_donor_sha256=...,
   expected_population_sha256=..., choice_weight=...)` binds source/context/
   target bytes, conditioning, codec, runtime and objective to an initial state.
3. `inspect(...)` and `training_row(...)` validate the checkpoint and independent
   checkpoint/policy commitments without allocating a model.
4. `restore(...)` returns the canonical model and Adam optimizer after validation.
5. The caller performs a teacher-forced forward, calls `objective(...)`, then
   performs backward, global L2 clipping at 5, and one optimizer update.
6. `pack(...)` validates and serializes the one-step successor, including named
   moments and progress. It must retain the same policy and all input bindings.

`inspect`, `training_row`, `restore`, `objective` and `pack` require
`expected_checkpoint_sha256` and
`expected_policy_sha256`. Save actual serialized checkpoints and their raw-byte
commitments; restore the saved predecessor when testing resume. Later parent
hashes are provenance commitments, not an independent proof of training history.
The caller owns admission, source custody, numerical work limits, artifact
retention and cleanup. The module does not initiate forward/backward/update work,
grant authority, or launch inference.

## Qualification and limitations

The bounded qualification is recorded separately under
`artifacts/legal-ir-weighted-training-20261018-01` in the enclosing workspace.
Its enrolled roster is baseline step 1, all-one step 1, weighted steps 1 and 2,
and replay of weighted step 2 from the actual saved step-1 checkpoint: five
updates and four model/Adam allocations. Baseline parity uses the same numerical
body and mean-CE kernel, not the older public trainer's entire execution path.
Independent saved-only arithmetic must reconcile scalar losses, clipping and
Adam updates, along with complete-state parity and original cleanup receipts.

Installation and numerical mechanics do not establish improved reconstruction,
statutory meaning, held-out generalization, or Lean validity. No BOS-generation
or holdout evaluation is part of this five-update qualification. Weighted
checkpoints require their own validated inference consumer; they must not be
relabeled as older v2 checkpoints. A longer fixed comparison, including actual
generation, remains a subsequent experiment. LegalIR qualification and authority
remain false for this development profile.
