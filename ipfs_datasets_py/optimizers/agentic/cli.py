"""Command-line interface for agentic optimizer.

Provides commands for:
- Starting optimization tasks
- Managing agents
- Viewing status and metrics
- Processing task queues
- Rolling back changes
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (
    ChangeControlMethod,
    OptimizationMethod,
    OptimizationTask,
)
from .coordinator import AgentCoordinator
from .methods import (
    TestDrivenOptimizer,
    AdversarialOptimizer,
    ActorCriticOptimizer,
    ChaosEngineeringOptimizer,
)
from .validation import OptimizationValidator, ValidationLevel
from .production_hardening import (
    InputSanitizer,
    ResourceMonitor,
    get_input_sanitizer,
)


class OptimizerCLI:
    """Command-line interface for agentic optimizer."""
    
    def __init__(self):
        """Initialize CLI."""
        self.coordinator: Optional[AgentCoordinator] = None
        self.config_path = Path(".optimizer-config.json")
        self.config = self._load_config()
        
        # Production hardening: Input sanitizer for security
        self._sanitizer = get_input_sanitizer()
        
        # Production hardening: Resource monitor for tracking
        self._monitor = ResourceMonitor()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file.
        
        Returns:
            Configuration dictionary
        """
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                return json.load(f)
        
        # Default configuration
        return {
            "change_control": "patch",
            "validation_level": "standard",
            "max_agents": 5,
            "ipfs_gateway": "http://127.0.0.1:5001",
            "github_repo": None,
            "github_token": None,
        }
    
    def _save_config(self):
        """Save configuration to file."""
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def cmd_optimize(self, args: argparse.Namespace) -> int:
        """Run optimization task.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        print(f"🚀 Starting optimization task...")
        print(f"   Method: {args.method}")
        print(f"   Target: {args.target}")
        print(f"   Description: {args.description}")
        
        # Parse target files
        target_files = []
        if args.target:
            for pattern in args.target:
                path = Path(pattern)
                if path.is_file():
                    # Production hardening: Validate file path
                    if not self._sanitizer.validate_file_path(str(path)):
                        print(f"⚠️  Warning: {pattern} failed security validation")
                        continue
                    target_files.append(path)
                elif path.is_dir():
                    # Add all Python files in directory
                    for py_file in path.glob("**/*.py"):
                        # Production hardening: Validate each file
                        if self._sanitizer.validate_file_path(str(py_file)):
                            target_files.append(py_file)
                else:
                    print(f"⚠️  Warning: {pattern} not found")
        
        if not target_files:
            print("❌ Error: No target files found")
            return 1
        
        print(f"   Files: {len(target_files)} Python files")
        
        # Create optimization task
        task = OptimizationTask(
            task_id=f"task-{args.method}-{len(target_files)}",
            description=args.description,
            target_files=target_files,
            method=OptimizationMethod[args.method.upper()],
            priority=args.priority,
        )
        
        # Create optimizer based on method
        try:
            # Note: LLM router would need to be provided here
            # For now, we'll show what the interface would look like
            print(f"\n📋 Task created: {task.task_id}")
            print(f"   Priority: {task.priority}")
            print(f"   Change control: {self.config['change_control']}")
            
            if args.dry_run:
                print("\n🔍 Dry run - no changes will be made")
                return 0
            
            # In production, would create and run optimizer here
            print("\n⏳ Optimization in progress...")
            print("   (Implementation requires LLM router configuration)")
            
            return 0
            
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")
            return 1
    
    def cmd_agents_list(self, args: argparse.Namespace) -> int:
        """List all agents.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        print("🤖 Active Agents\n")
        
        if not self.coordinator:
            print("No coordinator initialized")
            print("\nTo start agents, run:")
            print("  optimizer-cli agents start --count N")
            return 0
        
        agents = self.coordinator.get_agent_states()
        
        if not agents:
            print("No agents running")
            return 0
        
        # Print table header
        print(f"{'ID':<15} {'Status':<12} {'Task':<25} {'Uptime':<10}")
        print("-" * 70)
        
        for agent_id, state in agents.items():
            status = state.status
            task = state.current_task[:25] if state.current_task else "-"
            uptime = self._format_duration(state.uptime)
            
            print(f"{agent_id:<15} {status:<12} {task:<25} {uptime:<10}")
        
        print(f"\nTotal: {len(agents)} agent(s)")
        return 0
    
    def cmd_agents_status(self, args: argparse.Namespace) -> int:
        """Show detailed status for an agent.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        agent_id = args.agent_id
        
        print(f"🤖 Agent Status: {agent_id}\n")
        
        if not self.coordinator:
            print("❌ No coordinator initialized")
            return 1
        
        state = self.coordinator.get_agent_state(agent_id)
        
        if not state:
            print(f"❌ Agent not found: {agent_id}")
            return 1
        
        print(f"Status: {state.status}")
        print(f"Current Task: {state.current_task or 'None'}")
        print(f"Tasks Completed: {state.tasks_completed}")
        print(f"Tasks Failed: {state.tasks_failed}")
        print(f"Uptime: {self._format_duration(state.uptime)}")
        print(f"Last Activity: {state.last_activity}")
        
        if state.error_message:
            print(f"\n⚠️  Last Error: {state.error_message}")
        
        return 0
    
    def cmd_queue_process(self, args: argparse.Namespace) -> int:
        """Process task queue.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        print("📋 Processing Task Queue\n")
        
        if not self.coordinator:
            print("❌ No coordinator initialized")
            return 1
        
        # Get queue status
        queue_size = len(self.coordinator.task_queue)
        print(f"Tasks in queue: {queue_size}")
        
        if queue_size == 0:
            print("Queue is empty")
            return 0
        
        # Process queue
        print("\n⏳ Processing tasks...")
        
        try:
            # In production, would call coordinator.process_queue()
            print("   (Queue processing not yet implemented)")
            return 0
            
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")
            return 1
    
    def cmd_stats(self, args: argparse.Namespace) -> int:
        """Show optimization statistics.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        print("📊 Optimization Statistics\n")
        
        if not self.coordinator:
            print("❌ No coordinator initialized")
            return 1
        
        stats = self.coordinator.get_statistics()
        
        print(f"Total Tasks: {stats.get('total_tasks', 0)}")
        print(f"Completed: {stats.get('completed', 0)}")
        print(f"Failed: {stats.get('failed', 0)}")
        print(f"In Progress: {stats.get('in_progress', 0)}")
        print(f"Queued: {stats.get('queued', 0)}")
        
        success_rate = 0
        if stats.get('total_tasks', 0) > 0:
            success_rate = (stats.get('completed', 0) / stats['total_tasks']) * 100
        print(f"\nSuccess Rate: {success_rate:.1f}%")
        
        if 'conflicts' in stats:
            print(f"\nConflicts Detected: {stats['conflicts']}")
            print(f"Auto-Resolved: {stats.get('conflicts_resolved', 0)}")
        
        return 0
    
    def cmd_rollback(self, args: argparse.Namespace) -> int:
        """Rollback a change.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        patch_id = args.patch_id
        
        print(f"↩️  Rolling back patch: {patch_id}\n")
        
        # Load patch manager
        from .patch_control import PatchManager
        
        patch_manager = PatchManager()
        
        try:
            # Check if patch exists
            patch = patch_manager.load_patch(patch_id)
            
            if not patch:
                print(f"❌ Patch not found: {patch_id}")
                return 1
            
            print(f"Patch: {patch.metadata.get('description', 'No description')}")
            print(f"Author: {patch.metadata.get('author', 'Unknown')}")
            print(f"Timestamp: {patch.timestamp}")
            
            if not args.force:
                confirm = input("\nProceed with rollback? [y/N]: ")
                if confirm.lower() != 'y':
                    print("Rollback cancelled")
                    return 0
            
            # Create reversal patch
            print("\n⏳ Creating reversal patch...")
            reversal = patch_manager.create_reversal_patch(patch)
            
            # Apply reversal
            print("⏳ Applying reversal...")
            success = patch_manager.apply_patch(reversal)
            
            if success:
                print("✅ Rollback successful")
                return 0
            else:
                print("❌ Rollback failed")
                return 1
                
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")
            return 1
    
    def cmd_config(self, args: argparse.Namespace) -> int:
        """Manage configuration.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        if args.action == 'show':
            print("⚙️  Current Configuration\n")
            for key, value in self.config.items():
                # Mask sensitive values
                if 'token' in key.lower() or 'password' in key.lower():
                    value = "***" if value else None
                print(f"{key}: {value}")
            return 0
        
        elif args.action == 'set':
            key = args.key
            value = args.value
            
            print(f"⚙️  Setting {key} = {value}")
            
            # Validate key
            if key not in self.config:
                print(f"⚠️  Warning: {key} is not a standard config key")
            
            # Parse value type
            if value.lower() in ['true', 'false']:
                value = value.lower() == 'true'
            elif value.isdigit():
                value = int(value)
            
            self.config[key] = value
            self._save_config()
            
            print("✅ Configuration updated")
            return 0
        
        elif args.action == 'reset':
            print("⚙️  Resetting configuration to defaults")
            
            if not args.force:
                confirm = input("Are you sure? [y/N]: ")
                if confirm.lower() != 'y':
                    print("Reset cancelled")
                    return 0
            
            self.config_path.unlink(missing_ok=True)
            self.config = self._load_config()
            self._save_config()
            
            print("✅ Configuration reset")
            return 0
        
        return 0
    
    def cmd_validate(self, args: argparse.Namespace) -> int:
        """Validate code.
        
        Args:
            args: Command arguments
            
        Returns:
            Exit code
        """
        print(f"🔍 Validating Code\n")
        print(f"   Level: {args.level}")
        print(f"   Target: {args.target}")
        
        # Read code
        target_path = Path(args.target)
        if not target_path.exists():
            print(f"❌ File not found: {args.target}")
            return 1
        
        code = target_path.read_text()
        
        # Create validator
        level = ValidationLevel[args.level.upper()]
        validator = OptimizationValidator(level=level, parallel=not args.sequential)
        
        # Run validation
        print("\n⏳ Running validation...")
        
        try:
            # Production hardening: Monitor resources during validation
            with self._monitor.monitor():
                result = validator.validate_sync(
                    code=code,
                    target_files=[target_path],
                    context={},
                )
            
            # Get resource stats
            stats = self._monitor.get_stats()
            
            # Display results
            print(f"\n{'='*60}")
            print(f"Validation Result: {'✅ PASSED' if result.passed else '❌ FAILED'}")
            print(f"{'='*60}\n")
            
            # Syntax
            if result.syntax:
                status = "✅" if result.syntax.get("passed") else "❌"
                print(f"{status} Syntax: {result.syntax.get('passed', False)}")
            
            # Types
            if result.types:
                status = "✅" if result.types.get("passed") else "❌"
                print(f"{status} Type Checking: {result.types.get('passed', False)}")
            
            # Tests
            if result.unit_tests:
                status = "✅" if result.unit_tests.get("passed") else "❌"
                tests_run = result.unit_tests.get("tests_run", 0)
                tests_passed = result.unit_tests.get("tests_passed", 0)
                print(f"{status} Unit Tests: {tests_passed}/{tests_run} passed")
            
            # Performance
            if result.performance:
                status = "✅" if result.performance.get("passed") else "❌"
                improvement = result.performance.get("improvement", 0) * 100
                print(f"{status} Performance: {improvement:+.1f}% change")
            
            # Security
            if result.security:
                status = "✅" if result.security.get("passed") else "❌"
                issues = len(result.security.get("issues_found", []))
                print(f"{status} Security: {issues} issue(s) found")
            
            # Style
            if result.style:
                status = "✅" if result.style.get("passed") else "❌"
                score = result.style.get("score", 0)
                print(f"{status} Style: {score:.1f}% score")
            
            # Errors and warnings
            if result.errors:
                print(f"\n❌ Errors ({len(result.errors)}):")
                for error in result.errors[:5]:  # Show first 5
                    print(f"   • {error}")
                if len(result.errors) > 5:
                    print(f"   ... and {len(result.errors) - 5} more")
            
            if result.warnings:
                print(f"\n⚠️  Warnings ({len(result.warnings)}):")
                for warning in result.warnings[:5]:  # Show first 5
                    print(f"   • {warning}")
                if len(result.warnings) > 5:
                    print(f"   ... and {len(result.warnings) - 5} more")
            
            print(f"\n⏱️  Validation time: {result.execution_time:.2f}s")
            
            # Production hardening: Show resource usage
            print(f"📊 Resource usage:")
            print(f"   • Time: {stats['elapsed_time']:.2f}s")
            print(f"   • Peak memory: {stats['peak_memory_mb']:.1f}MB")
            
            return 0 if result.passed else 1
            
        except Exception as e:
            print(f"\n❌ Validation error: {str(e)}")
            return 1
    
    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format.
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            Formatted string
        """
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds/60:.0f}m"
        else:
            return f"{seconds/3600:.1f}h"
    
    def run(self, argv: Optional[List[str]] = None) -> int:
        """Run CLI.
        
        Args:
            argv: Command line arguments (None = sys.argv)
            
        Returns:
            Exit code
        """
        parser = argparse.ArgumentParser(
            description="Agentic Optimizer CLI",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        
        subparsers = parser.add_subparsers(dest='command', help='Commands')
        
        # optimize command
        optimize_parser = subparsers.add_parser(
            'optimize',
            help='Run optimization task',
        )
        optimize_parser.add_argument(
            '--method',
            choices=['test_driven', 'adversarial', 'actor_critic', 'chaos'],
            default='test_driven',
            help='Optimization method',
        )
        optimize_parser.add_argument(
            '--target',
            action='append',
            required=True,
            help='Target files or directories',
        )
        optimize_parser.add_argument(
            '--description',
            required=True,
            help='Optimization description',
        )
        optimize_parser.add_argument(
            '--priority',
            type=int,
            default=50,
            help='Task priority (0-100)',
        )
        optimize_parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Dry run without making changes',
        )
        
        # agents commands
        agents_parser = subparsers.add_parser('agents', help='Manage agents')
        agents_subparsers = agents_parser.add_subparsers(dest='agents_command')
        
        agents_subparsers.add_parser('list', help='List all agents')
        
        status_parser = agents_subparsers.add_parser('status', help='Show agent status')
        status_parser.add_argument('agent_id', help='Agent ID')
        
        # queue command
        queue_parser = subparsers.add_parser('queue', help='Manage task queue')
        queue_parser.add_argument(
            'queue_command',
            choices=['process', 'clear', 'list'],
            help='Queue command',
        )
        
        # stats command
        subparsers.add_parser('stats', help='Show statistics')
        
        # rollback command
        rollback_parser = subparsers.add_parser('rollback', help='Rollback a change')
        rollback_parser.add_argument('patch_id', help='Patch ID or CID')
        rollback_parser.add_argument('--force', action='store_true', help='Skip confirmation')
        
        # config command
        config_parser = subparsers.add_parser('config', help='Manage configuration')
        config_parser.add_argument(
            'action',
            choices=['show', 'set', 'reset'],
            help='Config action',
        )
        config_parser.add_argument('--key', help='Config key')
        config_parser.add_argument('--value', help='Config value')
        config_parser.add_argument('--force', action='store_true', help='Skip confirmation')
        
        # validate command
        validate_parser = subparsers.add_parser('validate', help='Validate code')
        validate_parser.add_argument('target', help='File to validate')
        validate_parser.add_argument(
            '--level',
            choices=['basic', 'standard', 'strict', 'paranoid'],
            default='standard',
            help='Validation level',
        )
        validate_parser.add_argument(
            '--sequential',
            action='store_true',
            help='Run validators sequentially',
        )
        
        # Parse arguments
        args = parser.parse_args(argv)
        
        if not args.command:
            parser.print_help()
            return 1
        
        # Route to command handler
        try:
            if args.command == 'optimize':
                return self.cmd_optimize(args)
            elif args.command == 'agents':
                if args.agents_command == 'list':
                    return self.cmd_agents_list(args)
                elif args.agents_command == 'status':
                    return self.cmd_agents_status(args)
            elif args.command == 'queue':
                return self.cmd_queue_process(args)
            elif args.command == 'stats':
                return self.cmd_stats(args)
            elif args.command == 'rollback':
                return self.cmd_rollback(args)
            elif args.command == 'config':
                return self.cmd_config(args)
            elif args.command == 'validate':
                return self.cmd_validate(args)
            else:
                parser.print_help()
                return 1
                
        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted by user")
            return 130
        except Exception as e:
            print(f"\n❌ Unexpected error: {str(e)}")
            import traceback
            traceback.print_exc()
            return 1


def main():
    """Main entry point."""
    cli = OptimizerCLI()
    sys.exit(cli.run())


if __name__ == '__main__':
    main()
