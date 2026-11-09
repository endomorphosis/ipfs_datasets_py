"""Independent byte/domain tests for the additive framed fingerprint utility.

Only complete pinned standard-library source leaves are loaded, under private
names.  The reference is runtime._copy followed by HEAD._fingerprint, not the
different runtime fingerprint.  Numerical/product entry points are not called.
The native owner separately pins the installed utility and this test source.
"""
from __future__ import annotations

import ast
import builtins
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import stat
import struct
import types
import unittest


_HEAD_SHA256 = "8e32341e5962c01193ec46313011b83ba67b340a8996f866e417b10179b5c021"
_RUNTIME_SHA256 = "43037fe64c58de0bcfc2072178eabe1276b4a020863e20b9498a634763b56e5a"
_LEAF_RELATIVE = Path("logic/formalization/autoencoder")
_ALLOWED_IMPORTS = frozenset(("__future__", "hashlib", "importlib", "json",
    "json.encoder", "math", "os", "pathlib", "re", "stat", "struct"))
_DEFAULT_MAXIMUM = 24 * 1024**2
_MAXIMUM = 64 * 1024**2


def _package_directory():
    # Supports both the staged test and its canonical tests/unit location.
    for parent in Path(__file__).absolute().parents:
        for relative in ("ipfs_datasets_py", "external/ipfs_datasets/ipfs_datasets_py"):
            candidate = parent / relative
            if (candidate / _LEAF_RELATIVE / "legal_compact_content_head_v1.py").is_file():
                assert candidate.resolve(strict=True) == candidate
                return candidate
    raise AssertionError("canonical source leaves were not found")


