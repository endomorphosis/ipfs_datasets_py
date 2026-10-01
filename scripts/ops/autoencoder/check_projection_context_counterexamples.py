#!/usr/bin/env python3
"""Build explicit finite context countermodels with installed Lake, offline.

These authored models explain why missing clock/scope/event context matters.
They do not resolve the default Legal/UI source interpretations, exercise the
production translators, train a model, or issue a qualification/admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import traceback


SCHEMA = "projection-context-counterexamples/v1"
FALSE = {"admitted": False, "qualified": False, "source_semantics_verified": False,
         "source_interpretation_selected": False, "training_executed": False,
         "production_translator_executed": False, "constitution_formalized": False}

LEGAL = """-- Authored finite countermodels, not an interpretation of any legal span.
set_option autoImplicit false
namespace LegalIR

-- Explicit toy clock: discrete natural ticks with both interval endpoints included.
def withinDeadline (origin duration : Nat) (event : Nat → Bool) : Bool :=
  (List.range (duration + 1)).any (fun delta => event (origin + delta))

def publishedAtSix (tick : Nat) : Bool := tick == 6

theorem deadlineFromZero : withinDeadline 0 10 publishedAtSix = true := by decide
theorem deadlineFromSeven : withinDeadline 7 10 publishedAtSix = false := by decide
theorem deadlineOriginChangesVerdict :
    withinDeadline 0 10 publishedAtSix ≠ withinDeadline 7 10 publishedAtSix := by decide

-- Two explicit ideal worlds; no assumption identifies either with actual behavior.
def idealWorlds : List Nat := [0, 1]
def obligated (claim : Nat → Bool) : Bool := idealWorlds.all claim
def idealPublication (world tick : Nat) : Bool :=
  (world == 0 && tick == 2) || (world == 1 && tick == 5)
def actualPublication (_tick : Nat) : Bool := false

theorem idealDeadlineObligation :
    obligated (fun world => withinDeadline 0 10 (idealPublication world)) = true := by decide
theorem actualDeadlineMissed : withinDeadline 0 10 actualPublication = false := by decide
theorem obligationDoesNotEstablishActualPublication :
    obligated (fun world => withinDeadline 0 10 (idealPublication world)) ≠
      withinDeadline 0 10 actualPublication := by decide

-- O(F p) quantifies world then time; F(O p) demands one shared publication tick.
theorem everyIdealWorldEventuallyPublishes :
    obligated (fun world => withinDeadline 0 10 (idealPublication world)) = true := by decide
theorem noTickHasPublicationInEveryIdealWorld :
    withinDeadline 0 10 (fun tick => obligated (fun world => idealPublication world tick)) = false := by decide
theorem modalityOrderChangesMeaning :
    obligated (fun world => withinDeadline 0 10 (idealPublication world)) ≠
      withinDeadline 0 10 (fun tick => obligated (fun world => idealPublication world tick)) := by decide

end LegalIR
"""

LEGAL_FALSE = """
namespace LegalIR
-- Deliberately false: changing the origin can change the same ten-tick verdict.
theorem falseOriginIndependence :
    withinDeadline 0 10 publishedAtSix = withinDeadline 7 10 publishedAtSix := by decide
end LegalIR
"""

UI = """-- Authored finite event-witness models, not a deployed confirmation policy.
set_option autoImplicit false
namespace UIUXIR

structure Event where
  kind : String
  action : String
  request : String
  token : String
  tick : Nat

-- This intentionally small predicate only asks whether the supplied prefix has
-- a matching, strictly earlier, fresh confirmation. It does not implement
-- cancellation, token consumption, event authenticity, or lifetime enforcement.
def hasFreshConfirmation (history : List Event) (invocation : Event) (maxAge : Nat) : Bool :=
  history.any (fun event =>
    event.kind == "confirm" && event.action == invocation.action &&
    event.request == invocation.request && event.token == invocation.token &&
    decide (event.tick < invocation.tick) && decide (invocation.tick - event.tick ≤ maxAge))

