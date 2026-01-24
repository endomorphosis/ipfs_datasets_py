#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Comprehensive GUI Testing Script for News Analysis Dashboard

This script starts the dashboard server, captures screenshots of all views,
analyzes the GUI for issues, and provides improvement recommendations.
"""

import os
import sys
import time
import json
import anyio
import threading
import webbrowser
from pathlib import Path
from datetime import datetime
from html2image import Html2Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

class ComprehensiveGUITester:
    """Comprehensive GUI testing class with screenshot analysis."""
    
    def __init__(self):
        self.screenshots_dir = Path("gui_analysis_screenshots")
        self.screenshots_dir.mkdir(exist_ok=True)
        
        self.analysis_results = {
            "timestamp": datetime.now().isoformat(),
            "screenshots": [],
            "gui_issues": [],
            "improvements": [],
            "test_results": {}
        }
        
        # Dashboard server process
        self.server_process = None
        self.server_url = "http://localhost:8080"
        
    def setup_chrome_driver(self):
        """Set up Chrome driver with appropriate options."""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        
        try:
            driver = webdriver.Chrome(options=chrome_options)
            return driver
        except Exception as e:
            print(f"Failed to setup Chrome driver: {e}")
            return None
    
    def start_dashboard_server(self):
        """Start the news analysis dashboard server."""
        try:
            # Import and start dashboard
            from ipfs_datasets_py.news_analysis_dashboard import NewsAnalysisDashboard, MCPDashboardConfig
            
            config = MCPDashboardConfig()
            dashboard = NewsAnalysisDashboard(config)
            
            def run_server():
                dashboard.start()
            
            # Start server in background thread
            server_thread = threading.Thread(target=run_server, daemon=True)
            server_thread.start()
            
            # Wait for server to start
            time.sleep(5)
            print(f"✓ Dashboard server started at {self.server_url}")
            return True
            
        except Exception as e:
            print(f"✗ Failed to start dashboard server: {e}")
            return False
    
    def capture_screenshot(self, driver, url, filename, description=""):
        """Capture screenshot of a specific URL."""
        try:
            print(f"Capturing screenshot: {filename}")
            driver.get(url)
            
            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Additional wait for dynamic content
            time.sleep(2)
            
            # Capture screenshot
            screenshot_path = self.screenshots_dir / f"{filename}.png"
            driver.save_screenshot(str(screenshot_path))
            
            # Record screenshot info
            self.analysis_results["screenshots"].append({
                "filename": f"{filename}.png",
                "url": url,
                "description": description,
                "timestamp": datetime.now().isoformat(),
                "path": str(screenshot_path)
            })
            
            print(f"✓ Screenshot saved: {screenshot_path}")
            return screenshot_path
            
        except Exception as e:
            print(f"✗ Failed to capture screenshot {filename}: {e}")
            return None
    
    def analyze_gui_elements(self, driver):
        """Analyze GUI elements for accessibility and usability issues."""
        issues = []
        
        try:
            # Check for missing alt attributes on images
            images = driver.find_elements(By.TAG_NAME, "img")
            for img in images:
                if not img.get_attribute("alt"):
                    issues.append({
                        "type": "accessibility",
                        "severity": "high",
                        "element": "img",
                        "issue": "Missing alt attribute",
                        "location": img.get_attribute("src") or "unknown"
                    })
            
            # Check for missing ARIA labels on interactive elements
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                if not btn.get_attribute("aria-label") and not btn.get_attribute("title"):
                    text_content = btn.get_attribute("textContent").strip()
                    if not text_content:
                        issues.append({
                            "type": "accessibility",
                            "severity": "medium",
                            "element": "button",
                            "issue": "Button without accessible label",
                            "location": btn.get_attribute("class") or "unknown"
                        })
            
            # Check for form inputs without labels
            inputs = driver.find_elements(By.TAG_NAME, "input")
            for input_elem in inputs:
                input_id = input_elem.get_attribute("id")
                if input_id:
                    # Check if there's a label for this input
                    labels = driver.find_elements(By.CSS_SELECTOR, f"label[for='{input_id}']")
                    if not labels and not input_elem.get_attribute("aria-label"):
                        issues.append({
                            "type": "accessibility",
                            "severity": "high",
                            "element": "input",
                            "issue": "Input without associated label",
                            "location": input_id
                        })
            
            # Check for proper heading hierarchy
            headings = driver.find_elements(By.CSS_SELECTOR, "h1, h2, h3, h4, h5, h6")
            if headings:
                last_level = 0
                for heading in headings:
                    level = int(heading.tag_name[1])
                    if level > last_level + 1:
                        issues.append({
                            "type": "accessibility",
                            "severity": "low",
                            "element": heading.tag_name,
                            "issue": f"Skipped heading level from h{last_level} to h{level}",
                            "location": heading.get_attribute("textContent")[:50]
                        })
                    last_level = level
            
            # Check color contrast (basic check for background/text colors)
            elements_with_style = driver.find_elements(By.CSS_SELECTOR, "*[style*='color']")
            for elem in elements_with_style[:10]:  # Limit to first 10 for performance
                style = elem.get_attribute("style")
                if "background-color" in style and "color" in style:
                    # This would need more sophisticated color contrast calculation
                    # For now, just flag for manual review
                    issues.append({
                        "type": "accessibility",
                        "severity": "low",
                        "element": elem.tag_name,
                        "issue": "Element with custom colors - manual contrast check needed",
                        "location": elem.get_attribute("class") or "unknown"
                    })
            
        except Exception as e:
            print(f"Error during GUI analysis: {e}")
        
        return issues
    
    def test_interactive_elements(self, driver):
        """Test interactive elements for functionality."""
        test_results = {}
        
        try:
            # Test navigation tabs
            tabs = driver.find_elements(By.CSS_SELECTOR, ".nav-tabs a, .tab-link, [role='tab']")
            tab_results = {"total": len(tabs), "clickable": 0, "issues": []}
            
            for i, tab in enumerate(tabs[:5]):  # Limit to first 5 tabs
                try:
                    if tab.is_enabled() and tab.is_displayed():
                        # Don't actually click to avoid changing state, just check if clickable
                        tab_results["clickable"] += 1
                    else:
                        tab_results["issues"].append(f"Tab {i+1} not clickable or visible")
                except Exception as e:
                    tab_results["issues"].append(f"Tab {i+1} error: {str(e)}")
            
            test_results["navigation_tabs"] = tab_results
            
            # Test form elements
            forms = driver.find_elements(By.TAG_NAME, "form")
            form_results = {"total": len(forms), "functional": 0, "issues": []}
            
            for i, form in enumerate(forms):
                try:
                    inputs = form.find_elements(By.TAG_NAME, "input")
                    if inputs:
                        form_results["functional"] += 1
                    else:
                        form_results["issues"].append(f"Form {i+1} has no input elements")
                except Exception as e:
                    form_results["issues"].append(f"Form {i+1} error: {str(e)}")
            
            test_results["forms"] = form_results
            
            # Test buttons
            buttons = driver.find_elements(By.TAG_NAME, "button")
            button_results = {"total": len(buttons), "enabled": 0, "disabled": 0}
            
            for button in buttons:
                try:
                    if button.is_enabled():
                        button_results["enabled"] += 1
                    else:
                        button_results["disabled"] += 1
                except:
                    pass
            
            test_results["buttons"] = button_results
            
        except Exception as e:
            print(f"Error during interactive element testing: {e}")
        
        return test_results
    
    def run_comprehensive_test(self):
        """Run comprehensive GUI testing and analysis."""
        print("Starting comprehensive GUI testing...")
        
        # Start dashboard server
        if not self.start_dashboard_server():
            print("Failed to start server, cannot continue testing")
            return
        
        # Setup Chrome driver
        driver = self.setup_chrome_driver()
        if not driver:
            print("Failed to setup Chrome driver, cannot continue testing")
            return
        
        try:
            # Test scenarios with different URL fragments and interactions
            test_scenarios = [
                {
                    "name": "main_dashboard",
                    "url": self.server_url,
                    "description": "Main dashboard view"
                },
                {
                    "name": "overview_tab",
                    "url": f"{self.server_url}#overview",
                    "description": "Overview tab with statistics"
                },
                {
                    "name": "ingest_tab",
                    "url": f"{self.server_url}#ingest",
                    "description": "Article ingestion interface"
                },
                {
                    "name": "timeline_tab",
                    "url": f"{self.server_url}#timeline",
                    "description": "Timeline analysis view"
                },
                {
                    "name": "query_tab",
                    "url": f"{self.server_url}#query",
                    "description": "GraphRAG query interface"
                },
                {
                    "name": "graph_explorer",
                    "url": f"{self.server_url}#graph-explorer",
                    "description": "Interactive graph explorer"
                },
                {
                    "name": "export_tab",
                    "url": f"{self.server_url}#export",
                    "description": "Professional export interface"
                },
                {
                    "name": "workflows_tab",
                    "url": f"{self.server_url}#workflows",
                    "description": "Professional workflows"
                }
            ]
            
            # Capture screenshots for each scenario
            for scenario in test_scenarios:
                screenshot_path = self.capture_screenshot(
                    driver, 
                    scenario["url"],
                    scenario["name"],
                    scenario["description"]
                )
                
                if screenshot_path:
                    # Analyze GUI elements for this view
                    issues = self.analyze_gui_elements(driver)
                    self.analysis_results["gui_issues"].extend(issues)
                    
                    # Test interactive elements
                    test_results = self.test_interactive_elements(driver)
                    self.analysis_results["test_results"][scenario["name"]] = test_results
            
            # Test different user themes by simulating theme changes
            themes = ["data-scientist", "historian", "lawyer"]
            for theme in themes:
                # Use JavaScript to change theme
                try:
                    driver.execute_script(f"""
                        document.body.className = document.body.className.replace(/theme-\\w+/, 'theme-{theme}');
                        if (window.changeUserType) window.changeUserType('{theme}');
                    """)
                    time.sleep(1)
                    
                    self.capture_screenshot(
                        driver,
                        self.server_url,
                        f"theme_{theme}",
                        f"Dashboard with {theme.replace('-', ' ').title()} theme"
                    )
                except Exception as e:
                    print(f"Could not test theme {theme}: {e}")
            
            # Test mobile responsiveness
            mobile_sizes = [
                (375, 667),  # iPhone SE
                (414, 896),  # iPhone XR
                (768, 1024)  # iPad
            ]
            
            for width, height in mobile_sizes:
                try:
                    driver.set_window_size(width, height)
                    time.sleep(1)
                    
                    self.capture_screenshot(
                        driver,
                        self.server_url,
                        f"mobile_{width}x{height}",
                        f"Mobile view {width}x{height}"
                    )
                    
                    # Test mobile-specific issues
                    mobile_issues = self.analyze_mobile_responsiveness(driver)
                    self.analysis_results["gui_issues"].extend(mobile_issues)
                    
                except Exception as e:
                    print(f"Could not test mobile size {width}x{height}: {e}")
            
        finally:
            driver.quit()
        
        # Generate improvement recommendations
        self.generate_improvement_recommendations()
        
        # Save analysis results
        self.save_analysis_results()
        
        print(f"\n✓ Comprehensive GUI testing completed!")
        print(f"Screenshots saved in: {self.screenshots_dir}")
        print(f"Analysis results: gui_analysis_results.json")
        
        return self.analysis_results
    
    def analyze_mobile_responsiveness(self, driver):
        """Analyze mobile responsiveness issues."""
        issues = []
        
        try:
            # Check for elements that overflow viewport
            viewport_width = driver.execute_script("return window.innerWidth;")
            elements = driver.find_elements(By.CSS_SELECTOR, "*")
            
            for elem in elements[:20]:  # Limit for performance
                try:
                    elem_width = elem.size['width']
                    if elem_width > viewport_width:
                        issues.append({
                            "type": "mobile_responsiveness",
                            "severity": "medium",
                            "element": elem.tag_name,
                            "issue": f"Element width ({elem_width}px) exceeds viewport ({viewport_width}px)",
                            "location": elem.get_attribute("class") or elem.tag_name
                        })
                except:
                    pass
            
            # Check for small touch targets
            clickable_elements = driver.find_elements(By.CSS_SELECTOR, "button, a, input[type='button'], input[type='submit']")
            for elem in clickable_elements:
                try:
                    size = elem.size
                    if size['width'] < 44 or size['height'] < 44:
                        issues.append({
                            "type": "mobile_usability",
                            "severity": "medium",
                            "element": elem.tag_name,
                            "issue": f"Touch target too small: {size['width']}x{size['height']}px (min 44x44px recommended)",
                            "location": elem.get_attribute("textContent")[:30] or elem.get_attribute("class")
                        })
                except:
                    pass
        
        except Exception as e:
            print(f"Error analyzing mobile responsiveness: {e}")
        
        return issues
    
    def generate_improvement_recommendations(self):
        """Generate improvement recommendations based on analysis."""
        issues_by_type = {}
        for issue in self.analysis_results["gui_issues"]:
            issue_type = issue["type"]
            if issue_type not in issues_by_type:
                issues_by_type[issue_type] = []
            issues_by_type[issue_type].append(issue)
        
        recommendations = []
        
        # Accessibility improvements
        if "accessibility" in issues_by_type:
            accessibility_issues = issues_by_type["accessibility"]
            high_priority = [i for i in accessibility_issues if i["severity"] == "high"]
            
            if high_priority:
                recommendations.append({
                    "priority": "high",
                    "category": "Accessibility",
                    "recommendation": "Add missing alt attributes to images and labels to form inputs",
                    "affected_elements": len(high_priority),
                    "implementation": "Add aria-label attributes and associate labels with form inputs"
                })
        
        # Mobile responsiveness improvements
        if "mobile_responsiveness" in issues_by_type:
            mobile_issues = issues_by_type["mobile_responsiveness"]
            recommendations.append({
                "priority": "medium",
                "category": "Mobile Responsiveness",
                "recommendation": "Fix elements that overflow viewport on mobile devices",
                "affected_elements": len(mobile_issues),
                "implementation": "Add responsive CSS media queries and max-width constraints"
            })
        
        # Touch target improvements
        if "mobile_usability" in issues_by_type:
            touch_issues = issues_by_type["mobile_usability"]
            recommendations.append({
                "priority": "medium", 
                "category": "Mobile Usability",
                "recommendation": "Increase touch target sizes for better mobile interaction",
                "affected_elements": len(touch_issues),
                "implementation": "Ensure buttons and links are at least 44x44px"
            })
        
        # General UI improvements based on test results
        test_results = self.analysis_results.get("test_results", {})
        for view, results in test_results.items():
            if "navigation_tabs" in results and results["navigation_tabs"]["issues"]:
                recommendations.append({
                    "priority": "low",
                    "category": "Navigation",
                    "recommendation": f"Fix navigation issues in {view}",
                    "affected_elements": len(results["navigation_tabs"]["issues"]),
                    "implementation": "Ensure all navigation tabs are properly functional"
                })
        
        self.analysis_results["improvements"] = recommendations
    
    def save_analysis_results(self):
        """Save analysis results to JSON file."""
        results_file = "gui_analysis_results.json"
        with open(results_file, 'w') as f:
            json.dump(self.analysis_results, f, indent=2)
        
        # Also create a human-readable summary
        self.create_analysis_summary()
    
    def create_analysis_summary(self):
        """Create a human-readable analysis summary."""
        summary_file = "gui_analysis_summary.md"
        
        with open(summary_file, 'w') as f:
            f.write("# GUI Analysis Summary\n\n")
            f.write(f"**Analysis Date:** {self.analysis_results['timestamp']}\n")
            f.write(f"**Total Screenshots:** {len(self.analysis_results['screenshots'])}\n")
            f.write(f"**Total Issues Found:** {len(self.analysis_results['gui_issues'])}\n\n")
            
            # Screenshots section
            f.write("## Screenshots Captured\n\n")
            for screenshot in self.analysis_results['screenshots']:
                f.write(f"- **{screenshot['filename']}**: {screenshot['description']}\n")
            f.write("\n")
            
            # Issues section
            if self.analysis_results['gui_issues']:
                f.write("## Issues Found\n\n")
                
                issues_by_severity = {"high": [], "medium": [], "low": []}
                for issue in self.analysis_results['gui_issues']:
                    severity = issue.get('severity', 'low')
                    if severity in issues_by_severity:
                        issues_by_severity[severity].append(issue)
                
                for severity in ['high', 'medium', 'low']:
                    if issues_by_severity[severity]:
                        f.write(f"### {severity.title()} Priority Issues\n\n")
                        for issue in issues_by_severity[severity]:
                            f.write(f"- **{issue['element']}**: {issue['issue']}\n")
                            f.write(f"  - Location: {issue['location']}\n")
                            f.write(f"  - Type: {issue['type']}\n\n")
            
            # Recommendations section
            if self.analysis_results['improvements']:
                f.write("## Improvement Recommendations\n\n")
                for rec in self.analysis_results['improvements']:
                    f.write(f"### {rec['category']} ({rec['priority']} priority)\n")
                    f.write(f"{rec['recommendation']}\n")
                    f.write(f"**Implementation:** {rec['implementation']}\n")
                    f.write(f"**Affected Elements:** {rec['affected_elements']}\n\n")

if __name__ == "__main__":
    tester = ComprehensiveGUITester()
    results = tester.run_comprehensive_test()
    
    print("\n" + "="*60)
    print("COMPREHENSIVE GUI TESTING COMPLETED")
    print("="*60)
    print(f"Screenshots: {len(results['screenshots'])}")
    print(f"Issues found: {len(results['gui_issues'])}")
    print(f"Recommendations: {len(results['improvements'])}")
    print("="*60)