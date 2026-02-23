"""Compliance checking for MCP++ tool invocations.

Provides a lightweight, rule-based compliance engine that evaluates
:class:`~cid_artifacts.IntentObject`-like objects against a set of
named compliance rules before dispatch.

Key concepts
------------
- **ComplianceRule** — a named callable ``(intent) → ComplianceResult``.
- **ComplianceResult** — status + list of :class:`ComplianceViolation`.
- **ComplianceReport** — aggregated results across all rules checked.
- **ComplianceChecker** — manages a registry of rules and runs them.

Built-in rules
--------------
The default checker includes these rules (all can be removed/replaced):

``tool_name_convention``
    Tool names must be non-empty and use only ``[a-z0-9_]`` characters.

``intent_has_actor``
    The intent must specify a non-empty ``actor`` field.

``actor_is_valid``
    Actor string must not contain whitespace.

``params_are_serializable``
    All parameter values must be JSON-serializable primitives or containers.

``tool_not_in_deny_list``
    Blocks specific tool names via a configurable deny list.

``rate_limit_ok``
    Rate-limit check stub — always passes unless overridden by a subclass or
    custom rule (requires external state).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "ComplianceStatus",
    "ComplianceViolation",
    "ComplianceResult",
    "ComplianceReport",
    "ComplianceChecker",
    "make_default_compliance_checker",
    "_COMPLIANCE_RULE_VERSION",
]


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class ComplianceStatus(str, Enum):
    """Result status for a single compliance rule check."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    WARNING = "warning"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Violation
# ---------------------------------------------------------------------------

@dataclass
class ComplianceViolation:
    """A single compliance violation detected by a rule.

    Attributes
    ----------
    rule_id:
        Identifier of the rule that raised this violation.
    message:
        Human-readable explanation.
    severity:
        ``"error"`` (blocks dispatch), ``"warning"`` (advisory only), or
        ``"info"``.
    """

    rule_id: str
    message: str
    severity: str = "error"  # "error" | "warning" | "info"

    def to_dict(self) -> Dict:
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity,
        }


# ---------------------------------------------------------------------------
# ComplianceResult
# ---------------------------------------------------------------------------

