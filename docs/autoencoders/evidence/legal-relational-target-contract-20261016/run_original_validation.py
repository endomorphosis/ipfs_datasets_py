"""Call unchanged native validation and retain its actual exception observations.

This parent-side receipt grants no admission and changes no native function.
Original child startup, custody, limits and durable closeout remain authoritative.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import types


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--expected-request-sha256", required=True)
    parser.add_argument("--resource-ledger", required=True)
    parser.add_argument("--failure-report", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    path = root / "scripts/ops/legal_ir/run_owned_validation.py"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != "2d7a250e4c5237d24bf1b9328b059a71854d613a568de55f08c83b8e045e41b4":
        raise ValueError("original validation launcher changed")
    module = types.ModuleType("_unchanged_native_validation")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    try:
        return module.main(["--request", args.request,
            "--expected-request-sha256", args.expected_request_sha256,
            "--resource-ledger", args.resource_ledger])
    except BaseException as error:
        report = {"schema": "unchanged-native-validation-exception/v1",
            "error_type": type(error).__name__,
            "admission_observation": getattr(error, "admission_observation", None),
            "proof_refusal_observation": getattr(error, "proof_refusal_observation", None),
            "timeout_decision": getattr(error, "timeout_decision", None),
            "capacity_observation": getattr(error, "_capacity_observation", None),
            "observations_are_detached_not_capabilities": True}
        destination = Path(args.failure_report)
        private = Path("/home/barberb/lift_coding/artifacts/legal-relational-target-contract-20261016")
        if not destination.is_absolute() or private not in destination.parents or destination.parent.resolve() != destination.parent:
            raise ValueError("direct private parent receipt required") from error
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        raise


if __name__ == "__main__":
    raise SystemExit(main())
