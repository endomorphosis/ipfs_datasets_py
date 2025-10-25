# Web Search API Integrations - Usage Guide

This guide demonstrates how to use the new web search API integrations for dataset creation.

## Overview

The `ipfs_datasets_py` package now includes comprehensive search API integrations for:

- **Brave Search API** - Web, news, and image search
- **Google Custom Search API** - Web and image search
- **GitHub API** - Repository, code, user, and issue search
- **HuggingFace Hub API** - Model, dataset, and space search

All integrations are located in `ipfs_datasets_py.mcp_server.tools.web_archive_tools`.

## Setup

### Install Dependencies

```bash
pip install aiohttp pydantic
```

### API Keys

Set up your API keys as environment variables:

```bash
# Brave Search (get key from https://brave.com/search/api/)
export BRAVE_API_KEY="your_brave_api_key"

# Google Custom Search (get key from https://console.cloud.google.com/)
export GOOGLE_API_KEY="your_google_api_key"
export GOOGLE_CSE_ID="your_custom_search_engine_id"

# GitHub (optional, reduces rate limits)
export GITHUB_TOKEN="your_github_token"

# HuggingFace (optional for public data)
export HF_TOKEN="your_huggingface_token"
```

Alternatively, pass API keys directly to functions:

```python
result = await search_brave(query="test", api_key="your_api_key")
```

## Usage Examples

### Brave Search API

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import (
    search_brave, search_brave_news, search_brave_images, batch_search_brave
)

async def brave_search_example():
    # Basic web search
    result = await search_brave(
        query="machine learning datasets",
        count=10,
        safesearch="moderate"
    )
    
    if result['status'] == 'success':
        for item in result['results']:
            print(f"Title: {item['title']}")
            print(f"URL: {item['url']}")
            print(f"Description: {item['description']}")
            print()
    
    # News search
    news_result = await search_brave_news(
        query="artificial intelligence",
        count=5,
        freshness="pw"  # past week
    )
    
    # Image search
    image_result = await search_brave_images(
        query="neural networks diagram",
        count=10
    )
    
    # Batch search multiple queries
    batch_result = await batch_search_brave(
        queries=["deep learning", "computer vision", "NLP"],
        count=5,
        delay_seconds=1.0
    )
    
    print(f"Batch results: {batch_result['success_count']} successful")

asyncio.run(brave_search_example())
```

### Google Custom Search API

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.google_search import (
    search_google, search_google_images, batch_search_google
)

async def google_search_example():
    # Basic web search
    result = await search_google(
        query="python data science libraries",
        num=10,
        safe="medium"
    )
    
    if result['status'] == 'success':
        print(f"Total results: {result['total_results']}")
        for item in result['results']:
            print(f"Title: {item['title']}")
            print(f"URL: {item['url']}")
            print(f"Snippet: {item['snippet']}")
            print()
    
    # Search with filters
    pdf_result = await search_google(
        query="machine learning research",
        file_type="pdf",
        num=5
    )
    
    # Image search
    image_result = await search_google_images(
        query="data visualization examples",
        num=10,
        img_size="large"
    )
    
    # Batch search
    batch_result = await batch_search_google(
        queries=["pandas dataframe", "numpy arrays", "scikit-learn"],
        num=5
    )

asyncio.run(google_search_example())
```

### GitHub API Search

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.github_search import (
    search_github_repositories,
    search_github_code,
    search_github_users,
    search_github_issues,
    batch_search_github
)

async def github_search_example():
    # Search repositories
    repo_result = await search_github_repositories(
        query="language:python stars:>1000 topic:machine-learning",
        sort="stars",
        order="desc",
        per_page=10
    )
    
    if repo_result['status'] == 'success':
        for repo in repo_result['results']:
            print(f"Repository: {repo['full_name']}")
            print(f"Stars: {repo['stars']}, Forks: {repo['forks']}")
            print(f"Description: {repo['description']}")
            print(f"URL: {repo['url']}")
            print()
    
    # Search code
    code_result = await search_github_code(
        query="import tensorflow language:python",
        per_page=5
    )
    
    # Search users
    user_result = await search_github_users(
        query="location:\"San Francisco\" followers:>100",
        per_page=10
    )
    
    # Search issues/PRs
    issue_result = await search_github_issues(
        query="is:issue is:open label:bug repo:pytorch/pytorch",
        per_page=10
    )
    
    # Batch search different types
    batch_result = await batch_search_github(
        queries=[
            "language:python stars:>5000",
            "language:javascript stars:>10000"
        ],
        search_type="repositories",
        per_page=5
    )

