"""Modern Isabelle theory invocation; discovery never downloads or builds heaps."""
from __future__ import annotations

import re

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_']*\Z")
CHECK_MARKER = "IPFS_ISABELLE_KERNEL_CHECKED"


def theory_name(source: str) -> str:
    match = re.search(r"^\s*theory\s+([A-Za-z_][A-Za-z0-9_']*)\s", source, re.MULTILINE)
    if not match:
        raise ValueError("requires a simple Isabelle theory header")
    return match.group(1)


def theory_command(executable: str, name: str, directory: str, *, capture: bool = False) -> list[str]:
    if not _NAME.fullmatch(name):
        raise ValueError("invalid Isabelle theory name")
    return [executable, "process_theories", "-D", directory, "-O", "-l", "HOL",
            "-o", "threads=1", "-o", "parallel_proofs=0",
            "-o", f"quick_and_dirty={'true' if capture else 'false'}", name]


def add_kernel_audit(source: str, declaration: str) -> str:
    """Require the named theorem and reject any oracle dependency.

    Output is emitted only after Isabelle has elaborated the exact theorem.
    The audit is inserted inside the theory, after the reconstructed proof.
    """
    if not _NAME.fullmatch(declaration):
        raise ValueError("kernel audit requires a simple theorem identifier")
    closing = list(re.finditer(r"\bend\s*\Z", source))
    if not closing:
        raise ValueError("Isabelle theory must end with end")
    audit = ('\nML \\<open>\n'
             f'val checked = @{{thm {declaration}}};\n'
             'val _ = if null (Thm_Deps.all_oracles [checked]) then ()\n'
             '  else error "Untrusted oracle dependency";\n'
             f'writeln "{CHECK_MARKER}";\n'
             '\\<close>\n')
    index = closing[-1].start()
    return source[:index] + audit + source[index:]
