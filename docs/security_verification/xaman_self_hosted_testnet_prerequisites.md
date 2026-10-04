# Xaman Self-Hosted Testnet Bridge: Prerequisites and Isolation Design

Task: `PORTAL-CXTP-155`

This document describes the isolated, self-hosted `rippled` XRPL bridge
provisioned by
`scripts/ops/security_verification/provision_xaman_self_hosted_testnet.py`.
It is the runtime counterpart of the verifier-only source candidate prepared
by `PORTAL-CXTP-154`
(`docs/security_verification/xaman_self_hosted_endpoint_rebind_candidate.md`),
which expects a local ledger bridge reachable from an Android emulator at
`ws://10.0.2.2:51235` (the host sees this as `ws://127.0.0.1:51235`).

This tool does not prove wallet security, vendor-release equivalence,
production readiness, or XRPL transaction finality. It provisions and
empirically verifies one thing: an isolated `rippled` standalone daemon with
a single reviewed, loopback-only listener and no reachable public network
path.

## Prerequisites

- Docker Engine (bridge network driver, `docker exec`, `docker inspect`, and
  `docker network create --opt com.docker.network.bridge.enable_ip_masquerade`
  support). Verified against Docker Engine 29.1.3.
- Outbound network access to pull the pinned image once, or the image
  already present locally by digest.
- No other container or network already using the fixed names
  `ipfs-datasets-portal-cxtp-155-rippled` /
  `ipfs-datasets-portal-cxtp-155-isolated-net`, and host port
  `127.0.0.1:51235` free.

## Pinned Image

The daemon image is pinned by content digest, not by a mutable tag:

```
xrpllabsofficial/xrpld@sha256:035813a8980d7fe571027b168c48ae896e3f20e361b529904235290ccdb8babf
```

This digest was resolved from the published `xrpllabsofficial/xrpld:2.2.0`
tag. The tag is recorded only as informational provenance; the digest above
is the sole authoritative reference the provisioner uses to start the
daemon. Re-pinning to a newer digest is a deliberate, reviewed change, not an
automatic `docker pull xrpllabsofficial/xrpld:latest` drift.

## Why Not Docker's `--internal` Network Flag

The obvious way to isolate a container is a Docker network created with
`--internal`. That flag was evaluated and rejected here for a specific,
verified reason: **Docker refuses to publish (`-p`) any port of a container
whose only network is `--internal`.** `docker port` and
`NetworkSettings.Ports` report `null` for every mapping in that
configuration, confirmed empirically while building this tool. An
`--internal` network would therefore make it impossible to also expose the
one reviewed host-loopback listener this bridge requires for an emulator.

Instead, the provisioner creates a private bridge network with IP
masquerading disabled:

```
docker network create --driver bridge \
  --opt com.docker.network.bridge.enable_ip_masquerade=false \
  ipfs-datasets-portal-cxtp-155-isolated-net
```

Disabling masquerade removes the daemon's NAT path to the public internet
(the data-plane egress route) while leaving Docker's normal DNAT-based port
publishing intact, so the host can still forward one specific port into the
container. Every activation run re-verifies this empirically (see
"Isolation Verification" below) rather than assuming the configuration is
correct.

## Daemon Configuration (Standalone, Self-Hosted Network ID)

The daemon always runs `rippled -a` (`--standalone`, no peers) with a
generated `rippled.cfg` that:

- Sets `[network_id] 777777` -- the same self-hosted network ID
  `SELF_HOSTED_NETWORK_ID` used by the `PORTAL-CXTP-154` source candidate.
  `777777` is not a public Mainnet (`0`), Testnet (`1`), or Devnet (`2`)
  identifier, so the candidate's own network-ID guard rejects any
  accidental connection to a real network.
- Opens exactly three server ports, and no others (no peer port, no gRPC
  port):
  - `port_rpc_admin_local` (`5005/http`) and `port_ws_admin_local`
    (`6006/ws`) bind to the container's own loopback (`ip = 127.0.0.1`,
    `admin = 127.0.0.1`). These never leave the container's network
    namespace and are reachable only via `docker exec`, used solely for the
    provisioner's own categorical health check.
  - `port_ws_public` (`6005/ws`) binds to all of the container's own
    interfaces (`ip = 0.0.0.0`) so the host can publish it. This is the
    **only** port ever published, and only as `127.0.0.1:51235` on the
    host -- the single reviewed loopback listener for an emulator.
