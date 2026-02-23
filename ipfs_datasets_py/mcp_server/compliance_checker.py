"""Compliance checking utilities for MCP++ tool invocation intents.

Provides a rule-based compliance engine plus persistence helpers. The module
keeps backward compatibility with legacy ComplianceRule APIs while supporting
the newer ComplianceStatus/Violation/Report structures.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "ComplianceStatus",
    "ComplianceViolation",
    "ComplianceResult",
    "ComplianceReport",
    "ComplianceRule",
    "ComplianceMergeResult",
    "ComplianceChecker",
    "make_default_checker",
    "make_default_compliance_checker",
    "_COMPLIANCE_RULE_VERSION",
]


class ComplianceMergeResult(NamedTuple):
    """Result of a ComplianceChecker.merge operation.

    Backward-compatible with int comparisons via __eq__ and __int__ (added).
    """

    added: int
    skipped_protected: int
    skipped_duplicate: int

    def __int__(self) -> int:
        return self.added

    def __eq__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, int):
            return self.added == other
        return tuple.__eq__(self, other)

    def __hash__(self) -> int:  # type: ignore[override]
        return hash(tuple(self))

    @property
    def total(self) -> int:
        return self.added + self.skipped_protected + self.skipped_duplicate

    def __bool__(self) -> bool:
        return self.added > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added": self.added,
            "skipped_protected": self.skipped_protected,
            "skipped_duplicate": self.skipped_duplicate,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ComplianceMergeResult":
        return cls(
            added=int(d.get("added", 0)),
            skipped_protected=int(d.get("skipped_protected", 0)),
            skipped_duplicate=int(d.get("skipped_duplicate", 0)),
        )


class ComplianceStatus(str, Enum):
    """Result status for a single compliance rule check."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    WARNING = "warning"
    SKIPPED = "skipped"


@dataclass
class ComplianceViolation:
    """A single compliance violation detected by a rule."""

    rule_id: str
    message: str
    severity: str = "error"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class ComplianceResult:
    """Result of a single compliance rule applied to one intent."""

    rule_id: str
    status: ComplianceStatus
    violations: List[ComplianceViolation] = field(default_factory=list)
    checked_at: float = field(default_factory=time.time)

    @property
    def is_compliant(self) -> bool:
        return self.status in (ComplianceStatus.COMPLIANT, ComplianceStatus.SKIPPED)

    @property
    def passed(self) -> bool:
        return self.is_compliant

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "status": self.status.value,
            "violations": [v.to_dict() for v in self.violations],
            "checked_at": self.checked_at,
        }


@dataclass
class ComplianceReport:
    """Aggregated compliance results for one intent across all rules."""

    results: List[ComplianceResult] = field(default_factory=list)
    checked_at: float = field(default_factory=time.time)
    intent_snapshot: Dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        for r in self.results:
            if not r.is_compliant:
                return "fail"
        return "pass"

    @property
    def all_violations(self) -> List[ComplianceViolation]:
        violations: List[ComplianceViolation] = []
        for r in self.results:
            violations.extend(r.violations)
        return violations

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failed_rules(self) -> List[str]:
        return [r.rule_id for r in self.results if not r.passed]

    @property
    def passed_rules(self) -> List[str]:
        return [r.rule_id for r in self.results if r.passed]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "results": [r.to_dict() for r in self.results],
            "all_violations": [v.to_dict() for v in self.all_violations],
            "checked_at": self.checked_at,
        }


ComplianceRuleFn = Callable[[Any], ComplianceResult]


