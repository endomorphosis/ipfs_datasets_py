"""State laws scraper for building state statutory law datasets.

This tool scrapes state statutes and regulations from various state
legislative websites and legal databases.
"""
import ast
import logging
import threading
from ipfs_datasets_py.utils import anyio_compat as asyncio
import inspect
import time
from typing import Callable, Dict, List, Optional, Any, Mapping, Sequence
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path

try:
    from .canonical_legal_corpora import get_canonical_legal_corpus
except ImportError:  # pragma: no cover - file-based test imports
    import importlib.util
    import sys

    _CANONICAL_MODULE_PATH = Path(__file__).with_name("canonical_legal_corpora.py")
    _CANONICAL_SPEC = importlib.util.spec_from_file_location(
        "canonical_legal_corpora",
        _CANONICAL_MODULE_PATH,
    )
    if _CANONICAL_SPEC is None or _CANONICAL_SPEC.loader is None:
        raise
    _CANONICAL_MODULE = importlib.util.module_from_spec(_CANONICAL_SPEC)
    sys.modules.setdefault("canonical_legal_corpora", _CANONICAL_MODULE)
    _CANONICAL_SPEC.loader.exec_module(_CANONICAL_MODULE)
    get_canonical_legal_corpus = _CANONICAL_MODULE.get_canonical_legal_corpus

logger = logging.getLogger(__name__)

# Enacted provisions can be very short.  Length is not a validity rule; the
# structural/navigation/placeholder checks below own source-text admission.
DEFAULT_MIN_FULL_TEXT_CHARS = 1

_QUALITY_NAV_RE = re.compile(
    r"skip navigation|skip to content|all rights reserved|bill status|meeting schedule|calendar|login|contact us|docs options help|home documents",
    re.IGNORECASE,
)
_QUALITY_SECTION_FALLBACK_RE = re.compile(r"^Section-\d+$", re.IGNORECASE)
_QUALITY_SECTION_SIGNAL_RE = re.compile(
    r"(?:\b\d{1,4}[A-Za-z]?(?:[.\-]\d+[A-Za-z]*)+\b|§\s*\d+[A-Za-z]?(?:[.\-]\d+[A-Za-z]*)+|\b(?:section|sec\.?|s\.)\s*\d+[A-Za-z]?(?:[.\-]\d+[A-Za-z]*)*\b)",
    re.IGNORECASE,
)
_QUALITY_SECTION_NUMBER_COMPONENT = (
    r"(?:\d+[A-Za-z0-9]*|\.\d+)"
    r"(?:[.:\-][A-Za-z0-9]+)*"
    r"(?:\([^()/]{1,80}\))?"
)
_QUALITY_SECTION_NUMBER_RE = re.compile(
    rf"^{_QUALITY_SECTION_NUMBER_COMPONENT}"
    rf"(?:/{_QUALITY_SECTION_NUMBER_COMPONENT})*$",
    re.IGNORECASE,
)
_QUALITY_SCAFFOLD_TEXT_RE = re.compile(r"^\s*Section\s+Section-\d+\s*:", re.IGNORECASE)
_QUALITY_NAV_URL_RE = re.compile(
    r"/(?:calendar|meeting|roster|blog|news|jobs|photo|links?|home|bulletin|live|staff|contact|interim|committee|reports?|member|media)\b",
    re.IGNORECASE,
)
_QUALITY_BILL_HISTORY_RE = re.compile(
    r"\bhistory of actions(?:/background)?\b",
    re.IGNORECASE,
)
_QUALITY_BILL_NUMBER_RE = re.compile(
    r"\b(?:house|senate)\s+bill\s+\d+\b|\bHB\s*\d+\b|\bSB\s*\d+\b",
    re.IGNORECASE,
)
_QUALITY_LEGAL_METADATA_RE = re.compile(
    r"\b(?:authority|implementing|history|rule history|relevant notices|relevant mar notices|references|referenced by|rule version|active version|effective|statutory authority|citation(?:s)?)\b",
    re.IGNORECASE,
)
_CHECKPOINT_STAGE_LABEL_RE = re.compile(r'"stage_label"\s*:\s*"([^"]*)"')
_CHECKPOINT_UPDATED_AT_STR_RE = re.compile(r'"updated_at"\s*:\s*"([^"]*)"')
_CHECKPOINT_UPDATED_AT_NUM_RE = re.compile(r'"updated_at"\s*:\s*([0-9]+(?:\.[0-9]+)?)')
_CHECKPOINT_STATUTES_COUNT_RE = re.compile(r'"statutes_count"\s*:\s*(-?[0-9]+)')

MULTIFETCH_EVIDENCE_ROOT_ENV = "STATE_LAWS_MULTIFETCH_EVIDENCE_ROOT"
STRICT_MULTIFETCH_EVIDENCE_ENV = "STATE_LAWS_STRICT_MULTIFETCH_EVIDENCE"
RETAINED_REPLAY_ONLY_ENV = "STATE_LAWS_RETAINED_REPLAY_ONLY"
_IMMUTABLE_STATE_RUN_PATH_ENV_KEYS = (
    "ARKANSAS_CURRENT_VARIANT_EVIDENCE_ROOT",
    "ARKANSAS_LEXIS_INVENTORY_PATH",
    "CALIFORNIA_BULK_ZIP",
    "CALIFORNIA_BULK_ZIP_RECEIPT",
    "DC_CODE_SECTION_XML",
    "DC_CODE_XML_DIR",
    "GEORGIA_ARCHIVED_OFFICIAL_MANIFEST",
    "ILLINOIS_BULK_ZIP",
    "ILLINOIS_MANIFEST_TEXT",
    "INDIANA_BULK_ZIP",
    "INDIANA_BULK_ZIP_RECEIPT",
    "INDIANA_CODE_ZIP_RECEIPT",
    "INDIANA_CODE_ZIP_CACHE_DIR",
    "MICHIGAN_CHAPTER_INDEX_HTML",
    "MICHIGAN_CHAPTER_XML",
    "NEW_JERSEY_BULK_ZIP",
    "NY_CATEGORY_HTML",
    "NY_OPENLEG_LAW_JSON",
    "STATE_SCRAPER_MS_LEXIS_EVIDENCE_DIR",
    "UTAH_TITLE_XML",
    "UTAH_TOC_HTML",
)
_IMMUTABLE_STATE_RUN_BOOLEAN_ENV_KEYS = (
    "ARKANSAS_LEXIS_PUBLIC_ACCESS_ENABLE",
    "GEORGIA_LEXIS_PUBLIC_ACCESS_ENABLE",
    "MISSISSIPPI_LEXIS_PUBLIC_ACCESS_ENABLE",
    "STATE_SCRAPER_FULL_CORPUS",
)
_IMMUTABLE_STATE_RUN_DIGEST_ENV_KEYS = (
    "NEW_JERSEY_BULK_RETAINED_SHA256",
)
_IMMUTABLE_STATE_RUN_SECRET_ENV_KEYS = (
    "NORTH_CAROLINA_BYCHAPTER_CHECKPOINT_HMAC_KEY",
)
_IMMUTABLE_STATE_RUN_CACHE_PATH_ENV_KEYS = (
    "IPFS_DATASETS_LEGAL_FETCH_CACHE_DIR",
    "LEGAL_SCRAPER_FETCH_CACHE_DIR",
    "LEGAL_SCRAPER_IPFS_PAGE_CACHE_DIR",
)
_PARSER_TRANSPORT_ENTRYPOINTS = ("scrape_all", "get_code_list", "scrape_code")
_SHARED_PARSER_FETCH_METHODS = frozenset(
    {
        "_fetch_page_content_with_archival_fallback",
        "_fetch_page_contents_with_archival_fallback",
        "_fetch_parser_input_with_transport",
    }
)
_DIRECT_HTTP_MODULES = frozenset({"aiohttp", "httpx", "requests", "urllib"})
_DIRECT_HTTP_CALLS = frozenset(
    {"get", "post", "put", "patch", "delete", "request", "urlopen", "goto"}
)
_CUSTOM_HTTP_OWNER_HINTS = frozenset(
    {"api", "browser", "client", "driver", "http", "page", "session", "transport"}
)
_BOUNDED_ENV_KEYS = (
    "STATE_SCRAPER_CODE_TIMEOUT_SECONDS",
    "STATE_SCRAPER_FETCH_TIMEOUT_SECONDS",
    "STATE_SCRAPER_MAX_STATUTES",
    "STATE_SCRAPER_BOUNDED_DIRECT_ONLY",
)
_BOUNDED_ENV_LEASE_LOCK = threading.Lock()
_BOUNDED_ENV_LEASE_OWNER: object | None = None


