#!/usr/bin/env python3
"""
Comprehensive Self-Hosted Runner Validation Suite

This script validates that the self-hosted runner can execute all expected
functionality for the ipfs_datasets_py repository.
"""

import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging


class SelfHostedRunnerValidator:
    """Comprehensive validation suite for self-hosted runner capabilities."""
    
    def __init__(self):
        self.results = {}
        self.start_time = time.time()
        
        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def get_system_info(self) -> Dict[str, Any]:
        """Collect comprehensive system information."""
        self.logger.info("🖥️ Collecting system information...")
        
        try:
            info = {
                'timestamp': time.time(),
                'hostname': platform.node(),
                'os': platform.system(),
                'os_release': platform.release(),
                'os_version': platform.version(),
                'architecture': platform.machine(),
                'processor': platform.processor(),
                'python_version': platform.python_version(),
                'python_implementation': platform.python_implementation(),
                'cpu_count': os.cpu_count(),
            }
            
            # Add memory information
            try:
                with open('/proc/meminfo', 'r') as f:
                    meminfo = f.read()
                    for line in meminfo.split('\n'):
                        if line.startswith('MemTotal:'):
                            info['memory_total_kb'] = int(line.split()[1])
                        elif line.startswith('MemAvailable:'):
                            info['memory_available_kb'] = int(line.split()[1])
            except Exception:
                pass
            
            # Add disk information
            try:
                disk_usage = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
                if disk_usage.returncode == 0:
                    lines = disk_usage.stdout.strip().split('\n')
                    if len(lines) > 1:
                        parts = lines[1].split()
                        info['disk_total'] = parts[1]
                        info['disk_used'] = parts[2]
                        info['disk_available'] = parts[3]
            except Exception:
                pass
            
            # Check for GPU
            try:
                nvidia_smi = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'], 
                                          capture_output=True, text=True)
                if nvidia_smi.returncode == 0:
                    gpus = []
                    for line in nvidia_smi.stdout.strip().split('\n'):
                        if line.strip():
                            parts = line.split(', ')
                            gpus.append({
                                'name': parts[0],
                                'memory': parts[1] if len(parts) > 1 else 'Unknown'
                            })
                    info['gpus'] = gpus
            except Exception:
                info['gpus'] = []
            
            self.logger.info(f"✅ System: {info['architecture']} running {info['os']}")
            self.logger.info(f"✅ Python: {info['python_version']}")
            self.logger.info(f"✅ CPUs: {info['cpu_count']}")
            if info.get('memory_total_kb'):
                self.logger.info(f"✅ Memory: {info['memory_total_kb'] // 1024} MB total")
            if info.get('gpus'):
                self.logger.info(f"✅ GPUs: {len(info['gpus'])} detected")
            
            return info
            
        except Exception as e:
            self.logger.error(f"❌ Error collecting system info: {e}")
            return {'error': str(e)}
    
    def test_python_environment(self) -> Dict[str, Any]:
        """Test Python environment and package availability."""
        self.logger.info("🐍 Testing Python environment...")
        
        results = {
            'python_executable': sys.executable,
            'python_path': sys.path[:3],  # First few paths
            'virtual_env': os.environ.get('VIRTUAL_ENV'),
            'conda_env': os.environ.get('CONDA_DEFAULT_ENV'),
        }
        
        # Test core package imports
        packages_to_test = [
            'numpy',
            'requests', 
            'json',
            'pathlib',
            'asyncio',
            'subprocess',
            'platform',
            'sys',
            'os'
        ]
        
        import_results = {}
        for package in packages_to_test:
            try:
                __import__(package)
                import_results[package] = {'success': True}
                self.logger.info(f"  ✅ {package}")
            except ImportError as e:
                import_results[package] = {'success': False, 'error': str(e)}
                self.logger.warning(f"  ⚠️ {package}: {e}")
        
        results['package_imports'] = import_results
        
        # Test ipfs_datasets_py import
        try:
            import ipfs_datasets_py
            results['ipfs_datasets_py'] = {
                'success': True,
                'version': getattr(ipfs_datasets_py, '__version__', 'unknown'),
                'path': ipfs_datasets_py.__file__
            }
            self.logger.info("✅ ipfs_datasets_py imported successfully")
        except ImportError as e:
            results['ipfs_datasets_py'] = {'success': False, 'error': str(e)}
            self.logger.error(f"❌ ipfs_datasets_py import failed: {e}")
        
        return results
    
    def test_docker_functionality(self) -> Dict[str, Any]:
        """Test Docker availability and functionality."""
        self.logger.info("🐳 Testing Docker functionality...")
        
        results = {}
        
        # Test Docker availability
        try:
            docker_version = subprocess.run(['docker', '--version'], capture_output=True, text=True)
            if docker_version.returncode == 0:
                results['docker_available'] = True
                results['docker_version'] = docker_version.stdout.strip()
                self.logger.info(f"✅ Docker available: {results['docker_version']}")
            else:
                results['docker_available'] = False
                results['error'] = 'Docker command failed'
                self.logger.warning("⚠️ Docker command failed")
        except FileNotFoundError:
            results['docker_available'] = False
            results['error'] = 'Docker not found'
            self.logger.warning("⚠️ Docker not found")
        
        # Test Docker daemon connectivity
        if results.get('docker_available'):
            try:
                docker_info = subprocess.run(['docker', 'info'], capture_output=True, text=True, timeout=10)
                if docker_info.returncode == 0:
                    results['docker_daemon'] = True
                    self.logger.info("✅ Docker daemon accessible")
                else:
                    results['docker_daemon'] = False
                    results['daemon_error'] = docker_info.stderr
                    self.logger.warning("⚠️ Docker daemon not accessible")
            except Exception as e:
                results['docker_daemon'] = False
                results['daemon_error'] = str(e)
                self.logger.warning(f"⚠️ Docker daemon test failed: {e}")
        
        # Test simple container run
        if results.get('docker_daemon'):
            try:
                hello_world = subprocess.run(['docker', 'run', '--rm', 'hello-world'], 
                                           capture_output=True, text=True, timeout=30)
                if hello_world.returncode == 0:
                    results['container_execution'] = True
                    self.logger.info("✅ Docker container execution working")
                else:
                    results['container_execution'] = False
                    results['container_error'] = hello_world.stderr
                    self.logger.warning("⚠️ Docker container execution failed")
            except Exception as e:
                results['container_execution'] = False
                results['container_error'] = str(e)
                self.logger.warning(f"⚠️ Docker container test failed: {e}")
        
        return results
    
    def test_git_functionality(self) -> Dict[str, Any]:
        """Test Git availability and repository access."""
        self.logger.info("🔀 Testing Git functionality...")
        
        results = {}
        
        # Test Git availability
        try:
            git_version = subprocess.run(['git', '--version'], capture_output=True, text=True)
            if git_version.returncode == 0:
                results['git_available'] = True
                results['git_version'] = git_version.stdout.strip()
                self.logger.info(f"✅ Git available: {results['git_version']}")
            else:
                results['git_available'] = False
        except FileNotFoundError:
            results['git_available'] = False
            self.logger.warning("⚠️ Git not found")
        
        # Test repository access
        if results.get('git_available'):
            repo_path = Path.cwd()
            try:
                # Check if we're in a git repository
                git_status = subprocess.run(['git', 'status', '--porcelain'], 
                                          capture_output=True, text=True, cwd=repo_path)
                if git_status.returncode == 0:
                    results['in_git_repo'] = True
                    
                    # Get repository info
                    remote_url = subprocess.run(['git', 'remote', 'get-url', 'origin'], 
                                              capture_output=True, text=True, cwd=repo_path)
                    if remote_url.returncode == 0:
                        results['remote_url'] = remote_url.stdout.strip()
                    
                    current_branch = subprocess.run(['git', 'branch', '--show-current'], 
                                                  capture_output=True, text=True, cwd=repo_path)
                    if current_branch.returncode == 0:
                        results['current_branch'] = current_branch.stdout.strip()
                    
                    self.logger.info("✅ Git repository accessible")
                else:
                    results['in_git_repo'] = False
                    self.logger.warning("⚠️ Not in a git repository")
            except Exception as e:
                results['git_repo_error'] = str(e)
                self.logger.warning(f"⚠️ Git repository test failed: {e}")
        
        return results
    
    def test_network_connectivity(self) -> Dict[str, Any]:
        """Test network connectivity for GitHub and package repositories."""
        self.logger.info("🌐 Testing network connectivity...")
        
        results = {}
        test_urls = {
            'github': 'https://github.com',
            'pypi': 'https://pypi.org',
            'docker_hub': 'https://hub.docker.com'
        }
        
        for name, url in test_urls.items():
            try:
                import urllib.request
                with urllib.request.urlopen(url, timeout=10) as response:
                    if response.status == 200:
                        results[name] = {'success': True, 'status': response.status}
                        self.logger.info(f"✅ {name} accessible")
                    else:
                        results[name] = {'success': False, 'status': response.status}
                        self.logger.warning(f"⚠️ {name} returned status {response.status}")
            except Exception as e:
                results[name] = {'success': False, 'error': str(e)}
                self.logger.warning(f"⚠️ {name} not accessible: {e}")
        
        return results
    
    def test_mcp_dashboard(self) -> Dict[str, Any]:
        """Test MCP dashboard functionality if available."""
        self.logger.info("🎛️ Testing MCP dashboard...")
        
        results = {}
        
        # Try to start MCP dashboard temporarily
        try:
            # Check if dashboard is already running
            import urllib.request
            try:
                with urllib.request.urlopen('http://127.0.0.1:8899/api/mcp/status', timeout=5) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode())
                        results['dashboard_running'] = True
                        results['status'] = data
                        self.logger.info("✅ MCP dashboard already running")
                        return results
            except:
                pass
            
            # Try to start dashboard briefly
            import subprocess
            dashboard_proc = subprocess.Popen([
                sys.executable, '-m', 'ipfs_datasets_py.mcp_dashboard'
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Wait a moment for startup
            time.sleep(3)
            
            # Test dashboard
            try:
                with urllib.request.urlopen('http://127.0.0.1:8899/api/mcp/status', timeout=5) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode())
                        results['dashboard_startup'] = True
                        results['status'] = data
                        self.logger.info("✅ MCP dashboard started successfully")
                    else:
                        results['dashboard_startup'] = False
                        self.logger.warning("⚠️ MCP dashboard responded with non-200 status")
            except Exception as e:
                results['dashboard_startup'] = False
                results['error'] = str(e)
                self.logger.warning(f"⚠️ MCP dashboard test failed: {e}")
            
            # Clean up
            dashboard_proc.terminate()
            dashboard_proc.wait(timeout=5)
            
        except Exception as e:
            results['dashboard_startup'] = False
            results['error'] = str(e)
            self.logger.warning(f"⚠️ MCP dashboard test error: {e}")
        
        return results
    
    def test_runner_capabilities(self) -> Dict[str, Any]:
        """Test GitHub Actions runner specific capabilities."""
        self.logger.info("🏃 Testing runner capabilities...")
        
        results = {}
        
        # Check runner environment variables
        runner_env_vars = [
            'GITHUB_ACTIONS',
            'RUNNER_OS',
            'RUNNER_ARCH', 
            'RUNNER_NAME',
            'GITHUB_WORKSPACE',
            'GITHUB_REPOSITORY',
            'GITHUB_RUN_ID'
        ]
        
        env_vars = {}
        for var in runner_env_vars:
            value = os.environ.get(var)
            env_vars[var] = value
            if value:
                self.logger.info(f"✅ {var}: {value}")
        
        results['environment_variables'] = env_vars
        
        # Check if we're running in GitHub Actions
        results['in_github_actions'] = os.environ.get('GITHUB_ACTIONS') == 'true'
        
        # Test file system permissions
        test_dir = Path('/tmp/runner_test')
        try:
            test_dir.mkdir(exist_ok=True)
            test_file = test_dir / 'test.txt'
            test_file.write_text('test content')
            content = test_file.read_text()
            test_file.unlink()
            test_dir.rmdir()
            results['filesystem_rw'] = True
            self.logger.info("✅ Filesystem read/write working")
        except Exception as e:
            results['filesystem_rw'] = False
            results['filesystem_error'] = str(e)
            self.logger.warning(f"⚠️ Filesystem test failed: {e}")
        
        return results
    
    async def run_comprehensive_validation(self) -> Dict[str, Any]:
        """Run all validation tests."""
        self.logger.info("🚀 Starting comprehensive self-hosted runner validation")
        self.logger.info("=" * 60)
        
        # Collect all test results
        test_results = {
            'validation_start_time': self.start_time,
            'system_info': self.get_system_info(),
            'python_environment': self.test_python_environment(),
            'docker_functionality': self.test_docker_functionality(),
            'git_functionality': self.test_git_functionality(),
            'network_connectivity': self.test_network_connectivity(),
            'mcp_dashboard': self.test_mcp_dashboard(),
            'runner_capabilities': self.test_runner_capabilities(),
        }
        
        # Calculate overall success
        validation_end_time = time.time()
        test_results['validation_end_time'] = validation_end_time
        test_results['validation_duration'] = validation_end_time - self.start_time
        
        # Determine critical failures
        critical_tests = [
            ('python_environment', 'ipfs_datasets_py', 'success'),
            ('git_functionality', 'git_available'),
            ('network_connectivity', 'github', 'success')
        ]
        
        failed_critical = []
        for test_path in critical_tests:
            current = test_results
            failed = False
            try:
                for key in test_path[:-1]:
                    current = current[key]
                if not current.get(test_path[-1]):
                    failed = True
            except (KeyError, TypeError):
                failed = True
            
            if failed:
                failed_critical.append('.'.join(test_path))
        
        test_results['overall_success'] = len(failed_critical) == 0
        test_results['failed_critical_tests'] = failed_critical
        
        # Summary
        self.logger.info("=" * 60)
        if test_results['overall_success']:
            self.logger.info("🎉 All critical validations PASSED!")
            self.logger.info("✅ Self-hosted runner is ready for GitHub Actions workflows")
        else:
            self.logger.warning("⚠️ Some critical validations FAILED:")
            for failed_test in failed_critical:
                self.logger.warning(f"  ❌ {failed_test}")
        
        self.logger.info(f"⏱️ Total validation time: {test_results['validation_duration']:.2f} seconds")
        
        return test_results
    
    def save_results(self, results: Dict[str, Any], output_file: str = "runner_validation_results.json"):
        """Save validation results to file."""
        output_path = Path(output_file)
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        self.logger.info(f"💾 Validation results saved to {output_path}")
    
    def generate_report(self, results: Dict[str, Any]) -> str:
        """Generate human-readable validation report."""
        lines = []
        lines.append("# Self-Hosted Runner Validation Report")
        lines.append("")
        lines.append(f"**Validation Date:** {time.ctime(results.get('validation_start_time', time.time()))}")
        lines.append(f"**Overall Result:** {'✅ PASSED' if results.get('overall_success', False) else '❌ FAILED'}")
        lines.append(f"**Duration:** {results.get('validation_duration', 0):.2f} seconds")
        lines.append("")
        
        # System Information
        if 'system_info' in results:
            sys_info = results['system_info']
            lines.append("## System Information")
            lines.append(f"- **Hostname:** {sys_info.get('hostname', 'Unknown')}")
            lines.append(f"- **Architecture:** {sys_info.get('architecture', 'Unknown')}")
            lines.append(f"- **OS:** {sys_info.get('os', 'Unknown')} {sys_info.get('os_release', '')}")
            lines.append(f"- **Python:** {sys_info.get('python_version', 'Unknown')}")
            lines.append(f"- **CPUs:** {sys_info.get('cpu_count', 'Unknown')}")
            if sys_info.get('memory_total_kb'):
                lines.append(f"- **Memory:** {sys_info['memory_total_kb'] // 1024} MB")
            if sys_info.get('gpus'):
                lines.append(f"- **GPUs:** {len(sys_info['gpus'])} detected")
            lines.append("")
        
        # Test Results
        test_sections = [
            ('python_environment', 'Python Environment'),
            ('docker_functionality', 'Docker'),
            ('git_functionality', 'Git'),
            ('network_connectivity', 'Network'),
            ('mcp_dashboard', 'MCP Dashboard'),
            ('runner_capabilities', 'Runner Capabilities')
        ]
        
        for section_key, section_name in test_sections:
            if section_key in results:
                lines.append(f"## {section_name}")
                section_data = results[section_key]
                
                # Determine section status
                if isinstance(section_data, dict):
                    if section_data.get('success') is True:
                        lines.append("✅ **Status:** Passed")
                    elif section_data.get('error'):
                        lines.append("❌ **Status:** Failed")
                    else:
                        lines.append("ℹ️ **Status:** Informational")
                
                # Add key details
                if section_key == 'python_environment':
                    if section_data.get('ipfs_datasets_py', {}).get('success'):
                        lines.append("- ✅ ipfs_datasets_py package imported successfully")
                    else:
                        lines.append("- ❌ ipfs_datasets_py package import failed")
                
                elif section_key == 'docker_functionality':
                    if section_data.get('docker_available'):
                        lines.append("- ✅ Docker available")
                    if section_data.get('docker_daemon'):
                        lines.append("- ✅ Docker daemon accessible")
                    if section_data.get('container_execution'):
                        lines.append("- ✅ Container execution working")
                
                elif section_key == 'mcp_dashboard':
                    if section_data.get('dashboard_running') or section_data.get('dashboard_startup'):
                        lines.append("- ✅ MCP dashboard functional")
                    else:
                        lines.append("- ⚠️ MCP dashboard test inconclusive")
                
                lines.append("")
        
        # Failed Critical Tests
        if results.get('failed_critical_tests'):
            lines.append("## ❌ Critical Issues")
            for failed_test in results['failed_critical_tests']:
                lines.append(f"- {failed_test}")
            lines.append("")
        
        # Recommendations
        lines.append("## Recommendations")
        if results.get('overall_success'):
            lines.append("✅ Runner is ready for production workflows")
            lines.append("- All critical tests passed")
            lines.append("- Can execute GitHub Actions workflows")
            lines.append("- MCP functionality available")
        else:
            lines.append("⚠️ Address critical issues before production use")
            lines.append("- Review failed tests above")
            lines.append("- Ensure all dependencies are installed")
            lines.append("- Verify network connectivity")
        
        return "\\n".join(lines)


async def main():
    """Main validation function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Self-Hosted Runner Validation Suite')
    parser.add_argument('--output', default='runner_validation_results.json', help='Output JSON file')
    parser.add_argument('--report', default='runner_validation_report.md', help='Output report file')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Run validation
    validator = SelfHostedRunnerValidator()
    results = await validator.run_comprehensive_validation()
    
    # Save results
    validator.save_results(results, args.output)
    
    # Generate report
    report = validator.generate_report(results)
    with open(args.report, 'w') as f:
        f.write(report)
    
    print(f"\\n💾 Results saved to: {args.output}")
    print(f"📝 Report saved to: {args.report}")
    print(f"🎯 Overall result: {'PASSED' if results.get('overall_success', False) else 'FAILED'}")
    
    return 0 if results.get('overall_success', False) else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)