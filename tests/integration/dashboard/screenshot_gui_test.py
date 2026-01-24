#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
GUI Screenshot Testing Script

Takes screenshots of the News Analysis Dashboard GUI to identify bugs and improvement opportunities.
"""
import sys
import anyio
import time
import threading
from pathlib import Path
import json
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from ipfs_datasets_py.news_analysis_dashboard import NewsAnalysisDashboard, MCPDashboardConfig
    from html2image import Html2Image
    print("✓ Successfully imported dependencies")
except ImportError as e:
    print(f"✗ Failed to import dependencies: {e}")
    print("Trying alternative approach...")
    try:
        import subprocess
        import os
        print("✓ Will use alternative screenshot method")
    except ImportError:
        sys.exit(1)

def start_dashboard_server():
    """Start the news analysis dashboard server."""
    try:
        config = MCPDashboardConfig(
            host="127.0.0.1",
            port=8080,
            mcp_server_host="127.0.0.1",
            mcp_server_port=8001,
            enable_tool_execution=True
        )
        
        dashboard = NewsAnalysisDashboard(config)
        
        # Start server in background thread
        def run_server():
            print("Starting dashboard server on http://127.0.0.1:8080")
            dashboard.run()
        
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        time.sleep(5)  # Give server more time to start
        
        return dashboard, server_thread
        
    except Exception as e:
        print(f"Error starting server: {e}")
        print(f"Full error details: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def take_screenshots_playwright():
    """Take screenshots using Playwright if available."""
    try:
        from playwright.sync_api import sync_playwright
        
        screenshots_dir = Path("gui_screenshots")
        screenshots_dir.mkdir(exist_ok=True)
        
        with sync_playwright() as p:
            # Try different browsers
            for browser_type in [p.chromium, p.firefox, p.webkit]:
                try:
                    browser = browser_type.launch(headless=True)
                    page = browser.new_page()
                    
                    # Set viewport size
                    page.set_viewport_size({"width": 1200, "height": 800})
                    
                    # Navigate to dashboard
                    page.goto("http://127.0.0.1:8080")
                    page.wait_for_load_state("networkidle")
                    
                    # Take full page screenshot
                    page.screenshot(path=screenshots_dir / f"full_dashboard_{browser_type.name}.png", full_page=True)
                    
                    # Test different tabs
                    tabs = ["overview", "ingest", "timeline", "query", "graph-explorer", "export", "workflows"]
                    for tab in tabs:
                        try:
                            # Click on tab
                            tab_selector = f"[data-tab='{tab}']"
                            if page.locator(tab_selector).count() > 0:
                                page.click(tab_selector)
                                page.wait_for_timeout(1000)  # Wait for content to load
                                
                                # Take screenshot of tab
                                page.screenshot(
                                    path=screenshots_dir / f"{tab}_tab_{browser_type.name}.png",
                                    full_page=False
                                )
                                print(f"✓ Screenshot taken for {tab} tab")
                        except Exception as tab_error:
                            print(f"! Error with {tab} tab: {tab_error}")
                    
                    # Test user type switcher
                    user_types = ["data-scientist", "historian", "lawyer"]
                    for user_type in user_types:
                        try:
                            user_selector = f"[data-user-type='{user_type}']"
                            if page.locator(user_selector).count() > 0:
                                page.click(user_selector)
                                page.wait_for_timeout(500)
                                
                                page.screenshot(
                                    path=screenshots_dir / f"{user_type}_theme_{browser_type.name}.png",
                                    full_page=False
                                )
                                print(f"✓ Screenshot taken for {user_type} theme")
                        except Exception as theme_error:
                            print(f"! Error with {user_type} theme: {theme_error}")
                    
                    browser.close()
                    print(f"✓ Screenshots completed with {browser_type.name}")
                    return screenshots_dir
                    
                except Exception as browser_error:
                    print(f"! Browser {browser_type.name} failed: {browser_error}")
                    continue
                    
    except ImportError:
        print("Playwright not available, trying alternative method...")
        return None

def take_screenshots_html2image():
    """Take screenshots using html2image."""
    try:
        screenshots_dir = Path("gui_screenshots")
        screenshots_dir.mkdir(exist_ok=True)
        
        hti = Html2Image(output_path=str(screenshots_dir))
        
        # Take screenshot of main dashboard
        hti.screenshot(url="http://127.0.0.1:8080", save_as="dashboard_main.png", size=(1200, 800))
        print("✓ Main dashboard screenshot taken")
        
        # Create test HTML for different states
        test_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Dashboard Test</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                .test-section { margin: 20px 0; padding: 20px; border: 1px solid #ccc; }
                .tab { display: inline-block; padding: 10px 20px; margin: 5px; background: #f0f0f0; cursor: pointer; }
                .tab.active { background: #007bff; color: white; }
                .content { padding: 20px; border: 1px solid #ddd; margin-top: 10px; }
            </style>
        </head>
        <body>
            <h1>News Analysis Dashboard Test</h1>
            
            <div class="test-section">
                <h2>Navigation Tabs</h2>
                <div class="tab active">Overview</div>
                <div class="tab">Ingest</div>
                <div class="tab">Timeline</div>
                <div class="tab">Query</div>
                <div class="tab">Graph Explorer</div>
                <div class="tab">Export</div>
                <div class="tab">Workflows</div>
            </div>
            
            <div class="test-section">
                <h2>User Types</h2>
                <div class="tab">Data Scientist</div>
                <div class="tab">Historian</div>
                <div class="tab">Lawyer</div>
            </div>
            
            <div class="test-section">
                <h2>Dashboard Content</h2>
                <div class="content">
                    <p>This is a test of the dashboard interface.</p>
                    <p>Testing responsiveness and styling.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        test_file = screenshots_dir / "test_dashboard.html"
        test_file.write_text(test_html)
        
        hti.screenshot(html_file=str(test_file), save_as="dashboard_test.png", size=(1200, 800))
        print("✓ Test dashboard screenshot taken")
        
        return screenshots_dir
        
    except Exception as e:
        print(f"Error with html2image: {e}")
        return None

def analyze_gui_issues(screenshots_dir):
    """Analyze GUI and identify potential issues."""
    issues = []
    improvements = []
    
    if screenshots_dir and screenshots_dir.exists():
        screenshot_files = list(screenshots_dir.glob("*.png"))
        
        print(f"\n=== GUI Analysis Report ===")
        print(f"Screenshots taken: {len(screenshot_files)}")
        
        # Check if basic functionality works
        if any("main" in f.name for f in screenshot_files):
            print("✓ Main dashboard screenshot successful")
        else:
            issues.append("Main dashboard screenshot failed")
        
        # Check tab functionality
        tab_screenshots = [f for f in screenshot_files if "tab" in f.name]
        if tab_screenshots:
            print(f"✓ Tab screenshots: {len(tab_screenshots)}")
        else:
            issues.append("Tab navigation screenshots missing")
            improvements.append("Add tab click testing functionality")
        
        # Check theme switching
        theme_screenshots = [f for f in screenshot_files if "theme" in f.name]
        if theme_screenshots:
            print(f"✓ Theme screenshots: {len(theme_screenshots)}")
        else:
            issues.append("Theme switching screenshots missing")
            improvements.append("Add user type theme testing")
    
    # Common GUI improvements based on dashboard analysis
    improvements.extend([
        "Add loading states for async operations",
        "Improve error handling display",
        "Add keyboard navigation support",
        "Enhance mobile responsiveness",
        "Add dark/light mode toggle",
        "Improve accessibility (ARIA labels, screen reader support)",
        "Add tooltips for complex features",
        "Implement better visual feedback for user actions"
    ])
    
    return issues, improvements

def generate_improvement_recommendations():
    """Generate specific GUI improvement recommendations."""
    return {
        "critical_fixes": [
            "Fix any JavaScript console errors",
            "Ensure all API endpoints are working",
            "Validate form submissions and error handling",
            "Test responsive design on mobile devices"
        ],
        "user_experience_improvements": [
            "Add progress indicators for long-running operations",
            "Implement better visual hierarchy with consistent typography",
            "Add hover states and visual feedback for interactive elements",
            "Improve color contrast for accessibility compliance"
        ],
        "functionality_enhancements": [
            "Add keyboard shortcuts for power users",
            "Implement auto-save for form inputs",
            "Add undo/redo functionality where appropriate",
            "Create guided onboarding tour for new users"
        ],
        "performance_optimizations": [
            "Lazy load dashboard components",
            "Implement virtual scrolling for large datasets",
            "Add caching for frequently accessed data",
            "Optimize bundle size and loading times"
        ]
    }

def main():
    """Main function to run GUI testing and analysis."""
    print("=== GUI Screenshot Testing and Analysis ===")
    
    # Start dashboard server
    dashboard, server_thread = start_dashboard_server()
    
    if not dashboard:
        print("✗ Failed to start dashboard server")
        return
    
    screenshots_dir = None
    
    # Try Playwright first, then fallback to html2image
    try:
        screenshots_dir = take_screenshots_playwright()
    except Exception as e:
        print(f"Playwright method failed: {e}")
    
    if not screenshots_dir:
        screenshots_dir = take_screenshots_html2image()
    
    # Analyze GUI issues
    issues, improvements = analyze_gui_issues(screenshots_dir)
    
    # Generate report
    report = {
        "timestamp": datetime.now().isoformat(),
        "screenshots_location": str(screenshots_dir) if screenshots_dir else "No screenshots taken",
        "issues_found": issues,
        "improvement_suggestions": improvements,
        "detailed_recommendations": generate_improvement_recommendations()
    }
    
    # Save report
    report_file = Path("gui_analysis_report.json")
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\n=== Analysis Complete ===")
    print(f"Report saved to: {report_file}")
    print(f"Screenshots saved to: {screenshots_dir}")
    
    if issues:
        print(f"\n⚠️  Issues found: {len(issues)}")
        for issue in issues:
            print(f"  - {issue}")
    
    if improvements:
        print(f"\n💡 Improvements suggested: {len(improvements[:5])}")
        for improvement in improvements[:5]:
            print(f"  - {improvement}")
    
    print("\nCheck gui_analysis_report.json for detailed recommendations")

if __name__ == "__main__":
    main()