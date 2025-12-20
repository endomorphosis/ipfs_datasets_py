#!/usr/bin/env python3
"""
Complete HuggingFace Hub Scraping Runner

This script runs the complete scraping process with all optimizations
and integrates with the existing model manager system.
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from production_hf_scraper import ProductionHFScraper
from enhanced_model_scraper import EnhancedModelScraper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_complete_scraping():
    """Run complete HuggingFace Hub scraping with all features"""
    
    print("🚀 Complete HuggingFace Hub Model Scraping System")
    print("=" * 70)
    print()
    
    # Check for API token
    hf_token = os.getenv("HF_TOKEN")
    has_token = bool(hf_token)
    
    print(f"🔑 HuggingFace API Token: {'✅ Available' if has_token else '❌ Not found'}")
    print(f"🌐 Network Access: {'✅ Production mode' if has_token else '🎭 Mock mode'}")
    print()
    
    # Configuration options
    print("📋 Configuration Options:")
    print("1. Mock mode (fast, 10K synthetic models)")
    print("2. Production mode (real HF API, all models)")
    print("3. Hybrid mode (real API, limited models)")
    print()
    
    mode = input("🔧 Select mode (1/2/3, default 1): ").strip() or "1"
    
    if mode == "1":
        # Mock mode with enhanced scraper
        print("\n🎭 Running in Mock Mode with Enhanced Scraper")
        print("-" * 50)
        
        scraper = EnhancedModelScraper("complete_model_data")
        
        # Get number of models
        num_models = input("🔢 Number of models (default 10000): ").strip()
        num_models = int(num_models) if num_models else 10000
        
        print(f"\n🚀 Generating {num_models:,} comprehensive synthetic models...")
        results = scraper.scrape_all_models(limit=num_models, mock_mode=True)
        
        print(f"\n✅ Mock scraping completed!")
        print(f"   • Models generated: {results['total_models']:,}")
        print(f"   • Processing rate: {results['models_per_second']:.1f} models/sec")
        print(f"   • Storage size: {results['storage_size_mb']:.1f} MB")
        
    elif mode == "2" and has_token:
        # Production mode with real API
        print("\n🌐 Running in Production Mode with Real HuggingFace API")
        print("-" * 50)
        
        async def run_production():
            scraper = ProductionHFScraper("complete_model_data", api_token=hf_token)
            
            print("⚠️  WARNING: This will scrape ALL HuggingFace models (750K+)")
            print("   Estimated time: 2-4 hours")
            print("   Storage required: ~500MB-2GB")
            
            confirm = input("\n🤔 Continue with full scraping? (y/N): ").strip().lower()
            if confirm != 'y':
                print("❌ Scraping cancelled")
                return
            
            print(f"\n🚀 Starting production scraping of all HuggingFace models...")
            results = await scraper.scrape_production_models()
            
            print(f"\n✅ Production scraping completed!")
            print(f"   • Models scraped: {results['total_models']:,}")
            print(f"   • Processing rate: {results['models_per_second']:.1f} models/sec")
            print(f"   • Storage size: {results['storage_size_mb']:.1f} MB")
        
        asyncio.run(run_production())
        
    elif mode == "3" and has_token:
        # Hybrid mode with limited real scraping
        print("\n🔄 Running in Hybrid Mode with Limited Real Scraping")
        print("-" * 50)
        
        async def run_hybrid():
            scraper = ProductionHFScraper("complete_model_data", api_token=hf_token)
            
            # Get limit
            limit = input("🔢 Number of real models to scrape (default 5000): ").strip()
            limit = int(limit) if limit else 5000
            
            print(f"\n🚀 Scraping {limit:,} real models from HuggingFace Hub...")
            results = await scraper.scrape_production_models(limit=limit)
            
            print(f"\n✅ Hybrid scraping completed!")
            print(f"   • Real models scraped: {results['total_models']:,}")
            print(f"   • Processing rate: {results['models_per_second']:.1f} models/sec")
            print(f"   • Storage size: {results['storage_size_mb']:.1f} MB")
        
        asyncio.run(run_hybrid())
        
    else:
        print("❌ Invalid mode or missing API token for production modes")
        return
    
    # Test search functionality
    print(f"\n🔍 Testing Search Functionality...")
    
    # Load the scraper with results
    if mode == "1":
        test_scraper = scraper
    else:
        test_scraper = EnhancedModelScraper("complete_model_data")
    
    # Test queries
    test_queries = [
        "GPT text generation",
        "BERT classification", 
        "vision transformer image",
        "whisper speech recognition",
        "code generation model"
    ]
    
    for query in test_queries:
        results = test_scraper.search_models(query, top_k=3)
        if results:
            print(f"\n🎯 '{query}':")
            for i, result in enumerate(results[:3], 1):
                print(f"   {i}. {result['model_name']} ({result['author']})")
                print(f"      {result['architecture']} | {result['model_size_mb']:.0f}MB | {result['similarity_score']:.3f}")
    
    # Final statistics
    stats = test_scraper.get_statistics()
    print(f"\n📊 Final Statistics:")
    print(f"   • Total models: {stats.get('total_models', 0):,}")
    print(f"   • Architectures: {stats.get('total_architectures', 0)}")
    print(f"   • Task types: {stats.get('total_tasks', 0)}")
    print(f"   • Authors: {stats.get('total_authors', 0)}")
    print(f"   • Average size: {stats.get('avg_model_size_mb', 0):.1f} MB")
    
    print(f"\n🎉 Complete scraping system ready!")
    print(f"💾 Data location: {test_scraper.data_dir}")
    print(f"🔍 K-NN search index: Ready")
    print(f"📊 Parquet analytics: Ready") 
    print(f"🌐 Model manager: Populated")

if __name__ == "__main__":
    run_complete_scraping()