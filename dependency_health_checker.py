#!/usr/bin/env python3
"""
Dependency Health Monitor
Monitors dependency status and provides health checks for CLI tools.
"""

import os
import sys
import json
import subprocess
import importlib
import time
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import argparse

@dataclass
class HealthStatus:
    """Health status for a dependency"""
    name: str
    status: str  # 'ok', 'missing', 'error', 'outdated'
    version: Optional[str] = None
    error: Optional[str] = None
    import_time: Optional[float] = None
    recommendation: Optional[str] = None

class DependencyHealthChecker:
    """Check health status of dependencies"""
    
    def __init__(self):
        self.critical_deps = [
            'numpy', 'pandas', 'requests', 'yaml', 'tqdm', 'psutil'
        ]
        
        self.optional_deps = [
            'torch', 'transformers', 'datasets', 'pydantic', 'networkx',
            'PIL', 'bs4', 'nltk', 'scipy', 'sklearn'
        ]
        
        self.cli_deps = [
            'json', 'argparse', 'subprocess', 'pathlib', 'sys', 'os'
        ]

        # System-level tools (binaries) used by some features. These are validated
        # via PATH lookup + a lightweight version command.
        self.system_tools = {
            'ffmpeg': ['ffmpeg', '-version'],
            'tesseract': ['tesseract', '--version'],
            # poppler-utils provides these
            'pdfinfo': ['pdfinfo', '-v'],
            'pdftoppm': ['pdftoppm', '-v'],
        }

    def check_system_tool(self, tool_name: str, version_cmd: List[str]) -> HealthStatus:
        """Check health of a system tool (binary in PATH)."""
        start_time = time.time()
        if shutil.which(tool_name) is None:
            return HealthStatus(
                name=tool_name,
                status='missing',
                error=f"'{tool_name}' not found in PATH",
                recommendation=(
                    f"Install system dependency for {tool_name} (or enable zero-touch local bin installs)"
                ),
            )

        try:
            result = subprocess.run(version_cmd, capture_output=True, text=True, timeout=10)
            import_time = time.time() - start_time
            if result.returncode != 0:
                return HealthStatus(
                    name=tool_name,
                    status='error',
                    error=(result.stderr or result.stdout or '').strip() or f"Non-zero exit ({result.returncode})",
                    import_time=import_time,
                    recommendation=f"Reinstall/repair {tool_name} or use local bin fallback",
                )

            # Attempt to extract something vaguely version-like (best effort)
            first_line = (result.stdout or result.stderr or '').splitlines()[:1]
            version = first_line[0].strip() if first_line else None
            return HealthStatus(
                name=tool_name,
                status='ok',
                version=version,
                import_time=import_time,
            )
        except subprocess.TimeoutExpired:
            return HealthStatus(
                name=tool_name,
                status='error',
                error='Timeout while running version command',
                recommendation=f"Check {tool_name} installation or use local bin fallback",
            )
        except Exception as e:
            return HealthStatus(
                name=tool_name,
                status='error',
                error=str(e),
                recommendation=f"Check {tool_name} installation or use local bin fallback",
            )
    
    def check_dependency_health(self, name: str) -> HealthStatus:
        """Check health of a single dependency"""
        start_time = time.time()
        
        try:
            module = importlib.import_module(name)
            import_time = time.time() - start_time
            
            # Get version if available
            version = getattr(module, '__version__', None)
            if not version:
                for attr in ['version', 'VERSION', '_version']:
                    version = getattr(module, attr, None)
                    if version:
                        break
            
            # Check if version is outdated (simplified check)
            status = 'ok'
            recommendation = None
            
            if import_time > 5.0:  # Slow import
                recommendation = f"Slow import ({import_time:.1f}s) - consider reinstalling"
            
            return HealthStatus(
                name=name,
                status=status,
                version=str(version) if version else None,
                import_time=import_time,
                recommendation=recommendation
            )
            
        except ImportError as e:
            return HealthStatus(
                name=name,
                status='missing',
                error=str(e),
                recommendation=f"Install with: pip install {name}"
            )
        except Exception as e:
            return HealthStatus(
                name=name,
                status='error',
                error=str(e),
                recommendation=f"Reinstall with: pip install --upgrade {name}"
            )
    
    def check_all_dependencies(self) -> Dict[str, Dict[str, HealthStatus]]:
        """Check health of all dependency categories"""
        results = {
            'critical': {},
            'optional': {},
            'cli': {},
            'system': {},
        }
        
        print("🏥 Checking dependency health...")
        
        # Check critical dependencies
        for dep in self.critical_deps:
            results['critical'][dep] = self.check_dependency_health(dep)
            
        # Check optional dependencies  
        for dep in self.optional_deps:
            results['optional'][dep] = self.check_dependency_health(dep)
            
        # Check CLI dependencies (should always be available)
        for dep in self.cli_deps:
            results['cli'][dep] = self.check_dependency_health(dep)

        # Check system tools
        for tool, cmd in self.system_tools.items():
            results['system'][tool] = self.check_system_tool(tool, cmd)
        
        return results
    
    def check_cli_functionality(self) -> Dict[str, Dict]:
        """Test CLI functionality"""
        tests = {
            'basic_cli': {
                'cmd': [sys.executable, 'ipfs_datasets_cli.py', '--help'],
                'description': 'Basic CLI help',
                'critical': True
            },
            'enhanced_cli': {
                'cmd': [sys.executable, 'enhanced_cli.py', '--help'],
                'description': 'Enhanced CLI help',
                'critical': True
            },
            'cli_status': {
                'cmd': [sys.executable, 'ipfs_datasets_cli.py', 'info', 'status'],
                'description': 'CLI status command',
                'critical': True
            },
            'cli_list_tools': {
                'cmd': [sys.executable, 'ipfs_datasets_cli.py', 'info', 'list-tools'],
                'description': 'CLI list tools',
                'critical': False
            },
            'enhanced_list_categories': {
                'cmd': [sys.executable, 'enhanced_cli.py', '--list-categories'],
                'description': 'Enhanced CLI list categories',
                'critical': False
            }
        }
        
        results = {}
        
        print("🧪 Testing CLI functionality...")
        
        for test_name, test_config in tests.items():
            try:
                result = subprocess.run(
                    test_config['cmd'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                results[test_name] = {
                    'success': result.returncode == 0,
                    'description': test_config['description'],
                    'critical': test_config['critical'],
                    'returncode': result.returncode,
                    'stdout_length': len(result.stdout) if result.stdout else 0,
                    'stderr': result.stderr if result.returncode != 0 else None
                }
                
            except subprocess.TimeoutExpired:
                results[test_name] = {
                    'success': False,
                    'description': test_config['description'],
                    'critical': test_config['critical'],
                    'error': 'Timeout'
                }
            except Exception as e:
                results[test_name] = {
                    'success': False,
                    'description': test_config['description'],
                    'critical': test_config['critical'],
                    'error': str(e)
                }
        
        return results
    
    def generate_health_report(self) -> Dict:
        """Generate comprehensive health report"""
        # Check dependencies
        dep_results = self.check_all_dependencies()
        
        # Check CLI functionality
        cli_results = self.check_cli_functionality()
        
        # Calculate summary statistics
        critical_ok = sum(1 for status in dep_results['critical'].values() 
                         if status.status == 'ok')
        critical_total = len(dep_results['critical'])
        
        optional_ok = sum(1 for status in dep_results['optional'].values() 
                         if status.status == 'ok')
        optional_total = len(dep_results['optional'])
        
        cli_tests_passed = sum(1 for result in cli_results.values() 
                              if result['success'])
        cli_tests_total = len(cli_results)
        
        critical_cli_passed = sum(1 for result in cli_results.values() 
                                 if result['success'] and result['critical'])
        critical_cli_total = sum(1 for result in cli_results.values() 
                               if result['critical'])

        system_ok = sum(1 for status in dep_results['system'].values() if status.status == 'ok')
        system_total = len(dep_results['system'])
        
        # Determine overall health
        overall_health = 'healthy'
        if critical_ok < critical_total or critical_cli_passed < critical_cli_total:
            overall_health = 'critical'
        elif optional_ok < optional_total * 0.5 or cli_tests_passed < cli_tests_total * 0.8 or system_ok < system_total:
            overall_health = 'degraded'
        
        return {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'overall_health': overall_health,
            'summary': {
                'critical_dependencies': f"{critical_ok}/{critical_total}",
                'optional_dependencies': f"{optional_ok}/{optional_total}",
                'cli_tests': f"{cli_tests_passed}/{cli_tests_total}",
                'critical_cli_tests': f"{critical_cli_passed}/{critical_cli_total}",
                'system_tools': f"{system_ok}/{system_total}",
            },
            'dependencies': dep_results,
            'cli_functionality': cli_results,
            'recommendations': self._generate_recommendations(dep_results, cli_results)
        }
    
    def _generate_recommendations(self, dep_results: Dict, cli_results: Dict) -> List[str]:
        """Generate recommendations based on health check results"""
        recommendations = []
        
        # Check for missing critical dependencies
        for name, status in dep_results['critical'].items():
            if status.status == 'missing':
                recommendations.append(f"🚨 CRITICAL: Install {name} with: pip install {name}")
            elif status.status == 'error':
                recommendations.append(f"🚨 CRITICAL: Fix {name} - {status.error}")
        
        # Check for failed critical CLI tests
        for test_name, result in cli_results.items():
            if not result['success'] and result['critical']:
                recommendations.append(f"🚨 CRITICAL: CLI test '{result['description']}' failed")
        
        # Check for missing optional dependencies
        missing_optional = [name for name, status in dep_results['optional'].items() 
                           if status.status == 'missing']
        if missing_optional:
            recommendations.append(f"💡 Consider installing optional packages: {', '.join(missing_optional[:3])}")

        # Check for missing system tools
        missing_tools = [name for name, status in dep_results.get('system', {}).items() if status.status != 'ok']
        if missing_tools:
            recommendations.append(f"💡 System tools missing/degraded: {', '.join(missing_tools[:3])}")
        
        # Check for slow imports
        slow_imports = [status.name for status in dep_results['critical'].values() 
                       if status.import_time and status.import_time > 2.0]
        if slow_imports:
            recommendations.append(f"⚠️ Slow imports detected: {', '.join(slow_imports)} - consider reinstalling")
        
        # General recommendations
        if not recommendations:
            recommendations.append("✅ All critical dependencies are healthy!")
        
        return recommendations

def print_health_report(report: Dict):
    """Print formatted health report"""
    print(f"\n🏥 Dependency Health Report - {report['timestamp']}")
    print("=" * 60)
    
    # Overall status
    health_emoji = {
        'healthy': '✅',
        'degraded': '⚠️',
        'critical': '🚨'
    }
    
    emoji = health_emoji.get(report['overall_health'], '❓')
    print(f"Overall Health: {emoji} {report['overall_health'].upper()}")
    
    # Summary
    summary = report['summary']
    print(f"\n📊 Summary:")
    print(f"  Critical Dependencies: {summary['critical_dependencies']}")
    print(f"  Optional Dependencies: {summary['optional_dependencies']}")
    print(f"  CLI Tests: {summary['cli_tests']}")
    print(f"  Critical CLI Tests: {summary['critical_cli_tests']}")
    if 'system_tools' in summary:
        print(f"  System Tools: {summary['system_tools']}")
    
    # Critical dependency details
    print(f"\n🔴 Critical Dependencies:")
    for name, status in report['dependencies']['critical'].items():
        emoji = '✅' if status.status == 'ok' else '❌'
        version_str = f" v{status.version}" if status.version else ""
        print(f"  {emoji} {name:12s}{version_str}")
        if status.error:
            print(f"      Error: {status.error}")
    
    # CLI test details
    print(f"\n🧪 CLI Functionality:")
    for test_name, result in report['cli_functionality'].items():
        emoji = '✅' if result['success'] else '❌'
        critical_mark = " [CRITICAL]" if result['critical'] else ""
        print(f"  {emoji} {result['description']}{critical_mark}")
        if not result['success'] and 'error' in result:
            print(f"      Error: {result['error']}")

    # System tool details
    if 'system' in report.get('dependencies', {}):
        print(f"\n🧰 System Tools:")
        for name, status in report['dependencies']['system'].items():
            emoji = '✅' if status.status == 'ok' else '❌'
            version_str = f" - {status.version}" if status.version and status.status == 'ok' else ""
            print(f"  {emoji} {name:12s}{version_str}")
            if status.error and status.status != 'ok':
                print(f"      Error: {status.error}")
    
    # Recommendations
    print(f"\n💡 Recommendations:")
    for rec in report['recommendations']:
        print(f"  {rec}")

def monitor_mode(interval: int = 300):
    """Run health checks in monitoring mode"""
    checker = DependencyHealthChecker()
    
    print(f"🔄 Starting dependency health monitoring (checking every {interval} seconds)")
    print("Press Ctrl+C to stop")
    
    try:
        while True:
            report = checker.generate_health_report()
            
            # Save report
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            report_file = f"health_report_{timestamp}.json"
            
            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            
            # Print summary
            health = report['overall_health']
            critical_deps = report['summary']['critical_dependencies']
            cli_tests = report['summary']['cli_tests']
            
            print(f"[{report['timestamp']}] Health: {health} | "
                  f"Critical Deps: {critical_deps} | CLI Tests: {cli_tests}")
            
            if health == 'critical':
                print("🚨 CRITICAL issues detected! Check full report.")
                print_health_report(report)
                
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped")

def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(description='IPFS Datasets Dependency Health Checker')
    parser.add_argument('command', choices=['check', 'monitor', 'report'],
                       help='Command to execute')
    parser.add_argument('--interval', type=int, default=300,
                       help='Monitoring interval in seconds (default: 300)')
    parser.add_argument('--output', help='Output file for reports')
    parser.add_argument('--quiet', action='store_true', help='Quiet mode (minimal output)')
    
    args = parser.parse_args()
    
    checker = DependencyHealthChecker()
    
    if args.command == 'check':
        report = checker.generate_health_report()
        
        if not args.quiet:
            print_health_report(report)
        
        # Save report if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            print(f"\n📄 Report saved to {args.output}")
        
        # Exit with appropriate code
        if report['overall_health'] == 'critical':
            return 1
        else:
            return 0
            
    elif args.command == 'monitor':
        monitor_mode(args.interval)
        return 0
        
    elif args.command == 'report':
        report = checker.generate_health_report()
        output_file = args.output or 'dependency_health_report.json'
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"📄 Health report saved to {output_file}")
        return 0

if __name__ == '__main__':
    sys.exit(main())