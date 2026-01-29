#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
State Laws Cron Job Manager

This script provides a command-line interface for managing cron jobs
that periodically update state law datasets.

Usage:
    python state_laws_cron.py add --schedule-id daily_ca_ny --states CA,NY --interval 24
    python state_laws_cron.py list
    python state_laws_cron.py run --schedule-id daily_ca_ny
    python state_laws_cron.py remove --schedule-id daily_ca_ny
    python state_laws_cron.py enable --schedule-id daily_ca_ny
    python state_laws_cron.py disable --schedule-id daily_ca_ny
    python state_laws_cron.py daemon  # Run continuous scheduler
"""

import argparse
import anyio
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ipfs_datasets_py.legal_scrapers.state_laws_scheduler import (
    StateLawsUpdateScheduler,
    create_schedule,
    remove_schedule,
    list_schedules,
    run_schedule_now,
    enable_disable_schedule
)


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Manage cron jobs for state law dataset updates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add a schedule for California and New York, updated daily
  %(prog)s add --schedule-id daily_ca_ny --states CA,NY --interval 24
  
  # Add a schedule for all states, updated weekly
  %(prog)s add --schedule-id weekly_all --states all --interval 168
  
  # List all schedules
  %(prog)s list
  
  # Run a schedule immediately
  %(prog)s run --schedule-id daily_ca_ny
  
  # Enable/disable a schedule
  %(prog)s enable --schedule-id daily_ca_ny
  %(prog)s disable --schedule-id daily_ca_ny
  
  # Remove a schedule
  %(prog)s remove --schedule-id daily_ca_ny
  
  # Run continuous scheduler daemon
  %(prog)s daemon --check-interval 300
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Add schedule
    add_parser = subparsers.add_parser('add', help='Add a new update schedule')
    add_parser.add_argument('--schedule-id', required=True, help='Unique schedule identifier')
    add_parser.add_argument('--states', help='Comma-separated state codes (e.g., CA,NY,TX) or "all"')
    add_parser.add_argument('--legal-areas', help='Comma-separated legal areas')
    add_parser.add_argument('--interval', type=int, default=24, help='Update interval in hours (default: 24)')
    add_parser.add_argument('--disabled', action='store_true', help='Create schedule in disabled state')
    
    # List schedules
    list_parser = subparsers.add_parser('list', help='List all schedules')
    list_parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    # Run schedule
    run_parser = subparsers.add_parser('run', help='Run a schedule immediately')
    run_parser.add_argument('--schedule-id', required=True, help='Schedule ID to run')
    
    # Remove schedule
    remove_parser = subparsers.add_parser('remove', help='Remove a schedule')
    remove_parser.add_argument('--schedule-id', required=True, help='Schedule ID to remove')
    
    # Enable schedule
    enable_parser = subparsers.add_parser('enable', help='Enable a schedule')
    enable_parser.add_argument('--schedule-id', required=True, help='Schedule ID to enable')
    
    # Disable schedule
    disable_parser = subparsers.add_parser('disable', help='Disable a schedule')
    disable_parser.add_argument('--schedule-id', required=True, help='Schedule ID to disable')
    
    # Daemon mode
    daemon_parser = subparsers.add_parser('daemon', help='Run continuous scheduler daemon')
    daemon_parser.add_argument('--check-interval', type=int, default=300, 
                             help='Seconds between schedule checks (default: 300)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    try:
        if args.command == 'add':
            return anyio.run(cmd_add(args))
        elif args.command == 'list':
            return anyio.run(cmd_list(args))
        elif args.command == 'run':
            return anyio.run(cmd_run(args))
        elif args.command == 'remove':
            return anyio.run(cmd_remove(args))
        elif args.command == 'enable':
            return anyio.run(cmd_enable(args))
        elif args.command == 'disable':
            return anyio.run(cmd_disable(args))
        elif args.command == 'daemon':
            return anyio.run(cmd_daemon(args))
        else:
            print(f"Unknown command: {args.command}")
            return 1
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        return 130
    except Exception as e:
        print(f"Error: {e}")
        return 1


async def cmd_add(args):
    """Add a new schedule."""
    states = None
    if args.states:
        states = [s.strip() for s in args.states.split(',')]
    
    legal_areas = None
    if args.legal_areas:
        legal_areas = [a.strip() for a in args.legal_areas.split(',')]
    
    result = await create_schedule(
        schedule_id=args.schedule_id,
        states=states,
        legal_areas=legal_areas,
        interval_hours=args.interval,
        enabled=not args.disabled
    )
    
    print(f"✓ Schedule '{args.schedule_id}' created successfully")
    print(f"  States: {states or 'all'}")
    print(f"  Interval: {args.interval} hours")
    print(f"  Status: {'disabled' if args.disabled else 'enabled'}")
    
    return 0


async def cmd_list(args):
    """List all schedules."""
    result = await list_schedules()
    
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    
    schedules = result.get('schedules', [])
    
    if not schedules:
        print("No schedules configured")
        return 0
    
    print(f"\nConfigured Schedules ({len(schedules)}):\n")
    
    for schedule in schedules:
        status = "✓" if schedule['enabled'] else "✗"
        print(f"{status} {schedule['schedule_id']}")
        print(f"  States: {', '.join(schedule['states'])}")
        print(f"  Interval: {schedule['interval_hours']} hours")
        print(f"  Last run: {schedule['last_run'] or 'never'}")
        print(f"  Next run: {schedule['next_run']}")
        if schedule.get('legal_areas'):
            print(f"  Legal areas: {', '.join(schedule['legal_areas'])}")
        print()
    
    return 0


async def cmd_run(args):
    """Run a schedule immediately."""
    print(f"Running schedule '{args.schedule_id}'...")
    
    result = await run_schedule_now(args.schedule_id)
    
    if result.get('status') == 'error':
        print(f"✗ Error: {result.get('error')}")
        return 1
    elif result.get('status') == 'skipped':
        print(f"⊘ Skipped: {result.get('reason')}")
        return 0
    else:
        metadata = result.get('metadata', {})
        print(f"✓ Schedule completed successfully")
        print(f"  States scraped: {metadata.get('states_count', 0)}")
        print(f"  Statutes fetched: {metadata.get('statutes_count', 0)}")
        print(f"  Elapsed time: {metadata.get('elapsed_time_seconds', 0):.2f}s")
        if result.get('output_file'):
            print(f"  Output saved to: {result['output_file']}")
        return 0


async def cmd_remove(args):
    """Remove a schedule."""
    result = await remove_schedule(args.schedule_id)
    
    if result.get('status') == 'success':
        print(f"✓ Schedule '{args.schedule_id}' removed")
        return 0
    else:
        print(f"✗ Error: {result.get('message')}")
        return 1


async def cmd_enable(args):
    """Enable a schedule."""
    result = await enable_disable_schedule(args.schedule_id, enabled=True)
    
    if result.get('status') == 'success':
        print(f"✓ Schedule '{args.schedule_id}' enabled")
        return 0
    else:
        print(f"✗ Error: {result.get('message')}")
        return 1


async def cmd_disable(args):
    """Disable a schedule."""
    result = await enable_disable_schedule(args.schedule_id, enabled=False)
    
    if result.get('status') == 'success':
        print(f"✓ Schedule '{args.schedule_id}' disabled")
        return 0
    else:
        print(f"✗ Error: {result.get('message')}")
        return 1


async def cmd_daemon(args):
    """Run continuous scheduler daemon."""
    print(f"Starting scheduler daemon (check interval: {args.check_interval}s)")
    print("Press Ctrl+C to stop\n")
    
    scheduler = StateLawsUpdateScheduler()
    await scheduler.run_scheduler_loop(check_interval_seconds=args.check_interval)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
