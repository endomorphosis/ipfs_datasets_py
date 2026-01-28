#!/usr/bin/env python3
"""
MCP Dashboard Screenshot Script

This script starts the MCP dashboard and takes screenshots of various pages.
"""

import os
import sys
import time
import subprocess
from pathlib import Path


def start_dashboard(host="127.0.0.1", port=8899):
    """Start the MCP dashboard in background."""
    print(f"Starting MCP Dashboard on {host}:{port}...")
    
    env = os.environ.copy()
    env["MCP_DASHBOARD_HOST"] = host
    env["MCP_DASHBOARD_PORT"] = str(port)
    
    cmd = [sys.executable, "-m", "ipfs_datasets_py.mcp_dashboard"]
    
    logs_dir = Path.home() / ".ipfs_datasets"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "mcp_dashboard_screenshot.log"
    
    log_fh = open(log_path, "w")
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT
    )
    
    print(f"Dashboard process started with PID: {proc.pid}")
    print("Waiting for dashboard to be ready...")
    
    # Wait for dashboard to start
    time.sleep(5)
    
    return proc, log_path


def take_screenshots(host="127.0.0.1", port=8899):
    """Take screenshots of dashboard pages."""
    from playwright.sync_api import sync_playwright
    
    print("\nTaking screenshots...")
    
    screenshots_dir = Path("mcp_dashboard_screenshots")
    screenshots_dir.mkdir(exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        
        # Main dashboard page
        try:
            url = f"http://{host}:{port}/"
            print(f"Capturing: {url}")
            page.goto(url, wait_until="networkidle", timeout=10000)
            time.sleep(2)
            screenshot_path = screenshots_dir / "main_dashboard.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"  ✅ Saved: {screenshot_path}")
        except Exception as e:
            print(f"  ❌ Error: {e}")
        
        # MCP interface
        try:
            url = f"http://{host}:{port}/mcp"
            print(f"Capturing: {url}")
            page.goto(url, wait_until="networkidle", timeout=10000)
            time.sleep(2)
            screenshot_path = screenshots_dir / "mcp_interface.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"  ✅ Saved: {screenshot_path}")
        except Exception as e:
            print(f"  ❌ Error: {e}")
        
        # MCP status page
        try:
            url = f"http://{host}:{port}/api/mcp/status"
            print(f"Capturing: {url}")
            page.goto(url, wait_until="networkidle", timeout=10000)
            time.sleep(1)
            screenshot_path = screenshots_dir / "mcp_status.png"
            page.screenshot(path=str(screenshot_path))
            print(f"  ✅ Saved: {screenshot_path}")
        except Exception as e:
            print(f"  ❌ Error: {e}")
        
        browser.close()
    
    return screenshots_dir


def stop_dashboard(proc):
    """Stop the dashboard process."""
    if proc:
        print("\nStopping dashboard...")
        try:
            proc.terminate()
            proc.wait(timeout=5)
            print("✅ Dashboard stopped")
        except subprocess.TimeoutExpired:
            proc.kill()
            print("⚠️  Dashboard killed")
        except Exception as e:
            print(f"❌ Error stopping dashboard: {e}")


def main():
    """Main execution flow."""
    print("="*60)
    print("  MCP Dashboard Screenshot Utility")
    print("="*60)
    
    # Start dashboard
    proc, log_path = start_dashboard()
    
    try:
        # Take screenshots
        screenshots_dir = take_screenshots()
        
        print(f"\n✅ Screenshots saved to: {screenshots_dir.absolute()}")
        print(f"📝 Dashboard logs: {log_path}")
        
    finally:
        # Cleanup
        stop_dashboard(proc)
    
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
