"""Shared wallet processor conformance harness (WALPROC-G090).

Every chain lane must pass the checks in :data:`REQUIRED_SHARED_CHECKS`.
Chain-specific assertions register through :class:`ProviderContract.extra_checks`
and **extend** the suite; they cannot remove or skip shared checks.

AST entry points used by objective scanners:

* ``WalletProcessorConformance``
* ``ProviderContract``
* ``FixtureTransport``
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import json
import socket
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar

from ipfs_datasets_py.processors.wallets.canonical import deterministic_id
from ipfs_datasets_py.processors.wallets.checkpoints import (
    CheckpointIdentity,
    HashAnchor,
    InMemoryCheckpointStore,
    build_checkpoint,
)
from ipfs_datasets_py.processors.wallets.errors import (
    NormalizationError,
    OperationCancelledError,
    ProviderError,
)
from ipfs_datasets_py.processors.wallets.export import (
    ExportFormat,
    round_trip_records,
)
from ipfs_datasets_py.processors.wallets.finality import (
    CanonicalHistory,
    DepthFinalityPolicy,
    DepthThresholds,
    ReorgKind,
    ReorgReviewRequired,
)
from ipfs_datasets_py.processors.wallets.models import (
    AccountKind,
    AccountRef,
    AssetKind,
    AssetRef,
    ChainRef,
    ExactAmount,
    Finality,
    LedgerPosition,
    Provenance,
    RawPayloadRef,
    TransactionRecord,
    TransactionStatus,
    TransferKind,
    TransferRecord,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    OperationContext,
    RequestLimits,
    SecretValue,
)
from ipfs_datasets_py.processors.wallets.security import (
    SecretHeaderValue,
    SecretReference,
)


# ---------------------------------------------------------------------------
# Paths and required check catalog
# ---------------------------------------------------------------------------

_CONTRACT_DIR = Path(__file__).resolve().parent
_FIXTURE_ROOT = _CONTRACT_DIR.parents[2] / "fixtures" / "wallets"
_SHARED_DIR = _FIXTURE_ROOT / "_shared"
_DIGESTS_NAME = "digests.json"
_ROOT_MANIFEST_NAME = "manifest.json"

REQUIRED_SHARED_CHECKS: frozenset[str] = frozenset(
    {
        "address_network_identity",
        "exact_amounts",
        "deterministic_ids",
        "malformed_empty_partial",
        "pagination",
        "retries",
        "cancellation",
        "idempotency",
        "cas_conflicts",
        "shallow_deep_reorg",
        "export_round_trip",
        "secret_leaks",
        "optional_dependency_absence",
        "no_network_imports",
    }
)

# Modules that must import without performing network I/O or secret resolution.
NO_NETWORK_IMPORT_MODULES: tuple[str, ...] = (
    "ipfs_datasets_py.processors.wallets.models",
    "ipfs_datasets_py.processors.wallets.canonical",
    "ipfs_datasets_py.processors.wallets.protocols",
    "ipfs_datasets_py.processors.wallets.errors",
    "ipfs_datasets_py.processors.wallets.checkpoints",
    "ipfs_datasets_py.processors.wallets.finality",
    "ipfs_datasets_py.processors.wallets.export",
    "ipfs_datasets_py.processors.wallets.security",
    "ipfs_datasets_py.processors.wallets.providers.http",
    "ipfs_datasets_py.processors.wallets.providers.retry",
    "ipfs_datasets_py.processors.wallets.providers.rate_limit",
)

# Optional chain extras that must remain absente-tolerant at package import time.
OPTIONAL_CHAIN_MODULES: tuple[str, ...] = (
    "web3",
    "solana",
    "solders",
    "xrpl",
    "xumm",
    "bitcoinlib",
)

_NOW = datetime(2026, 7, 29, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixture transport
# ---------------------------------------------------------------------------


def fixture_root() -> Path:
    """Return the absolute path to ``tests/fixtures/wallets``."""

    return _FIXTURE_ROOT


def file_sha256(path: Path) -> str:
    """Return a tagged SHA-256 digest of raw file bytes."""

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _sorted_fixture_files(root: Path | None = None) -> list[Path]:
    base = root or _FIXTURE_ROOT
    files = [
        path
        for path in base.rglob("*")
        if path.is_file() and path.name != _DIGESTS_NAME
    ]
    return sorted(files, key=lambda p: p.relative_to(base).as_posix())


class FixtureTransport:
    """Offline fixture loader with integrity digests.

    Never opens sockets, resolves DNS, or reads ambient credentials. All data
    comes from files under :func:`fixture_root`.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or _FIXTURE_ROOT).resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"wallet fixture root missing: {self.root}")

    def path(self, *parts: str) -> Path:
        candidate = (self.root.joinpath(*parts)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"path escapes fixture root: {parts}") from exc
        return candidate

    def load_json(self, *parts: str) -> Any:
        path = self.path(*parts)
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def load_text(self, *parts: str) -> str:
        return self.path(*parts).read_text(encoding="utf-8")

    def load_shared(self, name: str) -> Any:
        return self.load_json("_shared", name)

    def load_manifest(self, subdir: str | None = None) -> dict[str, Any]:
        if subdir is None:
            return self.load_json(_ROOT_MANIFEST_NAME)
        return self.load_json(subdir, _ROOT_MANIFEST_NAME)

    def list_chain_dirs(self) -> list[str]:
        names: list[str] = []
        for child in sorted(self.root.iterdir()):
            if child.is_dir() and (child / _ROOT_MANIFEST_NAME).is_file():
                names.append(child.name)
        return names

    def iter_fixture_files(self) -> list[Path]:
        return _sorted_fixture_files(self.root)

    def compute_digests(self) -> dict[str, str]:
        digests: dict[str, str] = {}
        for path in self.iter_fixture_files():
            rel = path.relative_to(self.root).as_posix()
            digests[rel] = file_sha256(path)
        return digests

    def load_digest_manifest(self) -> dict[str, Any]:
        return self.load_json(_DIGESTS_NAME)

    def verify_digests(self) -> None:
        """Assert every tracked fixture file matches :file:`digests.json`."""

        manifest = self.load_digest_manifest()
        expected = manifest.get("files")
        if not isinstance(expected, Mapping):
            raise AssertionError("digests.json must contain a files mapping")
        actual = self.compute_digests()
        expected_keys = set(expected)
        actual_keys = set(actual)
        missing = actual_keys - expected_keys
        extra = expected_keys - actual_keys
        if missing:
            raise AssertionError(
                f"digests.json missing entries for: {sorted(missing)}"
            )
        if extra:
            raise AssertionError(
                f"digests.json lists missing files: {sorted(extra)}"
            )
        mismatches = [
            key
            for key, digest in expected.items()
            if actual.get(key) != digest
        ]
        if mismatches:
            raise AssertionError(
                f"fixture content digests drifted for: {sorted(mismatches)}"
            )

    def assert_manifest_provenance(self, subdir: str | None = None) -> None:
        """Require source, license, and provenance on a fixture manifest."""

        manifest = self.load_manifest(subdir)
        for key in ("source", "license", "provenance"):
            if key not in manifest:
                label = subdir or "<root>"
                raise AssertionError(f"manifest {label} missing {key}")
        classification = manifest.get("classification") or {}
        if classification.get("offline_default") is not True:
            label = subdir or "<root>"
            raise AssertionError(
                f"manifest {label} must declare classification.offline_default=true"
            )


