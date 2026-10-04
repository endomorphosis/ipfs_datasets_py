#!/usr/bin/env python3
"""
Production Deployment Script

This script automates the deployment of the IPFS Datasets service to production.
"""

import os
import sys
import subprocess
import argparse
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def run_command(cmd, cwd=None, check=True):
    """Run a shell command with logging."""
    logger.info(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    result = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd, capture_output=True, text=True)
    
    if result.returncode != 0 and check:
        logger.error(f"Command failed: {result.stderr}")
        sys.exit(1)
    
    if result.stdout:
        logger.info(result.stdout)
    
    return result

def deploy_docker(port=8000, build=True):
    """Deploy using Docker."""
    logger.info("🐳 Deploying with Docker...")
    
    if build:
        logger.info("Building Docker image...")
        run_command(["docker", "build", "-t", "ipfs-datasets-py", "."])
    
    logger.info(f"Starting container on port {port}...")
    run_command([
        "docker", "run", "-d",
        "--name", "ipfs-datasets-service",
        "-p", f"{port}:8000",
        "--restart", "unless-stopped",
        "ipfs-datasets-py"
    ])
    
    logger.info(f"✅ Service deployed at http://localhost:{port}")

def deploy_systemd(user="ipfs-datasets", install_path="/opt/ipfs-datasets"):
    """Deploy as systemd service."""
    logger.info("🔧 Deploying as systemd service...")
    
    # Create service user
    logger.info(f"Creating service user: {user}")
    run_command(f"sudo useradd -r -s /bin/false {user}", check=False)
    
    # Install application
    logger.info(f"Installing to {install_path}")
    run_command(f"sudo mkdir -p {install_path}")
    run_command(f"sudo cp -r . {install_path}/")
    run_command(f"sudo chown -R {user}:{user} {install_path}")
    
    # Install dependencies
    logger.info("Installing Python dependencies...")
    run_command(f"sudo -u {user} python3 -m venv {install_path}/.venv")
    run_command(f"sudo -u {user} {install_path}/.venv/bin/pip install -r {install_path}/requirements.txt")
    
    # Create systemd service file
    service_content = f"""[Unit]
Description=IPFS Datasets Service
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={install_path}
Environment=PATH={install_path}/.venv/bin
ExecStart={install_path}/.venv/bin/python start_fastapi.py --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    
    # Write service file
    service_file = "/etc/systemd/system/ipfs-datasets.service"
    with open("/tmp/ipfs-datasets.service", "w") as f:
        f.write(service_content)
    
    run_command(f"sudo mv /tmp/ipfs-datasets.service {service_file}")
    
    # Enable and start service
    logger.info("Enabling and starting systemd service...")
    run_command("sudo systemctl daemon-reload")
    run_command("sudo systemctl enable ipfs-datasets")
    run_command("sudo systemctl start ipfs-datasets")
    
    logger.info("✅ Service deployed and started")
    logger.info("Check status with: sudo systemctl status ipfs-datasets")

def deploy_development(port=8000, host="127.0.0.1"):
    """Deploy in development mode."""
    logger.info("🚀 Starting development server...")
    
    # Install dependencies
    run_command([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    
    # Start server
    cmd = [sys.executable, "start_fastapi.py", "--host", host, "--port", str(port)]
    logger.info(f"Starting server at http://{host}:{port}")
    
    # Run in foreground
    subprocess.run(cmd)

def validate_deployment(port=8000, host="localhost"):
    """Validate deployment by testing endpoints."""
    logger.info("🔍 Validating deployment...")
    
    import requests
    import time
    
    base_url = f"http://{host}:{port}"
    
    # Wait for service to start
    for i in range(30):  # Wait up to 30 seconds
        try:
            response = requests.get(f"{base_url}/health", timeout=5)
            if response.status_code == 200:
                logger.info("✅ Health check passed")
                break
        except requests.RequestException:
            pass
        
        time.sleep(1)
    else:
        logger.error("❌ Service not responding to health checks")
        return False
    
    # Test key endpoints
    endpoints = ["/health", "/api/v1/auth/status", "/docs"]
    
    for endpoint in endpoints:
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=5)
            if response.status_code in [200, 401]:  # 401 OK for auth endpoints
                logger.info(f"✅ {endpoint} - Status: {response.status_code}")
            else:
                logger.warning(f"⚠️ {endpoint} - Status: {response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ {endpoint} - Error: {e}")
    
    logger.info("🎯 Deployment validation complete")
    logger.info(f"📖 API documentation available at: {base_url}/docs")
    return True

def main():
    parser = argparse.ArgumentParser(description="Deploy IPFS Datasets Service")
    parser.add_argument("--method", choices=["docker", "systemd", "dev"], default="dev",
                       help="Deployment method")
    parser.add_argument("--port", type=int, default=8000, help="Service port")
    parser.add_argument("--host", default="127.0.0.1", help="Service host")
    parser.add_argument("--no-build", action="store_true", help="Skip Docker build")
    parser.add_argument("--validate", action="store_true", help="Validate deployment")
    
    args = parser.parse_args()
    
    # Ensure we're in the project directory
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    logger.info("🚀 Starting IPFS Datasets Service Deployment")
    logger.info(f"Method: {args.method}, Port: {args.port}, Host: {args.host}")
    
    try:
        if args.method == "docker":
            deploy_docker(port=args.port, build=not args.no_build)
        elif args.method == "systemd":
            deploy_systemd()
        elif args.method == "dev":
            deploy_development(port=args.port, host=args.host)
        
        if args.validate:
            validate_deployment(port=args.port, host=args.host)
        
        logger.info("🎉 Deployment completed successfully!")
        
    except KeyboardInterrupt:
        logger.info("🛑 Deployment interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Deployment failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