@dataclass
class ComplianceRule:
    """A single named compliance predicate."""

    rule_id: str
    description: str
    check_fn: ComplianceRuleFn
    removable: bool = True

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("ComplianceRule.rule_id must be non-empty")

    def check(self, intent: Any) -> ComplianceResult:
        try:
            result = self.check_fn(intent)
            if isinstance(result, ComplianceResult):
                return result
            if isinstance(result, bool):
                status = (
                    ComplianceStatus.COMPLIANT
                    if result
                    else ComplianceStatus.NON_COMPLIANT
                )
                return ComplianceResult(rule_id=self.rule_id, status=status)
            return ComplianceResult(
                rule_id=self.rule_id,
                status=ComplianceStatus.WARNING,
                violations=[
                    ComplianceViolation(
                        rule_id=self.rule_id,
                        message="Rule returned non-standard result",
                        severity="warning",
                    )
                ],
            )
        except Exception as exc:
            logger.warning(
                "ComplianceRule %s raised %s: %s",
                self.rule_id,
                type(exc).__name__,
                exc,
            )
            return ComplianceResult(
                rule_id=self.rule_id,
                status=ComplianceStatus.NON_COMPLIANT,
                violations=[
                    ComplianceViolation(
                        rule_id=self.rule_id,
                        message=f"Rule raised {type(exc).__name__}: {exc}",
                        severity="error",
                    )
                ],
            )


_COMPLIANCE_RULE_VERSION = "1"
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _is_json_serializable(obj: Any, _depth: int = 0) -> bool:
    if _depth > 10:
        return False
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return True
    if isinstance(obj, (list, tuple)):
        return all(_is_json_serializable(v, _depth + 1) for v in obj)
    if isinstance(obj, dict):
        return all(
            isinstance(k, str) and _is_json_serializable(v, _depth + 1)
            for k, v in obj.items()
        )
    return False


