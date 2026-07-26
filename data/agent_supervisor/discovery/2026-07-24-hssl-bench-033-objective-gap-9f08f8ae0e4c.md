# HSSL-BENCH-033 Objective Gap Resolution

Date: 2026-07-24
Task: HSSL-BENCH-033
Title: Close objective gap: Restore and pin the shared Leanstral endpoint and model identity
Goal: HSSL-G112 — Restore and pin the shared Leanstral endpoint and model identity
Priority: P0
Track: benchmark-remediation
Attempt: 1
Depends on: none
Missing evidence: HSSLEV1126C73
Source finding: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-24-hssl-bench-033-objective-gap-9f08f8ae0e4c.md`
Source fingerprint: `9f08f8ae0e4c34bd9f87e3cfba289fefc80295b7`
Source todo: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/objective_bundles/objective-hssl-remediation-leanstral.todo.md`
Source line: 7
Todo vector index: `/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/objective_bundles/todo_vector_index.json`
Todo vector: `b539d27fd7daba57`
Merge key: `d726ef26ce4da788`
Merge family: `objective/HSSL-G112`
Merge role: `aggregate`
Surplus group: `objective/HSSL-G112`
Candidate kind: `aggregate`
Work item count: 1
Work scope: `goal_subgoal_multi_evidence_batch`
Bundle: `objective/hssl/remediation-leanstral`
Parallel lane: `objective/hssl/remediation-leanstral`
Graph depth: 14
Parent goal: HSSL-G100
Cluster: `todo/benchmark-protocol/385e65bc`
Expected outputs: `data/agent_supervisor/discovery`,
`docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md`,
`benchmarks/logic_pipeline/runtime_env/leanstral.lock`,
`scripts/benchmarks/provision_hssl_leanstral.py`,
`tests/integration/benchmarks/logic_pipeline/test_leanstral_runtime.py`,
`ipfs_accelerate_py/test/api/test_model_manager_mcp_live.py`
Validation: `python -m pytest tests/integration/benchmarks/logic_pipeline/test_leanstral_runtime.py tests/integration/benchmarks/logic_pipeline/test_leanstral_adapter.py ipfs_accelerate_py/test/api/test_model_manager_mcp_live.py -q`
Acceptance: Objective scan filed this gap for HSSL-G112. Use evidence in
`/home/barberb/.local/share/ipfs_accelerate_py/benchmarks/hssl-20260723T235556Z/discovery/2026-07-24-hssl-bench-033-objective-gap-9f08f8ae0e4c.md`,
add code/tests/docs or child goals that prove the missing evidence terms are
covered (HSSLEV1126C73), and keep the supervisor-fed backlog aligned with the
objective heap. Refine the objective heap if the gap needs smaller child goals.

## Evidence

- `scripts.benchmarks.provision_hssl_leanstral.HSSLEV1126C73` is the stable
  executable evidence marker for the locked Leanstral shared-service identity
  and its bounded provisioning/verification boundary. The canonical lock,
  provisioning command, focused runtime tests, live model-manager/MCP discovery
  tests, objective heap, and this receipt all name the same evidence term.
- `benchmarks/logic_pipeline/runtime_env/leanstral.lock` is the canonical,
  secret-free `ipfs-accelerate.hssl-leanstral-runtime-lock.v1` identity
  contract. It fixes endpoint `http://127.0.0.1:8080/v1`, provider
  `leanstral_local`, model
  `Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4`, service
  `leanstral-119b-shared`, build `llama.cpp`, bounded health/model-list
  behavior, model-manager advertisement, MCP discovery identity, and the
  optional P2P provider/custom-port policy instead of allowing ambient defaults
  or provider/model fallback.
- `scripts/benchmarks/provision_hssl_leanstral.py` is a noninteractive
  attach-and-verify boundary for the existing supervisor-owned service. It does
  not install, start, autostart, or mutate a model service. Identity drift, an
  unreachable health endpoint, a model-list mismatch, a model-manager or MCP
  advertisement mismatch, or an unrequested provider/model substitution fails
  closed.
