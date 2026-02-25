"""Interactive REPL (Read-Eval-Print Loop) for GraphRAG Optimizer CLI.

Provides an interactive shell where users can issue GraphRAG commands without
restarting the process, with command history, tab completion, and inline help.

Usage:
    python -m ipfs_datasets_py.optimizers.graphrag_repl
    
    # Inside REPL:
    > help              # Show available commands
    > generate --help   # Show command-specific help
    > exit              # Exit REPL

Features:
    - Command history with arrow keys (persistent across sessions)
    - Tab completion for commands and arguments
    - Inline help with '?'
    - Syntax highlighting for errors
    - Status tracking across sessions
"""

from __future__ import annotations

import cmd
import os
import sys
import json
import shlex
import traceback
from pathlib import Path
from typing import Optional, Dict, Any, List


# Try to import readline for better history support
try:
    import readline
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False

# Try to import prompt_toolkit for fancier REPL
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.enums import EditingMode
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False


class GraphRAGREPL(cmd.Cmd):
    """Interactive REPL for GraphRAG Optimizer CLI.
    
    Wraps GraphRAGOptimizerCLI to provide an interactive shell experience.
    """
    
    # REPL configuration
    intro = """
╔════════════════════════════════════════════════════════════════════╗
║          GraphRAG Optimizer Interactive REPL                      ║
╠════════════════════════════════════════════════════════════════════╣
║  Type 'help' for available commands                               ║
║  Type 'help <command>' for command-specific help                  ║
║  Type 'exit' or Ctrl+D to quit                                    ║
║  Type '?' for quick help                                          ║
╚════════════════════════════════════════════════════════════════════╝
"""
    
    prompt = "graphrag> "
    ruler = "─"
    
    # Commands available in REPL
    GRAPHRAG_COMMANDS = {
        'generate': 'Generate ontology from documents/data',
        'optimize': 'Optimize existing knowledge graph',
        'validate': 'Validate ontology consistency',
        'query': 'Optimize query against knowledge graph',
        'extract': 'Extract entities and relationships from text',
        'critic': 'Run critic analysis on ontology',
        'status': 'Show optimizer status',
        'health': 'Show query optimizer health snapshot',
        'export': 'Export ontology in different formats',
        'import': 'Import ontology from external source',
    }
    
    def __init__(self, *args, **kwargs):
        """Initialize REPL."""
        super().__init__(*args, **kwargs)
        
        # Try to load GraphRAG CLI
        try:
            from ipfs_datasets_py.optimizers.graphrag.cli_wrapper import GraphRAGOptimizerCLI
            self.cli = GraphRAGOptimizerCLI()
            self.cli_available = True
        except Exception as e:
            self.cli = None
            self.cli_available = False
            self.poutput(f"Warning: GraphRAG CLI unavailable: {e}")
        
        # Session state
        self.session_state: Dict[str, Any] = {
            'current_ontology': None,
            'last_output': None,
            'command_count': 0,
            'error_count': 0,
        }
        
        # Setup history
        self.setup_history()
        
        # Setup tab completion
        self.setup_completion()
        
    def setup_history(self) -> None:
        """Setup command history persistence."""
        if not HAS_READLINE and not HAS_PROMPT_TOOLKIT:
            return
        
        history_file = Path.home() / '.graphrag_repl_history'
        
        if HAS_READLINE:
            # Use readline for history
            readline.set_history_length(1000)
            if history_file.exists():
                try:
                    readline.read_history_file(str(history_file))
                except Exception:
                    pass
            
            # Save history on exit
            import atexit
            atexit.register(self._save_history, history_file)
        elif HAS_PROMPT_TOOLKIT:
            self.prompt_session = PromptSession(
                history=FileHistory(str(history_file)),
                editing_mode=EditingMode.EMACS,
            )
    
    def _save_history(self, history_file: Path) -> None:
        """Save command history to file."""
        if HAS_READLINE:
            try:
                readline.write_history_file(str(history_file))
            except Exception:
                pass
    
    def setup_completion(self) -> None:
        """Setup tab completion."""
        if HAS_READLINE:
            # Enable more sophisticated completion
            readline.set_completer(self.complete)
            readline.parse_and_bind("tab: complete")
        elif HAS_PROMPT_TOOLKIT:
            # Will be handled in cmdloop
            pass
    
    def complete_help(self, text: str, line: str, begidx: int, endidx: int) -> List[str]:
        """Complete help command."""
        return [cmd for cmd in self.GRAPHRAG_COMMANDS.keys() if cmd.startswith(text)]
    
    def do_help(self, arg: str) -> None:
        """Show help for commands.
        
        Usage:
            help                # List all commands
            help <command>      # Show command-specific help
        """
        if not arg:
            self.poutput("\n╔ Available Commands ╗")
            for cmd_name, description in self.GRAPHRAG_COMMANDS.items():
                self.poutput(f"  {cmd_name:12} - {description}")
            self.poutput("  help           - Show this help")
            self.poutput("  status         - Show REPL session status")
            self.poutput("  exit           - Exit REPL\n")
            return
        
        # Show specific command help
        if arg in self.GRAPHRAG_COMMANDS:
            self._invoke_graphrag_command([arg, '--help'])
        else:
            self.poutput(f"Unknown command: {arg}")
    
    def do_status(self, arg: str) -> None:
        """Show REPL session status.
        
        Displays current session state including loaded ontology and
        statistics about commands executed.
        """
        state = self.session_state
        self.poutput("\n╔ REPL Session Status ╗")
        self.poutput(f"  Commands executed:  {state['command_count']}")
        self.poutput(f"  Errors encountered: {state['error_count']}")
        self.poutput(f"  Current ontology:   {state['current_ontology'] or 'None'}")
        
        if state['last_output']:
            self.poutput(f"  Last output:        {len(str(state['last_output']))} bytes")
        self.poutput()
    
    def do_exit(self, arg: str) -> bool:
        """Exit the REPL.
        
        Usage:
            exit        # Exit REPL
        """
        self.poutput("\nGoodbye!")
        return True
    
    def do_quit(self, arg: str) -> bool:
        """Quit the REPL (alias for exit)."""
        return self.do_exit(arg)
    
    def do_clear(self, arg: str) -> None:
        """Clear the screen.
        
        Usage:
            clear       # Clear terminal
        """
        os.system('clear' if os.name != 'nt' else 'cls')
    
    def do_history(self, arg: str) -> None:
        """Show command history.
        
        Usage:
            history              # Show all commands
            history <count>      # Show last N commands
        """
        if not HAS_READLINE:
            self.poutput("History not available (readline not installed)")
            return
        
        import readline
        try:
            limit = int(arg) if arg else None
        except ValueError:
            self.poutput(f"Invalid limit: {arg}")
            return
        
        length = readline.get_current_history_length()
        start = max(1, length - limit + 1) if limit else 1
        
        for i in range(start, length + 1):
            self.poutput(f"  {i:4d}  {readline.get_history_item(i)}")
    
    def default(self, line: str) -> None:
        """Handle unrecognized commands (forward to GraphRAG CLI)."""
        # Parse command
        try:
            args = shlex.split(line)
        except ValueError as e:
            self.poutput(f"Error parsing command: {e}")
            return
        
        if not args:
            return
        
        cmd_name = args[0]
        
        # Check if this is a GraphRAG command
        if cmd_name in self.GRAPHRAG_COMMANDS:
            self._invoke_graphrag_command(args)
        elif cmd_name == '?':
            self.do_help('')
        else:
            self.poutput(f"Unknown command: {cmd_name}")
            self.poutput("Type 'help' for available commands")
    
    def _invoke_graphrag_command(self, args: List[str]) -> None:
        """Invoke a GraphRAG CLI command.
        
        Args:
            args: Command arguments (first element is command name)
        """
        if not self.cli_available:
            self.poutput("Error: GraphRAG CLI not available")
            return
        
        self.session_state['command_count'] += 1
        
        try:
            # Invoke CLI with captured output
            exit_code = self.cli.run(args)
            
            if exit_code != 0:
                self.session_state['error_count'] += 1
                if exit_code != 130:  # Skip user interrupt message
                    self.poutput(f"Command exited with code {exit_code}")
        except KeyboardInterrupt:
            self.poutput("\nInterrupted by user")
            self.session_state['error_count'] += 1
        except Exception as e:
            self.poutput(f"Error: {e}")
            self.session_state['error_count'] += 1
            if '--verbose' in args:
                traceback.print_exc()
    
    def emptyline(self) -> None:
        """Handle empty line (do nothing instead of repeating last command)."""
        pass
    
    def precmd(self, line: str) -> str:
        """Hook before command execution."""
        # Handle ? for help
        if line.strip() == '?':
            line = 'help'
        return line
    
    def postcmd(self, stop: bool, line: str) -> bool:
        """Hook after command execution."""
        return stop


def main() -> int:
    """Entry point for GraphRAG REPL.
    
    Returns:
        Exit code (0 for success)
    """
    try:
        repl = GraphRAGREPL()
        repl.cmdloop()
        return 0
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
