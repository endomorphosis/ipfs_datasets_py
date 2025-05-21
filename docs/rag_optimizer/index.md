# RAG Query Optimizer Documentation

This directory contains technical documentation for the RAG Query Optimizer component of IPFS Datasets Python.

## Contents

- [Learning Metrics Implementation](learning_metrics_implementation.md): Implementation details for the optimizer's learning metrics collection and visualization capabilities
- [Integration Plan](integration_plan.md): Plan for integrating the learning metrics collector with the core optimizer

## Overview

The RAG Query Optimizer is designed to improve retrieval performance for knowledge graph-enhanced retrievals (GraphRAG). Key features include:

1. **Statistical Learning**: Adapts query strategies based on historical performance
2. **Performance Metrics**: Collects and analyzes detailed performance metrics
3. **Visualization**: Provides visualizations for understanding optimizer behavior
4. **Alert Integration**: Detects anomalies and performance issues

## Architecture

The optimizer consists of several key components:

- **GraphRAGQueryOptimizer**: Core optimization logic
- **GraphRAGQueryStats**: Query statistics tracking
- **OptimizerLearningMetricsCollector**: Learning-specific metrics collection
- **QueryMetricsCollector**: General query metrics collection
- **QueryVisualizer**: Visualization capabilities for metrics

## Usage Examples

For usage examples, see:
- [graphrag_optimizer_example.py](/examples/graphrag_optimizer_example.py)
- [rag_query_optimizer_example.py](/examples/rag_query_optimizer_example.py)
- [Alert Visualization Integration](../examples/alert_visualization_integration.md)
