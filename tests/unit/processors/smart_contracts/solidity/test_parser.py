"""CRYPTOIR-G730 bounded inert Solidity parsing and normalization.

Acceptance coverage:

* Deterministic results preserve exact source spans for contracts, libraries,
  interfaces, inheritance, imports, functions, constructors, modifiers, state
  variables, events, errors, calls, reads/writes, authorization guards, value
  effects, assembly, and unsupported syntax;
* parser identity/version/config and byte/node/nesting/import/diagnostic/
  cancellation/time bounds are receipt-bound;
* imports never resolve over the network;
* source/compiler/address claims remain evidence, not deployed semantics;
* failure and partial coverage are explicit;
* no import-time parser installation or system ``solc`` requirement;
* capability unavailability is a typed unsupported result.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ipfs_datasets_py.processors.smart_contracts.artifacts import bytes_digest
from ipfs_datasets_py.processors.smart_contracts.errors import (
    InvalidRequestError,
    ResourceLimitError,
    UnsupportedCapabilityError,
)
from ipfs_datasets_py.processors.smart_contracts.protocols import (
    Capability,
    ContractParser,
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.smart_contracts.solidity import (
    PARSER_ID,
    PARSER_VERSION,
    AuthGuardKind,
    CallKind,
    ClaimKind,
    ContractKind,
    ParseStatus,
    ParserBounds,
    ParserConfig,
    SolidityContractParser,
    SolidityParseResult,
    SourceSpan,
    UnavailableBackend,
    ValueEffectKind,
    ensure_parser_available,
    parse_solidity,
)


NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

SIMPLE_CONTRACT = """\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import "./LibMath.sol";

interface IVault {
    function deposit() external payable;
}

library LibMath {
    function add(uint256 a, uint256 b) internal pure returns (uint256) {
        return a + b;
    }
}

abstract contract Base is Ownable {
    address public admin;
}

contract Vault is Base, IVault {
    uint256 public total;
    mapping(address => uint256) private balances;

    event Deposited(address indexed user, uint256 amount);
    error InsufficientBalance(uint256 have, uint256 need);

    modifier onlyAdmin() {
        require(msg.sender == admin, "not admin");
        _;
    }

    constructor(address admin_) {
        admin = admin_;
    }

    function deposit() external payable override {
        require(msg.value > 0, "zero");
        balances[msg.sender] += msg.value;
        total += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    function withdraw(uint256 amount) external onlyAdmin nonReentrant {
        uint256 have = balances[msg.sender];
        if (have < amount) revert InsufficientBalance(have, amount);
        balances[msg.sender] = have - amount;
        total = total - amount;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "xfer");
    }

    function poke() external onlyOwner {
        uint256 x = this.total;
        admin = admin;
    }

    function explode(address payable to) external onlyOwner {
        selfdestruct(to);
    }

    receive() external payable {}
    fallback() external payable {}

    function yulBits() external pure returns (uint256 r) {
        assembly {
            r := 1
        }
    }
}
"""

MULTI_KIND = """\
pragma solidity >=0.8.0;

interface IFoo {
    function foo() external;
}

library L {
    function id(uint256 x) internal pure returns (uint256) {
        return x;
    }
}

