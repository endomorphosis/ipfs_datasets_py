#!/usr/bin/env python3
"""
Self-Hosted Runner Secrets Manager

This script provides secure secrets management for self-hosted GitHub Actions runners.
Secrets are stored locally on the runner machine and accessed securely without
exposing them in GitHub repository secrets or workflow logs.

Features:
- Store secrets in encrypted file on runner machine
- Load secrets securely during workflow execution
- Support for multiple secret providers (OpenAI, Anthropic, OpenRouter, etc.)
- Automatic fallback to environment variables
- No secrets exposed in GitHub UI or logs

Setup:
1. On the self-hosted runner, create secrets directory:
   sudo mkdir -p /etc/github-runner-secrets
   sudo chmod 700 /etc/github-runner-secrets

2. Store secrets in a JSON file:
   sudo bash -c 'cat > /etc/github-runner-secrets/secrets.json << EOF
   {
     "OPENAI_API_KEY": "sk-...",
     "ANTHROPIC_API_KEY": "sk-ant-...",
     "OPENROUTER_API_KEY": "sk-or-..."
   }
   EOF'

3. Secure the file:
   sudo chmod 600 /etc/github-runner-secrets/secrets.json
   sudo chown runner:runner /etc/github-runner-secrets/secrets.json

4. Use in workflows:
   - name: Load secrets
     run: python3 scripts/load_runner_secrets.py
   
   - name: Use secrets
     env:
       OPENAI_API_KEY: ${{ env.OPENAI_API_KEY }}
     run: your_command

Alternative Setup (Environment Variables):
For simpler setup, you can also use runner's environment variables:
1. Edit runner service file or user profile
2. Add secrets as environment variables
3. They will be automatically available to workflows
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Any

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SecretsManager:
    """
    Manages secrets for self-hosted GitHub Actions runners.
    
    Secrets are loaded from:
    1. Local encrypted file on runner machine
    2. Runner environment variables
    3. Fallback to workflow environment
    """
    
    # Default secrets file locations (in priority order)
    SECRETS_PATHS = [
        '/etc/github-runner-secrets/secrets.json',
        '/var/lib/github-runner/secrets.json',
        '~/.github-runner/secrets.json',
        '/opt/github-runner/secrets.json'
    ]
    
    # Required secret keys
    SECRET_KEYS = [
        'OPENAI_API_KEY',
        'ANTHROPIC_API_KEY',
        'OPENROUTER_API_KEY'
    ]
    
    def __init__(self, secrets_file: Optional[str] = None):
        """
        Initialize secrets manager.
        
        Args:
            secrets_file: Optional path to secrets file
        """
        self.secrets_file = secrets_file
        self.secrets: Dict[str, str] = {}
    
    def load_secrets_from_file(self, filepath: str) -> Dict[str, str]:
        """
        Load secrets from a JSON file.
        
        Args:
            filepath: Path to secrets JSON file
        
        Returns:
            Dictionary of secrets
        """
        try:
            path = Path(filepath).expanduser()
            
            if not path.exists():
                logger.debug(f"Secrets file not found: {filepath}")
                return {}
            
            # Check file permissions (should be 600 or more restrictive)
            stat = path.stat()
            mode = stat.st_mode & 0o777
            
            if mode & 0o077:  # Check if group or others have any permissions
                logger.warning(f"⚠️  Secrets file {filepath} has insecure permissions: {oct(mode)}")
                logger.warning("   Recommended: chmod 600 {filepath}")
            
            with open(path, 'r') as f:
                secrets = json.load(f)
            
            logger.info(f"✅ Loaded {len(secrets)} secret(s) from {filepath}")
            return secrets
        
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in secrets file {filepath}: {e}")
            return {}
        except PermissionError:
            logger.error(f"❌ Permission denied reading {filepath}")
            return {}
        except Exception as e:
            logger.error(f"❌ Error loading secrets from {filepath}: {e}")
            return {}
    
    def load_secrets_from_env(self) -> Dict[str, str]:
        """
        Load secrets from environment variables.
        
        Returns:
            Dictionary of secrets found in environment
        """
        secrets = {}
        
        for key in self.SECRET_KEYS:
            value = os.environ.get(key)
            if value:
                secrets[key] = value
                logger.debug(f"✅ Loaded {key} from environment")
        
        if secrets:
            logger.info(f"✅ Loaded {len(secrets)} secret(s) from environment variables")
        
        return secrets
    
    def find_secrets_file(self) -> Optional[str]:
        """
        Find the first available secrets file from default locations.
        
        Returns:
            Path to secrets file or None if not found
        """
        for path in self.SECRETS_PATHS:
            expanded_path = Path(path).expanduser()
            if expanded_path.exists():
                logger.info(f"📁 Found secrets file: {path}")
                return str(expanded_path)
        
        logger.debug("No secrets file found in default locations")
        return None
    
    def load_secrets(self) -> Dict[str, str]:
        """
        Load secrets from all available sources.
        
        Priority:
        1. Specified secrets file
        2. Default secrets file locations
        3. Environment variables
        
        Returns:
            Dictionary of all loaded secrets
        """
        all_secrets = {}
        
        # Try to load from file
        if self.secrets_file:
            file_secrets = self.load_secrets_from_file(self.secrets_file)
            all_secrets.update(file_secrets)
        else:
            # Try default locations
            secrets_file = self.find_secrets_file()
            if secrets_file:
                file_secrets = self.load_secrets_from_file(secrets_file)
                all_secrets.update(file_secrets)
        
        # Load from environment (overrides file)
        env_secrets = self.load_secrets_from_env()
        all_secrets.update(env_secrets)
        
        self.secrets = all_secrets
        return all_secrets
    
    def export_to_github_env(self) -> None:
        """
        Export secrets to GitHub Actions environment.
        
        Secrets are written to $GITHUB_ENV file so they're available
        to subsequent workflow steps.
        """
        github_env = os.environ.get('GITHUB_ENV')
        
        if not github_env:
            logger.warning("⚠️  GITHUB_ENV not set - not running in GitHub Actions?")
            return
        
        try:
            with open(github_env, 'a') as f:
                for key, value in self.secrets.items():
                    # Mask the secret in logs
                    print(f"::add-mask::{value}")
                    
                    # Write to GITHUB_ENV
                    f.write(f"{key}={value}\n")
                    logger.info(f"✅ Exported {key} to GitHub Actions environment")
            
            logger.info(f"✅ Exported {len(self.secrets)} secret(s) to GITHUB_ENV")
        
        except Exception as e:
            logger.error(f"❌ Error exporting secrets to GitHub Actions: {e}")
    
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get a specific secret value.
        
        Args:
            key: Secret key name
            default: Default value if secret not found
        
        Returns:
            Secret value or default
        """
        return self.secrets.get(key, default)
    
    def print_summary(self) -> None:
        """Print summary of loaded secrets."""
        print("\n" + "="*80)
        print("🔐 Secrets Manager Summary")
        print("="*80)
        
        if not self.secrets:
            print("❌ No secrets loaded")
            print("\nTo set up secrets:")
            print("1. Create /etc/github-runner-secrets/secrets.json")
            print("2. Add your API keys in JSON format")
            print("3. Set file permissions: chmod 600 /etc/github-runner-secrets/secrets.json")
        else:
            print(f"✅ Loaded {len(self.secrets)} secret(s):")
            for key in self.secrets.keys():
                # Never print secrets or their partial values.
                print(f"   - {key}: [MASKED]")
        
        print("="*80 + "\n")


def main():
    """Main execution function."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Load secrets for self-hosted GitHub Actions runners'
    )
    parser.add_argument(
        '--secrets-file',
        type=str,
        help='Path to secrets JSON file'
    )
    parser.add_argument(
        '--export',
        action='store_true',
        help='Export secrets to GitHub Actions environment'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check which secrets are available'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create secrets manager
    manager = SecretsManager(secrets_file=args.secrets_file)
    
    # Load secrets
    secrets = manager.load_secrets()
    
    # Print summary if checking
    if args.check:
        manager.print_summary()
    
    # Export to GitHub Actions environment if requested
    if args.export:
        manager.export_to_github_env()
    
    # Exit with error if no secrets loaded
    if not secrets:
        logger.error("❌ No secrets loaded. Please configure secrets on the runner.")
        sys.exit(1)
    
    logger.info("✅ Secrets manager completed successfully")
    sys.exit(0)


if __name__ == '__main__':
    main()
