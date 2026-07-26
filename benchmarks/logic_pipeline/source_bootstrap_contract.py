"""Small, path-free contract shared by the G240 bootstrap and its parent.

This module is intentionally safe to load before the production child applies
Landlock.  It imports only the benchmark's side-effect-free CID primitives and
the dedicated confinement contract.  In particular, it does not import the
source executor, optional model packages, or benchmark inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType
from typing import Final, Mapping, Self

from .content_addressing import cid_for_dag_json, validate_cid
from .runtime_confinement import (
    G240_LANDLOCK_HANDLED_ACCESS_FS_V1,
    G240_LANDLOCK_HANDLED_ACCESS_NET_V1,
    G240_LANDLOCK_POLICY_SCHEMA_V1,
    G240_LANDLOCK_RECEIPT_SCHEMA_V1,
    G240_LANDLOCK_RESTRICT_SELF_FLAGS_V1,
    G240_LANDLOCK_SCOPED_V1,
    G240_MAXIMUM_KNOWN_LANDLOCK_ABI,
    G240_MINIMUM_LANDLOCK_ABI,
    G240LandlockConfinementError,
    G240LandlockPolicyV1,
    G240LandlockPrivatePolicySourcesV1,
    G240LandlockReceiptV1,
    validate_g240_landlock_policy_v1,
    validate_g240_landlock_receipt_v1,
)


G240_BOOTSTRAP_CONFINEMENT_PROFILE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g240-bootstrap-confinement-profile.v2"
)
G240_BOOTSTRAP_PRIVATE_POLICY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g240-bootstrap-private-policy.v2"
)
G240_BOOTSTRAP_RECEIPT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g240-bootstrap-confinement-receipt.v2"
)
G240_TRACKED_SOURCE_BOOTSTRAP_PATH_V2: Final = (
    "benchmarks/logic_pipeline/source_bootstrap.py"
)
G240_TRACKED_SOURCE_BOOTSTRAP_COMMAND_V2: Final = (
    "python",
    G240_TRACKED_SOURCE_BOOTSTRAP_PATH_V2,
)
G240_APPROVED_TCP_DESTINATION_PORTS_V2: Final = (8080,)

_GIT_OBJECT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def _profile_payload() -> dict[str, object]:
    return {
        "schema": G240_BOOTSTRAP_CONFINEMENT_PROFILE_SCHEMA_V2,
        "bootstrap_path": G240_TRACKED_SOURCE_BOOTSTRAP_PATH_V2,
        "two_stage_launch": True,
        "production_landlock_required": True,
        "synthetic_test_bypass_is_distinct": True,
        "minimum_landlock_abi": G240_MINIMUM_LANDLOCK_ABI,
        "maximum_known_landlock_abi": G240_MAXIMUM_KNOWN_LANDLOCK_ABI,
        "handled_access_fs": G240_LANDLOCK_HANDLED_ACCESS_FS_V1,
        "handled_access_net": G240_LANDLOCK_HANDLED_ACCESS_NET_V1,
        "scoped": G240_LANDLOCK_SCOPED_V1,
        "restrict_self_flags": G240_LANDLOCK_RESTRICT_SELF_FLAGS_V1,
        "landlock_policy_schema": G240_LANDLOCK_POLICY_SCHEMA_V1,
        "landlock_receipt_schema": G240_LANDLOCK_RECEIPT_SCHEMA_V1,
        "approved_tcp_destination_ports": list(
            G240_APPROVED_TCP_DESTINATION_PORTS_V2
        ),
        "tcp_destination_address_authenticated": False,
        "udp_restricted_by_landlock": False,
        "pathname_unix_socket_restricted_by_landlock": False,
        "close_fds_required": True,
        "inherited_descriptor_policy": (
            "stdio-plus-one-dedicated-one-shot-receipt-pipe"
        ),
        "inherited_socket_count_required": 0,
        "git_observation_before_confinement": True,
        "execution_request_opened_after_confinement": True,
    }


G240_BOOTSTRAP_CONFINEMENT_PROFILE_V2: Final[
    Mapping[str, object]
] = MappingProxyType(_profile_payload())
G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2: Final = cid_for_dag_json(
    _profile_payload()
)
_G240_APPROVED_TCP_PORT_SET_CID_V2: Final = cid_for_dag_json(
    {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "g240-landlock-tcp-port-set.v1"
        ),
        "transport": "tcp",
        "authority": "destination-port-only",
        "ports": list(G240_APPROVED_TCP_DESTINATION_PORTS_V2),
    }
)


class G240BootstrapContractError(ValueError):
    """Raised when the two-stage bootstrap boundary cannot be authenticated."""


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise G240BootstrapContractError(
            f"{field} must be an object with string keys"
        )
    return value


def _canonical_cid(value: object, field: str) -> str:
    try:
        return validate_cid(value, codecs=("dag-json",))
    except (TypeError, ValueError) as exc:
        raise G240BootstrapContractError(
            f"{field} must be a canonical DAG-JSON CID"
        ) from exc


def g240_bootstrap_git_observation_cid(
    object_id: str,
    *,
    role: str,
) -> str:
    """Content-address one Git commit observation without exposing a path."""

    if (
        not isinstance(object_id, str)
        or not _GIT_OBJECT.fullmatch(object_id)
        or role not in {"source", "ipfs-accelerate-gitlink"}
    ):
        raise G240BootstrapContractError(
            "bootstrap Git observation is invalid"
        )
    return cid_for_dag_json(
        {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark."
                "g240-bootstrap-git-observation.v2"
            ),
            "role": role,
            "object_format": (
                "sha1" if len(object_id) == 40 else "sha256"
            ),
            "object_type": "commit",
            "oid": object_id,
        }
    )


@dataclass(frozen=True, slots=True)
class G240BootstrapConfinementReceiptV2:
    """Path-free receipt emitted once before the executor is imported."""

    confinement_profile_cid: str
    landlock_policy: Mapping[str, object] | None
    landlock_receipt: Mapping[str, object] | None
    source_commit_observation_cid: str
    source_bound_gitlink_observation_cid: str | None
    inherited_descriptor_count: int
    unexpected_inherited_descriptor_count: int
    inherited_socket_count: int
    close_fds_observed: bool
    receipt_channel_one_shot: bool
    git_observed_before_confinement: bool
    execution_request_opened_before_confinement: bool
    confinement_applied: bool
    stage2_authorized: bool
    synthetic_test_only: bool
    schema: str = G240_BOOTSTRAP_RECEIPT_SCHEMA_V2
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G240_BOOTSTRAP_RECEIPT_SCHEMA_V2:
            raise G240BootstrapContractError(
                "unsupported G240 bootstrap receipt schema"
            )
        profile_cid = _canonical_cid(
            self.confinement_profile_cid,
            "confinement_profile_cid",
        )
        if profile_cid != G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2:
            raise G240BootstrapContractError(
                "G240 bootstrap confinement profile changed"
            )
        object.__setattr__(
            self, "confinement_profile_cid", profile_cid
        )
        object.__setattr__(
            self,
            "source_commit_observation_cid",
            _canonical_cid(
                self.source_commit_observation_cid,
                "source_commit_observation_cid",
            ),
        )
        if self.source_bound_gitlink_observation_cid is not None:
            object.__setattr__(
                self,
                "source_bound_gitlink_observation_cid",
                _canonical_cid(
                    self.source_bound_gitlink_observation_cid,
                    "source_bound_gitlink_observation_cid",
                ),
            )
        for name in (
            "inherited_descriptor_count",
            "unexpected_inherited_descriptor_count",
            "inherited_socket_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise G240BootstrapContractError(
                    f"{name} must be a nonnegative observed count"
                )
        expected_descriptor_count = 3 if self.synthetic_test_only else 4
        if (
            self.inherited_descriptor_count != expected_descriptor_count
            or self.unexpected_inherited_descriptor_count != 0
            or self.inherited_socket_count != 0
        ):
            raise G240BootstrapContractError(
                "bootstrap inherited descriptors differ from stdio plus the "
                "one-shot receipt pipe"
            )
        for name in (
            "close_fds_observed",
            "receipt_channel_one_shot",
            "git_observed_before_confinement",
            "execution_request_opened_before_confinement",
            "confinement_applied",
            "stage2_authorized",
            "synthetic_test_only",
        ):
            if type(getattr(self, name)) is not bool:
                raise G240BootstrapContractError(
                    f"{name} must be boolean"
                )
        if (
            not self.close_fds_observed
            or self.receipt_channel_one_shot
            is not (not self.synthetic_test_only)
            or not self.git_observed_before_confinement
            or self.execution_request_opened_before_confinement
            or not self.stage2_authorized
        ):
            raise G240BootstrapContractError(
                "bootstrap sequencing or descriptor assurance changed"
            )
        policy: G240LandlockPolicyV1 | None
        receipt: G240LandlockReceiptV1 | None
        if self.synthetic_test_only:
            if (
                self.landlock_policy is not None
                or self.landlock_receipt is not None
                or self.confinement_applied
            ):
                raise G240BootstrapContractError(
                    "synthetic bootstrap bypass may not claim Landlock"
                )
            policy = None
            receipt = None
        else:
            if (
                self.landlock_policy is None
                or self.landlock_receipt is None
                or not self.confinement_applied
            ):
                raise G240BootstrapContractError(
                    "production bootstrap requires applied Landlock evidence"
                )
            try:
                policy = validate_g240_landlock_policy_v1(
                    self.landlock_policy
                )
                receipt = validate_g240_landlock_receipt_v1(
                    self.landlock_receipt,
                    expected_policy=policy,
                )
            except (
                G240LandlockConfinementError,
                TypeError,
                ValueError,
            ) as exc:
                raise G240BootstrapContractError(
                    "bootstrap Landlock evidence is invalid"
                ) from exc
            if (
                policy.approved_tcp_port_count
                != len(G240_APPROVED_TCP_DESTINATION_PORTS_V2)
                or policy.approved_tcp_port_set_cid
                != _G240_APPROVED_TCP_PORT_SET_CID_V2
            ):
                raise G240BootstrapContractError(
                    "bootstrap Landlock TCP-port authority changed"
                )
            object.__setattr__(
                self,
                "landlock_policy",
                MappingProxyType(policy.to_dict()),
            )
            object.__setattr__(
                self,
                "landlock_receipt",
                MappingProxyType(receipt.to_dict()),
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.receipt_cid is None:
            object.__setattr__(self, "receipt_cid", expected)
        elif (
            _canonical_cid(self.receipt_cid, "receipt_cid") != expected
        ):
            raise G240BootstrapContractError(
                "G240 bootstrap receipt CID changed"
            )

    @property
    def typed_landlock_policy(self) -> G240LandlockPolicyV1 | None:
        if self.landlock_policy is None:
            return None
        return validate_g240_landlock_policy_v1(self.landlock_policy)

    @property
    def typed_landlock_receipt(self) -> G240LandlockReceiptV1 | None:
        policy = self.typed_landlock_policy
        if policy is None or self.landlock_receipt is None:
            return None
        return validate_g240_landlock_receipt_v1(
            self.landlock_receipt,
            expected_policy=policy,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            name: (
                None
                if value is None
                else dict(value)
                if isinstance(value, Mapping)
                else value
            )
            for name, value in (
                (field, getattr(self, field))
                for field in self.__dataclass_fields__
                if field != "receipt_cid"
            )
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "receipt_cid": self.receipt_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G240 bootstrap receipt")
        if set(data) != set(cls.__dataclass_fields__):
            raise G240BootstrapContractError(
                "G240 bootstrap receipt fields changed"
            )
        return cls(
            **{
                **data,
                "landlock_policy": (
                    None
                    if data["landlock_policy"] is None
                    else _mapping(
                        data["landlock_policy"], "landlock_policy"
                    )
                ),
                "landlock_receipt": (
                    None
                    if data["landlock_receipt"] is None
                    else _mapping(
                        data["landlock_receipt"], "landlock_receipt"
                    )
                ),
            }
        )  # type: ignore[arg-type]


def g240_private_landlock_policy_payload_v2(
    sources: G240LandlockPrivatePolicySourcesV1,
) -> dict[str, object]:
    """Serialize private enforcement inputs for the bootstrap-only file."""

    if not isinstance(sources, G240LandlockPrivatePolicySourcesV1):
        raise G240BootstrapContractError(
            "private bootstrap policy requires typed Landlock sources"
        )
    sources.revalidate()
    if (
        sources.approved_tcp_ports
        != G240_APPROVED_TCP_DESTINATION_PORTS_V2
    ):
        raise G240BootstrapContractError(
            "private bootstrap policy must authorize TCP port 8080 only"
        )
    identity = {
        "schema": G240_BOOTSTRAP_PRIVATE_POLICY_SCHEMA_V2,
        "confinement_profile_cid": (
            G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
        ),
        "landlock_policy": sources.policy.to_dict(),
        "read_only_paths": [
            path.as_posix() for path in sources.read_only_paths
        ],
        "state_path": sources.state_path.as_posix(),
        "output_path": sources.output_path.as_posix(),
        "cache_paths": [
            path.as_posix() for path in sources.cache_paths
        ],
        "approved_tcp_ports": list(sources.approved_tcp_ports),
    }
    return {
        **identity,
        "private_policy_cid": cid_for_dag_json(identity),
    }


def g240_private_landlock_sources_from_payload_v2(
    value: object,
) -> G240LandlockPrivatePolicySourcesV1:
    """Reconstruct and source-validate private policy inputs."""

    data = _mapping(value, "G240 bootstrap private policy")
    expected_fields = {
        "schema",
        "confinement_profile_cid",
        "landlock_policy",
        "read_only_paths",
        "state_path",
        "output_path",
        "cache_paths",
        "approved_tcp_ports",
        "private_policy_cid",
    }
    if set(data) != expected_fields:
        raise G240BootstrapContractError(
            "G240 bootstrap private policy fields changed"
        )
    if (
        data["schema"] != G240_BOOTSTRAP_PRIVATE_POLICY_SCHEMA_V2
        or _canonical_cid(
            data["confinement_profile_cid"],
            "confinement_profile_cid",
        )
        != G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
    ):
        raise G240BootstrapContractError(
            "G240 bootstrap private policy profile changed"
        )
    identity = {
        key: data[key] for key in expected_fields - {"private_policy_cid"}
    }
    if (
        _canonical_cid(data["private_policy_cid"], "private_policy_cid")
        != cid_for_dag_json(identity)
    ):
        raise G240BootstrapContractError(
            "G240 bootstrap private policy CID changed"
        )
    raw_read_only = data["read_only_paths"]
    raw_caches = data["cache_paths"]
    raw_ports = data["approved_tcp_ports"]
    if (
        not isinstance(raw_read_only, list)
        or not isinstance(raw_caches, list)
        or not isinstance(raw_ports, list)
        or not isinstance(data["state_path"], str)
        or not isinstance(data["output_path"], str)
    ):
        raise G240BootstrapContractError(
            "G240 bootstrap private policy sources are malformed"
        )
    try:
        policy = validate_g240_landlock_policy_v1(
            _mapping(data["landlock_policy"], "landlock_policy")
        )
        return G240LandlockPrivatePolicySourcesV1(
            policy=policy,
            read_only_paths=tuple(Path(item) for item in raw_read_only),
            state_path=Path(data["state_path"]),
            output_path=Path(data["output_path"]),
            cache_paths=tuple(Path(item) for item in raw_caches),
            approved_tcp_ports=tuple(raw_ports),
        )
    except (
        G240LandlockConfinementError,
        TypeError,
        ValueError,
    ) as exc:
        raise G240BootstrapContractError(
            "G240 bootstrap private policy failed source replay"
        ) from exc


def validate_g240_bootstrap_confinement_receipt_v2(
    value: object,
    *,
    expected_policy: G240LandlockPolicyV1 | None = None,
    synthetic_test_only: bool | None = None,
) -> G240BootstrapConfinementReceiptV2:
    """Typed-replay a one-shot bootstrap receipt and optional parent policy."""

    receipt = (
        value
        if isinstance(value, G240BootstrapConfinementReceiptV2)
        else G240BootstrapConfinementReceiptV2.from_dict(value)
    )
    receipt = G240BootstrapConfinementReceiptV2.from_dict(
        receipt.to_dict()
    )
    if (
        synthetic_test_only is not None
        and receipt.synthetic_test_only is not synthetic_test_only
    ):
        raise G240BootstrapContractError(
            "bootstrap receipt synthetic/production mode changed"
        )
    if expected_policy is not None:
        policy = validate_g240_landlock_policy_v1(expected_policy)
        observed = receipt.typed_landlock_policy
        if observed is None or observed.to_dict() != policy.to_dict():
            raise G240BootstrapContractError(
                "bootstrap receipt differs from the parent-held policy"
            )
    return receipt


__all__ = [
    "G240_APPROVED_TCP_DESTINATION_PORTS_V2",
    "G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2",
    "G240_BOOTSTRAP_CONFINEMENT_PROFILE_SCHEMA_V2",
    "G240_BOOTSTRAP_CONFINEMENT_PROFILE_V2",
    "G240_BOOTSTRAP_PRIVATE_POLICY_SCHEMA_V2",
    "G240_BOOTSTRAP_RECEIPT_SCHEMA_V2",
    "G240_TRACKED_SOURCE_BOOTSTRAP_COMMAND_V2",
    "G240_TRACKED_SOURCE_BOOTSTRAP_PATH_V2",
    "G240BootstrapConfinementReceiptV2",
    "G240BootstrapContractError",
    "g240_bootstrap_git_observation_cid",
    "g240_private_landlock_policy_payload_v2",
    "g240_private_landlock_sources_from_payload_v2",
    "validate_g240_bootstrap_confinement_receipt_v2",
]
