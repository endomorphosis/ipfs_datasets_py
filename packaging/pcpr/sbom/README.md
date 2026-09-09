# PCPR-054 declared-release-profile SBOMs

These files are declared SPDX-2.3 SBOMs of the Datasets *release*
profile. The core `setup.py` install_requires set is empty; that empty
set is the SBOM, not an omission. They are not a live Syft/CycloneDX
scan, not a hashed transitive graph, not a signed SLSA attestation,
and not a closed PCPR release.

- `cpython312/release.sbom.json` is the canonical declared SBOM.
- Development `requirements.txt` VCS pins remain source-checkout
  development only and are not this SBOM.
- Hash and transitive identities stay typed unavailable. Hashes are
  never invented. `filesAnalyzed` is false.

Sealed validation PATH is exactly `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin`.