class ComplianceChecker:
    """Manages compliance rules and runs them against intents."""

    def __init__(
        self,
        deny_list: Optional[Set[str]] = None,
        rules: Optional[List[ComplianceRule]] = None,
        *,
        fail_fast: bool = False,
    ) -> None:
        self._rules: Dict[str, ComplianceRuleFn] = {}
        self._rule_order: List[str] = []
        self._rule_meta: Dict[str, ComplianceRule] = {}
        self._deny_list: Set[str] = set(deny_list or [])
        self.fail_fast = fail_fast
        for rule in rules or []:
            self.add_rule(rule)

    def add_rule(
        self,
        rule: ComplianceRule | str,
        fn: Optional[ComplianceRuleFn] = None,
        *,
        description: str = "",
        removable: bool = True,
    ) -> None:
        if isinstance(rule, ComplianceRule):
            rule_id = rule.rule_id
            self._rule_meta[rule_id] = rule
            fn = rule.check
        else:
            rule_id = rule
            if fn is None:
                raise ValueError("add_rule requires a function when rule_id is provided")
            self._rule_meta[rule_id] = ComplianceRule(
                rule_id=rule_id,
                description=description,
                check_fn=fn,
                removable=removable,
            )
        if rule_id in self._rules:
            raise ValueError(f"Rule with rule_id={rule_id!r} already registered")
        self._rules[rule_id] = fn
        self._rule_order.append(rule_id)

    def remove_rule(self, rule_id: str) -> bool:
        meta = self._rule_meta.get(rule_id)
        if meta is not None and not meta.removable:
            raise ValueError(f"Rule {rule_id!r} is not removable")
        if rule_id in self._rules:
            del self._rules[rule_id]
            self._rule_order = [r for r in self._rule_order if r != rule_id]
            self._rule_meta.pop(rule_id, None)
            return True
        return False

    def list_rules(self) -> List[str]:
        return list(self._rule_order)

    def list_rule_details(self) -> List[Dict[str, Any]]:
        return [
            {
                "rule_id": rule_id,
                "description": self._rule_meta.get(rule_id, ComplianceRule(rule_id, "", lambda _: ComplianceResult(rule_id, ComplianceStatus.COMPLIANT))).description,
                "removable": self._rule_meta.get(rule_id, ComplianceRule(rule_id, "", lambda _: ComplianceResult(rule_id, ComplianceStatus.COMPLIANT))).removable,
            }
            for rule_id in self._rule_order
        ]

    def get_rule(self, rule_id: str) -> Optional[ComplianceRule]:
        return self._rule_meta.get(rule_id)

    def __len__(self) -> int:
        return len(self._rule_order)

    def check(self, intent: Any) -> ComplianceReport:
        results: List[ComplianceResult] = []
        snapshot: Dict[str, Any] = {}
        if isinstance(intent, dict):
            snapshot = {k: v for k, v in intent.items() if k != "params"}
        for rule_id in self._rule_order:
            fn = self._rules.get(rule_id)
            if fn is None:
                continue
            try:
                result = fn(intent)
                if not isinstance(result, ComplianceResult):
                    result = ComplianceResult(
                        rule_id=rule_id,
                        status=ComplianceStatus.WARNING,
                        violations=[
                            ComplianceViolation(
                                rule_id=rule_id,
                                message="Rule returned non-standard result",
                                severity="warning",
                            )
                        ],
                    )
            except Exception as exc:
                result = ComplianceResult(
                    rule_id=rule_id,
                    status=ComplianceStatus.SKIPPED,
                    violations=[
                        ComplianceViolation(
                            rule_id=rule_id,
                            message=f"Rule raised an exception: {exc}",
                            severity="error",
                        )
                    ],
                )
            results.append(result)
            if self.fail_fast and not result.passed:
                break
        return ComplianceReport(results=results, intent_snapshot=snapshot)

    def check_compliance(self, intent: Any) -> ComplianceReport:
        return self.check(intent)

    def merge(
        self,
        other: "ComplianceChecker",
        *,
        include_protected_rules: bool = False,
        copy_deny_list: bool = True,
    ) -> ComplianceMergeResult:
        existing_ids = set(self._rule_order)
        added = 0
        skipped_protected = 0
        skipped_duplicate = 0
        for rule_id in other._rule_order:
            meta = other._rule_meta.get(rule_id)
            if meta is not None and not meta.removable and not include_protected_rules:
                skipped_protected += 1
                continue
            if rule_id in existing_ids:
                skipped_duplicate += 1
                continue
            fn = other._rules.get(rule_id)
            if fn is None:
                continue
            meta_copy = copy.copy(meta) if meta is not None else None
            if meta_copy is not None:
                self._rule_meta[rule_id] = meta_copy
            self._rules[rule_id] = fn
            self._rule_order.append(rule_id)
            existing_ids.add(rule_id)
            added += 1
        if copy_deny_list:
            self._deny_list.update(other._deny_list)
        return ComplianceMergeResult(
            added=added,
            skipped_protected=skipped_protected,
            skipped_duplicate=skipped_duplicate,
        )

    def diff(self, other: "ComplianceChecker") -> Dict[str, Any]:
        self_ids = {r: self._rule_meta.get(r) for r in self._rule_order}
        other_ids = {r: other._rule_meta.get(r) for r in other._rule_order}
        added = sorted(set(other_ids) - set(self_ids))
        removed = sorted(set(self_ids) - set(other_ids))
        common = sorted(set(self_ids) & set(other_ids))
        changed = [
            rid for rid in common
            if (
                (self_ids[rid] and other_ids[rid])
                and (
                    self_ids[rid].description != other_ids[rid].description
                    or self_ids[rid].removable != other_ids[rid].removable
                )
            )
        ]
        return {
            "added_rules": added,
            "removed_rules": removed,
            "common_rules": common,
            "changed_rules": changed,
        }

    def save(self, path: str) -> None:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        data: Dict[str, Any] = {
            "version": _COMPLIANCE_RULE_VERSION,
            "rule_order": list(self._rule_order),
            "deny_list": sorted(self._deny_list),
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        logger.debug("Saved %d compliance rules to %s", len(self._rule_order), path)

    def load(self, path: str) -> int:
        if not os.path.exists(path):
            logger.debug("Compliance rule file not found: %s", path)
            return 0
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning("Could not load compliance rules from %s: %s", path, exc)
            return 0

        file_version = data.get("version", "")
        if file_version and file_version != _COMPLIANCE_RULE_VERSION:
            import warnings

            warnings.warn(
                f"Compliance rule file {path!r} was saved with version "
                f"{file_version!r} but current version is "
                f"{_COMPLIANCE_RULE_VERSION!r}. Rule migration may be needed.",
                UserWarning,
                stacklevel=2,
            )

        deny_list = data.get("deny_list", [])
        if isinstance(deny_list, list):
            self._deny_list = set(str(d) for d in deny_list)

        builtin_map: Dict[str, ComplianceRuleFn] = {
            "tool_name_convention": self._rule_tool_name_convention,
            "intent_has_actor": self._rule_intent_has_actor,
            "actor_is_valid": self._rule_actor_is_valid,
            "params_are_serializable": self._rule_params_are_serializable,
            "tool_not_in_deny_list": self._rule_tool_not_in_deny_list,
            "rate_limit_ok": self._rule_rate_limit_ok,
        }

        rule_order = data.get("rule_order", [])
        loaded = 0
        for rule_id in rule_order:
            if not isinstance(rule_id, str) or not rule_id:
                continue
            fn = builtin_map.get(rule_id)
            if fn is None:
                _captured_id = rule_id

                def _stub(_intent: Any, _rule_id: str = _captured_id) -> ComplianceResult:
                    return ComplianceResult(
                        rule_id=_rule_id,
                        status=ComplianceStatus.COMPLIANT,
                    )

                fn = _stub
            if rule_id not in self._rules:
                self._rule_order.append(rule_id)
            self._rules[rule_id] = fn
            if rule_id not in self._rule_meta:
                self._rule_meta[rule_id] = ComplianceRule(
                    rule_id=rule_id,
                    description="",
                    check_fn=fn,
                    removable=True,
                )
            loaded += 1

        logger.debug("Loaded %d compliance rules from %s", loaded, path)
        return loaded

    def reload(self, path: str) -> int:
        self._rules.clear()
        self._rule_order.clear()
        self._rule_meta.clear()
        self._deny_list.clear()
        return self.load(path)

    def save_encrypted(self, path: str, password: str) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            import hashlib
        except ImportError:
            import warnings

            warnings.warn(
                "cryptography package not installed; falling back to plain save()",
                UserWarning,
                stacklevel=2,
            )
            self.save(path)
            return

        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        pw_bytes = password.encode() if isinstance(password, str) else password
        kdf_salt = b"ipfs_datasets_py.mcp_server.compliance_checker.save_encrypted"
        key = hashlib.pbkdf2_hmac("sha256", pw_bytes, kdf_salt, 100_000, dklen=32)
        nonce = os.urandom(12)
        data: Dict[str, Any] = {
            "version": _COMPLIANCE_RULE_VERSION,
            "rule_order": list(self._rule_order),
            "deny_list": sorted(self._deny_list),
        }
        plaintext = json.dumps(data).encode()
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
        with open(path, "wb") as fh:
            fh.write(nonce + ciphertext)
        logger.debug(
            "Saved %d compliance rules (encrypted) to %s",
            len(self._rule_order),
            path,
        )

    def load_encrypted(self, path: str, password: str) -> int:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.exceptions import InvalidTag
            import hashlib
        except ImportError:
            import warnings

            warnings.warn(
                "cryptography package not installed; falling back to plain load()",
                UserWarning,
                stacklevel=2,
            )
            return self.load(path)

        if not os.path.exists(path):
            logger.debug("Encrypted compliance rule file not found: %s", path)
            return 0

        min_size = 13
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            if len(raw) < min_size:
                logger.warning("Encrypted compliance file too short: %s", path)
                return 0
            nonce, ciphertext = raw[:12], raw[12:]
            pw_bytes = password.encode() if isinstance(password, str) else password
            kdf_salt = b"ipfs_datasets_py.mcp_server.compliance_checker.save_encrypted"
            key = hashlib.pbkdf2_hmac("sha256", pw_bytes, kdf_salt, 100_000, dklen=32)
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
            data = json.loads(plaintext.decode())
        except (InvalidTag, Exception) as exc:
            logger.warning("Could not decrypt compliance rules from %s: %s", path, exc)
            return 0

        file_version = data.get("version", "")
        if file_version and file_version != _COMPLIANCE_RULE_VERSION:
            import warnings

            warnings.warn(
                f"Encrypted compliance rule file was saved with version "
                f"{file_version!r} but current version is "
                f"{_COMPLIANCE_RULE_VERSION!r}. Proceeding with caution.",
                UserWarning,
                stacklevel=2,
            )

        return self._load_from_data(data)

    def _load_from_data(self, data: Dict[str, Any]) -> int:
        deny_list = data.get("deny_list", [])
        if isinstance(deny_list, list):
            self._deny_list = set(str(d) for d in deny_list)

        builtin_map: Dict[str, ComplianceRuleFn] = {
            "tool_name_convention": self._rule_tool_name_convention,
            "intent_has_actor": self._rule_intent_has_actor,
            "actor_is_valid": self._rule_actor_is_valid,
            "params_are_serializable": self._rule_params_are_serializable,
            "tool_not_in_deny_list": self._rule_tool_not_in_deny_list,
            "rate_limit_ok": self._rule_rate_limit_ok,
        }

        rule_order = data.get("rule_order", [])
        loaded = 0
        for rule_id in rule_order:
            if not isinstance(rule_id, str) or not rule_id:
                continue
            fn = builtin_map.get(rule_id)
            if fn is None:
                _captured_id = rule_id

                def _stub(_intent: Any, _rule_id: str = _captured_id) -> ComplianceResult:
                    return ComplianceResult(
                        rule_id=_rule_id,
                        status=ComplianceStatus.COMPLIANT,
                    )

                fn = _stub
            if rule_id not in self._rules:
                self._rule_order.append(rule_id)
            self._rules[rule_id] = fn
            if rule_id not in self._rule_meta:
                self._rule_meta[rule_id] = ComplianceRule(
                    rule_id=rule_id,
                    description="",
                    check_fn=fn,
                    removable=True,
                )
            loaded += 1
        return loaded

    def migrate_encrypted(self, path: str, old_password: str, new_password: str) -> bool:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.exceptions import InvalidTag
            import hashlib
        except ImportError:
            import warnings

            warnings.warn(
                "cryptography package not installed; migrate_encrypted() cannot proceed",
                UserWarning,
                stacklevel=2,
            )
            return False

        if not os.path.exists(path):
            logger.debug("migrate_encrypted: file not found: %s", path)
            return False

        min_size = 13
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            if len(raw) < min_size:
                logger.warning("migrate_encrypted: file too short: %s", path)
                return False
            nonce, ciphertext = raw[:12], raw[12:]
            old_pw = old_password.encode() if isinstance(old_password, str) else old_password
            kdf_salt = b"ipfs_datasets_py.mcp_server.compliance_checker.save_encrypted"
            old_key = hashlib.pbkdf2_hmac("sha256", old_pw, kdf_salt, 100_000, dklen=32)
            plaintext = AESGCM(old_key).decrypt(nonce, ciphertext, None)
            data = json.loads(plaintext.decode())
        except InvalidTag:
            logger.warning("migrate_encrypted: wrong old password for %s", path)
            return False
        except Exception as exc:
            logger.warning("migrate_encrypted: failed to decrypt %s: %s", path, exc)
            return False

        data["version"] = _COMPLIANCE_RULE_VERSION
        new_pw = new_password.encode() if isinstance(new_password, str) else new_password
        new_key = hashlib.pbkdf2_hmac("sha256", new_pw, kdf_salt, 100_000, dklen=32)
        new_nonce = os.urandom(12)
        new_ciphertext = AESGCM(new_key).encrypt(new_nonce, json.dumps(data).encode(), None)

        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        bak_path = path + ".bak"
        try:
            shutil.copy2(path, bak_path)
            logger.debug("migrate_encrypted: backup written to %s", bak_path)
        except Exception as exc:
            logger.warning("migrate_encrypted: failed to create backup %s: %s", bak_path, exc)
            bak_path = None

        try:
            with open(path, "wb") as fh:
                fh.write(new_nonce + new_ciphertext)
        except Exception as exc:
            logger.warning("migrate_encrypted: failed to write %s: %s", path, exc)
            return False

        if bak_path is not None:
            try:
                os.unlink(bak_path)
                logger.debug("migrate_encrypted: backup removed %s", bak_path)
            except OSError as exc:
                logger.debug("migrate_encrypted: could not remove backup %s: %s", bak_path, exc)

        logger.debug("migrate_encrypted: re-encrypted %s with new password", path)
        return True

    def restore_from_bak(self, path: str) -> bool:
        bak_path = path + ".bak"
        if not os.path.exists(bak_path):
            logger.debug("restore_from_bak: no backup found at %s", bak_path)
            return False
        try:
            shutil.copy2(bak_path, path)
            os.unlink(bak_path)
            logger.debug("restore_from_bak: restored %s from %s", path, bak_path)
            return True
        except Exception as exc:
            logger.warning("restore_from_bak: failed to restore %s: %s", path, exc)
            return False

    @staticmethod
    def bak_exists(path: str) -> bool:
        return os.path.exists(path + ".bak")

    @staticmethod
    def bak_path(path: str) -> str:
        return path + ".bak"

    @staticmethod
    def rotate_bak(path: str, *, max_keep: int = 3) -> None:
        bak = path + ".bak"
        if not os.path.exists(bak):
            return
        for i in range(max_keep, 0, -1):
            src = bak if i == 1 else f"{bak}.{i - 1}"
            dst = f"{bak}.{i}"
            if i == max_keep:
                try:
                    if os.path.exists(dst):
                        os.unlink(dst)
                except OSError:
                    pass
            if os.path.exists(src):
                try:
                    os.rename(src, dst)
                except OSError:
                    pass

    @staticmethod
    def list_bak_files(path: str) -> List[str]:
        bak = path + ".bak"
        found: List[str] = []
        if os.path.exists(bak):
            found.append(bak)
        i = 1
        while True:
            numbered = f"{bak}.{i}"
            if os.path.exists(numbered):
                found.append(numbered)
                i += 1
            else:
                break
        return found

    @staticmethod
    def purge_bak_files(path: str) -> int:
        removed = 0
        for bak_file in ComplianceChecker.list_bak_files(path):
            try:
                os.unlink(bak_file)
                removed += 1
            except OSError:
                pass
        return removed

    @staticmethod
    def backup_and_save(path: str, content: str, *, max_keep: int = 3) -> bool:
        ComplianceChecker.rotate_bak(path, max_keep=max_keep)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            return True
        except OSError:
            return False

    @staticmethod
    def backup_exists_any(path: str) -> bool:
        return bool(ComplianceChecker.list_bak_files(path))

    @staticmethod
    def backup_count(path: str) -> int:
        return len(ComplianceChecker.list_bak_files(path))

    @staticmethod
    def backup_age(path: str) -> Optional[float]:
        files = ComplianceChecker.list_bak_files(path)
        if not files:
            return None
        try:
            return float(os.path.getmtime(files[0]))
        except OSError:
            return None

    @staticmethod
    def oldest_backup_age(path: str) -> Optional[float]:
        files = ComplianceChecker.list_bak_files(path)
        if not files:
            return None
        try:
            return float(os.path.getmtime(files[-1]))
        except OSError:
            return None

    @staticmethod
    def newest_backup_path(path: str) -> Optional[str]:
        files = ComplianceChecker.list_bak_files(path)
        return files[0] if files else None

    @staticmethod
    def oldest_backup_path(path: str) -> Optional[str]:
        files = ComplianceChecker.list_bak_files(path)
        return files[-1] if files else None

    @staticmethod
    def _get_field(intent: Any, field: str, default: Any = None) -> Any:
        if isinstance(intent, dict):
            return intent.get(field, default)
        return getattr(intent, field, default)

    def _rule_tool_name_convention(self, intent: Any) -> ComplianceResult:
        rule_id = "tool_name_convention"
        tool_name = self._get_field(intent, "tool_name", "") or self._get_field(intent, "tool", "") or ""
        violations: List[ComplianceViolation] = []
        if not tool_name:
            violations.append(
                ComplianceViolation(
                    rule_id=rule_id,
                    message="tool_name is empty or missing",
                    severity="error",
                )
            )
        elif not _TOOL_NAME_RE.match(tool_name):
            violations.append(
                ComplianceViolation(
                    rule_id=rule_id,
                    message=(
                        f"tool_name '{tool_name}' violates naming convention "
                        "(must match ^[a-z][a-z0-9_]*$)"
                    ),
                    severity="error",
                )
            )
        status = ComplianceStatus.COMPLIANT if not violations else ComplianceStatus.NON_COMPLIANT
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_intent_has_actor(self, intent: Any) -> ComplianceResult:
        rule_id = "intent_has_actor"
        actor = self._get_field(intent, "actor", "") or ""
        violations: List[ComplianceViolation] = []
        if not str(actor).strip():
            violations.append(
                ComplianceViolation(
                    rule_id=rule_id,
                    message="intent is missing a non-empty 'actor' field",
                    severity="warning",
                )
            )
        status = ComplianceStatus.COMPLIANT if not violations else ComplianceStatus.WARNING
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_actor_is_valid(self, intent: Any) -> ComplianceResult:
        rule_id = "actor_is_valid"
        actor = self._get_field(intent, "actor", "") or ""
        violations: List[ComplianceViolation] = []
        if actor and re.search(r"\s", str(actor)):
            violations.append(
                ComplianceViolation(
                    rule_id=rule_id,
                    message=f"actor '{actor}' contains whitespace",
                    severity="error",
                )
            )
        status = ComplianceStatus.COMPLIANT if not violations else ComplianceStatus.NON_COMPLIANT
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_params_are_serializable(self, intent: Any) -> ComplianceResult:
        rule_id = "params_are_serializable"
        params = self._get_field(intent, "params", {}) or {}
        violations: List[ComplianceViolation] = []
        if not _is_json_serializable(params):
            violations.append(
                ComplianceViolation(
                    rule_id=rule_id,
                    message="intent params contain non-JSON-serializable values",
                    severity="warning",
                )
            )
        status = ComplianceStatus.COMPLIANT if not violations else ComplianceStatus.WARNING
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_tool_not_in_deny_list(self, intent: Any) -> ComplianceResult:
        rule_id = "tool_not_in_deny_list"
        tool_name = self._get_field(intent, "tool_name", "") or self._get_field(intent, "tool", "") or ""
        violations: List[ComplianceViolation] = []
        if tool_name in self._deny_list:
            violations.append(
                ComplianceViolation(
                    rule_id=rule_id,
                    message=f"tool '{tool_name}' is in the deny list",
                    severity="error",
                )
            )
        status = ComplianceStatus.COMPLIANT if not violations else ComplianceStatus.NON_COMPLIANT
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_rate_limit_ok(self, intent: Any) -> ComplianceResult:
        rule_id = "rate_limit_ok"
        return ComplianceResult(rule_id=rule_id, status=ComplianceStatus.COMPLIANT)

    def __repr__(self) -> str:
        return f"ComplianceChecker(rules={len(self._rule_order)}, fail_fast={self.fail_fast})"


def make_default_compliance_checker(
    deny_list: Optional[Set[str]] = None,
) -> ComplianceChecker:
    checker = ComplianceChecker(deny_list=deny_list)
    checker.add_rule("tool_name_convention", checker._rule_tool_name_convention)
    checker.add_rule("intent_has_actor", checker._rule_intent_has_actor)
    checker.add_rule("actor_is_valid", checker._rule_actor_is_valid)
    checker.add_rule("params_are_serializable", checker._rule_params_are_serializable)
    checker.add_rule("tool_not_in_deny_list", checker._rule_tool_not_in_deny_list)
    checker.add_rule("rate_limit_ok", checker._rule_rate_limit_ok)
    return checker


def make_default_checker(*, fail_fast: bool = False) -> ComplianceChecker:
    checker = make_default_compliance_checker()
    checker.fail_fast = fail_fast
    return checker
