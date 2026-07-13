# MCP++ Profile G datasets provider

`ipfs_datasets_py.profile_g` is the package-import provider for the datasets
portion of MCP++ Profile G (`mcp++/risk-scheduling` version 1.0). It provides:

- strict canonical validation and CID generation for every Profile G artifact;
- contextual goal, subgoal, PlanBranch, PlanSelection, and TaskSpec validation;
- integer-only `weighted-saturated-sum-v1` risk evaluation;
- bounded SQLite-backed artifact and risk-evidence history with classification
  redaction;
- detached Ed25519 evidence, neighborhood-record, and attestation verification;
- policy-filtered neighborhood selection and distinct-DID quorum evaluation.

The MCP service exposes the Profile G operations through JSON-RPC, REST, and
native Profile E/libp2p dispatch. Mutations fail closed unless Profile C and
Profile D validators have been configured. An authenticated in-process caller
may explicitly construct `ProfileGService(trusted_local=True)`; network code
must instead inject authority and policy validators and an attestation signer.

```python
from ipfs_datasets_py.profile_g import RiskEvidenceStore, validate_profile_g_artifact
from ipfs_datasets_py.mcp_server.profile_g_service import ProfileGService

store = RiskEvidenceStore("profile-g.sqlite", signature_verifier=verify_signed_artifact)
service = ProfileGService(
    store=store,
    authority_validator=verify_profile_c,
    policy_validator=verify_profile_d,
    record_policy_filter=may_disclose_record,
    signer=local_attestation_signer,
)
```

A PlanBranch is always advisory. A TaskSpec is accepted only when its
`selection_cid` resolves to a matching PlanSelection and that selection's
authority and policy material remains valid. Neighborhood support is placement
confidence only and is never converted into execution authority.

The persistent store path used by the default server can be set with
`IPFS_DATASETS_PROFILE_G_DB`. The default is in-memory; production deployments
should set a durable path and configure the service before advertising it.
