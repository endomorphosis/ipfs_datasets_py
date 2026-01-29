#!/usr/bin/env python3
"""
Setup Periodic Updates for Legal Datasets

This script helps you easily set up periodic updates for US Code, Federal Register,
and State Laws datasets. It creates cron schedules using the built-in scheduler.

Usage:
    python setup_periodic_updates.py --help
    python setup_periodic_updates.py --preset daily_us_code
    python setup_periodic_updates.py --custom
"""
import argparse
import anyio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ipfs_datasets_py.legal_scrapers import (
    create_schedule,
    list_schedules,
    run_schedule_now
)


async def setup_daily_us_code():
    """Set up daily US Code updates."""
    print("Setting up daily US Code updates...")
    try:
        result = await create_schedule(
            schedule_id="daily_us_code",
            schedule_type="us_code",
            interval_hours=24,
            enabled=True,
            config={
                "titles": None,  # All titles
                "output_format": "json",
                "include_metadata": True,
                "rate_limit_delay": 1.0
            }
        )
        print(f"✓ Daily US Code schedule created: {result['schedule_id']}")
        return result
    except Exception as e:
        print(f"✗ Failed to create US Code schedule: {e}")
        return None


async def setup_daily_federal_register():
    """Set up daily Federal Register updates."""
    print("Setting up daily Federal Register updates...")
    try:
        from datetime import datetime, timedelta
        
        # Get last 7 days of documents
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        result = await create_schedule(
            schedule_id="daily_federal_register",
            schedule_type="federal_register",
            interval_hours=24,
            enabled=True,
            config={
                "agencies": None,  # All agencies
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "document_types": None,
                "output_format": "json",
                "include_full_text": False,
                "rate_limit_delay": 1.0
            }
        )
        print(f"✓ Daily Federal Register schedule created: {result['schedule_id']}")
        return result
    except Exception as e:
        print(f"✗ Failed to create Federal Register schedule: {e}")
        return None


async def setup_daily_state_laws():
    """Set up daily state laws updates."""
    print("Setting up daily state laws updates...")
    try:
        result = await create_schedule(
            schedule_id="daily_state_laws",
            schedule_type="state_laws",
            interval_hours=24,
            enabled=True,
            config={
                "states": ["CA", "NY", "TX"],  # Major states
                "legal_areas": None,
                "output_format": "json",
                "include_metadata": True,
                "rate_limit_delay": 2.0
            }
        )
        print(f"✓ Daily State Laws schedule created: {result['schedule_id']}")
        return result
    except Exception as e:
        print(f"✗ Failed to create State Laws schedule: {e}")
        return None


async def setup_weekly_all_states():
    """Set up weekly updates for all states."""
    print("Setting up weekly updates for all US states...")
    try:
        result = await create_schedule(
            schedule_id="weekly_all_states",
            schedule_type="state_laws",
            interval_hours=168,  # Weekly
            enabled=True,
            config={
                "states": None,  # All states
                "legal_areas": None,
                "output_format": "json",
                "include_metadata": True,
                "rate_limit_delay": 2.0
            }
        )
        print(f"✓ Weekly All States schedule created: {result['schedule_id']}")
        return result
    except Exception as e:
        print(f"✗ Failed to create weekly All States schedule: {e}")
        return None


async def setup_custom_schedule():
    """Interactive setup for custom schedule."""
    print("\n=== Custom Schedule Setup ===")
    
    try:
        # Get schedule type
        print("\nSelect dataset type:")
        print("1. US Code")
        print("2. Federal Register")
        print("3. State Laws")
        choice = input("Enter choice (1-3): ").strip()
        
        schedule_types = {
            "1": "us_code",
            "2": "federal_register",
            "3": "state_laws"
        }
        
        if choice not in schedule_types:
            print("Invalid choice!")
            return None
        
        schedule_type = schedule_types[choice]
        
        # Get schedule ID
        schedule_id = input("\nEnter schedule ID (e.g., 'my_daily_updates'): ").strip()
        if not schedule_id:
            print("Schedule ID is required!")
            return None
        
        # Get interval
        print("\nHow often should updates run?")
        print("1. Every 6 hours")
        print("2. Daily (24 hours)")
        print("3. Weekly (168 hours)")
        print("4. Custom interval")
        interval_choice = input("Enter choice (1-4): ").strip()
        
        intervals = {
            "1": 6,
            "2": 24,
            "3": 168
        }
        
        if interval_choice in intervals:
            interval_hours = intervals[interval_choice]
        elif interval_choice == "4":
            try:
                interval_hours = int(input("Enter custom interval in hours: ").strip())
                if interval_hours <= 0:
                    print("Interval must be greater than 0!")
                    return None
            except ValueError:
                print("Invalid interval! Please enter a number.")
                return None
        else:
            print("Invalid choice!")
            return None
        
        # Build configuration based on type
        config = {}
        
        if schedule_type == "us_code":
            config = {
                "titles": None,
                "output_format": "json",
                "include_metadata": True,
                "rate_limit_delay": 1.0
            }
        elif schedule_type == "federal_register":
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            
            config = {
                "agencies": None,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "document_types": None,
                "output_format": "json",
                "include_full_text": False,
                "rate_limit_delay": 1.0
            }
        elif schedule_type == "state_laws":
            states_input = input("\nEnter states (comma-separated, or 'all'): ").strip()
            states = None if states_input.lower() == "all" else [s.strip() for s in states_input.split(",")]
            
            config = {
                "states": states,
                "legal_areas": None,
                "output_format": "json",
                "include_metadata": True,
                "rate_limit_delay": 2.0
            }
        
        # Create schedule
        result = await create_schedule(
            schedule_id=schedule_id,
            schedule_type=schedule_type,
            interval_hours=interval_hours,
            enabled=True,
            config=config
        )
        
        print(f"\n✓ Custom schedule created: {result['schedule_id']}")
        return result
        
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
        return None
    except Exception as e:
        print(f"\n✗ Failed to create custom schedule: {e}")
        return None


