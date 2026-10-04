# OntologyGenerator Public API Doctest Reference

This reference provides copy-pasteable doctest-style examples for the stable public
`OntologyGenerator` API surface.

The examples are intentionally marked with `# doctest: +SKIP` where runtime setup is
non-trivial (e.g., async execution, context wiring, file fixtures).

## Common Setup

```python
>>> from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
...     Entity,
...     EntityExtractionResult,
...     OntologyGenerationContext,
...     OntologyGenerator,
... )
>>> generator = OntologyGenerator(use_ipfs_accelerate=False)
>>> context = OntologyGenerationContext(data_source="inline", data_type="text", domain="general")
```

## `extract_entities`

```python
>>> result = generator.extract_entities("Alice joined Acme Corp.", context)  # doctest: +SKIP
>>> isinstance(result, EntityExtractionResult)  # doctest: +SKIP
True
```

## `infer_relationships`

```python
>>> entities = [Entity(id="e1", type="Person", text="Alice"), Entity(id="e2", type="Organization", text="Acme")]  # doctest: +SKIP
>>> rels = generator.infer_relationships(entities, context, data="Alice works at Acme")  # doctest: +SKIP
>>> isinstance(rels, list)  # doctest: +SKIP
True
```

## `extract_entities_from_file`

```python
>>> file_result = generator.extract_entities_from_file("/tmp/sample.txt", context)  # doctest: +SKIP
>>> isinstance(file_result, EntityExtractionResult)  # doctest: +SKIP
True
```

## `batch_extract`

```python
>>> docs = ["Alice sued Bob.", "Acme hired Carol."]
>>> batch = generator.batch_extract(docs, context, max_workers=2)  # doctest: +SKIP
>>> len(batch) == len(docs)  # doctest: +SKIP
True
```

## `extract_entities_streaming`

```python
>>> stream = generator.extract_entities_streaming("Alice met Bob.", context)  # doctest: +SKIP
>>> first = next(stream)  # doctest: +SKIP
>>> isinstance(first, Entity)  # doctest: +SKIP
True
```

## `extract_entities_with_spans`

```python
>>> span_result = generator.extract_entities_with_spans("Alice met Bob.", context)  # doctest: +SKIP
>>> isinstance(span_result, EntityExtractionResult)  # doctest: +SKIP
True
```

## `extract_with_coref`

```python
>>> coref_result = generator.extract_with_coref("Alice filed a claim. She won.", context)  # doctest: +SKIP
>>> coref_result.metadata.get("coref_resolved")  # doctest: +SKIP
True
```

## `extract_with_context_windows`

```python
>>> long_text = "Alice joined Acme. " * 200
>>> windowed = generator.extract_with_context_windows(long_text, context, window_size=256, window_overlap=32)  # doctest: +SKIP
>>> "window_count" in windowed.metadata  # doctest: +SKIP
True
```

## `generate_ontology`

```python
>>> ontology = generator.generate_ontology("Alice joined Acme.", context)  # doctest: +SKIP
>>> sorted(k for k in ontology.keys() if k in {"entities", "relationships", "metadata", "domain"})  # doctest: +SKIP
['domain', 'entities', 'metadata', 'relationships']
```

## `__call__`

```python
>>> ontology = generator("Alice joined Acme.", context)  # doctest: +SKIP
>>> "entities" in ontology and "relationships" in ontology  # doctest: +SKIP
True
```

## `generate_ontology_rich`

```python
>>> rich = generator.generate_ontology_rich("Alice joined Acme.", context)  # doctest: +SKIP
>>> rich.entity_count >= 0 and rich.relationship_count >= 0  # doctest: +SKIP
True
```

## `generate_with_feedback`

```python
>>> fb = {"confidence_floor": 0.7}
>>> refined = generator.generate_with_feedback("Alice joined Acme.", context, feedback=fb)  # doctest: +SKIP
>>> refined["metadata"].get("feedback_applied") in (True, False)  # doctest: +SKIP
True
```

