#!/usr/bin/env python3
"""
Import Path Validation Script

This script validates that all import paths in test files match the actual
MCP tool structure and reports any inconsistencies.
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

class ImportPathValidator:
    def __init__(self):
        self.root_path = Path(__file__).parent.parent
        self.mcp_tools_path = self.root_path / "ipfs_datasets_py" / "mcp_server" / "tools"
        self.test_files = []
        self.errors = []
        self.warnings = []
        
    def discover_test_files(self) -> List[Path]:
        """Discover all test files that might contain MCP tool imports."""
        test_patterns = [
            "tests/**/*.py",
            "**/*test*.py",
            "**/test_*.py"
        ]
        
        test_files = []
        for pattern in test_patterns:
            test_files.extend(self.root_path.glob(pattern))
            
        # Filter to only files that likely contain MCP imports
        filtered_files = []
        for file_path in test_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if "mcp_server.tools" in content or "from ipfs_datasets_py" in content:
                        filtered_files.append(file_path)
            except Exception as e:
                self.warnings.append(f"Could not read {file_path}: {e}")
                
        return filtered_files
    
    def get_actual_tool_structure(self) -> Dict[str, List[str]]:
        """Get the actual MCP tool directory structure."""
        structure = {}
        
        if not self.mcp_tools_path.exists():
            self.errors.append(f"MCP tools path does not exist: {self.mcp_tools_path}")
            return structure
            
        for category_dir in self.mcp_tools_path.iterdir():
            if category_dir.is_dir() and not category_dir.name.startswith('__'):
                tools = []
                for tool_file in category_dir.iterdir():
                    if tool_file.is_file() and tool_file.suffix == '.py' and not tool_file.name.startswith('__'):
                        # Get the function/class name from the file
                        tool_name = tool_file.stem
                        tools.append(tool_name)
                        
                if tools:
                    structure[category_dir.name] = tools
                    
        return structure
    
    def extract_imports_from_file(self, file_path: Path) -> List[Tuple[str, int]]:
        """Extract MCP tool imports from a Python file."""
        imports = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                
                # Match import patterns
                patterns = [
                    r'from\s+ipfs_datasets_py\.mcp_server\.tools\.([^.\s]+)\.([^.\s]+)\s+import\s+([^.\s]+)',
                    r'import\s+ipfs_datasets_py\.mcp_server\.tools\.([^.\s]+)\.([^.\s]+)',
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, line)
                    if match:
                        imports.append((line.strip(), line_num))
                        
        except Exception as e:
            self.warnings.append(f"Could not parse {file_path}: {e}")
            
        return imports
    
    def validate_import_path(self, import_line: str, actual_structure: Dict[str, List[str]]) -> Tuple[bool, str]:
        """Validate a single import path against actual structure."""
        
        # Extract components from import
        from_match = re.search(r'from\s+ipfs_datasets_py\.mcp_server\.tools\.([^.\s]+)\.([^.\s]+)\s+import\s+([^.\s]+)', import_line)
        import_match = re.search(r'import\s+ipfs_datasets_py\.mcp_server\.tools\.([^.\s]+)\.([^.\s]+)', import_line)
        
        if from_match:
            category, tool, function = from_match.groups()
        elif import_match:
            category, tool = import_match.groups()
            function = None
        else:
            return False, "Could not parse import statement"
            
        # Check if category exists
        if category not in actual_structure:
            # Check for common naming issues
            suggested_categories = []
            for actual_category in actual_structure.keys():
                if category.replace('_tools', '') == actual_category.replace('_tools', ''):
                    suggested_categories.append(actual_category)
                elif category in actual_category or actual_category in category:
                    suggested_categories.append(actual_category)
                    
            if suggested_categories:
                return False, f"Category '{category}' not found. Did you mean: {', '.join(suggested_categories)}?"
            else:
                return False, f"Category '{category}' not found. Available categories: {', '.join(actual_structure.keys())}"
                
        # Check if tool exists in category
        if tool not in actual_structure[category]:
            suggested_tools = []
            for actual_tool in actual_structure[category]:
                if tool in actual_tool or actual_tool in tool:
                    suggested_tools.append(actual_tool)
                    
            if suggested_tools:
                return False, f"Tool '{tool}' not found in '{category}'. Did you mean: {', '.join(suggested_tools)}?"
            else:
                return False, f"Tool '{tool}' not found in '{category}'. Available tools: {', '.join(actual_structure[category])}"
                
        return True, "Valid import path"
    
    def generate_corrected_import(self, import_line: str, actual_structure: Dict[str, List[str]]) -> str:
        """Generate a corrected import statement."""
        # This is a basic implementation - could be enhanced with fuzzy matching
        
        from_match = re.search(r'from\s+ipfs_datasets_py\.mcp_server\.tools\.([^.\s]+)\.([^.\s]+)\s+import\s+([^.\s]+)', import_line)
        
        if from_match:
            old_category, old_tool, function = from_match.groups()
            
            # Try to find the correct category
            for category in actual_structure:
                if old_category.replace('_tools', '') == category.replace('_tools', ''):
                    # Try to find the correct tool
                    for tool in actual_structure[category]:
                        if old_tool in tool or tool in old_tool:
                            return f"from ipfs_datasets_py.mcp_server.tools.{category}.{tool} import {function}"
                            
        return f"# FIXME: Could not auto-correct: {import_line}"
    
    def validate_all_imports(self) -> Dict[str, any]:
        """Validate all imports in all test files."""
        print("🔍 Discovering test files...")
        test_files = self.discover_test_files()
        print(f"Found {len(test_files)} test files with MCP imports")
        
        print("\n📂 Analyzing actual MCP tool structure...")
        actual_structure = self.get_actual_tool_structure()
        print(f"Found {len(actual_structure)} tool categories:")
        for category, tools in actual_structure.items():
            print(f"  - {category}: {len(tools)} tools")
            
        print("\n🧪 Validating import paths...")
        results = {
            'valid_imports': [],
            'invalid_imports': [],
            'files_processed': 0,
            'total_imports': 0
        }
        
        for file_path in test_files:
            print(f"\nProcessing: {file_path.relative_to(self.root_path)}")
            imports = self.extract_imports_from_file(file_path)
            results['files_processed'] += 1
            results['total_imports'] += len(imports)
            
            for import_line, line_num in imports:
                is_valid, message = self.validate_import_path(import_line, actual_structure)
                
                import_info = {
                    'file': str(file_path.relative_to(self.root_path)),
                    'line': line_num,
                    'import': import_line,
                    'message': message
                }
                
                if is_valid:
                    results['valid_imports'].append(import_info)
                    print(f"  ✅ Line {line_num}: Valid")
                else:
                    import_info['suggested_fix'] = self.generate_corrected_import(import_line, actual_structure)
                    results['invalid_imports'].append(import_info)
                    print(f"  ❌ Line {line_num}: {message}")
                    print(f"     Original: {import_line}")
                    print(f"     Suggested: {import_info['suggested_fix']}")
                    
        return results
    
    def generate_fix_script(self, results: Dict[str, any]) -> str:
        """Generate a script to automatically fix import issues."""
        
        script_content = [
            "#!/usr/bin/env python3",
            '"""',
            "Auto-generated script to fix MCP tool import paths.",
            "Generated by validate_import_paths.py",
            '"""',
            "",
            "import re",
            "from pathlib import Path",
            "",
            "def fix_import_paths():",
            '    """Fix all invalid import paths."""',
            "    fixes = ["
        ]
        
        for invalid_import in results['invalid_imports']:
            script_content.append(f"        # {invalid_import['file']}:{invalid_import['line']}")
            script_content.append(f"        (")
            script_content.append(f"            Path('{invalid_import['file']}'),")
            script_content.append(f"            r'{re.escape(invalid_import['import'])}',")
            script_content.append(f"            '{invalid_import['suggested_fix'].replace('# FIXME: Could not auto-correct: ', '')}',")
            script_content.append(f"        ),")
            
        script_content.extend([
            "    ]",
            "",
            "    for file_path, old_import, new_import in fixes:",
            "        if file_path.exists():",
            "            with open(file_path, 'r') as f:",
            "                content = f.read()",
            "            ",
            "            if old_import in content:",
            "                content = content.replace(old_import, new_import)",
            "                with open(file_path, 'w') as f:",
            "                    f.write(content)",
            "                print(f'Fixed: {file_path}')",
            "            else:",
            "                print(f'Warning: Pattern not found in {file_path}')",
            "        else:",
            "            print(f'Warning: File not found: {file_path}')",
            "",
            "if __name__ == '__main__':",
            "    fix_import_paths()"
        ])
        
        return "\n".join(script_content)
    
    def run_validation(self):
        """Run the complete validation process."""
        print("🚀 MCP Tool Import Path Validation")
        print("=" * 50)
        
        results = self.validate_all_imports()
        
        print("\n📊 VALIDATION RESULTS")
        print("=" * 50)
        print(f"Files processed: {results['files_processed']}")
        print(f"Total imports found: {results['total_imports']}")
        print(f"Valid imports: {len(results['valid_imports'])}")
        print(f"Invalid imports: {len(results['invalid_imports'])}")
        
        if results['invalid_imports']:
            print(f"\n❌ ISSUES FOUND ({len(results['invalid_imports'])} invalid imports)")
            print("-" * 30)
            
            # Group by file
            by_file = {}
            for invalid in results['invalid_imports']:
                file_name = invalid['file']
                if file_name not in by_file:
                    by_file[file_name] = []
                by_file[file_name].append(invalid)
                
            for file_name, issues in by_file.items():
                print(f"\n📄 {file_name} ({len(issues)} issues)")
                for issue in issues:
                    print(f"   Line {issue['line']}: {issue['message']}")
                    
            # Generate fix script
            fix_script_path = self.root_path / "scripts" / "fix_import_paths.py"
            fix_script_content = self.generate_fix_script(results)
            
            with open(fix_script_path, 'w') as f:
                f.write(fix_script_content)
                
            print(f"\n🔧 Auto-fix script generated: {fix_script_path}")
            print("Run it with: python scripts/fix_import_paths.py")
            
        else:
            print("\n✅ ALL IMPORTS ARE VALID!")
            
        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)})")
            print("-" * 20)
            for warning in self.warnings:
                print(f"   {warning}")
                
        if self.errors:
            print(f"\n💥 ERRORS ({len(self.errors)})")
            print("-" * 15)
            for error in self.errors:
                print(f"   {error}")
                
        # Return success/failure
        return len(results['invalid_imports']) == 0 and len(self.errors) == 0

def main():
    validator = ImportPathValidator()
    success = validator.run_validation()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