async def list_existing_schedules():
    """List all existing schedules."""
    print("\n=== Existing Schedules ===")
    result = await list_schedules()
    
    schedules = result.get('schedules', [])
    if not schedules:
        print("No schedules configured yet.")
        return
    
    for schedule in schedules:
        enabled_status = "✓ Enabled" if schedule.get('enabled') else "✗ Disabled"
        print(f"\n{schedule['schedule_id']} ({enabled_status})")
        print(f"  Type: {schedule.get('schedule_type', 'unknown')}")
        print(f"  Interval: {schedule['interval_hours']} hours")
        print(f"  Last run: {schedule.get('last_run', 'Never')}")
        print(f"  Next run: {schedule.get('next_run', 'Not scheduled')}")


async def main():
    parser = argparse.ArgumentParser(
        description="Setup periodic updates for legal datasets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Set up daily US Code updates
  python setup_periodic_updates.py --preset daily_us_code
  
  # Set up all recommended presets
  python setup_periodic_updates.py --preset all
  
  # Interactive custom setup
  python setup_periodic_updates.py --custom
  
  # List existing schedules
  python setup_periodic_updates.py --list
        """
    )
    
    parser.add_argument(
        '--preset',
        choices=['daily_us_code', 'daily_federal_register', 'daily_state_laws', 
                 'weekly_all_states', 'all'],
        help='Use a preset configuration'
    )
    
    parser.add_argument(
        '--custom',
        action='store_true',
        help='Interactive custom schedule setup'
    )
    
    parser.add_argument(
        '--list',
        action='store_true',
        help='List existing schedules'
    )
    
    parser.add_argument(
        '--run-now',
        metavar='SCHEDULE_ID',
        help='Run a specific schedule immediately (for testing)'
    )
    
    args = parser.parse_args()
    
    # If no arguments, show help
    if not any([args.preset, args.custom, args.list, args.run_now]):
        parser.print_help()
        return
    
    # List existing schedules
    if args.list:
        await list_existing_schedules()
        return
    
    # Run schedule now
    if args.run_now:
        print(f"Running schedule {args.run_now} now...")
        result = await run_schedule_now(args.run_now)
        if result.get('status') == 'success':
            print("✓ Schedule executed successfully!")
            print(f"Results: {result.get('result', {})}")
        else:
            print(f"✗ Schedule execution failed: {result.get('error')}")
        return
    
    # Setup presets
    if args.preset:
        if args.preset == 'daily_us_code':
            await setup_daily_us_code()
        elif args.preset == 'daily_federal_register':
            await setup_daily_federal_register()
        elif args.preset == 'daily_state_laws':
            await setup_daily_state_laws()
        elif args.preset == 'weekly_all_states':
            await setup_weekly_all_states()
        elif args.preset == 'all':
            await setup_daily_us_code()
            await setup_daily_federal_register()
            await setup_daily_state_laws()
            await setup_weekly_all_states()
        
        print("\n✓ Setup complete!")
        print("\nTo view your schedules, run:")
        print("  python setup_periodic_updates.py --list")
        print("\nTo test a schedule immediately, run:")
        print("  python setup_periodic_updates.py --run-now <schedule_id>")
        return
    
    # Custom setup
    if args.custom:
        await setup_custom_schedule()
        print("\n✓ Custom schedule created!")
        return


if __name__ == "__main__":
    try:
        anyio.run(main())
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)