def confirmation : Event := ⟨"confirm", "publish", "request:1", "token:1", 1⟩
def invocation : Event := ⟨"invoke", "publish", "request:1", "token:1", 8⟩
def wrongRequest : Event := ⟨"confirm", "publish", "request:2", "token:1", 1⟩

theorem fiveTickPolicyHasNoFreshWitness :
    hasFreshConfirmation [confirmation] invocation 5 = false := by decide
theorem tenTickPolicyHasFreshWitness :
    hasFreshConfirmation [confirmation] invocation 10 = true := by decide
theorem suppliedFreshnessPolicyChangesVerdict :
    hasFreshConfirmation [confirmation] invocation 5 ≠
      hasFreshConfirmation [confirmation] invocation 10 := by decide
theorem absentPrefixHasNoObservedWitness :
    hasFreshConfirmation [] invocation 10 = false := by decide
theorem retrievingEarlierEvidenceChangesWitnessResult :
    hasFreshConfirmation [] invocation 10 ≠
      hasFreshConfirmation [confirmation] invocation 10 := by decide
theorem wrongRequestIsNotAWitness :
    hasFreshConfirmation [wrongRequest] invocation 10 = false := by decide

-- No witness in a truncated prefix does not assert no confirmation ever occurred.
end UIUXIR
"""

UI_FALSE = """
namespace UIUXIR
-- Deliberately false: these two authored freshness policies disagree.
theorem falseFreshnessIndependence :
    hasFreshConfirmation [confirmation] invocation 5 =
      hasFreshConfirmation [confirmation] invocation 10 := by decide
