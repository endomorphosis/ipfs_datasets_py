# AI-Powered Dataset Builder Documentation

## Overview

The AI-Powered Dataset Builder provides a complete demonstration of how scraped medical research data can be processed, analyzed, and augmented using AI models from the `ipfs_accelerate_py` library.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Scraping Layer                            │
│   PubMed Scraper | Clinical Trials Scraper | Biomolecule   │
└───────────────────────────┬─────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│              AI Dataset Builder Pipeline                     │
│                                                              │
│   Step 1: Build Dataset (AI Filtering)                     │
│   ├─ Quality assessment using AI models                     │
│   ├─ Relevance scoring                                      │
│   ├─ Keyword-based filtering                               │
│   └─ Metrics: completeness, quality, diversity             │
│                                                              │
│   Step 2: Analyze Dataset (AI Insights)                    │
│   ├─ Pattern identification                                 │
│   ├─ Theme extraction                                       │
│   ├─ Research gap identification                           │
│   └─ Trend analysis                                        │
│                                                              │
│   Step 3: Transform Dataset (AI Operations)                │
│   ├─ Summarization                                         │
│   ├─ Entity extraction (conditions, treatments, outcomes)  │
│   ├─ Format normalization                                  │
│   └─ Data extrapolation                                    │
│                                                              │
│   Step 4: Generate Synthetic Data (AI Variations)          │
│   ├─ Template-based generation                            │
│   ├─ Configurable creativity (temperature)                │
│   ├─ Variation sampling                                    │
│   └─ Privacy-preserving datasets                          │
└───────────────────────────┬─────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│           Evaluation & Testing Layer                        │
│   Test pipelines | Validate models | Benchmark systems     │
└─────────────────────────────────────────────────────────────┘
```

## Integration with ipfs_accelerate_py

### Supported Models

The system integrates with HuggingFace models via `ipfs_accelerate_py`:

- **meta-llama/Llama-2-7b-hf** (default) - Fast, good quality
- **meta-llama/Llama-2-13b-hf** - Better quality, slower
- **mistralai/Mistral-7B-v0.1** - Alternative architecture
- **Mock mode** - Fallback when ipfs_accelerate_py unavailable

### Code Example

```python
from ipfs_accelerate_py import HuggingFaceModel, ModelConfig

# Initialize model
config = ModelConfig(
    model_name="meta-llama/Llama-2-7b-hf",
    device="auto",
    torch_dtype="auto"
)
model = HuggingFaceModel(config)

# Generate text
result = model.generate(
    prompt="Analyze this medical research...",
    max_length=500,
    temperature=0.7
)
```

### Graceful Fallback

```python
try:
    from ipfs_accelerate_py import HuggingFaceModel
    ACCELERATE_AVAILABLE = True
except ImportError:
    ACCELERATE_AVAILABLE = False
    # Use mock implementations
```

## Complete Workflow Examples

### Example 1: COVID-19 Vaccine Research Pipeline

```python
from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers import (
    scrape_pubmed_medical_research,
    build_dataset_from_scraped_data,
    analyze_dataset_with_ai,
    transform_dataset_with_ai,
    generate_synthetic_dataset
)

# Step 1: Scrape COVID-19 vaccine research
articles = scrape_pubmed_medical_research(
    query="COVID-19 vaccine efficacy",
    max_results=200
)

# Step 2: Build filtered dataset with AI
dataset = build_dataset_from_scraped_data(
    scraped_data=articles['articles'],
    filter_criteria={
        'keywords': ['efficacy', 'safety', 'phase 3'],
        'min_quality': 0.7
    },
    model_name='meta-llama/Llama-2-7b-hf'
)

print(f"Dataset quality score: {dataset['metrics']['quality_score']}")
print(f"Filtered from {dataset['original_count']} to {dataset['filtered_count']} records")

# Step 3: Analyze patterns with AI
analysis = analyze_dataset_with_ai(
    dataset=dataset['dataset'],
    model_name='meta-llama/Llama-2-7b-hf'
)

print("AI Insights:")
print(analysis['insights']['ai_analysis'])

# Step 4: Generate summaries
summaries = transform_dataset_with_ai(
    dataset=dataset['dataset'],
    transformation_type='summarize',
    model_name='meta-llama/Llama-2-7b-hf'
)

print(f"Generated {summaries['count']} summaries")

# Step 5: Extract medical entities
entities = transform_dataset_with_ai(
    dataset=dataset['dataset'],
    transformation_type='extract_entities',
    model_name='meta-llama/Llama-2-7b-hf'
)

print("Extracted conditions, treatments, and outcomes")

# Step 6: Generate synthetic data for testing
synthetic = generate_synthetic_dataset(
    template_data=dataset['dataset'][:5],
    num_samples=30,
    model_name='meta-llama/Llama-2-7b-hf',
    temperature=0.8  # Higher temperature = more creative
)

