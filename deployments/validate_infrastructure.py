#!/usr/bin/env python3
"""
Infrastructure Validation Script

Validates that all infrastructure components are properly configured
and can be deployed successfully.
"""

import os
import sys
import yaml
import json
import asyncio
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

class InfrastructureValidator:
    """Validates GraphRAG system infrastructure configuration."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.errors = []
        self.warnings = []
    
    def validate_docker_compose(self) -> bool:
        """Validate Docker Compose configuration."""
        print("🐳 Validating Docker Compose configuration...")
        
        compose_file = self.project_root / "docker-compose.yml"
        if not compose_file.exists():
            self.errors.append("docker-compose.yml not found")
            return False
        
        try:
            # Validate YAML syntax
            with open(compose_file) as f:
                compose_config = yaml.safe_load(f)
            
            # Check required services
            required_services = [
                'postgres', 'redis', 'ipfs', 'elasticsearch',
                'website-graphrag-processor', 'job-worker'
            ]
            
            services = compose_config.get('services', {})
            for service in required_services:
                if service not in services:
                    self.errors.append(f"Required service '{service}' not found in docker-compose.yml")
            
            # Validate service configurations
            if 'website-graphrag-processor' in services:
                main_service = services['website-graphrag-processor']
                if 'depends_on' not in main_service:
                    self.warnings.append("website-graphrag-processor has no dependency constraints")
                
                if 'healthcheck' not in main_service:
                    self.warnings.append("website-graphrag-processor has no health check")
            
            print("✅ Docker Compose configuration valid")
            return True
            
        except yaml.YAMLError as e:
            self.errors.append(f"Invalid YAML in docker-compose.yml: {e}")
            return False
    
    def validate_kubernetes_manifests(self) -> bool:
        """Validate Kubernetes deployment manifests."""
        print("☸️ Validating Kubernetes manifests...")
        
        k8s_dir = self.project_root / "deployments" / "kubernetes"
        if not k8s_dir.exists():
            self.errors.append("Kubernetes deployment directory not found")
            return False
        
        required_files = [
            "infrastructure.yaml",
            "graphrag-deployment.yaml", 
            "ingress.yaml"
        ]
        
        for filename in required_files:
            file_path = k8s_dir / filename
            if not file_path.exists():
                self.errors.append(f"Required Kubernetes manifest not found: {filename}")
                continue
            
            try:
                # Validate YAML syntax
                with open(file_path) as f:
                    docs = list(yaml.safe_load_all(f))
                
                # Basic validation
                for doc in docs:
                    if not doc:
                        continue
                    
                    if 'apiVersion' not in doc:
                        self.errors.append(f"Missing apiVersion in {filename}")
                    
                    if 'kind' not in doc:
                        self.errors.append(f"Missing kind in {filename}")
                
                print(f"✅ {filename} is valid")
                
            except yaml.YAMLError as e:
                self.errors.append(f"Invalid YAML in {filename}: {e}")
                return False
        
        return True
    
    def validate_environment_files(self) -> bool:
        """Validate environment configuration files."""
        print("🔧 Validating environment configuration...")
        
        env_example = self.project_root / ".env.example"
        if not env_example.exists():
            self.errors.append(".env.example not found")
            return False
        
        # Check for required environment variables
        required_vars = [
            'POSTGRES_PASSWORD', 'JWT_SECRET_KEY', 'OPENAI_API_KEY',
            'POSTGRES_URL', 'REDIS_URL', 'IPFS_API_URL'
        ]
        
        with open(env_example) as f:
            env_content = f.read()
        
        for var in required_vars:
            if var not in env_content:
                self.errors.append(f"Required environment variable {var} not found in .env.example")
        
        print("✅ Environment configuration valid")
        return True
    
    def validate_database_schema(self) -> bool:
        """Validate database initialization SQL."""
        print("💾 Validating database schema...")
        
        sql_file = self.project_root / "deployments" / "sql" / "init.sql"
        if not sql_file.exists():
            self.errors.append("Database initialization SQL not found")
            return False
        
        with open(sql_file) as f:
            sql_content = f.read()
        
        # Check for required tables
        required_tables = [
            'users', 'processing_jobs', 'website_content',
            'kg_entities', 'kg_relationships', 'system_metrics'
        ]
        
        for table in required_tables:
            if f"CREATE TABLE IF NOT EXISTS {table}" not in sql_content:
                self.errors.append(f"Required table '{table}' not found in init.sql")
        
        print("✅ Database schema valid")
        return True
    
    def validate_deployment_scripts(self) -> bool:
        """Validate deployment automation scripts."""
        print("📜 Validating deployment scripts...")
        
        deploy_script = self.project_root / "deployments" / "deploy.sh"
        if not deploy_script.exists():
            self.errors.append("Deployment script not found")
            return False
        
        if not os.access(deploy_script, os.X_OK):
            self.warnings.append("Deployment script is not executable")
        
        entrypoint_script = self.project_root / "docker-entrypoint.sh"
        if not entrypoint_script.exists():
            self.errors.append("Docker entrypoint script not found")
            return False
        
        if not os.access(entrypoint_script, os.X_OK):
            self.warnings.append("Docker entrypoint script is not executable")
        
        print("✅ Deployment scripts valid")
        return True
    
    def validate_monitoring_config(self) -> bool:
        """Validate monitoring configuration."""
        print("📊 Validating monitoring configuration...")
        
        prometheus_config = self.project_root / "deployments" / "monitoring" / "prometheus.yml"
        if not prometheus_config.exists():
            self.errors.append("Prometheus configuration not found")
            return False
        
        try:
            with open(prometheus_config) as f:
                config = yaml.safe_load(f)
            
            if 'scrape_configs' not in config:
                self.errors.append("No scrape configs found in prometheus.yml")
            
            print("✅ Monitoring configuration valid")
            return True
            
        except yaml.YAMLError as e:
            self.errors.append(f"Invalid Prometheus configuration: {e}")
            return False
    
    def run_docker_compose_validation(self) -> bool:
        """Run docker-compose config validation."""
        try:
            result = subprocess.run(
                ["docker-compose", "config"],
                cwd=self.project_root,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                self.errors.append(f"docker-compose config validation failed: {result.stderr}")
                return False
            
            print("✅ Docker Compose configuration syntax valid")
            return True
            
        except FileNotFoundError:
            self.warnings.append("docker-compose not available for validation")
            return True
    
    def run_kubectl_validation(self) -> bool:
        """Run kubectl dry-run validation."""
        try:
            k8s_dir = self.project_root / "deployments" / "kubernetes"
            for yaml_file in k8s_dir.glob("*.yaml"):
                result = subprocess.run(
                    ["kubectl", "apply", "--dry-run=client", "-f", str(yaml_file)],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode != 0:
                    self.errors.append(f"Kubernetes validation failed for {yaml_file.name}: {result.stderr}")
                    return False
            
            print("✅ Kubernetes manifests syntax valid")
            return True
            
        except FileNotFoundError:
            self.warnings.append("kubectl not available for validation")
            return True
    
    def generate_report(self) -> Dict:
        """Generate validation report."""
        return {
            "timestamp": f"{datetime.now().isoformat()}",
            "status": "PASS" if not self.errors else "FAIL",
            "errors": self.errors,
            "warnings": self.warnings,
            "checks_run": [
                "docker_compose_config",
                "kubernetes_manifests", 
                "environment_files",
                "database_schema",
                "deployment_scripts",
                "monitoring_config"
            ]
        }

def main():
    """Main validation entry point."""
    project_root = Path(__file__).parent.parent
    validator = InfrastructureValidator(project_root)
    
    print("🏗️ GraphRAG Infrastructure Validation")
    print("=" * 50)
    
    # Run all validations
    validations = [
        validator.validate_docker_compose(),
        validator.validate_kubernetes_manifests(),
        validator.validate_environment_files(),
        validator.validate_database_schema(),
        validator.validate_deployment_scripts(),
        validator.validate_monitoring_config(),
        validator.run_docker_compose_validation(),
        validator.run_kubectl_validation()
    ]
    
    # Generate and display report
    report = validator.generate_report()
    
    print("\n📋 Validation Report")
    print("=" * 30)
    print(f"Status: {report['status']}")
    
    if validator.errors:
        print("\n❌ Errors:")
        for error in validator.errors:
            print(f"  - {error}")
    
    if validator.warnings:
        print("\n⚠️ Warnings:")
        for warning in validator.warnings:
            print(f"  - {warning}")
    
    if not validator.errors and not validator.warnings:
        print("✅ All validations passed!")
    
    # Save report
    report_file = project_root / "infrastructure_validation_report.json"
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\n📄 Full report saved to: {report_file}")
    
    # Exit with appropriate code
    sys.exit(0 if not validator.errors else 1)

if __name__ == "__main__":
    from datetime import datetime
    main()