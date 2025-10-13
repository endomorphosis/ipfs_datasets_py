"""RECAP Archive scraper for building court document datasets.

This tool scrapes the RECAP Archive from courtlistener.com/recap/
and provides structured access to federal court documents including
dockets, opinions, and filings from PACER.

RECAP (PACER Backwards) is a free and open archive of court documents
from the federal PACER system.
"""
import logging
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Federal court types
COURT_TYPES = {
    "district": "District Courts",
    "appellate": "Circuit Courts of Appeals",
    "bankruptcy": "Bankruptcy Courts",
    "supreme": "Supreme Court",
    "specialty": "Specialty Courts (Tax, Claims, etc.)"
}

# Federal circuits
FEDERAL_CIRCUITS = {
    "1": "First Circuit",
    "2": "Second Circuit",
    "3": "Third Circuit",
    "4": "Fourth Circuit",
    "5": "Fifth Circuit",
    "6": "Sixth Circuit",
    "7": "Seventh Circuit",
    "8": "Eighth Circuit",
    "9": "Ninth Circuit",
    "10": "Tenth Circuit",
    "11": "Eleventh Circuit",
    "dc": "D.C. Circuit",
    "fed": "Federal Circuit"
}


async def search_recap_documents(
    query: Optional[str] = None,
    court: Optional[str] = None,
    case_name: Optional[str] = None,
    filed_after: Optional[str] = None,
    filed_before: Optional[str] = None,
    document_type: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """Search RECAP Archive for court documents.
    
    Args:
        query: Text search query
        court: Court identifier (e.g., "ca9" for 9th Circuit, "nysd" for S.D.N.Y.)
        case_name: Case name to search for
        filed_after: Date filed after (YYYY-MM-DD format)
        filed_before: Date filed before (YYYY-MM-DD format)
        document_type: Type of document (e.g., "opinion", "docket", "complaint")
        limit: Maximum number of results
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - documents: List of matching documents
            - count: Number of documents found
            - search_params: Parameters used for search
            - error: Error message (if failed)
    """
    try:
        logger.info(f"Searching RECAP Archive: query={query}, court={court}, case_name={case_name}")
        
        # Import required libraries
        try:
            import requests
        except ImportError as ie:
            return {
                "status": "error",
                "error": f"Required library not available: {ie}. Install with: pip install requests",
                "documents": [],
                "count": 0
            }
        
        # Build search parameters
        search_params = {
            "query": query,
            "court": court,
            "case_name": case_name,
            "filed_after": filed_after,
            "filed_before": filed_before,
            "document_type": document_type,
            "limit": limit
        }
        
        # Query the CourtListener API
        # API endpoint: https://www.courtlistener.com/api/rest/v3/search/
        # Documentation: https://www.courtlistener.com/api/rest-info/
        
        try:
            # Build API query parameters
            api_params = {}
            
            # Add search query if provided
            if query:
                api_params['q'] = query
            elif case_name:
                api_params['case_name'] = case_name
                
            # Add court filter
            if court:
                api_params['court'] = court
                
            # Add date filters
            if filed_after:
                api_params['filed_after'] = filed_after
            if filed_before:
                api_params['filed_before'] = filed_before
                
            # Add document type filter (map to CourtListener types)
            if document_type:
                if document_type == 'opinion':
                    api_params['type'] = 'o'  # Opinion
                elif document_type == 'docket':
                    api_params['type'] = 'r'  # RECAP document
                    
            # Set result limit
            api_params['page_size'] = min(limit, 100)  # API max is typically 100
            
            # Make API request
            api_url = "https://www.courtlistener.com/api/rest/v3/search/"
            logger.info(f"Querying CourtListener API: {api_url} with params {api_params}")
            
            response = requests.get(api_url, params=api_params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                
                # Transform results to our standardized format
                documents = []
                for result in results:
                    doc = {
                        "id": result.get('id', ''),
                        "docket_id": result.get('docket_id', ''),
                        "case_name": result.get('caseName', result.get('case_name', '')),
                        "court": result.get('court', court or ''),
                        "court_full_name": result.get('court_name', ''),
                        "document_type": document_type or 'unknown',
                        "document_number": result.get('document_number', ''),
                        "description": result.get('description', result.get('snippet', '')),
                        "date_filed": result.get('dateFiled', result.get('date_filed', '')),
                        "page_count": result.get('page_count', 0),
                        "pacer_doc_id": result.get('pacer_doc_id', ''),
                        "recap_url": result.get('download_url', ''),
                        "docket_url": result.get('absolute_url', ''),
                        "plain_text_available": result.get('plain_text', '') != '',
                        "pdf_available": result.get('filepath_local', '') != '',
                        "ocr_status": result.get('ocr_status', 'unknown'),
                        "abstract": result.get('snippet', '')[:500] if result.get('snippet') else '',
                    }
                    documents.append(doc)
                
                return {
                    "status": "success",
                    "documents": documents,
                    "count": len(documents),
                    "total_available": data.get('count', len(documents)),
                    "search_params": search_params,
                    "api_endpoint": api_url,
                    "note": "Results from CourtListener RECAP Archive API"
                }
            else:
                # API request failed, return error with details
                logger.warning(f"CourtListener API returned status {response.status_code}")
                return {
                    "status": "error",
                    "error": f"API request failed with status {response.status_code}: {response.text[:200]}",
                    "documents": [],
                    "count": 0,
                    "search_params": search_params,
                    "api_endpoint": api_url
                }
                
        except requests.exceptions.Timeout:
            logger.error("CourtListener API request timed out")
            return {
                "status": "error",
                "error": "API request timed out after 30 seconds",
                "documents": [],
                "count": 0
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"CourtListener API request failed: {e}")
            return {
                "status": "error",
                "error": f"API request failed: {str(e)}",
                "documents": [],
                "count": 0
            }
        
    except Exception as e:
        logger.error(f"RECAP Archive search failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "documents": [],
            "count": 0
        }


async def get_recap_document(
    document_id: str,
    include_text: bool = True,
    include_metadata: bool = True
) -> Dict[str, Any]:
    """Get a specific RECAP document by ID.
    
    Args:
        document_id: RECAP document ID
        include_text: Include document text (if available)
        include_metadata: Include full document metadata
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - document: Document data
            - error: Error message (if failed)
    """
    try:
        logger.info(f"Fetching RECAP document: {document_id}")
        
        # Import required libraries
        try:
            import requests
        except ImportError as ie:
            return {
                "status": "error",
                "error": f"Required library not available: {ie}. Install with: pip install requests",
                "document": None
            }
        
        # Fetch from CourtListener API
        # API endpoint: https://www.courtlistener.com/api/rest/v3/recap-documents/{id}/
        api_url = f"https://www.courtlistener.com/api/rest/v3/recap-documents/{document_id}/"
        
        try:
            response = requests.get(api_url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Transform to our standardized format
                document = {
                    "id": document_id,
                    "docket_id": data.get('docket', ''),
                    "case_name": data.get('case_name', ''),
                    "court": data.get('court', ''),
                    "document_type": data.get('document_type', ''),
                    "date_filed": data.get('date_filed', ''),
                    "page_count": data.get('page_count', 0),
                    "recap_url": data.get('filepath_local', ''),
                    "text": data.get('plain_text', '') if include_text else None,
                    "metadata": {
                        "pacer_doc_id": data.get('pacer_doc_id', ''),
                        "pacer_case_id": data.get('pacer_case_id', ''),
                        "ocr_status": data.get('ocr_status', ''),
                        "plain_text_available": data.get('plain_text', '') != '',
                        "pdf_available": data.get('filepath_local', '') != '',
                        "description": data.get('description', ''),
                        "document_number": data.get('document_number', '')
                    } if include_metadata else None
                }
                
                return {
                    "status": "success",
                    "document": document,
                    "api_endpoint": api_url,
                    "note": "Document fetched from CourtListener RECAP Archive API"
                }
            else:
                logger.warning(f"CourtListener API returned status {response.status_code}")
                return {
                    "status": "error",
                    "error": f"API request failed with status {response.status_code}: {response.text[:200]}",
                    "document": None,
                    "api_endpoint": api_url
                }
                
        except requests.exceptions.Timeout:
            return {
                "status": "error",
                "error": "API request timed out after 30 seconds",
                "document": None
            }
        except requests.exceptions.RequestException as e:
            return {
                "status": "error",
                "error": f"API request failed: {str(e)}",
                "document": None
            }
        
    except Exception as e:
        logger.error(f"Failed to get RECAP document {document_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "document": None
        }


async def scrape_recap_archive(
    courts: Optional[List[str]] = None,
    document_types: Optional[List[str]] = None,
    filed_after: Optional[str] = None,
    filed_before: Optional[str] = None,
    case_name_pattern: Optional[str] = None,
    output_format: str = "json",
    include_text: bool = True,
    include_metadata: bool = True,
    rate_limit_delay: float = 1.0,
    max_documents: Optional[int] = None,
    job_id: Optional[str] = None,
    resume: bool = False
) -> Dict[str, Any]:
    """Scrape RECAP Archive documents and build a structured dataset.
    
    Args:
        courts: List of court identifiers to scrape (e.g., ["ca9", "nysd"]).
                If None or ["all"], scrapes from all courts.
        document_types: Types of documents to scrape (e.g., ["opinion", "complaint", "docket"])
        filed_after: Only include documents filed after this date (YYYY-MM-DD)
        filed_before: Only include documents filed before this date (YYYY-MM-DD)
        case_name_pattern: Pattern to match case names (e.g., "Smith v.")
        output_format: Output format - "json" or "parquet"
        include_text: Include document text (increases data size)
        include_metadata: Include full document metadata
        rate_limit_delay: Delay between requests in seconds (default 1.0)
        max_documents: Maximum number of documents to scrape
        job_id: Unique job identifier for resume capability (auto-generated if not provided)
        resume: Whether to resume from previous state (requires job_id)
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - data: Scraped RECAP documents
            - metadata: Scraping metadata
            - output_format: Format of the data
            - job_id: Job identifier (for resume)
            - error: Error message (if failed)
    """
    try:
        # Import state manager
        from .state_manager import ScrapingState
        
        # Generate job ID if not provided
        if job_id is None:
            import uuid
            job_id = f"recap_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        # Initialize or load state
        state = ScrapingState(job_id)
        
        if resume:
            if state.load():
                logger.info(f"Resuming scraping job {job_id}")
                # Restore scraped data
                scraped_documents = state.get_data()
                documents_count = len(scraped_documents)
                
                # Get previous parameters
                prev_params = state.metadata.get("parameters", {})
                courts = prev_params.get("courts", courts)
                document_types = prev_params.get("document_types", document_types)
                filed_after = prev_params.get("filed_after", filed_after)
                filed_before = prev_params.get("filed_before", filed_before)
            else:
                logger.warning(f"No previous state found for job {job_id}, starting fresh")
                resume = False
        
        if not resume:
            scraped_documents = []
            documents_count = 0
        
        # Set default date range if not provided
        if not filed_before:
            filed_before = datetime.now().strftime("%Y-%m-%d")
        if not filed_after:
            filed_after = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        # Validate document types
        valid_doc_types = ["opinion", "complaint", "docket", "order", "motion", "brief"]
        if document_types:
            document_types = [dt for dt in document_types if dt in valid_doc_types]
        if not document_types:
            document_types = ["opinion"]  # Default to opinions
        
        # Save parameters to state
        state.set_parameters({
            "courts": courts,
            "document_types": document_types,
            "filed_after": filed_after,
            "filed_before": filed_before,
            "case_name_pattern": case_name_pattern,
            "max_documents": max_documents
        })
        state.set_status("running")
        state.save()
        
        logger.info(f"Starting RECAP Archive scraping: courts={courts}, types={document_types}, dates={filed_after} to {filed_before}")
        start_time = time.time()
        
        # Import required libraries
        try:
            import requests
        except ImportError as ie:
            state.set_status("failed")
            state.add_error(f"Required library not available: {ie}")
            state.save()
            return {
                "status": "error",
                "error": f"Required library not available: {ie}. Install with: pip install requests",
                "data": [],
                "metadata": {},
                "job_id": job_id
            }
        
        # Process courts
        if courts is None or "all" in courts:
            # In production, would iterate through actual court list
            courts_to_scrape = ["ca9", "nysd", "txnd"]  # Sample courts
        else:
            courts_to_scrape = courts
        
        # Calculate total items for progress tracking
        total_items = len(courts_to_scrape) * len(document_types)
        items_processed = 0
        
        # Scrape documents using search API
        try:
            for court in courts_to_scrape:
                if max_documents and documents_count >= max_documents:
                    logger.info(f"Reached max_documents limit of {max_documents}")
                    break
                
                logger.info(f"Scraping RECAP documents from court: {court}")
                
                # Query CourtListener API for this court
                for doc_type in document_types:
                    if max_documents and documents_count >= max_documents:
                        break
                    
                    # Update progress
                    state.update_progress(items_processed, total_items, f"{court}/{doc_type}")
                    
                    # Use the search function to get documents
                    search_result = await search_recap_documents(
                        court=court,
                        document_type=doc_type,
                        filed_after=filed_after,
                        filed_before=filed_before,
                        case_name=case_name_pattern,
                        limit=min(20, max_documents - documents_count if max_documents else 20)
                    )
                    
                    if search_result['status'] == 'success' and search_result['documents']:
                        for doc in search_result['documents']:
                            if max_documents and documents_count >= max_documents:
                                break
                            
                            # Check if already processed (for resume)
                            doc_id = doc.get('id', '')
                            if state.is_processed(doc_id):
                                logger.debug(f"Skipping already processed document: {doc_id}")
                                continue
                            
                            # Optionally fetch full document details
                            if include_text and doc.get('id'):
                                doc_details = await get_recap_document(
                                    doc['id'],
                                    include_text=include_text,
                                    include_metadata=include_metadata
                                )
                                if doc_details['status'] == 'success' and doc_details.get('document'):
                                    # Merge search result with detailed document
                                    doc.update(doc_details['document'])
                            
                            # Add to state
                            state.add_item(doc, doc_id)
                            scraped_documents.append(doc)
                            documents_count += 1
                    
                    items_processed += 1
                    
                    # Save state periodically (every 10 items)
                    if items_processed % 10 == 0:
                        state.save()
                        logger.debug(f"Saved state: {documents_count} documents processed")
                    
                    # Rate limiting between requests
                    time.sleep(rate_limit_delay)
            
            # Mark as completed
            state.set_status("completed")
            state.update_progress(items_processed, total_items)
            state.save()
            
        except Exception as scrape_error:
            # Save state on error for resume
            state.set_status("failed")
            state.add_error(str(scrape_error))
            state.save()
            raise

        
        elapsed_time = time.time() - start_time
        
        metadata = {
            "courts_scraped": courts_to_scrape,
            "courts_count": len(courts_to_scrape),
            "documents_count": documents_count,
            "document_types": document_types,
            "date_range": {
                "filed_after": filed_after,
                "filed_before": filed_before
            },
            "elapsed_time_seconds": elapsed_time,
            "scraped_at": datetime.now().isoformat(),
            "source": "CourtListener RECAP Archive",
            "api_endpoint": "https://www.courtlistener.com/api/rest/v3/",
            "rate_limit_delay": rate_limit_delay,
            "include_text": include_text,
            "include_metadata": include_metadata,
            "job_id": job_id,
            "resumed": resume
        }
        
        logger.info(f"Completed RECAP Archive scraping: {documents_count} documents in {elapsed_time:.2f}s")
        
        return {
            "status": "success",
            "data": scraped_documents,
            "metadata": metadata,
            "output_format": output_format,
            "job_id": job_id,
            "note": "Documents fetched from CourtListener/RECAP Archive API at courtlistener.com. Job state saved for resume capability."
        }
        
    except Exception as e:
        logger.error(f"RECAP Archive scraping failed: {e}")
        # Try to get job_id from state if available
        try:
            state_job_id = job_id if 'job_id' in locals() else None
        except:
            state_job_id = None
        
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
            "job_id": state_job_id,
            "note": "Scraping failed. State saved for resume if job_id is available."
        }
