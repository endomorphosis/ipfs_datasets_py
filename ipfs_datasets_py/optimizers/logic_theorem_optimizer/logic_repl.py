"""Interactive REPL for Logic Theorem Optimizer CLI.

Provides a lightweight command loop with command history and readline-based
tab completion where available.
"""

from __future__ import annotations

import cmd
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List


try:
    import readline

    HAS_READLINE = True
except ImportError:  # pragma: no cover
    HAS_READLINE = False


class LogicREPL(cmd.Cmd):
    """Interactive REPL that forwards commands to ``LogicOptimizerCLI``."""

    intro = (
        "\n"
        "╔════════════════════════════════════════════════════════════════════╗\n"
        "║          Logic Theorem Optimizer Interactive REPL                 ║\n"
        "╠════════════════════════════════════════════════════════════════════╣\n"
        "║  Type 'help' for available commands                               ║\n"
        "║  Type 'help <command>' for command-specific help                  ║\n"
        "║  Type 'exit' or Ctrl+D to quit                                    ║\n"
        "╚════════════════════════════════════════════════════════════════════╝\n"
    )
    prompt = "logic> "
    LOGIC_COMMANDS: Dict[str, str] = {
        "extract": "Extract logic from source text",
        "prove": "Prove a theorem with configured provers",
        "validate": "Validate logical consistency",
        "optimize": "Run optimizer cycles",
        "status": "Show optimizer capabilities",
    }

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import LogicOptimizerCLI

        self.cli = LogicOptimizerCLI()
        self.session_state: Dict[str, Any] = {
            "command_count": 0,
            "error_count": 0,
        }
        self.setup_history()
        self.setup_completion()

    def setup_history(self) -> None:
        if not HAS_READLINE:
            return
        history_file = Path.home() / ".logic_optimizer_repl_history"
        readline.set_history_length(1000)
        if history_file.exists():
            try:
                readline.read_history_file(str(history_file))
            except (FileNotFoundError, OSError):
                pass

        import atexit

        def _save() -> None:
            try:
                readline.write_history_file(str(history_file))
            except OSError:
                pass

        atexit.register(_save)

    def setup_completion(self) -> None:
        if not HAS_READLINE:
            return
        readline.set_completer(self.complete)
        readline.parse_and_bind("tab: complete")

    def complete_help(self, text: str, line: str, begidx: int, endidx: int) -> List[str]:
        return [name for name in self.LOGIC_COMMANDS if name.startswith(text)]

    def do_help(self, arg: str) -> None:
        if not arg:
            print("\nAvailable commands:")
            for name, desc in self.LOGIC_COMMANDS.items():
                print(f"  {name:10} - {desc}")
            print("  history    - Show command history")
            print("  exit       - Exit REPL\n")
            return
        if arg in self.LOGIC_COMMANDS:
            self._invoke_logic_command([arg, "--help"])
            return
        print(f"Unknown command: {arg}")

    def do_history(self, arg: str) -> None:
        if not HAS_READLINE:
            print("History unavailable (readline not installed)")
            return
        try:
            limit = int(arg) if arg else None
        except ValueError:
            print(f"Invalid history limit: {arg}")
            return
        length = readline.get_current_history_length()
        start = max(1, length - limit + 1) if limit else 1
        for i in range(start, length + 1):
            print(f"  {i:4d}  {readline.get_history_item(i)}")

    def do_clear(self, arg: str) -> None:
        os.system("clear" if os.name != "nt" else "cls")

    def do_exit(self, arg: str) -> bool:
        print("\nGoodbye!")
        return True

    def do_quit(self, arg: str) -> bool:
        return self.do_exit(arg)

    def emptyline(self) -> None:
        pass

    def precmd(self, line: str) -> str:
        if line.strip() == "?":
            return "help"
        return line

    def default(self, line: str) -> None:
        try:
            argv = shlex.split(line)
        except ValueError as e:
            print(f"Error parsing command: {e}")
            return
        if not argv:
            return
        command = argv[0]
        if command in self.LOGIC_COMMANDS:
            self._invoke_logic_command(argv)
        else:
            print(f"Unknown command: {command}")
            print("Type 'help' for available commands")

    def _invoke_logic_command(self, argv: List[str]) -> None:
        self.session_state["command_count"] += 1
        exit_code = self.cli.run(argv)
        if exit_code != 0:
            self.session_state["error_count"] += 1
            if exit_code != 130:
                print(f"Command exited with code {exit_code}")


def main() -> int:
    """Entry point for logic theorem REPL."""
    try:
        repl = LogicREPL()
        repl.cmdloop()
        return 0
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 130
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
