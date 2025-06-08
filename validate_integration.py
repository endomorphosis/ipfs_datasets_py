#!/usr/bin/env python3
"""
IPFS Embeddings Integration Validation Script

This script validates the integration setup for ipfs_embeddings_py into ipfs_datasets_py.
It checks dependencies, tool compatibility, and prepares for the migration.
"""

import sys
import subprocess
import importlib
try:
    from importlib.metadata import version, PackageNotFoundError
except ImportError:
    from importlib_metadata import version, PackageNotFoundError
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import traceback

class IntegrationValidator:
    """Validates the ipfs_embeddings_py integration setup."""
    
    def __init__(self):
        self.project_root = Path(__file__).parent
        self.ipfs_embeddings_path = self.project_root / "docs" / "ipfs_embeddings_py"
        self.ipfs_datasets_path = self.project_root / "ipfs_datasets_py"
        self.validation_results = {}
        
    def validate_all(self) -> Dict[str, bool]:
        """Run all validation checks."""
        print("IPFS Embeddings Integration Validation")
        print("=" * 50)
        
        checks = [
            ("Directory Structure", self.check_directory_structure),
            ("Dependencies", self.check_dependencies),
            ("Python Path", self.check_python_path),
            ("Basic Imports", self.check_basic_imports),
            ("MCP Tools Discovery", self.check_mcp_tools),
            ("Configuration", self.check_configuration),
            ("Integration Readiness", self.check_integration_readiness)
        ]
        
        for check_name, check_func in checks:
            print(f"\n{check_name}:")
            print("-" * 30)
            try:
                result = check_func()
                self.validation_results[check_name] = result
                status = "✅ PASS" if result else "❌ FAIL"
                print(f"Status: {status}")
            except Exception as e:
                print(f"❌ ERROR: {e}")
                self.validation_results[check_name] = False
                
        self.print_summary()
        return self.validation_results
        
    def check_directory_structure(self) -> bool:
        """Check if required directories exist."""
        required_paths = [
            self.ipfs_embeddings_path,
            self.ipfs_embeddings_path / "src" / "mcp_server" / "tools",
            self.ipfs_datasets_path / "mcp_server" / "tools",
            self.project_root / "requirements.txt"
        ]
        
        all_exist = True
        for path in required_paths:
            exists = path.exists()
            status = "✅" if exists else "❌"
            print(f"{status} {path}")
            if not exists:
                all_exist = False
                
        return all_exist
        
    def check_dependencies(self) -> bool:
        """Check if new dependencies are properly installed."""
        new_dependencies = [
            "fastapi", "uvicorn", "qdrant-client", "elasticsearch",
            "llama-index", "torch", "faiss-cpu", "PyJWT", "passlib"
        ]
        
        missing_deps = []
        for dep in new_dependencies:
            try:
                version(dep)
                print(f"✅ {dep}")
            except PackageNotFoundError:
                print(f"❌ {dep} - Not installed")
                missing_deps.append(dep)
                
        if missing_deps:
            print(f"\nMissing dependencies: {missing_deps}")
            print("Run: pip install -r requirements.txt")
            return False
            
        return True
        
    def check_python_path(self) -> bool:
        """Check if Python can find the ipfs_embeddings_py package."""
        try:
            sys.path.insert(0, str(self.ipfs_embeddings_path))
            sys.path.insert(0, str(self.ipfs_embeddings_path / "src"))
            
            # Test if we can import from the package
            import ipfs_embeddings_py
            print(f"✅ ipfs_embeddings_py module found at: {ipfs_embeddings_py.__file__}")
            return True
        except ImportError as e:
            print(f"❌ Cannot import ipfs_embeddings_py: {e}")
            return False
            
    def check_basic_imports(self) -> bool:
        """Check if basic modules can be imported."""
        try:
            sys.path.insert(0, str(self.ipfs_embeddings_path))
            sys.path.insert(0, str(self.ipfs_embeddings_path / "src"))
            
            # Test core imports
            test_imports = [
                "ipfs_embeddings_py.ipfs_embeddings",
                "src.mcp_server.server",
                "src.mcp_server.tool_registry"
            ]
            
            for module in test_imports:
                try:
                    importlib.import_module(module)
                    print(f"✅ {module}")
                except ImportError as e:
                    print(f"❌ {module}: {e}")
                    return False
                    
            return True
        except Exception as e:
            print(f"❌ Import error: {e}")
            return False
            
    def check_mcp_tools(self) -> bool:
        """Discover and validate MCP tools from ipfs_embeddings_py."""
        tools_path = self.ipfs_embeddings_path / "src" / "mcp_server" / "tools"
        
        if not tools_path.exists():
            print(f"❌ Tools directory not found: {tools_path}")
            return False
            
        tool_files = list(tools_path.glob("*.py"))
        tool_files = [f for f in tool_files if not f.name.startswith("__")]
        
        print(f"Found {len(tool_files)} tool files:")
        
        working_tools = 0
        for tool_file in tool_files:
            try:
                # Try to import the tool module
                module_name = f"src.mcp_server.tools.{tool_file.stem}"
                sys.path.insert(0, str(self.ipfs_embeddings_path))
                importlib.import_module(module_name)
                print(f"✅ {tool_file.name}")
                working_tools += 1
            except Exception as e:
                print(f"❌ {tool_file.name}: {str(e)[:100]}...")
                
        success_rate = working_tools / len(tool_files) if tool_files else 0
        print(f"\nTool import success rate: {working_tools}/{len(tool_files)} ({success_rate:.1%})")
        
        return success_rate >= 0.8  # 80% success rate threshold
        
    def check_configuration(self) -> bool:
        """Check configuration files and setup."""
        config_files = [
            self.project_root / "requirements.txt",
            self.ipfs_embeddings_path / "requirements.txt",
            self.ipfs_embeddings_path / "pyproject.toml"
        ]
        
        all_good = True
        for config_file in config_files:
            if config_file.exists():
                print(f"✅ {config_file.name}")
            else:
                print(f"❌ {config_file.name} - Missing")
                all_good = False
                
        # Check if ipfs_embeddings_py is mentioned in requirements.txt
        requirements_file = self.project_root / "requirements.txt"
        if requirements_file.exists():
            content = requirements_file.read_text()
            if "ipfs_embeddings_py" in content:
                print("✅ ipfs_embeddings_py referenced in requirements.txt")
            else:
                print("⚠️  ipfs_embeddings_py not explicitly referenced in requirements.txt")
                
        return all_good
        
    def check_integration_readiness(self) -> bool:
        """Check if the project is ready for integration."""
        readiness_checks = []
        
        # Check if MCP server exists in both projects
        ipfs_datasets_mcp = self.ipfs_datasets_path / "mcp_server"
        ipfs_embeddings_mcp = self.ipfs_embeddings_path / "src" / "mcp_server"
        
        readiness_checks.append(("ipfs_datasets_py MCP server", ipfs_datasets_mcp.exists()))
        readiness_checks.append(("ipfs_embeddings_py MCP server", ipfs_embeddings_mcp.exists()))
        
        # Check for tool directories
        datasets_tools = ipfs_datasets_mcp / "tools"
        embeddings_tools = ipfs_embeddings_mcp / "tools"
        
        readiness_checks.append(("ipfs_datasets_py tools", datasets_tools.exists()))
        readiness_checks.append(("ipfs_embeddings_py tools", embeddings_tools.exists()))
        
        # Check for configuration files
        readiness_checks.append(("Migration plan", (self.project_root / "IPFS_EMBEDDINGS_MIGRATION_PLAN.md").exists()))
        readiness_checks.append(("Tool mapping", (self.project_root / "IPFS_EMBEDDINGS_TOOL_MAPPING.md").exists()))
        
        all_ready = True
        for check_name, result in readiness_checks:
            status = "✅" if result else "❌"
            print(f"{status} {check_name}")
            if not result:
                all_ready = False
                
        return all_ready
        
    def print_summary(self):
        """Print validation summary."""
        print("\n" + "=" * 50)
        print("VALIDATION SUMMARY")
        print("=" * 50)
        
        passed = sum(1 for result in self.validation_results.values() if result)
        total = len(self.validation_results)
        
        for check, result in self.validation_results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status} {check}")
            
        print(f"\nOverall: {passed}/{total} checks passed ({passed/total:.1%})")
        
        if passed == total:
            print("\n🎉 Integration setup is ready!")
            print("Next steps:")
            print("1. Review the migration plan: IPFS_EMBEDDINGS_MIGRATION_PLAN.md")
            print("2. Review the tool mapping: IPFS_EMBEDDINGS_TOOL_MAPPING.md")
            print("3. Begin Phase 2 of the migration (MCP Tools Integration)")
        else:
            print("\n⚠️  Integration setup needs attention.")
            print("Please fix the failing checks before proceeding.")
            
    def generate_next_steps(self):
        """Generate specific next steps based on validation results."""
        print("\n" + "=" * 50)
        print("RECOMMENDED NEXT STEPS")
        print("=" * 50)
        
        if not self.validation_results.get("Dependencies", False):
            print("1. Install missing dependencies:")
            print("   pip install -r requirements.txt")
            
        if not self.validation_results.get("Basic Imports", False):
            print("2. Fix import issues:")
            print("   - Check Python path configuration")
            print("   - Verify package structure")
            
        if not self.validation_results.get("MCP Tools Discovery", False):
            print("3. Fix MCP tool issues:")
            print("   - Review tool import errors")
            print("   - Check for missing dependencies")
            
        if self.validation_results.get("Integration Readiness", True):
            print("4. Begin integration:")
            print("   - Start with Phase 2: MCP Tools Integration")
            print("   - Follow the migration plan timeline")

def main():
    """Main validation function."""
    validator = IntegrationValidator()
    results = validator.validate_all()
    validator.generate_next_steps()
    
    # Exit with error code if validation fails
    success_rate = sum(1 for result in results.values() if result) / len(results)
    if success_rate < 1.0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
