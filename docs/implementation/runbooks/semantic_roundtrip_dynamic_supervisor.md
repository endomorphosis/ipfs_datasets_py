# Semantic Round-Trip Dynamic Supervisor

This runbook projects the hand-authored semantic round-trip taskboard into the
queryable bundle-index schema consumed by
`DynamicBundleScheduler`. It does not use the objective daemon because that
daemon derives new tasks from an objective heap; this board is already the
authoritative task set.

The preparation command:

```bash
cd /var/tmp/hssl-semantic-roundtrip-20260726
PYTHONPATH=ipfs_accelerate_py:. python -m \
  benchmarks.semantic_roundtrip_scheduler prepare
```

Preparation validates every bundle/resource/provider binding, probes the exact
configured Leanstral endpoint and model, and writes these untracked runtime
artifacts under `/var/tmp/hssl-srt-dynamic-supervisor`:

- `bundles/index.json` and its queryable `index.duckdb` sidecar
- `provider_capacity.json`

The preparation receipt binds the exact taskboard bytes with a CIDv1 `raw`
CID. The provider-capacity receipt is bound with a CIDv1 `dag-json` CID over
the canonical capacity payload before its CID metadata fields are attached.
Both use the shared `ipfs_datasets_py.utils.cid_utils` multiformats helpers.

The capacity receipt binds `leanstral-local` to `max_concurrency: 1`. It
requires `/props` to report `total_slots: 1`, the exact configured
`model_alias`, and a positive `default_generation_settings.n_ctx`; it also
cross-checks `/health` and `/v1/models`. Any mismatch records the provider
unhealthy, so CPU lanes may continue while model lanes fail closed.

Inspect the planned isolated lanes without starting a supervisor:

```bash
PYTHONPATH=ipfs_accelerate_py:. python -m \
  benchmarks.semantic_roundtrip_scheduler plan --no-implement
```

Print the exact persistent launch command:

```bash
PYTHONPATH=ipfs_accelerate_py:. python -m \
  benchmarks.semantic_roundtrip_scheduler launch
```

Start only after reviewing the index, capacity receipt, and planned lanes:

```bash
PYTHONPATH=ipfs_accelerate_py:. python -m \
  benchmarks.semantic_roundtrip_scheduler launch --execute
```

`launch --execute` replaces the foreground process with the supported
`ipfs_accelerate_py.agent_supervisor.bundle_supervisor` entry point and passes
`--start --implement`. Stop it with `SIGTERM` or `Ctrl-C`; the dynamic
scheduler then stops owned children and releases their fenced leases.

Do not use `bundle_supervisor --start --once` as a dry run. A one-cycle return
does not request scheduler shutdown and therefore is not the safe planning
path. Use the `plan` command above, which deliberately omits `--start`.

Each independently parallel task must have its own `Bundle`. Provider-backed
tasks must declare:

```text
- Resource class: llm-proof-draft
- Resource stage: inference
- Provider ID: leanstral-local
- Requires provider: true
```

CPU work must use a supported class such as `cpu-small` or `cpu-medium`.
Custom labels are rejected before the index is written rather than being
silently mapped to an incompatible host class.
