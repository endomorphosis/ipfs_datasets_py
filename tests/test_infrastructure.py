# GraphRAG System Infrastructure Test Suite

import pytest
import anyio
import docker
import subprocess
import time
from pathlib import Path
from typing import Dict, Any

class TestDockerInfrastructure:
    """Test Docker deployment infrastructure."""
    
    @pytest.fixture(scope="class")
    def docker_client(self):
        """Docker client fixture."""
        return docker.from_env()
    
    def test_dockerfile_exists(self):
        """Test that Dockerfile exists and is valid."""
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        assert dockerfile.exists(), "Dockerfile not found"
        
        # Basic syntax validation
        content = dockerfile.read_text()
        assert "FROM" in content, "Dockerfile missing FROM instruction"
        assert "WORKDIR" in content, "Dockerfile missing WORKDIR instruction"
        assert "COPY" in content, "Dockerfile missing COPY instruction"
    
    def test_docker_compose_config(self):
        """Test Docker Compose configuration."""
        compose_file = Path(__file__).parent.parent / "docker-compose.yml"
        assert compose_file.exists(), "docker-compose.yml not found"
        
        # Validate compose file
        result = subprocess.run(
            ["docker-compose", "config"],
            cwd=compose_file.parent,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"docker-compose config failed: {result.stderr}"
    
    def test_env_example_completeness(self):
        """Test that .env.example contains all required variables."""
        env_file = Path(__file__).parent.parent / ".env.example"
        assert env_file.exists(), ".env.example not found"
        
        content = env_file.read_text()
        required_vars = [
            'POSTGRES_PASSWORD', 'JWT_SECRET_KEY', 'OPENAI_API_KEY',
            'POSTGRES_URL', 'REDIS_URL', 'IPFS_API_URL'
        ]
        
        for var in required_vars:
            assert var in content, f"Required environment variable {var} not found"

class TestKubernetesInfrastructure:
    """Test Kubernetes deployment infrastructure."""
    
    def test_kubernetes_manifests_exist(self):
        """Test that all required Kubernetes manifests exist."""
        k8s_dir = Path(__file__).parent.parent / "deployments" / "kubernetes"
        assert k8s_dir.exists(), "Kubernetes deployment directory not found"
        
        required_files = [
            "infrastructure.yaml",
            "graphrag-deployment.yaml",
            "ingress.yaml"
        ]
        
        for filename in required_files:
            file_path = k8s_dir / filename
            assert file_path.exists(), f"Required Kubernetes manifest not found: {filename}"
    
    def test_kubernetes_manifest_syntax(self):
        """Test Kubernetes manifest YAML syntax."""
        k8s_dir = Path(__file__).parent.parent / "deployments" / "kubernetes"
        
        for yaml_file in k8s_dir.glob("*.yaml"):
            result = subprocess.run(
                ["kubectl", "apply", "--dry-run=client", "-f", str(yaml_file)],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                # Only fail if kubectl is available
                if "command not found" not in result.stderr:
                    assert False, f"Kubernetes validation failed for {yaml_file.name}: {result.stderr}"

class TestDeploymentAutomation:
    """Test deployment automation scripts."""
    
    def test_deployment_script_exists(self):
        """Test that deployment script exists and is executable."""
        deploy_script = Path(__file__).parent.parent / "deployments" / "deploy.sh"
        assert deploy_script.exists(), "Deployment script not found"
        assert os.access(deploy_script, os.X_OK), "Deployment script is not executable"
    
    def test_entrypoint_script_exists(self):
        """Test that Docker entrypoint script exists and is executable."""
        entrypoint = Path(__file__).parent.parent / "docker-entrypoint.sh"
        assert entrypoint.exists(), "Docker entrypoint script not found"
        assert os.access(entrypoint, os.X_OK), "Docker entrypoint script is not executable"
    
    def test_database_init_script_exists(self):
        """Test that database initialization script exists."""
        init_script = Path(__file__).parent.parent / "ipfs_datasets_py" / "scripts" / "init_database.py"
        assert init_script.exists(), "Database initialization script not found"

class TestMonitoringConfiguration:
    """Test monitoring and observability configuration."""
    
    def test_prometheus_config_exists(self):
        """Test Prometheus configuration."""
        prometheus_config = Path(__file__).parent.parent / "deployments" / "monitoring" / "prometheus.yml"
        assert prometheus_config.exists(), "Prometheus configuration not found"
        
        # Basic YAML validation
        import yaml
        with open(prometheus_config) as f:
            config = yaml.safe_load(f)
        
        assert "scrape_configs" in config, "Prometheus scrape configs not found"
    
    def test_grafana_datasource_config(self):
        """Test Grafana datasource configuration."""
        datasource_config = Path(__file__).parent.parent / "deployments" / "monitoring" / "grafana" / "datasources" / "prometheus.yml"
        assert datasource_config.exists(), "Grafana datasource configuration not found"

class TestDatabaseConfiguration:
    """Test database configuration and schema."""
    
    def test_database_init_sql_exists(self):
        """Test that database initialization SQL exists."""
        sql_file = Path(__file__).parent.parent / "deployments" / "sql" / "init.sql"
        assert sql_file.exists(), "Database initialization SQL not found"
    
    def test_database_schema_completeness(self):
        """Test that database schema includes all required tables."""
        sql_file = Path(__file__).parent.parent / "deployments" / "sql" / "init.sql"
        content = sql_file.read_text()
        
        required_tables = [
            'users', 'processing_jobs', 'website_content',
            'kg_entities', 'kg_relationships', 'system_metrics',
            'user_activity', 'search_queries', 'archive_metadata'
        ]
        
        for table in required_tables:
            assert f"CREATE TABLE IF NOT EXISTS {table}" in content, f"Required table '{table}' not found in schema"

@pytest.mark.asyncio
class TestInfrastructureIntegration:
    """Integration tests for infrastructure components."""
    
    async def test_health_check_script(self):
        """Test the health check script functionality."""
        # This is a basic test - in real deployment, you'd test against running services
        health_script = Path(__file__).parent.parent / "deployments" / "health_check.py"
        assert health_script.exists(), "Health check script not found"
        assert os.access(health_script, os.X_OK), "Health check script is not executable"
    
    async def test_production_readiness_check(self):
        """Test production readiness checker."""
        readiness_script = Path(__file__).parent.parent / "deployments" / "production_readiness_check.py"
        assert readiness_script.exists(), "Production readiness script not found"
        assert os.access(readiness_script, os.X_OK), "Production readiness script is not executable"

def test_deployment_documentation():
    """Test that deployment documentation is complete."""
    docs_dir = Path(__file__).parent.parent / "deployments"
    readme = docs_dir / "README.md"
    assert readme.exists(), "Deployment documentation not found"
    
    content = readme.read_text()
    assert "Quick Start" in content, "Quick start section missing from documentation"
    assert "Docker Compose" in content, "Docker Compose documentation missing"
    assert "Kubernetes" in content, "Kubernetes documentation missing"

if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])