end UIUXIR
"""


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def execute(command, directory, environment, label, timeout=60):
    """Run one bounded process group; preserve the exact stdout/stderr bytes."""
    started = time.monotonic()
    with (directory / (label + ".stdout")).open("wb") as out, (directory / (label + ".stderr")).open("wb") as err:
        process = subprocess.Popen(command, cwd=directory, env=environment,
                                   stdout=out, stderr=err, start_new_session=True)
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    result = {"command": list(command), "cwd": str(directory), "returncode": process.returncode,
              "timed_out": timed_out, "wall_seconds": time.monotonic() - started,
              "stdout": label + ".stdout", "stderr": label + ".stderr",
              "stdout_sha256": sha(directory / (label + ".stdout")),
              "stderr_sha256": sha(directory / (label + ".stderr"))}
    write_json(directory / (label + ".json"), result)
    return result


def build_case(output, lake, environment, toolchain, library, source, false_claim):
    directory = output / (library + ("-false-claim" if false_claim else "-countermodels"))
    directory.mkdir()
    files = {"lakefile.toml": 'name = "context_countermodels_' + library.lower() + '"\n'
             'version = "0.1.0"\n\n[[lean_lib]]\nname = "' + library + '"\n',
             "lean-toolchain": toolchain + "\n", library + ".lean": source}
    for name, content in files.items():
        (directory / name).write_text(content)
    result = execute([str(lake), "build", library], directory, environment, "lake-build")
    result.update(library=library, input_files_sha256={name: sha(directory / name) for name in files},
                  deliberately_false_claim=false_claim, actual_lake_build=True, **FALSE)
    diagnostic = ((directory / "lake-build.stdout").read_text(errors="replace") +
                  (directory / "lake-build.stderr").read_text(errors="replace"))
    # The positive project must already pass. A negative result counts only if
    # Lean identifies the appended decide proof as false, not a timeout/tool error.
    expected = (result["returncode"] != 0 and
                re.search(r"Tactic [`']decide[`'] proved that the proposition[\s\S]*?is false", diagnostic) is not None
                ) if false_claim else result["returncode"] == 0
    result["expected_outcome_observed"] = expected and not result["timed_out"]
    write_json(directory / "receipt.json", result)
    return result


def run(output, lake):
    started = time.monotonic()
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    runner = Path(__file__).resolve()
    (output / runner.name).write_bytes(runner.read_bytes())
    native_lake = Path(lake).resolve(strict=True)
    native_lean = native_lake.with_name("lean")
    # Require real installed Linux binaries, excluding an Elan downloader shim.
    for executable in (native_lake, native_lean):
        if (executable.parent.name != "bin" or executable.parent.parent.name == ".elan"
                or not os.access(executable, os.X_OK)):
            raise ValueError("installed native Lake and sibling Lean binaries required")
        with executable.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                raise ValueError("native Linux executable required; no wrappers or downloader shims")
    before_hashes = {str(path): sha(path) for path in (native_lake, native_lean)}
    environment = {key: os.environ[key] for key in ("HOME", "LANG", "TMPDIR") if key in os.environ}
    environment.update(PATH=str(native_lake.parent) + os.pathsep + os.defpath,
                       LEAN_SYSROOT=str(native_lake.parent.parent))
    probe = execute([str(native_lake), "--version"], output, environment, "lake-version", timeout=5)
    version = (output / "lake-version.stdout").read_text()
    match = re.search(r"Lean version (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)", version)
    if probe["returncode"] or probe["timed_out"] or not match:
        raise ValueError("installed Lake version probe failed")
    toolchain = "leanprover/lean4:v" + match.group(1)
    environment["ELAN_TOOLCHAIN"] = str(native_lake.parent.parent)
    results = []
    for library, source, false_claim in (("LegalIR", LEGAL, LEGAL_FALSE), ("UIUXIR", UI, UI_FALSE)):
        positive = build_case(output, native_lake, environment, toolchain, library, source, False)
        results.append(positive)
        if positive["expected_outcome_observed"]:
            results.append(build_case(output, native_lake, environment, toolchain,
                                      library, source + false_claim, True))
    after_hashes = {path: sha(path) for path in before_hashes}
    summary = {"schema": SCHEMA, "scope": "explicitly authored finite context countermodels",
               "claims_checked": {"LegalIR": 9, "UIUXIR": 6},
               "positive_claims_executed": sum((9 if row["library"] == "LegalIR" else 6)
                   for row in results if not row["deliberately_false_claim"] and row["expected_outcome_observed"]),
               "results": results, "toolchain": toolchain, "tool_hashes": before_hashes,
               "tool_hashes_unchanged": before_hashes == after_hashes,
               "runner_sha256": sha(output / runner.name), "wall_seconds": time.monotonic() - started,
               "all_expected_outcomes_observed": len(results) == 4 and before_hashes == after_hashes
                   and all(row["expected_outcome_observed"] for row in results),
               "actual_lake_build_count": len(results), "model_dependencies": [], "download_calls": 0,
               "limitations": ["No source span is assigned these interpretations.",
                   "The toy clock does not resolve calendar days, business days, or a legal trigger.",
                   "The ideal-world model is illustrative, not a selected deontic axiom system.",
                   "UI checks only witnesses in supplied history, not full confirmation enforcement.",
                   "Absence from a truncated prefix is not proof of absence from real history.",
                   "These finite models do not exercise production projection emitters or training gates."], **FALSE}
    write_json(output / "summary.json", summary)
    print(json.dumps({"output": str(output), "all_expected_outcomes_observed": summary["all_expected_outcomes_observed"],
                      "actual_lake_build_count": len(results), "wall_seconds": summary["wall_seconds"]}), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lake", required=True, help="Installed native Linux Lake executable; no Elan shim")
    parser.add_argument("--output", required=True, help="Fresh output directory for source and exact tool receipts")
    args = parser.parse_args()
    fresh = not Path(args.output).exists()
    try:
        summary = run(args.output, args.lake)
    except Exception:
        if fresh and Path(args.output).is_dir():
            (Path(args.output) / "failure.txt").write_text(traceback.format_exc())
        raise
    raise SystemExit(0 if summary["all_expected_outcomes_observed"] else 1)
