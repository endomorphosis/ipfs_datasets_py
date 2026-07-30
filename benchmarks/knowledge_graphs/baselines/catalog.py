"""Baseline catalog, schema constants, and disk loaders (KGP-030)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

JSONDict = Dict[str, Any]

BASELINE_SCHEMA = "ipfs-datasets.knowledge-graphs.load-baseline.v1"
BASELINE_SCHEMA_VERSION = 1

# Absolute p95 / throughput claims are environment-bound. Relative release
# gate from the production hardening plan (KGP-G090 / KGP-030).
REGRESSION_RATIO_LIMIT = 0.10

# Profiles that must have labelled baselines (acceptance criteria).
REQUIRED_BASELINE_PROFILES: Tuple[str, ...] = (
    "smoke",
    "corpus_211",
    "corpus_cvefixes",
    "synthetic_large",
    "concurrent_mixed",
)

# CI-friendly profile also kept so local/harness correctness has a baseline.
OPTIONAL_BASELINE_PROFILES: Tuple[str, ...] = ("tiny",)

# Hard correctness / security error budget (always zero).
CORRECTNESS_ERROR_MAX = 0
SECURITY_ERROR_MAX = 0

REQUIRED_BASELINE_KEYS: Tuple[str, ...] = (
    "schema",
    "schema_version",
    "baseline_id",
    "profile",
    "environment_label",
    "environment",
    "methodology",
    "metrics",
    "gates",
    "status",
    "ratified_at",
)

REQUIRED_METHODOLOGY_KEYS: Tuple[str, ...] = (
    "warmup_runs",
    "warmup_operations",
    "repetitions",
    "variance_model",
    "matrix_mode",
    "surfaces",
    "storage_profiles",
)

REQUIRED_METRIC_KEYS: Tuple[str, ...] = (
    "p95_ms",
    "p99_ms",
    "ops_per_s",
    "recovery_ms_mean",
    "max_rss_bytes",
)

REQUIRED_METRIC_SUMMARY_KEYS: Tuple[str, ...] = (
    "median",
    "mean",
    "stdev",
    "n",
    "bound",
    "samples",
)


def baselines_root() -> Path:
    """Return the on-disk root for labelled baseline artifacts."""
    return Path(__file__).resolve().parent


def environments_root() -> Path:
    return baselines_root() / "environments"


def catalog_path() -> Path:
    return baselines_root() / "catalog.json"


@dataclass(frozen=True, slots=True)
class BaselineRef:
    """Pointer to one labelled baseline document."""

    profile: str
    environment_label: str
    path: Path
    status: str
    baseline_id: str

    def to_json_dict(self) -> JSONDict:
        return {
            "profile": self.profile,
            "environment_label": self.environment_label,
            "path": str(self.path.relative_to(baselines_root())).replace("\\", "/"),
            "status": self.status,
            "baseline_id": self.baseline_id,
        }


@dataclass
class BaselineCatalog:
    """Index of labelled baselines across environments."""

    schema: str = BASELINE_SCHEMA
    schema_version: int = BASELINE_SCHEMA_VERSION
    environments: List[str] = field(default_factory=list)
    baselines: List[BaselineRef] = field(default_factory=list)
    required_profiles: Tuple[str, ...] = REQUIRED_BASELINE_PROFILES
    regression_ratio_limit: float = REGRESSION_RATIO_LIMIT
    notes: str = ""

    def profiles_for(self, environment_label: str) -> List[str]:
        return sorted(
            {
                b.profile
                for b in self.baselines
                if b.environment_label == environment_label
            }
        )

    def find(
        self,
        profile: str,
        environment_label: Optional[str] = None,
    ) -> List[BaselineRef]:
        out = [b for b in self.baselines if b.profile == profile]
        if environment_label is not None:
            out = [b for b in out if b.environment_label == environment_label]
        return out

    def to_json_dict(self) -> JSONDict:
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "required_profiles": list(self.required_profiles),
            "optional_profiles": list(OPTIONAL_BASELINE_PROFILES),
            "regression_ratio_limit": self.regression_ratio_limit,
            "correctness_error_max": CORRECTNESS_ERROR_MAX,
            "security_error_max": SECURITY_ERROR_MAX,
            "environments": list(self.environments),
            "baselines": [b.to_json_dict() for b in self.baselines],
            "notes": self.notes,
        }


def load_catalog(path: Optional[Path | str] = None) -> BaselineCatalog:
    """Load the catalog index (or rebuild from the environments tree)."""
    root = baselines_root()
    cat_file = Path(path) if path is not None else catalog_path()
    if cat_file.is_file():
        data = json.loads(cat_file.read_text(encoding="utf-8"))
        refs: List[BaselineRef] = []
        for entry in data.get("baselines") or []:
            rel = entry["path"]
            refs.append(
                BaselineRef(
                    profile=entry["profile"],
                    environment_label=entry["environment_label"],
                    path=(root / rel).resolve(),
                    status=entry.get("status", "unknown"),
                    baseline_id=entry.get("baseline_id", ""),
                )
            )
        return BaselineCatalog(
            schema=data.get("schema", BASELINE_SCHEMA),
            schema_version=int(data.get("schema_version", BASELINE_SCHEMA_VERSION)),
            environments=list(data.get("environments") or []),
            baselines=refs,
            required_profiles=tuple(
                data.get("required_profiles") or REQUIRED_BASELINE_PROFILES
            ),
            regression_ratio_limit=float(
                data.get("regression_ratio_limit", REGRESSION_RATIO_LIMIT)
            ),
            notes=str(data.get("notes") or ""),
        )
    return scan_environments()


def scan_environments() -> BaselineCatalog:
    """Rebuild a catalog by walking ``environments/*/profiles/*.json``."""
    env_root = environments_root()
    refs: List[BaselineRef] = []
    environments: List[str] = []
    if env_root.is_dir():
        for env_dir in sorted(env_root.iterdir()):
            if not env_dir.is_dir():
                continue
            environments.append(env_dir.name)
            profiles_dir = env_dir / "profiles"
            if not profiles_dir.is_dir():
                continue
            for path in sorted(profiles_dir.glob("*.json")):
                data = json.loads(path.read_text(encoding="utf-8"))
                refs.append(
                    BaselineRef(
                        profile=str(data.get("profile") or path.stem),
                        environment_label=str(
                            data.get("environment_label") or env_dir.name
                        ),
                        path=path.resolve(),
                        status=str(data.get("status") or "unknown"),
                        baseline_id=str(data.get("baseline_id") or ""),
                    )
                )
    return BaselineCatalog(environments=environments, baselines=refs)


def load_baseline(
    profile: str,
    *,
    environment_label: Optional[str] = None,
    catalog: Optional[BaselineCatalog] = None,
    path: Optional[Path | str] = None,
) -> JSONDict:
    """Load a single baseline document for *profile*.

    If *path* is given it is used directly. Otherwise the catalog is
    searched; when multiple environments match and none is requested, the
    first ``ratified`` entry wins, then the first entry overall.
    """
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    cat = catalog or load_catalog()
    matches = cat.find(profile, environment_label=environment_label)
    if not matches:
        known = sorted({b.profile for b in cat.baselines})
        envs = sorted({b.environment_label for b in cat.baselines})
        raise KeyError(
            f"no baseline for profile={profile!r} "
            f"environment_label={environment_label!r}; "
            f"known profiles={known} environments={envs}"
        )
    # Prefer ratified status.
    ratified = [m for m in matches if m.status == "ratified"]
    chosen = (ratified or matches)[0]
    return json.loads(chosen.path.read_text(encoding="utf-8"))


def list_environment_labels(
    catalog: Optional[BaselineCatalog] = None,
) -> Tuple[str, ...]:
    cat = catalog or load_catalog()
    return tuple(sorted(set(cat.environments) | {b.environment_label for b in cat.baselines}))


def write_json_atomic(path: Path | str, data: Mapping[str, Any]) -> Path:
    """Atomically write JSON with stable key order."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True, default=str) + "\n"
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)
    return target