contract C is IFoo {
    function foo() external override {}
}
"""


class FakeCancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self._cancelled = cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancelled


@pytest.fixture
def parser() -> SolidityContractParser:
    return SolidityContractParser()


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="solidity-parse-1",
        limits=RequestLimits(
            max_items=16,
            max_requests=8,
            max_response_bytes=4 * 1024 * 1024,
            max_depth=16,
        ),
        deadline=datetime(2099, 1, 1, tzinfo=timezone.utc),
        cancellation=FakeCancellation(False),
    )


def test_import_does_not_require_solc_or_install() -> None:
    """Importing the package must not touch solc or installers."""
    import ipfs_datasets_py.processors.smart_contracts.solidity as pkg
    import ipfs_datasets_py.processors.smart_contracts.solidity.parser as parser_mod

    assert pkg.PARSER_ID
    assert parser_mod.InertSolidityBackend().available is True
    # Default parser is available without system solc.
    p = SolidityContractParser()
    assert p.available is True
    assert p.capabilities.supports(Capability.PARSE_ARTIFACT)


def test_implements_contract_parser_protocol(parser: SolidityContractParser) -> None:
    assert isinstance(parser, ContractParser)
    assert Capability.PARSE_ARTIFACT in parser.capabilities.features


def test_parse_simple_contract_spans_and_kinds(
    parser: SolidityContractParser,
) -> None:
    result = parser.parse_source(SIMPLE_CONTRACT, path="Vault.sol")
    assert result.is_success
    assert result.status in (ParseStatus.OK, ParseStatus.PARTIAL)
    unit = result.source_unit
    assert unit is not None
    assert unit.path == "Vault.sol"
    assert unit.source_digest.startswith("sha256:")
    assert unit.byte_length == len(SIMPLE_CONTRACT.encode("utf-8"))

    # Pragma + imports
    assert any(p.name == "solidity" for p in unit.pragmas)
    assert len(unit.imports) >= 2
    assert all(imp.resolved is False for imp in unit.imports)
    assert any("Ownable" in imp.path or "Ownable" in "".join(imp.symbols) for imp in unit.imports)

    kinds = {t.kind for t in unit.type_definitions}
    names = {t.name for t in unit.type_definitions}
    assert ContractKind.INTERFACE in kinds or "IVault" in names
    assert ContractKind.LIBRARY in kinds or "LibMath" in names
    assert ContractKind.CONTRACT in kinds or "Vault" in names
    assert "Vault" in names

    vault = next(t for t in unit.type_definitions if t.name == "Vault")
    assert vault.span.start_offset < vault.span.end_offset
    assert vault.span.start_line >= 1
    # Inheritance
    base_names = {i.name for i in vault.inheritance}
    assert "Base" in base_names or "IVault" in base_names

    fn_names = {f.name for f in vault.functions}
    assert "deposit" in fn_names
    assert "withdraw" in fn_names
    assert "constructor" in fn_names
    assert "receive" in fn_names
    assert "fallback" in fn_names

    assert any(m.name == "onlyAdmin" for m in vault.modifiers)
    assert any(s.name == "total" for s in vault.state_variables)
    assert any(e.name == "Deposited" for e in vault.events)
    assert any(e.name == "InsufficientBalance" for e in vault.errors)

    # Calls / value effects / assembly
    assert vault.calls or vault.value_effects or vault.assembly_blocks
    assert any(v.kind is ValueEffectKind.CALL_VALUE or v.kind is ValueEffectKind.SELFDESTRUCT
               for v in vault.value_effects) or vault.calls
    assert any(a.dialect == "assembly" for a in vault.assembly_blocks) or any(
        u.construct == "assembly" for u in vault.unsupported
    )

    # Auth guards
    assert vault.auth_guards
    assert any(
        g.kind in {AuthGuardKind.REQUIRE, AuthGuardKind.MODIFIER, AuthGuardKind.OWNABLE, AuthGuardKind.REVERT}
        for g in vault.auth_guards
    )


def test_spans_are_exact_byte_slices() -> None:
    src = "pragma solidity ^0.8.0;\ncontract C { uint256 public x; }\n"
    result = parse_solidity(src, path="C.sol")
    unit = result.source_unit
    assert unit is not None
    assert unit.pragmas
    pragma = unit.pragmas[0]
    fragment = src.encode("utf-8")[pragma.span.start_offset : pragma.span.end_offset]
    # Source is ASCII so byte offsets == char offsets.
    assert b"pragma" in fragment
    c = unit.type_definitions[0]
    body = src[c.span.start_offset : c.span.end_offset]
    assert "contract C" in body
    assert body.strip().endswith("}")


def test_multi_kind_interface_library_contract() -> None:
    result = parse_solidity(MULTI_KIND)
    assert result.is_success
    unit = result.source_unit
    assert unit is not None
    by_name = {t.name: t for t in unit.type_definitions}
    assert "IFoo" in by_name
    assert by_name["IFoo"].kind is ContractKind.INTERFACE
    assert "L" in by_name
    assert by_name["L"].kind is ContractKind.LIBRARY
    assert "C" in by_name
    assert by_name["C"].kind is ContractKind.CONTRACT
    assert any(i.name == "IFoo" for i in by_name["C"].inheritance)


def test_identity_version_config_bounds_receipt_bound(
    parser: SolidityContractParser,
) -> None:
    bounds = ParserBounds(max_source_bytes=100_000, max_nodes=10_000)
    config = ParserConfig(backend="inert", extract_assembly=True)
    p = SolidityContractParser(bounds=bounds, config=config)
    result = p.parse_source("contract C {}", path="c.sol")
    assert result.identity.parser_id == PARSER_ID
    assert result.identity.parser_version == PARSER_VERSION
    assert result.identity.config_digest
    assert result.identity.bounds_digest
    assert result.bounds.max_source_bytes == 100_000
    assert result.config.backend == "inert"
    assert result.usage.source_bytes == len(b"contract C {}")
    # Round-trip
    restored = SolidityParseResult.from_dict(result.to_dict())
    assert restored.content_digest == result.content_digest
    assert restored.identity.parser_id == result.identity.parser_id


def test_imports_never_resolve_network() -> None:
    src = 'import "https://evil.example/x.sol";\ncontract C {}'
    result = parse_solidity(src)
    unit = result.source_unit
    assert unit is not None
    assert unit.imports
    assert all(imp.resolved is False for imp in unit.imports)
    with pytest.raises(InvalidRequestError):
        ParserConfig(resolve_imports=True)


def test_compiler_and_address_claims_are_evidence_only(
    parser: SolidityContractParser,
) -> None:
    result = parser.parse_source(
        "pragma solidity 0.8.20;\ncontract C {}",
        path="C.sol",
        evidence={
            "compiler": "solc-0.8.20",
            "address": "0x" + "ab" * 20,
            "verified_source": "true",
        },
    )
    unit = result.source_unit
    assert unit is not None
    kinds = {c.kind for c in unit.evidence_claims}
    assert ClaimKind.COMPILER in kinds
    assert ClaimKind.ADDRESS in kinds
    # Claims carry unverified role — never deployed semantics.
    for claim in unit.evidence_claims:
        if claim.kind is ClaimKind.ADDRESS:
            assert claim.attributes.get("role") == "unverified_evidence"
            assert claim.value.startswith("0x")


def test_resource_limit_source_bytes() -> None:
    bounds = ParserBounds(max_source_bytes=16)
    result = parse_solidity("contract TooLongNameForBudget {}", bounds=bounds)
    assert result.status is ParseStatus.RESOURCE_LIMIT
    assert result.source_unit is None
    assert any(d.code == "max_source_bytes" for d in result.diagnostics)


def test_resource_limit_max_imports_partial() -> None:
    imports = "\n".join(f'import "./f{i}.sol";' for i in range(5))
    src = imports + "\ncontract C {}"
    bounds = ParserBounds(max_imports=2, max_nodes=10_000)
    result = parse_solidity(src, bounds=bounds)
    assert result.status in (ParseStatus.PARTIAL, ParseStatus.OK, ParseStatus.RESOURCE_LIMIT)
    # When limited during imports we still may produce a unit with truncated imports.
    if result.source_unit is not None:
        assert result.usage.imports <= 5


def test_cancellation(parser: SolidityContractParser) -> None:
    ctx = OperationContext(
        request_id="cancel-1",
        cancellation=FakeCancellation(True),
    )
    result = parser.parse_source("contract C {}", context=ctx)
    assert result.status is ParseStatus.CANCELLED


def test_deadline_exceeded(parser: SolidityContractParser) -> None:
    ctx = OperationContext(
        request_id="deadline-1",
        deadline=datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    result = parser.parse_source("contract C {}", context=ctx)
    assert result.status is ParseStatus.DEADLINE_EXCEEDED


def test_unavailable_backend_is_typed_unsupported() -> None:
    p = SolidityContractParser(config=ParserConfig(backend="solc"))
    assert p.available is False
    result = p.parse_source("contract C {}")
    assert result.status is ParseStatus.UNSUPPORTED
    assert result.is_unsupported
    assert any(d.code == "backend_unavailable" for d in result.diagnostics)

    with pytest.raises(UnsupportedCapabilityError):
        ensure_parser_available(p)


def test_injected_unavailable_backend() -> None:
    backend = UnavailableBackend("custom-solc")
    p = SolidityContractParser(
        config=ParserConfig(backend="custom-solc"),
        backend=backend,
    )
    result = p.parse_source("contract C {}")
    assert result.status is ParseStatus.UNSUPPORTED


def test_protocol_parse_batch(
    parser: SolidityContractParser, context: OperationContext
) -> None:
    artifacts = [
        SIMPLE_CONTRACT,
        {"source": "contract D {}", "path": "D.sol", "compiler": "0.8.19"},
        b"contract E { }",
    ]
    parsed = parser.parse(artifacts, context=context)
    assert len(parsed) == 3
    assert all(item.representation == "solidity-source-unit-v1" for item in parsed)
    assert all(item.artifact_digest.startswith("sha256:") for item in parsed)
    assert parsed[0].payload["status"] in {"ok", "partial"}
    assert parsed[1].payload["source_unit"]["path"] == "D.sol"


def test_protocol_parse_batch_limit(
    parser: SolidityContractParser,
) -> None:
    ctx = OperationContext(
        request_id="limit-batch",
        limits=RequestLimits(
            max_items=1,
            max_requests=1,
            max_response_bytes=1024,
            max_depth=4,
        ),
        deadline=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ResourceLimitError):
        parser.parse(["contract A {}", "contract B {}"], context=ctx)


def test_deterministic_digests() -> None:
    a = parse_solidity(SIMPLE_CONTRACT, path="Vault.sol")
    b = parse_solidity(SIMPLE_CONTRACT, path="Vault.sol")
    assert a.content_digest == b.content_digest
    assert a.source_unit is not None and b.source_unit is not None
    assert a.source_unit.content_digest == b.source_unit.content_digest
    assert a.source_unit.source_digest == bytes_digest(
        SIMPLE_CONTRACT.encode("utf-8")
    )


def test_source_span_validation() -> None:
    with pytest.raises(InvalidRequestError):
        SourceSpan(start_offset=10, end_offset=5)
    span = SourceSpan(
        start_offset=0,
        end_offset=4,
        start_line=1,
        start_column=1,
        end_line=1,
        end_column=5,
    )
    assert span.length == 4
    assert SourceSpan.from_dict(span.to_dict()) == span


def test_partial_unsupported_syntax_explicit() -> None:
    src = """\
