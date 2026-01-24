#!/usr/bin/env python3
"""
Fix script to address failing development tools by improving tool discovery.
The issue is that the test script is treating standard library imports as MCP tools.
"""

import anyio
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

def identify_standard_library_functions():
    """Identify standard library and non-MCP functions that should be excluded"""
    excluded_functions = {
        # Python standard library functions
        'dataclass', 'asdict', 'field', 'abstractmethod', 'as_completed',
        
        # Other common imports that aren't MCP tools
        'wraps', 'partial', 'reduce', 'filter', 'map', 'zip', 'enumerate',
        'range', 'len', 'str', 'int', 'bool', 'list', 'dict', 'set', 'tuple',
        'open', 'print', 'input', 'type', 'isinstance', 'hasattr', 'getattr',
        'setattr', 'delattr', 'callable', 'iter', 'next', 'all', 'any',
        'min', 'max', 'sum', 'abs', 'round', 'sorted', 'reversed',
        
        # Async functions
        'aiofiles', 'asyncio', 'aiohttp', 'async', 'await',
        
        # Logging and config
        'logging', 'config', 'logger',
        
        # Path and file operations  
        'Path', 'pathlib', 'os', 'sys', 'shutil', 'glob',
        
        # JSON and data handling
        'json', 'yaml', 'csv', 'pickle', 'base64',
        
        # Time and datetime
        'time', 'datetime', 'timedelta',
        
        # Regular expressions
        're', 'match', 'search', 'findall', 'sub',
        
        # Collections
        'defaultdict', 'Counter', 'OrderedDict', 'namedtuple',
        
        # Typing
        'List', 'Dict', 'Tuple', 'Set', 'Optional', 'Union', 'Any', 'Callable',
        
        # Exception handling
        'Exception', 'ValueError', 'TypeError', 'KeyError', 'AttributeError',
        'ImportError', 'FileNotFoundError', 'PermissionError'
    }
    
    return excluded_functions

def create_improved_discovery_filter():
    """Create an improved tool discovery filter"""
    excluded = identify_standard_library_functions()
    
    filter_code = f'''
def is_valid_mcp_tool(name: str, obj: Any, module_name: str) -> bool:
    """
    Determine if a function/object is a valid MCP tool.
    
    Args:
        name: Function/object name
        obj: The function/object
        module_name: Module where it's defined
        
    Returns:
        True if it's a valid MCP tool, False otherwise
    """
    # Exclude standard library and common imports
    excluded_names = {excluded}
    
    if name in excluded_names:
        return False
        
    # Must be a function or coroutine
    if not (inspect.isfunction(obj) or inspect.iscoroutinefunction(obj)):
        return False
        
    # Skip private functions
    if name.startswith("_"):
        return False
        
    # Must be defined in the current module (not imported)
    if hasattr(obj, '__module__') and obj.__module__ != module_name:
        return False
        
    # Must have parameters (MCP tools take arguments)
    try:
        sig = inspect.signature(obj)
        if len(sig.parameters) == 0:
            return False
    except (ValueError, TypeError):
        return False
        
    # Additional checks for specific naming patterns
    mcp_tool_patterns = [
        'load_', 'save_', 'create_', 'generate_', 'process_', 'convert_',
        'record_', 'search_', 'get_', 'pin_', 'extract_', 'index_',
        'check_', 'query_', 'execute_', 'list_', 'use_'
    ]
    
    # If name starts with common MCP tool patterns, it's likely a valid tool
    if any(name.startswith(pattern) for pattern in mcp_tool_patterns):
        return True
        
    # Otherwise, be more selective - require it to be in a specific tool file
    # that matches the function name
    if name.lower() in module_name.lower():
        return True
        
    return False
'''
    
    return filter_code

