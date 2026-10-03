"""Bounded paired timing; pure identity microbenchmark, no model or benchmark scores."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import time
from multiformats import multihash
from ipfs_datasets_py.logic.software_contracts import content

root = Path(__file__).resolve().parent
before = root.parent / "content.before.py"
spec = importlib.util.spec_from_file_location("historical_content", before)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
inputs = [(f"def offset_{n}(value):\n    return value + {n}\n".encode(),
           {"source_unit": n, "effect": ["return", "add", "value", n],
            "scope": "integer-offset-development-fixture"}) for n in range(16)]
expected = [(old.cid_for_bytes(body), old.cid_for_obj(obj)) for body, obj in inputs]
source_paths = {"uncached": before, "memoized": Path(content.__file__)}
pins = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in source_paths.items()}
iterations = 512
samples = []
original_digest = multihash.digest
counts = {"calls": 0, "bytes": 0}
def digest(body, *args, **kwargs):
    counts["calls"] += 1
    counts["bytes"] += len(body)
    return original_digest(body, *args, **kwargs)
multihash.digest = digest
try:
    for trial in range(4):
        order = [("uncached", old), ("memoized", content)]
        if trial % 2:
            order.reverse()
        for name, owner in order:
            # Declare warm state explicitly; every later payload is still hashed.
            for (body, obj), (source, structured) in zip(inputs, expected):
                assert owner.decode_and_recompute_source(source, body) == source
                assert owner.decode_and_recompute_structured(structured, obj) == structured
            counts.update(calls=0, bytes=0)
            cpu = time.process_time()
            wall = time.perf_counter()
            for index in range(iterations):
                body, obj = inputs[index % len(inputs)]
                source, structured = expected[index % len(inputs)]
                assert owner.decode_and_recompute_source(source, body) == source
                assert owner.decode_and_recompute_structured(structured, obj) == structured
            elapsed = time.perf_counter() - wall
            cpu_elapsed = time.process_time() - cpu
            assert counts["calls"] == iterations * 2
            samples.append({"pair": trial, "mode": name, "iterations": iterations,
                "verified_body_reads": iterations * 2, "digest_calls": counts["calls"],
                "hashed_bytes": counts["bytes"], "wall_seconds": elapsed,
                "process_cpu_seconds": cpu_elapsed,
                "verified_reads_per_second": iterations * 2 / elapsed})
            (root / "timing-partial.json").write_text(json.dumps(samples, indent=2) + "\n")
finally:
    multihash.digest = original_digest
assert pins == {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in source_paths.items()}
result = {"schema": "canonical-cid-paired-microbenchmark@1", "scope": "warm16identityfixture; no repository scan, proof checker, model or official benchmark workload",
    "python": sys.version, "source_sha256": pins, "source_drift": False,
    "fixture_count": len(inputs), "per_pair_iterations": iterations,
    "all_outputs_equal": True, "all_body_bytes_rehashed": True, "raw_samples": samples,
    "memo_encode": content._memo_encode_digest.cache_info()._asdict(),
    "memo_validate": content._memo_validate_cid.cache_info()._asdict(),
    "limitations": ["Small warm repeated identity set; no cold scan or end-to-end speedup claim.",
        "Host runs other work; paired wall and process CPU times are retained separately."]}
(root / "timings.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
