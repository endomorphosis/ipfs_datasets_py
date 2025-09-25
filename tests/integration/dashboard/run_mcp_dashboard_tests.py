#!/usr/bin/env python3
"""
MCP Dashboard Test Runner

This script provides a comprehensive test runner for the MCP dashboard
with support for different test modes, reporting, and CI/CD integration.

Usage:
    python run_mcp_dashboard_tests.py --help
    python run_mcp_dashboard_tests.py --mode comprehensive
    python run_mcp_dashboard_tests.py --mode smoke --browser firefox
    python run_mcp_dashboard_tests.py --docker --report-format html
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

try:
    import requests
except ImportError:
    requests = None

# Set up logging
def setup_logging():
    """Set up logging with proper directory creation."""
    test_outputs_dir = Path("test_outputs")
    test_outputs_dir.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(test_outputs_dir / 'test_runner.log')
        ]
    )

logger = logging.getLogger(__name__)


class MCPDashboardTestRunner:
    """
    Comprehensive test runner for MCP dashboard testing.
    
    Supports multiple test modes, browsers, and reporting formats.
    """
    
    def __init__(self, 
                 mode: str = "comprehensive",
                 browser: str = "chromium", 
                 headless: bool = True,
                 docker: bool = False,
                 report_format: str = "html"):
        """
        Initialize the test runner.
        
        Args:
            mode: Test mode (smoke, comprehensive, performance, accessibility)
            browser: Browser to use (chromium, firefox, webkit)
            headless: Run browser in headless mode
            docker: Use Docker for testing
            report_format: Report format (html, json, junit)
        """
        self.mode = mode
        self.browser = browser
        self.headless = headless
        self.docker = docker
        self.report_format = report_format
        self.test_outputs_dir = Path("test_outputs")
        self.test_outputs_dir.mkdir(exist_ok=True)
        
        # Test configuration
        self.test_configs = {
            "smoke": {
                "tests": ["test_mcp_dashboard_api_endpoints"],
                "timeout": 300,
                "description": "Basic smoke tests for critical functionality"
            },
            "comprehensive": {
                "tests": ["test_mcp_dashboard_comprehensive"],
                "timeout": 1800,
                "description": "Full comprehensive testing suite"
            },
            "performance": {
                "tests": ["test_mcp_dashboard_performance"],
                "timeout": 600,
                "description": "Performance and load testing"
            },
            "accessibility": {
                "tests": ["test_mcp_dashboard_accessibility"],
                "timeout": 900,
                "description": "Accessibility compliance testing"
            },
            "api": {
                "tests": ["test_mcp_dashboard_api_endpoints"],
                "timeout": 300,
                "description": "API endpoint testing"
            },
            "ui": {
                "tests": ["test_mcp_dashboard_ui"],
                "timeout": 900,
                "description": "UI and visual testing"
            }
        }
    
    async def run_tests(self) -> Dict[str, any]:
        """
        Run the specified test suite.
        
        Returns:
            Dict containing test results and metadata
        """
        logger.info(f"Starting MCP dashboard tests in {self.mode} mode")
        start_time = time.time()
        
        try:
            # Prepare test environment
            await self._prepare_test_environment()
            
            # Check prerequisites
            if not self._check_prerequisites():
                raise RuntimeError("Prerequisites check failed")
            
            # Start services if needed
            services_started = await self._start_required_services()
            
            try:
                # Run tests
                test_results = await self._execute_tests()
                
                # Generate reports
                await self._generate_reports(test_results)
                
                # Analyze results
                analysis = self._analyze_results(test_results)
                
                return {
                    "mode": self.mode,
                    "browser": self.browser,
                    "duration": time.time() - start_time,
                    "timestamp": datetime.now().isoformat(),
                    "results": test_results,
                    "analysis": analysis,
                    "success": analysis["success"]
                }
                
            finally:
                if services_started:
                    await self._stop_services()
                    
        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            return {
                "mode": self.mode,
                "browser": self.browser,
                "duration": time.time() - start_time,
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "success": False
            }
    
    async def _prepare_test_environment(self):
        """Prepare the test environment."""
        logger.info("Preparing test environment...")
        
        # Create necessary directories
        (self.test_outputs_dir / "screenshots").mkdir(exist_ok=True)
        (self.test_outputs_dir / "reports").mkdir(exist_ok=True)
        (self.test_outputs_dir / "logs").mkdir(exist_ok=True)
        
        # Install browser if needed
        if not self.docker:
            await self._ensure_browser_installed()
    
    def _check_prerequisites(self) -> bool:
        """Check if all prerequisites are met."""
        logger.info("Checking prerequisites...")
        
        try:
            import playwright
            import pytest
            logger.info("✓ Playwright and pytest available")
        except ImportError as e:
            logger.error(f"✗ Missing required packages: {e}")
            return False
        
        # Check if test files exist
        test_file = Path("tests/integration/dashboard/comprehensive_mcp_dashboard_test.py")
        if not test_file.exists():
            logger.error(f"✗ Test file not found: {test_file}")
            return False
        
        logger.info("✓ Test files found")
        return True
    
    async def _ensure_browser_installed(self):
        """Ensure the required browser is installed."""
        logger.info(f"Ensuring {self.browser} browser is installed...")
        
        try:
            result = subprocess.run([
                sys.executable, "-m", "playwright", "install", self.browser
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                logger.info(f"✓ {self.browser} browser ready")
            else:
                logger.warning(f"Browser installation output: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            logger.warning("Browser installation timed out, proceeding anyway")
        except Exception as e:
            logger.warning(f"Browser installation failed: {e}")
    
    async def _start_required_services(self) -> bool:
        """Start required services for testing."""
        if self.docker:
            return await self._start_docker_services()
        else:
            return await self._start_local_services()
    
    async def _start_docker_services(self) -> bool:
        """Start services using Docker Compose."""
        logger.info("Starting Docker services...")
        
        def _compose_cmd(args: list[str]) -> subprocess.CompletedProcess:
            try:
                return subprocess.run([
                    "docker-compose", *args
                ], capture_output=True, text=True, timeout=600)
            except FileNotFoundError:
                # Fallback to `docker compose ...`
                logger.info("docker-compose not found, falling back to 'docker compose'.")
                return subprocess.run([
                    "docker", "compose", *args
                ], capture_output=True, text=True, timeout=600)
        
        try:
            # Start MCP server and dashboard
            args = ["-f", "docker-compose.mcp.yml", "up", "-d", "mcp-server", "mcp-dashboard"]
            result = _compose_cmd(args)
            
            if result.returncode != 0:
                logger.error(f"Failed to start Docker services: {result.stderr or result.stdout}")
                return False
            
            # Wait for services to be healthy
            await self._wait_for_services_health()
            return True
            
        except Exception as e:
            logger.error(f"Docker service startup failed: {e}")
            return False
    
    async def _start_local_services(self) -> bool:
        """Start services locally for testing."""
        logger.info("Starting local services...")
        
        # For now, assume services are already running
        # In a real implementation, we would start the dashboard process
        await self._wait_for_services_health()
        return True
    
    async def _wait_for_services_health(self, timeout: int = 60):
        """Wait for services to become healthy."""
        logger.info("Waiting for services to become healthy...")
        
        if not requests:
            logger.warning("Requests not available, skipping health check")
            return
        
        start_time = time.time()
        dashboard_url = "http://localhost:8899/api/mcp/status"
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get(dashboard_url, timeout=5)
                if response.status_code == 200:
                    logger.info("✓ Services are healthy")
                    return
            except:
                pass
            
            await asyncio.sleep(2)
        
        logger.warning("Services health check timed out")
    
    async def _execute_tests(self) -> Dict[str, any]:
        """Execute the test suite."""
        logger.info(f"Executing {self.mode} tests...")
        
        config = self.test_configs.get(self.mode, self.test_configs["comprehensive"])
        
        # Build pytest command
        cmd = [
            sys.executable, "-m", "pytest",
            "tests/integration/dashboard/comprehensive_mcp_dashboard_test.py",
            "-v",
            f"--timeout={config['timeout']}",
            f"--html={self.test_outputs_dir}/reports/report.html",
            "--self-contained-html"
        ]
        
        # Add specific test selection if configured
        if config["tests"]:
            for test in config["tests"]:
                cmd.extend(["-k", test])
        
        # Add browser-specific options
        if not self.headless:
            cmd.append("--headed")
        
        # Execute tests
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True,
                timeout=config["timeout"] + 60,
                cwd=Path(__file__).parent.parent.parent.parent
            )
            
            return {
                "command": " ".join(cmd),
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0
            }
            
        except subprocess.TimeoutExpired:
            return {
                "command": " ".join(cmd),
                "returncode": -1,
                "error": "Test execution timed out",
                "success": False
            }
        except Exception as e:
            return {
                "command": " ".join(cmd),
                "returncode": -1,
                "error": str(e),
                "success": False
            }
    
    async def _generate_reports(self, test_results: Dict[str, any]):
        """Generate test reports in various formats."""
        logger.info("Generating test reports...")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # JSON report
        json_report = self.test_outputs_dir / f"reports/test_results_{timestamp}.json"
        with open(json_report, "w") as f:
            json.dump(test_results, f, indent=2, default=str)
        
        logger.info(f"✓ JSON report: {json_report}")
        
        # Summary report
        summary_report = self.test_outputs_dir / f"reports/test_summary_{timestamp}.txt"
        with open(summary_report, "w") as f:
            f.write(f"MCP Dashboard Test Summary\n")
            f.write(f"========================\n\n")
            f.write(f"Mode: {self.mode}\n")
            f.write(f"Browser: {self.browser}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Success: {test_results.get('success', False)}\n\n")
            
            if test_results.get("stdout"):
                f.write("Test Output:\n")
                f.write("------------\n")
                f.write(test_results["stdout"])
            
            if test_results.get("stderr"):
                f.write("\n\nTest Errors:\n")
                f.write("------------\n")
                f.write(test_results["stderr"])
        
        logger.info(f"✓ Summary report: {summary_report}")
    
    def _analyze_results(self, test_results: Dict[str, any]) -> Dict[str, any]:
        """Analyze test results and provide insights."""
        analysis = {
            "success": test_results.get("success", False),
            "total_tests": 0,
            "passed_tests": 0,
            "failed_tests": 0,
            "skipped_tests": 0,
            "errors": [],
            "warnings": [],
            "recommendations": []
        }
        
        # Parse pytest output for test counts
        stdout = test_results.get("stdout", "")
        stderr = test_results.get("stderr", "")
        
        # Look for pytest summary line
        for line in stdout.split("\n"):
            if "passed" in line and "failed" in line:
                # Extract test counts from pytest output
                # This is a simplified parser
                pass
        
        # Analyze common issues
        if "FAILED" in stdout:
            analysis["recommendations"].append(
                "Some tests failed. Check the HTML report for detailed failure information."
            )
        
        if "timeout" in stderr.lower():
            analysis["recommendations"].append(
                "Tests timed out. Consider increasing timeout or optimizing test performance."
            )
        
        if "connection" in stderr.lower():
            analysis["recommendations"].append(
                "Connection issues detected. Verify services are running and accessible."
            )
        
        return analysis
    
    async def _stop_services(self):
        """Stop test services."""
        if self.docker:
            logger.info("Stopping Docker services...")
            args = ["-f", "docker-compose.mcp.yml", "down"]
            try:
                subprocess.run(["docker-compose", *args], capture_output=True)
            except FileNotFoundError:
                subprocess.run(["docker", "compose", *args], capture_output=True)


def main():
    """Main entry point for the test runner."""
    # Set up logging first
    setup_logging()
    
    parser = argparse.ArgumentParser(
        description="MCP Dashboard Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_mcp_dashboard_tests.py --mode smoke
  python run_mcp_dashboard_tests.py --mode comprehensive --browser firefox
  python run_mcp_dashboard_tests.py --docker --report-format json
  python run_mcp_dashboard_tests.py --mode performance --headless false
        """
    )
    
    parser.add_argument(
        "--mode", 
        choices=["smoke", "comprehensive", "performance", "accessibility", "api", "ui"],
        default="comprehensive",
        help="Test mode to run (default: comprehensive)"
    )
    
    parser.add_argument(
        "--browser",
        choices=["chromium", "firefox", "webkit"],
        default="chromium", 
        help="Browser to use for testing (default: chromium)"
    )
    
    parser.add_argument(
        "--headless",
        type=str,
        choices=["true", "false"],
        default="true",
        help="Run browser in headless mode (default: true)"
    )
    
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Use Docker for service deployment"
    )
    
    parser.add_argument(
        "--report-format",
        choices=["html", "json", "junit"],
        default="html",
        help="Report format (default: html)"
    )
    
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("test_outputs"),
        help="Output directory for test results"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create test runner
    runner = MCPDashboardTestRunner(
        mode=args.mode,
        browser=args.browser,
        headless=args.headless.lower() == "true",
        docker=args.docker,
        report_format=args.report_format
    )
    
    # Run tests
    async def run():
        results = await runner.run_tests()
        
        # Print summary
        print("\n" + "="*60)
        print("MCP DASHBOARD TEST SUMMARY")
        print("="*60)
        print(f"Mode: {results['mode']}")
        print(f"Browser: {results['browser']}")
        print(f"Duration: {results['duration']:.2f}s")
        print(f"Success: {'✓' if results['success'] else '✗'}")
        
        if not results['success']:
            print(f"Error: {results.get('error', 'Unknown error')}")
            sys.exit(1)
        else:
            print("All tests passed successfully!")
            
        print("\nReports generated in: test_outputs/reports/")
        print("Screenshots saved in: test_outputs/screenshots/")
    
    # Run the async function
    asyncio.run(run())


if __name__ == "__main__":
    main()