- Ships a `validators.txt` with an empty `[validators]` section and no
  `[validator_list_sites]` / `[validator_list_keys]`. The image's *default*
  `validators.txt` configures `https://vl.ripple.com` and
  `https://vl.xrplf.org` as validator-list publishers; standalone mode needs
  no validators at all, and this tool never ships a config that names a
  public or vendor validator-list endpoint.

## Isolation Verification (Performed on Every `--activate` Run)

1. **Port publication audit** -- inspects `NetworkSettings.Ports` and
   confirms: the admin RPC and admin WebSocket ports were never published
   to the host; the one reviewed ledger-bridge port was published, and only
   to `127.0.0.1`; no port was published to any non-loopback host address.
2. **Public egress probe** -- from inside the running container, attempts a
   short-timeout outbound HTTP connection to a raw public IP literal and to
   a public/vendor XRP Testnet host, and records only a categorical
   pass/fail per target category (never the literal target string). A
   connection reaching either target fails isolation.
3. **Network isolation facts** -- confirms the network's masquerade option
   is disabled and records the driver and assigned-subnet count (the
   `--internal` flag is deliberately `false`; see above).
4. **Daemon health** -- polls the container-loopback-only admin RPC for
   `server_info` and extracts only categorical fields (`server_state`,
   `network_id`, ledger/peer booleans). The raw RPC response is discarded
   immediately after categorization and is never written to disk.

A known, disclosed boundary: Docker's embedded DNS proxy (`127.0.0.11`) runs
in the host's network namespace and can still resolve public hostnames even
when the container's own network has masquerading disabled, because
resolution itself never traverses the denied data-plane path. This tool
therefore does not claim DNS-query privacy -- only that no TCP data-plane
connection reaches a public IP literal or a public/vendor Testnet host from
inside the isolated container, which is what the egress probe verifies.

## Evidence and Redaction

- `security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/daemon-health.json`
  records only categorical daemon health: reachability, standalone/full
  state, network ID match, ledger/peer booleans, and an explicit
  `evidence_boundary` block asserting no seeds, addresses, transaction
  blobs, raw RPC responses, or endpoints were retained.
- `security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/bridge-isolation-report.json`
  records network/port/egress isolation facts, the reviewed loopback
  listener's role and port number (a fixed local test port, not a vendor or
  public endpoint), and the run's `teardown_or_retention_state`.
- Both files carry a `prohibited_claims` list and an `artifact_cid`
  (`sha256:` over the canonicalized payload) for downstream reference by the
  independent review in `PORTAL-CXTP-156`.

## CLI Usage

```
# Dry run (default): read-only Docker inspection only. Never creates a
# network or starts a container.
python scripts/ops/security_verification/provision_xaman_self_hosted_testnet.py

# Activate: provisions the isolated network and daemon, captures health and
# isolation evidence, and by default retains the daemon for follow-on
# runtime-evidence capture (PORTAL-CXTP-157).
python scripts/ops/security_verification/provision_xaman_self_hosted_testnet.py --activate

# Activate and tear down immediately after evidence capture (ephemeral run).
python scripts/ops/security_verification/provision_xaman_self_hosted_testnet.py --activate --teardown

# Tear down an existing daemon/network from a previous --activate run,
# without starting anything new.
python scripts/ops/security_verification/provision_xaman_self_hosted_testnet.py --teardown
```

## Non-Claims

This tool does not prove that the Xaman wallet is secure, that a vendor
release behaves the same way, that an XRPL transaction reached finality, or
that the XRPL Labs backend is secure. It does not claim that the Docker
network-level isolation controls here have been independently reviewed --
that review is `PORTAL-CXTP-156`'s scope, which must inspect this
configuration, the port-publication and egress-probe evidence, and the
absence of vendor fallback before any runtime-conformance trace
(`PORTAL-CXTP-157`) may be captured against this bridge.
