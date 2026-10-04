#!/usr/bin/env python3
"""
Check GitHub Actions Self-Hosted Runner Availability

This script checks if self-hosted runners with specific labels are available
before running workflows that depend on them. This prevents workflow failures
when runners are offline.

Usage:
    python check_runner_availability.py --labels linux,x64,self-hosted
    python check_runner_availability.py --labels linux,arm64,self-hosted
    python check_runner_availability.py --labels linux,x64,gpu,self-hosted
    
Exit Codes:
    0 - Runners available
    1 - No runners available (graceful skip)
    2 - Error checking runners (API error, auth failure, etc.)
"""

import os
import sys
import argparse
import json
from typing import List, Dict, Any
import requests
import time


class RunnerAvailabilityChecker:
    """Check availability of GitHub Actions self-hosted runners."""
    
    def __init__(self, token: str, repo: str):
        """
        Initialize the checker.
        
        Args:
            token: GitHub token for API authentication
            repo: Repository in format 'owner/repo'
        """
        self.token = token
        self.repo = repo
        self.api_base = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
    
    def get_runners(self) -> List[Dict[str, Any]]:
        """
        Fetch all self-hosted runners for the repository.
        
        Returns:
            List of runner dictionaries
            
        Raises:
            Exception: If API call fails
        """
        url = f"{self.api_base}/repos/{self.repo}/actions/runners"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get('runners', [])
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching runners: {e}", file=sys.stderr)
            raise
    
    def check_runner_availability(self, required_labels: List[str]) -> bool:
        """
        Check if any runner with the required labels is online and available.
        
        Args:
            required_labels: List of labels that runner must have
            
        Returns:
            True if at least one matching runner is available, False otherwise
        """
        try:
            runners = self.get_runners()
            
            if not runners:
                print("⚠️  No runners found in repository", file=sys.stderr)
                return False
            
            # Normalize required labels (lowercase, sorted)
            required_set = set(label.lower().strip() for label in required_labels)
            
            matching_runners = []
            for runner in runners:
                # Get runner labels
                runner_labels = set(label['name'].lower() for label in runner.get('labels', []))
                
                # Check if runner has all required labels
                if required_set.issubset(runner_labels):
                    status = runner.get('status', 'unknown')
                    busy = runner.get('busy', False)
                    
                    matching_runners.append({
                        'name': runner.get('name', 'unknown'),
                        'status': status,
                        'busy': busy,
                        'labels': sorted(runner_labels)
                    })
            
            if not matching_runners:
                print(f"⚠️  No runners found with labels: {', '.join(required_labels)}", file=sys.stderr)
                return False
            
            # Check if any matching runner is online (and optionally not busy)
            available_runners = [
                r for r in matching_runners 
                if r['status'] == 'online'
            ]
            
            if not available_runners:
                print(f"⚠️  Found {len(matching_runners)} matching runner(s), but none are online", file=sys.stderr)
                for r in matching_runners:
                    print(f"   - {r['name']}: status={r['status']}, busy={r['busy']}", file=sys.stderr)
                return False
            
            # Found available runners
            print(f"✅ Found {len(available_runners)} available runner(s) with labels: {', '.join(required_labels)}")
            for r in available_runners[:3]:  # Show first 3
                status_icon = "🔴" if r['busy'] else "🟢"
                print(f"   {status_icon} {r['name']}: status={r['status']}, busy={r['busy']}")
            
            if len(available_runners) > 3:
                print(f"   ... and {len(available_runners) - 3} more")
            
            return True
            
        except Exception as e:
            print(f"❌ Error checking runner availability: {e}", file=sys.stderr)
            raise
    
    def check_with_retry(self, required_labels: List[str], max_retries: int = 3, delay: int = 2) -> bool:
        """
        Check runner availability with retries.
        
        Args:
            required_labels: List of labels that runner must have
            max_retries: Maximum number of retry attempts
            delay: Delay between retries in seconds
            
        Returns:
            True if runners available, False otherwise
        """
        for attempt in range(max_retries):
            try:
                return self.check_runner_availability(required_labels)
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"⚠️  Attempt {attempt + 1}/{max_retries} failed, retrying in {delay}s...", file=sys.stderr)
                    time.sleep(delay)
                else:
                    print(f"❌ All {max_retries} attempts failed", file=sys.stderr)
                    raise


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Check GitHub Actions self-hosted runner availability",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check for linux x64 runners
  python check_runner_availability.py --labels self-hosted,linux,x64
  
  # Check for GPU runners
  python check_runner_availability.py --labels self-hosted,linux,x64,gpu
  
  # Check for ARM64 runners
  python check_runner_availability.py --labels self-hosted,linux,arm64

Exit Codes:
  0 - Runners available and online
  1 - No runners available (graceful skip)
  2 - Error checking runners (API error, etc.)
        """
    )
    
    parser.add_argument(
        '--labels',
        required=True,
        help='Comma-separated list of required runner labels'
    )
    
    parser.add_argument(
        '--token',
        default=os.environ.get('GITHUB_TOKEN'),
        help='GitHub token (default: GITHUB_TOKEN env var)'
    )
    
    parser.add_argument(
        '--repo',
        default=os.environ.get('GITHUB_REPOSITORY'),
        help='Repository in format owner/repo (default: GITHUB_REPOSITORY env var)'
    )
    
    parser.add_argument(
        '--retries',
        type=int,
        default=3,
        help='Number of retry attempts (default: 3)'
    )
    
    parser.add_argument(
        '--delay',
        type=int,
        default=2,
        help='Delay between retries in seconds (default: 2)'
    )
    
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results as JSON'
    )
    
    args = parser.parse_args()
    
    # Validate inputs
    if not args.token:
        print("❌ Error: GITHUB_TOKEN not provided", file=sys.stderr)
        print("   Set GITHUB_TOKEN environment variable or use --token", file=sys.stderr)
        sys.exit(2)
    
    if not args.repo:
        print("❌ Error: GITHUB_REPOSITORY not provided", file=sys.stderr)
        print("   Set GITHUB_REPOSITORY environment variable or use --repo", file=sys.stderr)
        sys.exit(2)
    
    # Parse labels
    required_labels = [label.strip() for label in args.labels.split(',') if label.strip()]
    if not required_labels:
        print("❌ Error: No labels provided", file=sys.stderr)
        sys.exit(2)
    
    # Check runner availability
    try:
        checker = RunnerAvailabilityChecker(args.token, args.repo)
        available = checker.check_with_retry(
            required_labels,
            max_retries=args.retries,
            delay=args.delay
        )
        
        if args.json:
            result = {
                "available": available,
                "labels": required_labels,
                "repository": args.repo
            }
            print(json.dumps(result, indent=2))
        
        if available:
            print("\n✅ Self-hosted runners are available")
            sys.exit(0)
        else:
            print("\n⚠️  No self-hosted runners available - workflow will skip")
            sys.exit(1)
            
    except Exception as e:
        if args.json:
            result = {
                "available": False,
                "error": str(e),
                "labels": required_labels,
                "repository": args.repo
            }
            print(json.dumps(result, indent=2))
        
        print(f"\n❌ Error checking runner availability: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
