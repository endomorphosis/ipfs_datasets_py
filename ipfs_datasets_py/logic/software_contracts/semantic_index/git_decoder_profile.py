"""Closed, explicitly admitted Git decoder resource profiles.

The default remains 128 MiB. A caller must separately authorize the fixed
256 MiB profile; neither a manifest nor its content hashes authorize resources.
"""
from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from .snapshot import GIT_COMMAND_TIMEOUT_SECONDS, SnapshotError

DEFAULT_DECODER_ADDRESS_BYTES = 128 * 1024 * 1024
EXPLICIT_DECODER_ADDRESS_BYTES = 256 * 1024 * 1024
DECODER_CONFIG = (("core.packedGitWindowSize", "8388608"),
                  ("core.packedGitLimit", "33554432"),
                  ("core.deltaBaseCacheLimit", "16777216"))
DECODER_LAUNCHER = (
    "import os,resource,sys; "
    "n=int(sys.argv[1]); resource.setrlimit(resource.RLIMIT_AS,(n,n)); "
    "os.execvp('git',['git',*sys.argv[2:]])"
)


def _source_identity():
    root = Path(__file__).resolve().parent
    return tuple((name, hashlib.sha256((root / name).read_bytes()).hexdigest())
                 for name in ("git_decoder_profile.py", "chunked_snapshot.py", "snapshot.py"))


@dataclass(frozen=True)
class GitBlobDecoderProfile:
    address_space_bytes: int = DEFAULT_DECODER_ADDRESS_BYTES
    source_identity: tuple = field(default_factory=_source_identity, init=False)

    def __post_init__(self):
        if type(self.address_space_bytes) is not int or self.address_space_bytes not in {
                DEFAULT_DECODER_ADDRESS_BYTES, EXPLICIT_DECODER_ADDRESS_BYTES}:
            raise SnapshotError("unsupported fixed Git decoder profile")

    def payload(self):
        return {"schema": "ipfs-datasets.git-blob-decoder-profile@1",
                "address_space_bytes": self.address_space_bytes,
                "command_timeout_seconds": str(GIT_COMMAND_TIMEOUT_SECONDS),
                "git_config": dict(DECODER_CONFIG),
                "launcher_sha256": hashlib.sha256(DECODER_LAUNCHER.encode()).hexdigest(),
                "source_sha256": dict(self.source_identity),
                "target_imports": False, "source_execution": False}


@dataclass(frozen=True)
class GitBlobDecoderBudget:
    max_address_space_bytes: int = DEFAULT_DECODER_ADDRESS_BYTES

    def __post_init__(self):
        if type(self.max_address_space_bytes) is not int or self.max_address_space_bytes not in {
                DEFAULT_DECODER_ADDRESS_BYTES, EXPLICIT_DECODER_ADDRESS_BYTES}:
            raise SnapshotError("unsupported fixed Git decoder caller budget")


DEFAULT_DECODER_PROFILE = GitBlobDecoderProfile()
DEFAULT_DECODER_BUDGET = GitBlobDecoderBudget()


def validate_decoder_profile(profile):
    if type(profile) is not GitBlobDecoderProfile:
        raise SnapshotError("Git decoder requires a typed profile")
    profile.__post_init__()
    if profile.source_identity != _source_identity():
        raise SnapshotError("Git decoder source profile changed")
    return profile


def admit_decoder_profile(profile, budget):
    if type(profile) is not GitBlobDecoderProfile or type(budget) is not GitBlobDecoderBudget:
        raise SnapshotError("Git decoder admission requires typed profile and caller budget")
    # Revalidate frozen instances too: deserialization/object mutation must not
    # turn a resource observation into permission for an unsupported profile.
    validate_decoder_profile(profile)
    budget.__post_init__()
    if profile.address_space_bytes > budget.max_address_space_bytes:
        raise SnapshotError("Git decoder profile exceeds caller resource budget")
    return profile


def require_decoder_profile(observed, requested, budget):
    admit_decoder_profile(requested, budget)
    if type(observed) is not GitBlobDecoderProfile or observed != requested:
        raise SnapshotError("Git decoder profile differs from immutable request")
    return requested