async def test_fixed_discovery():
    """Test the improved discovery logic"""
    print("🔧 Testing improved tool discovery...")
    
    # Import the test framework
    from complete_mcp_discovery_test import CompleteMCPToolTester
    
    # Create modified tester
    tester = CompleteMCPToolTester()
    
    # Get the original discovery function
    original_discovery = tester._discover_tools_in_category
    
    # Create our improved version
    def improved_discover_tools_in_category(self, category_path, category_name):
        """Improved tool discovery with better filtering"""
        import inspect
        import importlib
        from typing import Any
        
        tools = []
        
        # Exclude list
        excluded_names = identify_standard_library_functions()
        
        # Look for Python files
        for py_file in category_path.rglob("*.py"):
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue
                
            try:
                # Convert file path to module name
                relative_path = py_file.relative_to(Path(__file__).parent)
                module_name = str(relative_path.with_suffix("")).replace("/", ".")
                
                # Try to import the module
                try:
                    module = importlib.import_module(module_name)
                except Exception as e:
                    print(f"⚠️  Failed to import {module_name}: {e}")
                    continue
                
                # Find callable functions/tools with improved filtering
                for name, obj in inspect.getmembers(module):
                    # Skip if in exclude list
                    if name in excluded_names:
                        continue
                        
                    # Must be a function or coroutine
                    if not (inspect.isfunction(obj) or inspect.iscoroutinefunction(obj)):
                        continue
                        
                    # Skip private functions
                    if name.startswith("_"):
                        continue
                        
                    # Must be defined in the current module (not imported)
                    if hasattr(obj, '__module__') and obj.__module__ != module_name:
                        continue
                        
                    # Must have parameters (MCP tools take arguments)
                    try:
                        sig = inspect.signature(obj)
                        if len(sig.parameters) == 0:
                            continue
                    except (ValueError, TypeError):
                        continue
                        
                    # Additional validation for MCP tools
                    mcp_tool_patterns = [
                        'load_', 'save_', 'create_', 'generate_', 'process_', 'convert_',
                        'record_', 'search_', 'get_', 'pin_', 'extract_', 'index_',
                        'check_', 'query_', 'execute_', 'list_', 'use_', 'run_'
                    ]
                    
                    # If name starts with common MCP tool patterns, it's likely valid
                    is_mcp_tool = any(name.startswith(pattern) for pattern in mcp_tool_patterns)
                    
                    # Or if it's in a file that matches the function name
                    if not is_mcp_tool and name.lower() in py_file.stem.lower():
                        is_mcp_tool = True
                        
                    # Or if it's a known MCP tool function
                    known_tools = {
                        'test_generator', 'codebase_search', 'documentation_generator', 
                        'lint_python_codebase', 'development_tool_mcp_wrapper',
                        'set_config', 'audit_log'
                    }
                    if name in known_tools:
                        is_mcp_tool = True
                    
                    if is_mcp_tool:
                        tools.append({
                            "name": name,
                            "function": obj,
                            "module": module_name,
                            "file": str(py_file),
                            "is_async": inspect.iscoroutinefunction(obj),
                            "signature": str(sig),
                            "category": category_name
                        })
                        
            except Exception as e:
                print(f"⚠️  Error processing {py_file}: {e}")
                continue
                
        return tools
    
    # Replace the method
    import types
    tester._discover_tools_in_category = types.MethodType(improved_discover_tools_in_category, tester)
    
    # Test discovery
    print("📋 Discovering tools with improved filtering...")
    discovered = tester.discover_all_tools()
    
    print("\n📊 Discovery Results:")
    total_tools = 0
    for category, tools in discovered.items():
        print(f"  {category}: {len(tools)} tools")
        for tool in tools:
            print(f"    - {tool['name']} ({'async' if tool['is_async'] else 'sync'})")
        total_tools += len(tools)
        
    print(f"\nTotal tools discovered: {total_tools}")
    
    # Check development_tools specifically
    dev_tools = discovered.get('development_tools', [])
    print(f"\n🔧 Development Tools Found: {len(dev_tools)}")
    for tool in dev_tools:
        print(f"  ✓ {tool['name']} - {tool['file']}")
    
    return discovered

async def fix_specific_development_tools():
    """Fix specific development tool issues"""
    print("\n🔨 Fixing specific development tool issues...")
    
    # Issues to fix:
    # 1. dataclass parameter issue: "dataclass() got some positional-only arguments passed as keyword arguments: 'cls'"
    # 2. asdict parameter issue: "asdict() should be called on dataclass instances"
    # 3. abstractmethod parameter issue: "'str' object has no attribute '__isabstractmethod__'"
    # 4. development_tool_mcp_wrapper parameter issue: "'str' object has no attribute '__name__'"
    # 5. run_comprehensive_tests asyncio issue: "anyio.run() cannot be called from a running event loop"
    # 6. test_generator and lint_python_codebase module attribute issues
    
    fixes = {
        'dataclass': 'Skip - standard library decorator, not an MCP tool',
        'asdict': 'Skip - standard library function, not an MCP tool', 
        'abstractmethod': 'Skip - standard library decorator, not an MCP tool',
        'field': 'Skip - standard library function, not an MCP tool',
        'as_completed': 'Skip - asyncio function, not an MCP tool',
        'development_tool_mcp_wrapper': 'Fix parameter handling',
        'run_comprehensive_tests': 'Fix asyncio event loop issue',
        'test_generator': 'Check module attribute access',
        'lint_python_codebase': 'Check module attribute access'
    }
    
    print("🔍 Issues identified:")
    for tool, fix in fixes.items():
        print(f"  - {tool}: {fix}")
    
    return fixes

async def main():
    """Main fix execution"""
    print("🚀 Starting development tools fix...")
    
    # Test improved discovery
    discovered = await test_fixed_discovery()
    
    # Fix specific issues
    fixes = await fix_specific_development_tools()
    
    # Calculate expected improvement
    dev_tools_count = len(discovered.get('development_tools', []))
    excluded_count = sum(1 for fix in fixes.values() if fix.startswith('Skip'))
    expected_valid_tools = dev_tools_count - excluded_count
    
    print(f"\n📈 Expected Improvement:")
    print(f"  Total dev tools found: {dev_tools_count}")
    print(f"  Non-MCP tools to exclude: {excluded_count}")
    print(f"  Valid MCP tools expected: {expected_valid_tools}")
    print(f"  This should improve the development_tools pass rate significantly!")
    
    print("\n✅ Fix analysis complete!")
    print("Next step: Update the comprehensive test script with improved filtering.")

if __name__ == "__main__":
    anyio.run(main())