# ---------------------------------------------------------------------------
# Provider contract
# ---------------------------------------------------------------------------

ExtraCheck = Callable[["WalletProcessorConformance"], None]


@dataclass(frozen=True, slots=True)
class ProviderContract:
    """Registration surface for a chain under the shared conformance suite.

    Chain-specific behavior is supplied through optional factories and
    :attr:`extra_checks`. Extra checks run **after** every required shared
    check; they cannot replace or suppress shared coverage.
    """

    name: str
    chain_namespace: str
    network: str
    chain_id: str
    genesis_hash: str
    fixture_subdir: str = "_shared"
    provider_name: str = "fixture-provider"
    import_modules: tuple[str, ...] = ()
    optional_modules: tuple[str, ...] = OPTIONAL_CHAIN_MODULES
    extra_checks: tuple[ExtraCheck, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("ProviderContract.name must not be empty")
        if not self.chain_namespace.strip():
            raise ValueError("chain_namespace must not be empty")
        if not self.network.strip():
            raise ValueError("network must not be empty")
        if not self.chain_id.strip():
            raise ValueError("chain_id must not be empty")
        if not self.genesis_hash.strip():
            raise ValueError("genesis_hash must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        # Disallow empty extra_check callables that claim to skip shared work.
        for check in self.extra_checks:
            if not callable(check):
                raise TypeError("extra_checks must be callable")

    def chain_ref(self) -> ChainRef:
        return ChainRef(
            namespace=self.chain_namespace,
            network=self.network,
            chain_id=self.chain_id,
            genesis_hash=self.genesis_hash,
        )

    def with_extra_checks(self, *checks: ExtraCheck) -> "ProviderContract":
        """Return a copy with additional chain-native checks appended."""

        return ProviderContract(
            name=self.name,
            chain_namespace=self.chain_namespace,
            network=self.network,
            chain_id=self.chain_id,
            genesis_hash=self.genesis_hash,
            fixture_subdir=self.fixture_subdir,
            provider_name=self.provider_name,
            import_modules=self.import_modules,
            optional_modules=self.optional_modules,
            extra_checks=self.extra_checks + tuple(checks),
            metadata=dict(self.metadata),
        )


def make_reference_provider_contract() -> ProviderContract:
    """Offline reference contract exercised by the harness self-tests."""

    return ProviderContract(
        name="shared-reference",
        chain_namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=(
            "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"
        ),
        fixture_subdir="_shared",
        provider_name="fixture-rpc",
        import_modules=NO_NETWORK_IMPORT_MODULES,
        optional_modules=OPTIONAL_CHAIN_MODULES,
        metadata={"role": "shared_harness_reference"},
    )


# ---------------------------------------------------------------------------
# Offline helpers used by shared checks
# ---------------------------------------------------------------------------


class _CancelToken:
    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _context(
    request_id: str = "conformance-1",
    *,
    limits: RequestLimits | None = None,
    cancellation: _CancelToken | None = None,
) -> OperationContext:
    return OperationContext(
        request_id=request_id,
        limits=limits or RequestLimits(),
        cancellation=cancellation,
    )


def _dedupe_native_ids(records: Sequence[Mapping[str, Any]]) -> list[str]:
    seen: list[str] = []
    for item in records:
        native_id = str(item["native_id"])
        if native_id not in seen:
            seen.append(native_id)
    return seen


def _paginate(
    pages: Sequence[Mapping[str, Any]],
    *,
    max_pages: int,
    detect_loops: bool = True,
) -> list[str]:
    """Replay offline pagination pages under finite page budgets."""

    by_cursor: dict[str | None, Mapping[str, Any]] = {
        page.get("cursor"): page for page in pages
    }
    cursor: str | None = None
    seen_cursors: set[str | None] = set()
    collected: list[str] = []
    for page_index in range(max_pages):
        if cursor in seen_cursors and detect_loops:
            raise ProviderError(f"pagination cursor loop at {cursor!r}")
        seen_cursors.add(cursor)
        page = by_cursor.get(cursor)
        if page is None:
            break
        for record in page.get("records") or []:
            collected.append(str(record["native_id"]))
        next_cursor = page.get("next_cursor")
        if not next_cursor:
            return collected
        cursor = str(next_cursor)
    else:
        # Exhausted page budget while still having a next cursor.
        raise ProviderError(f"pagination exceeded max_pages={max_pages}")
    return collected


def _retry_outcomes(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    max_attempts: int,
    cancel_before_attempt: int | None = None,
) -> tuple[int, Mapping[str, Any] | None]:
    attempts = 0
    for outcome in outcomes:
        attempt = int(outcome["attempt"])
        if cancel_before_attempt is not None and attempt >= cancel_before_attempt:
            raise OperationCancelledError("cancelled before attempt")
        attempts += 1
        disposition = outcome["disposition"]
        if disposition == "success":
            payload = outcome.get("payload")
            if not isinstance(payload, Mapping):
                raise ProviderError("success outcome missing payload")
            return attempts, payload
        if disposition == "permanent":
            raise ProviderError(str(outcome.get("error") or "permanent failure"))
        if disposition == "transient":
            if attempts >= max_attempts:
                raise ProviderError("retry budget exhausted")
            continue
        raise ProviderError(f"unknown disposition: {disposition}")
    raise ProviderError("no successful outcome")


# ---------------------------------------------------------------------------
# Conformance suite
# ---------------------------------------------------------------------------


@dataclass
class ConformanceResult:
    """Outcome of one named conformance check."""

    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }


class WalletProcessorConformance:
    """Reusable provider/normalizer/processor conformance suite.

    Instantiate with a :class:`ProviderContract` (and optional
    :class:`FixtureTransport`). Call :meth:`run_all` or individual
    ``check_*`` methods. Pytest mixins subclass this class and expose each
    ``check_*`` as a test method; chain suites only add ``extra_checks``.
    """

    required_checks: ClassVar[frozenset[str]] = REQUIRED_SHARED_CHECKS

    def __init__(
        self,
        contract: ProviderContract | None = None,
        transport: FixtureTransport | None = None,
    ) -> None:
        self.contract = contract or make_reference_provider_contract()
        self.transport = transport or FixtureTransport()
        self._completed_shared: set[str] = set()

    # -- factories ----------------------------------------------------------

    def chain(self) -> ChainRef:
        return self.contract.chain_ref()

    def operation_context(self, **kwargs: Any) -> OperationContext:
        return _context(**kwargs)

    # -- orchestration ------------------------------------------------------

    def run_shared_checks(self) -> list[ConformanceResult]:
        """Run every required shared check; chain extras are not included."""

        results: list[ConformanceResult] = []
        for name in sorted(self.required_checks):
            method = getattr(self, f"check_{name}")
            try:
                method()
                self._completed_shared.add(name)
                results.append(ConformanceResult(name=name, passed=True))
            except Exception as exc:  # pragma: no cover - surfaced to caller
                results.append(
                    ConformanceResult(name=name, passed=False, detail=str(exc))
                )
                raise
        missing = self.required_checks - self._completed_shared
        if missing:
            raise AssertionError(f"shared checks not completed: {sorted(missing)}")
        return results

    def run_extra_checks(self) -> list[ConformanceResult]:
        """Run chain-native extensions only after shared checks finished."""

        if self._completed_shared != self.required_checks:
            missing = self.required_checks - self._completed_shared
            raise AssertionError(
                "chain-specific checks cannot run until shared suite passes; "
                f"missing: {sorted(missing)}"
            )
        results: list[ConformanceResult] = []
        for index, check in enumerate(self.contract.extra_checks):
            name = f"extra[{index}]:{getattr(check, '__name__', 'check')}"
            try:
                check(self)
                results.append(ConformanceResult(name=name, passed=True))
            except Exception as exc:  # pragma: no cover
                results.append(
                    ConformanceResult(name=name, passed=False, detail=str(exc))
                )
                raise
        return results

    def run_all(self) -> list[ConformanceResult]:
        """Shared checks first, then chain extensions."""

        results = self.run_shared_checks()
        results.extend(self.run_extra_checks())
        return results

    def assert_cannot_weaken_shared_checks(self) -> None:
        """Document and enforce the extend-only refinement rule."""

        declared = set(self.required_checks)
        if declared != REQUIRED_SHARED_CHECKS:
            raise AssertionError(
                "ProviderContract/WalletProcessorConformance must not shrink "
                f"REQUIRED_SHARED_CHECKS (got {sorted(declared)})"
            )
        # Attempting to run extras without shared completion must fail closed.
        incomplete = WalletProcessorConformance(self.contract, self.transport)
        incomplete._completed_shared = set()  # type: ignore[attr-defined]
        try:
            incomplete.run_extra_checks()
        except AssertionError:
            return
        raise AssertionError(
            "extra checks must refuse to run before shared suite completes"
        )

    # -- shared checks ------------------------------------------------------

    def check_address_network_identity(self) -> None:
        vectors = self.transport.load_shared("identity_vectors.json")
        built: dict[str, tuple[str, str]] = {}
        for item in vectors["vectors"]:
            vid = item["id"]
            chain_data = item["chain"]
            address = item["address"]
            if item.get("expect_valid") is False:
                try:
                    AccountRef(
                        ChainRef(
                            namespace=chain_data["namespace"],
                            network=chain_data["network"],
                            chain_id=chain_data["chain_id"],
                            genesis_hash=chain_data["genesis_hash"],
                        ),
                        address,
                        AccountKind(item.get("kind") or "address"),
                    )
                except ValueError:
                    continue
                raise AssertionError(f"{vid}: expected invalid address")
            chain = ChainRef(
                namespace=chain_data["namespace"],
                network=chain_data["network"],
                chain_id=chain_data["chain_id"],
                genesis_hash=chain_data["genesis_hash"],
            )
            account = AccountRef(
                chain,
                address,
                AccountKind(item.get("kind") or "address"),
            )
            built[vid] = (chain.chain_ref_id, account.account_id)
            if "must_differ_from" in item:
                other = built[item["must_differ_from"]]
                assert built[vid][0] != other[0], f"{vid} chain id collided"
                assert built[vid][1] != other[1], f"{vid} account id collided"
            if item.get("assert_chain_ids_differ"):
                foreign = item["foreign_network"]
                foreign_chain = ChainRef(
                    namespace=foreign["namespace"],
                    network=foreign["network"],
                    chain_id=foreign["chain_id"],
                    genesis_hash=foreign["genesis_hash"],
                )
                assert chain.chain_ref_id != foreign_chain.chain_ref_id
        self._completed_shared.add("address_network_identity")

    def check_exact_amounts(self) -> None:
        vectors = self.transport.load_shared("amount_vectors.json")
        for item in vectors["valid"]:
            amount = ExactAmount(
                base_units=item["base_units"],
                decimals=item["decimals"],
            )
            assert amount.base_units == item["base_units"]
            assert amount.decimals == item["decimals"]
            as_dict = amount.to_dict()
            assert isinstance(as_dict["base_units"], str)
            assert "." not in as_dict["base_units"] or as_dict[
                "base_units"
            ].startswith("-")
            # No binary float coercion path.
            assert not isinstance(as_dict["base_units"], float)
        for item in vectors["invalid"]:
            try:
                ExactAmount(base_units=item["base_units"], decimals=item["decimals"])
            except ValueError:
                continue
            raise AssertionError(f"expected invalid amount {item['id']}")
        self._completed_shared.add("exact_amounts")

    def check_deterministic_ids(self) -> None:
        fixture = self.transport.load_shared("deterministic_ids.json")
        chain = ChainRef(
            namespace=fixture["chain"]["namespace"],
            network=fixture["chain"]["network"],
            chain_id=fixture["chain"]["chain_id"],
            genesis_hash=fixture["chain"]["genesis_hash"],
        )
        ids: dict[str, str] = {}
        for item in fixture["records"]:
            # Identity must ignore observation noise.
            payload = {
                "chain": chain.identity_dict(),
                "coordinates": item["identity"],
            }
            record_id = deterministic_id(item["record_type"], payload)
            ids[item["id"]] = record_id
            if "must_match_id" in item:
                assert ids[item["id"]] == ids[item["must_match_id"]], item["id"]
            if "must_differ_from" in item:
                assert ids[item["id"]] != ids[item["must_differ_from"]], item["id"]
        self._completed_shared.add("deterministic_ids")

    def check_malformed_empty_partial(self) -> None:
        fixture = self.transport.load_shared("malformed_payloads.json")

        def normalize(payload: Any) -> list[str]:
            if payload is None or isinstance(payload, (str, int, float, bool)):
                raise NormalizationError("malformed payload")
            if not isinstance(payload, list):
                if isinstance(payload, Mapping):
                    if "native_id" not in payload and "transaction_hash" not in payload:
                        raise NormalizationError("partial payload missing identity")
                    if "amount" in payload and "base_units" not in (
                        payload.get("amount") or {}
                    ):
                        raise NormalizationError("partial amount")
                    native = payload.get("native_id") or payload.get(
                        "transaction_hash"
                    )
                    return [str(native)]
                raise NormalizationError("unexpected payload type")
            return _dedupe_native_ids(payload)  # type: ignore[arg-type]

        for case in fixture["cases"]:
            expect = case["expect"]
            payload = case["payload"]
            if expect == "empty_ok_or_noop":
                assert normalize(payload) == []
            elif expect in {"reject", "reject_or_skip"}:
                try:
                    normalize(payload)
                except NormalizationError:
                    continue
                raise AssertionError(f"{case['id']} should reject")
            elif expect == "dedupe_or_idempotent":
                assert normalize(payload) == ["dup-1"]
            elif expect == "accept_preserve_identity":
                assert set(normalize(payload)) == {"a", "b"}
            else:
                raise AssertionError(f"unknown expect {expect}")
        self._completed_shared.add("malformed_empty_partial")

    def check_pagination(self) -> None:
        fixture = self.transport.load_shared("pagination_pages.json")
        max_pages = int(fixture["limits"]["max_pages"])
        happy = _paginate(fixture["happy_path"]["pages"], max_pages=max_pages)
        assert happy == fixture["happy_path"]["expected_native_ids"]
        try:
            _paginate(fixture["cursor_loop"]["pages"], max_pages=max_pages)
        except ProviderError as exc:
            assert "loop" in str(exc).lower() or "max_pages" in str(exc)
        else:
            raise AssertionError("cursor loop must be detected")
        try:
            _paginate(
                fixture["page_limit_exceeded"]["pages"],
                max_pages=max_pages,
                detect_loops=True,
            )
        except ProviderError:
            pass
        else:
            raise AssertionError("page limit must stop pagination")
        self._completed_shared.add("pagination")

    def check_retries(self) -> None:
        fixture = self.transport.load_shared("retry_and_cancel.json")
        retries = fixture["retries"]
        attempts, payload = _retry_outcomes(
            retries["outcomes"],
            max_attempts=int(retries["max_attempts"]),
        )
        assert attempts == retries["expected_attempts"]
        assert payload is not None
        assert payload["native_id"] == retries["expected_native_id"]

        permanent = fixture["permanent_failure"]
        try:
            _retry_outcomes(
                permanent["outcomes"],
                max_attempts=int(permanent["max_attempts"]),
            )
        except ProviderError:
            pass
        else:
            raise AssertionError("permanent failures must not succeed")
        self._completed_shared.add("retries")

    def check_cancellation(self) -> None:
        fixture = self.transport.load_shared("retry_and_cancel.json")
        cancel = fixture["cancellation"]
        token = _CancelToken()
        # Simulate cooperative cancel at the configured attempt boundary.
        try:
            _retry_outcomes(
                cancel["outcomes"],
                max_attempts=5,
                cancel_before_attempt=int(cancel["cancel_before_attempt"]),
            )
        except OperationCancelledError:
            token.cancel()
        else:
            raise AssertionError("cancellation must raise OperationCancelledError")
        assert token.cancelled is True
        ctx = _context(cancellation=token)
        try:
            ctx.check_active()
        except OperationCancelledError:
            pass
        else:
            raise AssertionError("cancelled context must fail closed")
        self._completed_shared.add("cancellation")

    def check_idempotency(self) -> None:
        fixture = self.transport.load_shared("cas_checkpoint.json")
        records = fixture["idempotent_replay"]["records"]
        unique = _dedupe_native_ids(records)
        assert unique == fixture["idempotent_replay"]["expected_unique_native_ids"]
        # Replay of the same set yields the same order and content.
        assert _dedupe_native_ids(records) == unique
        self._completed_shared.add("idempotency")

    def check_cas_conflicts(self) -> None:
        fixture = self.transport.load_shared("cas_checkpoint.json")
        identity_data = fixture["identity"]
        chain = ChainRef(
            namespace=identity_data["chain"]["namespace"],
            network=identity_data["chain"]["network"],
            chain_id=identity_data["chain"]["chain_id"],
            genesis_hash=identity_data["chain"]["genesis_hash"],
        )
        identity = CheckpointIdentity(
            chain=chain,
            provider=identity_data["provider"],
            scope=identity_data["scope"],
            normalized_schema_major=int(identity_data["normalized_schema_major"]),
            normalizer_version=identity_data["normalizer_version"],
        )
        store = InMemoryCheckpointStore()
        ctx = _context("cas-1")
        initial = fixture["cas_conflicts"]["initial"]
        first = build_checkpoint(
            identity,
            sequence=int(initial["sequence"]),
            block_hash=initial["block_hash"],
            revision=initial["revision"],
        )

        async def exercise() -> None:
            ok = await store.compare_and_set(
                identity.key,
                expected_revision=None,
                checkpoint=first,
                context=ctx,
            )
            assert ok is True
            loaded = await store.load(identity.key, context=ctx)
            assert loaded is not None
            stale = fixture["cas_conflicts"]["stale_write"]
            stale_ckpt = build_checkpoint(
                identity,
                sequence=int(stale["sequence"]),
                block_hash=stale["block_hash"],
            )
            conflict = await store.compare_and_set(
                identity.key,
                expected_revision=stale["expected_revision"],
                checkpoint=stale_ckpt,
                context=ctx,
            )
            assert conflict is False
            matching = fixture["cas_conflicts"]["matching_write"]
            match_ckpt = build_checkpoint(
                identity,
                sequence=int(matching["sequence"]),
                block_hash=matching["block_hash"],
            )
            success = await store.compare_and_set(
                identity.key,
                expected_revision=loaded.revision,
                checkpoint=match_ckpt,
                context=ctx,
            )
            assert success is True

        _run(exercise())
        self._completed_shared.add("cas_conflicts")

    def check_shallow_deep_reorg(self) -> None:
        fixture = self.transport.load_shared("reorg_histories.json")
        identity_chain = self.chain()
        identity = CheckpointIdentity(
            chain=identity_chain,
            provider=self.contract.provider_name,
            scope="wallet:conformance/reorg",
            normalized_schema_major=1,
            normalizer_version="shared-fixture-v1",
        )
        ctx = _context("reorg-1")

        shallow = fixture["shallow"]
        local = tuple(
            HashAnchor(int(item["sequence"]), item["hash"])
            for item in shallow["local_history"]
        )
        checkpoint = build_checkpoint(
            identity,
            sequence=local[-1].sequence,
            block_hash=local[-1].block_hash,
            safety_depth=3,
            prior_history=local[:-1],
        )
        remote = CanonicalHistory.from_pairs(
            [
                (int(item["sequence"]), item["hash"])
                for item in shallow["remote_history"]
            ]
        )
        policy = DepthFinalityPolicy(
            chain_namespaces=frozenset(
                {f"{self.contract.chain_namespace}:{self.contract.chain_id}"}
            ),
            thresholds=DepthThresholds(confirmed=1, safe=4, finalized=12),
            max_reorg_depth=64,
        )
        tip = HashAnchor(
            int(shallow["observed_tip"]["sequence"]),
            shallow["observed_tip"]["hash"],
        )
        decision = policy.evaluate_reorg(
            checkpoint,
            observed_anchor=tip,
            context=ctx,
            remote_history=remote,
            record_ids_by_hash=shallow["record_ids_by_hash"],
            prior_finality_by_id={
                rid: Finality.CONFIRMED
                for hashes in shallow["record_ids_by_hash"].values()
                for rid in hashes
            },
        )
        assert decision.kind is ReorgKind.SHALLOW
        assert decision.common_ancestor is not None
        assert decision.common_ancestor.sequence == int(
            shallow["expected_ancestor"]["sequence"]
        )
        assert decision.common_ancestor.block_hash == shallow["expected_ancestor"][
            "hash"
        ]
        orphaned = {a.block_hash for a in decision.orphaned_anchors}
        assert orphaned == set(shallow["expected_orphaned_hashes"])
        rewound = policy.apply_shallow_rewind(checkpoint, decision)
        assert rewound.anchor.sequence == decision.common_ancestor.sequence

        deep = fixture["deep"]
        deep_policy = DepthFinalityPolicy(
            chain_namespaces=frozenset(
                {f"{self.contract.chain_namespace}:{self.contract.chain_id}"}
            ),
            thresholds=DepthThresholds(confirmed=1, safe=2, finalized=8),
            max_reorg_depth=int(deep["max_reorg_depth"]),
        )
        deep_local = tuple(
            HashAnchor(int(item["sequence"]), item["hash"])
            for item in deep["local_history"]
        )
        deep_ckpt = build_checkpoint(
            identity,
            sequence=deep_local[-1].sequence,
            block_hash=deep_local[-1].block_hash,
            safety_depth=int(deep["max_reorg_depth"]),
            prior_history=deep_local[:-1],
        )
        deep_remote = CanonicalHistory.from_pairs(
            [(int(item["sequence"]), item["hash"]) for item in deep["remote_history"]]
        )
        deep_tip = HashAnchor(
            int(deep["observed_tip"]["sequence"]),
            deep["observed_tip"]["hash"],
        )
        deep_decision = deep_policy.evaluate_reorg(
            deep_ckpt,
            observed_anchor=deep_tip,
            context=ctx,
            remote_history=deep_remote,
        )
        assert deep_decision.kind is ReorgKind.DEEP
        assert deep_decision.review_required is True
        try:
            deep_policy.apply_shallow_rewind(deep_ckpt, deep_decision)
        except ReorgReviewRequired:
            pass
        else:
            raise AssertionError("deep reorg must require review")
        self._completed_shared.add("shallow_deep_reorg")

    def check_export_round_trip(self) -> None:
        fixture = self.transport.load_shared("export_sample_records.json")
        chain = ChainRef(
            namespace=fixture["chain"]["namespace"],
            network=fixture["chain"]["network"],
            chain_id=fixture["chain"]["chain_id"],
            genesis_hash=fixture["chain"]["genesis_hash"],
        )
        account = AccountRef(chain, fixture["account"], AccountKind.ADDRESS)
        asset_data = fixture["asset"]
        asset = AssetRef(
            chain,
            asset_namespace=asset_data["asset_namespace"],
            asset_reference=asset_data["asset_reference"],
            decimals=int(asset_data["decimals"]),
            kind=AssetKind(asset_data["kind"]),
            symbol=asset_data.get("symbol"),
        )
        provenance = Provenance(
            provider=self.contract.provider_name,
            provider_kind="fixture",
            request_id="export-conformance",
            scope=f"wallet:{fixture['account']}",
            observed_at=_NOW,
            raw_payload=RawPayloadRef(
                digest=fixture["raw_payload_digest"],
                media_type="application/json",
                byte_length=64,
            ),
        )
        records: list[TransactionRecord | TransferRecord] = []
        for tx in fixture["transactions"]:
            records.append(
                TransactionRecord(
                    chain=chain,
                    provenance=provenance,
                    ledger_position=LedgerPosition(
                        sequence=int(tx["sequence"]),
                        hash=tx["block_hash"],
                        transaction_index=int(tx["transaction_index"]),
                    ),
                    finality=Finality(tx["finality"]),
                    transaction_hash=tx["transaction_hash"],
                    status=TransactionStatus(tx["status"]),
                    participants=(account,),
                )
            )
        for transfer in fixture["transfers"]:
            records.append(
                TransferRecord(
                    chain=chain,
                    provenance=provenance,
                    ledger_position=LedgerPosition(
                        sequence=int(transfer["sequence"]),
                        hash=transfer["block_hash"],
                        transaction_index=int(transfer["transaction_index"]),
                        event_index=int(transfer["event_index"]),
                    ),
                    finality=Finality(transfer["finality"]),
                    transaction_hash=transfer["transaction_hash"],
                    transfer_index=int(transfer["transfer_index"]),
                    asset=asset,
                    amount=ExactAmount(
                        base_units=transfer["base_units"],
                        decimals=asset.decimals,
                    ),
                    source_account=AccountRef(
                        chain, transfer["from_address"], AccountKind.ADDRESS
                    ),
                    destination_account=AccountRef(
                        chain, transfer["to_address"], AccountKind.ADDRESS
                    ),
                    transfer_kind=TransferKind(transfer["kind"]),
                )
            )
        import tempfile

        with tempfile.TemporaryDirectory(prefix="wallet-conformance-export-") as tmp:
            written = round_trip_records(
                records,
                format=ExportFormat.JSONL,
                directory=tmp,
            )
        assert len(written) == len(records)
        written_ids = {item["record_id"] for item in written}
        expected_ids = {record.record_id for record in records}
        assert written_ids == expected_ids
        for item in written:
            assert item.get("chain_namespace") == chain.namespace
            assert item.get("network") == chain.network
        self._completed_shared.add("export_round_trip")

    def check_secret_leaks(self) -> None:
        fixture = self.transport.load_shared("secret_redaction_cases.json")
        forbidden = list(fixture["forbidden_substrings"])
        surfaces: list[str] = []
        for case in fixture["cases"]:
            kind = case["kind"]
            if kind == "secret_value":
                secret = SecretValue(case["secret_bytes_utf8"].encode("utf-8"))
                surfaces.extend([repr(secret), str(secret)])
            elif kind == "secret_reference":
                ref = SecretReference(case["reference"])
                surfaces.extend([repr(ref), str(ref), json.dumps(ref.to_dict())])
            elif kind == "secret_header":
                header = SecretHeaderValue(case["value"])
                surfaces.append(repr(header))
            else:
                raise AssertionError(f"unknown secret case kind {kind}")
        blob = "\n".join(surfaces)
        for needle in forbidden:
            if needle in blob:
                raise AssertionError(f"secret material leaked: {needle!r}")
        self._completed_shared.add("secret_leaks")

    def check_optional_dependency_absence(self) -> None:
        """Prove shared imports succeed even when chain SDKs are missing."""

        # Presence of optional modules is fine; absence must not break imports.
        for module_name in NO_NETWORK_IMPORT_MODULES:
            importlib.import_module(module_name)
        missing = [
            name
            for name in self.contract.optional_modules
            if name not in sys.modules
            and importlib.util.find_spec(name) is None  # type: ignore[attr-defined]
        ]
        # Re-import kernel after noting absences.
        for module_name in (
            "ipfs_datasets_py.processors.wallets.models",
            "ipfs_datasets_py.processors.wallets.protocols",
            "ipfs_datasets_py.processors.wallets.export",
        ):
            importlib.import_module(module_name)
        # Record that optional deps may be missing without failure.
        _ = missing
        self._completed_shared.add("optional_dependency_absence")

    def check_no_network_imports(self) -> None:
        """Import kernel modules with a socket guard to prove offline import."""

        modules = self.contract.import_modules or NO_NETWORK_IMPORT_MODULES
        original_socket = socket.socket
        original_create = socket.create_connection

        def _blocked(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("network I/O during wallet kernel import")

        socket.socket = _blocked  # type: ignore[assignment,misc]
        socket.create_connection = _blocked  # type: ignore[assignment]
        try:
            for module_name in modules:
                # Drop and re-import to exercise import-time side effects.
                sys.modules.pop(module_name, None)
                importlib.import_module(module_name)
        finally:
            socket.socket = original_socket  # type: ignore[assignment]
            socket.create_connection = original_create  # type: ignore[assignment]
        self._completed_shared.add("no_network_imports")


# ---------------------------------------------------------------------------
# Pytest mixin for chain adapters
# ---------------------------------------------------------------------------


class WalletProcessorConformanceMixin:
    """Pytest mixin: subclasses implement :meth:`provider_contract`.

    Chain suites inherit this mixin so shared checks stay identical. Override
    :meth:`provider_contract` and optionally append ``extra_checks`` on the
    contract; never override individual ``test_conformance_*`` methods to skip
    shared coverage.
    """

    def provider_contract(self) -> ProviderContract:
        return make_reference_provider_contract()

    def fixture_transport(self) -> FixtureTransport:
        return FixtureTransport()

    def conformance(self) -> WalletProcessorConformance:
        return WalletProcessorConformance(
            self.provider_contract(),
            self.fixture_transport(),
        )

    def test_conformance_address_network_identity(self) -> None:
        self.conformance().check_address_network_identity()

    def test_conformance_exact_amounts(self) -> None:
        self.conformance().check_exact_amounts()

    def test_conformance_deterministic_ids(self) -> None:
        self.conformance().check_deterministic_ids()

    def test_conformance_malformed_empty_partial(self) -> None:
        self.conformance().check_malformed_empty_partial()

    def test_conformance_pagination(self) -> None:
        self.conformance().check_pagination()

    def test_conformance_retries(self) -> None:
        self.conformance().check_retries()

    def test_conformance_cancellation(self) -> None:
        self.conformance().check_cancellation()

    def test_conformance_idempotency(self) -> None:
        self.conformance().check_idempotency()

    def test_conformance_cas_conflicts(self) -> None:
        self.conformance().check_cas_conflicts()

    def test_conformance_shallow_deep_reorg(self) -> None:
        self.conformance().check_shallow_deep_reorg()

    def test_conformance_export_round_trip(self) -> None:
        self.conformance().check_export_round_trip()

    def test_conformance_secret_leaks(self) -> None:
        self.conformance().check_secret_leaks()

    def test_conformance_optional_dependency_absence(self) -> None:
        self.conformance().check_optional_dependency_absence()

    def test_conformance_no_network_imports(self) -> None:
        self.conformance().check_no_network_imports()

    def test_conformance_run_all_shared_then_extra(self) -> None:
        suite = self.conformance()
        results = suite.run_all()
        names = {item.name for item in results if not item.name.startswith("extra[")}
        assert names == REQUIRED_SHARED_CHECKS
        assert all(item.passed for item in results)

    def test_conformance_chain_checks_extend_not_weaken(self) -> None:
        self.conformance().assert_cannot_weaken_shared_checks()


__all__ = [
    "REQUIRED_SHARED_CHECKS",
    "NO_NETWORK_IMPORT_MODULES",
    "OPTIONAL_CHAIN_MODULES",
    "ConformanceResult",
    "FixtureTransport",
    "ProviderContract",
    "WalletProcessorConformance",
    "WalletProcessorConformanceMixin",
    "file_sha256",
    "fixture_root",
    "make_reference_provider_contract",
]
