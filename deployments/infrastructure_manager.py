#!/usr/bin/env python3
"""
GraphRAG Infrastructure Manager

Comprehensive infrastructure management tool for the GraphRAG system.
Provides unified interface for deployment, monitoring, scaling, and maintenance.
"""

import os
import sys
import json
import yaml
import anyio
import subprocess
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

@dataclass
class DeploymentStatus:
    """Represents deployment status."""
    environment: str
    type: str  # docker-compose, kubernetes
    status: str  # running, stopped, error, unknown
    services: Dict[str, str]
    health_score: float
    last_updated: str

class GraphRAGInfrastructureManager:
    """Comprehensive infrastructure management."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.deployments_dir = project_root / "deployments"
    
    async def deploy_system(self, environment: str, deployment_type: str, options: Dict) -> bool:
        """Deploy the GraphRAG system."""
        print(f"🚀 Deploying GraphRAG system to {environment} using {deployment_type}")
        
        if deployment_type == "docker-compose":
            return await self._deploy_docker_compose(environment, options)
        elif deployment_type == "kubernetes":
            return await self._deploy_kubernetes(environment, options)
        else:
            print(f"❌ Unknown deployment type: {deployment_type}")
            return False
    
    async def _deploy_docker_compose(self, environment: str, options: Dict) -> bool:
        """Deploy using Docker Compose."""
        try:
            # Validate configuration
            result = subprocess.run(
                ["docker-compose", "config"],
                cwd=self.project_root,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print(f"❌ Docker Compose configuration invalid: {result.stderr}")
                return False
            
            # Build images if requested
            if options.get("build", False):
                print("🔨 Building Docker images...")
                result = subprocess.run(
                    ["docker-compose", "build"],
                    cwd=self.project_root
                )
                if result.returncode != 0:
                    return False
            
            # Start services
            print("🚀 Starting services...")
            result = subprocess.run(
                ["docker-compose", "up", "-d"],
                cwd=self.project_root
            )
            
            if result.returncode != 0:
                return False
            
            # Wait for services to be healthy
            print("⏳ Waiting for services to be healthy...")
            await anyio.sleep(30)  # Give services time to start
            
            # Initialize database if requested
            if options.get("init_db", False):
                print("💾 Initializing database...")
                result = subprocess.run([
                    "docker-compose", "exec", "-T", "website-graphrag-processor",
                    "python", "-m", "ipfs_datasets_py.scripts.init_database", "--init"
                ], cwd=self.project_root)
                
                if result.returncode != 0:
                    print("⚠️ Database initialization may have failed")
            
            print("✅ Docker Compose deployment completed")
            return True
            
        except Exception as e:
            print(f"❌ Docker Compose deployment failed: {e}")
            return False
    
    async def _deploy_kubernetes(self, environment: str, options: Dict) -> bool:
        """Deploy using Kubernetes."""
        try:
            # Check kubectl connectivity
            result = subprocess.run(
                ["kubectl", "cluster-info"],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                print("❌ Cannot connect to Kubernetes cluster")
                return False
            
            # Create namespace
            print("📦 Creating namespace...")
            subprocess.run([
                "kubectl", "create", "namespace", "graphrag-system",
                "--dry-run=client", "-o", "yaml"
            ], stdout=subprocess.PIPE, check=True)
            
            subprocess.run([
                "kubectl", "apply", "-f", "-"
            ], input=result.stdout, text=True, check=True)
            
            # Check for required secrets
            secrets_needed = ["db-credentials", "api-credentials", "api-keys"]
            missing_secrets = []
            
            for secret in secrets_needed:
                result = subprocess.run([
                    "kubectl", "get", "secret", secret, "-n", "graphrag-system"
                ], capture_output=True)
                
                if result.returncode != 0:
                    missing_secrets.append(secret)
            
            if missing_secrets:
                print(f"⚠️ Missing required secrets: {missing_secrets}")
                print("Please create secrets before deploying:")
                for secret in missing_secrets:
                    print(f"kubectl create secret generic {secret} --from-literal=key=value -n graphrag-system")
                
                if not options.get("force", False):
                    return False
            
            # Deploy infrastructure
            print("🏗️ Deploying infrastructure...")
            result = subprocess.run([
                "kubectl", "apply", "-f", str(self.deployments_dir / "kubernetes" / "infrastructure.yaml")
            ])
            
            if result.returncode != 0:
                return False
            
            # Wait for infrastructure
            print("⏳ Waiting for infrastructure to be ready...")
            infrastructure_deployments = ["redis", "ipfs", "elasticsearch"]
            
            for deployment in infrastructure_deployments:
                subprocess.run([
                    "kubectl", "wait", "--for=condition=available",
                    "--timeout=300s", f"deployment/{deployment}",
                    "-n", "graphrag-system"
                ], check=True)
            
            # Deploy application
            print("🚀 Deploying application...")
            result = subprocess.run([
                "kubectl", "apply", "-f", str(self.deployments_dir / "kubernetes" / "graphrag-deployment.yaml")
            ])
            
            if result.returncode != 0:
                return False
            
            # Wait for application
            subprocess.run([
                "kubectl", "wait", "--for=condition=available",
                "--timeout=600s", "deployment/website-graphrag-processor",
                "-n", "graphrag-system"
            ], check=True)
            
            # Setup ingress
            print("🌐 Setting up ingress...")
            result = subprocess.run([
                "kubectl", "apply", "-f", str(self.deployments_dir / "kubernetes" / "ingress.yaml")
            ])
            
            print("✅ Kubernetes deployment completed")
            return True
            
        except Exception as e:
            print(f"❌ Kubernetes deployment failed: {e}")
            return False
    
    async def get_deployment_status(self, deployment_type: str) -> DeploymentStatus:
        """Get current deployment status."""
        if deployment_type == "docker-compose":
            return await self._get_docker_compose_status()
        elif deployment_type == "kubernetes":
            return await self._get_kubernetes_status()
        else:
            return DeploymentStatus(
                environment="unknown",
                type=deployment_type,
                status="error",
                services={},
                health_score=0.0,
                last_updated=datetime.now().isoformat()
            )
    
    async def _get_docker_compose_status(self) -> DeploymentStatus:
        """Get Docker Compose deployment status."""
        try:
            result = subprocess.run(
                ["docker-compose", "ps", "--format", "json"],
                cwd=self.project_root,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return DeploymentStatus(
                    environment="docker",
                    type="docker-compose", 
                    status="stopped",
                    services={},
                    health_score=0.0,
                    last_updated=datetime.now().isoformat()
                )
            
            # Parse service status
            services = {}
            for line in result.stdout.strip().split('\n'):
                if line:
                    service_info = json.loads(line)
                    services[service_info["Service"]] = service_info["State"]
            
            # Calculate health score
            healthy_services = sum(1 for status in services.values() if status == "running")
            health_score = (healthy_services / len(services)) * 100 if services else 0
            
            status = "running" if health_score > 80 else "degraded" if health_score > 0 else "stopped"
            
            return DeploymentStatus(
                environment="docker",
                type="docker-compose",
                status=status,
                services=services,
                health_score=health_score,
                last_updated=datetime.now().isoformat()
            )
            
        except Exception as e:
            print(f"Error getting Docker Compose status: {e}")
            return DeploymentStatus(
                environment="docker",
                type="docker-compose",
                status="error",
                services={},
                health_score=0.0,
                last_updated=datetime.now().isoformat()
            )
    
    async def _get_kubernetes_status(self) -> DeploymentStatus:
        """Get Kubernetes deployment status."""
        try:
            # Get pod status
            result = subprocess.run([
                "kubectl", "get", "pods", "-n", "graphrag-system",
                "-o", "json"
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                return DeploymentStatus(
                    environment="kubernetes",
                    type="kubernetes",
                    status="not_deployed",
                    services={},
                    health_score=0.0,
                    last_updated=datetime.now().isoformat()
                )
            
            pods_data = json.loads(result.stdout)
            services = {}
            
            for pod in pods_data.get("items", []):
                pod_name = pod["metadata"]["name"]
                pod_phase = pod["status"].get("phase", "Unknown")
                services[pod_name] = pod_phase
            
            # Calculate health score
            healthy_pods = sum(1 for status in services.values() if status == "Running")
            health_score = (healthy_pods / len(services)) * 100 if services else 0
            
            status = "running" if health_score > 80 else "degraded" if health_score > 0 else "stopped"
            
            return DeploymentStatus(
                environment="kubernetes",
                type="kubernetes",
                status=status,
                services=services,
                health_score=health_score,
                last_updated=datetime.now().isoformat()
            )
            
        except Exception as e:
            print(f"Error getting Kubernetes status: {e}")
            return DeploymentStatus(
                environment="kubernetes", 
                type="kubernetes",
                status="error",
                services={},
                health_score=0.0,
                last_updated=datetime.now().isoformat()
            )
    
    async def scale_deployment(self, deployment_type: str, service: str, replicas: int) -> bool:
        """Scale a deployment."""
        print(f"📈 Scaling {service} to {replicas} replicas...")
        
        try:
            if deployment_type == "docker-compose":
                # Docker Compose scaling
                result = subprocess.run([
                    "docker-compose", "up", "-d", "--scale", f"{service}={replicas}"
                ], cwd=self.project_root)
                
                return result.returncode == 0
                
            elif deployment_type == "kubernetes":
                # Kubernetes scaling
                result = subprocess.run([
                    "kubectl", "scale", f"deployment/{service}",
                    f"--replicas={replicas}", "-n", "graphrag-system"
                ])
                
                return result.returncode == 0
            
            return False
            
        except Exception as e:
            print(f"❌ Scaling failed: {e}")
            return False
    
    async def run_maintenance(self, tasks: List[str]) -> Dict[str, bool]:
        """Run maintenance tasks."""
        results = {}
        
        for task in tasks:
            print(f"🔧 Running maintenance task: {task}")
            
            if task == "cleanup_logs":
                # Clean up old log files
                result = subprocess.run([
                    "find", str(self.project_root / "logs"),
                    "-name", "*.log", "-mtime", "+7", "-delete"
                ], capture_output=True)
                results[task] = result.returncode == 0
                
            elif task == "backup_database":
                # Run database backup
                result = subprocess.run([
                    str(self.deployments_dir / "backup_recovery.sh"), "backup-db"
                ])
                results[task] = result.returncode == 0
                
            elif task == "update_dependencies":
                # Update Python dependencies
                result = subprocess.run([
                    "pip", "install", "--upgrade", "-e", ".[all]"
                ], cwd=self.project_root)
                results[task] = result.returncode == 0
                
            elif task == "health_check":
                # Run comprehensive health check
                result = subprocess.run([
                    "python", str(self.deployments_dir / "health_check.py")
                ])
                results[task] = result.returncode == 0
                
            else:
                print(f"⚠️ Unknown maintenance task: {task}")
                results[task] = False
        
        return results

async def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(description="GraphRAG Infrastructure Manager")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy the system")
    deploy_parser.add_argument("-e", "--environment", default="development",
                              choices=["development", "staging", "production"])
    deploy_parser.add_argument("-t", "--type", default="docker-compose",
                              choices=["docker-compose", "kubernetes"])
    deploy_parser.add_argument("--build", action="store_true", help="Build images before deployment")
    deploy_parser.add_argument("--init-db", action="store_true", help="Initialize database")
    deploy_parser.add_argument("--force", action="store_true", help="Force deployment even with warnings")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Get deployment status")
    status_parser.add_argument("-t", "--type", default="docker-compose",
                              choices=["docker-compose", "kubernetes"])
    status_parser.add_argument("--json", action="store_true", help="Output in JSON format")
    
    # Scale command
    scale_parser = subparsers.add_parser("scale", help="Scale services")
    scale_parser.add_argument("-t", "--type", default="docker-compose",
                             choices=["docker-compose", "kubernetes"])
    scale_parser.add_argument("service", help="Service to scale")
    scale_parser.add_argument("replicas", type=int, help="Number of replicas")
    
    # Maintenance command
    maintenance_parser = subparsers.add_parser("maintenance", help="Run maintenance tasks")
    maintenance_parser.add_argument("tasks", nargs="+",
                                   choices=["cleanup_logs", "backup_database", "update_dependencies", "health_check"])
    
    # Health command
    health_parser = subparsers.add_parser("health", help="Run health checks")
    health_parser.add_argument("--detailed", action="store_true", help="Show detailed health information")
    
    # Logs command
    logs_parser = subparsers.add_parser("logs", help="View system logs")
    logs_parser.add_argument("-t", "--type", default="docker-compose",
                            choices=["docker-compose", "kubernetes"])
    logs_parser.add_argument("-s", "--service", help="Specific service to view logs for")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Initialize manager
    project_root = Path(__file__).parent.parent
    manager = GraphRAGInfrastructureManager(project_root)
    
    if args.command == "deploy":
        options = {
            "build": args.build,
            "init_db": args.init_db,
            "force": args.force
        }
        success = await manager.deploy_system(args.environment, args.type, options)
        sys.exit(0 if success else 1)
    
    elif args.command == "status":
        status = await manager.get_deployment_status(args.type)
        
        if args.json:
            print(json.dumps({
                "environment": status.environment,
                "type": status.type,
                "status": status.status,
                "services": status.services,
                "health_score": status.health_score,
                "last_updated": status.last_updated
            }, indent=2))
        else:
            print(f"📊 Deployment Status")
            print(f"Environment: {status.environment}")
            print(f"Type: {status.type}")
            print(f"Status: {status.status}")
            print(f"Health Score: {status.health_score:.1f}%")
            print(f"Services:")
            for service, service_status in status.services.items():
                status_icon = "✅" if service_status in ["running", "Running"] else "❌"
                print(f"  {status_icon} {service}: {service_status}")
    
    elif args.command == "scale":
        success = await manager.scale_deployment(args.type, args.service, args.replicas)
        sys.exit(0 if success else 1)
    
    elif args.command == "maintenance":
        results = await manager.run_maintenance(args.tasks)
        
        print("🔧 Maintenance Results:")
        all_success = True
        for task, success in results.items():
            status_icon = "✅" if success else "❌"
            print(f"  {status_icon} {task}")
            all_success = all_success and success
        
        sys.exit(0 if all_success else 1)
    
    elif args.command == "health":
        # Run health check script
        result = subprocess.run([
            "python", str(manager.deployments_dir / "health_check.py")
        ])
        sys.exit(result.returncode)
    
    elif args.command == "logs":
        if args.type == "docker-compose":
            cmd = ["docker-compose", "logs"]
            if args.follow:
                cmd.append("-f")
            if args.service:
                cmd.append(args.service)
            
            subprocess.run(cmd, cwd=project_root)
            
        elif args.type == "kubernetes":
            cmd = ["kubectl", "logs"]
            if args.follow:
                cmd.append("-f")
            
            if args.service:
                cmd.extend([f"deployment/{args.service}", "-n", "graphrag-system"])
            else:
                cmd.extend(["-l", "app=website-graphrag-processor", "-n", "graphrag-system"])
            
            subprocess.run(cmd)

if __name__ == "__main__":
    anyio.run(main)