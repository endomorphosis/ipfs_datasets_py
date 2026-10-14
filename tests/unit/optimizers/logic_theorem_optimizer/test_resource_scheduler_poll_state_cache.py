"""Fresh-state polling caches preserve scheduler authority and decoder behavior."""

from contextlib import contextmanager, nullcontext
import functools
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from types import SimpleNamespace
import types
import unittest
from unittest.mock import patch


from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
_DEFAULT = object()
BOOT_A = "11111111-1111-4111-8111-111111111111"
BOOT_B = "22222222-2222-4222-8222-222222222222"




@contextmanager
def decoded_calls():
    """Count actual default json.loads calls without replacing the decoder."""
    code = json.loads.__code__
    observed = []
    previous = sys.getprofile()

    def observe(frame, event, argument):
        if event == "call" and frame.f_code is code:
            observed.append(1)
        if previous is not None:
            previous(frame, event, argument)

    sys.setprofile(observe)
    try:
        yield observed
    finally:
        sys.setprofile(previous)


def encode(state):
    return json.dumps(state, sort_keys=True, separators=(",", ":")).encode()


def fresh_candidate_module(name):
    """Root-executed reload of the same selected leaf under a fresh module name."""
    path = Path(resources.__file__)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise RuntimeError("selected candidate source must retain its canonical path")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not (stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                and before.st_nlink == 1 and 0 < before.st_size <= 4 * 1024**2):
            raise RuntimeError("selected candidate source exceeds the held ordinary-leaf bound")
        parts = []
        remaining = before.st_size
        while remaining:
            block = os.read(descriptor, min(65536, remaining))
            if not block:
                raise RuntimeError("selected source read ended early")
            parts.append(block)
            remaining -= len(block)
        stamp = lambda value: tuple(getattr(value, key) for key in (
            "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode", "st_uid", "st_nlink"))
        if os.read(descriptor, 1) or stamp(before) != stamp(os.fstat(descriptor)) \
                or stamp(before) != stamp(os.stat(path, follow_symlinks=False)):
            raise RuntimeError("selected candidate source changed during its held read")
    finally:
        os.close(descriptor)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = resources.__name__.rpartition(".")[0]
    module.__spec__ = importlib.util.spec_from_file_location(name, path)
    if name in sys.modules:
        raise RuntimeError("fresh candidate alias is already occupied")
    sys.modules[name] = module
    try:
        exec(compile(b"".join(parts), str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


class TestFreshPollStateReuse(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="scheduler-poll-cache-tests-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.sequence = 0

    def owner(self, option=_DEFAULT, *, scheduler_type=None, ttl=30):
        self.sequence += 1
        config = resources.ResourceSchedulerConfig(
            state_path=self.directory / ("state-%d.json" % self.sequence),
            total_cpu_slots=2, total_memory_mb=200, total_child_process_slots=2,
            lane_reservations={}, auto_renew_leases=False,
            lease_ttl_seconds=ttl, poll_interval_seconds=.005,
        )
        factory = scheduler_type or resources.GlobalResourceScheduler
        if option is _DEFAULT:
            return factory(config)
        return factory(config, cached_poll_state=option)

    def lease(self, owner):
        lease = owner.acquire("orchestration", cpu_slots=2, memory_mb=200,
            child_process_slots=2, timeout=0)
        self.addCleanup(lease.release)
        return lease

    def child(self, parent):
        child = parent.acquire_child(cpu_slots=1, memory_mb=50,
            child_process_slots=1, timeout=0)
        self.addCleanup(child.release)
        return child

    def warm(self, lease):
        """Exercise both sentinel and admission reads before a hit-specific check."""
        self.assertFalse(lease.cancelled)
        self.assertFalse(lease.cancelled)
        owner = lease._scheduler
        if owner._cached_poll_state:
            self.assertIs(type(owner._poll_state_cache), tuple)
            self.assertIsNone(owner._poll_state_pending)

    def state(self, owner):
        return json.loads(owner.state_path.read_text(encoding="utf-8"))

    def write(self, owner, value):
        raw = encode(value)
        owner.state_path.write_bytes(raw)
        return raw

    def test_default_on_and_exact_boolean_opt_out_are_not_persisted_configuration(self):
        default = self.owner()
        explicit = self.owner(True)
        disabled = self.owner(False)
        self.assertIs(default._cached_poll_state, True)
        self.assertIs(explicit._cached_poll_state, True)
        self.assertIs(disabled._cached_poll_state, False)
        for owner in (default, explicit, disabled):
            self.assertNotIn("cached_poll_state", owner.config.persisted_dict())
            self.assertNotIn("cached_poll_state", self.state(owner)["config"])
        for index, option in enumerate((0, 1, None, "false", [], {}, object())):
            with self.subTest(option=repr(option)):
                path = self.directory / ("invalid-%d.json" % index)
                config = resources.ResourceSchedulerConfig(state_path=path,
                    total_cpu_slots=2, total_memory_mb=200, lane_reservations={},
                    auto_renew_leases=False)
                with self.assertRaises(resources.ResourceConfigurationError):
                    resources.GlobalResourceScheduler(config, cached_poll_state=option)
                self.assertFalse(path.exists())
                self.assertFalse(path.with_name(path.name + ".lock").exists())

    def test_identical_polls_still_read_each_time_and_opt_out_decodes_each_time(self):
        native_read = Path.read_text
        for option in (True, False):
            with self.subTest(cached_poll_state=option):
                owner = self.owner(option)
                lease = self.lease(owner)
                self.warm(lease)
                before = owner.state_path.read_bytes()
                reads = []

                def fresh(path, *arguments, **keywords):
                    value = native_read(path, *arguments, **keywords)
                    if path == owner.state_path:
                        reads.append(1)
                    return value

                with patch.object(Path, "read_text", fresh), decoded_calls() as calls:
                    for _ in range(3):
                        self.assertFalse(lease.cancelled)
                self.assertEqual(len(reads), 3)
                self.assertEqual(len(calls), 0 if option else 3)
                self.assertEqual(owner.state_path.read_bytes(), before)

    def test_same_size_and_mtime_in_place_cancellation_is_seen_on_next_poll(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        before = owner.state_path.stat()
        raw = owner.state_path.read_bytes()
        changed = raw.replace(b'"cancelled":false', b'"cancelled":true ', 1)
        self.assertNotEqual(changed, raw)
        self.assertEqual(len(changed), len(raw))
        owner.state_path.write_bytes(changed)
        os.utime(owner.state_path, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = owner.state_path.stat()
        self.assertEqual((after.st_size, after.st_mtime_ns), (before.st_size, before.st_mtime_ns))
        self.assertTrue(lease.cancelled)
        self.assertEqual(owner.state_path.read_bytes(), changed)

    def test_another_facade_cancel_and_release_are_observed_without_cached_authority(self):
        owner = self.owner()
        lease = self.lease(owner)
        writer = resources.GlobalResourceScheduler(owner.config, cached_poll_state=False)
        self.warm(lease)
        self.assertTrue(writer.cancel(lease.lease_id, lease.lease_key))
        self.assertTrue(lease.cancelled)
        self.assertTrue(writer.release(lease.lease_id, lease.lease_key))
        self.assertTrue(owner.is_cancelled(lease.lease_id, missing_is_cancelled=True))
        self.assertFalse(owner.is_cancelled(lease.lease_id, missing_is_cancelled=False))

    def test_corrupt_fresh_text_is_not_hidden_and_failure_clears_memo(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        valid = owner.state_path.read_bytes()
        broken = b'{"schema_version":'
        try:
            owner.state_path.write_bytes(broken)
            with self.assertRaises(resources.SchedulerStateError):
                owner.is_cancelled(lease.lease_id)
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
            self.assertEqual(owner.state_path.read_bytes(), broken)
        finally:
            owner.state_path.write_bytes(valid)
        self.assertFalse(lease.cancelled)

    def test_missing_and_blank_files_do_not_reuse_previous_leases(self):
        owner = self.owner()
        lease = self.lease(owner)
        valid = owner.state_path.read_bytes()
        for replacement in (None, b""):
            with self.subTest(replacement=replacement):
                owner.state_path.write_bytes(valid)
                self.warm(lease)
                try:
                    if replacement is None:
                        owner.state_path.unlink()
                    else:
                        owner.state_path.write_bytes(replacement)
                    self.assertTrue(owner.is_cancelled(lease.lease_id, missing_is_cancelled=True))
                    self.assertIsNone(owner._poll_state_cache)
                    self.assertIsNone(owner._poll_state_pending)
                    if replacement is None:
                        self.assertFalse(owner.state_path.exists())
                    else:
                        self.assertEqual(owner.state_path.read_bytes(), replacement)
                finally:
                    owner.state_path.write_bytes(valid)

    def test_fresh_schema_and_configuration_changes_are_refused_without_writes(self):
        owner = self.owner()
        lease = self.lease(owner)
        valid = owner.state_path.read_bytes()
        for field, error in (("schema", resources.SchedulerStateError),
                             ("config", resources.ResourceConfigurationError)):
            with self.subTest(field=field):
                owner.state_path.write_bytes(valid)
                self.warm(lease)
                value = self.state(owner)
                if field == "schema":
                    value["schema_version"] = "unsupported-future-schema"
                else:
                    value["config"]["total_memory_mb"] += 1
                changed = self.write(owner, value)
                try:
                    with self.assertRaises(error):
                        owner.is_cancelled(lease.lease_id)
                    self.assertIsNone(owner._poll_state_cache)
                    self.assertIsNone(owner._poll_state_pending)
                    self.assertEqual(owner.state_path.read_bytes(), changed)
                finally:
                    owner.state_path.write_bytes(valid)

    def test_current_facade_configuration_is_revalidated_on_identical_text(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        before = owner.state_path.read_bytes()
        with patch.object(owner.config, "total_memory_mb", 201):
            with self.assertRaises(resources.ResourceConfigurationError):
                owner.is_cancelled(lease.lease_id)
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
        self.assertEqual(owner.state_path.read_bytes(), before)
        self.assertFalse(lease.cancelled)

    def test_identical_text_still_observes_ancestor_expiry(self):
        clock = [time.time()]
        replacement = SimpleNamespace(time=lambda: clock[0], monotonic=time.monotonic, sleep=time.sleep)
        with patch.object(resources, "time", replacement):
            owner = self.owner(ttl=10)
            parent = self.lease(owner)
            clock[0] += 5
            child = self.child(parent)
            self.warm(child)
            before = owner.state_path.read_bytes()
            clock[0] += 6
            self.assertTrue(child.cancelled)
            self.assertEqual(owner.state_path.read_bytes(), before)

    def test_identical_text_still_observes_current_boot_identity(self):
        current = [BOOT_A]
        with patch.object(resources, "_owner_boot_id", lambda: current[0]):
            owner = self.owner()
            lease = self.lease(owner)
            try:
                self.warm(lease)
                before = owner.state_path.read_bytes()
                current[0] = BOOT_B
                self.assertTrue(lease.cancelled)
                self.assertEqual(owner.state_path.read_bytes(), before)
            finally:
                current[0] = BOOT_A
                lease.release()

    def test_identical_text_still_observes_process_birth_marker(self):
        marker = ["first-incarnation"]
        with patch.object(resources, "_owner_birth_marker", lambda pid: marker[0]):
            owner = self.owner()
            lease = self.lease(owner)
            try:
                self.warm(lease)
                before = owner.state_path.read_bytes()
                marker[0] = "second-incarnation"
                self.assertTrue(lease.cancelled)
                self.assertEqual(owner.state_path.read_bytes(), before)
            finally:
                marker[0] = "first-incarnation"
                lease.release()

    def test_liveness_is_fresh_per_poll_with_only_operation_local_owner_deduplication(self):
        owner = self.owner()
        parent = self.lease(owner)
        child = self.child(parent)
        self.warm(child)
        before = owner.state_path.read_bytes()
        native_alive = resources._owner_is_alive
        observed = []
        alive = [True]

        def probe(pid, marker):
            observed.append((pid, marker))
            return alive[0] and native_alive(pid, marker)

        with patch.object(resources, "_owner_is_alive", probe):
            for _ in range(3):
                count = len(observed)
                self.assertFalse(child.cancelled)
                self.assertEqual(len(observed), count + 1)
            alive[0] = False
            self.assertTrue(child.cancelled)
        self.assertEqual(owner.state_path.read_bytes(), before)

    def test_virtual_validator_mutation_never_poison_pristine_miss_or_hit_snapshots(self):
        class MutatingScheduler(resources.GlobalResourceScheduler):
            inject = False
            target = None

            def _validate_state_configuration(inner, state, *, allow_reconfigure=False):
                super()._validate_state_configuration(state, allow_reconfigure=allow_reconfigure)
                if inner.target is not None:
                    inner.observed.append(state)
                    if inner.inject:
                        state["leases"][inner.target]["cancelled"] = True
                        state["metrics"]["wait_samples"].append("local-only")

        owner = self.owner(scheduler_type=MutatingScheduler)
        lease = self.lease(owner)
        owner.target = lease.lease_id
        owner.observed = []
        value = self.state(owner)
        value["metrics"]["test_revision"] = 1
        before = self.write(owner, value)
        for inject in (True, False, True, False):
            owner.inject = inject
            self.assertIs(owner.is_cancelled(lease.lease_id), inject)
        self.assertEqual(len(owner.observed), 4)
        for index, current in enumerate(owner.observed):
            for earlier in owner.observed[:index]:
                self.assertIsNot(current, earlier)
                self.assertIsNot(current["leases"], earlier["leases"])
                self.assertIsNot(current["leases"][lease.lease_id], earlier["leases"][lease.lease_id])
                self.assertIsNot(current["metrics"]["wait_samples"], earlier["metrics"]["wait_samples"])
        self.assertEqual(owner.state_path.read_bytes(), before)
        owner.target = None

    def test_read_only_context_body_mutation_is_detached_from_next_poll(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        before = owner.state_path.read_bytes()
        with owner._locked_state(persist=False) as state:
            state["leases"][lease.lease_id]["cancelled"] = True
            state["metrics"]["wait_samples"].append("context-only")
        self.assertFalse(lease.cancelled)
        self.assertEqual(owner.state_path.read_bytes(), before)

    def test_virtual_validation_failure_clears_memo_before_next_attempt(self):
        class RejectingScheduler(resources.GlobalResourceScheduler):
            reject = False

            def _validate_state_configuration(inner, state, *, allow_reconfigure=False):
                super()._validate_state_configuration(state, allow_reconfigure=allow_reconfigure)
                if inner.reject:
                    state["metrics"]["wait_samples"].append("failed-only")
                    raise resources.ResourceConfigurationError("injected virtual validation failure")

        owner = self.owner(scheduler_type=RejectingScheduler)
        lease = self.lease(owner)
        self.warm(lease)
        before = owner.state_path.read_bytes()
        owner.reject = True
        try:
            with self.assertRaises(resources.ResourceConfigurationError):
                owner.is_cancelled(lease.lease_id)
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
        finally:
            owner.reject = False
        with decoded_calls() as calls:
            self.assertFalse(lease.cancelled)
        self.assertEqual(len(calls), 1)
        self.assertEqual(owner.state_path.read_bytes(), before)

    def test_replaced_loads_hook_runs_each_time_and_changed_meaning_is_visible(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        before = owner.state_path.read_bytes()
        native_loads = json.loads
        observed = []
        cancelled = [True]

        def changed(raw, *arguments, **keywords):
            observed.append(1)
            state = native_loads(raw, *arguments, **keywords)
            state["leases"][lease.lease_id]["cancelled"] = cancelled[0]
            return state

        with patch.object(resources.json, "loads", changed):
            self.assertTrue(lease.cancelled)
            cancelled[0] = False
            self.assertFalse(lease.cancelled)
            self.assertEqual(len(observed), 2)
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
        self.assertFalse(lease.cancelled)
        self.assertEqual(owner.state_path.read_bytes(), before)

    def test_replaced_decoder_class_hook_is_not_bypassed_by_warm_memo(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        before = owner.state_path.read_bytes()
        native_decode = json.JSONDecoder.raw_decode
        observed = []

        def changed(decoder, text, idx=0):
            value, end = native_decode(decoder, text, idx=idx)
            if type(value) is dict and "leases" in value:
                observed.append(1)
                value["leases"][lease.lease_id]["cancelled"] = True
            return value, end

        with patch.object(json.JSONDecoder, "raw_decode", changed):
            self.assertTrue(lease.cancelled)
            self.assertTrue(lease.cancelled)
            self.assertEqual(len(observed), 2)
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
        self.assertFalse(lease.cancelled)
        self.assertEqual(owner.state_path.read_bytes(), before)

    def test_preimport_partial_decoder_loads_and_preserves_stateful_hook_semantics(self):
        native_loads = json.loads
        target = [None]
        cancelled = [False]
        observed = []

        def changed(raw, *arguments, **keywords):
            value = native_loads(raw, *arguments, **keywords)
            if type(value) is dict and target[0] in value.get("leases", {}):
                observed.append(1)
                value["leases"][target[0]]["cancelled"] = cancelled[0]
            return value

        alias = resources.__name__.rpartition(".")[0] + "._poll_cache_preimport_partial"
        with patch.object(json, "loads", functools.partial(changed)):
            module = fresh_candidate_module(alias)
            self.addCleanup(sys.modules.pop, alias, None)
            owner = module.GlobalResourceScheduler(module.ResourceSchedulerConfig(
                state_path=self.directory / "preimport-partial.json", total_cpu_slots=2,
                total_memory_mb=200, lane_reservations={}, auto_renew_leases=False))
            lease = self.lease(owner)
            target[0] = lease.lease_id
            before = owner.state_path.read_bytes()
            try:
                cancelled[0] = True
                self.assertTrue(lease.cancelled)
                cancelled[0] = False
                self.assertFalse(lease.cancelled)
                self.assertEqual(len(observed), 2)
                self.assertIsNone(owner._poll_state_cache)
                self.assertIsNone(owner._poll_state_pending)
                self.assertEqual(owner.state_path.read_bytes(), before)
            finally:
                target[0] = None
                lease.release()

    def test_preimport_default_decoder_object_hook_remains_fresh_and_uncached(self):
        target = [None]
        cancelled = [False]
        observed = []

        def object_hook(value):
            if target[0] in value.get("leases", {}):
                observed.append(1)
                value["leases"][target[0]]["cancelled"] = cancelled[0]
            return value

        decoder = json.JSONDecoder(object_hook=object_hook)
        alias = resources.__name__.rpartition(".")[0] + "._poll_cache_preimport_object_hook"
        with patch.object(json, "_default_decoder", decoder):
            module = fresh_candidate_module(alias)
            self.addCleanup(sys.modules.pop, alias, None)
            owner = module.GlobalResourceScheduler(module.ResourceSchedulerConfig(
                state_path=self.directory / "preimport-hook.json", total_cpu_slots=2,
                total_memory_mb=200, lane_reservations={}, auto_renew_leases=False))
            lease = self.lease(owner)
            target[0] = lease.lease_id
            before = owner.state_path.read_bytes()
            try:
                cancelled[0] = True
                self.assertTrue(lease.cancelled)
                cancelled[0] = False
                self.assertFalse(lease.cancelled)
                self.assertEqual(len(observed), 2)
                self.assertIsNone(owner._poll_state_cache)
                self.assertIsNone(owner._poll_state_pending)
                self.assertEqual(owner.state_path.read_bytes(), before)
            finally:
                target[0] = None
                lease.release()

    def test_clone_failure_falls_back_to_fresh_json_without_changing_authority(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        before = owner.state_path.read_bytes()

        def broken(encoded):
            raise ValueError("injected marshal clone refusal")

        with patch.object(resources, "_clone_poll_state", broken), decoded_calls() as calls:
            self.assertFalse(lease.cancelled)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(owner._poll_state_cache)
        self.assertIsNone(owner._poll_state_pending)
        self.assertFalse(lease.cancelled)
        self.assertEqual(owner.state_path.read_bytes(), before)

    def test_decoder_changed_during_fresh_read_is_used_before_virtual_validation(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        before = owner.state_path.read_bytes()
        native_read, native_loads = Path.read_text, json.loads
        observed = []

        def changed(raw, *arguments, **keywords):
            observed.append(1)
            value = native_loads(raw, *arguments, **keywords)
            value["leases"][lease.lease_id]["cancelled"] = True
            return value

        def read_then_change(path, *arguments, **keywords):
            raw = native_read(path, *arguments, **keywords)
            if path == owner.state_path:
                resources.json.loads = changed
            return raw

        with patch.object(resources.json, "loads", native_loads), patch.object(Path, "read_text", read_then_change):
            self.assertTrue(lease.cancelled)
            self.assertEqual(len(observed), 1)
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
        self.assertEqual(owner.state_path.read_bytes(), before)
        self.assertFalse(lease.cancelled)

    def test_decoder_changed_during_clone_discards_clone_and_uses_current_decoder(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        before = owner.state_path.read_bytes()
        native_clone, native_loads = resources._clone_poll_state, json.loads
        observed = []

        def changed(raw, *arguments, **keywords):
            observed.append(1)
            value = native_loads(raw, *arguments, **keywords)
            value["leases"][lease.lease_id]["cancelled"] = True
            return value

        def clone_then_change(encoded):
            value = native_clone(encoded)
            resources.json.loads = changed
            return value

        with patch.object(resources.json, "loads", native_loads), patch.object(resources, "_clone_poll_state", clone_then_change):
            self.assertTrue(lease.cancelled)
            self.assertEqual(len(observed), 1)
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
        self.assertEqual(owner.state_path.read_bytes(), before)
        self.assertFalse(lease.cancelled)

    def test_fresh_read_error_cannot_fall_back_to_previous_successful_state(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        native_read = Path.read_text

        def fail(path, *arguments, **keywords):
            if path == owner.state_path:
                raise PermissionError("injected state read refusal")
            return native_read(path, *arguments, **keywords)

        with patch.object(Path, "read_text", fail):
            with self.assertRaises(PermissionError):
                owner.is_cancelled(lease.lease_id)
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
        self.assertFalse(lease.cancelled)

    def test_single_entry_cache_is_immutable_bounded_and_replaced_for_changed_text(self):
        owner = self.owner()
        lease = self.lease(owner)
        for revision in range(8):
            value = self.state(owner)
            value["metrics"]["test_revision"] = revision
            current = self.write(owner, value)
            self.assertFalse(lease.cancelled)
            self.assertIsNone(owner._poll_state_cache)
            self.assertEqual(owner._poll_state_pending, current.decode())
            self.assertFalse(lease.cancelled)
            memo = owner._poll_state_cache
            self.assertIs(type(memo), tuple)
            self.assertEqual(len(memo), 2)
            self.assertIs(type(memo[0]), str)
            self.assertIs(type(memo[1]), bytes)
            self.assertEqual(memo[0], current.decode())
            self.assertLessEqual(len(memo[0]), resources._POLL_CACHE_MAX_TEXT_CHARS)
            self.assertLessEqual(sum(sys.getsizeof(item) for item in memo) + sys.getsizeof(memo),
                resources._POLL_CACHE_MAX_RESIDENT_BYTES)
        owner.snapshot()
        self.assertIsNone(owner._poll_state_cache)
        self.assertIsNone(owner._poll_state_pending)

    def test_text_node_depth_and_resident_refusals_keep_ordinary_poll_semantics(self):
        for bound in ("text", "nodes", "depth", "resident"):
            with self.subTest(bound=bound):
                owner = self.owner()
                lease = self.lease(owner)
                value = self.state(owner)
                if bound == "text":
                    value["metrics"]["test_padding"] = "x" * (resources._POLL_CACHE_MAX_TEXT_CHARS + 1)
                elif bound == "nodes":
                    value["metrics"]["test_nodes"] = [0] * (resources._POLL_CACHE_MAX_NODES + 1)
                elif bound == "depth":
                    nested = 0
                    for _ in range(resources._POLL_CACHE_MAX_DEPTH + 1):
                        nested = [nested]
                    value["metrics"]["test_depth"] = nested
                self.write(owner, value)
                guard = (patch.object(resources, "_POLL_CACHE_MAX_RESIDENT_BYTES", 64)
                    if bound == "resident" else nullcontext())
                with guard, decoded_calls() as calls:
                    self.assertFalse(lease.cancelled)
                    self.assertFalse(lease.cancelled)
                    self.assertIsNone(owner._poll_state_cache)
                    self.assertIsNone(owner._poll_state_pending)
                self.assertEqual(len(calls), 2)

    def test_nonfinite_json_values_are_not_cached(self):
        owner = self.owner()
        lease = self.lease(owner)
        value = self.state(owner)
        value["metrics"]["test_nonfinite"] = math.nan
        before = self.write(owner, value)
        with decoded_calls() as calls:
            self.assertFalse(lease.cancelled)
            self.assertFalse(lease.cancelled)
        self.assertEqual(len(calls), 2)
        self.assertIsNone(owner._poll_state_cache)
        self.assertIsNone(owner._poll_state_pending)
        self.assertEqual(owner.state_path.read_bytes(), before)

    @unittest.skipUnless(hasattr(sys, "getrefcount"), "requires CPython reference counts")
    def test_changed_text_releases_evicted_memo_before_admitting_replacement(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        old_memo = owner._poll_state_cache
        self.assertIs(type(old_memo), tuple)
        # The test retains one external reference. The private scheduler slot
        # must release its reference before a replacement snapshot is built;
        # a generator-local reference would retain both admitted payloads.
        warm_references = sys.getrefcount(old_memo)
        value = self.state(owner)
        value["metrics"]["test_changed_text_lifetime"] = "replacement"
        changed = self.write(owner, value)
        self.assertNotEqual(changed.decode(), old_memo[0])
        native_snapshot = resources._poll_state_snapshot
        observed = []

        def snapshot_after_eviction(text, state):
            observed.append(sys.getrefcount(old_memo))
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
            self.assertEqual(observed[-1], warm_references - 1)
            return native_snapshot(text, state)

        with patch.object(resources, "_poll_state_snapshot", snapshot_after_eviction):
            self.assertFalse(lease.cancelled)
            self.assertEqual(observed, [])
            self.assertIsNone(owner._poll_state_cache)
            self.assertEqual(owner._poll_state_pending, changed.decode())
            self.assertEqual(sys.getrefcount(old_memo), warm_references - 1)
            self.assertFalse(lease.cancelled)
        self.assertEqual(len(observed), 1)
        self.assertEqual(sys.getrefcount(old_memo), warm_references - 1)
        self.assertIsNot(owner._poll_state_cache, old_memo)
        self.assertEqual(owner._poll_state_cache[0], changed.decode())
        self.assertFalse(lease.cancelled)

    def test_first_read_retains_only_text_second_admits_and_third_clones(self):
        owner = self.owner()
        lease = self.lease(owner)
        before = owner.state_path.read_bytes()
        native_snapshot, native_clone = resources._poll_state_snapshot, resources._clone_poll_state
        snapshots, clones = [], []

        def freeze(text, state):
            snapshots.append(text)
            self.assertIsNone(owner._poll_state_pending)
            self.assertIsNone(owner._poll_state_cache)
            return native_snapshot(text, state)

        def clone(encoded):
            clones.append(encoded)
            return native_clone(encoded)

        with patch.object(resources, "_poll_state_snapshot", freeze), \
                patch.object(resources, "_clone_poll_state", clone), decoded_calls() as calls:
            self.assertFalse(lease.cancelled)
            self.assertEqual(len(calls), 1)
            self.assertEqual(snapshots, [])
            self.assertEqual(clones, [])
            self.assertIsNone(owner._poll_state_cache)
            self.assertEqual(owner._poll_state_pending, before.decode())
            self.assertLessEqual(sys.getsizeof(owner._poll_state_pending) + 256,
                resources._POLL_CACHE_MAX_RESIDENT_BYTES)
            self.assertFalse(lease.cancelled)
            self.assertEqual(len(calls), 2)
            self.assertEqual(snapshots, [before.decode()])
            self.assertEqual(clones, [])
            self.assertIsNone(owner._poll_state_pending)
            self.assertIs(type(owner._poll_state_cache), tuple)
            self.assertFalse(lease.cancelled)
            self.assertEqual(len(calls), 2)
            self.assertEqual(len(clones), 1)
        self.assertEqual(owner.state_path.read_bytes(), before)

    def test_every_changed_poll_decodes_without_attempting_snapshot_admission(self):
        for option in (True, False):
            with self.subTest(cached_poll_state=option):
                owner = self.owner(option)
                lease = self.lease(owner)
                value = self.state(owner)
                snapshots = []
                native_snapshot = resources._poll_state_snapshot

                def freeze(text, state):
                    snapshots.append(text)
                    return native_snapshot(text, state)

                # Each changed document remains valid and differs only in
                # diagnostic metrics. Only polling invokes the observed decoder.
                with patch.object(resources, "_poll_state_snapshot", freeze), decoded_calls() as calls:
                    for revision in range(10):
                        value["metrics"]["test_revision"] = revision
                        current = self.write(owner, value)
                        self.assertFalse(lease.cancelled)
                        self.assertIsNone(owner._poll_state_cache)
                        if option:
                            self.assertEqual(owner._poll_state_pending, current.decode())
                        else:
                            self.assertIsNone(owner._poll_state_pending)
                self.assertEqual(len(calls), 10)
                self.assertEqual(snapshots, [])

    def test_whitespace_change_requires_two_fresh_reads_before_readmission(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.warm(lease)
        before = owner.state_path.read_bytes()
        changed = b" \n" + before + b"\t "
        owner.state_path.write_bytes(changed)
        with decoded_calls() as calls:
            self.assertFalse(lease.cancelled)
            self.assertIsNone(owner._poll_state_cache)
            self.assertEqual(owner._poll_state_pending, changed.decode())
            self.assertFalse(lease.cancelled)
            self.assertIsNone(owner._poll_state_pending)
            self.assertEqual(owner._poll_state_cache[0], changed.decode())
            self.assertFalse(lease.cancelled)
        self.assertEqual(len(calls), 2)
        self.assertEqual(owner.state_path.read_bytes(), changed)

    def test_pending_slot_is_cleared_by_each_authority_or_decoder_failure(self):
        for action in ("persist", "reconfigure", "blank", "missing", "parse", "read", "validation", "decoder"):
            with self.subTest(action=action):
                owner = self.owner()
                lease = self.lease(owner)
                valid = owner.state_path.read_bytes()
                self.assertFalse(lease.cancelled)
                self.assertIsNone(owner._poll_state_cache)
                self.assertEqual(owner._poll_state_pending, valid.decode())
                try:
                    if action == "persist":
                        owner.snapshot()
                    elif action == "reconfigure":
                        with owner._locked_state(persist=False, allow_reconfigure=True):
                            pass
                    elif action == "blank":
                        owner.state_path.write_bytes(b"")
                        self.assertTrue(owner.is_cancelled(lease.lease_id, missing_is_cancelled=True))
                    elif action == "missing":
                        owner.state_path.unlink()
                        self.assertTrue(owner.is_cancelled(lease.lease_id, missing_is_cancelled=True))
                    elif action == "parse":
                        owner.state_path.write_bytes(b'{"schema_version":')
                        with self.assertRaises(resources.SchedulerStateError):
                            owner.is_cancelled(lease.lease_id)
                    elif action == "read":
                        native_read = Path.read_text

                        def refuse(path, *arguments, **keywords):
                            if path == owner.state_path:
                                raise PermissionError("injected pending read refusal")
                            return native_read(path, *arguments, **keywords)

                        with patch.object(Path, "read_text", refuse), self.assertRaises(PermissionError):
                            owner.is_cancelled(lease.lease_id)
                    elif action == "validation":
                        with patch.object(owner.config, "total_memory_mb", 201), \
                                self.assertRaises(resources.ResourceConfigurationError):
                            owner.is_cancelled(lease.lease_id)
                    else:
                        native_loads = json.loads
                        with patch.object(json, "loads", lambda *args, **kwargs: native_loads(*args, **kwargs)):
                            self.assertFalse(lease.cancelled)
                    self.assertIsNone(owner._poll_state_cache)
                    self.assertIsNone(owner._poll_state_pending)
                finally:
                    owner.state_path.write_bytes(valid)

    def test_unexpected_decode_failure_clears_pending_and_admitted_slots(self):
        for failure in (MemoryError, RuntimeError):
            for stage in ("pending", "admitted"):
                with self.subTest(failure=failure.__name__, stage=stage):
                    owner = self.owner()
                    lease = self.lease(owner)
                    self.assertFalse(lease.cancelled)
                    self.assertIsNotNone(owner._poll_state_pending)
                    if stage == "admitted":
                        self.assertFalse(lease.cancelled)
                        self.assertIsNotNone(owner._poll_state_cache)
                        value = self.state(owner)
                        value["metrics"]["test_decode_failure_revision"] = 1
                        self.write(owner, value)

                    def refuse(raw):
                        raise failure("injected decode failure")

                    with patch.object(resources, "_decode_state_json", refuse), self.assertRaises(failure):
                        owner.is_cancelled(lease.lease_id)
                    self.assertIsNone(owner._poll_state_cache)
                    self.assertIsNone(owner._poll_state_pending)

    def test_snapshot_refusal_clears_pending_and_skips_the_following_attempt(self):
        owner = self.owner()
        lease = self.lease(owner)
        native_snapshot = resources._poll_state_snapshot
        snapshots = []

        def refuse(text, state):
            snapshots.append(text)
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
            self.assertIsNotNone(native_snapshot(text, state))
            return None

        with patch.object(resources, "_poll_state_snapshot", refuse), decoded_calls() as calls:
            for index in range(5):
                self.assertFalse(lease.cancelled)
                self.assertIsNone(owner._poll_state_cache)
                self.assertEqual(len(snapshots), (index + 1) // 2)
                if index % 2:
                    self.assertIsNone(owner._poll_state_pending)
                else:
                    self.assertIs(type(owner._poll_state_pending), str)
        self.assertEqual(len(calls), 5)

    def test_pending_resident_bound_counts_unicode_storage_and_fixed_overhead(self):
        owner = self.owner()
        lease = self.lease(owner)
        value = self.state(owner)
        value["metrics"]["test_unicode"] = "\U0001f642" * 100
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        owner.state_path.write_text(text, encoding="utf-8")
        self.assertLess(len(text), resources._POLL_CACHE_MAX_TEXT_CHARS)
        with patch.object(resources, "_POLL_CACHE_MAX_RESIDENT_BYTES", sys.getsizeof(text) + 255):
            self.assertFalse(lease.cancelled)
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
        with patch.object(resources, "_POLL_CACHE_MAX_RESIDENT_BYTES", sys.getsizeof(text) + 256):
            self.assertFalse(lease.cancelled)
            self.assertIsNone(owner._poll_state_cache)
            self.assertEqual(owner._poll_state_pending, text)

    def test_decoder_changed_by_validator_discards_pending_candidate_and_warm_hit(self):
        native_loads = json.loads

        def hooked(*arguments, **keywords):
            return native_loads(*arguments, **keywords)

        class ChangingScheduler(resources.GlobalResourceScheduler):
            change = False

            def _validate_state_configuration(inner, state, *, allow_reconfigure=False):
                super()._validate_state_configuration(state, allow_reconfigure=allow_reconfigure)
                if inner.change:
                    resources.json.loads = hooked

        for stage in ("pending", "admission", "hit"):
            with self.subTest(stage=stage):
                owner = self.owner(scheduler_type=ChangingScheduler)
                lease = self.lease(owner)
                if stage in ("admission", "hit"):
                    self.assertFalse(lease.cancelled)
                if stage == "hit":
                    self.assertFalse(lease.cancelled)
                owner.change = True
                try:
                    with patch.object(json, "loads", native_loads):
                        self.assertFalse(lease.cancelled)
                        self.assertIsNone(owner._poll_state_cache)
                        self.assertIsNone(owner._poll_state_pending)
                finally:
                    owner.change = False

    @unittest.skipUnless(hasattr(sys, "getrefcount"), "requires CPython reference counts")
    def test_pending_reference_is_released_before_snapshot_admission(self):
        owner = self.owner()
        lease = self.lease(owner)
        self.assertFalse(lease.cancelled)
        old_pending = owner._poll_state_pending
        self.assertIs(type(old_pending), str)
        references = sys.getrefcount(old_pending)
        native_snapshot = resources._poll_state_snapshot
        observed = []

        def after_pending_release(text, state):
            observed.append(sys.getrefcount(old_pending))
            self.assertIsNone(owner._poll_state_cache)
            self.assertIsNone(owner._poll_state_pending)
            self.assertEqual(observed[-1], references - 1)
            self.assertEqual(text, old_pending)
            self.assertIsNot(text, old_pending)
            return native_snapshot(text, state)

        with patch.object(resources, "_poll_state_snapshot", after_pending_release):
            self.assertFalse(lease.cancelled)
        self.assertEqual(len(observed), 1)
        self.assertEqual(sys.getrefcount(old_pending), references - 1)