asyncio.run(github_search_example())
```

### HuggingFace Hub API Search

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.huggingface_search import (
    search_huggingface_models,
    search_huggingface_datasets,
    search_huggingface_spaces,
    get_huggingface_model_info,
    batch_search_huggingface
)

async def huggingface_search_example():
    # Search models
    model_result = await search_huggingface_models(
        query="bert",
        filter_task="text-classification",
        filter_library="transformers",
        sort="downloads",
        limit=10
    )
    
    if model_result['status'] == 'success':
        for model in model_result['results']:
            print(f"Model: {model['model_id']}")
            print(f"Author: {model['author']}")
            print(f"Downloads: {model['downloads']}")
            print(f"Tags: {', '.join(model['tags'])}")
            print(f"URL: {model['model_url']}")
            print()
    
    # Search datasets
    dataset_result = await search_huggingface_datasets(
        query="sentiment",
        filter_task="text-classification",
        filter_language="en",
        sort="downloads",
        limit=10
    )
    
    # Search spaces (demo applications)
    space_result = await search_huggingface_spaces(
        query="image generation",
        filter_sdk="gradio",
        limit=5
    )
    
    # Get detailed model information
    model_info = await get_huggingface_model_info(
        model_id="bert-base-uncased"
    )
    
    if model_info['status'] == 'success':
        info = model_info['model_info']
        print(f"Model: {info['id']}")
        print(f"Pipeline: {info['pipeline_tag']}")
        print(f"Library: {info['library_name']}")
        print(f"Downloads: {info['downloads']}")
    
    # Batch search
    batch_result = await batch_search_huggingface(
        queries=["gpt", "bert", "t5"],
        search_type="models",
        limit=5
    )

asyncio.run(huggingface_search_example())
```

## Creating Datasets from Search Results

Here's an example of creating a dataset from search results:

```python
import asyncio
import json
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.github_search import (
    search_github_repositories
)

async def create_ml_repos_dataset():
    """Create a dataset of popular ML repositories."""
    
    # Search for ML repositories
    result = await search_github_repositories(
        query="machine-learning stars:>5000 language:python",
        sort="stars",
        order="desc",
        per_page=100
    )
    
    if result['status'] != 'success':
        print(f"Error: {result['error']}")
        return
    
    # Extract relevant data
    dataset = []
    for repo in result['results']:
        dataset.append({
            'name': repo['name'],
            'full_name': repo['full_name'],
            'owner': repo['owner'],
            'description': repo['description'],
            'url': repo['url'],
            'clone_url': repo['clone_url'],
            'stars': repo['stars'],
            'forks': repo['forks'],
            'language': repo['language'],
            'topics': repo['topics'],
            'created_at': repo['created_at'],
            'updated_at': repo['updated_at'],
            'license': repo['license']
        })
    
    # Save to JSON
    with open('ml_repositories_dataset.json', 'w') as f:
        json.dump(dataset, f, indent=2)
    
    print(f"Created dataset with {len(dataset)} repositories")
    print(f"Saved to ml_repositories_dataset.json")

asyncio.run(create_ml_repos_dataset())
```

## Rate Limiting

All batch search functions include rate limiting:

```python
# Brave Search - 1 second delay between requests
batch_result = await batch_search_brave(
    queries=["query1", "query2", "query3"],
    delay_seconds=1.0
)

# Google Search - 0.5 second delay
batch_result = await batch_search_google(
    queries=["query1", "query2", "query3"],
    delay_seconds=0.5
)

# GitHub Search - 2 second delay (recommended to avoid rate limits)
batch_result = await batch_search_github(
    queries=["query1", "query2"],
    delay_seconds=2.0
)
```

## Error Handling

All functions return a consistent response format:

```python
{
    "status": "success",  # or "error"
    "results": [...],      # search results (if successful)
    "error": "...",        # error message (if failed)
    # ... additional metadata
}
```

Example error handling:

```python
result = await search_brave(query="test")

if result['status'] == 'error':
    if 'API key' in result['error']:
        print("Please set BRAVE_API_KEY environment variable")
    elif 'rate limit' in result['error'].lower():
        print("Rate limit exceeded, please wait")
    else:
        print(f"Error: {result['error']}")
else:
    # Process results
    for item in result['results']:
        print(item['title'])
```

## Advanced Usage

### Combining Multiple Search Sources

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
    brave_search, github_search, huggingface_search
)

async def multi_source_search(query):
    """Search across multiple platforms."""
    
    # Run searches in parallel
    web_task = brave_search.search_brave(query)
    github_task = github_search.search_github_repositories(query)
    hf_task = huggingface_search.search_huggingface_models(query)
    
    web_result, github_result, hf_result = await asyncio.gather(
        web_task, github_task, hf_task
    )
    
    return {
        'web': web_result,
        'github': github_result,
        'huggingface': hf_result
    }

# Example usage
results = asyncio.run(multi_source_search("transformer models"))
```

## API Documentation Links

- **Brave Search API**: https://brave.com/search/api/
- **Google Custom Search API**: https://developers.google.com/custom-search/v1/overview
- **GitHub API**: https://docs.github.com/en/rest/search
- **HuggingFace Hub API**: https://huggingface.co/docs/hub/api

## Troubleshooting

### Common Issues

1. **Missing API Key**: Set environment variables or pass as parameters
2. **Rate Limiting**: Use batch functions with appropriate delays
3. **Authentication Errors**: Verify API key is valid
4. **Import Errors**: Ensure `aiohttp` is installed

### Getting Help

For issues or questions:
- Check the API documentation links above
- Review the test files in `tests/test_search_integrations_standalone.py`
- Open an issue on the repository

## License

These integrations are part of the `ipfs_datasets_py` package and follow the same license.
