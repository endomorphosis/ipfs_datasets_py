#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Patent Dashboard for IPFS Datasets.

This module provides a web interface for searching and building patent datasets
from the USPTO PatentsView API and integrating them with GraphRAG.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from flask import Flask, render_template, request, jsonify, Blueprint
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

logger = logging.getLogger(__name__)


def create_patent_dashboard_blueprint() -> Optional[Blueprint]:
    """
    Create a Flask blueprint for the patent dashboard.
    
    Returns:
        Flask Blueprint if Flask is available, None otherwise
    """
    if not FLASK_AVAILABLE:
        logger.warning("Flask not available, patent dashboard cannot be created")
        return None

    patent_bp = Blueprint('patents', __name__, url_prefix='/mcp/patents')
    
    @patent_bp.route('/')
    def patent_dashboard():
        """Render the patent dashboard page."""
        return render_template('admin/patent_dashboard.html')
    
    @patent_bp.route('/api/search', methods=['POST'])
    async def api_search_patents():
        """
        API endpoint for searching patents.
        
        Request body:
            {
                "keywords": ["keyword1", "keyword2"],
                "inventor_name": "LastName",
                "assignee_name": "Company",
                "patent_number": "US1234567",
                "date_from": "2020-01-01",
                "date_to": "2024-12-31",
                "cpc_classification": ["G06F", "H04L"],
                "limit": 100
            }
        
        Returns:
            JSON response with patents data
        """
        try:
            from ipfs_datasets_py.processors.patent_scraper import (
                USPTOPatentScraper,
                PatentSearchCriteria,
            )
            from dataclasses import asdict
            
            # Get request data
            data = request.get_json()
            
            # Build search criteria
            criteria = PatentSearchCriteria(
                keywords=data.get('keywords'),
                inventor_name=data.get('inventor_name'),
                assignee_name=data.get('assignee_name'),
                patent_number=data.get('patent_number'),
                date_from=data.get('date_from'),
                date_to=data.get('date_to'),
                cpc_classification=data.get('cpc_classification'),
                limit=data.get('limit', 100),
                offset=data.get('offset', 0)
            )
            
            # Search patents
            scraper = USPTOPatentScraper(rate_limit_delay=1.0)
            patents = await scraper.search_patents_async(criteria)
            
            # Convert to dict
            patents_data = [asdict(patent) for patent in patents]
            
            return jsonify({
                "status": "success",
                "patents": patents_data,
                "count": len(patents_data),
                "query": asdict(criteria)
            })
        except Exception as e:
            logger.error(f"Patent search API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e),
                "patents": [],
                "count": 0
            }), 500
    
    @patent_bp.route('/api/build_dataset', methods=['POST'])
    async def api_build_dataset():
        """
        API endpoint for building patent datasets.
        
        Request body:
            {
                "search_criteria": {...},
                "output_format": "json",
                "dataset_name": "patent_dataset_2024",
                "include_citations": true,
                "include_classifications": true,
                "graphrag_format": true
            }
        
        Returns:
            JSON response with dataset metadata
        """
        try:
            from ipfs_datasets_py.processors.patent_scraper import (
                USPTOPatentScraper,
                PatentSearchCriteria,
                PatentDatasetBuilder,
            )
            
            # Get request data
            data = request.get_json()
            
            # Build search criteria from stored search or new criteria
            search_params = data.get('search_criteria', {})
            criteria = PatentSearchCriteria(
                keywords=search_params.get('keywords'),
                inventor_name=search_params.get('inventor_name'),
                assignee_name=search_params.get('assignee_name'),
                patent_number=search_params.get('patent_number'),
                date_from=search_params.get('date_from'),
                date_to=search_params.get('date_to'),
                cpc_classification=search_params.get('cpc_classification'),
                limit=search_params.get('limit', 100),
                offset=search_params.get('offset', 0)
            )
            
            # Initialize scraper and builder
            scraper = USPTOPatentScraper(rate_limit_delay=1.0)
            builder = PatentDatasetBuilder(scraper)
            
            # Build output path
            dataset_name = data.get('dataset_name', 'patent_dataset')
            output_format = data.get('output_format', 'json')
            output_path = Path(f"/tmp/{dataset_name}.{output_format}")
            
            # Build dataset
            result = await builder.build_dataset_async(
                criteria=criteria,
                output_format=output_format,
                output_path=output_path
            )
            
            # Add GraphRAG metadata if requested
            if data.get('graphrag_format', True):
                result['graphrag_metadata'] = {
                    "entity_types": ["Patent", "Inventor", "Assignee", "Classification"],
                    "relationship_types": ["INVENTED_BY", "ASSIGNED_TO", "CLASSIFIED_AS", "CITES"],
                    "ready_for_ingestion": True,
                    "suggested_embeddings": ["patent_title", "patent_abstract"]
                }
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Dataset building API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e),
                "metadata": {}
            }), 500
    
    @patent_bp.route('/api/graphrag/ingest', methods=['POST'])
    async def api_graphrag_ingest():
        """
        API endpoint for ingesting patent datasets into GraphRAG.
        
        Request body:
            {
                "dataset_path": "/path/to/dataset.json",
                "graph_name": "patent_graph"
            }
        
        Returns:
            JSON response with ingestion status
        """
        try:
            # Get request data
            data = request.get_json()
            dataset_path = data.get('dataset_path')
            graph_name = data.get('graph_name', 'patent_graph')
            
            # TODO: Implement actual GraphRAG ingestion
            # For now, return a placeholder response
            
            return jsonify({
                "status": "success",
                "message": "Patent dataset queued for GraphRAG ingestion",
                "graph_name": graph_name,
                "dataset_path": dataset_path,
                "note": "GraphRAG ingestion integration is in development"
            })
            
        except Exception as e:
            logger.error(f"GraphRAG ingestion API error: {e}", exc_info=True)
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500
    
    return patent_bp


def register_patent_routes(app: Flask) -> None:
    """
    Register patent dashboard routes with a Flask app.
    
    Args:
        app: Flask application instance
    """
    if not FLASK_AVAILABLE:
        logger.warning("Flask not available, cannot register patent routes")
        return
    
    patent_bp = create_patent_dashboard_blueprint()
    if patent_bp:
        app.register_blueprint(patent_bp)
        logger.info("Patent dashboard routes registered")
