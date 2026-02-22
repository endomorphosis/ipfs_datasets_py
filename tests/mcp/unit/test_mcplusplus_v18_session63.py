"""Session 63 — MCP++ v18 Next Steps tests.

Implements tests for:
1. FilePolicyStore version control (_POLICY_STORE_VERSION, save/load "version" field)
2. IPFSPolicyStore.save_encrypted / load_encrypted
3. DelegationManager.revoke_chain() pubsub notification
4. ComplianceChecker.merge(other)
5. E2E: encrypted policy store + compliance versioning + revocation pubsub + round-trip
"""

import json
import os
import tempfile
import time
import unittest
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_path(suffix=""):
    d = tempfile.mkdtemp()
    return os.path.join(d, f"test_file{suffix}")


# ===========================================================================
# Section 1 — FilePolicyStore version control
# ===========================================================================

class TestFilePolicyStoreVersionControl(unittest.TestCase):
    """FilePolicyStore: _POLICY_STORE_VERSION constant + versioned save/load."""

    def test_policy_store_version_constant_exists(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import _POLICY_STORE_VERSION
        self.assertIsInstance(_POLICY_STORE_VERSION, str)
        self.assertEqual(_POLICY_STORE_VERSION, "1")

    def test_save_writes_version_field(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = FilePolicyStore(path, reg)
        reg.register("allow_admin", "admin may call any tool")
        store.save()
        with open(path) as fh:
            data = json.load(fh)
        self.assertIn("version", data)
        self.assertEqual(data["version"], "1")

    def test_save_writes_policies_under_policies_key(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = FilePolicyStore(path, reg)
        reg.register("p1", "user may call search")
        store.save()
        with open(path) as fh:
            data = json.load(fh)
        self.assertIn("policies", data)
        self.assertIn("p1", data["policies"])

    def test_load_reads_versioned_format(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = FilePolicyStore(path, reg)
        reg.register("p1", "user may call search")
        store.save()
        # Load into fresh registry
        reg2 = PolicyRegistry()
        store2 = FilePolicyStore(path, reg2)
        count = store2.load()
        self.assertEqual(count, 1)
        self.assertIn("p1", reg2.list_names())

    def test_load_legacy_flat_format_still_works(self):
        """Old files without 'version' key are still accepted."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry, _make_policy_cid,
        )
        path = _tmp_path(".json")
        nl = "user may call search"
        cid = _make_policy_cid(nl)
        legacy = {
            "p_legacy": {
                "nl_policy": nl,
                "description": "",
                "source_cid": cid,
            }
        }
        with open(path, "w") as fh:
            json.dump(legacy, fh)
        reg = PolicyRegistry()
        store = FilePolicyStore(path, reg)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            count = store.load()
        # No version warning for legacy files
        version_warnings = [x for x in w if "Policy store file" in str(x.message)]
        self.assertEqual(len(version_warnings), 0)
        self.assertEqual(count, 1)
        self.assertIn("p_legacy", reg.list_names())

    def test_load_warns_on_version_mismatch(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry, _make_policy_cid,
        )
        path = _tmp_path(".json")
        nl = "user may call search"
        cid = _make_policy_cid(nl)
        future_versioned = {
            "version": "99",
            "policies": {
                "p1": {"nl_policy": nl, "description": "", "source_cid": cid}
            },
        }
        with open(path, "w") as fh:
            json.dump(future_versioned, fh)
        reg = PolicyRegistry()
        store = FilePolicyStore(path, reg)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            count = store.load()
        version_warnings = [x for x in w if "Policy store file" in str(x.message)]
        self.assertEqual(len(version_warnings), 1)
        self.assertIn("99", str(version_warnings[0].message))
        # Still loads the data
        self.assertEqual(count, 1)

    def test_load_no_warning_for_matching_version(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = FilePolicyStore(path, reg)
        reg.register("p1", "user may call search")
        store.save()
        reg2 = PolicyRegistry()
        store2 = FilePolicyStore(path, reg2)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            store2.load()
        version_warnings = [x for x in w if "Policy store file" in str(x.message)]
        self.assertEqual(len(version_warnings), 0)

    def test_save_then_load_round_trip_multiple_policies(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = FilePolicyStore(path, reg)
        reg.register("p1", "user may call search")
        reg.register("p2", "admin may call delete")
        store.save()
        reg2 = PolicyRegistry()
        store2 = FilePolicyStore(path, reg2)
        count = store2.load()
        self.assertEqual(count, 2)

    def test_encrypted_save_includes_version(self):
        """save_encrypted payload must include 'version' field."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            self.skipTest("cryptography not installed")
        import hashlib
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = FilePolicyStore(path, reg)
        reg.register("p1", "user may call search")
        store.save_encrypted("testpass")
        enc_path = path + ".enc"
        self.assertTrue(os.path.exists(enc_path))
        with open(enc_path, "rb") as fh:
            raw = fh.read()
        nonce, ciphertext = raw[:12], raw[12:]
        key = hashlib.sha256(b"testpass").digest()
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
        data = json.loads(plaintext)
        self.assertIn("version", data)
        self.assertEqual(data["version"], "1")
        self.assertIn("policies", data)


# ===========================================================================
# Section 2 — IPFSPolicyStore.save_encrypted / load_encrypted
# ===========================================================================

class TestIPFSPolicyStoreEncryption(unittest.TestCase):
    """IPFSPolicyStore inherits encrypted persistence from FilePolicyStore."""

    def test_ipfs_policy_store_has_save_encrypted(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSPolicyStore
        self.assertTrue(hasattr(IPFSPolicyStore, "save_encrypted"))
        self.assertTrue(callable(IPFSPolicyStore.save_encrypted))

    def test_ipfs_policy_store_has_load_encrypted(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSPolicyStore
        self.assertTrue(hasattr(IPFSPolicyStore, "load_encrypted"))
        self.assertTrue(callable(IPFSPolicyStore.load_encrypted))

    def test_ipfs_save_encrypted_delegates_to_file(self):
        """save_encrypted should produce a .enc file at path+'.enc'."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa
        except ImportError:
            self.skipTest("cryptography not installed")
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = IPFSPolicyStore(path, reg, ipfs_client=None)
        reg.register("p1", "user may call search")
        store.save_encrypted("secret")
        self.assertTrue(os.path.exists(path + ".enc"))

    def test_ipfs_load_encrypted_round_trip(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa
        except ImportError:
            self.skipTest("cryptography not installed")
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = IPFSPolicyStore(path, reg, ipfs_client=None)
        reg.register("p1", "user may call search")
        store.save_encrypted("secret")
        reg2 = PolicyRegistry()
        store2 = IPFSPolicyStore(path, reg2, ipfs_client=None)
        count = store2.load_encrypted("secret")
        self.assertEqual(count, 1)
        self.assertIn("p1", reg2.list_names())

    def test_ipfs_load_encrypted_wrong_password_returns_0(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa
        except ImportError:
            self.skipTest("cryptography not installed")
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = IPFSPolicyStore(path, reg, ipfs_client=None)
        reg.register("p1", "user may call search")
        store.save_encrypted("correct_password")
        reg2 = PolicyRegistry()
        store2 = IPFSPolicyStore(path, reg2, ipfs_client=None)
        count = store2.load_encrypted("wrong_password")
        self.assertEqual(count, 0)

    def test_ipfs_load_encrypted_no_file_returns_0(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = IPFSPolicyStore(path, reg, ipfs_client=None)
        count = store.load_encrypted("anypassword")
        self.assertEqual(count, 0)

    def test_ipfs_save_encrypted_fallback_when_no_cryptography(self):
        """save_encrypted produces either .enc (cryptography present) or falls back to plain."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = IPFSPolicyStore(path, reg, ipfs_client=None)
        reg.register("p1", "user may call search")
        # Test the actual public contract: after save_encrypted a retrievable
        # file is produced regardless of whether cryptography is installed.
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa
            # cryptography is available → .enc file should be produced
            store.save_encrypted("password")
            self.assertTrue(os.path.exists(path + ".enc"),
                            ".enc file should be created when cryptography is available")
        except ImportError:
            # cryptography is NOT available → fallback to plain save + UserWarning
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                store.save_encrypted("password")
            warn_msgs = [str(x.message) for x in w if issubclass(x.category, UserWarning)]
            self.assertTrue(any("cryptography" in m for m in warn_msgs),
                            "UserWarning expected when cryptography is absent")
            self.assertTrue(os.path.exists(path),
                            "Plain JSON file should exist after fallback save()")


# ===========================================================================
# Section 3 — DelegationManager.revoke_chain() pubsub notification
# ===========================================================================

class TestDelegationManagerRevokePubsub(unittest.TestCase):
    """DelegationManager.revoke_chain publishes RECEIPT_DISSEMINATE to PubSubBus."""

    def test_revoke_chain_publishes_to_bus(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Delegation, Capability,
        )
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import (
            PubSubBus, PubSubEventType,
        )
        mgr = DelegationManager()
        # Add a simple delegation
        d = Delegation(
            cid="cid-root",
            issuer="did:key:alice",
            audience="did:key:bob",
            capabilities=[Capability("mcp://tool", "invoke")],
            expiry=time.time() + 3600,
            proof_cid=None,
        )
        mgr.add(d)
        bus = PubSubBus()
        received = []
        bus.subscribe(PubSubEventType.RECEIPT_DISSEMINATE, lambda _t, p: received.append(p))
        import ipfs_datasets_py.mcp_server.mcp_p2p_transport as t_mod
        original = t_mod._GLOBAL_BUS
        try:
            t_mod._GLOBAL_BUS = bus
            count = mgr.revoke_chain("cid-root")
        finally:
            t_mod._GLOBAL_BUS = original
        # revoke_chain on a CID in the store should revoke it + publish
        self.assertGreaterEqual(count, 0)
        self.assertEqual(len(received), 1)

    def test_revoke_chain_pubsub_payload_structure(self):
        """Published payload must include type, root_cid and count."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import (
            PubSubBus, PubSubEventType,
        )
        mgr = DelegationManager()
        bus = PubSubBus()
        payloads = []
        bus.subscribe(PubSubEventType.RECEIPT_DISSEMINATE, lambda _t, p: payloads.append(p))
        import ipfs_datasets_py.mcp_server.mcp_p2p_transport as t_mod
        original = t_mod._GLOBAL_BUS
        try:
            t_mod._GLOBAL_BUS = bus
            mgr.revoke_chain("non-existent-cid")
        finally:
            t_mod._GLOBAL_BUS = original
        self.assertEqual(len(payloads), 1)
        p = payloads[0]
        self.assertEqual(p["type"], "revocation")
        self.assertEqual(p["root_cid"], "non-existent-cid")
        self.assertIn("count", p)

    def test_revoke_chain_pubsub_failure_does_not_raise(self):
        """Pubsub exceptions must be swallowed."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        failing_bus = MagicMock()
        failing_bus.publish.side_effect = RuntimeError("bus exploded")
        import ipfs_datasets_py.mcp_server.mcp_p2p_transport as t_mod
        original = t_mod._GLOBAL_BUS
        try:
            t_mod._GLOBAL_BUS = failing_bus
            # Should not raise
            result = mgr.revoke_chain("any-cid")
        finally:
            t_mod._GLOBAL_BUS = original
        self.assertIsInstance(result, int)

    def test_revoke_chain_pubsub_count_matches_revoked(self):
        """The published 'count' matches the return value of revoke_chain."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Delegation, Capability,
        )
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import (
            PubSubBus, PubSubEventType,
        )
        mgr = DelegationManager()
        d = Delegation(
            cid="root-cid",
            issuer="did:key:alice",
            audience="did:key:bob",
            capabilities=[Capability("mcp://tool", "invoke")],
            expiry=time.time() + 3600,
            proof_cid=None,
        )
        mgr.add(d)
        bus = PubSubBus()
        payloads = []
        bus.subscribe(PubSubEventType.RECEIPT_DISSEMINATE, lambda _t, p: payloads.append(p))
        import ipfs_datasets_py.mcp_server.mcp_p2p_transport as t_mod
        original = t_mod._GLOBAL_BUS
        try:
            t_mod._GLOBAL_BUS = bus
            returned_count = mgr.revoke_chain("root-cid")
        finally:
            t_mod._GLOBAL_BUS = original
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["count"], returned_count)

    def test_revoke_chain_source_code_uses_receipt_disseminate(self):
        """Source inspection: revoke_chain must reference RECEIPT_DISSEMINATE."""
        import inspect
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = inspect.getsource(DelegationManager.revoke_chain)
        self.assertIn("RECEIPT_DISSEMINATE", src)
        self.assertIn("get_global_bus", src)


# ===========================================================================
# Section 4 — ComplianceChecker.merge(other)
# ===========================================================================

class TestComplianceCheckerMerge(unittest.TestCase):
    """ComplianceChecker.merge(other) merges rules and deny-list."""

    def _make_checker_with_rule(self, rule_id: str):
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceResult, ComplianceStatus,
        )
        checker = ComplianceChecker()
        checker.add_rule(
            rule_id,
            lambda intent, _r=rule_id: ComplianceResult(ComplianceStatus.COMPLIANT),
        )
        return checker

    def test_merge_adds_new_rules(self):
        checker_a = self._make_checker_with_rule("rule_a")
        checker_b = self._make_checker_with_rule("rule_b")
        added = checker_a.merge(checker_b)
        self.assertEqual(added, 1)
        self.assertIn("rule_b", checker_a.list_rules())

    def test_merge_does_not_overwrite_existing_rules(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceResult, ComplianceStatus,
        )
        # Both have 'rule_shared' — checker_a's version should win.
        original_fn = lambda intent: ComplianceResult(ComplianceStatus.COMPLIANT)
        other_fn = lambda intent: ComplianceResult(ComplianceStatus.NON_COMPLIANT)
        checker_a = ComplianceChecker()
        checker_a.add_rule("rule_shared", original_fn)
        checker_b = ComplianceChecker()
        checker_b.add_rule("rule_shared", other_fn)
        added = checker_a.merge(checker_b)
        self.assertEqual(added, 0)
        # Verify checker_a's rule_shared fn is unchanged
        self.assertIs(checker_a._rules["rule_shared"], original_fn)

    def test_merge_unions_deny_list(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker_a = ComplianceChecker(deny_list={"tool_x"})
        checker_b = ComplianceChecker(deny_list={"tool_y"})
        checker_a.merge(checker_b)
        self.assertIn("tool_x", checker_a._deny_list)
        self.assertIn("tool_y", checker_a._deny_list)

    def test_merge_returns_count_of_new_rules(self):
        checker_a = self._make_checker_with_rule("rule_a")
        checker_b = self._make_checker_with_rule("rule_b")
        checker_b.add_rule("rule_b2", lambda i: None)
        added = checker_a.merge(checker_b)
        self.assertEqual(added, 2)

    def test_merge_empty_other_returns_0(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker_a = self._make_checker_with_rule("rule_a")
        checker_b = ComplianceChecker()
        added = checker_a.merge(checker_b)
        self.assertEqual(added, 0)

    def test_merge_empty_self_with_full_other(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker_a = ComplianceChecker()
        checker_b = self._make_checker_with_rule("rule_b")
        added = checker_a.merge(checker_b)
        self.assertEqual(added, 1)
        self.assertIn("rule_b", checker_a.list_rules())

    def test_merge_preserves_rule_order(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker_a = ComplianceChecker()
        checker_a.add_rule("rule_1", lambda i: None)
        checker_a.add_rule("rule_2", lambda i: None)
        checker_b = ComplianceChecker()
        checker_b.add_rule("rule_3", lambda i: None)
        checker_a.merge(checker_b)
        order = checker_a.list_rules()
        self.assertEqual(order.index("rule_1"), 0)
        self.assertEqual(order.index("rule_2"), 1)
        self.assertEqual(order.index("rule_3"), 2)

    def test_merge_with_default_checker(self):
        """Merging two default checkers should add 0 new rules (all duplicates)."""
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            make_default_compliance_checker,
        )
        checker_a = make_default_compliance_checker()
        checker_b = make_default_compliance_checker()
        added = checker_a.merge(checker_b)
        self.assertEqual(added, 0)

    def test_merge_adds_deny_list_from_other_with_rules(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker_a = ComplianceChecker()
        checker_b = ComplianceChecker(deny_list={"banned_tool"})
        checker_b.add_rule("extra", lambda i: None)
        checker_a.merge(checker_b)
        self.assertIn("banned_tool", checker_a._deny_list)
        self.assertIn("extra", checker_a.list_rules())

    def test_merge_source_code_inspection(self):
        """Source inspection: merge() must reference _rule_order and _deny_list."""
        import inspect
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        src = inspect.getsource(ComplianceChecker.merge)
        self.assertIn("_rule_order", src)
        self.assertIn("_deny_list", src)


# ===========================================================================
# Section 5 — E2E: encrypted store + compliance versioning + revocation pubsub
# ===========================================================================

class TestE2ESession63(unittest.TestCase):
    """End-to-end scenario spanning multiple session 63 features."""

    def test_policy_store_version_round_trip(self):
        """Save + load produces correct version and policy count."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry, _POLICY_STORE_VERSION,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = FilePolicyStore(path, reg)
        reg.register("allow_search", "user may call search_tool")
        reg.register("deny_delete", "nobody may call delete_tool")
        store.save()
        with open(path) as fh:
            raw = json.load(fh)
        self.assertEqual(raw["version"], _POLICY_STORE_VERSION)
        self.assertEqual(len(raw["policies"]), 2)

        reg2 = PolicyRegistry()
        store2 = FilePolicyStore(path, reg2)
        count = store2.load()
        self.assertEqual(count, 2)
        self.assertIn("allow_search", reg2.list_names())
        self.assertIn("deny_delete", reg2.list_names())

    def test_compliance_and_policy_merge_pipeline(self):
        """Merge two specialised checkers + verify combined rule count."""
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceResult, ComplianceStatus,
        )
        security_checker = ComplianceChecker(deny_list={"exploit_tool"})
        security_checker.add_rule(
            "no_exploit",
            lambda i: ComplianceResult(ComplianceStatus.COMPLIANT),
        )
        audit_checker = ComplianceChecker(deny_list={"legacy_tool"})
        audit_checker.add_rule(
            "audit_trail_required",
            lambda i: ComplianceResult(ComplianceStatus.COMPLIANT),
        )
        combined = ComplianceChecker()
        combined.merge(security_checker)
        combined.merge(audit_checker)
        self.assertEqual(len(combined.list_rules()), 2)
        self.assertIn("exploit_tool", combined._deny_list)
        self.assertIn("legacy_tool", combined._deny_list)

    def test_revocation_pubsub_notification_observed(self):
        """revoke_chain publishes a payload that can be observed."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import (
            PubSubBus, PubSubEventType,
        )
        mgr = DelegationManager()
        bus = PubSubBus()
        events = []
        bus.subscribe(PubSubEventType.RECEIPT_DISSEMINATE, lambda _t, p: events.append(p))
        import ipfs_datasets_py.mcp_server.mcp_p2p_transport as t_mod
        original = t_mod._GLOBAL_BUS
        try:
            t_mod._GLOBAL_BUS = bus
            mgr.revoke_chain("root-cid-x")
        finally:
            t_mod._GLOBAL_BUS = original
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "revocation")
        self.assertEqual(events[0]["root_cid"], "root-cid-x")

    def test_ipfs_store_inherits_versioning(self):
        """IPFSPolicyStore uses the same versioned format as FilePolicyStore."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        path = _tmp_path(".json")
        reg = PolicyRegistry()
        store = IPFSPolicyStore(path, reg, ipfs_client=None)
        reg.register("p1", "admin may call all_tools")
        store.save()
        with open(path) as fh:
            raw = json.load(fh)
        self.assertIn("version", raw)
        self.assertIn("policies", raw)

    def test_compliance_merge_does_not_corrupt_deny_list(self):
        """After merge, original deny lists are not mutated."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker_a = ComplianceChecker(deny_list={"a_tool"})
        checker_b = ComplianceChecker(deny_list={"b_tool"})
        original_b = set(checker_b._deny_list)
        checker_a.merge(checker_b)
        # checker_b's deny_list should not have changed
        self.assertEqual(checker_b._deny_list, original_b)

    def test_policy_store_version_constant_exported(self):
        """_POLICY_STORE_VERSION should be importable at module level."""
        import importlib
        mod = importlib.import_module("ipfs_datasets_py.mcp_server.nl_ucan_policy")
        self.assertTrue(hasattr(mod, "_POLICY_STORE_VERSION"))

    def test_session62_spec_tests_still_pass_smoke(self):
        """Smoke: session 62 features still work after session 63 changes."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        metrics = mgr.get_metrics()
        self.assertIn("delegation_count", metrics)
        self.assertIn("revoked_cid_count", metrics)
        self.assertIn("max_chain_depth", metrics)

        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, _COMPLIANCE_RULE_VERSION,
        )
        self.assertEqual(_COMPLIANCE_RULE_VERSION, "1")

        from ipfs_datasets_py.mcp_server.nl_ucan_policy import _POLICY_STORE_VERSION
        self.assertEqual(_POLICY_STORE_VERSION, "1")


if __name__ == "__main__":
    unittest.main()
