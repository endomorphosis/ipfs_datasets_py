#!/usr/bin/env python3
"""
MCP Dashboard Validation Script

This script validates that the MCP dashboard can start successfully and
provides basic functionality testing.
"""

import os
import sys
import time
import subprocess
import urllib.request
import urllib.error
import json
import platform
from pathlib import Path


def print_header(msg):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}\n")


def print_info(msg):
    """Print info message."""
    print(f"ℹ️  {msg}")


def print_success(msg):
    """Print success message."""
    print(f"✅ {msg}")


def print_error(msg):
    """Print error message."""
    print(f"❌ {msg}")


def print_warning(msg):
    """Print warning message."""
    print(f"⚠️  {msg}")


def check_system_info():
    """Check and display system information."""
    print_header("System Information")
    
    info = {
        "OS": platform.system(),
        "Release": platform.release(),
        "Version": platform.version(),
        "Machine": platform.machine(),
        "Processor": platform.processor() or "Unknown",
        "Python": platform.python_version(),
    }
    
    for key, value in info.items():
        print_info(f"{key}: {value}")
    
    return info


def check_dependencies():
    """Check if required dependencies are installed."""
    print_header("Dependency Check")
    
    required_packages = [
        "flask",
        "mcp",
    ]
    
    all_ok = True
    for package in required_packages:
        try:
            __import__(package)
            print_success(f"{package} is installed")
        except ImportError:
            print_error(f"{package} is NOT installed")
            all_ok = False
    
    return all_ok


def test_dashboard_cli():
    """Test the ipfs-datasets CLI for MCP dashboard commands."""
    print_header("Testing ipfs-datasets CLI")
    
    # Check if ipfs-datasets command is available
    try:
        result = subprocess.run(
            ["python", "-m", "ipfs_datasets_cli", "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            print_success("ipfs-datasets CLI is available")
            return True
        else:
            print_error(f"CLI returned error code {result.returncode}")
            print_error(f"Error: {result.stderr}")
            return False
            
    except FileNotFoundError:
        print_error("ipfs-datasets CLI not found")
        return False
    except subprocess.TimeoutExpired:
        print_error("CLI command timed out")
        return False
    except Exception as e:
        print_error(f"Error testing CLI: {e}")
        return False


def start_dashboard_process(host="127.0.0.1", port=8899, blocking=False):
    """Start the MCP dashboard process."""
    print_header(f"Starting MCP Dashboard on {host}:{port}")
    
    env = os.environ.copy()
    env["MCP_DASHBOARD_HOST"] = host
    env["MCP_DASHBOARD_PORT"] = str(port)
    if blocking:
        env["MCP_DASHBOARD_BLOCKING"] = "1"
    
    cmd = [sys.executable, "-m", "ipfs_datasets_py.mcp_dashboard"]
    
    try:
        if blocking:
            print_info("Starting in blocking mode...")
            proc = subprocess.run(cmd, env=env, timeout=30)
            return proc.returncode == 0, None
        else:
            print_info("Starting in background mode...")
            logs_dir = Path.home() / ".ipfs_datasets"
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_path = logs_dir / "mcp_dashboard_validation.log"
            
            log_fh = open(log_path, "w")
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT
            )
            
            print_info(f"Dashboard process started with PID: {proc.pid}")
            print_info(f"Logs: {log_path}")
            
            # Wait for dashboard to start
            print_info("Waiting for dashboard to be ready...")
            status_url = f"http://{host}:{port}/api/mcp/status"
            
            for i in range(30):  # 30 seconds timeout
                try:
                    with urllib.request.urlopen(status_url, timeout=1) as response:
                        if response.status == 200:
                            print_success(f"Dashboard is ready! (took {i+1}s)")
                            return True, proc
                except (urllib.error.URLError, urllib.error.HTTPError):
                    pass
                
                # Check if process died
                if proc.poll() is not None:
                    print_error(f"Dashboard process exited with code {proc.returncode}")
                    with open(log_path, "r") as f:
                        print_error("Last log lines:")
                        print(f.read()[-1000:])  # Last 1000 chars
                    return False, None
                
                time.sleep(1)
            
            print_warning("Dashboard did not respond within 30 seconds")
            print_info(f"Check logs at: {log_path}")
            return False, proc
            
    except Exception as e:
        print_error(f"Failed to start dashboard: {e}")
        import traceback
        traceback.print_exc()
        return False, None


def test_dashboard_endpoints(host="127.0.0.1", port=8899):
    """Test various dashboard endpoints."""
    print_header("Testing Dashboard Endpoints")
    
    endpoints = [
        ("/", "Main Dashboard"),
        ("/api/mcp/status", "MCP Status"),
        ("/mcp", "MCP Interface"),
    ]
    
    results = {}
    for endpoint, name in endpoints:
        url = f"http://{host}:{port}{endpoint}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                status = response.status
                if status == 200:
                    print_success(f"{name}: OK (200)")
                    results[endpoint] = True
                else:
                    print_warning(f"{name}: {status}")
                    results[endpoint] = False
        except urllib.error.HTTPError as e:
            print_warning(f"{name}: HTTP {e.code}")
            results[endpoint] = False
        except Exception as e:
            print_error(f"{name}: {e}")
            results[endpoint] = False
    
    return results


def stop_dashboard(proc):
    """Stop the dashboard process."""
    if proc:
        print_header("Stopping Dashboard")
        try:
            proc.terminate()
            proc.wait(timeout=5)
            print_success("Dashboard stopped successfully")
        except subprocess.TimeoutExpired:
            proc.kill()
            print_warning("Dashboard killed (did not terminate gracefully)")
        except Exception as e:
            print_error(f"Error stopping dashboard: {e}")


def main():
    """Main validation flow."""
    print_header("MCP Dashboard Validation")
    print_info("This script validates the MCP dashboard functionality")
    
    # Check system info
    sys_info = check_system_info()
    
    # Check dependencies
    deps_ok = check_dependencies()
    if not deps_ok:
        print_error("Missing required dependencies")
        print_info("Install dependencies with: pip install -r requirements.txt")
        return 1
    
    # Test CLI
    cli_ok = test_dashboard_cli()
    if not cli_ok:
        print_warning("CLI test failed, but continuing...")
    
    # Start dashboard
    success, proc = start_dashboard_process()
    
    if not success:
        print_error("Failed to start dashboard")
        if proc:
            stop_dashboard(proc)
        return 1
    
    # Test endpoints
    endpoint_results = test_dashboard_endpoints()
    
    # Generate report
    print_header("Validation Summary")
    print_info(f"System: {sys_info['Machine']} running {sys_info['OS']}")
    print_info(f"Dependencies: {'✅ OK' if deps_ok else '❌ Failed'}")
    print_info(f"CLI: {'✅ OK' if cli_ok else '⚠️ Warning'}")
    print_info(f"Dashboard Started: {'✅ Yes' if success else '❌ No'}")
    
    if endpoint_results:
        working = sum(1 for v in endpoint_results.values() if v)
        total = len(endpoint_results)
        print_info(f"Endpoints: {working}/{total} working")
    
    # Cleanup
    stop_dashboard(proc)
    
    # Final result
    if success and any(endpoint_results.values()):
        print_success("\n🎉 Validation PASSED!")
        return 0
    else:
        print_error("\n❌ Validation FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