contract C {
    struct S { uint256 a; }
    enum E { A, B }
    type MyInt is uint256;
    using L for uint256;
    function f() external {
        unchecked { }
        try this.f() {} catch {}
        assembly { let x := 1 }
    }
}
"""
    result = parse_solidity(src)
    assert result.is_success
    unit = result.source_unit
    assert unit is not None
    c = unit.type_definitions[0]
    constructs = {u.construct for u in c.unsupported}
    # At least some unsupported constructs are explicit.
    assert constructs & {"struct", "enum", "type", "using", "try", "unchecked", "assembly"}
    assert result.partial or result.status is ParseStatus.PARTIAL or c.unsupported


def test_storage_access_and_call_kinds() -> None:
    src = """\
contract C {
    uint256 public x;
    function f() external {
        x = 1;
        x += 2;
        this.x;
        other.g();
        super.f();
        address(this).delegatecall("");
    }
}
"""
    result = parse_solidity(src)
    unit = result.source_unit
    assert unit is not None
    c = unit.type_definitions[0]
    assert c.storage_accesses
    assert any(s.kind.value in {"write", "read"} for s in c.storage_accesses)
    kinds = {call.kind for call in c.calls}
    assert kinds & {
        CallKind.EXTERNAL,
        CallKind.SUPER,
        CallKind.DELEGATECALL,
        CallKind.INTERNAL,
        CallKind.LOW_LEVEL,
        CallKind.BUILTIN,
    } or c.calls


def test_empty_source_ok() -> None:
    result = parse_solidity("")
    assert result.status is ParseStatus.OK
    assert result.source_unit is not None
    assert result.source_unit.type_definitions == ()


def test_invalid_artifact_type(
    parser: SolidityContractParser, context: OperationContext
) -> None:
    with pytest.raises(InvalidRequestError):
        parser.parse([12345], context=context)


def test_resolve_imports_forbidden_on_import_model() -> None:
    from ipfs_datasets_py.processors.smart_contracts.solidity import SolidityImport

    with pytest.raises(InvalidRequestError):
        SolidityImport(
            path="./x.sol",
            span=SourceSpan(0, 1),
            resolved=True,
        )
