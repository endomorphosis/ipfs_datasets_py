# GraphRAG Infrastructure Test Suite

import pytest
import subprocess
import tempfile
import json
import os
import shutil
from pathlib import Path

class TestDeploymentInfrastructure:
    """Test deployment infrastructure components."""
    
    def test_docker_compose_syntax(self):
        """Test Docker Compose file syntax validation."""
        project_root = Path(__file__).parent.parent

        if shutil.which("docker-compose") is None:
            pytest.skip("docker-compose not available; skipping docker compose validation")
        
        result = subprocess.run(
            ["docker-compose", "config"],
            cwd=project_root,
            capture_output=True,
            text=True
        )
        
        # Should validate syntax even if services aren't available
        assert result.returncode == 0, f"Docker Compose syntax error: {result.stderr}"
    
    def test_kubernetes_manifest_validation(self):
        """Test Kubernetes manifests can be validated."""
        k8s_dir = Path(__file__).parent.parent / "deployments" / "kubernetes"

        if shutil.which("kubectl") is None:
            pytest.skip("kubectl not available; skipping Kubernetes manifest validation")
        
        for yaml_file in k8s_dir.glob("*.yaml"):
            # Test with kubectl dry-run if available
            result = subprocess.run(
                ["kubectl", "apply", "--dry-run=client", "-f", str(yaml_file)],
                capture_output=True,
                text=True
            )
            
            # Only fail if kubectl is available and validation actually fails
            if result.returncode != 0 and "command not found" not in result.stderr:
                assert False, f"Kubernetes validation failed for {yaml_file.name}: {result.stderr}"
    
    def test_deployment_scripts_executable(self):
        """Test that deployment scripts are executable."""
        scripts_dir = Path(__file__).parent.parent / "deployments"
        
        required_scripts = [
            "deploy.sh",
            "backup_recovery.sh", 
            "infrastructure_manager.py",
            "health_check.py",
            "production_readiness_check.py",
            "validate_infrastructure.py"
        ]
        
        for script in required_scripts:
            script_path = scripts_dir / script
            assert script_path.exists(), f"Required script not found: {script}"
            assert os.access(script_path, os.X_OK), f"Script not executable: {script}"
    
    def test_database_schema_completeness(self):
        """Test database schema includes all required tables."""
        sql_file = Path(__file__).parent.parent / "deployments" / "sql" / "init.sql"
        assert sql_file.exists(), "Database initialization SQL not found"
        
        content = sql_file.read_text()
        
        # Check for essential tables
        required_tables = [
            'users', 'processing_jobs', 'website_content',
            'kg_entities', 'kg_relationships', 'system_metrics'
        ]
        
        for table in required_tables:
            assert f"CREATE TABLE IF NOT EXISTS {table}" in content, f"Table {table} not found in schema"
    
    def test_environment_configuration(self):
        """Test environment configuration completeness."""
        env_file = Path(__file__).parent.parent / ".env.example"
        assert env_file.exists(), ".env.example not found"
        
        content = env_file.read_text()
        
        # Check for critical configuration
        required_configs = [
            'POSTGRES_URL', 'REDIS_URL', 'JWT_SECRET_KEY',
            'OPENAI_API_KEY', 'IPFS_API_URL'
        ]
        
        for config in required_configs:
            assert config in content, f"Required configuration {config} not found"

class TestInfrastructureAutomation:
    """Test infrastructure automation capabilities."""
    
    def test_infrastructure_manager_commands(self):
        """Test infrastructure manager CLI interface."""
        manager_script = Path(__file__).parent.parent / "deployments" / "infrastructure_manager.py"
        
        # Test help command
        result = subprocess.run(
            ["python", str(manager_script), "--help"],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, "Infrastructure manager help failed"
        assert "deploy" in result.stdout, "Deploy command not found in help"
        assert "status" in result.stdout, "Status command not found in help"
    
    def test_backup_recovery_commands(self):
        """Test backup and recovery script commands."""
        backup_script = Path(__file__).parent.parent / "deployments" / "backup_recovery.sh"
        
        # Test help command
        result = subprocess.run(
            [str(backup_script), "help"],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, "Backup script help failed"
        assert "backup" in result.stdout, "Backup command not found in help"
        assert "restore" in result.stdout, "Restore command not found in help"
    
    def test_health_check_functionality(self):
        """Test health check script can run."""
        health_script = Path(__file__).parent.parent / "deployments" / "health_check.py"
        
        # Test script can at least start (will fail on actual health checks without services)
        result = subprocess.run(
            ["python", str(health_script)],
            capture_output=True,
            text=True
        )
        
        # Script should handle missing services gracefully
        assert "Health Check Summary" in result.stdout or "connection" in result.stderr

class TestProductionReadiness:
    """Test production readiness validation."""
    
    def test_production_readiness_checker(self):
        """Test production readiness assessment."""
        readiness_script = Path(__file__).parent.parent / "deployments" / "production_readiness_check.py"
        
        result = subprocess.run(
            ["python", str(readiness_script)],
            capture_output=True,
            text=True
        )
        
        # Should generate a report even if not ready
        assert "Production Readiness Assessment" in result.stdout
        assert "readiness score" in result.stdout.lower()
    
    def test_infrastructure_validation(self):
        """Test infrastructure validation script."""
        validation_script = Path(__file__).parent.parent / "deployments" / "validate_infrastructure.py"
        
        result = subprocess.run(
            ["python", str(validation_script)],
            capture_output=True,
            text=True
        )
        
        # Should generate validation report
        assert "Infrastructure Validation" in result.stdout
        assert "Validation Report" in result.stdout

@pytest.mark.integration
class TestDeploymentIntegration:
    """Integration tests for deployment workflows."""
    
    def test_deployment_workflow_dry_run(self):
        """Test deployment workflow in dry-run mode."""
        # This would test the full deployment workflow without actually deploying
        deploy_script = Path(__file__).parent.parent / "deployments" / "deploy.sh"
        
        # Test help to ensure script is functional
        result = subprocess.run(
            [str(deploy_script), "-h"],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0, "Deploy script help failed"
        assert "Usage:" in result.stdout, "Usage information not found"

if __name__ == "__main__":
    import os
    # Run tests directly
    pytest.main([__file__, "-v"])