## `generate_synthetic_ontology`

```python
>>> synthetic = generator.generate_synthetic_ontology("legal", n_entities=3)
>>> len(synthetic["entities"]) == 3
True
```

## `batch_extract_with_spans`

```python
>>> docs = ["Alice met Bob.", "Carol joined Acme."]
>>> batch_spans = generator.batch_extract_with_spans(docs, context, max_workers=2)  # doctest: +SKIP
>>> len(batch_spans) == 2  # doctest: +SKIP
True
```

## `extract_keyphrases`

```python
>>> generator.extract_keyphrases("cat sat cat mat", top_k=2)
['cat', 'mat']
```

## `extract_noun_phrases`

```python
>>> phrases = generator.extract_noun_phrases("The quick brown fox jumped")
>>> isinstance(phrases, list)
True
```

## `merge_results`

```python
>>> r1 = EntityExtractionResult(entities=[Entity(id="e1", type="Person", text="Alice", confidence=0.8)], relationships=[], confidence=0.8)
>>> r2 = EntityExtractionResult(entities=[Entity(id="e2", type="Person", text="Bob", confidence=0.9)], relationships=[], confidence=0.9)
>>> merged = generator.merge_results([r1, r2])
>>> len(merged.entities)
2
```

## `deduplicate_entities`

```python
>>> dup = EntityExtractionResult(entities=[Entity(id="e1", type="Person", text="Alice", confidence=0.6), Entity(id="e2", type="Person", text="Alice", confidence=0.9)], relationships=[], confidence=0.8)
>>> deduped = generator.deduplicate_entities(dup)
>>> len(deduped.entities)
1
```

## `anonymize_entities`

```python
>>> anon = generator.anonymize_entities(r1)
>>> anon.entities[0].text
'[REDACTED]'
```

## `tag_entities`

```python
>>> tagged = generator.tag_entities(r1, {"source": "demo"})
>>> tagged.entities[0].properties["source"]
'demo'
```

## `score_entity`

```python
>>> score = generator.score_entity(Entity(id="e1", type="Person", text="Alice", confidence=0.9))
>>> 0.0 <= score <= 1.0
True
```

## `describe_result`

```python
>>> summary = generator.describe_result(r1)
>>> "entities" in summary and "confidence" in summary
True
```

## `result_summary_dict`

```python
>>> summary_dict = generator.result_summary_dict(r1)
>>> sorted(k for k in ["entity_count", "relationship_count", "mean_confidence"] if k in summary_dict)
['entity_count', 'mean_confidence', 'relationship_count']
```

## `extract_entities_async`

```python
>>> import asyncio
>>> async_result = asyncio.run(generator.extract_entities_async("Alice joined Acme.", context))  # doctest: +SKIP
>>> isinstance(async_result, EntityExtractionResult)  # doctest: +SKIP
True
```

## `extract_batch_async`

```python
>>> import asyncio
>>> async_batch = asyncio.run(generator.extract_batch_async(["Alice", "Bob"], context, max_concurrent=2))  # doctest: +SKIP
>>> len(async_batch) == 2  # doctest: +SKIP
True
```

## `infer_relationships_async`

```python
>>> import asyncio
>>> entities = [Entity(id="e1", type="Person", text="Alice"), Entity(id="e2", type="Person", text="Bob")]  # doctest: +SKIP
>>> async_rels = asyncio.run(generator.infer_relationships_async(entities, context))  # doctest: +SKIP
>>> isinstance(async_rels, list)  # doctest: +SKIP
True
```

## `extract_with_streaming_async`

```python
>>> import asyncio
>>> async def _consume():
...     chunks = []
...     async for chunk in generator.extract_with_streaming_async("Alice met Bob.", context, chunk_size=1):
...         chunks.append(chunk)
...     return chunks
>>> chunks = asyncio.run(_consume())  # doctest: +SKIP
>>> isinstance(chunks, list)  # doctest: +SKIP
True
```