- Health and discovery requests are bounded by the lock's explicit timeout and
  response limits. The resulting content-addressed receipt binds the endpoint,
  provider, model, service identity, server build, and all accepted probe
  observations without serializing credentials, authorization headers, secret
  query values, or benchmark inputs.
- P2P transport is pinned to provider `leanstral_local` and custom port `19001`
  but disabled by default. If `p2p.enabled` is set in a reviewed lock, the
  verifier requires nonempty advertised and dialed IPv4 multiaddresses on that
  exact port, rejects wildcard advertisement and loopback dialing, and rejects
  provider substitution. Supplying transport evidence while P2P is disabled
  also fails closed.
- The only generation smoke input is an explicitly non-corpus proof obligation
  bounded independently of benchmark cases. Its result is retained solely as
  proof that the locked service can return a draft. Leanstral model output
  remains untrusted and cannot claim kernel acceptance, proof verification, or
  native-kernel receipt authority.
- Model-manager discovery uses `list_served_models`/`get_served_model`; MCP
  discovery uses the registered `model_list_served`/`model_get_served` tools
  through JSON-RPC. Exact and compatibility-alias lookups retain the effective
  pinned identity, unreachable calls remain bounded and invent no fallback,
  and neither surface serializes credential-bearing fields. An endpoint that
  is healthy but advertised under the wrong service, provider, model, or build
  identity is therefore ineligible for the fresh benchmark run.

## Validation

Required command:

```text
python -m pytest tests/integration/benchmarks/logic_pipeline/test_leanstral_runtime.py tests/integration/benchmarks/logic_pipeline/test_leanstral_adapter.py ipfs_accelerate_py/test/api/test_model_manager_mcp_live.py -q
```

The suite must prove canonical lock loading; strict identity agreement;
bounded, secret-safe health and model discovery; attach-only provisioning;
model-manager and MCP advertisement agreement; configured P2P address and port
enforcement; duplicate-service and fallback rejection; and the untrusted
non-corpus draft/native-kernel authority boundary.

Validation results:

- Required three-file command: 33 collected, 32 passed, 1 skipped. The skip is
  the deliberately opt-in localhost live model-list probe, gated by
  `HSSL_RUN_LEANSTRAL_LIVE=1`; the default suite exercises the same bounded
  model-manager and MCP JSON-RPC paths with injected HTTP transport and performs
  no inference.
- Focused Leanstral runtime suite: 20 passed. It covers strict lock/schema and
  secret-bearing endpoint rejection, every exact identity field, bounded
  health/model/draft calls, HTTP/model-manager/MCP parity, canonical receipt
  hashing, attach-only ownership, disabled and enabled P2P policy, successful
  custom-port dialing, and untrusted draft normalization without retained draft
  text.
- Existing Leanstral adapter suite: 8 passed. Its independent stage contract
  continues to reject proof authority and requires native-kernel validation
  outside the model lane.
- Model-manager/MCP live-contract suite: 4 passed, 1 skipped. Exact and alias
  lookups preserve the pinned effective identity, unreachable discovery fails
  closed, registered MCP list/get tools retain JSON-RPC identity parity, and
  serialized observations contain no credential fields.

## Backlog alignment

HSSL-G112 remains one cohesive shared-runtime identity goal. Endpoint
reachability, model-manager advertisement, MCP discovery, configured P2P
transport, identity agreement, and the bounded proof-draft probe all describe
and validate the same supervisor-owned service. Splitting them into child goals
could allow one discovery surface or transport to drift independently of the
canonical lock, so no smaller child goal or objective-graph refinement is
needed.

The objective heap now names HSSLEV1126C73, the canonical lock and provisioning
boundary, the identity agreement and bounded receipt contract, the optional P2P
requirements, and the untrusted model-output boundary. Generated todo-vector,
objective-bundle, and task-status metadata remain supervisor-owned and were not
edited manually. The supervisor can reconcile the backlog from todo vector
`b539d27fd7daba57`, merge key `d726ef26ce4da788`, the executable evidence
marker, canonical output paths, objective heap, this discovery receipt, and the
required validator.
