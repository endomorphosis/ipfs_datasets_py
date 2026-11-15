# Frozen reviewed-context tokenizer mapping

This public test fixture preserves the exact native mapping used in the original aggregate-context census. It is generated from the maintained fixed typed-schema vocabulary, independently of the legal-source panel. It contains no model checkpoint, learned weights, original legal text, review authority, or runtime authorization.

`frozen_native_mapping_v1.json` is unchanged: 783134 UTF-8 bytes, SHA-256 `96e2847bb5d6ba940dd9a5e3fec599a0204b4a22f6d4c4fd6ad4d250e8d4be14`. Its Unigram vocabulary has 53549 entries. The native serialization and frontend options are restored through the existing real fast-tokenizer owner; there is no vocabulary rebuilding, fitting, network loader, truncation, or padding. The owning test requires exact mapping/frontend equality, including the observed tokenizers version 0.21.4. A changed runtime must qualify its own pipeline rather than silently change this mapping.

The `origin_pipeline_sha256` field records historical provenance only. The current worker derives a fresh complete pipeline identity from its actual source and runtime. This fixture does not assert that the historical complete pipeline is the current pipeline.

The owning worker test retains the shared-json-v2 4096-token refusal and tests shared-json-v3 under the same mapping, unchanged 4096-token context bound and 65536-token source bound. It uses an inert structural backend returning abstentions; no training, model restoration, model inference, legal meaning acceptance, or native Lean qualification follows. The original failed v04 test remains recorded in `docs/autoformalization/evidence/legal-ir-v4-public-tokenizer-context-refusal-20261115.json`; it is not rewritten as success.

Native tokenizer execution remains subject to the repository's existing resource admission. This JSON is portable test data, not an executable loader or an installation request.
