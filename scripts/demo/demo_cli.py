#!/usr/bin/env python3
"""
Demo script for the IPFS Datasets CLI tool.
Shows various CLI operations and their outputs.
"""

import subprocess
import time
import json

def run_demo_command(description, command, format_output=True):
    """Run a demo command and display the results."""
    print(f"\n🔹 {description}")
    print(f"   Command: {' '.join(command)}")
    print("   " + "─" * 50)
    
    try:
        if command[0] == "./ipfs-datasets":
            cmd = command
        else:
            cmd = ["python", "ipfs_datasets_cli.py"] + command[1:]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            output = result.stdout.strip()
            if format_output and output:
                # Try to format JSON output nicely
                if command and "--format" in command and "json" in command:
                    try:
                        data = json.loads(output)
                        # Show just key fields for demo
                        if "tool_categories" in data:
                            print(f"   📊 Found {data.get('total_categories', 0)} tool categories")
                            categories = list(data.get('tool_categories', {}).keys())[:5]
                            print(f"   📁 Sample categories: {', '.join(categories)}...")
                        elif "system" in data:
                            print(f"   💻 Platform: {data.get('system', {}).get('platform', 'Unknown')}")
                            print(f"   🐍 Python: {data.get('system', {}).get('python_version', 'Unknown')[:20]}...")
                            print(f"   🛠️  Tools: {data.get('mcp_tools', {}).get('total_categories', 0)} categories")
                        else:
                            print(f"   📋 Status: {data.get('status', 'unknown')}")
                    except json.JSONDecodeError:
                        print(f"   📝 Output: {output}")
                else:
                    print(f"   📝 Output: {output}")
            else:
                print(f"   📝 Output: {output}")
        else:
            print(f"   ❌ Error (code {result.returncode}): {result.stderr.strip()}")
    
    except subprocess.TimeoutExpired:
        print("   ⏰ Command timed out")
    except Exception as e:
        print(f"   💥 Exception: {e}")
    
    time.sleep(1)  # Small delay for better readability

def main():
    """Run the CLI demo."""
    print("🎭 IPFS Datasets CLI Demo")
    print("=" * 60)
    print("This demo shows the capabilities of the new CLI tool")
    print("that provides convenient access to MCP functionality.")
    
    # Basic information commands
    run_demo_command(
        "Check CLI status",
        ["./ipfs-datasets", "info", "status"]
    )
    
    run_demo_command(
        "Get system info (JSON format)",
        ["./ipfs-datasets", "--format", "json", "info", "status"]
    )
    
    run_demo_command(
        "List available tool categories",
        ["./ipfs-datasets", "info", "list-tools"]
    )
    
    run_demo_command(
        "Show CLI help",
        ["./ipfs-datasets", "--help"]
    )
    
    run_demo_command(
        "Show dataset commands help",
        ["./ipfs-datasets", "dataset", "--help"]
    )
    
    run_demo_command(
        "Show vector commands help", 
        ["./ipfs-datasets", "vector", "--help"]
    )
    
    # Test error handling
    run_demo_command(
        "Test error handling (invalid command)",
        ["./ipfs-datasets", "invalid", "command"]
    )
    
    print("\n" + "=" * 60)
    print("🎉 Demo completed!")
    print("\n📚 Key features demonstrated:")
    print("   • System status and tool discovery")
    print("   • JSON and pretty output formats")
    print("   • Hierarchical command structure")
    print("   • Comprehensive help system")
    print("   • Graceful error handling")
    print("   • 31 tool categories with 100+ individual tools")
    
    print("\n🚀 Ready to use! Try these commands:")
    print("   ./ipfs-datasets info status")
    print("   ./ipfs-datasets info list-tools")
    print("   ./ipfs-datasets --help")

if __name__ == "__main__":
    main()