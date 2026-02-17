#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Example: Using CLI Tools as Data Sources

This example demonstrates how to use the GitHub CLI, Gemini CLI, and Claude CLI
as data sources in the IPFS Datasets Python library.

The CLI tools can be used to:
1. Fetch data from GitHub (issues, pull requests, repository info)
2. Generate text/analysis using Gemini
3. Generate text/analysis using Claude

All of this data can then be processed, embedded, and stored in IPFS.
"""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ipfs_datasets_py.utils.github_cli import GitHubCLI
from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
from ipfs_datasets_py.utils.claude_cli import ClaudeCLI


def example_github_as_data_source():
    """
    Example: Use GitHub CLI to fetch repository data as a data source.
    """
    print("=" * 60)
    print("Example: GitHub CLI as Data Source")
    print("=" * 60)
    
    cli = GitHubCLI()
    
    # Check if installed
    if not cli.is_installed():
        print("GitHub CLI not installed. Installing...")
        success = cli.download_and_install()
        if not success:
            print("Failed to install GitHub CLI")
            return
    
    # Example: Get repository information as data
    print("\nFetching repository list as data...")
    try:
        result = cli.execute(['repo', 'list', '--limit', '5', '--json', 'name,description,url'])
        if result.returncode == 0:
            repos_data = json.loads(result.stdout)
            print(f"Fetched {len(repos_data)} repositories as data:")
            for repo in repos_data:
                print(f"  - {repo.get('name')}: {repo.get('description', 'No description')}")
            
            # This data can now be:
            # - Stored in IPFS
            # - Used for embedding generation
            # - Processed by AI models
            # - Used in RAG systems
            return repos_data
        else:
            print("Note: Authentication required to fetch repository data")
            print("Run: ipfs-datasets github auth login")
    except Exception as e:
        print(f"Error: {e}")
        print("Note: This requires GitHub authentication")
    
    return None


def example_gemini_as_data_source():
    """
    Example: Use Gemini CLI to generate text data.
    """
    print("\n" + "=" * 60)
    print("Example: Gemini CLI as Data Source")
    print("=" * 60)
    
    cli = GeminiCLI()
    
    # Check if installed
    if not cli.is_installed():
        print("Gemini CLI not installed. Installing...")
        success = cli.install()
        if not success:
            print("Failed to install Gemini CLI")
            return
    
    # Check if API key is configured
    if not cli.get_api_key():
        print("\nGemini API key not configured.")
        print("To use Gemini as a data source:")
        print("1. Get an API key from: https://makersuite.google.com/app/apikey")
        print("2. Configure it: ipfs-datasets gemini config set-api-key YOUR_API_KEY")
        print("\nExample of what you could generate:")
        print("  - Summaries of documents")
        print("  - Answers to questions")
        print("  - Analysis of data")
        print("  - Generated content")
        return None
    
    # Example: Generate text as data
    print("\nGenerating text data with Gemini...")
    try:
        result = cli.execute(['chat', 'What are the key benefits of IPFS?'])
        if result.returncode == 0:
            generated_text = result.stdout.strip()
            print(f"Generated text:\n{generated_text}\n")
            
            # This generated text can now be:
            # - Stored in IPFS
            # - Used for creating embeddings
            # - Added to a vector database
            # - Used as training data
            return {
                'source': 'gemini',
                'prompt': 'What are the key benefits of IPFS?',
                'response': generated_text
            }
        else:
            print(f"Failed to generate text: {result.stderr}")
    except Exception as e:
        print(f"Error: {e}")
    
    return None


def example_claude_as_data_source():
    """
    Example: Use Claude CLI to generate text data.
    """
    print("\n" + "=" * 60)
    print("Example: Claude CLI as Data Source")
    print("=" * 60)
    
    cli = ClaudeCLI()
    
    # Check if installed
    if not cli.is_installed():
        print("Claude CLI not installed. Installing...")
        success = cli.install()
        if not success:
            print("Failed to install Claude CLI")
            return
    
    # Check if API key is configured
    if not cli.get_api_key():
        print("\nClaude API key not configured.")
        print("To use Claude as a data source:")
        print("1. Get an API key from: https://console.anthropic.com/")
        print("2. Configure it: ipfs-datasets claude config set-api-key YOUR_API_KEY")
        print("\nExample of what you could generate:")
        print("  - Detailed analysis of code")
        print("  - Summaries of technical documents")
        print("  - Structured data extraction")
        print("  - Question answering")
        return None
    
    # Example: Generate text as data
    print("\nGenerating text data with Claude...")
    try:
        result = cli.execute(['chat', 'Explain how distributed hash tables work in IPFS'])
        if result.returncode == 0:
            generated_text = result.stdout.strip()
            print(f"Generated text:\n{generated_text}\n")
            
            # This generated text can now be:
            # - Stored in IPFS
            # - Used for creating embeddings
            # - Added to a RAG system
            # - Used as documentation
            return {
                'source': 'claude',
                'prompt': 'Explain how distributed hash tables work in IPFS',
                'response': generated_text
            }
        else:
            print(f"Failed to generate text: {result.stderr}")
    except Exception as e:
        print(f"Error: {e}")
    
    return None


def example_combined_workflow():
    """
    Example: Combined workflow using all CLI tools as data sources.
    """
    print("\n" + "=" * 60)
    print("Example: Combined Workflow - CLI Tools as Data Sources")
    print("=" * 60)
    
    print("\nThis example demonstrates a workflow where:")
    print("1. GitHub CLI fetches repository data")
    print("2. Gemini/Claude analyze the data")
    print("3. Results are stored and can be indexed in IPFS")
    
    # Step 1: Fetch data from GitHub
    print("\n[Step 1] Fetching repository data from GitHub...")
    github_data = example_github_as_data_source()
    
    if github_data:
        # Step 2: Use Gemini to analyze the data
        print("\n[Step 2] Using Gemini to analyze repository data...")
        gemini_analysis = example_gemini_as_data_source()
        
        # Step 3: Use Claude for additional insights
        print("\n[Step 3] Using Claude for additional insights...")
        claude_analysis = example_claude_as_data_source()
        
        # Combine all data
        combined_data = {
            'github_repositories': github_data,
            'gemini_analysis': gemini_analysis,
            'claude_analysis': claude_analysis,
            'timestamp': '2024-01-01T00:00:00Z'
        }
        
        print("\n[Result] Combined data ready for IPFS storage:")
        print(json.dumps(combined_data, indent=2))
        
        # This combined data can now be:
        # - Stored in IPFS
        # - Indexed in a vector database
        # - Used for RAG queries
        # - Shared via IPFS hash
        
        return combined_data
    
    return None


if __name__ == '__main__':
    print("CLI Tools as Data Sources - Examples\n")
    
    # Run individual examples
    github_data = example_github_as_data_source()
    gemini_data = example_gemini_as_data_source()
    claude_data = example_claude_as_data_source()
    
    # Show combined workflow
    print("\n" + "=" * 60)
    print("Next Steps:")
    print("=" * 60)
    print("\n1. Install the CLI tools:")
    print("   ipfs-datasets github install")
    print("   ipfs-datasets gemini install")
    print("   ipfs-datasets claude install")
    print("\n2. Configure authentication:")
    print("   ipfs-datasets github auth login")
    print("   ipfs-datasets gemini config set-api-key YOUR_KEY")
    print("   ipfs-datasets claude config set-api-key YOUR_KEY")
    print("\n3. Use them as data sources in your code:")
    print("   from ipfs_datasets_py.utils.github_cli import GitHubCLI")
    print("   from ipfs_datasets_py.utils.gemini_cli import GeminiCLI")
    print("   from ipfs_datasets_py.utils.claude_cli import ClaudeCLI")
    print("\n4. Process and store the data:")
    print("   - Create embeddings from generated text")
    print("   - Store in IPFS")
    print("   - Index in vector database")
    print("   - Use in RAG systems")
