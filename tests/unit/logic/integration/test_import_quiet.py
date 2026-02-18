import importlib
import sys
import warnings
from pathlib import Path


def test_integration_has_no_logging_basicconfig_calls() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    integration_dir = repo_root / "ipfs_datasets_py" / "logic" / "integration"

    offenders: list[Path] = []
    for path in integration_dir.rglob("*.py"):
        if "logging.basicConfig(" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(repo_root))

    assert offenders == [], f"Found import-time logging configuration in: {offenders}"


def test_proof_cache_shim_does_not_warn_on_import() -> None:
    module_name = "ipfs_datasets_py.logic.integration.caching.proof_cache"

    sys.modules.pop(module_name, None)

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always", DeprecationWarning)
        importlib.import_module(module_name)

    assert not any(
        isinstance(w.message, DeprecationWarning) for w in recorded
    ), "DeprecationWarning should not be emitted at import time"


def test_proof_cache_shim_warns_on_attribute_access() -> None:
    module_name = "ipfs_datasets_py.logic.integration.caching.proof_cache"

    mod = importlib.import_module(module_name)

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always", DeprecationWarning)
        _ = mod.ProofCache

    assert any(
        isinstance(w.message, DeprecationWarning) for w in recorded
    ), "DeprecationWarning should be emitted when accessing shim attributes"


def test_legal_symbolic_analyzer_import_is_symai_quiet() -> None:
    module_name = "ipfs_datasets_py.logic.integration.domain.legal_symbolic_analyzer"

    symai_was_loaded = "symai" in sys.modules

    mod = importlib.import_module(module_name)
    importlib.reload(mod)

    if not symai_was_loaded:
        assert "symai" not in sys.modules, "symai should not be imported at module import time"
