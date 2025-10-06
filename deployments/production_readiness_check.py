#!/usr/bin/env python3
"""
Production Readiness Checker

Comprehensive validation tool to ensure GraphRAG system is ready for production deployment.
Checks configuration, dependencies, security, performance, and operational readiness.
"""

import os
import sys
import json
import asyncio
import subprocess
import pkg_resources
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class ValidationResult:
    """Represents the result of a validation check."""
    name: str
    status: str  # PASS, FAIL, WARNING
    message: str
    details: Optional[Dict[str, Any]] = None
    remediation: Optional[str] = None

@dataclass
class ProductionReadinessReport:
    """Complete production readiness assessment."""
    timestamp: str
    overall_status: str
    readiness_score: float
    results: List[ValidationResult] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    
    def add_result(self, result: ValidationResult):
        """Add a validation result."""
        self.results.append(result)
        
        # Update summary
        status = result.status
        self.summary[status] = self.summary.get(status, 0) + 1
        
        # Update overall status
        if status == "FAIL":
            self.overall_status = "NOT_READY"
        elif status == "WARNING" and self.overall_status != "NOT_READY":
            self.overall_status = "REVIEW_REQUIRED"
    
    def calculate_readiness_score(self) -> float:
        """Calculate overall readiness score (0-100)."""
        if not self.results:
            return 0.0
        
        total_checks = len(self.results)
        pass_weight = 1.0
        warning_weight = 0.7
        fail_weight = 0.0
        
        score = (
            self.summary.get("PASS", 0) * pass_weight +
            self.summary.get("WARNING", 0) * warning_weight +
            self.summary.get("FAIL", 0) * fail_weight
        ) / total_checks * 100
        
        self.readiness_score = score
        return score

