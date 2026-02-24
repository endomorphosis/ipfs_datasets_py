"""AutoScraper engine — canonical domain module.

Core domain logic for intelligent web scraping using AutoScraper. Imported by:
  ipfs_datasets_py.mcp_server.tools.web_archive_tools.autoscraper_integration

Usage::

    from ipfs_datasets_py.web_archiving.autoscraper_engine import (
        create_autoscraper_model, scrape_with_autoscraper,
        optimize_autoscraper_model, batch_scrape_with_autoscraper,
        list_autoscraper_models,
    )
"""
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import json
import os
import tempfile

logger = logging.getLogger(__name__)

async def create_autoscraper_model(
    sample_url: str,
    wanted_data: List[Union[str, Dict[str, str]]],
    model_name: str,
    wanted_dict: Optional[Dict[str, List[str]]] = None
) -> Dict[str, Any]:
    """Create an AutoScraper model from sample data.

    Args:
        sample_url: URL to use as training sample
        wanted_data: List of data items to extract
        model_name: Name for the saved model
        wanted_dict: Dictionary mapping field names to example values

    Returns:
        Dict containing:
            - status: "success" or "error"
            - model_path: Path to saved model
            - learned_rules: Number of rules learned
            - error: Error message (if failed)
    """
    try:
        try:
            from autoscraper import AutoScraper
        except ImportError:
            return {
                "status": "error",
                "error": "autoscraper not installed. Install with: pip install autoscraper"
            }

        # Initialize AutoScraper
        scraper = AutoScraper()

        try:
            if wanted_dict:
                # Use build method with dictionary
                result = scraper.build(sample_url, wanted_dict)
            else:
                # Use build method with list
                result = scraper.build(sample_url, wanted_data)

            if not result:
                return {
                    "status": "error",
                    "error": "Failed to learn scraping rules from the provided sample"
                }

            # Save the model
            model_dir = "/tmp/autoscraper_models"
            os.makedirs(model_dir, exist_ok=True)
            model_path = os.path.join(model_dir, f"{model_name}.pkl")
            
            scraper.save(model_path)

            # Count learned rules (approximate)
            learned_rules = len(scraper.stack_list) if hasattr(scraper, 'stack_list') else 0

            return {
                "status": "success",
                "model_path": model_path,
                "model_name": model_name,
                "learned_rules": learned_rules,
                "sample_url": sample_url,
                "training_result": result,
                "created_at": datetime.now().isoformat()
            }

        except Exception as scraper_error:
            logger.error(f"AutoScraper training failed: {scraper_error}")
            return {
                "status": "error",
                "error": f"Failed to train AutoScraper model: {scraper_error}"
            }

    except Exception as e:
        logger.error(f"Failed to create AutoScraper model: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def scrape_with_autoscraper(
    model_path: str,
    target_urls: List[str],
    grouped: bool = False
) -> Dict[str, Any]:
    """Scrape data using a trained AutoScraper model.

    Args:
        model_path: Path to the saved AutoScraper model
        target_urls: List of URLs to scrape
        grouped: Whether to return results grouped by rule

    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: Scraped data for each URL
            - urls_processed: Number of URLs processed
            - error: Error message (if failed)
    """
    try:
        try:
            from autoscraper import AutoScraper
        except ImportError:
            return {
                "status": "error",
                "error": "autoscraper not installed. Install with: pip install autoscraper"
            }

        if not os.path.exists(model_path):
            return {
                "status": "error",
                "error": f"AutoScraper model not found: {model_path}"
            }

        # Load the trained model
        scraper = AutoScraper()
        scraper.load(model_path)

        results = {}
        successful_scrapes = 0
        failed_scrapes = 0

        for url in target_urls:
            try:
                if grouped:
                    scraped_data = scraper.get_result_exact(url, grouped=True)
                else:
                    scraped_data = scraper.get_result_similar(url, grouped=False)

                results[url] = {
                    "status": "success",
                    "data": scraped_data,
                    "scraped_at": datetime.now().isoformat()
                }
                successful_scrapes += 1

            except Exception as scrape_error:
                logger.error(f"Failed to scrape {url}: {scrape_error}")
                results[url] = {
                    "status": "error",
                    "error": str(scrape_error),
                    "scraped_at": datetime.now().isoformat()
                }
                failed_scrapes += 1

        return {
            "status": "success",
            "results": results,
            "urls_processed": len(target_urls),
            "successful_scrapes": successful_scrapes,
            "failed_scrapes": failed_scrapes,
            "model_used": model_path,
            "grouped": grouped
        }

    except Exception as e:
        logger.error(f"Failed to scrape with AutoScraper: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def optimize_autoscraper_model(
    model_path: str,
    new_sample_urls: List[str],
    new_wanted_data: Optional[List[Union[str, Dict[str, str]]]] = None,
    update_existing: bool = True
) -> Dict[str, Any]:
    """Optimize an existing AutoScraper model with new training data.

    Args:
        model_path: Path to the existing model
        new_sample_urls: Additional URLs for training
        new_wanted_data: Additional data examples
        update_existing: Whether to update the existing model or create new one

    Returns:
        Dict containing:
            - status: "success" or "error"
            - model_path: Path to the optimized model
            - optimization_results: Results from optimization
            - error: Error message (if failed)
    """
    try:
        try:
            from autoscraper import AutoScraper
        except ImportError:
            return {
                "status": "error",
                "error": "autoscraper not installed. Install with: pip install autoscraper"
            }

        if not os.path.exists(model_path):
            return {
                "status": "error",
                "error": f"AutoScraper model not found: {model_path}"
            }

        # Load existing model
        scraper = AutoScraper()
        scraper.load(model_path)

        optimization_results = []

        # Add training data from new URLs
        for sample_url in new_sample_urls:
            try:
                if new_wanted_data:
                    result = scraper.build(sample_url, new_wanted_data)
                else:
                    # Use existing model to extract data and add as training
                    existing_result = scraper.get_result_similar(sample_url)
                    if existing_result:
                        result = scraper.build(sample_url, existing_result)
                    else:
                        result = None

                optimization_results.append({
                    "url": sample_url,
                    "status": "success" if result else "no_data",
                    "training_result": result
                })

            except Exception as train_error:
                logger.error(f"Failed to train on {sample_url}: {train_error}")
                optimization_results.append({
                    "url": sample_url,
                    "status": "error",
                    "error": str(train_error)
                })

        # Save the optimized model
        if update_existing:
            scraper.save(model_path)
            final_model_path = model_path
        else:
            # Create new model with timestamp
            base_path, ext = os.path.splitext(model_path)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            final_model_path = f"{base_path}_optimized_{timestamp}{ext}"
            scraper.save(final_model_path)

        return {
            "status": "success",
            "model_path": final_model_path,
            "optimization_results": optimization_results,
            "training_urls_count": len(new_sample_urls),
            "optimized_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Failed to optimize AutoScraper model: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def batch_scrape_with_autoscraper(
    model_path: str,
    urls_file: str,
    output_format: str = "json",
    batch_size: int = 50,
    delay_seconds: float = 1.0
) -> Dict[str, Any]:
    """Perform batch scraping using AutoScraper model.

    Args:
        model_path: Path to the trained model
        urls_file: File containing URLs to scrape (one per line)
        output_format: Output format ("json", "csv", "jsonl")
        batch_size: Number of URLs to process per batch
        delay_seconds: Delay between requests

    Returns:
        Dict containing:
            - status: "success" or "error"
            - output_file: Path to results file
            - total_urls: Total URLs processed
            - success_count: Number of successful scrapes
            - error: Error message (if failed)
    """
    try:
        try:
            from autoscraper import AutoScraper
            import time
        except ImportError:
            return {
                "status": "error",
                "error": "autoscraper not installed. Install with: pip install autoscraper"
            }

        if not os.path.exists(model_path):
            return {
                "status": "error",
                "error": f"AutoScraper model not found: {model_path}"
            }

        if not os.path.exists(urls_file):
            return {
                "status": "error",
                "error": f"URLs file not found: {urls_file}"
            }

        # Load model
        scraper = AutoScraper()
        scraper.load(model_path)

        # Read URLs
        with open(urls_file, 'r') as f:
            urls = [line.strip() for line in f if line.strip()]

        if not urls:
            return {
                "status": "error",
                "error": "No URLs found in file"
            }

        # Prepare output file
        output_dir = "/tmp/autoscraper_results"
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(output_dir, f"scrape_results_{timestamp}.{output_format}")

        results = []
        success_count = 0
        error_count = 0

        # Process URLs in batches
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]
            
            for url in batch:
                try:
                    scraped_data = scraper.get_result_similar(url)
                    
                    result = {
                        "url": url,
                        "status": "success",
                        "data": scraped_data,
                        "scraped_at": datetime.now().isoformat()
                    }
                    results.append(result)
                    success_count += 1

                except Exception as scrape_error:
                    result = {
                        "url": url,
                        "status": "error",
                        "error": str(scrape_error),
                        "scraped_at": datetime.now().isoformat()
                    }
                    results.append(result)
                    error_count += 1

                # Add delay between requests
                time.sleep(delay_seconds)

        # Save results
        if output_format == "json":
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
        elif output_format == "jsonl":
            with open(output_file, 'w') as f:
                for result in results:
                    f.write(json.dumps(result) + '\n')
        elif output_format == "csv":
            # Simple CSV implementation - would need pandas for better CSV support
            with open(output_file, 'w') as f:
                f.write("url,status,data,scraped_at,error\n")
                for result in results:
                    data_str = json.dumps(result.get('data', '')).replace('"', '""')
                    error_str = result.get('error', '').replace('"', '""')
                    f.write(f'"{result["url"]}","{result["status"]}","{data_str}","{result["scraped_at"]}","{error_str}"\n')

        return {
            "status": "success",
            "output_file": output_file,
            "total_urls": len(urls),
            "success_count": success_count,
            "error_count": error_count,
            "batch_size": batch_size,
            "output_format": output_format,
            "model_used": model_path
        }

    except Exception as e:
        logger.error(f"Failed batch scraping with AutoScraper: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def list_autoscraper_models() -> Dict[str, Any]:
    """List available AutoScraper models.

    Returns:
        Dict containing:
            - status: "success" or "error"
            - models: List of available models with metadata
            - count: Number of models found
            - error: Error message (if failed)
    """
    try:
        model_dir = "/tmp/autoscraper_models"
        
        if not os.path.exists(model_dir):
            os.makedirs(model_dir, exist_ok=True)
            return {
                "status": "success",
                "models": [],
                "count": 0
            }

        models = []
        for filename in os.listdir(model_dir):
            if filename.endswith('.pkl'):
                model_path = os.path.join(model_dir, filename)
                stat = os.stat(model_path)
                
                models.append({
                    "name": filename[:-4],  # Remove .pkl extension
                    "path": model_path,
                    "size": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })

        return {
            "status": "success",
            "models": models,
            "count": len(models),
            "model_directory": model_dir
        }

    except Exception as e:
        logger.error(f"Failed to list AutoScraper models: {e}")
        return {
            "status": "error",
            "error": str(e)
        }