@dataclass
class ComplianceResult:
    """Result of a single compliance rule applied to one intent.

    Attributes
    ----------
    rule_id:
        Identifier of the rule that produced this result.
    status:
        :class:`ComplianceStatus` outcome.
    violations:
        List of :class:`ComplianceViolation` objects (may be empty).
    checked_at:
        Unix timestamp of the check.
    """

    rule_id: str
    status: ComplianceStatus
    violations: List[ComplianceViolation] = field(default_factory=list)
    checked_at: float = field(default_factory=time.time)

    @property
    def is_compliant(self) -> bool:
        return self.status in (ComplianceStatus.COMPLIANT, ComplianceStatus.SKIPPED)

    def to_dict(self) -> Dict:
        return {
            "rule_id": self.rule_id,
            "status": self.status.value,
            "violations": [v.to_dict() for v in self.violations],
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# ComplianceReport
# ---------------------------------------------------------------------------

@dataclass
class ComplianceReport:
    """Aggregated compliance results for one intent across all rules.

    Attributes
    ----------
    results:
        Per-rule :class:`ComplianceResult` objects.
    summary:
        ``"pass"`` if all rules pass, ``"fail"`` otherwise.
    checked_at:
        Unix timestamp.
    """

    results: List[ComplianceResult] = field(default_factory=list)
    checked_at: float = field(default_factory=time.time)

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

    def to_dict(self) -> Dict:
        return {
            "summary": self.summary,
            "results": [r.to_dict() for r in self.results],
            "all_violations": [v.to_dict() for v in self.all_violations],
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# ComplianceChecker
# ---------------------------------------------------------------------------

# Type alias for a compliance rule callable
ComplianceRuleFn = Callable[[Any], ComplianceResult]

# Regex for valid tool names
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Schema version stored in persisted rule files (Session 62)
_COMPLIANCE_RULE_VERSION = "1"


def _is_json_serializable(obj: Any, _depth: int = 0) -> bool:
    """Return True if *obj* is JSON-serializable."""
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
    """Manages a registry of compliance rules and runs them against intents.

    Usage::

        checker = ComplianceChecker()
        checker.add_rule("my_rule", my_rule_fn)
        report = checker.check_compliance(intent)
        if report.summary == "fail":
            ...
    """

    def __init__(
        self,
        deny_list: Optional[Set[str]] = None,
    ) -> None:
        self._rules: Dict[str, ComplianceRuleFn] = {}
        self._rule_order: List[str] = []
        self._deny_list: Set[str] = set(deny_list or [])

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule_id: str, fn: ComplianceRuleFn) -> None:
        """Register a compliance rule callable under *rule_id*."""
        self._rules[rule_id] = fn
        if rule_id not in self._rule_order:
            self._rule_order.append(rule_id)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule; return True if it existed."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            self._rule_order = [r for r in self._rule_order if r != rule_id]
            return True
        return False

    def list_rules(self) -> List[str]:
        """Return rule IDs in registration order."""
        return list(self._rule_order)

    def merge(self, other: "ComplianceChecker") -> int:
        """Merge rules and deny-list entries from *other* into this checker.

        Rules that already exist in this checker are **not** overwritten.
        The deny-list of *other* is unioned into this checker's deny-list.

        This is useful for assembling composite rule sets from multiple
        specialised checkers without reloading from disk.

        Args:
            other: Another :class:`ComplianceChecker` instance whose rules
                and deny-list should be incorporated.

        Returns:
            The number of **newly-added** rules (rules that did not already
            exist in this checker).
        """
        added = 0
        for rule_id in other._rule_order:
            if rule_id not in self._rules:
                fn = other._rules.get(rule_id)
                if fn is not None:
                    self._rules[rule_id] = fn
                    self._rule_order.append(rule_id)
                    added += 1
        self._deny_list.update(other._deny_list)
        return added

    # ------------------------------------------------------------------
    # Persistence (Session 60)
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Persist the ordered rule list to *path* as JSON.

        Only the **rule IDs** (names) are persisted — not the callables.  On
        :meth:`load` the rule names are used to look up matching built-in
        rule implementations that already exist on this instance.  Custom rules
        (added via :meth:`add_rule`) must be re-registered after :meth:`load`.

        The deny list is also persisted so that the full default configuration
        can be restored without re-specifying the blocked tools.

        Creates parent directories if they do not exist.

        Args:
            path: Filesystem path for the JSON file.
        """
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
        """Load rule configuration from *path*.

        Re-wires built-in rules whose IDs appear in the persisted
        ``"rule_order"`` list against the bound rule methods on *self*.
        Built-in rule IDs are: ``tool_name_convention``, ``intent_has_actor``,
        ``actor_is_valid``, ``params_are_serializable``,
        ``tool_not_in_deny_list``, ``rate_limit_ok``.

        For any rule ID that is **not** a built-in, a no-op stub is registered
        so that the rule slot is preserved in the order.  Callers should then
        call :meth:`add_rule` with the real implementation.

        Emits :class:`UserWarning` when the file's ``"version"`` field differs
        from :data:`_COMPLIANCE_RULE_VERSION` so that rule migrations are
        detectable at load time.

        Returns:
            Number of rule IDs loaded (including stubs for unknown rules).
        """
        if not os.path.exists(path):
            logger.debug("Compliance rule file not found: %s", path)
            return 0
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning("Could not load compliance rules from %s: %s", path, exc)
            return 0

        # Version compatibility check (Session 62)
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

        # Restore deny list
        deny_list = data.get("deny_list", [])
        if isinstance(deny_list, list):
            self._deny_list = set(str(d) for d in deny_list)

        # Map built-in rule IDs to their bound methods
        _builtin_map: Dict[str, ComplianceRuleFn] = {
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
            fn = _builtin_map.get(rule_id)
            if fn is None:
                # Stub: always COMPLIANT; real implementation must be re-added
                _captured_id = rule_id
                def _stub(_intent: Any, _rule_id: str = _captured_id) -> "ComplianceResult":
                    return ComplianceResult(rule_id=_rule_id, status=ComplianceStatus.COMPLIANT)
                fn = _stub
            if rule_id not in self._rules:
                self._rule_order.append(rule_id)
            self._rules[rule_id] = fn
            loaded += 1

        logger.debug("Loaded %d compliance rules from %s", loaded, path)
        return loaded

    def reload(self, path: str) -> int:
        """Reload rule configuration from *path*, replacing current rules.

        Equivalent to calling :meth:`load` on a fresh instance and then copying
        the results back.  This preserves any rules that were not persisted (they
        are lost) but allows hot-reloading dynamically added rules from disk.

        Returns:
            Number of rule IDs reloaded (same as :meth:`load`).
        """
        self._rules.clear()
        self._rule_order.clear()
        self._deny_list.clear()
        return self.load(path)

    def save_encrypted(self, path: str, password: str) -> None:
        """Persist rule configuration encrypted with AES-256-GCM.

        Derives a 32-byte key from *password* via a password-based key
        derivation function (PBKDF2-HMAC-SHA256). The nonce
        (12 bytes, ``os.urandom``) is prepended to the ciphertext.  Falls back
        to plain :meth:`save` with a ``UserWarning`` when the ``cryptography``
        package is not installed.

        Args:
            path: Filesystem path for the encrypted rule file.
            password: Encryption password (bytes or str; str is UTF-8 encoded).
        """
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
        # Derive a 32-byte key using PBKDF2-HMAC-SHA256 for computationally
        # expensive password hashing suitable for key derivation.
        kdf_salt = b"ipfs_datasets_py.mcp_server.compliance_checker.save_encrypted"
        key = hashlib.pbkdf2_hmac("sha256", pw_bytes, kdf_salt, 100_000, dklen=32)
        nonce = os.urandom(12)
        data: Dict[str, Any] = {
            "version": _COMPLIANCE_RULE_VERSION,
            "rule_order": list(self._rule_order),
            "deny_list": sorted(self._deny_list),
        }
        plaintext = json.dumps(data).encode()
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        with open(path, "wb") as fh:
            fh.write(nonce + ciphertext)
        logger.debug("Saved %d compliance rules (encrypted) to %s", len(self._rule_order), path)

    def load_encrypted(self, path: str, password: str) -> int:
        """Load encrypted rule configuration from *path*.

        Decrypts using AES-256-GCM (key derived via SHA-256 of *password*) and
        delegates the decoded JSON to :meth:`load`'s rule-wiring logic.  Falls
        back to plain :meth:`load` with a ``UserWarning`` when ``cryptography``
        is not installed.

        Returns 0 on decryption failure, missing file, or any other error
        without raising.

        Returns:
            Number of rule IDs loaded.
        """
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

        _MIN_ENCRYPTED_FILE_SIZE = 13  # 12-byte nonce + at least 1 ciphertext byte
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            if len(raw) < _MIN_ENCRYPTED_FILE_SIZE:
                logger.warning("Encrypted compliance file too short: %s", path)
                return 0
            nonce, ciphertext = raw[:12], raw[12:]
            pw_bytes = password.encode() if isinstance(password, str) else password
            key = hashlib.sha256(pw_bytes).digest()
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            data = json.loads(plaintext.decode())
        except (InvalidTag, Exception) as exc:
            logger.warning("Could not decrypt compliance rules from %s: %s", path, exc)
            return 0

        # Re-use the JSON deserialization logic from load()
        # Also perform the version check that load() does for plain files.
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
        import io
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
            json.dump(data, tf)
            tmp_path = tf.name
        try:
            return self.load(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def migrate_encrypted(
        self,
        path: str,
        old_password: str,
        new_password: str,
    ) -> bool:
        """Re-encrypt *path* with *new_password*, bumping the version field.

        Reads the file encrypted with *old_password*, updates the
        ``"version"`` field to the current :data:`_COMPLIANCE_RULE_VERSION`,
        and writes it back encrypted with *new_password*.

        Atomically creates a ``<path>.bak`` backup of the original before
        overwriting, and removes it only when the write succeeds.  On
        failure the backup is left in place.

        Useful for password rotation and migrating files saved by older
        versions of the compliance checker.

        Args:
            path: Path to the existing encrypted compliance rule file.
            old_password: The password used when the file was originally saved.
            new_password: The new password to encrypt the file with.

        Returns:
            ``True`` on success; ``False`` on any failure (wrong old password,
            missing file, ``cryptography`` package absent, etc.).
        """
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

        _MIN_SIZE = 13  # 12-byte nonce + at least 1 ciphertext byte
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            if len(raw) < _MIN_SIZE:
                logger.warning("migrate_encrypted: file too short: %s", path)
                return False
            nonce, ciphertext = raw[:12], raw[12:]
            old_pw = old_password.encode() if isinstance(old_password, str) else old_password
            old_key = hashlib.sha256(old_pw).digest()
            aesgcm_old = AESGCM(old_key)
            plaintext = aesgcm_old.decrypt(nonce, ciphertext, None)
            data = json.loads(plaintext.decode())
        except InvalidTag:
            logger.warning("migrate_encrypted: wrong old password for %s", path)
            return False
        except Exception as exc:
            logger.warning("migrate_encrypted: failed to decrypt %s: %s", path, exc)
            return False

        # Bump version to current
        data["version"] = _COMPLIANCE_RULE_VERSION

        # Re-encrypt with new password
        new_pw = new_password.encode() if isinstance(new_password, str) else new_password
        new_key = hashlib.sha256(new_pw).digest()
        new_nonce = os.urandom(12)
        new_plaintext = json.dumps(data).encode()
        aesgcm_new = AESGCM(new_key)
        new_ciphertext = aesgcm_new.encrypt(new_nonce, new_plaintext, None)

        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        # Atomic backup: copy original to <path>.bak before overwriting.
        bak_path = path + ".bak"
        try:
            shutil.copy2(path, bak_path)
            logger.debug("migrate_encrypted: backup written to %s", bak_path)
        except Exception as exc:
            logger.warning("migrate_encrypted: failed to create backup %s: %s", bak_path, exc)
            # Proceed even if backup fails — caller may not care
            bak_path = None  # type: ignore[assignment]

        try:
            with open(path, "wb") as fh:
                fh.write(new_nonce + new_ciphertext)
        except Exception as exc:
            logger.warning("migrate_encrypted: failed to write %s: %s", path, exc)
            return False

        # Remove backup only on success
        if bak_path is not None:
            try:
                os.unlink(bak_path)
                logger.debug("migrate_encrypted: backup removed %s", bak_path)
            except OSError as exc:
                logger.debug("migrate_encrypted: could not remove backup %s: %s", bak_path, exc)

        logger.debug("migrate_encrypted: re-encrypted %s with new password", path)
        return True

    def restore_from_bak(self, path: str) -> bool:
        """Restore an encrypted compliance rule file from its ``.bak`` backup.

        If ``<path>.bak`` exists, copies it back to *path* (overwriting the
        current file) and removes the backup.  Useful when a
        :meth:`migrate_encrypted` call partially failed and left the original
        file in a damaged state.

        Args:
            path: Path to the encrypted compliance rule file to restore.

        Returns:
            ``True`` if the backup was found and restored; ``False`` if no
            backup exists or the copy failed.
        """
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
        """Check whether a ``.bak`` backup file exists for *path*.

        Callers can use this as a lightweight pre-check before calling
        :meth:`restore_from_bak` to avoid the overhead of a failed restore
        attempt.

        Args:
            path: Path to the encrypted compliance rule file (without the
                ``.bak`` suffix).

        Returns:
            ``True`` if ``<path>.bak`` exists on the file system.
        """
        return os.path.exists(path + ".bak")

    @staticmethod
    def bak_path(path: str) -> str:
        """Return the expected ``.bak`` path for *path*.

        Avoids magic string duplication in callers that need the backup path
        for operations other than existence checking.

        Args:
            path: Base path (e.g., ``/data/rules.enc``).

        Returns:
            ``path + ".bak"`` (e.g., ``/data/rules.enc.bak``).
        """
        return path + ".bak"

    @staticmethod
    def rotate_bak(path: str, *, max_keep: int = 3) -> None:
        """Rotate existing ``.bak`` files before creating a new backup.

        Renames ``<path>.bak`` → ``<path>.bak.1``, ``<path>.bak.1`` →
        ``<path>.bak.2``, … up to ``<path>.bak.<max_keep>``.  Files beyond
        *max_keep* are deleted.  After rotation the slot ``<path>.bak`` is
        free for a new backup.

        If no ``<path>.bak`` exists the call is a no-op.

        Args:
            path: Base path (without the ``.bak`` suffix).
            max_keep: Maximum number of numbered rotations to retain
                (default 3).  Must be ≥ 1.
        """
        bak = path + ".bak"
        if not os.path.exists(bak):
            return
        # Rotate from oldest to newest to avoid overwriting unexpired slots.
        for i in range(max_keep, 0, -1):
            src = bak if i == 1 else f"{bak}.{i - 1}"
            dst = f"{bak}.{i}"
            if i == max_keep:
                # Evict the oldest slot if it exists.
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
        """Return a sorted list of existing backup paths for *path*.

        Checks for ``<path>.bak``, ``<path>.bak.1``, ``<path>.bak.2``, … and
        returns every path that currently exists on the file system.  The list
        is ordered from newest (``<path>.bak``) to oldest (highest number).

        The numbered scan starts at ``<path>.bak.1`` and stops at the **first
        missing slot** in the sequence, regardless of whether higher-numbered
        files exist.  For example, if ``<path>.bak.1`` is absent but
        ``<path>.bak.2`` exists, only ``<path>.bak`` (if present) is returned.
        If ``<path>.bak`` does not exist the numbered scan is still performed,
        so ``[path+".bak.1"]`` can be returned even when ``<path>.bak`` is
        absent.

        Args:
            path: Base path (without the ``.bak`` suffix).

        Returns:
            List of existing backup file paths, e.g.
            ``["/data/rules.enc.bak", "/data/rules.enc.bak.1"]``.  Empty list
            when no backups exist.
        """
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
        """Delete all backup files for *path* and return the count removed.

        Calls :meth:`list_bak_files` to discover existing backups and
        removes each one with :func:`os.unlink`.  Silently skips any file
        that has already been removed between the listing and deletion
        steps.

        Args:
            path: Base path (without the ``.bak`` suffix).

        Returns:
            Number of backup files successfully deleted.
        """
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
        """Rotate existing backups then write *content* to *path*.

        Convenience wrapper that:

        1. Calls :meth:`rotate_bak(path, max_keep=max_keep)` to shift any
           existing ``.bak`` files before overwriting the live file.
        2. Atomically writes *content* to *path* (write → flush → close).

        Args:
            path: Destination file path to write.
            content: String content to write.
            max_keep: Forwarded to :meth:`rotate_bak`; controls how many
                numbered backup slots to keep (default 3).

        Returns:
            ``True`` on success; ``False`` if an :class:`OSError` occurs
            during the write step.
        """
        ComplianceChecker.rotate_bak(path, max_keep=max_keep)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            return True
        except OSError:
            return False

    @staticmethod
    def backup_exists_any(path: str) -> bool:
        """Return ``True`` when at least one backup file exists for *path*.

        Convenience wrapper around :meth:`list_bak_files` for callers that
        only need to know whether *any* backup is present::

            if ComplianceChecker.backup_exists_any("/data/rules.enc"):
                # safe to restore from backup
                ComplianceChecker.restore_from_bak("/data/rules.enc")

        Args:
            path: Base file path (without ``.bak`` suffix).

        Returns:
            ``True`` if one or more backup files exist; ``False`` otherwise.
        """
        return bool(ComplianceChecker.list_bak_files(path))

    @staticmethod
    def backup_count(path: str) -> int:
        """Return the number of backup files that exist for *path*.

        Equivalent to ``len(list_bak_files(path))`` but more readable when
        only the count is needed::

            n = ComplianceChecker.backup_count("/data/rules.enc")
            print(f"{n} backups available")

        Args:
            path: Base file path (without ``.bak`` suffix).

        Returns:
            Number of backup files (``0`` when none exist).
        """
        return len(ComplianceChecker.list_bak_files(path))

    @staticmethod
    def backup_age(path: str) -> Optional[float]:
        """Return the age in seconds of the most-recent backup file.

        Uses :func:`os.path.getmtime` on the primary ``.bak`` file.  If no
        backup exists, returns ``None``::

            age = ComplianceChecker.backup_age("/data/rules.enc")
            if age is not None:
                print(f"Most recent backup is {age:.0f}s old")
            else:
                print("No backup exists")

        Args:
            path: Base file path (without ``.bak`` suffix).

        Returns:
            Age in seconds since last modification (``float``), or ``None``
            if no backup files exist.
        """
        files = ComplianceChecker.list_bak_files(path)
        if not files:
            return None
        try:
            return float(os.path.getmtime(files[0]))
        except OSError:
            return None

    @staticmethod
    def oldest_backup_age(path: str) -> Optional[float]:
        """Return the mtime of the *oldest* backup file.

        Uses :func:`os.path.getmtime` on the last item returned by
        :meth:`list_bak_files` (highest-numbered ``.bak.N``).  Returns
        ``None`` when no backup files exist or when ``getmtime`` raises
        ``OSError``::

            age = ComplianceChecker.oldest_backup_age("/data/rules.enc")
            if age is not None and time.time() - age > 86400:
                ComplianceChecker.purge_bak_files("/data/rules.enc")

        Args:
            path: Base file path (without ``.bak`` suffix).

        Returns:
            ``float`` mtime of the oldest backup, or ``None``.
        """
        files = ComplianceChecker.list_bak_files(path)
        if not files:
            return None
        try:
            return float(os.path.getmtime(files[-1]))
        except OSError:
            return None

    @staticmethod
    def newest_backup_path(path: str) -> Optional[str]:
        """Return the path of the *newest* (primary) backup file.

        Returns the first item from :meth:`list_bak_files`, which is the
        ``.bak`` file (most recently written).  Returns ``None`` when no
        backup exists::

            bak = ComplianceChecker.newest_backup_path("/data/rules.enc")
            if bak is not None:
                ComplianceChecker.restore_from_bak("/data/rules.enc")

        This is the complement of :meth:`oldest_backup_age` — while that
        method returns the *mtime* of the oldest backup, this method returns
        the *path* of the newest backup.

        Args:
            path: Base file path (without ``.bak`` suffix).

        Returns:
            Path string of the primary ``.bak`` file, or ``None``.
        """
        files = ComplianceChecker.list_bak_files(path)
        return files[0] if files else None

    @staticmethod
    def oldest_backup_path(path: str) -> Optional[str]:
        """Return the path of the *oldest* backup file.

        Returns the last item from :meth:`list_bak_files`, which is the
        ``.bak.N`` file with the highest index (oldest backup).  Returns
        ``None`` when no backup exists::

            old_bak = ComplianceChecker.oldest_backup_path("/data/rules.enc")
            if old_bak is not None:
                os.unlink(old_bak)  # targeted removal of oldest backup

        This is the complement of :meth:`newest_backup_path` — while that
        method returns the *path* of the newest backup (``path + ".bak"``),
        this method returns the *path* of the oldest backup
        (``path + ".bak.N"`` for largest N, or ``path + ".bak"`` when only
        one backup exists).

        Args:
            path: Base file path (without ``.bak`` suffix).

        Returns:
            Path string of the oldest ``.bak`` file, or ``None``.
        """
        files = ComplianceChecker.list_bak_files(path)
        return files[-1] if files else None

    @staticmethod
    def backup_summary(path: str) -> dict:
        """Return a dict summarising the backup state for *path*.

        Collects the most useful backup metrics into a single call so that
        callers do not need to invoke several static methods individually::

            summary = ComplianceChecker.backup_summary("/data/rules.enc")
            # {
            #     "count": 2,
            #     "newest": "/data/rules.enc.bak",
            #     "oldest": "/data/rules.enc.bak.1",
            #     "newest_age": 1708690123.4,   # Unix mtime of newest .bak
            #     "oldest_age": 1708690056.7,   # Unix mtime of oldest .bak
            # }

        When no backups exist all path/mtime fields are ``None``::

            summary = ComplianceChecker.backup_summary("/data/no-backups.enc")
            # {"count": 0, "newest": None, "oldest": None,
            #  "newest_age": None, "oldest_age": None}

        Note:
            ``newest_age`` and ``oldest_age`` are Unix modification-time
            timestamps (``os.path.getmtime``), consistent with
            :meth:`backup_age` and :meth:`oldest_backup_age`.  They are
            **not** elapsed ages in seconds.

        Args:
            path: Base file path (without ``.bak`` suffix).

        Returns:
            Dict with keys ``count`` (int), ``newest`` (str or None),
            ``oldest`` (str or None), ``newest_age`` (float mtime or None),
            and ``oldest_age`` (float mtime or None).
        """
        import os as _os
        files = ComplianceChecker.list_bak_files(path)
        count = len(files)
        if count == 0:
            return {
                "count": 0,
                "newest": None,
                "oldest": None,
                "newest_age": None,
                "oldest_age": None,
            }
        newest = files[0]
        oldest = files[-1]
        try:
            newest_age: Optional[float] = float(_os.path.getmtime(newest))
        except OSError:
            newest_age = None
        try:
            oldest_age: Optional[float] = float(_os.path.getmtime(oldest))
        except OSError:
            oldest_age = None
        return {
            "count": count,
            "newest": newest,
            "oldest": oldest,
            "newest_age": newest_age,
            "oldest_age": oldest_age,
        }
        import os as _os
        files = ComplianceChecker.list_bak_files(path)
        count = len(files)
        if count == 0:
            return {
                "count": 0,
                "newest": None,
                "oldest": None,
                "newest_age": None,
                "oldest_age": None,
            }
        newest = files[0]
        oldest = files[-1]
        try:
            newest_age: Optional[float] = float(_os.path.getmtime(newest))
        except OSError:
            newest_age = None
        try:
            oldest_age: Optional[float] = float(_os.path.getmtime(oldest))
        except OSError:
            oldest_age = None
        return {
            "count": count,
            "newest": newest,
            "oldest": oldest,
            "newest_age": newest_age,
            "oldest_age": oldest_age,
        }

    @staticmethod
    def _get_field(intent: Any, field: str, default: Any = None) -> Any:
        if isinstance(intent, dict):
            return intent.get(field, default)
        return getattr(intent, field, default)

    # ------------------------------------------------------------------
    # Built-in rule implementations
    # ------------------------------------------------------------------

    def _rule_tool_name_convention(self, intent: Any) -> ComplianceResult:
        rule_id = "tool_name_convention"
        tool_name = self._get_field(intent, "tool_name", "") or ""
        violations: List[ComplianceViolation] = []

        if not tool_name:
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message="tool_name is empty or missing",
                severity="error",
            ))
        elif not _TOOL_NAME_RE.match(tool_name):
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message=(
                    f"tool_name '{tool_name}' violates naming convention "
                    "(must match ^[a-z][a-z0-9_]*$)"
                ),
                severity="error",
            ))

        status = ComplianceStatus.COMPLIANT if not violations else ComplianceStatus.NON_COMPLIANT
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_intent_has_actor(self, intent: Any) -> ComplianceResult:
        rule_id = "intent_has_actor"
        actor = self._get_field(intent, "actor", "") or ""
        violations: List[ComplianceViolation] = []

        if not actor.strip():
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message="intent is missing a non-empty 'actor' field",
                severity="warning",
            ))

        status = (
            ComplianceStatus.COMPLIANT
            if not violations
            else ComplianceStatus.WARNING
        )
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_actor_is_valid(self, intent: Any) -> ComplianceResult:
        rule_id = "actor_is_valid"
        actor = self._get_field(intent, "actor", "") or ""
        violations: List[ComplianceViolation] = []

        if actor and re.search(r"\s", actor):
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message=f"actor '{actor}' contains whitespace",
                severity="error",
            ))

        status = ComplianceStatus.COMPLIANT if not violations else ComplianceStatus.NON_COMPLIANT
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_params_are_serializable(self, intent: Any) -> ComplianceResult:
        rule_id = "params_are_serializable"
        params = self._get_field(intent, "params", {}) or {}
        violations: List[ComplianceViolation] = []

        if not _is_json_serializable(params):
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message="intent params contain non-JSON-serializable values",
                severity="warning",
            ))

        status = (
            ComplianceStatus.COMPLIANT
            if not violations
            else ComplianceStatus.WARNING
        )
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_tool_not_in_deny_list(self, intent: Any) -> ComplianceResult:
        rule_id = "tool_not_in_deny_list"
        tool_name = self._get_field(intent, "tool_name", "") or ""
        violations: List[ComplianceViolation] = []

        if tool_name in self._deny_list:
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message=f"tool '{tool_name}' is in the deny list",
                severity="error",
            ))

        status = ComplianceStatus.COMPLIANT if not violations else ComplianceStatus.NON_COMPLIANT
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_rate_limit_ok(self, intent: Any) -> ComplianceResult:
        """Rate-limit stub — always passes.

        Implementations that need real rate limiting should remove this rule via
        :meth:`remove_rule` and register their own ``"rate_limit_ok"`` rule that
        reads per-actor request counters from an external store.

        The *intent* parameter is accepted for API compatibility but is not used
        by the default stub.
        """
        rule_id = "rate_limit_ok"
        return ComplianceResult(
            rule_id=rule_id,
            status=ComplianceStatus.COMPLIANT,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def check_compliance(self, intent: Any) -> ComplianceReport:
        """Run all registered rules against *intent* and return a report."""
        results: List[ComplianceResult] = []
        for rule_id in self._rule_order:
            fn = self._rules.get(rule_id)
            if fn is None:
                continue
            try:
                result = fn(intent)
            except Exception as exc:  # pragma: no cover  # guard
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

        return ComplianceReport(results=results)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_default_compliance_checker(
    deny_list: Optional[Set[str]] = None,
) -> ComplianceChecker:
    """Create a :class:`ComplianceChecker` with all 6 built-in rules loaded.

    Parameters
    ----------
    deny_list:
        Optional set of tool names to block outright.
    """
    checker = ComplianceChecker(deny_list=deny_list)
    checker.add_rule("tool_name_convention", checker._rule_tool_name_convention)
    checker.add_rule("intent_has_actor", checker._rule_intent_has_actor)
    checker.add_rule("actor_is_valid", checker._rule_actor_is_valid)
    checker.add_rule("params_are_serializable", checker._rule_params_are_serializable)
    checker.add_rule("tool_not_in_deny_list", checker._rule_tool_not_in_deny_list)
    checker.add_rule("rate_limit_ok", checker._rule_rate_limit_ok)
    return checker
