"""Explicit, solver-free replay allowance for the reviewed uncontained @1 generation.

This does not upgrade or rewrite an old sidecar. Its recorded process observations
remain historical claims with their original limits and authority. Only the exact
reviewed producer and dependency inventory is accepted, and semantic dependencies
must still have those bytes in the loaded current implementation.
"""
from __future__ import annotations

from typing import Any
from .content import canonical_dag_json_bytes

LEGACY_VERIFICATION_SCHEMA = "codebase-conditional-verification@1"
LEGACY_VERIFICATION_PROFILE = "current-python-int-bool-native-smt@1"
LEGACY_APPLICABILITY_SCHEMA = "codebase-input-applicability@1"
LEGACY_APPLICABILITY_PROFILE = "current-python-int-bool-domain-applicability@1"
# Captured before the contained transport upgrade; no dynamically learned trust.
_REVIEWED_PINS = (('ipfs_datasets_py.logic.software_contracts.codebase_verification',
  '9d735f56c3624dfaf9bd3ffbabc107ea6118057bfc85d8787b13077382cc6eb3'),
 ('ipfs_datasets_py.logic.software_contracts.codebase_integer_profile',
  '9baf67451294b29b7c9e205477293246b1dde46f6d4bebe627a4e3145832acf3'),
 ('ipfs_datasets_py.logic.software_verification.pipeline',
  '97048ce560b367b4651def82dcb345d3ee34edc60373c15dbaba551ca459e9da'),
 ('ipfs_datasets_py.logic.software_verification.source_adapters',
  'f903d036b38199f1cfd3ca72b065d2fec70e23ed6065795b11423e991d6f2fa2'),
 ('ipfs_datasets_py.logic.software_verification.program',
  'f051f42d64c5f993451972924953cc7eaa6d17df097235ddabfd5d791d406f91'),
 ('ipfs_datasets_py.logic.software_verification.contracts',
  '0238a345e5c35aec78801891562e896d719bca0424eab8ad790d5da2c239c5aa'),
 ('ipfs_datasets_py.logic.software_verification.vc',
  'bc738a32af07afb4cc787d0ea5f743dc01e99d52230a45669bb04222e6cf7bf9'),
 ('ipfs_datasets_py.logic.software_verification.ir',
  '40f59ac33b5e8c282b06d7d8dec34940ffa8013f50fc65fc71e19a1ea41ef282'),
 ('ipfs_datasets_py.logic.software_verification.properties',
  '0b438555895505df283d7f151887a14d826df27259f4f5eee0ac584b74dbe10a'),
 ('ipfs_datasets_py.logic.software_verification.receipts',
  '4065833e8fa766e587035c456b381fead715f39c1e4e4619ea0d0bb969a609ea'),
 ('ipfs_datasets_py.logic.software_verification.translations',
  'c418cf45efd69dd01ced3eb2e05f9bc411ab12855fa408401d1ba74839df6dda'),
 ('ipfs_datasets_py.logic.backends.results',
  'afda793472d3a6ba13f20bee13a992bfce68177388bdf338548157a5aa201458'),
 ('ipfs_datasets_py.logic.backends.smt.compiler',
  '9b14183c071fb9eaed29a18e0bdd6483f71e152a82c88732bc0ae0a6d2321be5'),
 ('ipfs_datasets_py.logic.backends.smt.differential',
  'a1df37ffd82c35e9bb89e2541238bc9e481c4515512571cee7fba411e36dbf2e'),
 ('ipfs_datasets_py.logic.backends.z3.compiler',
  '5f161a448b2ff23b25e6bca01da10e4165e99d516bc9d13ddc50f078e7b7368b'),
 ('ipfs_datasets_py.logic.backends.cvc5.compiler',
  '0f875814e314625db10f27f32386f22a19c19fb20c5dc01cc574bc1e5500331f'),
 ('ipfs_datasets_py.logic.ir_core.provenance',
  '16eaf7c258550e5625bc19e6e7468c94133aedd1e85e64075f057ab4e52c3efe'),
 ('ipfs_datasets_py.logic.ir_core.protocols',
  'b452a7095a2524f0ea3f4e4f3a395643d3257cd6f42e3c77f8e1817df62f6fed'),
 ('ipfs_datasets_py.logic.ir_core.claims',
  '282cdd3a6ba18a90079886337d360bae44da172748faa3ad2715d2071070de3b'),
 ('ipfs_datasets_py.logic.ir_core.identity',
  '606bffc1f938c59f44651eeb65cb9c0738e16e465aabba0ad82ef05e3b5b3b0e'),
 ('ipfs_datasets_py.logic.common.canonical_cache_key',
  '6cc3b52c8635f6400f4f4bc00974b6e3489ce853da9b79db6420eb243c10c58f'),
 ('ipfs_datasets_py.logic.software_contracts.codebase_applicability',
  'f930724d5e7e939605a83e8e453c28827595890bbff5ba191bfe68bae775c080'),
 ('ipfs_datasets_py.logic.software_verification.applicability',
  '64d2b9b784775aa0ec6eaa7352102ffb171570e22da9e798602af89bb344b884'))
