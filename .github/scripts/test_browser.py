#!/usr/bin/env python3
"""Simple browser test for CI/CD"""
from playwright.sync_api import sync_playwright
import json
import sys

def main():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("http://127.0.0.1:8899", wait_until="networkidle", timeout=30000)
            title = page.title()
            print(f"Page title: {title}")
            
            with open("/app/test-results/browser_test_results.json", "w") as f:
                json.dump({"title": title, "success": True}, f, indent=2)
            
            browser.close()
            print("✅ Browser test completed")
    except Exception as e:
        print(f"❌ Browser test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