print(f"Generated {synthetic['count']} synthetic samples for testing")
```

### Example 2: Clinical Trials Analysis

```python
from ipfs_datasets_py.mcp_server.tools.medical_research_scrapers import (
    scrape_clinical_trials,
    build_dataset_from_scraped_data,
    analyze_dataset_with_ai
)

# Scrape diabetes trials
trials = scrape_clinical_trials(
    condition="diabetes",
    intervention="metformin",
    max_results=100
)

# Build structured dataset
dataset = build_dataset_from_scraped_data(
    scraped_data=trials['trials'],
    filter_criteria={'keywords': ['HbA1c', 'glycemic control']}
)

# Analyze trial outcomes
analysis = analyze_dataset_with_ai(dataset['dataset'])

print(f"Total trials analyzed: {analysis['total_records']}")
print(f"Relevance score: {analysis['metrics']['relevance_score']}")
```

### Example 3: Synthetic Data Generation for Testing

```python
# Create synthetic variations of trial data for pipeline testing
synthetic_trials = generate_synthetic_dataset(
    template_data=trials['trials'][:10],
    num_samples=50,
    temperature=0.7,
    model_name='meta-llama/Llama-2-13b-hf'  # Use larger model
)

# Use synthetic data to test analysis pipeline
test_results = []
for sample in synthetic_trials['synthetic_data']:
    # Run through analysis pipeline
    result = analyze_sample(sample)
    test_results.append(result)

# Validate pipeline performance
accuracy = calculate_accuracy(test_results)
print(f"Pipeline accuracy: {accuracy}%")
```

## Dashboard Usage

### Step-by-Step Guide

**Step 1: Scrape Data**
1. Navigate to "PubMed Research" or "Clinical Trials" tab
2. Enter query (e.g., "cancer immunotherapy")
3. Click "Scrape"
4. Copy the JSON results

**Step 2: Build Dataset**
1. Navigate to "AI Dataset Builder" tab
2. Paste scraped data into "Source Data" field
3. Optional: Add filter keywords (e.g., "efficacy, toxicity")
4. Select AI model (Llama-2-7b recommended)
5. Click "Build Dataset"
6. View quality metrics dashboard

**Step 3: Analyze Dataset**
1. Dataset auto-loaded from Step 2 (or paste manually)
2. Select AI model
3. Click "Analyze Dataset"
4. View AI-generated insights and patterns

**Step 4: Transform Dataset**
1. Select transformation type:
   - Summarize: Generate article summaries
   - Extract Entities: Extract medical terms
   - Normalize: Standardize format
   - Extrapolate: Generate predictions
2. Click "Transform Dataset"
3. View transformed output

**Step 5: Generate Synthetic Data**
1. Paste template data (can use built dataset)
2. Set number of samples (1-50)
3. Adjust temperature (0.0-1.0)
   - Lower (0.3): More conservative, factual
   - Higher (0.9): More creative, diverse
4. Click "Generate Synthetic Data"
5. View generated samples

## API Reference

### Build Dataset

**Endpoint:** `POST /api/mcp/medicine/dataset/build`

**Request:**
```json
{
  "scraped_data": [...],  // Array of scraped articles/trials
  "filter_criteria": {
    "keywords": ["efficacy", "safety"],
    "min_quality": 0.7
  },
  "model_name": "meta-llama/Llama-2-7b-hf"
}
```

**Response:**
```json
{
  "success": true,
  "dataset": [...],
  "metrics": {
    "total_records": 150,
    "unique_records": 145,
    "completeness_score": 0.876,
    "quality_score": 0.812,
    "relevance_score": 0.794,
    "diversity_score": 0.967
  },
  "original_count": 200,
  "filtered_count": 150
}
```

### Analyze Dataset

**Endpoint:** `POST /api/mcp/medicine/dataset/analyze`

**Request:**
```json
{
  "dataset": [...],
  "model_name": "meta-llama/Llama-2-7b-hf"
}
```

**Response:**
```json
{
  "success": true,
  "metrics": {...},
  "insights": {
    "ai_analysis": "The dataset shows strong focus on...",
    "model_used": "meta-llama/Llama-2-7b-hf"
  }
}
```

### Transform Dataset

**Endpoint:** `POST /api/mcp/medicine/dataset/transform`

**Request:**
```json
{
  "dataset": [...],
  "transformation_type": "summarize",  // or extract_entities, normalize
  "parameters": {},
  "model_name": "meta-llama/Llama-2-7b-hf"
}
```

**Response:**
```json
{
  "success": true,
  "summaries": [
    {
      "original_id": "PMID12345",
      "summary": "This study investigated..."
    }
  ],
  "count": 10
}
```

### Generate Synthetic Data

**Endpoint:** `POST /api/mcp/medicine/dataset/generate_synthetic`

**Request:**
```json
{
  "template_data": [...],
  "num_samples": 20,
  "temperature": 0.8,
  "model_name": "meta-llama/Llama-2-7b-hf"
}
```

**Response:**
```json
{
  "success": true,
  "synthetic_data": [
    {
      "id": "synthetic_1",
      "content": "Generated article text...",
      "template_id": "PMID12345",
      "generated_at": "2025-10-29T05:00:00Z"
    }
  ],
  "count": 20
}
```

## Quality Metrics

### Completeness Score
Percentage of records with all required fields (title, abstract, date).

**Calculation:**
```
completeness = complete_records / total_records
```

**Interpretation:**
- >90%: Excellent - Most records have complete information
- 70-90%: Good - Acceptable level of completeness
- <70%: Poor - Many records missing key information

### Quality Score
AI-assessed quality based on content, structure, and relevance.

**Factors:**
- Completeness of information
- Scientific rigor indicators
- Source credibility
- Citation presence

**Range:** 0.0 (poor) to 1.0 (excellent)

### Relevance Score
How well the dataset matches intended research topics.

**Factors:**
- Keyword presence in abstracts
- Topic alignment
- Research type match
- Temporal relevance

**Range:** 0.0 (irrelevant) to 1.0 (highly relevant)

### Diversity Score
Uniqueness and variety within the dataset.

**Calculation:**
```
diversity = unique_records / total_records
```

**Interpretation:**
- >95%: Excellent - High diversity, minimal duplication
- 80-95%: Good - Acceptable diversity
- <80%: Poor - Too much duplication

## Use Cases

### 1. Research Pipeline Validation
Generate synthetic medical data to test your analysis pipeline without privacy concerns.

### 2. Model Training Augmentation
Augment small datasets with synthetic variations for better model training.

### 3. Quality Assessment
Evaluate scraped data quality before committing to large-scale processing.

### 4. Pattern Discovery
Use AI to identify hidden patterns and research trends in medical literature.

### 5. Entity Extraction
Automatically extract medical entities for knowledge graph construction.

### 6. Literature Summarization
Generate concise summaries of large volumes of medical research.

## Performance Considerations

### Model Selection

**Llama-2-7b (Default)**
- Speed: Fast (~2-5 sec per operation)
- Quality: Good for most tasks
- Memory: ~14 GB VRAM
- Use for: Real-time analysis, quick iterations

**Llama-2-13b**
- Speed: Moderate (~5-10 sec per operation)
- Quality: Better for complex analysis
- Memory: ~26 GB VRAM
- Use for: High-quality summaries, detailed analysis

**Mistral-7B**
- Speed: Fast (~2-4 sec per operation)
- Quality: Comparable to Llama-2-7b
- Memory: ~14 GB VRAM
- Use for: Alternative architecture, varied outputs

**Mock Mode**
- Speed: Instant
- Quality: Basic keyword matching
- Memory: Minimal
- Use for: Testing without GPU, development

### Batch Processing

For large datasets, process in batches:

```python
batch_size = 50
for i in range(0, len(dataset), batch_size):
    batch = dataset[i:i+batch_size]
    result = transform_dataset_with_ai(batch, 'summarize')
    save_batch_results(result)