_NEW_MODULES = (
    "ipfs_datasets_py.logic.software_contracts.codebase_smt_execution",
    "ipfs_datasets_py.logic.software_contracts.codebase_smt_protocol",
    "ipfs_datasets_py.logic.backends.process",
    __name__,
    "ipfs_datasets_py.logic.parsers.smtlib",
    "ipfs_datasets_py.logic.syntax_core.contracts",
)
_PRODUCERS = frozenset({
    "ipfs_datasets_py.logic.software_contracts.codebase_verification",
    "ipfs_datasets_py.logic.software_contracts.codebase_applicability",
})


# Exact reviewed source migration for read-only historical @1 replay.
# Original bytes, authority and process observations remain historical.
_REVIEWED_READ_ONLY_MIGRATION = {
    'ipfs_datasets_py.logic.software_contracts.codebase_integer_profile': '361aa7884b2d625709b22429ef96c562ab7f32264c937ee7a5b57d09165b21ee',
    'ipfs_datasets_py.logic.software_verification.pipeline': '60d98314dab4bd28c4b9337cd4db85886c57935c43ad8e826895d082cf299043',
    'ipfs_datasets_py.logic.software_verification.source_adapters': 'aef42730598f74d35e232f460637560be71b55ddc459d555df9105d17fcfc003',
}

def validate_legacy_module_pins(recorded: Any, current: Any, *, applicability: bool = False) -> None:
    """Reject unreviewed @1 inventories or changed semantic dependency bytes.

    Current transport modules were absent in @1. They are deliberately excluded
    from its historical environment, without claiming they governed its runs.
    """
    legacy = _REVIEWED_PINS if applicability else _REVIEWED_PINS[:-2]
    expected = [{"module": name, "sha256": digest} for name, digest in legacy]
    if canonical_dag_json_bytes(recorded) != canonical_dag_json_bytes(expected):
        raise ValueError("unreviewed legacy implementation generation; explicit migration required")
    current_names = [row["module"] for row in current]
    base_names = [name for name, _ in _REVIEWED_PINS[:-2]]
    expected_names = base_names + list(_NEW_MODULES)
    if applicability:
        expected_names += [name for name, _ in _REVIEWED_PINS[-2:]]
    if current_names != expected_names or any(set(row) != {"module", "sha256"} for row in current):
        raise ValueError("legacy replay module inventory differs; explicit migration required")
    current_map = {row["module"]: row["sha256"] for row in current}
    if any(current_map[name] != _REVIEWED_READ_ONLY_MIGRATION.get(name, digest)
           for name, digest in legacy if name not in _PRODUCERS):
        raise ValueError("legacy semantic dependency changed; explicit migration required")


__all__ = ["LEGACY_VERIFICATION_SCHEMA", "LEGACY_VERIFICATION_PROFILE",
    "LEGACY_APPLICABILITY_SCHEMA", "LEGACY_APPLICABILITY_PROFILE", "validate_legacy_module_pins"]
