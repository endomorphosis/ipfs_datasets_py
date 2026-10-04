"""Early-refusal cleanup controls; no Torch models or real CUDA are opened."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location(
    "native768_cleanup_control_target",
    Path(__file__).resolve().parents[5] / "benchmarks/qualify_native_768_device.py")
TARGET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TARGET)


class Native768EarlyRefusalCleanupTests(unittest.TestCase):
    def run_refusal(self, *, available=True, initialization_error=None,
                    synchronization_error=None, allocations=(0, 0, 0),
                    thread_restore_error=None):
        lease = SimpleNamespace(released=False, lease_id="inert-owned-lease")
        lease.to_dict = lambda: {"lease_id": lease.lease_id}
        def release():
            lease.released = True
        lease.release = Mock(side_effect=release)
        scheduler = SimpleNamespace(acquire=Mock(return_value=lease))
        scheduler.snapshot = lambda: {"active_lease_count": int(not lease.released)}
        scheduler_module = ModuleType("inert_scheduler")
        scheduler_module.GlobalResourceScheduler = Mock(return_value=scheduler)
        scheduler_module.ResourceSchedulerConfig = lambda **kwargs: SimpleNamespace(**kwargs)
        scheduler_module.ResourceLane = SimpleNamespace(SNAPSHOT_EVALUATION="snapshot_evaluation")
        torch = ModuleType("torch")
        torch.get_num_threads = Mock(return_value=7)
        torch.set_num_threads = Mock(side_effect=[None, thread_restore_error])
        torch.tensor = Mock(side_effect=RuntimeError("controlled initial allocation refusal"))
        torch.cuda = SimpleNamespace(
            is_available=Mock(return_value=available), init=Mock(side_effect=initialization_error),
            current_device=Mock(return_value=0), memory_allocated=Mock(side_effect=allocations),
            memory_reserved=Mock(return_value=0), synchronize=Mock(side_effect=synchronization_error),
            empty_cache=Mock())
        torch._C = SimpleNamespace(_cuda_clearCublasWorkspaces=Mock())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            configuration = root / "configuration.json"
            configuration.write_text(json.dumps({"persisted_config": {}, "state_path": "inert",
                "lease_ttl_seconds": 120, "auto_renew_leases": True}))
            modules = {"torch": torch,
                "ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler": scheduler_module}
            with patch.dict(sys.modules, modules), contextlib.redirect_stdout(io.StringIO()):
                code = TARGET.run(root / "result", configuration, root / "unused-manifest", root / "unused-assets")
            result = json.loads((root / "result/result.json").read_bytes())
        self.assertEqual(code, 1)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["setup_training_calls"], 0)
        self.assertEqual(result["inference_training_calls"], 0)
        self.assertEqual(result["source_pins"], [])
        return result, lease, torch

    def test_initial_allocation_refusal_restores_baseline_and_releases(self):
        result, lease, torch = self.run_refusal()
        self.assertIn("controlled initial allocation refusal", result["error"]["message"])
        self.assertNotIn("cuda_cleanup_error", result)
        self.assertEqual(result["gpu_allocated_before_owned_sessions_bytes"], 0)
        self.assertEqual(result["cuda_cleanup_status"], "owned_allocations_restored_to_baseline")
        self.assertTrue(result["own_root_lease_released"])
        self.assertEqual(result["resources_after"]["active_lease_count"], 0)
        lease.release.assert_called_once()
        torch._C._cuda_clearCublasWorkspaces.assert_called_once()
        torch.cuda.empty_cache.assert_called_once()

    def test_no_cuda_refusal_releases_without_cuda_cleanup_calls(self):
        result, lease, torch = self.run_refusal(available=False)
        self.assertIn("actual CUDA required", result["error"]["message"])
        self.assertTrue(lease.released)
        self.assertEqual(result["cuda_cleanup_status"], "no_owned_cuda_device_initialized")
        torch.cuda.init.assert_not_called()
        torch.cuda.synchronize.assert_not_called()
        torch.cuda.memory_allocated.assert_not_called()

    def test_initialization_refusal_releases_before_owned_allocation(self):
        result, lease, torch = self.run_refusal(initialization_error=RuntimeError("controlled init refusal"))
        self.assertEqual(result["error"]["message"], "controlled init refusal")
        self.assertTrue(lease.released)
        torch.tensor.assert_not_called()
        torch.cuda.synchronize.assert_not_called()

    def test_synchronization_failure_keeps_lease_and_primary_error(self):
        result, lease, torch = self.run_refusal(synchronization_error=RuntimeError("controlled sync failure"))
        self.assertIn("initial allocation refusal", result["error"]["message"])
        self.assertEqual(result["cuda_cleanup_error"]["message"], "controlled sync failure")
        self.assertFalse(lease.released)
        lease.release.assert_not_called()
        torch.cuda.empty_cache.assert_not_called()

    def test_remaining_allocation_keeps_lease(self):
        result, lease, torch = self.run_refusal(allocations=(0, 4, 4))
        self.assertIn("GPU allocations remained", result["cuda_cleanup_error"]["message"])
        self.assertFalse(lease.released)
        self.assertEqual(result["gpu_allocated_after_framework_workspace_clear_bytes"], 4)
        torch.cuda.empty_cache.assert_not_called()

    def test_thread_restore_failure_does_not_skip_safe_cuda_release(self):
        result, lease, torch = self.run_refusal(thread_restore_error=RuntimeError("controlled thread restore failure"))
        self.assertEqual(result["thread_restore_error"]["message"], "controlled thread restore failure")
        self.assertIn("initial allocation refusal", result["error"]["message"])
        self.assertTrue(lease.released)
        self.assertNotIn("cuda_cleanup_error", result)
        torch.cuda.empty_cache.assert_called_once()


if __name__ == "__main__":
    unittest.main()