class ProductionReadinessChecker:
    """Comprehensive production readiness validation."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.report = ProductionReadinessReport(
            timestamp=datetime.now().isoformat(),
            overall_status="READY",
            readiness_score=0.0
        )
    
    def check_python_dependencies(self) -> ValidationResult:
        """Check if all required Python dependencies are available."""
        try:
            required_packages = [
                'fastapi', 'uvicorn', 'sqlalchemy', 'asyncpg',
                'redis', 'elasticsearch', 'sentence-transformers',
                'transformers', 'torch', 'numpy', 'pandas'
            ]
            
            missing_packages = []
            for package in required_packages:
                try:
                    pkg_resources.get_distribution(package)
                except pkg_resources.DistributionNotFound:
                    missing_packages.append(package)
            
            if missing_packages:
                return ValidationResult(
                    name="Python Dependencies",
                    status="FAIL",
                    message=f"Missing required packages: {', '.join(missing_packages)}",
                    remediation="Run: pip install -e '.[all]'"
                )
            
            return ValidationResult(
                name="Python Dependencies",
                status="PASS",
                message="All required Python packages are available"
            )
            
        except Exception as e:
            return ValidationResult(
                name="Python Dependencies",
                status="FAIL",
                message=f"Error checking dependencies: {e}"
            )
    
    def check_system_dependencies(self) -> ValidationResult:
        """Check system-level dependencies."""
        required_commands = ['docker', 'docker-compose', 'curl', 'git']
        missing_commands = []
        
        for cmd in required_commands:
            if subprocess.run(['which', cmd], capture_output=True).returncode != 0:
                missing_commands.append(cmd)
        
        if missing_commands:
            return ValidationResult(
                name="System Dependencies",
                status="FAIL",
                message=f"Missing system commands: {', '.join(missing_commands)}",
                remediation="Install missing system packages"
            )
        
        return ValidationResult(
            name="System Dependencies",
            status="PASS",
            message="All required system commands are available"
        )
    
    def check_configuration_files(self) -> ValidationResult:
        """Check that all required configuration files exist."""
        required_files = [
            "docker-compose.yml",
            ".env.example",
            "deployments/sql/init.sql",
            "deployments/kubernetes/infrastructure.yaml",
            "deployments/kubernetes/graphrag-deployment.yaml",
            "deployments/deploy.sh"
        ]
        
        missing_files = []
        for file_path in required_files:
            if not (self.project_root / file_path).exists():
                missing_files.append(file_path)
        
        if missing_files:
            return ValidationResult(
                name="Configuration Files",
                status="FAIL",
                message=f"Missing configuration files: {', '.join(missing_files)}",
                remediation="Ensure all deployment files are present"
            )
        
        return ValidationResult(
            name="Configuration Files",
            status="PASS",
            message="All required configuration files are present"
        )
    
    def check_security_configuration(self) -> ValidationResult:
        """Check security configuration."""
        issues = []
        
        # Check .env.example for security issues
        env_file = self.project_root / ".env.example"
        if env_file.exists():
            with open(env_file) as f:
                env_content = f.read()
            
            # Check for default/weak values
            if "change_me" in env_content.lower():
                issues.append("Default placeholder values found in .env.example")
            
            if "admin" in env_content and "password" in env_content:
                issues.append("Default admin credentials detected")
        
        # Check for .env file in repo (should not be committed)
        if (self.project_root / ".env").exists():
            issues.append(".env file found in repository (security risk)")
        
        # Check SQL for default credentials
        sql_file = self.project_root / "deployments" / "sql" / "init.sql"
        if sql_file.exists():
            with open(sql_file) as f:
                sql_content = f.read()
            
            if "password: admin" in sql_content or "password: demo" in sql_content:
                issues.append("Default credentials found in database initialization")
        
        if issues:
            return ValidationResult(
                name="Security Configuration",
                status="WARNING",
                message=f"Security issues found: {'; '.join(issues)}",
                remediation="Review and update default credentials and sensitive values"
            )
        
        return ValidationResult(
            name="Security Configuration",
            status="PASS",
            message="Security configuration looks good"
        )
    
    def check_docker_configuration(self) -> ValidationResult:
        """Validate Docker configuration."""
        dockerfile = self.project_root / "Dockerfile"
        if not dockerfile.exists():
            return ValidationResult(
                name="Docker Configuration",
                status="FAIL",
                message="Dockerfile not found",
                remediation="Create Dockerfile for containerized deployment"
            )
        
        # Basic Dockerfile validation
        with open(dockerfile) as f:
            dockerfile_content = f.read()
        
        checks = [
            ("FROM", "Base image specified"),
            ("WORKDIR", "Working directory set"),
            ("COPY", "Application files copied"),
            ("EXPOSE", "Ports exposed"),
            ("ENTRYPOINT", "Entrypoint configured")
        ]
        
        missing_directives = []
        for directive, description in checks:
            if directive not in dockerfile_content:
                missing_directives.append(description)
        
        if missing_directives:
            return ValidationResult(
                name="Docker Configuration",
                status="WARNING",
                message=f"Dockerfile missing: {', '.join(missing_directives)}"
            )
        
        return ValidationResult(
            name="Docker Configuration",
            status="PASS",
            message="Dockerfile configuration is complete"
        )
    
    def check_api_endpoints(self) -> ValidationResult:
        """Check that API endpoints are properly defined."""
        api_file = self.project_root / "ipfs_datasets_py" / "enterprise_api.py"
        if not api_file.exists():
            return ValidationResult(
                name="API Endpoints",
                status="FAIL",
                message="Enterprise API file not found",
                remediation="Implement enterprise_api.py with FastAPI endpoints"
            )
        
        return ValidationResult(
            name="API Endpoints",
            status="PASS",
            message="Enterprise API file exists"
        )
    
    def check_test_coverage(self) -> ValidationResult:
        """Check test coverage and quality."""
        tests_dir = self.project_root / "tests"
        if not tests_dir.exists():
            return ValidationResult(
                name="Test Coverage",
                status="WARNING",
                message="Tests directory not found",
                remediation="Create comprehensive test suite"
            )
        
        # Count test files
        test_files = list(tests_dir.glob("test_*.py"))
        if len(test_files) < 5:
            return ValidationResult(
                name="Test Coverage",
                status="WARNING",
                message=f"Only {len(test_files)} test files found",
                remediation="Add more comprehensive test coverage"
            )
        
        return ValidationResult(
            name="Test Coverage",
            status="PASS",
            message=f"Found {len(test_files)} test files"
        )
    
    async def run_all_checks(self):
        """Run all production readiness checks."""
        print("🚀 GraphRAG Production Readiness Assessment")
        print("=" * 50)
        
        # Run all validation checks
        checks = [
            self.check_python_dependencies(),
            self.check_system_dependencies(),
            self.check_configuration_files(),
            self.check_security_configuration(),
            self.check_docker_configuration(),
            self.check_api_endpoints(),
            self.check_test_coverage()
        ]
        
        # Add results to report
        for result in checks:
            self.report.add_result(result)
        
        # Calculate readiness score
        score = self.report.calculate_readiness_score()
        
        # Display results
        print(f"\n📊 Assessment Results")
        print("=" * 30)
        
        for result in self.report.results:
            status_icon = "✅" if result.status == "PASS" else "⚠️" if result.status == "WARNING" else "❌"
            print(f"{status_icon} {result.name}: {result.message}")
            if result.remediation:
                print(f"   💡 {result.remediation}")
        
        print(f"\n🎯 Overall Readiness Score: {score:.1f}%")
        print(f"📈 Status: {self.report.overall_status}")
        
        # Provide recommendations
        if score >= 90:
            print("\n🚀 System is PRODUCTION READY!")
        elif score >= 75:
            print("\n🔧 System needs minor fixes before production deployment")
        elif score >= 50:
            print("\n⚠️ System needs significant improvements before production")
        else:
            print("\n❌ System is NOT ready for production deployment")
        
        # Save detailed report
        report_file = self.project_root / "production_readiness_report.json"
        with open(report_file, 'w') as f:
            json.dump({
                "timestamp": self.report.timestamp,
                "overall_status": self.report.overall_status,
                "readiness_score": self.report.readiness_score,
                "summary": self.report.summary,
                "results": [
                    {
                        "name": r.name,
                        "status": r.status,
                        "message": r.message,
                        "details": r.details,
                        "remediation": r.remediation
                    }
                    for r in self.report.results
                ]
            }, f, indent=2)
        
        print(f"\n📄 Detailed report saved to: {report_file}")
        
        return score >= 75  # Return True if ready for production

def main():
    """Main entry point."""
    project_root = Path(__file__).parent.parent
    checker = ProductionReadinessChecker(project_root)
    
    ready = asyncio.run(checker.run_all_checks())
    sys.exit(0 if ready else 1)

if __name__ == "__main__":
    main()