def _load_leaf(path, name, expected_sha256=None):
    """Load the entire source, never importing a package or selected fragments."""
    assert path.resolve(strict=True) == path
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
    assert 0 < before.st_size <= 131072
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert len(raw) == before.st_size
    if expected_sha256 is not None:
        assert digest == expected_sha256
    tree = ast.parse(raw, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(item.name in _ALLOWED_IMPORTS for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in _ALLOWED_IMPORTS
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    namespace = vars(builtins).copy()

    def guarded_import(import_name, globals=None, locals=None, fromlist=(), level=0):
        assert level == 0 and import_name in _ALLOWED_IMPORTS
        return builtins.__import__(import_name, globals, locals, fromlist, level)

    namespace["__import__"] = guarded_import
    module.__dict__["__builtins__"] = namespace
    exec(compile(raw, str(path), "exec"), module.__dict__)
    after = path.lstat()
    identity = lambda value: (value.st_dev, value.st_ino, value.st_mode,
        value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    assert identity(before) == identity(after)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    if expected_sha256 is not None:
        assert module._SELF_SHA == expected_sha256
        assert str(module._SELF_PATH) == str(path)
    return module


class FingerprintContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = _package_directory() / _LEAF_RELATIVE
        cls.head = _load_leaf(directory / "legal_compact_content_head_v1.py",
            "_fingerprint_test_original_head", _HEAD_SHA256)
        cls.runtime = _load_leaf(directory / "legal_compact_content_trained_runtime_v2.py",
            "_fingerprint_test_original_runtime", _RUNTIME_SHA256)
        cls.utility = _load_leaf(directory / "legal_compact_content_fingerprint_v1.py",
            "_fingerprint_test_candidate")

    def _legacy_stream(self, value, *, maximum=_DEFAULT_MAXIMUM, allow_bytes=True):
        checked = self.runtime._copy(value, maximum, allow_bytes=allow_bytes)
        reference_digest = self.head._fingerprint(checked)
        chunks = []

        class Recorder:
            def update(self, raw):
                if type(raw) is not bytes:
                    raise AssertionError("legacy emitted a non-bytes update")
                chunks.append(raw)

            def hexdigest(self):
                return hashlib.sha256(b"".join(chunks)).hexdigest()

        # Instrument only the private namespace's digest sink.  The complete
        # legacy function body/source bytes are unchanged.  Restore even on error.
        old_hashlib = self.head.hashlib
        self.head.hashlib = types.SimpleNamespace(sha256=Recorder)
        try:
            recorded_digest = self.head._fingerprint(checked)
        finally:
            self.head.hashlib = old_hashlib
        stream = b"".join(chunks)
        self.assertEqual(reference_digest, recorded_digest)
        self.assertEqual(reference_digest, hashlib.sha256(stream).hexdigest())
        return stream, reference_digest

    def _assert_parity(self, value, *, maximum=_DEFAULT_MAXIMUM, allow_bytes=True):
        stream, expected = self._legacy_stream(value, maximum=maximum, allow_bytes=allow_bytes)
        chunks = []
        result = self.utility._stream(value, chunks.append, maximum=maximum, allow_bytes=allow_bytes)
        self.assertIsNone(result)
        self.assertTrue(all(type(chunk) is bytes for chunk in chunks))
        self.assertEqual(b"".join(chunks), stream)
        observed = self.utility.fingerprint(value, maximum=maximum, allow_bytes=allow_bytes)
        self.assertIs(type(observed), str)
        self.assertRegex(observed, r"\A[0-9a-f]{64}\Z")
        self.assertEqual(observed, expected)
        self.assertEqual(hashlib.sha256(b"".join(chunks)).hexdigest(), observed)
        return stream

    def _assert_refusal(self, value, *, maximum=_DEFAULT_MAXIMUM, allow_bytes=True):
        # Invalid values are independently refused by the unchanged bounded
        # reference before the new implementation is called.  A partial private
        # sink stream on refusal is permitted and is not a valid fingerprint.
        with self.assertRaises(self.runtime.CompactContentGenerationError):
            self.runtime._copy(value, maximum, allow_bytes=allow_bytes)
        with self.assertRaises(self.utility.FingerprintError):
            self.utility.fingerprint(value, maximum=maximum, allow_bytes=allow_bytes)
        with self.assertRaises(self.utility.FingerprintError):
            self.utility._stream(value, lambda raw: None, maximum=maximum, allow_bytes=allow_bytes)

    def test_01_declared_bounds_and_exception(self):
        self.assertEqual(self.utility.DEFAULT_MAXIMUM, _DEFAULT_MAXIMUM)
        self.assertEqual(self.utility.MAXIMUM, _MAXIMUM)
        self.assertEqual(self.utility.MAX_JSON_ITEMS, 12_000_000)
        self.assertEqual(self.utility.MAX_JSON_DEPTH, 96)
        self.assertEqual(self.runtime.MAX_JSON_ITEMS, 12_000_000)
        self.assertEqual(self.runtime.MAX_JSON_DEPTH, 96)
        self.assertTrue(issubclass(self.utility.FingerprintError, ValueError))

    def test_02_handwritten_scalar_frames(self):
        examples = [(None, b"j4:null"), (True, b"j4:true"), (False, b"j5:false"),
            (0, b"j1:0"), (1.0, b"j3:1.0"), (-0.0, b"j4:-0.0"),
            ("", b'j2:""'), (b"", b"b0:"), (b"\x00\xff", b"b2:\x00\xff")]
        for value, expected in examples:
            with self.subTest(value_type=type(value).__name__, expected=expected):
                self.assertEqual(self._assert_parity(value), expected)

    def test_03_handwritten_container_frames(self):
        self.assertEqual(self._assert_parity([]), b"l0:")
        self.assertEqual(self._assert_parity({}), b"d0:")
        self.assertEqual(self._assert_parity({"b": [], "a": 1}), b'd2:j3:"a"j1:1j3:"b"l0:')
        self.assertEqual(self._assert_parity([True, "x", b"x"]), b'l3:j4:truej3:"x"b1:x')

    def test_04_exact_type_separation(self):
        groups = [[True, 1, 1.0, "1", b"1"], [False, 0, 0.0, -0.0, "0", b"0"],
            [None, "null", b"null"], [[], {}, "", b""]]
        for values in groups:
            streams = [self._assert_parity(value) for value in values]
            self.assertEqual(len(set(streams)), len(values))

    def test_05_float_extremes_subnormals_and_exponents(self):
        values = [0.0, -0.0, 5e-324, -5e-324, 2.2250738585072014e-308,
            1.7976931348623157e308, -1.7976931348623157e308, 1e-7, 1e-6,
            1e15, 1e16, 1e20, 1e21, 1.2345678901234567,
            math.nextafter(1.0, 0.0), math.nextafter(1.0, 2.0)]
        for value in values:
            with self.subTest(hex=value.hex()):
                raw = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
                self.assertEqual(self._assert_parity(value), b"j" + str(len(raw)).encode("ascii") + b":" + raw)

    def test_06_unicode_and_control_escape_frames(self):
        values = ['"\\\b\f\n\r\t', "\x01\x07\x0b\x1f", "\x7f\x80\u07ff\u0800",
            "\ud7ff\ue000\uffff", "\U00010000\U0010ffff", "café e\u0301", "\u2028\u2029"]
        for value in values:
            with self.subTest(value=value):
                self._assert_parity({value: [value, ""]})
        self.assertEqual(self._assert_parity("é"), b'j4:"\xc3\xa9"')
        self.assertEqual(self._assert_parity("\x01"), b'j8:"\\u0001"')
        self.assertEqual(self._assert_parity("\n"), b'j4:"\\n"')

    def test_07_all_dictionary_insertion_orders(self):
        pairs = [("z", 0), ("a", 1), ("é", 2), ("\U00010000", 3)]
        streams = [self._assert_parity(dict(order)) for order in itertools.permutations(pairs)]
        self.assertEqual(len(set(streams)), 1)

    def test_08_list_order_is_committed(self):
        streams = [self._assert_parity(list(order)) for order in itertools.permutations([None, True, 1])]
        self.assertEqual(len(set(streams)), 6)

    def test_09_aliases_are_values_not_cycles(self):
        child = {"numbers": [1, 2.0, -0.0], "raw": b"\x00"}
        aliased = [child, child, {"again": child}]
        detached = [{"numbers": [1, 2.0, -0.0], "raw": b"\x00"},
            {"numbers": [1, 2.0, -0.0], "raw": b"\x00"},
            {"again": {"numbers": [1, 2.0, -0.0], "raw": b"\x00"}}]
        self.assertEqual(self._assert_parity(aliased), self._assert_parity(detached))
        self.assertIs(aliased[0], child)
        self.assertIs(aliased[1], child)

    def test_10_mutation_changes_and_restoration_recovers_commitment(self):
        value = {"nested": [1, -0.0], "label": "original"}
        original = self._assert_parity(value)
        value["nested"][1] = 0.0
        changed = self._assert_parity(value)
        self.assertNotEqual(changed, original)
        value["nested"][1] = -0.0
        self.assertEqual(self._assert_parity(value), original)

    def test_11_deterministic_random_corpus(self):
        rng = random.Random(20261019)
        alphabet = "ab\"\\\n\t\x01é\u0800\U0001f680"
        def scalar():
            kind = rng.randrange(7)
            if kind == 0:
                return None
            if kind == 1:
                return bool(rng.randrange(2))
            if kind == 2:
                return rng.randrange(-(1 << 63) + 1, 1 << 63)
            if kind == 3:
                while True:
                    value = struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0]
                    if math.isfinite(value):
                        return value
            if kind == 4:
                return "".join(rng.choice(alphabet) for _ in range(rng.randrange(9)))
            if kind == 5:
                return bytes(rng.randrange(256) for _ in range(rng.randrange(9)))
            return -0.0
        def tree(depth):
            if depth == 0 or rng.randrange(3) == 0:
                return scalar()
            if rng.randrange(2):
                return [tree(depth - 1) for _ in range(rng.randrange(5))]
            return {str(index) + rng.choice(alphabet): tree(depth - 1)
                    for index in range(rng.randrange(5))}
        for index in range(128):
            with self.subTest(index=index):
                self._assert_parity(tree(4))

    def test_12_plain_json_byte_boundaries(self):
        # Whole canonical JSON length independently specifies the runtime copy
        # budget for these byte-free fixtures; fingerprint framing is additional.
        values = [None, False, 0, -123, -0.0, "", "a", "é", "\n", "\x01",
            [], {}, [0], {"": 0}, {"é": [True, "\n", -0.0]}]
        for value in values:
            maximum = len(json.dumps(value, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False).encode("utf-8"))
            with self.subTest(value=value, maximum=maximum):
                self._assert_parity(value, maximum=maximum, allow_bytes=False)
                self._assert_refusal(value, maximum=maximum - 1, allow_bytes=False)

    def test_13_bytes_charge_raw_payload_not_framing(self):
        self.assertEqual(self._assert_parity(b"", maximum=0), b"b0:")
        self.assertEqual(self._assert_parity(b"abc", maximum=3), b"b3:abc")
        self._assert_refusal(b"abc", maximum=2)
        self._assert_parity([b"ab", b"c"], maximum=6)  # brackets2 + comma1 + payload3
        self._assert_refusal([b"ab", b"c"], maximum=5)
        self._assert_parity({"x": b"abc"}, maximum=9)  # braces2 + key3 + colon1 + payload3
        self._assert_refusal({"x": b"abc"}, maximum=8)

    def test_14_zero_budget_has_only_empty_bytes(self):
        self._assert_parity(b"", maximum=0)
        for value in (None, False, 0, 0.0, "", [], {}, b"x"):
            with self.subTest(value_type=type(value).__name__):
                self._assert_refusal(value, maximum=0)

    def test_15_default_and_largest_valid_budget(self):
        value = {"x": [1, -0.0, b"payload"]}
        self.assertEqual(self.utility.fingerprint(value),
            self.utility.fingerprint(value, maximum=_DEFAULT_MAXIMUM, allow_bytes=True))
        self._assert_parity(value, maximum=_MAXIMUM)

    def test_16_invalid_public_budget_arguments(self):
        for maximum in (-1, _MAXIMUM + 1, True, False, 0.0, 24.0, None, "1024"):
            with self.subTest(maximum=maximum):
                with self.assertRaises(self.utility.FingerprintError):
                    self.utility.fingerprint(None, maximum=maximum)
                with self.assertRaises(self.utility.FingerprintError):
                    self.utility._stream(None, lambda raw: None, maximum=maximum)

    def test_17_strict_allow_bytes_flag(self):
        self._assert_parity({"x": [1, True, None]}, allow_bytes=False)
        for allow in (0, 1, None, "yes", [], {}):
            with self.subTest(allow_type=type(allow).__name__):
                with self.assertRaises(self.utility.FingerprintError):
                    self.utility.fingerprint(None, allow_bytes=allow)
                with self.assertRaises(self.utility.FingerprintError):
                    self.utility._stream(None, lambda raw: None, allow_bytes=allow)

    def test_18_bytes_disabled_at_every_depth(self):
        for value in (b"", b"raw", [b""], {"x": [b"raw"]}):
            with self.subTest(value_type=type(value).__name__):
                self._assert_refusal(value, allow_bytes=False)

    def test_19_nul_surrogates_refused_in_keys_and_values(self):
        for text in ("\x00", "before\x00after", "\ud800", "\udfff", "\ud83d\ude80"):
            for value in (text, [text], {text: 0}, {"safe": text}):
                with self.subTest(text_ascii=ascii(text), value_type=type(value).__name__):
                    self._assert_refusal(value)

    def test_20_nonfinite_numbers_refused(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            self._assert_refusal(value)
            self._assert_refusal({"nested": [value]})

    def test_21_exclusive_integer_endpoints(self):
        self._assert_parity(-(1 << 63) + 1)
        self._assert_parity((1 << 63) - 1)
        for value in (-(1 << 63), (1 << 63), -(1 << 100), 1 << 100):
            with self.subTest(value=value):
                self._assert_refusal(value)
                self._assert_refusal([value])

    def test_22_nonstring_dictionary_keys_refused(self):
        for key in (None, False, 1, 1.5, b"x", ("x",)):
            with self.subTest(key_type=type(key).__name__):
                self._assert_refusal({key: "value"})

    def test_23_plain_type_subclasses_refused_without_conversion(self):
        class String(str):
            pass
        class Integer(int):
            pass
        class Float(float):
            pass
        class Bytes(bytes):
            pass
        class List(list):
            pass
        class Dict(dict):
            pass
        for value in (String("x"), Integer(1), Float(1.0), Bytes(b"x"), List([1]), Dict(x=1)):
            with self.subTest(value_type=type(value).__name__):
                self._assert_refusal(value)
                self._assert_refusal([value])
        self._assert_refusal({String("x"): 1})

    def test_24_custom_objects_refused_without_hooks(self):
        calls = []
        class Hostile:
            def __iter__(self):
                calls.append("iter")
                raise AssertionError("must not iterate arbitrary objects")
            def __str__(self):
                calls.append("str")
                raise AssertionError("must not stringify arbitrary objects")
            def __repr__(self):
                calls.append("repr")
                raise AssertionError("must not repr arbitrary objects")
            def __len__(self):
                calls.append("len")
                raise AssertionError("must not size arbitrary objects")
        value = Hostile()
        self._assert_refusal(value)
        self._assert_refusal({"nested": value})
        self.assertEqual(calls, [])

    def test_25_other_container_types_refused(self):
        for value in ((1, 2), {1, 2}, frozenset((1, 2)), bytearray(b"x"), memoryview(b"x")):
            with self.subTest(value_type=type(value).__name__):
                self._assert_refusal(value)

    def test_26_direct_and_indirect_cycles_refused(self):
        loop_list = []
        loop_list.append(loop_list)
        loop_dict = {}
        loop_dict["self"] = loop_dict
        left, right = [], {}
        left.append(right)
        right["back"] = left
        for value in (loop_list, loop_dict, left):
            self._assert_refusal(value)

    def test_27_actual_depth_boundary_in_lists(self):
        value = 0
        for _ in range(96):
            value = [value]
        self._assert_parity(value)
        self._assert_refusal([value])

    def test_28_actual_depth_boundary_in_dictionary_values(self):
        value = 0
        for _ in range(96):
            value = {"k": value}
        self._assert_parity(value)
        self._assert_refusal({"k": value})

    def test_29_actual_item_limit_early_container_refusal(self):
        # One ~96 MB reference vector, no twelve-million-element traversal/copy.
        # The root consumes one item; len == MAX_JSON_ITEMS then exceeds the
        # remaining item allowance before any child is visited in either owner.
        value = [None] * 12_000_000
        self._assert_refusal(value, maximum=_MAXIMUM)

    def test_30_scaled_item_counter_counts_dictionary_keys_and_aliases(self):
        # A separately labeled small-counter check supplements the actual limit
        # refusal.  Only isolated namespace constants change, restored finally.
        prior_runtime, prior_utility = self.runtime.MAX_JSON_ITEMS, self.utility.MAX_JSON_ITEMS
        self.runtime.MAX_JSON_ITEMS = self.utility.MAX_JSON_ITEMS = 5
        try:
            self._assert_parity({"a": 0, "b": 1})  # root + two keys + two values
            self._assert_refusal({"a": 0, "b": [1]})
            shared = [0]
            self._assert_parity([shared, shared])  # repeated references are visited twice
            self._assert_refusal([shared, shared, shared])
        finally:
            self.runtime.MAX_JSON_ITEMS, self.utility.MAX_JSON_ITEMS = prior_runtime, prior_utility
        self.assertEqual(self.runtime.MAX_JSON_ITEMS, 12_000_000)
        self.assertEqual(self.utility.MAX_JSON_ITEMS, 12_000_000)

    def test_31_python_string_encoder_fallback_parity(self):
        values = ["", "plain", '"\\\b\f\n\r\t', "\x01\x1f", "é\u0800\uffff",
            "\U00010000\U0010ffff", "e\u0301\u2028\u2029"]
        prior = self.utility.encode_basestring
        self.utility.encode_basestring = json.encoder.py_encode_basestring
        try:
            for value in values:
                with self.subTest(value=value):
                    self._assert_parity({value: [value, ""]})
            self._assert_refusal("\x00")
            self._assert_refusal("\ud800")
            self._assert_parity("é", maximum=4)
            self._assert_refusal("é", maximum=3)
        finally:
            self.utility.encode_basestring = prior
        self.assertIs(self.utility.encode_basestring, prior)

    def test_32_private_sink_refuses_noncallables(self):
        for sink in (None, 0, b"", [], {}):
            with self.subTest(sink_type=type(sink).__name__):
                with self.assertRaises(self.utility.FingerprintError):
                    self.utility._stream(None, sink)


if __name__ == "__main__":
    unittest.main()
