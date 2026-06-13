# ProveKit Backend Artifacts

This directory is the reserved package location for optional ProveKit backend
assets used by `ipfs_datasets_py.logic.zkp`.

Current status:

- Python imports do not build or download ProveKit.
- Operators should provide a `provekit-cli` binary with
  `IPFS_DATASETS_PROVEKIT_CLI` or `IPFS_DATASETS_PROVEKIT_HOME`.
- Prepared `.pkp` and `.pkv` files must be represented by a deterministic
  `provekit-artifacts.json` manifest before the ProveKit backend will prove or
  verify.
- Private witness files such as `Prover.toml` must not be stored here or
  published to IPFS.

The manifest helper lives in:

```text
ipfs_datasets_py.logic.zkp.provekit.artifacts
```

Future packaging work can place approved read-only circuit assets under this
directory, but generated proving keys and private inputs should remain outside
the source tree unless a release process explicitly approves them.