def _capture_state_law_run_environment() -> Dict[str, str]:
    """Capture supported selectors once with type-appropriate normalization."""

    binding: Dict[str, str] = {}
    for name in _IMMUTABLE_STATE_RUN_PATH_ENV_KEYS:
        raw_value = str(os.environ.get(name) or "").strip()
        binding[name] = (
            str(Path(raw_value).expanduser().resolve()) if raw_value else ""
        )
    for name in _IMMUTABLE_STATE_RUN_BOOLEAN_ENV_KEYS:
        binding[name] = (
            "1"
            if str(os.environ.get(name) or "").strip().lower()
            in {"1", "true", "yes", "on"}
            else "0"
        )
    for name in _IMMUTABLE_STATE_RUN_DIGEST_ENV_KEYS:
        binding[name] = str(os.environ.get(name) or "").strip().lower()
    for name in _IMMUTABLE_STATE_RUN_SECRET_ENV_KEYS:
        # Opaque authentication material is neither path-normalized nor logged.
        binding[name] = str(os.environ.get(name, ""))
    strict_evidence = str(
        os.environ.get(STRICT_MULTIFETCH_EVIDENCE_ENV) or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    retained_replay_only = str(
        os.environ.get(RETAINED_REPLAY_ONLY_ENV) or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    for name in _IMMUTABLE_STATE_RUN_CACHE_PATH_ENV_KEYS:
        raw_value = str(os.environ.get(name) or "").strip()
        binding[name] = (
            str(Path(raw_value).expanduser().resolve()) if raw_value else ""
        )
    if strict_evidence or retained_replay_only:
        binding.update(
            {
                "LEGAL_SCRAPER_FETCH_CACHE_ENABLED": "0",
                "LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED": "0",
                "LEGAL_SCRAPER_IPFS_PAGE_CACHE_PIN": "0",
            }
        )
        for name in _IMMUTABLE_STATE_RUN_CACHE_PATH_ENV_KEYS:
            binding[name] = ""
    else:
        binding["LEGAL_SCRAPER_FETCH_CACHE_ENABLED"] = (
            "1"
            if str(
                os.environ.get("LEGAL_SCRAPER_FETCH_CACHE_ENABLED") or ""
            ).strip().lower()
            in {"1", "true", "yes", "on"}
            else "0"
        )
        ipfs_enabled = str(
            os.environ.get("LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED") or ""
        ).strip().lower()
        binding["LEGAL_SCRAPER_IPFS_PAGE_CACHE_ENABLED"] = (
            "0" if ipfs_enabled in {"0", "false", "no", "off"} else "1"
        )
        binding["LEGAL_SCRAPER_IPFS_PAGE_CACHE_PIN"] = (
            "1"
            if str(
                os.environ.get("LEGAL_SCRAPER_IPFS_PAGE_CACHE_PIN") or ""
            ).strip().lower()
            in {"1", "true", "yes", "on"}
            else "0"
        )
    return binding


class StateScraperNonQuiescentTimeout(TimeoutError):
    """A supervised timeout returned while its daemon worker was still live."""

    def __init__(self, state_code: str, worker_name: str, timeout_seconds: float):
        self.state_code = str(state_code or "").strip().upper()
        self.worker_name = str(worker_name or "")
        self.timeout_seconds = float(timeout_seconds)
        super().__init__(
            f"state scrape timed out after {timeout_seconds} seconds while "
            f"daemon worker {self.worker_name!r} remained nonquiescent"
        )


def _call_dotted_name(node: ast.AST) -> str:
    parts: List[str] = []
    cursor: ast.AST = node
    while isinstance(cursor, ast.Attribute):
        parts.append(cursor.attr)
        cursor = cursor.value
    if isinstance(cursor, ast.Name):
        parts.append(cursor.id)
    return ".".join(reversed(parts))


def _transport_call_kind(call: ast.Call) -> str:
    dotted = _call_dotted_name(call.func)
    if not dotted:
        return ""
    original_leaf = dotted.rsplit(".", 1)[-1]
    parts = dotted.lower().split(".")
    leaf = parts[-1]
    if dotted.lower() in {
        f"self.{name.lower()}" for name in _SHARED_PARSER_FETCH_METHODS
    }:
        return "shared_base_fetch"
    if leaf == "urlopen":
        return "urllib_urlopen"
    if original_leaf == "Request" and "urllib" in parts[:-1]:
        return ""
    if any(part in _DIRECT_HTTP_MODULES for part in parts[:-1]) and (
        leaf in _DIRECT_HTTP_CALLS or leaf in {"client", "clientsession", "session"}
    ):
        return next(
            (part for part in parts if part in _DIRECT_HTTP_MODULES),
            "direct_http",
        )
    if leaf in _DIRECT_HTTP_CALLS and any(
        hint in parts[:-1] for hint in _CUSTOM_HTTP_OWNER_HINTS
    ):
        return "custom_http_client"
    if leaf.startswith(("fetch_", "download_")):
        return "custom_fetch_helper"
    return ""


def inventory_state_scraper_transport_bypasses(scraper: Any) -> Dict[str, Any]:
    """Return machine-readable potential fetches outside the Base shared path.

    This is a conservative static inventory, not proof that a branch executed.
    Strict prospective evidence treats every candidate as an eligibility gap
    until the state implementation routes it through the shared ledger or its
    completion proof explicitly binds the bulk response to derived rows.
    """

    scraper_type = scraper if inspect.isclass(scraper) else type(scraper)
    source_path_raw = inspect.getsourcefile(scraper_type)
    if not source_path_raw:
        return {
            "complete": False,
            "candidate_count": 1,
            "candidates": [
                {
                    "kind": "source_uninspectable",
                    "line": None,
                    "source": getattr(scraper_type, "__name__", str(scraper_type)),
                }
            ],
            "schema_version": "state-laws-transport-bypass-inventory-v1",
        }
    source_path = Path(source_path_raw).resolve()
    try:
        source_text = source_path.read_text(encoding="utf-8", errors="strict")
        tree = ast.parse(source_text, filename=str(source_path))
    except (OSError, UnicodeError, SyntaxError):
        return {
            "complete": False,
            "candidate_count": 1,
            "candidates": [
                {
                    "kind": "source_unreadable",
                    "line": None,
                    "source": source_path.name,
                }
            ],
            "schema_version": "state-laws-transport-bypass-inventory-v1",
        }

    class_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == getattr(scraper_type, "__name__", "")
        ),
        None,
    )
    if class_node is None:
        return {
            "complete": False,
            "candidate_count": 1,
            "candidates": [
                {
                    "kind": "class_source_uninspectable",
                    "line": None,
                    "source": source_path.name,
                }
            ],
            "schema_version": "state-laws-transport-bypass-inventory-v1",
            "source": source_path.name,
        }

    method_nodes = {
        node.name: node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    module_function_nodes = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    entrypoints = [
        name for name in _PARSER_TRANSPORT_ENTRYPOINTS if name in method_nodes
    ]
    if not entrypoints:
        return {
            "complete": False,
            "candidate_count": 1,
            "candidates": [
                {
                    "kind": "parser_entrypoint_uninspectable",
                    "line": None,
                    "source": source_path.name,
                }
            ],
            "parser_entrypoints": [],
            "schema_version": "state-laws-transport-bypass-inventory-v1",
            "source": source_path.name,
        }

    candidates: List[Dict[str, Any]] = []
    reachable_labels: List[str] = []
    shared_fetch_call_count = 0
    shared_custom_transport_adapter_call_count = 0
    closure_projection_producer_call_count = 0
    work: List[tuple[str, str]] = [("method", name) for name in entrypoints]
    visited: set[tuple[str, str]] = set()
    while work:
        scope, name = work.pop()
        key = (scope, name)
        if key in visited:
            continue
        visited.add(key)
        node = method_nodes.get(name) if scope == "method" else module_function_nodes.get(name)
        if node is None:
            continue
        reachable_labels.append(f"{scope}:{name}")
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            dotted = _call_dotted_name(child.func)
            leaf = dotted.rsplit(".", 1)[-1] if dotted else ""
            if leaf == "retain_state_law_frontier_closure_projection":
                closure_projection_producer_call_count += 1
            if dotted.startswith("self.") and leaf in method_nodes:
                work.append(("method", leaf))
            elif isinstance(child.func, ast.Name) and leaf in module_function_nodes:
                work.append(("module", leaf))

            kind = _transport_call_kind(child)
            if kind == "shared_base_fetch":
                if leaf in method_nodes:
                    candidates.append(
                        {
                            "call": dotted,
                            "kind": "shared_base_fetch_overridden",
                            "line": int(getattr(child, "lineno", 0) or 0) or None,
                            "parser_scope": f"{scope}:{name}",
                            "source": source_path.name,
                        }
                    )
                    continue
                shared_fetch_call_count += 1
                if leaf == "_fetch_parser_input_with_transport":
                    shared_custom_transport_adapter_call_count += 1
                continue
            if not kind:
                continue
            # A local helper is traversed to its implementation; only report
            # the call itself when its implementation is opaque to this file.
            if kind == "custom_fetch_helper" and (
                leaf in method_nodes or leaf in module_function_nodes
            ):
                continue
            candidates.append(
                {
                    "call": dotted,
                    "kind": kind,
                    "line": int(getattr(child, "lineno", 0) or 0) or None,
                    "parser_scope": f"{scope}:{name}",
                    "source": source_path.name,
                }
            )

    candidates = sorted(
        {
            (item["kind"], item["line"], item.get("call"), item["parser_scope"]): item
            for item in candidates
        }.values(),
        key=lambda item: (
            int(item.get("line") or 0),
            str(item.get("kind") or ""),
            str(item.get("call") or ""),
        ),
    )
    shared_frontier_bridge = bool(
        "fetch_official" in method_nodes
        and callable(
            getattr(
                scraper_type,
                "_supports_shared_official_frontier_bridge",
                None,
            )
        )
    )
    if shared_frontier_bridge and closure_projection_producer_call_count == 0:
        closure_projection_producer_call_count = 1
    shared_frontier_live_transport_candidates: List[Dict[str, Any]] = []
    if shared_frontier_bridge:
        live_work: List[tuple[str, str]] = [("method", "fetch_official")]
        live_visited: set[tuple[str, str]] = set()
        while live_work:
            live_scope, live_name = live_work.pop()
            live_key = (live_scope, live_name)
            if live_key in live_visited:
                continue
            live_visited.add(live_key)
            live_node = (
                method_nodes.get(live_name)
                if live_scope == "method"
                else module_function_nodes.get(live_name)
            )
            if live_node is None:
                continue
            for child in ast.walk(live_node):
                if not isinstance(child, ast.Call):
                    continue
                dotted = _call_dotted_name(child.func)
                leaf = dotted.rsplit(".", 1)[-1] if dotted else ""
                if dotted.startswith("self.") and leaf in method_nodes:
                    live_work.append(("method", leaf))
                elif isinstance(child.func, ast.Name) and leaf in module_function_nodes:
                    live_work.append(("module", leaf))
                kind = _transport_call_kind(child)
                if not kind or kind == "shared_base_fetch":
                    continue
                if kind == "custom_fetch_helper" and (
                    leaf in method_nodes or leaf in module_function_nodes
                ):
                    continue
                shared_frontier_live_transport_candidates.append(
                    {
                        "call": dotted,
                        "kind": kind,
                        "line": int(getattr(child, "lineno", 0) or 0) or None,
                        "parser_scope": f"{live_scope}:{live_name}",
                        "source": source_path.name,
                    }
                )
        shared_frontier_live_transport_candidates = sorted(
            {
                (
                    item["kind"],
                    item["line"],
                    item.get("call"),
                    item["parser_scope"],
                ): item
                for item in shared_frontier_live_transport_candidates
            }.values(),
            key=lambda item: (
                int(item.get("line") or 0),
                str(item.get("kind") or ""),
                str(item.get("call") or ""),
            ),
        )
    return {
        "complete": not candidates,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "closure_projection_producer_call_count": (
            closure_projection_producer_call_count
        ),
        "closure_projection_producer_present": bool(
            closure_projection_producer_call_count
        ),
        "closure_projection_producer_kind": (
            "state_specific"
            if not shared_frontier_bridge
            else "shared_base_state_owned_official_catalog_bridge"
        ),
        "inventory_scope": "parser_reachable_static_call_graph",
        "parser_entrypoints": entrypoints,
        "reachable_scopes": sorted(reachable_labels),
        "schema_version": "state-laws-transport-bypass-inventory-v1",
        "shared_frontier_live_transport_candidate_count": len(
            shared_frontier_live_transport_candidates
        ),
        "shared_frontier_live_transport_candidates": (
            shared_frontier_live_transport_candidates
        ),
        "shared_frontier_retained_replay_guard": (
            "exact_ledger_input_reparse_with_process_global_network_deny"
            if shared_frontier_bridge
            else None
        ),
        "shared_custom_transport_adapter_call_count": (
            shared_custom_transport_adapter_call_count
        ),
        "shared_fetch_call_count": shared_fetch_call_count,
        "source": source_path.name,
    }


def inventory_registered_state_scraper_transport_bypasses(
    states: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Inventory parser-reachable transport gaps for registered scrapers."""

    from .state_scrapers import StateScraperRegistry

    requested = [
        str(code or "").strip().upper()
        for code in (states or tuple(US_STATES))
        if str(code or "").strip().upper() in US_STATES
    ]
    jurisdictions: Dict[str, Any] = {}
    for state_code in dict.fromkeys(requested):
        scraper_type = StateScraperRegistry.get_scraper_class(state_code)
        if scraper_type is None:
            jurisdictions[state_code] = {
                "candidate_count": 1,
                "candidates": [
                    {
                        "kind": "scraper_unregistered",
                        "line": None,
                        "source": None,
                    }
                ],
                "complete": False,
                "schema_version": "state-laws-transport-bypass-inventory-v1",
            }
        else:
            jurisdictions[state_code] = inventory_state_scraper_transport_bypasses(
                scraper_type
            )
    gap_jurisdictions = [
        code
        for code in requested
        if not bool((jurisdictions.get(code) or {}).get("complete"))
    ]
    closure_projection_missing_jurisdictions = [
        code
        for code in requested
        if not bool(
            (jurisdictions.get(code) or {}).get(
                "closure_projection_producer_present"
            )
        )
    ]
    return {
        "candidate_count": sum(
            int((row or {}).get("candidate_count") or 0)
            for row in jurisdictions.values()
        ),
        "complete": not gap_jurisdictions and len(jurisdictions) == len(set(requested)),
        "closure_projection_missing_jurisdictions": (
            closure_projection_missing_jurisdictions
        ),
        "closure_projection_producer_count": (
            len(requested) - len(closure_projection_missing_jurisdictions)
        ),
        "gap_jurisdictions": gap_jurisdictions,
        "jurisdiction_count": len(jurisdictions),
        "jurisdictions": jurisdictions,
        "publication_evidence_complete": bool(
            not gap_jurisdictions
            and not closure_projection_missing_jurisdictions
            and len(jurisdictions) == len(set(requested))
        ),
        "schema_version": "state-laws-registered-transport-bypass-inventory-v1",
    }


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _env_full_corpus_enabled() -> bool:
    return str(os.getenv("STATE_SCRAPER_FULL_CORPUS", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _derive_bounded_scraper_timeouts(per_state_timeout_seconds: float) -> Dict[str, float]:
    bounded_timeout = max(0.0, float(per_state_timeout_seconds or 0.0))
    if bounded_timeout <= 0.0:
        return {"code_timeout_seconds": 0.0, "fetch_timeout_seconds": 0.0}

    code_fraction = max(0.05, min(0.99, _env_float("STATE_SCRAPER_CODE_TIMEOUT_FRACTION", 0.8)))
    raw_code_cap = _env_float("STATE_SCRAPER_CODE_TIMEOUT_CAP_SECONDS", 0.0)
    code_cap = bounded_timeout if raw_code_cap <= 0.0 else max(45.0, raw_code_cap)
    code_timeout = max(0.1, min(bounded_timeout * code_fraction, code_cap))

    fetch_fraction = max(0.05, min(0.99, _env_float("STATE_SCRAPER_FETCH_TIMEOUT_FRACTION", 1.0 / 3.0)))
    fetch_cap = max(12.0, _env_float("STATE_SCRAPER_FETCH_TIMEOUT_CAP_SECONDS", 120.0))
    fetch_timeout = max(0.1, min(code_timeout * fetch_fraction, fetch_cap))

    return {
        "code_timeout_seconds": float(code_timeout),
        "fetch_timeout_seconds": float(fetch_timeout),
    }


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        text = str(value or "").strip()
        if not text:
            return int(default)
        return int(float(text))
    except Exception:
        return int(default)


def _coerce_checkpoint_updated_at(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except Exception:
            return ""
    return str(value).strip()


def _checkpoint_updated_at_to_timestamp(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return 0.0
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _partial_checkpoint_path_for_state(
    state_code: str,
    *,
    checkpoint_dir: Optional[str] = None,
) -> Optional[Path]:
    checkpoint_dir = (
        str(checkpoint_dir).strip()
        if checkpoint_dir is not None
        else str(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR") or "").strip()
    )
    if not checkpoint_dir:
        return None
    try:
        return Path(checkpoint_dir).expanduser().resolve() / f"STATE-{state_code.upper()}-partial.json"
    except Exception:
        return None


def _partial_checkpoint_progress_signature(payload: Mapping[str, Any]) -> tuple[Any, ...]:
    progress = payload.get("progress") if isinstance(payload.get("progress"), Mapping) else {}
    # Keep the timeout "progress" signature strictly numeric so stage-label
    # churn does not look like forward progress when counters are flat.
    counters = (
        _safe_int(payload.get("statutes_count"), 0),
        _safe_int(progress.get("scanned_candidates"), 0),
        _safe_int(progress.get("discovered_candidates"), 0),
        _safe_int(progress.get("scanned_history_urls"), 0),
        _safe_int(progress.get("discovered_history_urls"), 0),
        _safe_int(progress.get("scanned_laws"), 0),
        _safe_int(progress.get("discovered_laws"), 0),
        _safe_int(progress.get("titles_scanned"), 0),
        _safe_int(progress.get("discovered_titles"), 0),
        _safe_int(progress.get("chapters_scanned"), 0),
        _safe_int(progress.get("discovered_chapters"), 0),
        _safe_int(progress.get("sections_scanned"), 0),
        _safe_int(progress.get("discovered_sections"), 0),
        _safe_int(progress.get("codes_completed"), _safe_int(payload.get("codes_completed"), 0)),
        _safe_int(progress.get("codes_total"), _safe_int(payload.get("codes_total"), 0)),
    )
    return counters


def _checkpoint_has_explicit_noncompletion(payload: Mapping[str, Any]) -> bool:
    """Return whether a checkpoint explicitly says its frontier is incomplete.

    Equal scan counters are only a heuristic.  State scrapers can finish
    visiting every discovered parent unit and still reject the resulting
    frontier after typed reconciliation.  Those explicit failure signals must
    fence checkpoint promotion even when the generic counters are equal.
    """

    progress = payload.get("progress") if isinstance(payload.get("progress"), Mapping) else {}
    stage = str(payload.get("stage_label") or "").strip().lower()
    if stage == "incomplete" or stage.endswith(":incomplete"):
        return True

    for container in (payload, progress):
        for key, value in container.items():
            normalized_key = str(key or "").strip().lower()
            if normalized_key == "completion_status" or normalized_key.endswith(
                "_completion_status"
            ):
                status = str(value or "").strip().lower()
                if status == "incomplete" or status.endswith(":incomplete"):
                    return True
            if normalized_key == "unresolved_count" or normalized_key.endswith(
                "_unresolved_count"
            ):
                if _safe_int(value, 0) > 0:
                    return True

        code_failures = container.get("code_failures")
        if isinstance(code_failures, Mapping):
            if code_failures:
                return True
        elif isinstance(code_failures, (list, tuple, set, frozenset)):
            if len(code_failures) > 0:
                return True
        elif str(code_failures or "").strip():
            return True

    return False


def _checkpoint_progress_signal(payload: Mapping[str, Any]) -> Dict[str, Any]:
    progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}

    scanned_candidates = _safe_int(
        payload.get("scanned_candidates", progress.get("scanned_candidates")),
        0,
    )
    discovered_candidates = _safe_int(
        payload.get("discovered_candidates", progress.get("discovered_candidates")),
        0,
    )
    scanned_history_urls = _safe_int(
        payload.get("scanned_history_urls", progress.get("scanned_history_urls")),
        0,
    )
    discovered_history_urls = _safe_int(
        payload.get("discovered_history_urls", progress.get("discovered_history_urls")),
        0,
    )
    scanned_laws = _safe_int(
        payload.get("scanned_laws", progress.get("scanned_laws")),
        0,
    )
    discovered_laws = _safe_int(
        payload.get("discovered_laws", progress.get("discovered_laws")),
        0,
    )
    titles_scanned = _safe_int(
        payload.get("titles_scanned", progress.get("titles_scanned")),
        0,
    )
    discovered_titles = _safe_int(
        payload.get("discovered_titles", progress.get("discovered_titles")),
        0,
    )
    chapters_scanned = _safe_int(
        payload.get("chapters_scanned", progress.get("chapters_scanned")),
        0,
    )
    discovered_chapters = _safe_int(
        payload.get("discovered_chapters", progress.get("discovered_chapters")),
        0,
    )
    sections_scanned = _safe_int(
        payload.get("sections_scanned", progress.get("sections_scanned")),
        0,
    )
    discovered_sections = _safe_int(
        payload.get("discovered_sections", progress.get("discovered_sections")),
        0,
    )
    codes_completed = _safe_int(progress.get("codes_completed", payload.get("codes_completed")), 0)
    codes_total = _safe_int(progress.get("codes_total", payload.get("codes_total")), 0)

    signal_kind = ""
    scanned = 0
    discovered = 0
    populated_signals: List[tuple[str, int, int]] = []
    best_with_scanned: Optional[tuple[str, int, int]] = None
    best_any: Optional[tuple[str, int, int]] = None
    for kind, scanned_value, discovered_value in (
        ("candidate_scan", scanned_candidates, discovered_candidates),
        ("history_scan", scanned_history_urls, discovered_history_urls),
        ("law_page_scan", scanned_laws, discovered_laws),
        ("title_scan", titles_scanned, discovered_titles),
        ("chapter_scan", chapters_scanned, discovered_chapters),
        ("section_scan", sections_scanned, discovered_sections),
    ):
        if discovered_value <= 0:
            continue
        candidate = (kind, max(0, int(scanned_value)), int(discovered_value))
        populated_signals.append(candidate)
        if (
            best_any is None
            or candidate[2] > best_any[2]
            or (candidate[2] == best_any[2] and candidate[1] > best_any[1])
        ):
            best_any = candidate
        if candidate[1] > 0 and (
            best_with_scanned is None
            or candidate[2] > best_with_scanned[2]
            or (candidate[2] == best_with_scanned[2] and candidate[1] > best_with_scanned[1])
        ):
            best_with_scanned = candidate
    # ``codes_completed`` is a coarse lifecycle counter: many scrapers leave
    # it at 0 until the synchronous call returns even after their concrete URL
    # frontier is closed.  Use it only when no concrete scan dimension exists;
    # otherwise it would prevent legitimate retained-checkpoint promotion.
    # Parent title/chapter dimensions remain part of ``populated_signals`` and
    # therefore cannot be masked by a locally complete section scan.
    if not populated_signals and codes_total > 0:
        populated_signals.append(("codes_progress", max(0, codes_completed), codes_total))
        best_any = populated_signals[0]
        best_with_scanned = best_any if codes_completed > 0 else None
    selected = best_with_scanned or best_any
    if selected is not None:
        signal_kind, scanned, discovered = selected

    signal_found = bool(signal_kind)
    work_remaining: Optional[bool] = None
    if signal_found:
        # A nested scraper can finish every section discovered so far while
        # still having unvisited parent titles or chapters.  Keep the largest
        # populated dimension as the primary diagnostic signal, but only call
        # the checkpoint complete when *every* populated frontier dimension is
        # closed.  Otherwise a locally complete child scan can detach a live
        # daemon and promote an incomplete checkpoint.
        work_remaining = any(
            int(scanned_value) < int(discovered_value)
            for _kind, scanned_value, discovered_value in populated_signals
        )
    if _checkpoint_has_explicit_noncompletion(payload):
        work_remaining = True

    return {
        "signal_found": signal_found,
        "signal_kind": signal_kind,
        "work_remaining": work_remaining,
        "progress_scanned": int(scanned) if signal_found else None,
        "progress_discovered": int(discovered) if signal_found else None,
        "checkpoint_counters": {
            "scanned_candidates": scanned_candidates,
            "discovered_candidates": discovered_candidates,
            "scanned_history_urls": scanned_history_urls,
            "discovered_history_urls": discovered_history_urls,
            "scanned_laws": scanned_laws,
            "discovered_laws": discovered_laws,
            "titles_scanned": titles_scanned,
            "discovered_titles": discovered_titles,
            "chapters_scanned": chapters_scanned,
            "discovered_chapters": discovered_chapters,
            "sections_scanned": sections_scanned,
            "discovered_sections": discovered_sections,
            "codes_completed": codes_completed,
            "codes_total": codes_total,
        },
    }


def _checkpoint_stage_is_complete(stage_label: Any) -> bool:
    stage = str(stage_label or "").strip().lower()
    return bool(
        stage == "complete"
        or stage.endswith(":complete")
        or stage.startswith("scrape_all:complete")
    )


def _checkpoint_parse_max_bytes() -> int:
    raw = str(os.getenv("STATE_SCRAPER_TIMEOUT_CHECKPOINT_PARSE_MAX_BYTES", "") or "").strip()
    try:
        value = int(raw) if raw else (8 * 1024 * 1024)
    except Exception:
        value = 8 * 1024 * 1024
    return max(64 * 1024, min(128 * 1024 * 1024, value))


def _checkpoint_metadata_read_bytes() -> int:
    raw = str(os.getenv("STATE_SCRAPER_TIMEOUT_CHECKPOINT_META_READ_BYTES", "") or "").strip()
    try:
        value = int(raw) if raw else (256 * 1024)
    except Exception:
        value = 256 * 1024
    return max(8 * 1024, min(8 * 1024 * 1024, value))


def _quick_read_partial_checkpoint_meta(path: Path) -> Dict[str, Any]:
    try:
        stat_obj = path.stat()
        size = int(stat_obj.st_size)
        mtime = float(stat_obj.st_mtime)
    except Exception:
        return {
            "size_bytes": 0,
            "mtime_ts": 0.0,
            "stage_label": "",
            "stage_complete": False,
            "statutes_count": 0,
            "updated_ts": 0.0,
        }

    read_bytes = min(size, _checkpoint_metadata_read_bytes())
    text = ""
    if read_bytes > 0:
        try:
            with path.open("rb") as handle:
                text = handle.read(read_bytes).decode("utf-8", errors="ignore")
        except Exception:
            text = ""

    stage_label = ""
    statutes_count = 0
    updated_ts = 0.0

    if text:
        stage_match = _CHECKPOINT_STAGE_LABEL_RE.search(text)
        if stage_match:
            stage_label = str(stage_match.group(1) or "").strip()

        count_match = _CHECKPOINT_STATUTES_COUNT_RE.search(text)
        if count_match:
            statutes_count = _safe_int(count_match.group(1), 0)

        updated_str_match = _CHECKPOINT_UPDATED_AT_STR_RE.search(text)
        if updated_str_match:
            updated_ts = _checkpoint_updated_at_to_timestamp(updated_str_match.group(1))
        if updated_ts <= 0.0:
            updated_num_match = _CHECKPOINT_UPDATED_AT_NUM_RE.search(text)
            if updated_num_match:
                updated_ts = _checkpoint_updated_at_to_timestamp(updated_num_match.group(1))

    if updated_ts <= 0.0:
        updated_ts = mtime

    return {
        "size_bytes": size,
        "mtime_ts": mtime,
        "stage_label": stage_label,
        "stage_complete": _checkpoint_stage_is_complete(stage_label),
        "statutes_count": max(0, int(statutes_count)),
        "updated_ts": float(updated_ts),
    }


def _read_partial_checkpoint_activity(
    state_code: str,
    *,
    checkpoint_dir: Optional[str] = None,
) -> Dict[str, Any]:
    path = _partial_checkpoint_path_for_state(
        state_code,
        checkpoint_dir=checkpoint_dir,
    )
    if path is None or not path.exists():
        return {
            "path": str(path) if path else "",
            "updated_ts": 0.0,
            "signature": tuple(),
            "signature_mode": "none",
            "stage_label": "",
            "stage_complete": False,
            "signal_found": False,
            "signal_kind": "",
            "work_remaining": None,
            "progress_scanned": None,
            "progress_discovered": None,
            "statutes_count": 0,
            "size_bytes": 0,
            "mtime_ts": 0.0,
        }

    quick_meta = _quick_read_partial_checkpoint_meta(path)
    size_bytes = _safe_int(quick_meta.get("size_bytes"), 0)
    parse_payload = size_bytes > 0 and size_bytes <= _checkpoint_parse_max_bytes()
    if not parse_payload:
        signature = (
            _safe_int(quick_meta.get("statutes_count"), 0),
            _safe_int(quick_meta.get("size_bytes"), 0),
            str(quick_meta.get("stage_label") or ""),
        )
        return {
            "path": str(path),
            "updated_ts": float(quick_meta.get("updated_ts") or 0.0),
            "signature": signature,
            "signature_mode": "meta",
            "stage_label": str(quick_meta.get("stage_label") or ""),
            "stage_complete": bool(quick_meta.get("stage_complete")),
            "signal_found": False,
            "signal_kind": "",
            "work_remaining": None,
            "progress_scanned": None,
            "progress_discovered": None,
            "statutes_count": _safe_int(quick_meta.get("statutes_count"), 0),
            "size_bytes": _safe_int(quick_meta.get("size_bytes"), 0),
            "mtime_ts": float(quick_meta.get("mtime_ts") or 0.0),
        }

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        signature = (
            _safe_int(quick_meta.get("statutes_count"), 0),
            _safe_int(quick_meta.get("size_bytes"), 0),
            str(quick_meta.get("stage_label") or ""),
        )
        return {
            "path": str(path),
            "updated_ts": float(quick_meta.get("updated_ts") or 0.0),
            "signature": signature,
            "signature_mode": "meta",
            "stage_label": str(quick_meta.get("stage_label") or ""),
            "stage_complete": bool(quick_meta.get("stage_complete")),
            "signal_found": False,
            "signal_kind": "",
            "work_remaining": None,
            "progress_scanned": None,
            "progress_discovered": None,
            "statutes_count": _safe_int(quick_meta.get("statutes_count"), 0),
            "size_bytes": _safe_int(quick_meta.get("size_bytes"), 0),
            "mtime_ts": float(quick_meta.get("mtime_ts") or 0.0),
        }

    updated_ts = _checkpoint_updated_at_to_timestamp(payload.get("updated_at"))
    if updated_ts <= 0.0:
        updated_ts = float(quick_meta.get("mtime_ts") or 0.0)
    signature: tuple[Any, ...] = tuple()
    stage_label = str(quick_meta.get("stage_label") or "")
    stage_complete = bool(quick_meta.get("stage_complete"))
    statutes_count = _safe_int(quick_meta.get("statutes_count"), 0)
    signal = {
        "signal_found": False,
        "signal_kind": "",
        "work_remaining": None,
        "progress_scanned": None,
        "progress_discovered": None,
    }
    if isinstance(payload, Mapping):
        signature = _partial_checkpoint_progress_signature(payload)
        stage_label = str(payload.get("stage_label") or stage_label).strip()
        stage_complete = _checkpoint_stage_is_complete(stage_label)
        statutes_count = _safe_int(payload.get("statutes_count"), statutes_count)
        signal = _checkpoint_progress_signal(payload)
    if not signal.get("signal_found") and stage_complete and statutes_count > 0:
        signal = {
            "signal_found": True,
            "signal_kind": "checkpoint_stage_complete",
            "work_remaining": False,
            "progress_scanned": statutes_count,
            "progress_discovered": statutes_count,
        }
    return {
        "path": str(path),
        "updated_ts": updated_ts,
        "signature": signature,
        "signature_mode": "full",
        "stage_label": stage_label,
        "stage_complete": stage_complete,
        "signal_found": bool(signal.get("signal_found")),
        "signal_kind": str(signal.get("signal_kind") or ""),
        "work_remaining": signal.get("work_remaining"),
        "progress_scanned": signal.get("progress_scanned"),
        "progress_discovered": signal.get("progress_discovered"),
        "statutes_count": max(0, int(statutes_count)),
        "size_bytes": _safe_int(quick_meta.get("size_bytes"), 0),
        "mtime_ts": float(quick_meta.get("mtime_ts") or 0.0),
    }


def _derive_timeout_diagnostics_from_checkpoint_payload(
    *,
    payload: Dict[str, Any],
    error_msg: str,
    statutes_count: int,
) -> Dict[str, Any]:
    timed_out = "timed out" in str(error_msg or "").lower()
    signal = _checkpoint_progress_signal(payload)
    signal_found = bool(signal.get("signal_found"))
    signal_kind = str(signal.get("signal_kind") or "")
    work_remaining = signal.get("work_remaining")
    scanned = signal.get("progress_scanned")
    discovered = signal.get("progress_discovered")

    stage_label = str(payload.get("stage_label") or "").strip().lower()
    stage_indicates_complete = bool(
        stage_label == "complete"
        or stage_label.endswith(":complete")
        or stage_label.startswith("scrape_all:complete")
    )
    if (not signal_found) and stage_indicates_complete and int(statutes_count) > 0:
        signal_kind = "checkpoint_stage_complete"
        signal_found = True
        scanned = int(statutes_count)
        discovered = int(statutes_count)
        work_remaining = False

    coverage_ratio: Optional[float] = None
    if signal_found and discovered > 0:
        coverage_ratio = round(min(1.0, float(scanned) / float(discovered)), 4)

    if timed_out and signal_found and work_remaining is True:
        classification = "timeout_while_work_remaining"
    elif timed_out and signal_found and work_remaining is False:
        classification = "timeout_with_no_detectable_remaining_work"
    elif timed_out and signal_found:
        classification = "timeout_with_progress_signal_unknown_completion"
    elif timed_out:
        classification = "timeout_without_progress_signal"
    elif signal_found and work_remaining is False:
        classification = "error_with_no_detectable_remaining_work"
    elif signal_found and work_remaining is True:
        classification = "error_while_work_remaining"
    else:
        classification = "error_without_progress_signal"

    return {
        "timed_out": bool(timed_out),
        "classification": classification,
        "signal_found": signal_found,
        "signal_kind": signal_kind,
        "work_remaining": work_remaining,
        "progress_scanned": int(scanned) if signal_found else None,
        "progress_discovered": int(discovered) if signal_found else None,
        "coverage_ratio": coverage_ratio,
        "checkpoint_updated_at": _coerce_checkpoint_updated_at(payload.get("updated_at")),
        "checkpoint_stage_label": str(payload.get("stage_label") or "").strip(),
        "checkpoint_counters": dict(signal.get("checkpoint_counters") or {}),
    }


def _extract_statute_quality_fields(statute: Any) -> Dict[str, str]:
    if isinstance(statute, dict):
        return {
            "full_text": str(statute.get("full_text") or statute.get("text") or ""),
            "section_number": str(statute.get("section_number") or statute.get("sectionNumber") or ""),
            "section_name": str(statute.get("section_name") or statute.get("sectionName") or ""),
            "source_url": str(statute.get("source_url") or statute.get("sourceUrl") or ""),
        }

    return {
        "full_text": str(getattr(statute, "full_text", "") or ""),
        "section_number": str(getattr(statute, "section_number", "") or ""),
        "section_name": str(getattr(statute, "section_name", "") or ""),
        "source_url": str(getattr(statute, "source_url", "") or ""),
    }


def _is_source_bound_hawaii_operative_record(statute: Any) -> bool:
    structured_data = (
        statute.get("structured_data")
        if isinstance(statute, dict)
        else getattr(statute, "structured_data", None)
    )
    if (
        not isinstance(structured_data, Mapping)
        or structured_data.get("source_kind") != "official_hawaii_hrs_html"
    ):
        return False
    from .state_scrapers.hawaii_section import (
        is_source_bound_operative_hawaii_statute,
    )

    return is_source_bound_operative_hawaii_statute(statute)


def _is_scaffold_or_navigation_record(statute: Any) -> bool:
    fields = _extract_statute_quality_fields(statute)
    text = fields["full_text"].strip()
    section_number = fields["section_number"].strip()
    section_name = fields["section_name"].strip()
    source_url = fields["source_url"].strip().lower()

    fallback_section = bool(_QUALITY_SECTION_FALLBACK_RE.match(section_number))
    has_statute_signal = bool(
        _QUALITY_SECTION_SIGNAL_RE.search(text)
        or _QUALITY_SECTION_SIGNAL_RE.search(section_name)
        or _QUALITY_SECTION_NUMBER_RE.match(section_number)
    )
    nav_like_text = bool(_QUALITY_NAV_RE.search(text) or _QUALITY_NAV_RE.search(section_name))
    nav_like_url = bool(_QUALITY_NAV_URL_RE.search(source_url))

    if _QUALITY_SCAFFOLD_TEXT_RE.match(text):
        return True

    if _is_source_bound_hawaii_operative_record(statute):
        return False

    if fallback_section and nav_like_text and not has_statute_signal:
        return True

    if nav_like_url and not has_statute_signal:
        return True

    if nav_like_text and not has_statute_signal and len(text) < 1200:
        return True

    return False


def _has_quality_legal_signal(statute: Any) -> bool:
    fields = _extract_statute_quality_fields(statute)
    text = fields["full_text"]
    section_number = fields["section_number"]
    section_name = fields["section_name"]
    hay = " ".join([text, section_name, section_number])

    if _QUALITY_SECTION_SIGNAL_RE.search(text) or _QUALITY_SECTION_SIGNAL_RE.search(section_name):
        return True
    if _QUALITY_SECTION_NUMBER_RE.match(section_number):
        return True
    if len(_QUALITY_LEGAL_METADATA_RE.findall(hay)) >= 2:
        return True
    return False

# US States and territories
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia"
}

CANONICAL_PRODUCTION_JURISDICTIONS = frozenset(US_STATES.keys())
EXPECTED_PRODUCTION_JURISDICTION_COUNT = 51


class SubsetReleaseError(ValueError):
    """Raised when a production release path is asked to accept a subset corpus."""


def reject_subset_release(
    states: Sequence[str],
    *,
    context: str = "state_laws_scraper production release",
) -> List[str]:
    """Fail closed unless ``states`` is exactly the sealed 51-jurisdiction set.

    A nonzero, error-free requested subset must never authorize a production
    full-corpus release (LCR-007).
    """
    normalized: List[str] = []
    seen = set()
    for item in states:
        code = str(item or "").strip().upper()
        if not code or code in seen:
            continue
        normalized.append(code)
        seen.add(code)
    observed = set(normalized)
    if observed != CANONICAL_PRODUCTION_JURISDICTIONS:
        missing = sorted(CANONICAL_PRODUCTION_JURISDICTIONS - observed)
        extra = sorted(observed - CANONICAL_PRODUCTION_JURISDICTIONS)
        raise SubsetReleaseError(
            f"subset release rejected for {context}: "
            f"count={len(observed)} (expected {EXPECTED_PRODUCTION_JURISDICTION_COUNT}); "
            f"missing={missing}; extra={extra}"
        )
    if "DC" not in observed:
        raise SubsetReleaseError(f"subset release rejected for {context}: DC is required")
    return normalized


def _get_justia_state_slug(state_code: str) -> str:
    """Build the Justia state slug from canonical state name."""
    state_name = US_STATES.get(state_code.upper(), state_code)
    slug = state_name.strip().lower().replace("&", "and")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


async def list_state_jurisdictions() -> Dict[str, Any]:
    """Get list of all US state jurisdictions.
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - states: Dictionary mapping state codes to names
            - count: Number of states/territories
            - error: Error message (if failed)
    """
    try:
        return {
            "status": "success",
            "states": US_STATES,
            "count": len(US_STATES),
            "note": "Includes all 50 US states and DC"
        }
    except Exception as e:
        logger.error(f"Failed to get state jurisdictions: {e}")
        return {
            "status": "error",
            "error": str(e),
            "states": {},
            "count": 0
        }


async def scrape_state_laws(
    states: Optional[List[str]] = None,
    legal_areas: Optional[List[str]] = None,
    output_format: str = "json",
    include_metadata: bool = True,
    rate_limit_delay: float = 2.0,
    max_statutes: Optional[int] = None,
    use_state_specific_scrapers: bool = True,
    allow_justia_fallback: bool = True,
    output_dir: Optional[str] = None,
    write_jsonld: bool = True,
    strict_full_text: bool = False,
    min_full_text_chars: int = DEFAULT_MIN_FULL_TEXT_CHARS,
    hydrate_statute_text: bool = True,
    parallel_workers: int = 6,
    per_state_retry_attempts: int = 1,
    retry_zero_statute_states: bool = True,
    per_state_timeout_seconds: float = 480.0,
    state_completion_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    retain_state_data: Optional[bool] = None,
) -> Dict[str, Any]:
    """Scrape state statutes and build a structured dataset.
    
    This function now uses state-specific scrapers that go directly to
    each state's official legislative website and normalize the data
    into a consistent schema.
    
    Args:
        states: List of state codes to scrape (e.g., ["CA", "NY", "TX"]).
                If None or ["all"], scrapes all states.
        legal_areas: Specific areas of law to focus on (e.g., ["criminal", "civil", "family"])
        output_format: Output format - "json" or "parquet"
        include_metadata: Include statute metadata (effective dates, amendments, etc.)
        rate_limit_delay: Delay between requests in seconds (default 2.0, higher for state sites)
        max_statutes: Maximum number of statutes to scrape
        use_state_specific_scrapers: Use state-specific scrapers (True) or fallback to Justia (False)
        allow_justia_fallback: Whether empty/failed state-specific runs may fall back to Justia
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - data: Scraped state statutes in normalized schema
            - metadata: Scraping metadata
            - output_format: Format of the data
            - error: Error message (if failed)
    """
    try:
        # Validate and process states
        if states is None or "all" in states:
            selected_states = list(US_STATES.keys())
        else:
            selected_states = [s.upper() for s in states if s.upper() in US_STATES]
            if not selected_states:
                return {
                    "status": "error",
                    "error": "No valid states specified",
                    "data": [],
                    "metadata": {}
                }
        
        logger.info(f"Starting state laws scraping for states: {selected_states}")
        start_time = time.time()
        
        # Import required libraries
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError as ie:
            return {
                "status": "error",
                "error": f"Required library not available: {ie}. Install with: pip install requests beautifulsoup4",
                "data": [],
                "metadata": {}
            }
        
        scraped_statutes = []
        statutes_count = 0
        errors = []
        warnings = []
        zero_statute_states = []
        quality_by_state: Dict[str, Dict[str, Any]] = {}
        low_quality_states: List[str] = []
        fetch_analytics_by_state: Dict[str, Dict[str, Any]] = {}
        state_run_environment_binding = _capture_state_law_run_environment()

        parallel_workers = max(1, int(parallel_workers or 1))
        per_state_retry_attempts = max(0, int(per_state_retry_attempts or 0))
        if retain_state_data is None:
            retain_state_data = str(os.getenv("STATE_SCRAPER_RETAIN_STATE_DATA", "1")).strip().lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        
        # Try to use state-specific scrapers if enabled
        if use_state_specific_scrapers:
            try:
                prior_bounded_env = {
                    "STATE_SCRAPER_CODE_TIMEOUT_SECONDS": os.environ.get("STATE_SCRAPER_CODE_TIMEOUT_SECONDS"),
                    "STATE_SCRAPER_FETCH_TIMEOUT_SECONDS": os.environ.get("STATE_SCRAPER_FETCH_TIMEOUT_SECONDS"),
                    "STATE_SCRAPER_MAX_STATUTES": os.environ.get("STATE_SCRAPER_MAX_STATUTES"),
                    "STATE_SCRAPER_BOUNDED_DIRECT_ONLY": os.environ.get("STATE_SCRAPER_BOUNDED_DIRECT_ONLY"),
                    "STATE_SCRAPER_GLOBAL_BOUNDED_ENV": os.environ.get("STATE_SCRAPER_GLOBAL_BOUNDED_ENV"),
                }
                bounded_timeout = max(0.0, float(per_state_timeout_seconds or 0.0))
                use_global_bounded_env = bool(max_statutes and int(max_statutes) > 0 and bounded_timeout > 0)
                if use_global_bounded_env:
                    timeouts = _derive_bounded_scraper_timeouts(bounded_timeout)
                    code_timeout = max(0.1, float(timeouts.get("code_timeout_seconds") or 0.0))
                    fetch_timeout = max(0.1, float(timeouts.get("fetch_timeout_seconds") or 0.0))
                    disable_code_timeout_with_checkpoint = str(
                        os.environ.get("STATE_SCRAPER_DISABLE_CODE_TIMEOUT_WITH_CHECKPOINT", "1") or "1"
                    ).strip().lower() in {"1", "true", "yes", "on"}
                    checkpoint_dir_configured = bool(
                        str(os.environ.get("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", "") or "").strip()
                    )
                    if disable_code_timeout_with_checkpoint and checkpoint_dir_configured:
                        code_timeout = 0.0
                    if code_timeout > 0:
                        os.environ["STATE_SCRAPER_CODE_TIMEOUT_SECONDS"] = f"{code_timeout:.3f}"
                    else:
                        os.environ.pop("STATE_SCRAPER_CODE_TIMEOUT_SECONDS", None)
                    os.environ["STATE_SCRAPER_FETCH_TIMEOUT_SECONDS"] = f"{fetch_timeout:.3f}"
                    os.environ["STATE_SCRAPER_MAX_STATUTES"] = str(int(max_statutes))
                    os.environ["STATE_SCRAPER_BOUNDED_DIRECT_ONLY"] = "1"
                    os.environ["STATE_SCRAPER_GLOBAL_BOUNDED_ENV"] = "1"

                async def _run_state(state_code: str) -> Dict[str, Any]:
                    result = await _scrape_state_with_retries(
                        state_code=state_code,
                        legal_areas=legal_areas,
                        rate_limit_delay=rate_limit_delay,
                        max_statutes=max_statutes,
                        strict_full_text=strict_full_text,
                        min_full_text_chars=min_full_text_chars,
                        hydrate_statute_text=hydrate_statute_text,
                        retry_attempts=per_state_retry_attempts,
                        retry_zero_statute_states=retry_zero_statute_states,
                        per_state_timeout_seconds=per_state_timeout_seconds,
                        bound_state_run_environment=state_run_environment_binding,
                    )
                    if state_completion_callback is not None:
                        callback_result = state_completion_callback(result)
                        if inspect.isawaitable(callback_result):
                            await callback_result
                    if not retain_state_data:
                        result = _compact_state_result_for_retention(result)
                    return result

                if parallel_workers <= 1:
                    state_results = []
                    for state_code in selected_states:
                        state_results.append(await _run_state(state_code))
                        if rate_limit_delay > 0:
                            await asyncio.sleep(rate_limit_delay)
                else:
                    semaphore = asyncio.Semaphore(parallel_workers)

                    async def _guarded_run(state_code: str) -> Dict[str, Any]:
                        async with semaphore:
                            return await _run_state(state_code)

                    state_results = await asyncio.gather(*[_guarded_run(code) for code in selected_states])

                if use_global_bounded_env:
                    for key, value in prior_bounded_env.items():
                        if value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = value

                result_by_state = {str(item.get("state_code") or ""): item for item in state_results}
                for state_code in selected_states:
                    item = result_by_state.get(state_code) or {
                        "state_code": state_code,
                        "state_name": US_STATES[state_code],
                        "error": "missing-state-result",
                        "statute_data": {
                            "state_code": state_code,
                            "state_name": US_STATES[state_code],
                            "title": f"{US_STATES[state_code]} Laws",
                            "source": "Official State Legislative Website",
                            "error": "missing-state-result",
                            "scraped_at": datetime.now().isoformat(),
                            "statutes": [],
                        },
                    }

                    statute_data = item.get("statute_data") or {}
                    scraped_statutes.append(statute_data)
                    statutes_count += int(item.get("statutes_count") or 0)

                    state_error = item.get("error")
                    if state_error:
                        errors.append(str(state_error))

                    quality = item.get("quality_metrics") or {}
                    if quality:
                        quality_by_state[state_code] = quality

                    fetch_analytics = item.get("fetch_analytics") or {}
                    if fetch_analytics:
                        fetch_analytics_by_state[state_code] = fetch_analytics

                    for warning in item.get("warnings") or []:
                        warnings.append(str(warning))

                    if bool(item.get("zero_statute")):
                        zero_statute_states.append(state_code)
                    if bool(item.get("low_quality")):
                        low_quality_states.append(state_code)

                if max_statutes and max_statutes > 0:
                    scraped_statutes, statutes_count = _trim_scraped_statutes_to_max(
                        scraped_statutes,
                        int(max_statutes),
                    )
                    quality_by_state = {
                        str(block.get("state_code") or ""): block.get("quality_metrics") or {}
                        for block in scraped_statutes
                        if isinstance(block, dict)
                    }
                    zero_statute_states = [
                        str(block.get("state_code") or "")
                        for block in scraped_statutes
                        if isinstance(block, dict) and len(block.get("statutes") or []) == 0
                    ]
                    low_quality_states = [
                        str(block.get("state_code") or "")
                        for block in scraped_statutes
                        if isinstance(block, dict) and bool(block.get("quality_flag"))
                    ]
                
            except ImportError as e:
                logger.warning(f"State-specific scrapers not available: {e}, falling back to Justia")
                use_state_specific_scrapers = False
        
        # Fallback to Justia-based scraping if state-specific scrapers are disabled or failed
        if allow_justia_fallback and (not use_state_specific_scrapers or not scraped_statutes):
            logger.info("Using Justia fallback scraper")
            
            # State code sources mapping - using Justia as a reliable aggregator
            state_sources = {
                state_code: {
                    "name": US_STATES[state_code],
                    "justia_url": f"https://law.justia.com/codes/{_get_justia_state_slug(state_code)}/",
                    "official_url": _get_official_state_url(state_code)
                }
                for state_code in US_STATES.keys()
            }
            
            # Scrape each selected state
            for state_code in selected_states:
                if max_statutes and statutes_count >= max_statutes:
                    logger.info(f"Reached max_statutes limit of {max_statutes}")
                    break
                
                state_name = US_STATES[state_code]
                logger.info(f"Scraping {state_code}: {state_name}")
                
                try:
                    # Fetch state code overview from Justia
                    state_info = state_sources[state_code]
                    justia_url = state_info["justia_url"]
                    
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                    }
                    
                    response = requests.get(justia_url, headers=headers, timeout=30)
                    response.raise_for_status()
                    
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Extract code titles/sections
                    statutes = []
                    code_links = soup.find_all('a', href=True)
                    
                    for link in code_links:
                        href = link.get('href', '')
                        text = link.get_text(strip=True)
                        
                        # Look for statute/code links
                        if text and len(text) > 10 and (
                            '/codes/' in href or 
                            'title' in text.lower() or 
                            'chapter' in text.lower() or
                            'article' in text.lower()
                        ):
                            # Filter by legal area if specified
                            if legal_areas:
                                area_match = any(area.lower() in text.lower() for area in legal_areas)
                                if not area_match:
                                    continue
                            
                            statute = {
                                "statute_number": text[:100],
                                "title": text[:200],
                                "url": href if href.startswith('http') else f"https://law.justia.com{href}",
                                "legal_area": _identify_legal_area(text, legal_areas),
                            }
                            
                            if include_metadata:
                                statute["scraped_at"] = datetime.now().isoformat()
                                statute["source"] = "Justia"
                            
                            statutes.append(statute)
                            statutes_count += 1
                            
                            if max_statutes and statutes_count >= max_statutes:
                                break
                    
                    statute_data = {
                        "state_code": state_code,
                        "state_name": state_name,
                        "title": f"{state_name} Code",
                        "source": "Justia Legal Database (Fallback)",
                        "source_url": justia_url,
                        "official_url": state_info["official_url"],
                        "scraped_at": datetime.now().isoformat(),
                        "statutes": statutes[:max_statutes] if max_statutes else statutes,
                        "normalized": False
                    }
                    
                    scraped_statutes.append(statute_data)
                    logger.info(f"Successfully scraped {len(statutes)} statutes for {state_name}")
                    
                except Exception as e:
                    error_msg = f"Failed to scrape {state_name}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    
                    # Add minimal data even on error
                    state_info = state_sources.get(state_code, {})
                    statute_data = {
                        "state_code": state_code,
                        "state_name": state_name,
                        "title": f"{state_name} Code",
                        "source": "Justia Legal Database (Fallback)",
                        "source_url": state_info.get("justia_url", ""),
                        "official_url": state_info.get("official_url", ""),
                        "error": str(e),
                        "scraped_at": datetime.now().isoformat(),
                        "statutes": []
                    }
                    scraped_statutes.append(statute_data)
                
                # Rate limiting to be respectful to servers
                time.sleep(rate_limit_delay)
        
        elapsed_time = time.time() - start_time
        
        scraper_info = "State-specific scrapers" if use_state_specific_scrapers else "Justia fallback scraper"
        
        canonical_corpus = get_canonical_legal_corpus("state_laws")
        jsonld_paths: List[str] = []
        if use_state_specific_scrapers and write_jsonld:
            output_root = _resolve_state_output_dir(output_dir)
            jsonld_dir = canonical_corpus.jsonld_dir(str(output_root))
            jsonld_dir.mkdir(parents=True, exist_ok=True)
            jsonld_paths = _write_state_jsonld_files(scraped_statutes, jsonld_dir)

        strict_removed_total = 0
        for block in scraped_statutes:
            if isinstance(block, dict):
                strict_removed_total += int(block.get("strict_removed_count") or 0)

        metadata = {
            "states_scraped": selected_states,
            "states_count": len(selected_states),
            "statutes_count": statutes_count,
            "legal_areas": legal_areas or ["all"],
            "elapsed_time_seconds": elapsed_time,
            "scraped_at": datetime.now().isoformat(),
            "scraper_type": scraper_info,
            "sources": "Official State Legislative Websites" if use_state_specific_scrapers else "Justia Legal Database (https://law.justia.com)",
            "rate_limit_delay": rate_limit_delay,
            "parallel_workers": parallel_workers,
            "per_state_retry_attempts": per_state_retry_attempts,
            "retry_zero_statute_states": retry_zero_statute_states,
            "include_metadata": include_metadata,
            "errors": errors if errors else None,
            "warnings": warnings if warnings else None,
            "zero_statute_states": zero_statute_states if zero_statute_states else None,
            "low_quality_states": low_quality_states if low_quality_states else None,
            "quality_by_state": quality_by_state if quality_by_state else None,
            "coverage_summary": _compute_coverage_summary(
                selected_states=selected_states,
                scraped_statutes=scraped_statutes,
                errors=errors,
            ),
            "fetch_analytics": _aggregate_fetch_analytics(fetch_analytics_by_state),
            "fetch_analytics_by_state": fetch_analytics_by_state if fetch_analytics_by_state else None,
            "etl_readiness": _compute_etl_readiness_summary(scraped_statutes),
            "schema_normalized": use_state_specific_scrapers,
            "canonical_dataset": canonical_corpus.key,
            "canonical_hf_dataset_id": canonical_corpus.hf_dataset_id,
            "jsonld_dir": str(canonical_corpus.jsonld_dir(output_dir)) if (use_state_specific_scrapers and write_jsonld) else None,
            "jsonld_files": jsonld_paths if jsonld_paths else None,
            "strict_full_text": strict_full_text,
            "min_full_text_chars": int(min_full_text_chars),
            "strict_removed_total": strict_removed_total,
            "hydrate_statute_text": hydrate_statute_text,
        }
        
        logger.info(f"Completed state laws scraping: {statutes_count} statutes in {elapsed_time:.2f}s using {scraper_info}")
        
        coverage_summary = metadata.get("coverage_summary") or {}
        requested_closed = bool(coverage_summary.get("full_coverage"))
        full_corpus = bool(coverage_summary.get("full_corpus_coverage"))
        # LCR-007: partial_success must never promote to production full-corpus success.
        if errors or warnings or not requested_closed:
            run_status = "partial_success"
        elif full_corpus:
            run_status = "success"
        else:
            # Requested subset closed cleanly — success for the request only,
            # never a production full-corpus claim.
            run_status = "success"
            metadata["production_release_eligible"] = False
            metadata["coverage_claim"] = "requested_scope_only"

        return {
            "status": run_status,
            "data": scraped_statutes,
            "metadata": metadata,
            "output_format": output_format,
            "production_release_eligible": bool(full_corpus),
        }
        
    except Exception as e:
        logger.error(f"State laws scraping failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {}
        }


def _get_official_state_url(state_code: str) -> str:
    """Get official state legislature URL for a given state code."""
    # Mapping of state codes to their official legislative websites
    official_urls = {
        "CA": "https://leginfo.legislature.ca.gov/",
        "NY": "https://www.nysenate.gov/",
        "TX": "https://capitol.texas.gov/",
        "FL": "http://www.leg.state.fl.us/",
        "IL": "https://www.ilga.gov/",
        "PA": "https://www.legis.state.pa.us/",
        "OH": "https://www.legislature.ohio.gov/",
        "GA": "http://www.legis.ga.gov/",
        "NC": "https://www.ncleg.gov/",
        "MI": "https://www.legislature.mi.gov/",
    }
    
    return official_urls.get(state_code, f"https://legislature.{state_code.lower()}.gov/")


def build_state_law_section_url(
    state_code: str,
    section: str,
    *,
    code_name: Optional[str] = None,
    preferred_host: Optional[str] = None,
) -> str:
    """Build an official section URL for recovery-backed state-law scraping."""
    state = str(state_code or "").strip().upper()
    normalized_section = str(section or "").strip().strip(".")
    code_hint = str(code_name or "").strip()
    host_hint = str(preferred_host or "").strip().lower()
    if not state or not normalized_section:
        return ""

    def _section_parts(separator: str = "-") -> List[str]:
        return [part for part in normalized_section.split(separator) if part]

    known_section_urls = {
        ("AL", "13A-6-2"): "https://alison.legislature.state.al.us/code-of-alabama?section=13A-6-2",
        ("AR", "5-13-201"): "https://law.justia.com/codes/arkansas/title-5/subtitle-2/chapter-13/subchapter-2/section-5-13-201/",
        ("CO", "18-3-204"): "https://colorado.public.law/statutes/crs_18-3-204",
        ("CT", "53a-61"): "https://www.cga.ct.gov/current/pub/chap_952.htm#sec_53a-61",
        ("DE", "11-601"): "https://delcode.delaware.gov/title11/c005/sc02/index.html#601",
        ("GA", "16-5-23"): "https://law.justia.com/codes/georgia/title-16/chapter-5/article-2/section-16-5-23/",
        ("HI", "707-712"): "https://www.capitol.hawaii.gov/hrscurrent/Vol14_Ch0701-0853/HRS0707/HRS_0707-0712.htm",
        ("KY", "508.030"): "https://law.justia.com/codes/kentucky/chapter-508/section-508-030/",
        ("LA", "14:35"): "https://legis.la.gov/legis/Law.aspx?d=78452",
        ("MD", "3-203"): "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gcr&section=3-203",
        ("IN", "35-42-2-1"): "https://law.justia.com/codes/indiana/title-35/article-42/chapter-2/section-35-42-2-1/",
        ("MS", "97-3-7"): "https://law.justia.com/codes/mississippi/2024/title-97/chapter-3/section-97-3-7/",
        ("NH", "631:2-a"): "https://gc.nh.gov/rsa/html/LXII/631/631-2-a.htm",
        ("NJ", "2C:12-1"): "https://law.justia.com/codes/new-jersey/title-2c/section-2c-12-1/",
        ("NM", "30-3-4"): "https://law.justia.com/codes/new-mexico/chapter-30/article-3/section-30-3-4/",
        ("ND", "12.1-17-01"): "https://ndlegis.gov/cencode/t12-1c17.pdf",
        ("OK", "21-644"): "https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os21.pdf",
        ("TN", "39-13-101"): "https://law.justia.com/codes/tennessee/title-39/chapter-13/part-1/section-39-13-101/",
        ("VA", "18.2-57"): "https://law.lis.virginia.gov/vacode/title18.2/chapter4/section18.2-57/",
        ("VT", "13-1023"): "https://legislature.vermont.gov/statutes/section/13/019/01023",
        ("WY", "6-2-501"): "https://wyoleg.gov/statutes/compress/title06.pdf",
    }
    known_url = known_section_urls.get((state, normalized_section))
    if known_url:
        return known_url

    if state == "MN" or "revisor.mn.gov" in host_hint:
        return f"https://www.revisor.mn.gov/statutes/cite/{normalized_section}"
    if state == "AK" or "akleg.gov" in host_hint:
        return f"https://www.akleg.gov/basis/statutes.asp#{normalized_section}"
    if state == "AZ" or "azleg.gov" in host_hint:
        parts = _section_parts("-")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return f"https://www.azleg.gov/ars/{int(parts[0])}/{int(parts[1]):05d}.htm"
        return ""
    if state == "OR" or "oregon.public.law" in host_hint:
        return f"https://oregon.public.law/statutes/ors_{normalized_section}"
    if state == "CA" or "leginfo.legislature.ca.gov" in host_hint:
        law_code = "FAM"
        if re.search(r"\bPenal\s+Code\b", code_hint, re.IGNORECASE):
            law_code = "PEN"
        elif re.search(r"\bCiv\.\s+Code\b", code_hint, re.IGNORECASE):
            law_code = "CIV"
        return (
            "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml"
            f"?lawCode={law_code}&sectionNum={normalized_section}"
        )
    if state == "DC" or "code.dccouncil.gov" in host_hint:
        return f"https://code.dccouncil.gov/us/dc/council/code/sections/{normalized_section}"
    if state == "NY" or "nysenate.gov" in host_hint:
        law_code = "FCT" if re.search(r"\bFam\.\s+Ct\.\s+Act\b", code_hint, re.IGNORECASE) else "DOM"
        return f"https://www.nysenate.gov/legislation/laws/{law_code}/{normalized_section}"
    if state == "TX" or "statutes.capitol.texas.gov" in host_hint:
        law_code = "FA"
        if re.search(r"\bPenal\s+Code\b", code_hint, re.IGNORECASE):
            law_code = "PE"
        chapter = normalized_section.split(".", 1)[0]
        return f"https://statutes.capitol.texas.gov/Docs/{law_code}/htm/{law_code}.{chapter}.htm#{normalized_section}"
    if state == "ID" or "legislature.idaho.gov" in host_hint:
        parts = _section_parts("-")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            chapter = str(int(parts[1][0])) if len(parts[1]) >= 3 else str(int(parts[1]))
            return f"https://legislature.idaho.gov/statutesrules/idstat/title{int(parts[0])}/t{int(parts[0])}ch{chapter}/sect{normalized_section}/"
        return ""
    if state == "IN" or "iga.in.gov" in host_hint:
        parts = _section_parts("-")
        if parts and parts[0].isdigit():
            return f"https://iga.in.gov/laws/2026/ic/titles/{int(parts[0])}#{normalized_section}"
        return ""
    if state == "IA" or "legis.iowa.gov" in host_hint:
        return f"https://www.legis.iowa.gov/docs/code/{normalized_section}.pdf"
    if state == "KS" or "ksrevisor.gov" in host_hint:
        parts = _section_parts("-")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit() and len(parts[1]) >= 3:
            chapter = int(parts[0])
            article = int(parts[1][:-2])
            section_num = int(parts[1][-2:])
            return f"https://www.ksrevisor.gov/statutes/chapters/ch{chapter:02d}/{chapter:03d}_{article:03d}_{section_num:04d}.html"
        return ""
    if state == "ME" or "mainelegislature.org" in host_hint:
        title_section = normalized_section.split(":", 1)
        if len(title_section) == 2:
            title, section = title_section
            return f"https://www.mainelegislature.org/legis/statutes/{title}/title{title}sec{section}.html"
        return ""
    if state == "MA" or "malegislature.gov" in host_hint:
        parts = _section_parts("-")
        if len(parts) >= 2 and parts[0].isdigit():
            chapter = parts[0]
            section = "-".join(parts[1:])
            return f"https://malegislature.gov/Laws/GeneralLaws/PartIV/TitleI/Chapter{chapter}/Section{section.lower()}"
        return ""
    if state == "MI" or "legislature.mi.gov" in host_hint:
        return f"https://legislature.mi.gov/Laws/MCL?objectName=mcl-{normalized_section.replace('.', '-')}"
    if state == "MO" or "revisor.mo.gov" in host_hint:
        return f"https://revisor.mo.gov/main/OneSection.aspx?section={normalized_section}"
    if state == "MT" or "legmt.gov" in host_hint or "archive.legmt.gov" in host_hint:
        parts = _section_parts("-")
        if len(parts) >= 3 and all(part.isdigit() for part in parts):
            title = int(parts[0])
            chapter = int(parts[1])
            part_num = int(parts[2][0]) if len(parts[2]) >= 3 else int(parts[2])
            section_num = int(parts[2][1:]) if len(parts[2]) >= 3 else int(parts[2])
            return (
                "https://mca.legmt.gov/bills/mca/"
                f"title_{title * 10:04d}/chapter_{chapter * 10:04d}/part_{part_num * 10:04d}/section_{section_num * 10:04d}/"
                f"{title * 10:04d}-{chapter * 10:04d}-{part_num * 10:04d}-{section_num * 10:04d}.html"
            )
        return ""
    if state == "NC" or "ncleg.gov" in host_hint:
        parts = _section_parts("-")
        if len(parts) >= 2:
            return f"https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/Chapter_{parts[0]}/GS_{normalized_section}.html"
        return ""
    if state == "NE" or "nebraskalegislature.gov" in host_hint:
        return f"https://nebraskalegislature.gov/laws/statutes.php?statute={normalized_section}"
    if state == "NV" or "leg.state.nv.us" in host_hint:
        chapter = normalized_section.split(".", 1)[0]
        suffix = normalized_section.split(".", 1)[1] if "." in normalized_section else ""
        if chapter.isdigit() and suffix:
            return f"https://www.leg.state.nv.us/NRS/NRS-{int(chapter):03d}.html#NRS{int(chapter)}Sec{suffix}"
        return ""
    if state == "OH" or "codes.ohio.gov" in host_hint:
        return f"https://codes.ohio.gov/ohio-revised-code/section-{normalized_section}"
    if state == "SD" or "sdlegislature.gov" in host_hint:
        return f"https://sdlegislature.gov/Statutes/{normalized_section}"
    if state == "SC" or "scstatehouse.gov" in host_hint:
        parts = _section_parts("-")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return f"https://www.scstatehouse.gov/code/t{int(parts[0]):02d}c{int(parts[1]):03d}.php#{normalized_section}"
        return ""
    if state == "RI" or "rilegislature.gov" in host_hint or "rilin.state.ri.us" in host_hint:
        parts = _section_parts("-")
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            title = int(parts[0])
            chapter = int(parts[1])
            return (
                "https://webserver.rilegislature.gov/Statutes/"
                f"TITLE{title}/{title}-{chapter}/{normalized_section}.htm"
            )
        return ""
    if state == "UT" or "le.utah.gov" in host_hint:
        parts = _section_parts("-")
        if len(parts) >= 3 and parts[0].isdigit():
            return f"https://le.utah.gov/xcode/Title{parts[0]}/Chapter{parts[1]}/{parts[0]}-{parts[1]}-S{'-'.join(parts[2:])}.html"
        return ""
    if state == "WA" or "app.leg.wa.gov" in host_hint:
        return f"https://app.leg.wa.gov/RCW/default.aspx?cite={normalized_section}"
    if state == "WI" or "docs.legis.wisconsin.gov" in host_hint:
        chapter, _, section_tail = normalized_section.partition(".")
        if chapter and section_tail:
            return f"https://docs.legis.wisconsin.gov/statutes/statutes/{chapter}#{normalized_section}"
        return ""
    if state == "WV" or "code.wvlegislature.gov" in host_hint:
        return f"https://code.wvlegislature.gov/{normalized_section}/"
    if state == "FL" or "leg.state.fl.us" in host_hint:
        chapter = normalized_section.split(".", 1)[0]
        if not chapter.isdigit():
            return ""
        chapter_num = int(chapter)
        range_start = (chapter_num // 100) * 100
        range_end = range_start + 99
        return (
            "https://www.leg.state.fl.us/statutes/index.cfm"
            f"?App_mode=Display_Statute&URL={range_start:04d}-{range_end:04d}/{chapter_num:04d}/Sections/{chapter_num:04d}.{normalized_section.split('.', 1)[1] if '.' in normalized_section else '00'}.html"
        )
    if state == "IL" or "ilga.gov" in host_hint:
        il_match = re.search(r"\b(?P<title>\d+)\s+ILCS\s+(?P<act>\d+)\b", code_hint, re.IGNORECASE)
        if not il_match:
            return ""
        title = int(il_match.group("title"))
        act = int(il_match.group("act"))
        return f"https://www.ilga.gov/documents/legislation/ilcs/documents/{title:04d}{act:04d}0K{normalized_section}.htm"
    if state == "PA" or "palegis.us" in host_hint:
        title_match = re.search(r"\b(?P<title>\d+)\s+Pa\.?\s*C\.?S\.?", code_hint, re.IGNORECASE)
        if not title_match or not normalized_section.isdigit() or len(normalized_section) < 3:
            return ""
        title = int(title_match.group("title"))
        chapter = int(normalized_section[:-2])
        section = int(normalized_section[-2:])
        return (
            "https://www.legis.state.pa.us/WU01/LI/LI/CT/HTM/"
            f"{title:02d}/00.{chapter:03d}.{section:03d}.000..HTM"
        )
    return ""


def _resolve_state_output_dir(output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return get_canonical_legal_corpus("state_laws").default_local_root()


def _compute_state_quality_metrics(statutes: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(statutes)
    if total <= 0:
        return {
            "total": 0,
            "nav_like_ratio": 0.0,
            "fallback_section_ratio": 0.0,
            "numeric_section_name_ratio": 0.0,
            "scaffold_ratio": 0.0,
            "bill_history_ratio": 0.0,
        }

    nav_like = 0
    fallback_section = 0
    numeric_section_name = 0
    scaffold = 0
    bill_history = 0

    for statute in statutes:
        if not isinstance(statute, dict):
            continue

        text = str(statute.get("full_text") or statute.get("text") or "")
        section_number = str(statute.get("section_number") or statute.get("sectionNumber") or "")
        section_name = str(statute.get("section_name") or statute.get("sectionName") or "")
        source_url = str(statute.get("source_url") or statute.get("sourceUrl") or "").lower()
        has_quality_legal_signal = _has_quality_legal_signal(statute)

        # Treat nav markers as quality failures only when the text is mostly chrome/boilerplate.
        if _QUALITY_NAV_RE.search(text) and len(text) < 2000 and not has_quality_legal_signal:
            nav_like += 1
        if _QUALITY_SECTION_FALLBACK_RE.match(section_number):
            fallback_section += 1
        if _QUALITY_SECTION_SIGNAL_RE.search(section_name) or _QUALITY_SECTION_NUMBER_RE.match(section_number):
            numeric_section_name += 1
        if _is_scaffold_or_navigation_record(statute):
            scaffold += 1
        history_text = bool(_QUALITY_BILL_HISTORY_RE.search(text))
        bill_number_text = bool(_QUALITY_BILL_NUMBER_RE.search(text))
        bill_history_url = "/history/" in source_url and (
            "billstatus.ls.state.ms.us" in source_url
            or "legislature.ms.gov" in source_url
        )
        if history_text and (bill_number_text or bill_history_url):
            bill_history += 1

    return {
        "total": total,
        "nav_like_ratio": round(nav_like / total, 3),
        "fallback_section_ratio": round(fallback_section / total, 3),
        "numeric_section_name_ratio": round(numeric_section_name / total, 3),
        "scaffold_ratio": round(scaffold / total, 3),
        "bill_history_ratio": round(bill_history / total, 3),
    }


def _should_flag_quality(quality_metrics: Dict[str, Any]) -> bool:
    total_q = int(quality_metrics.get("total", 0) or 0)
    nav_q = float(quality_metrics.get("nav_like_ratio", 0.0) or 0.0)
    fallback_q = float(quality_metrics.get("fallback_section_ratio", 0.0) or 0.0)
    numeric_q = float(quality_metrics.get("numeric_section_name_ratio", 0.0) or 0.0)
    scaffold_q = float(quality_metrics.get("scaffold_ratio", 0.0) or 0.0)
    bill_history_q = float(quality_metrics.get("bill_history_ratio", 0.0) or 0.0)

    fallback_problem = (total_q >= 10 and fallback_q >= 0.7 and numeric_q <= 0.2)
    if total_q >= 10 and (
        nav_q >= 0.2
        or fallback_problem
        or numeric_q <= 0.2
        or scaffold_q >= 0.2
        or bill_history_q >= 0.25
    ):
        return True
    if total_q >= 5 and bill_history_q >= 0.5:
        return True
    if 1 <= total_q < 5 and bill_history_q >= 0.8:
        return True
    if 1 <= total_q < 10 and nav_q >= 0.5:
        return True
    return False


def _format_quality_warning(state_code: str, quality_metrics: Dict[str, Any]) -> str:
    total_q = int(quality_metrics.get("total", 0) or 0)
    nav_q = float(quality_metrics.get("nav_like_ratio", 0.0) or 0.0)
    fallback_q = float(quality_metrics.get("fallback_section_ratio", 0.0) or 0.0)
    numeric_q = float(quality_metrics.get("numeric_section_name_ratio", 0.0) or 0.0)
    scaffold_q = float(quality_metrics.get("scaffold_ratio", 0.0) or 0.0)
    bill_history_q = float(quality_metrics.get("bill_history_ratio", 0.0) or 0.0)
    return (
        f"{state_code} quality gate triggered "
        f"(total={total_q}, nav={nav_q}, fallback={fallback_q}, numeric={numeric_q}, scaffold={scaffold_q}, bill_history={bill_history_q})"
    )


def _run_state_law_frontier_producer_lifecycle(
    *,
    scraper: Any,
    ledger: Any,
    final_rows: Sequence[Mapping[str, Any]],
) -> tuple[Dict[str, Any], Optional[str]]:
    """Run one state-owned independent frontier replay after final filtering."""

    from ..legal_data.state_laws_multifetch_acquisition import (
        build_canonical_state_law_output_projection,
    )
    from .state_scrapers.base_scraper import BaseStateScraper

    lifecycle: Dict[str, Any] = {
        "hook": "BaseStateScraper.produce_state_law_frontier_closure",
        "invoked": False,
        "status": "pending",
    }
    try:
        output_projection = build_canonical_state_law_output_projection(
            final_rows,
            jurisdiction=str(getattr(scraper, "state_code", "") or ""),
        )
    except Exception as exc:
        lifecycle.update(
            {
                "error": str(exc),
                "status": "failed",
            }
        )
        return lifecycle, "source_frontier_producer_failed"

    lifecycle["canonical_output_projection"] = {
        key: value
        for key, value in output_projection.items()
        if key != "canonical_keys"
    }
    producer = getattr(scraper, "produce_state_law_frontier_closure", None)
    producer_impl = getattr(producer, "__func__", producer)
    base_impl = BaseStateScraper.produce_state_law_frontier_closure
    shared_bridge_support = getattr(
        scraper,
        "_supports_shared_official_frontier_bridge",
        None,
    )
    shared_bridge_ready = bool(
        producer_impl is base_impl
        and callable(shared_bridge_support)
        and shared_bridge_support()
    )
    if not callable(producer) or (
        producer_impl is base_impl and not shared_bridge_ready
    ):
        lifecycle["status"] = "missing"
        return lifecycle, "source_frontier_producer_missing"

    lifecycle["invoked"] = True
    try:
        retained_path_raw = asyncio.run(
            producer(canonical_output_projection=output_projection)
        )
        if retained_path_raw is None:
            raise RuntimeError(
                "state frontier producer returned without retaining closure evidence"
            )
        retained_path = ledger.resolve_frontier_closure_projection_path(
            retained_path_raw
        )
        verified = ledger.verify_retained_frontier_closure_projection(
            output_projection,
            closure_input_path=retained_path,
        )
    except Exception as exc:
        lifecycle.update(
            {
                "error": str(exc),
                "status": "failed",
            }
        )
        return lifecycle, "source_frontier_producer_failed"

    lifecycle.update(
        {
            "canonical_output_projection": {
                key: value for key, value in verified.items() if key != "canonical_keys"
            },
            "closure_input_path": str(retained_path),
            "status": "retained_and_verified",
        }
    )
    return lifecycle, None


def _scrape_state_once_sync_unguarded(
    *,
    state_code: str,
    legal_areas: Optional[List[str]],
    rate_limit_delay: float,
    max_statutes: Optional[int],
    strict_full_text: bool,
    min_full_text_chars: int,
    hydrate_statute_text: bool,
    per_state_timeout_seconds: float = 0.0,
    checkpoint_generation_key: str = "",
    checkpoint_generation: int = 0,
    bound_evidence_root: Optional[str] = None,
    bound_strict_evidence: Optional[bool] = None,
    bound_retained_replay_only: Optional[bool] = None,
    bound_state_run_environment: Optional[Mapping[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    from .state_scrapers import get_scraper_for_state, GenericStateScraper

    state_name = US_STATES[state_code]
    scraper = get_scraper_for_state(state_code, state_name)
    if not scraper:
        logger.info(f"No specific scraper for {state_code}, using generic scraper")
        scraper = GenericStateScraper(state_code, state_name)
    state_run_environment = (
        dict(bound_state_run_environment)
        if bound_state_run_environment is not None
        else _capture_state_law_run_environment()
    )
    bind_run_environment = getattr(
        scraper,
        "bind_state_law_run_environment",
        None,
    )
    if not callable(bind_run_environment):
        raise RuntimeError(
            f"{type(scraper).__name__} cannot bind immutable run selectors"
        )
    bind_run_environment(state_run_environment)
    bind_checkpoint_generation = getattr(
        scraper,
        "bind_partial_checkpoint_generation",
        None,
    )
    if callable(bind_checkpoint_generation):
        bind_checkpoint_generation(
            key=checkpoint_generation_key,
            generation=checkpoint_generation,
        )

    evidence_root_raw = (
        str(bound_evidence_root).strip()
        if bound_evidence_root is not None
        else str(os.getenv(MULTIFETCH_EVIDENCE_ROOT_ENV) or "").strip()
    )
    strict_evidence = (
        bool(bound_strict_evidence)
        if bound_strict_evidence is not None
        else str(os.getenv(STRICT_MULTIFETCH_EVIDENCE_ENV) or "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    retained_replay_only = (
        bool(bound_retained_replay_only)
        if bound_retained_replay_only is not None
        else str(os.getenv(RETAINED_REPLAY_ONLY_ENV) or "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    ledger = None
    bypass_inventory = inventory_state_scraper_transport_bypasses(scraper)
    evidence_root = ""
    if strict_evidence and not evidence_root_raw:
        raise RuntimeError(
            f"{STRICT_MULTIFETCH_EVIDENCE_ENV}=1 requires "
            f"{MULTIFETCH_EVIDENCE_ROOT_ENV} before scraper construction"
        )
    if retained_replay_only and not strict_evidence:
        raise RuntimeError(
            f"{RETAINED_REPLAY_ONLY_ENV}=1 requires "
            f"{STRICT_MULTIFETCH_EVIDENCE_ENV}=1"
        )
    if retained_replay_only and not evidence_root_raw:
        raise RuntimeError(
            f"{RETAINED_REPLAY_ONLY_ENV}=1 requires "
            f"{MULTIFETCH_EVIDENCE_ROOT_ENV} before scraper construction"
        )
    if retained_replay_only and not bypass_inventory.get("complete"):
        raise RuntimeError(
            f"{state_code} retained-replay-only mode rejected parser-reachable "
            "transport bypass candidates before scrape_all"
        )
    if evidence_root_raw:
        from ..legal_data.state_laws_multifetch_acquisition import (
            StateLawMultiFetchAcquisitionLedger,
        )

        evidence_root = str(Path(evidence_root_raw).expanduser().resolve())
        ledger = StateLawMultiFetchAcquisitionLedger(
            evidence_root,
            jurisdiction=state_code,
            parser_name=type(scraper).__name__,
            retained_replay_only=retained_replay_only,
        )
        attach = getattr(scraper, "attach_state_law_acquisition_ledger", None)
        if not callable(attach):
            raise RuntimeError(
                f"{type(scraper).__name__} cannot attach prospective acquisition evidence"
            )
        # This is intentionally before scrape_all: a strict production run can
        # never parse a shared-path response and attach provenance afterward.
        attach(ledger)

    if retained_replay_only:
        from .state_scrapers.retained_replay_network_guard import (
            retained_replay_network_guard,
        )

        with retained_replay_network_guard(
            ledger=ledger,
            state_code=state_code,
        ):
            normalized_statutes = asyncio.run(
                scraper.scrape_all(
                    legal_areas=legal_areas,
                    max_statutes=max_statutes,
                    rate_limit_delay=rate_limit_delay,
                    hydrate_statute_text=hydrate_statute_text,
                )
            )
    else:
        normalized_statutes = asyncio.run(
            scraper.scrape_all(
                legal_areas=legal_areas,
                max_statutes=max_statutes,
                rate_limit_delay=rate_limit_delay,
                hydrate_statute_text=hydrate_statute_text,
            )
        )

    strict_removed_count = 0
    if strict_full_text:
        normalized_statutes, strict_removed_count = _filter_strict_full_text_statutes(
            normalized_statutes,
            min_full_text_chars=min_full_text_chars,
            source_bound_operative_checker=getattr(
                scraper,
                "_is_source_bound_operative_statute_record",
                None,
            ),
        )
    output_rows = [statute.to_dict() for statute in normalized_statutes]

    statute_data = {
        "state_code": state_code,
        "state_name": state_name,
        "title": f"{state_name} Laws",
        "source": "Official State Legislative Website",
        "source_url": scraper.get_base_url(),
        "official_url": scraper.get_base_url(),
        "scraped_at": datetime.now().isoformat(),
        "statutes": output_rows,
        "schema_version": "1.0",
        "normalized": True,
        "strict_full_text": strict_full_text,
        "strict_removed_count": strict_removed_count,
    }
    quality_metrics = _compute_state_quality_metrics(statute_data["statutes"])
    quality_flag = _should_flag_quality(quality_metrics)
    fetch_analytics = {}
    if hasattr(scraper, "get_fetch_analytics_snapshot"):
        try:
            fetch_analytics = scraper.get_fetch_analytics_snapshot()
        except Exception:
            fetch_analytics = {}
    statute_data["quality_metrics"] = quality_metrics
    statute_data["quality_flag"] = quality_flag
    if fetch_analytics:
        statute_data["fetch_analytics"] = fetch_analytics

    warnings: List[str] = []
    if quality_flag:
        warnings.append(_format_quality_warning(state_code, quality_metrics))
    if len(normalized_statutes) == 0:
        warnings.append(f"{state_code} returned zero statutes")

    acquisition_evidence: Dict[str, Any] = {
        "aggregate": {
            "authorizing_for_publication": False,
            "status": "disabled" if ledger is None else "pending_canonical_materialization",
        },
        "aggregate_eligible": False,
        "all_fetch_coverage_claimed": False,
        "attached_before_scrape_all": ledger is not None,
        "enabled": ledger is not None,
        "evidence_root": evidence_root or None,
        "jurisdiction": state_code,
        "parser_name": type(scraper).__name__,
        "required_frontier_producer_api": (
            "BaseStateScraper.produce_state_law_frontier_closure"
        ),
        "required_frontier_retention_api": (
            "BaseStateScraper.retain_state_law_frontier_closure_projection"
        ),
        "schema_version": "state-laws-scraper-multifetch-evidence-v1",
        "strict": strict_evidence,
        "retained_replay_only": retained_replay_only,
        "transport_bypass_inventory": bypass_inventory,
    }
    evidence_blockers: List[str] = []
    if ledger is not None:
        full_scope = max_statutes is None and not legal_areas
        if full_scope:
            if retained_replay_only:
                from .state_scrapers.retained_replay_network_guard import (
                    retained_replay_network_guard,
                )

                with retained_replay_network_guard(
                    ledger=ledger,
                    state_code=state_code,
                ):
                    frontier_lifecycle, frontier_blocker = (
                        _run_state_law_frontier_producer_lifecycle(
                            scraper=scraper,
                            ledger=ledger,
                            final_rows=output_rows,
                        )
                    )
            else:
                frontier_lifecycle, frontier_blocker = (
                    _run_state_law_frontier_producer_lifecycle(
                        scraper=scraper,
                        ledger=ledger,
                        final_rows=output_rows,
                    )
                )
            if frontier_blocker:
                evidence_blockers.append(frontier_blocker)
        else:
            frontier_lifecycle = {
                "hook": "BaseStateScraper.produce_state_law_frontier_closure",
                "invoked": False,
                "status": "not_invoked_non_full_scope",
            }
        parser_output_coverage = ledger.audit_parser_output_coverage(output_rows)
        lifecycle_closure_path = str(
            frontier_lifecycle.get("closure_input_path") or ""
        ).strip()
        acquisition_evidence.update(
            {
                "jurisdiction_root": str(ledger.jurisdiction_root),
                "source_frontier_lifecycle": frontier_lifecycle,
                "parser_output_coverage": parser_output_coverage,
                "retained_parser_input_count": len(ledger.entries),
            }
        )
        if lifecycle_closure_path:
            acquisition_evidence["closure_input_path"] = lifecycle_closure_path
        if not parser_output_coverage.get("complete"):
            evidence_blockers.append("parser_output_units_without_retained_input")
        if not bypass_inventory.get("complete"):
            evidence_blockers.append("parser_reachable_transport_bypass_candidates")
        if max_statutes is not None:
            evidence_blockers.append("bounded_scrape_cannot_close_full_frontier")
        elif legal_areas:
            evidence_blockers.append("filtered_scope_cannot_close_full_frontier")
        acquisition_evidence["aggregate_eligible"] = not evidence_blockers
        if evidence_blockers:
            acquisition_evidence["aggregate"]["status"] = "blocked_before_materialization"
    elif strict_evidence:
        evidence_blockers.append("strict_evidence_ledger_unattached")
    acquisition_evidence["eligibility_blockers"] = evidence_blockers
    statute_data["acquisition_evidence"] = acquisition_evidence

    lifecycle = acquisition_evidence.get("source_frontier_lifecycle")
    if isinstance(lifecycle, Mapping) and lifecycle.get("status") in {
        "failed",
        "missing",
    }:
        warnings.append(
            f"{state_code} source frontier producer {lifecycle.get('status')}: "
            f"{lifecycle.get('error') or 'no state-specific producer is implemented'}"
        )

    evidence_error = ""
    if strict_evidence and evidence_blockers:
        evidence_error = (
            f"{state_code} strict acquisition evidence blocked: "
            + ",".join(evidence_blockers)
        )
        warnings.append(evidence_error)

    return {
        "state_code": state_code,
        "state_name": state_name,
        "error": evidence_error or None,
        "statutes_count": len(normalized_statutes),
        "zero_statute": len(normalized_statutes) == 0,
        "low_quality": quality_flag,
        "quality_metrics": quality_metrics,
        "fetch_analytics": fetch_analytics,
        "warnings": warnings,
        "acquisition_evidence": acquisition_evidence,
        "statute_data": statute_data,
    }


def _scrape_state_once_sync(
    *,
    state_code: str,
    legal_areas: Optional[List[str]],
    rate_limit_delay: float,
    max_statutes: Optional[int],
    strict_full_text: bool,
    min_full_text_chars: int,
    hydrate_statute_text: bool,
    per_state_timeout_seconds: float = 0.0,
    checkpoint_generation_key: str = "",
    checkpoint_generation: int = 0,
    bound_evidence_root: Optional[str] = None,
    bound_strict_evidence: Optional[bool] = None,
    bound_retained_replay_only: Optional[bool] = None,
    bound_state_run_environment: Optional[Mapping[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    """Run one state under a whole-worker retained-replay deny lease.

    The outer lease starts before scraper or ledger construction and remains
    active through normalization, analytics, quality checks, frontier closure,
    ledger coverage, and result construction.  Inner parser/frontier guards are
    intentionally retained as defense in depth and are safe to nest.
    """

    retained_replay_only = (
        bool(bound_retained_replay_only)
        if bound_retained_replay_only is not None
        else str(os.getenv(RETAINED_REPLAY_ONLY_ENV) or "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    if not retained_replay_only:
        return _scrape_state_once_sync_unguarded(
            state_code=state_code,
            legal_areas=legal_areas,
            rate_limit_delay=rate_limit_delay,
            max_statutes=max_statutes,
            strict_full_text=strict_full_text,
            min_full_text_chars=min_full_text_chars,
            hydrate_statute_text=hydrate_statute_text,
            per_state_timeout_seconds=per_state_timeout_seconds,
            checkpoint_generation_key=checkpoint_generation_key,
            checkpoint_generation=checkpoint_generation,
            bound_evidence_root=bound_evidence_root,
            bound_strict_evidence=bound_strict_evidence,
            bound_retained_replay_only=False,
            bound_state_run_environment=bound_state_run_environment,
        )

    strict_evidence = (
        bool(bound_strict_evidence)
        if bound_strict_evidence is not None
        else str(os.getenv(STRICT_MULTIFETCH_EVIDENCE_ENV) or "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    if not strict_evidence:
        raise RuntimeError(
            f"{RETAINED_REPLAY_ONLY_ENV}=1 requires "
            f"{STRICT_MULTIFETCH_EVIDENCE_ENV}=1"
        )
    evidence_root_raw = (
        str(bound_evidence_root).strip()
        if bound_evidence_root is not None
        else str(os.getenv(MULTIFETCH_EVIDENCE_ROOT_ENV) or "").strip()
    )
    if not evidence_root_raw:
        raise RuntimeError(
            f"{RETAINED_REPLAY_ONLY_ENV}=1 requires "
            f"{MULTIFETCH_EVIDENCE_ROOT_ENV} before scraper construction"
        )

    from types import SimpleNamespace

    from .state_scrapers.retained_replay_network_guard import (
        retained_replay_network_guard,
    )

    evidence_root_path = Path(evidence_root_raw).expanduser()
    if evidence_root_path.is_symlink():
        raise RuntimeError("acquisition evidence root must not be a symlink")
    # The guard must be able to install a permanent poison marker even if a
    # scraper constructor violates the deny policy before the real ledger is
    # constructed.  The ledger creates this same directory during an ordinary
    # strict run and repeats the symlink checks below.
    evidence_root_path.mkdir(parents=True, exist_ok=True)
    if evidence_root_path.is_symlink() or not evidence_root_path.is_dir():
        raise RuntimeError("acquisition evidence root must be a regular directory")
    evidence_root = str(evidence_root_path.resolve())
    root_binding = SimpleNamespace(
        retained_replay_only=True,
        root=evidence_root,
    )
    with retained_replay_network_guard(
        ledger=root_binding,
        state_code=state_code,
    ):
        return _scrape_state_once_sync_unguarded(
            state_code=state_code,
            legal_areas=legal_areas,
            rate_limit_delay=rate_limit_delay,
            max_statutes=max_statutes,
            strict_full_text=strict_full_text,
            min_full_text_chars=min_full_text_chars,
            hydrate_statute_text=hydrate_statute_text,
            per_state_timeout_seconds=per_state_timeout_seconds,
            checkpoint_generation_key=checkpoint_generation_key,
            checkpoint_generation=checkpoint_generation,
            bound_evidence_root=evidence_root,
            bound_strict_evidence=True,
            bound_retained_replay_only=True,
            bound_state_run_environment=bound_state_run_environment,
        )


def _load_partial_checkpoint_state_result(
    state_code: str,
    error_msg: str,
    *,
    checkpoint_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    checkpoint_dir = (
        str(checkpoint_dir).strip()
        if checkpoint_dir is not None
        else str(os.getenv("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR") or "").strip()
    )
    if not checkpoint_dir:
        return None
    path = Path(checkpoint_dir).expanduser().resolve() / f"STATE-{state_code.upper()}-partial.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    statutes = payload.get("statutes") if isinstance(payload, dict) else None
    if not isinstance(statutes, list):
        return None
    progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
    timeout_diagnostics = _derive_timeout_diagnostics_from_checkpoint_payload(
        payload=payload,
        error_msg=error_msg,
        statutes_count=len(statutes),
    )
    signal_found = bool(timeout_diagnostics.get("signal_found"))
    has_progress_fields = bool(progress)
    if len(statutes) <= 0 and not signal_found and not has_progress_fields:
        return None

    state_name = US_STATES[state_code]
    statute_data = {
        "state_code": state_code,
        "state_name": state_name,
        "title": f"{state_name} Laws",
        "source": "Official State Legislative Website",
        "source_url": str(payload.get("source_url") or ""),
        "official_url": str(payload.get("official_url") or ""),
        "scraped_at": datetime.now().isoformat(),
        "statutes": statutes,
        "schema_version": "1.0",
        "normalized": True,
        "partial_checkpoint": True,
        "partial_checkpoint_path": str(path),
        "partial_checkpoint_error": error_msg,
        "timeout_diagnostics": timeout_diagnostics,
    }
    quality_metrics = _compute_state_quality_metrics(statutes)
    quality_flag = _should_flag_quality(quality_metrics)
    zero_statute = len(statutes) <= 0
    if zero_statute:
        recovery_note = (
            f"{state_code} recovered timeout diagnostics from partial checkpoint with "
            "no statutes yet persisted"
        )
    else:
        recovery_note = (
            f"{state_code} recovered {len(statutes)} statutes from partial checkpoint after timeout/error"
        )
    warnings = [
        recovery_note,
        error_msg,
        (
            f"{state_code} checkpoint timeout_diagnostics="
            f"{timeout_diagnostics.get('classification')} "
            f"work_remaining={timeout_diagnostics.get('work_remaining')} "
            f"signal_kind={timeout_diagnostics.get('signal_kind')}"
        ),
    ]
    if quality_flag:
        warnings.append(_format_quality_warning(state_code, quality_metrics))
    return {
        "state_code": state_code,
        "state_name": state_name,
        "error": error_msg,
        "statutes_count": len(statutes),
        "zero_statute": bool(zero_statute),
        "low_quality": quality_flag,
        "quality_metrics": quality_metrics,
        "fetch_analytics": {},
        "warnings": warnings,
        "timeout_diagnostics": timeout_diagnostics,
        "statute_data": statute_data,
    }


def _load_partial_checkpoint_state_success_result(
    state_code: str,
    *,
    reason: str = "checkpoint_complete_promotion",
    require_no_remaining_work: bool = False,
    checkpoint_dir: Optional[str] = None,
    strict_evidence: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    strict_evidence = (
        bool(strict_evidence)
        if strict_evidence is not None
        else str(os.getenv(STRICT_MULTIFETCH_EVIDENCE_ENV, "") or "")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )
    if strict_evidence:
        # A parser checkpoint cannot prove that the separately retained source
        # frontier replay and closure projection completed.  Strict acquisition
        # runs must return the worker result (or its original failure) instead
        # of manufacturing success from parser rows alone.
        return None
    state = str(state_code or "").strip().upper()
    if not state:
        return None
    synthetic_error = f"{reason}: promote checkpoint-complete state"
    recovered = _load_partial_checkpoint_state_result(
        state,
        synthetic_error,
        checkpoint_dir=checkpoint_dir,
    )
    if recovered is None:
        return None
    statutes_count = _safe_int(recovered.get("statutes_count"), 0)
    if statutes_count <= 0:
        return None

    promoted = dict(recovered)
    promoted["error"] = None
    promoted["zero_statute"] = False
    warnings = [str(item) for item in list(promoted.get("warnings") or []) if str(item) != synthetic_error]
    warnings.append(f"{state} promoted from checkpoint-complete state")
    promoted["warnings"] = warnings

    diagnostics = dict(promoted.get("timeout_diagnostics") or {})
    if require_no_remaining_work and diagnostics.get("work_remaining") is not False:
        return None
    diagnostics["timed_out"] = False
    diagnostics["classification"] = "checkpoint_complete_promotion"
    diagnostics["work_remaining"] = False
    diagnostics.setdefault("signal_found", True)
    diagnostics.setdefault("signal_kind", "checkpoint_stage_complete")
    promoted["timeout_diagnostics"] = diagnostics

    statute_data = dict(promoted.get("statute_data") or {})
    statute_data["partial_checkpoint_error"] = ""
    statute_data["timeout_diagnostics"] = diagnostics
    promoted["statute_data"] = statute_data
    return promoted


def _promote_timeout_checkpoint_result_if_no_remaining_work(
    state_code: str,
    checkpoint_result: Optional[Dict[str, Any]],
    *,
    reason: str,
    checkpoint_dir: Optional[str] = None,
    strict_evidence: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    if checkpoint_result is None:
        return None
    diagnostics = dict(checkpoint_result.get("timeout_diagnostics") or {})
    statutes_count = _safe_int(checkpoint_result.get("statutes_count"), 0)
    if statutes_count <= 0:
        return checkpoint_result
    if diagnostics.get("work_remaining") is not False:
        return checkpoint_result
    promoted = _load_partial_checkpoint_state_success_result(
        state_code,
        reason=reason,
        require_no_remaining_work=True,
        checkpoint_dir=checkpoint_dir,
        strict_evidence=strict_evidence,
    )
    if promoted is not None:
        return promoted
    return checkpoint_result


async def _run_sync_scrape_on_daemon_thread(
    *,
    state_code: str,
    legal_areas: Optional[List[str]],
    rate_limit_delay: float,
    max_statutes: Optional[int],
    strict_full_text: bool,
    min_full_text_chars: int,
    hydrate_statute_text: bool,
    timeout_seconds: float,
    bound_checkpoint_dir: Optional[str] = None,
    bound_strict_evidence: Optional[bool] = None,
    bound_evidence_root: Optional[str] = None,
    bound_retained_replay_only: Optional[bool] = None,
    bound_state_run_environment: Optional[Mapping[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    from .state_scrapers.base_scraper import (
        bind_partial_checkpoint_run_directory,
        bind_state_law_worker_environment,
        claim_partial_checkpoint_generation,
        restore_partial_checkpoint_run_directory,
        restore_state_law_worker_environment,
    )

    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[Dict[str, Any]] = loop.create_future()
    checkpoint_dir_binding = (
        str(bound_checkpoint_dir).strip()
        if bound_checkpoint_dir is not None
        else str(
            os.environ.get("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR") or ""
        ).strip()
    )
    if checkpoint_dir_binding:
        checkpoint_dir_binding = str(
            Path(checkpoint_dir_binding).expanduser().resolve()
        )
    evidence_root_binding = (
        str(bound_evidence_root).strip()
        if bound_evidence_root is not None
        else str(os.environ.get(MULTIFETCH_EVIDENCE_ROOT_ENV) or "").strip()
    )
    if evidence_root_binding:
        evidence_root_binding = str(
            Path(evidence_root_binding).expanduser().resolve()
        )
    strict_evidence_binding = (
        bool(bound_strict_evidence)
        if bound_strict_evidence is not None
        else str(os.environ.get(STRICT_MULTIFETCH_EVIDENCE_ENV) or "")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )
    retained_replay_only_binding = (
        bool(bound_retained_replay_only)
        if bound_retained_replay_only is not None
        else str(os.environ.get(RETAINED_REPLAY_ONLY_ENV) or "")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )
    if bound_state_run_environment is not None:
        state_run_environment_binding = {
            str(name): (
                str(value if value is not None else "")
                if str(name) in _IMMUTABLE_STATE_RUN_SECRET_ENV_KEYS
                else str(value or "").strip()
            )
            for name, value in bound_state_run_environment.items()
        }
    else:
        state_run_environment_binding = _capture_state_law_run_environment()
    checkpoint_generation_key, checkpoint_generation = (
        claim_partial_checkpoint_generation(
            state_code=state_code,
            checkpoint_dir=checkpoint_dir_binding,
        )
    )
    bounded_env_lease_token = object()
    bounded_env_lease_state = {"status": "pending"}
    bounded_env_prior: Dict[str, Optional[str]] = {}
    bounded_env_applied: Dict[str, Optional[str]] = {}
    worker_finished = threading.Event()

    def _acquire_bounded_env_lease(values: Mapping[str, Optional[str]]) -> None:
        """Apply process-global bounded settings under an owned, revocable lease."""

        global _BOUNDED_ENV_LEASE_OWNER
        with _BOUNDED_ENV_LEASE_LOCK:
            if bounded_env_lease_state["status"] == "revoked":
                raise RuntimeError(
                    "bounded scraper environment lease was revoked before worker start"
                )
            if _BOUNDED_ENV_LEASE_OWNER is not None:
                raise RuntimeError(
                    "another bounded scraper worker owns the process environment lease"
                )
            _BOUNDED_ENV_LEASE_OWNER = bounded_env_lease_token
            bounded_env_prior.update(
                {key: os.environ.get(key) for key in _BOUNDED_ENV_KEYS}
            )
            for key, value in values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            bounded_env_applied.update(
                {key: os.environ.get(key) for key in _BOUNDED_ENV_KEYS}
            )
            bounded_env_lease_state["status"] = "active"

    def _release_bounded_env_lease(*, revoke: bool) -> None:
        """Restore only values still owned by this worker and prevent late writes."""

        global _BOUNDED_ENV_LEASE_OWNER
        with _BOUNDED_ENV_LEASE_LOCK:
            if revoke and bounded_env_lease_state["status"] == "pending":
                bounded_env_lease_state["status"] = "revoked"
                return
            if _BOUNDED_ENV_LEASE_OWNER is not bounded_env_lease_token:
                if revoke:
                    bounded_env_lease_state["status"] = "revoked"
                return
            for key in _BOUNDED_ENV_KEYS:
                # A later caller may have deliberately changed a value.  The
                # lease must never overwrite a value it no longer owns.
                if os.environ.get(key) != bounded_env_applied.get(key):
                    continue
                prior_value = bounded_env_prior.get(key)
                if prior_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = prior_value
            _BOUNDED_ENV_LEASE_OWNER = None
            bounded_env_lease_state["status"] = "revoked" if revoke else "released"

    def _publish_result(result: Dict[str, Any]) -> None:
        if not result_future.done():
            result_future.set_result(result)

    def _publish_exception(exc: BaseException) -> None:
        if not result_future.done():
            result_future.set_exception(exc)

    def _worker() -> None:
        prior_checkpoint_binding = bind_partial_checkpoint_run_directory(
            checkpoint_dir_binding
        )
        prior_state_run_environment = bind_state_law_worker_environment(
            state_run_environment_binding
        )
        global_bounded_env = str(os.environ.get("STATE_SCRAPER_GLOBAL_BOUNDED_ENV") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        bounded_timeout = max(0.0, float(timeout_seconds or 0.0))
        worker_exception: BaseException | None = None
        result: Dict[str, Any] = {}
        try:
            if (
                not global_bounded_env
                and max_statutes
                and int(max_statutes) > 0
                and bounded_timeout > 0
            ):
                timeouts = _derive_bounded_scraper_timeouts(bounded_timeout)
                code_timeout = max(
                    0.1,
                    float(timeouts.get("code_timeout_seconds") or 0.0),
                )
                fetch_timeout = max(
                    0.1,
                    float(timeouts.get("fetch_timeout_seconds") or 0.0),
                )
                disable_code_timeout_with_checkpoint = str(
                    os.environ.get(
                        "STATE_SCRAPER_DISABLE_CODE_TIMEOUT_WITH_CHECKPOINT",
                        "1",
                    )
                    or "1"
                ).strip().lower() in {"1", "true", "yes", "on"}
                checkpoint_dir_configured = bool(
                    str(
                        os.environ.get("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR", "")
                        or ""
                    ).strip()
                )
                if disable_code_timeout_with_checkpoint and checkpoint_dir_configured:
                    code_timeout = 0.0
                _acquire_bounded_env_lease(
                    {
                        "STATE_SCRAPER_CODE_TIMEOUT_SECONDS": (
                            f"{code_timeout:.3f}" if code_timeout > 0 else None
                        ),
                        "STATE_SCRAPER_FETCH_TIMEOUT_SECONDS": f"{fetch_timeout:.3f}",
                        "STATE_SCRAPER_MAX_STATUTES": str(int(max_statutes)),
                        "STATE_SCRAPER_BOUNDED_DIRECT_ONLY": "1",
                    }
                )
            result = _scrape_state_once_sync(
                state_code=state_code,
                legal_areas=legal_areas,
                rate_limit_delay=rate_limit_delay,
                max_statutes=max_statutes,
                strict_full_text=strict_full_text,
                min_full_text_chars=min_full_text_chars,
                hydrate_statute_text=hydrate_statute_text,
                per_state_timeout_seconds=timeout_seconds,
                checkpoint_generation_key=checkpoint_generation_key,
                checkpoint_generation=checkpoint_generation,
                bound_evidence_root=evidence_root_binding,
                bound_strict_evidence=strict_evidence_binding,
                bound_retained_replay_only=retained_replay_only_binding,
                bound_state_run_environment=state_run_environment_binding,
            )
        except BaseException as exc:
            worker_exception = exc
        finally:
            if not global_bounded_env:
                _release_bounded_env_lease(revoke=False)
            restore_state_law_worker_environment(prior_state_run_environment)
            restore_partial_checkpoint_run_directory(prior_checkpoint_binding)
            worker_finished.set()

        try:
            if worker_exception is not None:
                loop.call_soon_threadsafe(_publish_exception, worker_exception)
                return
            completed_result = dict(result or {})
            completed_result["worker_quiescence"] = {
                "attested": True,
                "quiescent": True,
                "worker_name": threading.current_thread().name,
                "completion_mode": "worker_returned",
            }
            loop.call_soon_threadsafe(_publish_result, completed_result)
        except RuntimeError:
            pass  # event loop already closed (e.g. outer timeout fired)

    worker = threading.Thread(
        target=_worker,
        name=f"state-scrape-{state_code.lower()}",
        daemon=True,
    )
    worker.start()
    try:
        if timeout_seconds <= 0:
            return await result_future

        poll_seconds_raw = str(os.getenv("STATE_SCRAPER_TIMEOUT_POLL_SECONDS", "") or "").strip()
        try:
            if poll_seconds_raw:
                poll_seconds = float(poll_seconds_raw)
            else:
                poll_seconds = min(15.0, max(0.01, float(timeout_seconds) / 4.0))
        except Exception:
            poll_seconds = min(15.0, max(0.01, float(timeout_seconds) / 4.0))
        poll_seconds = max(0.01, min(120.0, poll_seconds))
        checkpoint_complete_settle_raw = str(
            os.getenv("STATE_SCRAPER_CHECKPOINT_COMPLETE_SETTLE_SECONDS", "") or ""
        ).strip()
        try:
            if checkpoint_complete_settle_raw:
                checkpoint_complete_settle_seconds = float(checkpoint_complete_settle_raw)
            else:
                checkpoint_complete_settle_seconds = min(180.0, max(20.0, poll_seconds * 6.0))
        except Exception:
            checkpoint_complete_settle_seconds = min(180.0, max(20.0, poll_seconds * 6.0))
        checkpoint_complete_settle_seconds = max(0.05, checkpoint_complete_settle_seconds)

        grace_raw = str(os.getenv("STATE_SCRAPER_PROGRESS_GRACE_SECONDS", "") or "").strip()
        try:
            if grace_raw:
                progress_grace_seconds = float(grace_raw)
            elif float(timeout_seconds) <= 60.0:
                progress_grace_seconds = 0.0
            else:
                progress_grace_seconds = max(60.0, min(900.0, float(timeout_seconds) * 0.35))
        except Exception:
            progress_grace_seconds = 0.0 if float(timeout_seconds) <= 60.0 else max(60.0, min(900.0, float(timeout_seconds) * 0.35))
        progress_grace_seconds = max(0.0, progress_grace_seconds)

        hard_timeout_raw = str(os.getenv("STATE_SCRAPER_HARD_TIMEOUT_SECONDS", "") or "").strip()
        try:
            if hard_timeout_raw:
                hard_timeout_seconds = float(hard_timeout_raw)
            elif float(timeout_seconds) <= 60.0:
                hard_timeout_seconds = float(timeout_seconds) + max(0.02, float(timeout_seconds) * 0.25)
            else:
                hard_timeout_seconds = max(float(timeout_seconds) + progress_grace_seconds, float(timeout_seconds) * 6.0)
        except Exception:
            if float(timeout_seconds) <= 60.0:
                hard_timeout_seconds = float(timeout_seconds) + max(0.02, float(timeout_seconds) * 0.25)
            else:
                hard_timeout_seconds = max(float(timeout_seconds) + progress_grace_seconds, float(timeout_seconds) * 6.0)
        if hard_timeout_seconds <= 0.0:
            hard_timeout_seconds = float(timeout_seconds) + progress_grace_seconds

        start_ts = time.time()
        checkpoint_activity = _read_partial_checkpoint_activity(
            state_code,
            checkpoint_dir=checkpoint_dir_binding,
        )
        last_signature = checkpoint_activity.get("signature", tuple())
        last_signature_mode = str(checkpoint_activity.get("signature_mode") or "")
        last_progress_ts = start_ts
        last_signature_change_ts = start_ts
        initial_checkpoint_updated_ts = float(checkpoint_activity.get("updated_ts") or 0.0)
        if initial_checkpoint_updated_ts > 0.0:
            last_progress_ts = max(last_progress_ts, initial_checkpoint_updated_ts)

        while True:
            now_ts = time.time()
            elapsed = now_ts - start_ts
            if result_future.done():
                return result_future.result()
            if elapsed >= hard_timeout_seconds:
                break
            wait_window = min(poll_seconds, max(0.25, hard_timeout_seconds - elapsed))
            await asyncio.sleep(wait_window)
            if result_future.done():
                return result_future.result()

            activity = _read_partial_checkpoint_activity(
                state_code,
                checkpoint_dir=checkpoint_dir_binding,
            )
            signature = activity.get("signature", tuple())
            signature_mode = str(activity.get("signature_mode") or "")
            signature_reliable = signature_mode == "full"
            last_signature_reliable = last_signature_mode == "full"
            updated_ts = float(activity.get("updated_ts") or 0.0)
            signature_changed = bool(
                signature_reliable
                and signature
                and (
                    (not last_signature_reliable)
                    or signature != last_signature
                )
            )
            checkpoint_signal_found = bool(activity.get("signal_found"))
            checkpoint_work_remaining = activity.get("work_remaining")
            checkpoint_signal_complete = checkpoint_signal_found and checkpoint_work_remaining is False
            checkpoint_advanced = bool(updated_ts > initial_checkpoint_updated_ts + 1e-6)
            if signature_changed:
                last_signature = signature
                last_signature_mode = signature_mode
                last_progress_ts = now_ts
                last_signature_change_ts = now_ts
            elif signature_reliable and signature and not last_signature_reliable:
                # Establish a reliable signature baseline without forcing a reset.
                last_signature = signature
                last_signature_mode = signature_mode
            elif checkpoint_advanced and updated_ts > last_progress_ts and not checkpoint_signal_complete:
                # Treat checkpoint freshness as weak progress, even if
                # counters are unchanged.
                last_progress_ts = updated_ts

            checkpoint_stage_complete = bool(activity.get("stage_complete"))
            checkpoint_statutes_count = _safe_int(activity.get("statutes_count"), 0)
            if checkpoint_stage_complete or checkpoint_signal_complete:
                if checkpoint_statutes_count <= 0:
                    continue
                checkpoint_age_seconds = max(0.0, now_ts - updated_ts) if updated_ts > 0 else 0.0
                signal_stability_age_seconds = max(0.0, now_ts - last_signature_change_ts)
                settle_age_seconds = max(checkpoint_age_seconds, signal_stability_age_seconds)
                if settle_age_seconds >= checkpoint_complete_settle_seconds:
                    promoted = _load_partial_checkpoint_state_success_result(
                        state_code,
                        reason=(
                            "checkpoint_signal_complete_settled"
                            if checkpoint_signal_complete and not checkpoint_stage_complete
                            else "checkpoint_complete_settled"
                        ),
                        require_no_remaining_work=checkpoint_signal_complete,
                        checkpoint_dir=checkpoint_dir_binding,
                        strict_evidence=strict_evidence_binding,
                    )
                    # A complete checkpoint is diagnostic while the producing
                    # daemon is still live.  It cannot stand in for worker
                    # lifecycle completion or authorize a retry/final seal.
                    if promoted is not None:
                        last_progress_ts = max(last_progress_ts, now_ts)

            elapsed = now_ts - start_ts
            since_progress = now_ts - last_progress_ts
            if elapsed >= float(timeout_seconds) and since_progress >= progress_grace_seconds:
                break

        # Revoke the worker's process-global environment lease before control
        # returns.  Its eventual ``finally`` observes the revoked token and
        # cannot overwrite settings from a later test or acquisition run.
        _release_bounded_env_lease(revoke=True)
        raise StateScraperNonQuiescentTimeout(
            state_code,
            str(getattr(worker, "name", f"state-scrape-{state_code.lower()}")),
            timeout_seconds,
        )
    finally:
        # Backend-neutral cancellation/abandonment cleanup: any exit while the
        # daemon remains live revokes its process-global environment lease.
        # The late worker's own ``finally`` then observes that revocation and
        # cannot overwrite values installed by a later supervisor.
        if not worker_finished.is_set():
            _release_bounded_env_lease(revoke=True)


async def _scrape_state_with_retries(
    *,
    state_code: str,
    legal_areas: Optional[List[str]],
    rate_limit_delay: float,
    max_statutes: Optional[int],
    strict_full_text: bool,
    min_full_text_chars: int,
    hydrate_statute_text: bool,
    retry_attempts: int,
    retry_zero_statute_states: bool,
    per_state_timeout_seconds: float,
    bound_state_run_environment: Optional[
        Mapping[str, Optional[str]]
    ] = None,
) -> Dict[str, Any]:
    attempts = 1 + max(0, int(retry_attempts or 0))
    best: Optional[Dict[str, Any]] = None
    full_corpus_mode = bool(max_statutes is None and _env_full_corpus_enabled())
    checkpoint_dir_binding = str(
        os.environ.get("STATE_SCRAPER_PARTIAL_CHECKPOINT_DIR") or ""
    ).strip()
    if checkpoint_dir_binding:
        checkpoint_dir_binding = str(
            Path(checkpoint_dir_binding).expanduser().resolve()
        )
    evidence_root_binding = str(
        os.environ.get(MULTIFETCH_EVIDENCE_ROOT_ENV) or ""
    ).strip()
    if evidence_root_binding:
        evidence_root_binding = str(
            Path(evidence_root_binding).expanduser().resolve()
        )
    strict_evidence_binding = str(
        os.environ.get(STRICT_MULTIFETCH_EVIDENCE_ENV) or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    retained_replay_only_binding = str(
        os.environ.get(RETAINED_REPLAY_ONLY_ENV) or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    state_run_environment_binding = (
        {
            str(name): (
                str(value if value is not None else "")
                if str(name) in _IMMUTABLE_STATE_RUN_SECRET_ENV_KEYS
                else str(value or "").strip()
            )
            for name, value in bound_state_run_environment.items()
        }
        if bound_state_run_environment is not None
        else _capture_state_law_run_environment()
    )

    for attempt_idx in range(attempts):
        try:
            timeout_seconds = float(per_state_timeout_seconds or 0.0)
            result = await _run_sync_scrape_on_daemon_thread(
                state_code=state_code,
                legal_areas=legal_areas,
                rate_limit_delay=rate_limit_delay,
                max_statutes=max_statutes,
                strict_full_text=strict_full_text,
                min_full_text_chars=min_full_text_chars,
                hydrate_statute_text=hydrate_statute_text,
                timeout_seconds=timeout_seconds,
                bound_checkpoint_dir=checkpoint_dir_binding,
                bound_strict_evidence=strict_evidence_binding,
                bound_evidence_root=evidence_root_binding,
                bound_retained_replay_only=retained_replay_only_binding,
                bound_state_run_environment=state_run_environment_binding,
            )
        except StateScraperNonQuiescentTimeout as exc:
            state_name = US_STATES[state_code]
            error_msg = (
                f"Failed to scrape {state_name} using state-specific scraper: "
                f"{exc}"
            )
            logger.error(error_msg)
            checkpoint_result = _load_partial_checkpoint_state_result(
                state_code,
                error_msg,
                checkpoint_dir=checkpoint_dir_binding,
            )
            result = dict(checkpoint_result or {})
            result.update(
                {
                    "state_code": state_code,
                    "state_name": state_name,
                    "error": error_msg,
                    "zero_statute": int(result.get("statutes_count") or 0) <= 0,
                    "worker_quiescence": {
                        "attested": True,
                        "quiescent": False,
                        "worker_name": exc.worker_name,
                        "completion_mode": "supervisor_timeout_worker_still_live",
                    },
                }
            )
            diagnostics = dict(result.get("timeout_diagnostics") or {})
            diagnostics.update(
                {
                    "timed_out": True,
                    "classification": "timeout_nonquiescent_worker",
                    "worker_quiescent": False,
                    "retry_authorized": False,
                    "publication_authorized": False,
                }
            )
            result["timeout_diagnostics"] = diagnostics
            statute_data = dict(result.get("statute_data") or {})
            statute_data.update(
                {
                    "state_code": state_code,
                    "state_name": state_name,
                    "error": error_msg,
                    "timeout_diagnostics": diagnostics,
                }
            )
            statute_data.setdefault("statutes", [])
            result["statute_data"] = statute_data
            warnings = list(result.get("warnings") or [])
            warnings.append(
                f"{state_code} retry suppressed because timed-out worker is nonquiescent"
            )
            result["warnings"] = warnings
            # A new attempt could overlap the still-running writer and can
            # never repair this run's lifecycle proof.
            return result
        except asyncio.TimeoutError:
            state_name = US_STATES[state_code]
            error_msg = (
                f"Failed to scrape {state_name} using state-specific scraper: "
                f"timed out after {per_state_timeout_seconds} seconds"
            )
            logger.error(error_msg)
            checkpoint_result = _load_partial_checkpoint_state_result(
                state_code,
                error_msg,
                checkpoint_dir=checkpoint_dir_binding,
            )
            if checkpoint_result is not None:
                result = _promote_timeout_checkpoint_result_if_no_remaining_work(
                    state_code,
                    checkpoint_result,
                    reason="checkpoint_timeout_no_remaining_work",
                    checkpoint_dir=checkpoint_dir_binding,
                    strict_evidence=strict_evidence_binding,
                ) or checkpoint_result
            else:
                timeout_diagnostics = {
                    "timed_out": True,
                    "classification": "timeout_without_partial_checkpoint",
                    "signal_found": False,
                    "signal_kind": "",
                    "work_remaining": None,
                    "progress_scanned": None,
                    "progress_discovered": None,
                    "coverage_ratio": None,
                    "checkpoint_updated_at": "",
                    "checkpoint_stage_label": "",
                    "checkpoint_counters": {},
                }
                result = {
                    "state_code": state_code,
                    "state_name": state_name,
                    "error": error_msg,
                    "statutes_count": 0,
                    "zero_statute": True,
                    "low_quality": False,
                    "quality_metrics": {"total": 0, "nav_like_ratio": 0.0, "fallback_section_ratio": 0.0, "numeric_section_name_ratio": 0.0, "scaffold_ratio": 0.0},
                    "warnings": [
                        f"{state_code} timed out while scraping",
                        f"{state_code} timeout_diagnostics={timeout_diagnostics.get('classification')}",
                    ],
                    "timeout_diagnostics": timeout_diagnostics,
                    "statute_data": {
                        "state_code": state_code,
                        "state_name": state_name,
                        "title": f"{state_name} Laws",
                        "source": "Official State Legislative Website",
                        "error": error_msg,
                        "scraped_at": datetime.now().isoformat(),
                        "statutes": [],
                        "timeout_diagnostics": timeout_diagnostics,
                    },
                }
        except Exception as e:
            state_name = US_STATES[state_code]
            error_msg = f"Failed to scrape {state_name} using state-specific scraper: {str(e)}"
            logger.error(error_msg)
            checkpoint_result = _load_partial_checkpoint_state_result(
                state_code,
                error_msg,
                checkpoint_dir=checkpoint_dir_binding,
            )
            if checkpoint_result is not None:
                result = _promote_timeout_checkpoint_result_if_no_remaining_work(
                    state_code,
                    checkpoint_result,
                    reason="checkpoint_error_no_remaining_work",
                    checkpoint_dir=checkpoint_dir_binding,
                    strict_evidence=strict_evidence_binding,
                ) or checkpoint_result
            else:
                timeout_diagnostics = {
                    "timed_out": "timed out" in str(error_msg).lower(),
                    "classification": "error_without_partial_checkpoint",
                    "signal_found": False,
                    "signal_kind": "",
                    "work_remaining": None,
                    "progress_scanned": None,
                    "progress_discovered": None,
                    "coverage_ratio": None,
                    "checkpoint_updated_at": "",
                    "checkpoint_stage_label": "",
                    "checkpoint_counters": {},
                }
                result = {
                    "state_code": state_code,
                    "state_name": state_name,
                    "error": error_msg,
                    "statutes_count": 0,
                    "zero_statute": True,
                    "low_quality": False,
                    "quality_metrics": {"total": 0, "nav_like_ratio": 0.0, "fallback_section_ratio": 0.0, "numeric_section_name_ratio": 0.0, "scaffold_ratio": 0.0},
                    "warnings": [
                        f"{state_code} returned zero statutes",
                        f"{state_code} timeout_diagnostics={timeout_diagnostics.get('classification')}",
                    ],
                    "timeout_diagnostics": timeout_diagnostics,
                    "statute_data": {
                        "state_code": state_code,
                        "state_name": state_name,
                        "title": f"{state_name} Laws",
                        "source": "Official State Legislative Website",
                        "error": str(e),
                        "scraped_at": datetime.now().isoformat(),
                        "statutes": [],
                        "timeout_diagnostics": timeout_diagnostics,
                    },
                }

        result = dict(result or {})
        result.setdefault(
            "worker_quiescence",
            {
                "attested": True,
                "quiescent": True,
                "worker_name": f"state-scrape-{state_code.lower()}",
                "completion_mode": "worker_future_resolved",
            },
        )
        low_quality = bool(result.get("low_quality"))
        statutes_count = int(result.get("statutes_count") or 0)
        if full_corpus_mode and low_quality and statutes_count > 0 and not result.get("error"):
            quality = result.get("quality_metrics") or {}
            quality_msg = (
                f"{state_code} full-corpus quality gate failed; likely non-substantive scrape "
                f"(total={quality.get('total')}, bill_history={quality.get('bill_history_ratio')}, "
                f"scaffold={quality.get('scaffold_ratio')}, nav={quality.get('nav_like_ratio')})"
            )
            logger.warning(quality_msg)
            result = dict(result)
            result["error"] = quality_msg
            warnings = list(result.get("warnings") or [])
            warnings.append(quality_msg)
            result["warnings"] = warnings

        if best is None:
            best = result
        else:
            prior_count = int(best.get("statutes_count") or 0)
            current_count = int(result.get("statutes_count") or 0)
            if current_count > prior_count:
                best = result
            elif current_count == prior_count and best.get("error") and not result.get("error"):
                best = result

        if attempt_idx >= attempts - 1:
            break

        should_retry = bool(result.get("error"))
        if retry_zero_statute_states and int(result.get("statutes_count") or 0) == 0:
            should_retry = True
        if not should_retry:
            break

        await asyncio.sleep(max(0.0, rate_limit_delay) + (attempt_idx + 1) * 0.5)

    return best or {
        "state_code": state_code,
        "state_name": US_STATES[state_code],
        "error": "missing-state-result",
        "statutes_count": 0,
        "zero_statute": True,
        "low_quality": False,
        "quality_metrics": {"total": 0, "nav_like_ratio": 0.0, "fallback_section_ratio": 0.0, "numeric_section_name_ratio": 0.0, "scaffold_ratio": 0.0},
        "warnings": [f"{state_code} returned zero statutes"],
        "statute_data": {
            "state_code": state_code,
            "state_name": US_STATES[state_code],
            "title": f"{US_STATES[state_code]} Laws",
            "source": "Official State Legislative Website",
            "error": "missing-state-result",
            "scraped_at": datetime.now().isoformat(),
            "statutes": [],
        },
    }


def _trim_scraped_statutes_to_max(
    scraped_statutes: List[Dict[str, Any]],
    max_statutes: int,
) -> tuple[List[Dict[str, Any]], int]:
    if max_statutes <= 0:
        return scraped_statutes, sum(len((block or {}).get("statutes") or []) for block in scraped_statutes)

    trimmed: List[Dict[str, Any]] = []
    per_state_limit = int(max_statutes)
    for block in scraped_statutes:
        if not isinstance(block, dict):
            continue

        statutes = list(block.get("statutes") or [])
        kept = statutes[:per_state_limit]

        out_block = dict(block)
        out_block["statutes"] = kept
        out_block["quality_metrics"] = _compute_state_quality_metrics(kept)
        out_block["quality_flag"] = _should_flag_quality(out_block["quality_metrics"])
        trimmed.append(out_block)

    total = sum(len((block or {}).get("statutes") or []) for block in trimmed)
    return trimmed, total


def _compact_state_result_for_retention(result: Dict[str, Any]) -> Dict[str, Any]:
    """Drop bulky statute rows after a completion callback has persisted them.

    Long full-corpus daemon runs write/build/publish each completed state
    incrementally. Keeping the same large statute list in the final
    ``scrape_state_laws`` return value doubles memory pressure and can retain
    hundreds of thousands of rows until the last state completes.
    """
    compact = dict(result or {})
    statute_data = dict(compact.get("statute_data") or {})
    statutes = statute_data.get("statutes") or []
    statute_count = int(compact.get("statutes_count") or len(statutes) or 0)
    statute_data["statutes"] = []
    statute_data["statutes_count"] = statute_count
    statute_data["streamed_to_state_completion_callback"] = True
    compact["statute_data"] = statute_data
    return compact


def _compute_coverage_summary(
    *,
    selected_states: List[str],
    scraped_statutes: List[Dict[str, Any]],
    errors: List[str],
) -> Dict[str, Any]:
    """Summarize scrape coverage for the *requested* state set.

    LCR-007: a nonzero, error-free requested subset is **not** full-corpus
    coverage. ``full_coverage`` means the requested scope closed without gaps;
    ``full_corpus_coverage`` is true only for the exact 51-jurisdiction set
    (50 states + DC) with no gaps. Partial success must never promote to a
    production full-corpus claim.
    """
    states_targeted = len(selected_states)
    present_states = set()
    zero_states: List[str] = []
    error_states: List[str] = []
    selected_normalized = [str(code).upper() for code in selected_states]

    for block in scraped_statutes:
        if not isinstance(block, dict):
            continue
        state_code = str(block.get("state_code") or "").upper()
        if not state_code:
            continue
        present_states.add(state_code)
        statutes = block.get("statutes") or []
        retained_count = int(block.get("statutes_count") or 0)
        if len(statutes) == 0 and retained_count <= 0:
            zero_states.append(state_code)
        if block.get("error"):
            error_states.append(state_code)

    missing_states = [code for code in selected_normalized if code not in present_states]
    coverage_gap_states = sorted(set(zero_states + error_states + missing_states))
    requested_closed = len(coverage_gap_states) == 0 and not errors

    canonical_set = frozenset(US_STATES.keys())
    selected_set = set(selected_normalized)
    is_exact_51 = selected_set == canonical_set and len(selected_set) == len(US_STATES)
    includes_dc = "DC" in selected_set
    # Requested-scope success only — never imply production full-corpus coverage
    # for a subset or a 50-state run without DC.
    full_corpus_coverage = bool(requested_closed and is_exact_51 and includes_dc)

    return {
        "states_targeted": states_targeted,
        "states_returned": len(present_states),
        "states_with_nonzero_statutes": max(0, len(present_states) - len(set(zero_states))),
        "zero_statute_states": sorted(set(zero_states)),
        "error_states": sorted(set(error_states)),
        "missing_states": missing_states,
        "coverage_gap_states": coverage_gap_states,
        # Backward-compatible: full_coverage == requested scope closed.
        "full_coverage": requested_closed,
        "coverage_scope": "full_corpus" if is_exact_51 else "requested_scope",
        "full_corpus_coverage": full_corpus_coverage,
        "exact_51_jurisdiction_set": is_exact_51,
        "includes_dc": includes_dc,
        "production_release_eligible": full_corpus_coverage,
    }


def _aggregate_fetch_analytics(fetch_analytics_by_state: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    if not fetch_analytics_by_state:
        return {
            "states_with_fetch_analytics": 0,
            "attempted": 0,
            "success": 0,
            "success_ratio": 0.0,
            "fallback_count": 0,
            "providers": {},
        }

    attempted = 0
    success = 0
    fallback_count = 0
    providers: Dict[str, int] = {}

    for state_metrics in fetch_analytics_by_state.values():
        if not isinstance(state_metrics, dict):
            continue
        attempted += int(state_metrics.get("attempted", 0) or 0)
        success += int(state_metrics.get("success", 0) or 0)
        fallback_count += int(state_metrics.get("fallback_count", 0) or 0)

        provider_counts = state_metrics.get("providers") or {}
        if isinstance(provider_counts, dict):
            for provider, count in provider_counts.items():
                providers[str(provider)] = int(providers.get(str(provider), 0) or 0) + int(count or 0)

    return {
        "states_with_fetch_analytics": len(fetch_analytics_by_state),
        "attempted": attempted,
        "success": success,
        "success_ratio": round((success / attempted), 3) if attempted > 0 else 0.0,
        "fallback_count": fallback_count,
        "providers": providers,
    }


def _compute_etl_readiness_summary(scraped_statutes: List[Dict[str, Any]]) -> Dict[str, Any]:
    state_count = 0
    total_statutes = 0
    statutes_with_text = 0
    statutes_with_jsonld = 0
    statutes_with_jsonld_legislation = 0
    statutes_with_kg_payload = 0
    statutes_with_citations = 0
    statutes_with_statute_signals = 0
    non_scaffold_statutes = 0
    states_with_zero = 0
    states_with_jsonld = 0

    for state_block in scraped_statutes:
        if not isinstance(state_block, dict):
            continue
        state_count += 1
        statutes = state_block.get("statutes") or []
        retained_count = int(state_block.get("statutes_count") or 0)
        if not statutes and retained_count <= 0:
            states_with_zero += 1

        state_jsonld_hits = 0
        for statute in statutes:
            if not isinstance(statute, dict):
                continue
            total_statutes += 1

            full_text = str(statute.get("full_text") or statute.get("text") or "").strip()
            section_name = str(statute.get("section_name") or statute.get("sectionName") or "")
            section_number = str(statute.get("section_number") or statute.get("sectionNumber") or "")
            if len(full_text) >= 120:
                statutes_with_text += 1

            if not _is_scaffold_or_navigation_record(statute):
                non_scaffold_statutes += 1

            if (
                _QUALITY_SECTION_SIGNAL_RE.search(full_text)
                or _QUALITY_SECTION_SIGNAL_RE.search(section_name)
                or _QUALITY_SECTION_NUMBER_RE.match(section_number)
            ):
                statutes_with_statute_signals += 1

            structured_data = statute.get("structured_data") or {}
            if isinstance(structured_data, dict):
                jsonld = structured_data.get("jsonld")
                if isinstance(jsonld, dict):
                    statutes_with_jsonld += 1
                    state_jsonld_hits += 1

                    if str(jsonld.get("@type") or "").strip().lower() == "legislation":
                        statutes_with_jsonld_legislation += 1

                    # Require core fields used by downstream KG ETL transforms.
                    has_identity = bool(
                        str(jsonld.get("identifier") or "").strip()
                        or str(jsonld.get("@id") or "").strip()
                        or str(jsonld.get("sourceUrl") or "").strip()
                    )
                    has_name = bool(
                        str(jsonld.get("name") or "").strip()
                        or str(jsonld.get("sectionName") or "").strip()
                    )
                    has_locator = bool(str(jsonld.get("sectionNumber") or "").strip())
                    has_text = bool(str(jsonld.get("text") or "").strip())

                    if has_identity and has_name and has_locator and has_text:
                        statutes_with_kg_payload += 1

                citations = structured_data.get("citations") or {}
                if isinstance(citations, dict):
                    citation_items = 0
                    for value in citations.values():
                        if isinstance(value, list):
                            citation_items += len(value)
                    if citation_items > 0:
                        statutes_with_citations += 1

        if state_jsonld_hits > 0:
            states_with_jsonld += 1

    full_text_ratio = round((statutes_with_text / total_statutes), 3) if total_statutes > 0 else 0.0
    jsonld_ratio = round((statutes_with_jsonld / total_statutes), 3) if total_statutes > 0 else 0.0
    jsonld_legislation_ratio = (
        round((statutes_with_jsonld_legislation / total_statutes), 3) if total_statutes > 0 else 0.0
    )
    kg_payload_ratio = round((statutes_with_kg_payload / total_statutes), 3) if total_statutes > 0 else 0.0
    citation_ratio = round((statutes_with_citations / total_statutes), 3) if total_statutes > 0 else 0.0
    statute_signal_ratio = (
        round((statutes_with_statute_signals / total_statutes), 3) if total_statutes > 0 else 0.0
    )
    non_scaffold_ratio = round((non_scaffold_statutes / total_statutes), 3) if total_statutes > 0 else 0.0

    return {
        "states_processed": state_count,
        "states_with_zero_statutes": states_with_zero,
        "states_with_jsonld": states_with_jsonld,
        "total_statutes": total_statutes,
        "full_text_ratio": full_text_ratio,
        "jsonld_ratio": jsonld_ratio,
        "jsonld_legislation_ratio": jsonld_legislation_ratio,
        "kg_payload_ratio": kg_payload_ratio,
        "citation_ratio": citation_ratio,
        "statute_signal_ratio": statute_signal_ratio,
        "non_scaffold_ratio": non_scaffold_ratio,
        "ready_for_kg_etl": bool(
            total_statutes > 0
            and full_text_ratio >= 0.85
            and jsonld_ratio >= 0.75
            and jsonld_legislation_ratio >= 0.70
            and kg_payload_ratio >= 0.70
            and statute_signal_ratio >= 0.70
            and non_scaffold_ratio >= 0.85
        ),
    }


def _write_state_jsonld_files(scraped_statutes: List[Dict[str, Any]], jsonld_dir: Path) -> List[str]:
    written: List[str] = []
    for state_block in scraped_statutes:
        state_code = str(state_block.get("state_code") or "").strip().upper()
        state_name = str(state_block.get("state_name") or "").strip()
        statutes = state_block.get("statutes") or []
        if not state_code or not isinstance(statutes, list):
            continue

        out_path = jsonld_dir / f"STATE-{state_code}.jsonld"
        prior_exists = out_path.exists()
        prior_size = out_path.stat().st_size if prior_exists else 0
        prior_lines = 0
        if prior_exists and prior_size > 0:
            try:
                with out_path.open("r", encoding="utf-8", errors="ignore") as prior_handle:
                    prior_lines = sum(1 for line in prior_handle if line.strip())
            except Exception:
                prior_lines = 0
        tmp_path = out_path.with_suffix(".jsonld.tmp")
        lines_written = 0
        with tmp_path.open("w", encoding="utf-8") as handle:
            for statute in statutes:
                if not isinstance(statute, dict):
                    continue
                structured_data = statute.get("structured_data") or {}
                if not isinstance(structured_data, dict):
                    structured_data = {}

                payload = structured_data.get("jsonld")
                if not isinstance(payload, dict):
                    payload = _build_fallback_jsonld_payload(
                        state_code=state_code,
                        state_name=state_name,
                        statute=statute,
                    )
                if not isinstance(payload, dict):
                    continue
                payload = _jsonld_payload_with_row_provenance(
                    payload,
                    structured_data=structured_data,
                )
                handle.write(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
                )
                lines_written += 1

        if lines_written > 0:
            if prior_exists and prior_lines > lines_written:
                # Keep best-known state output when a run returns fewer records.
                tmp_path.unlink(missing_ok=True)
                written.append(str(out_path))
            else:
                tmp_path.replace(out_path)
                written.append(str(out_path))
        else:
            tmp_path.unlink(missing_ok=True)
            if prior_exists and prior_size > 0:
                # Preserve prior non-empty state output if this run yielded zero records.
                written.append(str(out_path))

    return written


_JSONLD_ROW_PROVENANCE_FIELDS = (
    "body_sha256",
    "content_digest",
    "content_sha256",
    "raw_sha256",
    "source_record_id",
    "source_checksum",
    "transport_receipt",
    "transport_receipts",
    "web_archiving_transport_receipt",
    "web_archiving_transport_receipts",
)


def _jsonld_payload_with_row_provenance(
    payload: Mapping[str, Any],
    *,
    structured_data: Mapping[str, Any],
) -> Dict[str, Any]:
    """Retain exact row transport evidence in the canonical JSON-LD projection.

    Scrapers keep byte-level acquisition evidence beside their JSON-LD while
    they are running.  The release adapter consumes JSON-LD, so dropping that
    evidence would sever an otherwise verified official-byte binding.  Copy
    only the release-critical provenance fields into ``structuredData`` and
    fail closed if the producer already declared a different value.  The
    source payload and its nested mappings are never mutated.
    """

    result = dict(payload)
    existing_nested = result.get("structuredData")
    if existing_nested is None:
        retained: Dict[str, Any] = {}
    elif isinstance(existing_nested, Mapping):
        retained = dict(existing_nested)
    else:
        raise ValueError("JSON-LD structuredData must be a mapping")

    existing_provenance = [result]
    for container_key in ("provenance", "structured_data", "structuredData"):
        container = result.get(container_key)
        if isinstance(container, Mapping):
            existing_provenance.append(container)

    for key in _JSONLD_ROW_PROVENANCE_FIELDS:
        if key not in structured_data:
            continue
        value = structured_data[key]
        if value is None or value == "":
            continue
        already_retained = False
        for container in existing_provenance:
            if key not in container:
                continue
            if container[key] != value:
                raise ValueError(f"conflicting JSON-LD row provenance field: {key}")
            already_retained = True
        if already_retained:
            continue
        retained[key] = value

    if retained:
        result["structuredData"] = retained
    return result


def _build_fallback_jsonld_payload(*, state_code: str, state_name: str, statute: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    full_text = str(statute.get("full_text") or "").strip()
    section_number = str(statute.get("section_number") or "").strip()
    section_name = str(statute.get("section_name") or "").strip()
    code_name = str(statute.get("code_name") or "").strip()
    source_url = str(statute.get("source_url") or "").strip()
    statute_id = str(statute.get("statute_id") or "").strip() or section_number or section_name

    if not (full_text or section_name or section_number or statute_id):
        return None

    title_parts = [part for part in [state_name or state_code, code_name, section_number] if part]
    title = " - ".join(title_parts) or f"{state_code} statute"
    legislation_id = statute_id or title

    payload: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Legislation",
        "legislationType": "StateStatute",
        "legislationJurisdiction": f"US-{state_code}",
        "name": title,
        "identifier": legislation_id,
        "description": section_name or full_text[:500],
        "text": full_text or section_name,
        "url": source_url,
    }

    if source_url:
        payload["sameAs"] = source_url
    if code_name:
        payload["legislationIdentifier"] = code_name

    return payload


def _has_sufficient_full_text(
    statute: Any,
    *,
    min_full_text_chars: int,
    source_bound_operative_checker: Optional[Callable[[Any], bool]] = None,
) -> bool:
    fields = _extract_statute_quality_fields(statute)
    full_text = fields["full_text"]

    if len(full_text.strip()) < int(min_full_text_chars):
        return False
    if _QUALITY_SCAFFOLD_TEXT_RE.match(full_text):
        return False

    # State-owned strict parsers may prove that operative text which happens
    # to contain generic navigation words (for example, "calendar" or
    # "meetings") belongs to an exact closed source frontier.  Keep the
    # explicit placeholder and length checks above authoritative, then allow
    # that existing state-specific proof seam to outrank only the heuristic.
    if callable(source_bound_operative_checker) and bool(
        source_bound_operative_checker(statute)
    ):
        return True

    if _is_scaffold_or_navigation_record(statute):
        return False

    structured_data = getattr(statute, "structured_data", None)
    if structured_data is None and isinstance(statute, dict):
        structured_data = statute.get("structured_data") or {}

    if isinstance(structured_data, dict):
        subsections = structured_data.get("subsections") or []
        citations = structured_data.get("citations") or {}
        if isinstance(subsections, list) and len(subsections) > 0:
            return True
        if isinstance(citations, dict):
            total_cites = sum(
                len(v) for v in citations.values() if isinstance(v, list)
            )
            if total_cites > 0:
                return True

    # If text length threshold passes and it is not navigation/scaffold content, allow it.
    return True


def _filter_strict_full_text_statutes(
    statutes: List[Any],
    *,
    min_full_text_chars: int,
    source_bound_operative_checker: Optional[Callable[[Any], bool]] = None,
) -> tuple[List[Any], int]:
    kept: List[Any] = []
    removed = 0
    for statute in statutes:
        if _has_sufficient_full_text(
            statute,
            min_full_text_chars=min_full_text_chars,
            source_bound_operative_checker=source_bound_operative_checker,
        ):
            kept.append(statute)
        else:
            removed += 1
    return kept, removed


def _identify_legal_area(text: str, legal_areas: Optional[List[str]] = None) -> str:
    """Identify the legal area from statute title text."""
    text_lower = text.lower()
    
    # Common legal area keywords
    area_keywords = {
        "criminal": ["criminal", "penal", "crime", "felony", "misdemeanor"],
        "civil": ["civil", "tort", "liability", "damages"],
        "family": ["family", "marriage", "divorce", "custody", "child support"],
        "employment": ["employment", "labor", "worker", "wage", "unemployment"],
        "environmental": ["environmental", "pollution", "conservation", "wildlife"],
        "business": ["business", "corporation", "commercial", "contract", "sales"],
        "property": ["property", "real estate", "land", "conveyance"],
        "tax": ["tax", "taxation", "revenue", "assessment"],
        "health": ["health", "medical", "healthcare", "insurance"],
        "education": ["education", "school", "university", "student"],
    }
    
    # Check if user specified legal areas
    if legal_areas:
        for area in legal_areas:
            if area.lower() in text_lower:
                return area
    
    # Auto-detect legal area
    for area, keywords in area_keywords.items():
        for keyword in keywords:
            if keyword in text_lower:
                return area
    
    return "general"


__all__ = [
    "DEFAULT_MIN_FULL_TEXT_CHARS",
    "build_state_law_section_url",
    "list_state_jurisdictions",
    "scrape_state_laws",
]
