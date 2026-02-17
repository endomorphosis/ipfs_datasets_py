#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VSCode CLI Authentication Examples

This script demonstrates various ways to authenticate with VSCode CLI
for tunnel functionality, supporting both GitHub and Microsoft providers.

Methods demonstrated:
1. Using configure_auth() method
2. Using install_with_auth() convenience method
3. Using command-line interface
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def example_configure_auth():
    """
    Example 1: Configure authentication after installation.
    
    This is useful when you already have VSCode CLI installed and
    just want to set up authentication.
    """
    print("\n" + "="*80)
    print("Example 1: Configure Authentication (GitHub)")
    print("="*80)
    
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    
    # Create VSCode CLI instance
    cli = VSCodeCLI()
    
    # Check if installed
    if not cli.is_installed():
        print("VSCode CLI is not installed.")
        print("Installing first...")
        success = cli.download_and_install()
        if not success:
            print("Installation failed. Cannot proceed.")
            return
    
    # Configure authentication with GitHub
    print("\nConfiguring authentication with GitHub...")
    result = cli.configure_auth(provider='github')
    
    print(f"\nAuthentication {'successful' if result['success'] else 'failed'}!")
    print(f"Provider: {result['provider']}")
    print(f"Message: {result['message']}")
    
    if result.get('stdout'):
        print("\nInstructions:")
        print(result['stdout'])


def example_configure_auth_microsoft():
    """
    Example 2: Configure authentication with Microsoft provider.
    """
    print("\n" + "="*80)
    print("Example 2: Configure Authentication (Microsoft)")
    print("="*80)
    
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    
    cli = VSCodeCLI()
    
    # Configure authentication with Microsoft
    print("\nConfiguring authentication with Microsoft...")
    result = cli.configure_auth(provider='microsoft')
    
    print(f"\nAuthentication {'successful' if result['success'] else 'failed'}!")
    print(f"Provider: {result['provider']}")
    print(f"Message: {result['message']}")


def example_install_with_auth():
    """
    Example 3: Install and authenticate in one step.
    
    This convenience method handles both installation and authentication,
    making it easy to get started from scratch.
    """
    print("\n" + "="*80)
    print("Example 3: Install with Authentication (One-Step Setup)")
    print("="*80)
    
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    import tempfile
    
    # Use a temporary directory for this example
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = VSCodeCLI(install_dir=tmpdir)
        
        print("\nInstalling VSCode CLI and configuring authentication...")
        print("This will:")
        print("  1. Download and install VSCode CLI")
        print("  2. Configure authentication with GitHub")
        print("  3. Return complete status")
        
        result = cli.install_with_auth(provider='github')
        
        print(f"\nInstallation: {'✓' if result['install_success'] else '✗'}")
        print(f"Authentication: {'✓' if result['auth_success'] else '✗'}")
        print(f"Provider: {result['provider']}")
        print(f"Overall: {result['message']}")
        
        print("\nDetailed steps:")
        for msg in result['messages']:
            print(f"  • {msg}")
        
        if result.get('status'):
            status = result['status']
            print(f"\nFinal status:")
            print(f"  Installed: {status['installed']}")
            print(f"  Version: {status['version']}")
            print(f"  Platform: {status['platform']}")


def example_cli_usage():
    """
    Example 4: Command-line interface usage.
    
    Shows how to use the CLI commands for authentication.
    """
    print("\n" + "="*80)
    print("Example 4: Command-Line Interface Usage")
    print("="*80)
    
    print("\n1. Configure authentication (interactive):")
    print("   $ ipfs-datasets vscode auth --provider github")
    print("   or")
    print("   $ ipfs-datasets vscode auth --provider microsoft")
    
    print("\n2. Configure authentication (JSON output):")
    print("   $ ipfs-datasets vscode auth --provider github --json")
    
    print("\n3. Install and authenticate in one step:")
    print("   $ ipfs-datasets vscode install-with-auth --provider github")
    
    print("\n4. Install and authenticate (JSON output):")
    print("   $ ipfs-datasets vscode install-with-auth --provider github --json")
    
    print("\n5. Use custom installation directory:")
    print("   $ ipfs-datasets vscode auth --provider github --install-dir /custom/path")
    
    print("\n6. Traditional tunnel login (still available):")
    print("   $ ipfs-datasets vscode tunnel login --provider github")


def example_complete_workflow():
    """
    Example 5: Complete workflow from installation to tunnel setup.
    """
    print("\n" + "="*80)
    print("Example 5: Complete Workflow - Ready for Remote Development")
    print("="*80)
    
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        print("\nStep 1: Create VSCode CLI instance")
        cli = VSCodeCLI(install_dir=tmpdir)
        print(f"  Installation directory: {tmpdir}")
        
        print("\nStep 2: Install with authentication")
        result = cli.install_with_auth(provider='github')
        print(f"  Installation: {'✓' if result['install_success'] else '✗'}")
        print(f"  Authentication: {'✓' if result['auth_success'] else '✗'}")
        
        if result['install_success'] and result['auth_success']:
            print("\nStep 3: Install tunnel service (example)")
            print("  $ code tunnel service install --name my-tunnel")
            print("\nStep 4: Start tunnel")
            print("  $ code tunnel service start")
            print("\n✓ Ready for remote development!")
        else:
            print("\n✗ Setup incomplete. Please check the errors above.")


def main():
    """Run all examples."""
    print("\n" + "="*80)
    print("VSCode CLI Authentication Examples")
    print("="*80)
    print("\nThis script demonstrates various ways to authenticate with VSCode CLI")
    print("for tunnel functionality.")
    
    # Example 1: Configure auth after installation
    try:
        example_configure_auth()
    except Exception as e:
        print(f"Example 1 error (expected in test environment): {e}")
    
    # Example 2: Configure auth with Microsoft
    try:
        example_configure_auth_microsoft()
    except Exception as e:
        print(f"Example 2 error (expected in test environment): {e}")
    
    # Example 3: Install with auth
    try:
        example_install_with_auth()
    except Exception as e:
        print(f"Example 3 error (expected in test environment): {e}")
    
    # Example 4: CLI usage
    example_cli_usage()
    
    # Example 5: Complete workflow
    try:
        example_complete_workflow()
    except Exception as e:
        print(f"Example 5 error (expected in test environment): {e}")
    
    print("\n" + "="*80)
    print("Examples completed!")
    print("="*80)
    print("\nKey Points:")
    print("  • Use configure_auth() to set up authentication on existing installation")
    print("  • Use install_with_auth() for one-step setup from scratch")
    print("  • CLI commands: 'auth' and 'install-with-auth' available")
    print("  • Both GitHub and Microsoft authentication supported")
    print("  • Works with custom installation directories")


if __name__ == "__main__":
    main()
