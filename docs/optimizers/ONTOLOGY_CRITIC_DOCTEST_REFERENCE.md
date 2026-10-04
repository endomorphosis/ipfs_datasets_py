# OntologyCritic Doctest Reference

This reference provides executable-style examples for stable public `OntologyCritic` APIs.

## `evaluate_ontology`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
>>> from types import SimpleNamespace
>>> critic = OntologyCritic(use_llm=False)
>>> ontology = {"entities": [{"id": "e1", "type": "Person", "text": "Alice"}], "relationships": []}
>>> context = SimpleNamespace(domain="general")
>>> score = critic.evaluate_ontology(ontology, context, source_data="Alice text")
>>> 0.0 <= score.overall <= 1.0
True
```

## `evaluate`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
>>> from types import SimpleNamespace
>>> critic = OntologyCritic(use_llm=False)
>>> result = critic.evaluate({"entities": [], "relationships": []}, SimpleNamespace(domain="general"))
>>> hasattr(result, "score") and hasattr(result, "dimensions")
True
```

## `evaluate_batch`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
>>> from types import SimpleNamespace
>>> critic = OntologyCritic(use_llm=False)
>>> ontologies = [{"entities": [], "relationships": []}, {"entities": [], "relationships": []}]
>>> out = critic.evaluate_batch(ontologies, SimpleNamespace(domain="general"))
>>> "scores" in out and len(out["scores"]) == 2
True
```

## `evaluate_batch_parallel`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
>>> from types import SimpleNamespace
>>> critic = OntologyCritic(use_llm=False)
>>> ontologies = [{"entities": [], "relationships": []}]
>>> out = critic.evaluate_batch_parallel(ontologies, SimpleNamespace(domain="general"), max_workers=1)
>>> "scores" in out and len(out["scores"]) == 1
True
```

## `explain_score`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
>>> critic = OntologyCritic(use_llm=False)
>>> score = CriticScore(0.7,0.8,0.6,0.5,0.7,0.75)
>>> expl = critic.explain_score(score)
>>> "completeness" in expl and "consistency" in expl
True
```

## `weighted_overall`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
>>> critic = OntologyCritic(use_llm=False)
>>> score = CriticScore(0.6,0.6,0.6,0.6,0.6,0.6)
>>> round(critic.weighted_overall(score, {"completeness": 1.0}), 2) >= 0.0
True
```

## `evaluate_with_rubric`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
>>> from types import SimpleNamespace
>>> critic = OntologyCritic(use_llm=False)
>>> ontology = {"entities": [], "relationships": []}
>>> rubric = {"completeness": 0.3, "consistency": 0.2, "clarity": 0.1, "granularity": 0.1, "relationship_coherence": 0.15, "domain_alignment": 0.15}
>>> score = critic.evaluate_with_rubric(ontology, SimpleNamespace(domain="general"), rubric)
>>> 0.0 <= score.overall <= 1.0
True
```

## `compare_ontologies`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
>>> from types import SimpleNamespace
>>> critic = OntologyCritic(use_llm=False)
>>> o1 = {"entities": [{"id": "e1", "type": "Person", "text": "Alice"}], "relationships": []}
>>> o2 = {"entities": [], "relationships": []}
>>> comparison = critic.compare_ontologies(o1, o2, SimpleNamespace(domain="general"))
>>> "better_ontology" in comparison
True
```

## `compare_versions`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
>>> from types import SimpleNamespace
>>> critic = OntologyCritic(use_llm=False)
>>> versions = [{"entities": [], "relationships": []}, {"entities": [{"id": "e1", "type": "X"}], "relationships": []}]
>>> report = critic.compare_versions(versions, SimpleNamespace(domain="general"))
>>> "scores" in report and len(report["scores"]) == 2
True
```

## `calibrate_thresholds`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
>>> critic = OntologyCritic(use_llm=False)
>>> history = [CriticScore(0.4,0.4,0.4,0.4,0.4,0.4), CriticScore(0.8,0.8,0.8,0.8,0.8,0.8)]
>>> thresholds = critic.calibrate_thresholds(history)
>>> "completeness" in thresholds and 0.0 <= thresholds["completeness"] <= 1.0
True
```

## `score_trend`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
>>> critic = OntologyCritic(use_llm=False)
>>> trend = critic.score_trend([CriticScore(0.4,0.4,0.4,0.4,0.4,0.4), CriticScore(0.6,0.6,0.6,0.6,0.6,0.6)])
>>> trend in {"improving", "stable", "degrading", "insufficient_data"}
True
```

## `emit_dimension_histogram`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
>>> critic = OntologyCritic(use_llm=False)
>>> hist = critic.emit_dimension_histogram([CriticScore(0.5,0.6,0.7,0.6,0.5,0.4)])
>>> "completeness" in hist and isinstance(hist["completeness"], list)
True
```

## `compare_with_baseline`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
>>> from types import SimpleNamespace
>>> critic = OntologyCritic(use_llm=False)
>>> ontology = {"entities": [], "relationships": []}
>>> baseline = {"entities": [{"id":"e1","type":"X"}], "relationships": []}
>>> delta = critic.compare_with_baseline(ontology, baseline, SimpleNamespace(domain="general"))
>>> "delta_overall" in delta
True
```

## `summarize_batch_results`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
>>> critic = OntologyCritic(use_llm=False)
>>> summary = critic.summarize_batch_results({"scores": []})
>>> isinstance(summary, list)
True
```

## `compare_batch`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
>>> from types import SimpleNamespace
>>> critic = OntologyCritic(use_llm=False)
>>> ranked = critic.compare_batch([{"entities": [], "relationships": []}], SimpleNamespace(domain="general"))
>>> isinstance(ranked, list)
True
```

## `critical_weaknesses`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
>>> critic = OntologyCritic(use_llm=False)
>>> score = CriticScore(0.3,0.8,0.2,0.7,0.9,0.6, weaknesses=["low clarity", "coverage gap"])
>>> out = critic.critical_weaknesses(score)
>>> isinstance(out, list)
True
```

## `top_dimension` / `bottom_dimension`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
>>> critic = OntologyCritic(use_llm=False)
>>> score = CriticScore(0.2,0.9,0.6,0.7,0.8,0.4)
>>> critic.top_dimension(score) in {"completeness","consistency","clarity","granularity","relationship_coherence","domain_alignment"}
True
>>> critic.bottom_dimension(score) in {"completeness","consistency","clarity","granularity","relationship_coherence","domain_alignment"}
True
```

## `score_range`

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
>>> critic = OntologyCritic(use_llm=False)
>>> lo, hi = critic.score_range([CriticScore(0.1,0.1,0.1,0.1,0.1,0.1), CriticScore(0.9,0.9,0.9,0.9,0.9,0.9)])
>>> lo <= hi
True
```
