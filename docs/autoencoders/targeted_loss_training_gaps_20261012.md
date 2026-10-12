# LegalIR qualification after targeted loss training

The targeted-loss experiment separates two mechanisms that the earlier matched curriculum exposed: actor-span competition and condition/exception presence suppression. It keeps all four candidates and their original parent. It supplies engineering evidence for the source-span decoder, not a certification that legal meaning is preserved.

## Accuracy and rehearsal

Compare actor ranking OFF/ON against presence weights 1/2 with fixed modality weight 2. Inspect exact raw and joint IR, each facet, paired control/hard cases, optional-head false negatives and every permission-to-obligation change. The exposed 96-row rehearsal gate requires 96/96 exact for both readouts and zero permission-to-obligation errors. Passing that gate is necessary but insufficient for promotion. Repeat promising settings with multiple initialization/order seeds and a separately authored, provision-disjoint panel before selecting a default.

Actor negatives are selected from the full valid gold-compatible training domain. Inference still forms its K=8 candidate sets before applying compatibility checks. Consequently a high gold-compatible rank does not guarantee inference candidate coverage: incompatible spans may occupy the top eight. Keep raw rank, compatible rank, top-K coverage and final selection errors distinct. An inference change needs a separately matched comparison and tests for ties, padding, overlap, maximum source length and bounded candidate enumeration.

The condition/exception presence loss changes calibration as well as training gradients. Choose any threshold adjustment on a development set, freeze it, and score a separate evaluation set. Do not select thresholds on the evaluation panel or compare different weighted losses as interchangeable accuracy metrics.

## Real statutory fidelity

Use the supplied `justicedao/open-us-law-span-cache` alongside `justicedao/uscode-autoformal-span-cache` as source material with immutable dataset revisions, source citations and exact text hashes. Dataset availability does not establish independent review. Build a review queue with complete source context, definitions, cross-references, amendments and effective dates. Obtain independent annotations for modality, actor, action, conditions, exceptions, temporal scope and supported logic family; retain disagreements and unsupported or ambiguous cases.

Split by provision and related cross-reference groups before training. Deduplicate text and latent provenance across splits. Require reviewers to check the resulting formula against the source and its context; neither parser success nor a reconstructed reference proves semantic equivalence. Report supported coverage, abstention, counterexamples and critical modality errors separately from exact agreement with reviewed targets.

## Genuine latent profiles and existing decoders

The current run has configured dimension 384, disabled latent conditioning and zero encoder calls. Its placeholder parity checks are source-only controls. Inventory existing 8D, 384D and 768D encoder/decoder checkpoints by immutable model hash, encoder revision, latent normalization, training split and output schema. Preserve each existing checkpoint and its loader contract.

For each real profile, compare source-only, latent-only and joint conditioning on the same reviewed splits and training budgets. Include zero, shuffled and mismatched-latent controls. Record encoder calls and actual latent provenance. A decoder's dimension label alone is insufficient evidence that it uses the intended encoder. Test the new authoritative targeted-loss checkpoint outer schema through its own loader rather than interpreting its nested initializer as a legacy trained checkpoint.

## Logic families and Lean

Create an explicit capability matrix from the repository's actual logic-family parsers, typed ASTs, serializers and inference backends. Mark each operator and construct as supported, partially supported or unsupported for this decoder. The single-rule LegalIR span task does not establish general first-order, deontic, temporal or other family support.

Decode into a typed intermediate representation with family-specific construction constraints, checked variable binding, symbol signatures, arities and scopes. Validate syntax and round-trip the family serializer before calling a proof backend. Retain unsupported output and abstention instead of mapping it silently to a different family.

Add a reproducible LegalIR-to-Lean lowering contract with a pinned Lean toolchain and imports. Generate explicit declarations and proof obligations, reject placeholders or untrusted proof bypasses, and execute `lake build legal` in a bounded compiler job against the generated project. Record the actual command, toolchain, exit status and diagnostics. Compilation establishes type checking for that encoding; source-to-formula fidelity still requires separate reviewed evidence and counterexample checks. No Lean build or broader-family qualification is claimed by this training experiment.

## Retention and integration

Keep model weights and larger authored data in the additive Hugging Face release; keep finite public source, contracts, tests and review evidence in Git. Exclude full shared resource ledgers and private endpoint snapshots from publication. Preserve other agents' newer main changes, independent recovery branches and existing artifact identities. Any automatic checkpoint selection, deletion, broader deployment or semantic qualification requires its own measured result; this experiment performs none.
