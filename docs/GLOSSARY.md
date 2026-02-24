# Optimizers Glossary

Concise definitions for common terms used across GraphRAG, logic, and agentic
optimizers. Terms are intentionally short and implementation-aligned.

## Artifact
The object being optimized. In GraphRAG this is typically an ontology dict.

## Critic Score
A quality score produced by a critic. Usually normalized to the [0.0, 1.0]
range and paired with feedback.

## Domain
The subject area guiding extraction and evaluation, such as `legal` or
`medical`.

## Entity
A node in the ontology representing a person, organization, concept, or
artifact.

## Extraction
The process of turning input data into entities, relationships, and metadata.

## Feedback
Structured guidance produced by a critic to improve an artifact.

## Ontology
A structured representation of entities and relationships extracted from
input data.

## Optimizer
A component that iteratively improves an artifact based on critic feedback.

## Pipeline
The end-to-end workflow: extraction, evaluation, and optional refinement.

## Refinement
The step that modifies the ontology based on critic feedback.

## Relationship
An edge between two entities, often with a type and confidence.

## Session
A single optimization run that can include multiple iterations or rounds.

## Stage
A pipeline phase, such as `extracting`, `evaluating`, or `refining`.

## Validation
A correctness check that verifies structural or domain-specific constraints.
