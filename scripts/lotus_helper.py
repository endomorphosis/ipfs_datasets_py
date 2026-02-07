#!/usr/bin/env python3
'''
Helper script for managing Lotus daemon.

This script provides simplified commands for starting, stopping, and
checking the status of the Lotus daemon.
'''

import argparse
import os
import signal
import subprocess
import sys
import time

# Setup paths
BIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "/home/barberb/Clarity_Act_Deontic_Logic/outputs/lotus_bin_userspace_20260207T091743Z"))
LOTUS_BIN = os.path.join(BIN_DIR, "lotus")
if sys.platform == "win32":
    LOTUS_BIN += ".exe"

# Find and read PID file
def get_daemon_pid():
    lotus_dir = os.path.expanduser("~/.lotus")
    pid_file = os.path.join(lotus_dir, "daemon.pid")
    if os.path.exists(pid_file):
        with open(pid_file, "r") as f:
            try:
                return int(f.read().strip())
            except ValueError:
                return None
    return None

# Check if daemon is running
def is_daemon_running():
    pid = get_daemon_pid()
    if pid is None:
        return False
    
    # Check if process exists
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

# Start Lotus daemon
def start_daemon(lite=False):
    if is_daemon_running():
        print("Lotus daemon is already running")
        return True
    
    # Build command
    cmd = [LOTUS_BIN, "daemon"]
    if lite:
        cmd.append("--lite")
        
    # Start daemon process
    try:
        print("Starting Lotus daemon...")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        
        # Wait for daemon to start
        for i in range(10):
            time.sleep(1)
            if is_daemon_running():
                print("Lotus daemon started successfully")
                return True
        
        print("Warning: Daemon seems to be starting, but PID file not found yet")
        print("Check 'lotus net id' to verify if daemon is ready")
        return True
    except Exception as e:
        print(f"Error starting Lotus daemon: {e}")
        return False

# Stop Lotus daemon
def stop_daemon():
    pid = get_daemon_pid()
    if pid is None:
        print("Lotus daemon is not running")
        return True
    
    try:
        # Try graceful shutdown first
        subprocess.run([LOTUS_BIN, "daemon", "stop"], check=True)
        
        # Wait for process to exit
        for i in range(10):
            time.sleep(1)
            if not is_daemon_running():
                print("Lotus daemon stopped successfully")
                return True
        
        # Force kill if still running
        print("Daemon not responding to graceful shutdown, force killing...")
        os.kill(pid, signal.SIGKILL)
        return True
    except Exception as e:
        print(f"Error stopping Lotus daemon: {e}")
        return False

# Check daemon status
def check_status():
    if is_daemon_running():
        pid = get_daemon_pid()
        print(f"Lotus daemon is running (PID: {pid})")
        
        # Get additional info
        try:
            info = subprocess.check_output([LOTUS_BIN, "net", "id"], universal_newlines=True)
            print(info.strip())
        except subprocess.SubprocessError:
            print("Warning: Could not get daemon status")
    else:
        print("Lotus daemon is not running")

# Main function
def main():
    parser = argparse.ArgumentParser(description="Lotus daemon helper")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Start command
    start_parser = subparsers.add_parser("start", help="Start Lotus daemon")
    start_parser.add_argument("--lite", action="store_true", help="Start in lite mode")
    
    # Stop command
    subparsers.add_parser("stop", help="Stop Lotus daemon")
    
    # Status command
    subparsers.add_parser("status", help="Check Lotus daemon status")
    
    args = parser.parse_args()
    
    if args.command == "start":
        start_daemon(args.lite)
    elif args.command == "stop":
        stop_daemon()
    elif args.command == "status":
        check_status()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