```

### Caching

Cache AI model outputs to avoid redundant processing:

```python
cache = {}

def cached_analyze(dataset, model_name):
    cache_key = hash(str(dataset) + model_name)
    if cache_key in cache:
        return cache[cache_key]
    
    result = analyze_dataset_with_ai(dataset, model_name)
    cache[cache_key] = result
    return result
```

## Troubleshooting

### ipfs_accelerate_py Not Found

**Symptom:** "Mock data - ipfs_accelerate_py not available"

**Solution:**
```bash
pip install git+https://github.com/endomorphosis/ipfs_accelerate_py.git@main
```

### Out of Memory

**Symptom:** CUDA out of memory error

**Solutions:**
1. Use smaller model (Llama-2-7b instead of 13b)
2. Reduce batch size
3. Process dataset in chunks
4. Use CPU mode: `device="cpu"`

### Slow Performance

**Solutions:**
1. Use GPU acceleration
2. Reduce dataset size
3. Use Llama-2-7b instead of larger models
4. Cache results for repeated operations

### Low Quality Results

**Solutions:**
1. Use Llama-2-13b for better quality
2. Adjust temperature (lower = more focused)
3. Improve filter criteria with better keywords
4. Provide more context in prompts

## Future Enhancements

### Planned Features

1. **Multi-Model Ensemble** - Combine outputs from multiple AI models
2. **Active Learning** - Iteratively improve dataset quality with human feedback
3. **Cross-Language Support** - Process non-English medical literature
4. **Real-Time Updates** - Stream new research as it becomes available
5. **Advanced Visualization** - Interactive graphs and charts for insights
6. **Collaborative Filtering** - Share and discover high-quality datasets
7. **Automated Validation** - Cross-reference with known medical databases
8. **Export Formats** - Support for multiple output formats (CSV, Parquet, etc.)

## Contributing

To add new transformation types:

1. Add method to `AIDatasetBuilder` class
2. Update `transform_dataset()` dispatcher
3. Add API route in `mcp_dashboard.py`
4. Add UI controls in dashboard template
5. Document in this file

## License

See repository LICENSE file.

## Support

For issues or questions:
- GitHub Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
- Documentation: This file and inline code comments
