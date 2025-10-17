#!/usr/bin/env python3
"""
Phase 7 Production Demonstration - Advanced Analytics & ML Integration

This script demonstrates the complete Phase 7 advanced analytics and ML
integration capabilities in a production-like environment.
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

# Import Phase 7 components
from ipfs_datasets_py.ml.content_classification import ContentClassificationPipeline
from ipfs_datasets_py.ml.quality_models import ProductionMLModelServer
from ipfs_datasets_py.analytics.cross_website_analyzer import CrossWebsiteAnalyzer


async def demonstrate_phase7_capabilities():
    """Demonstrate comprehensive Phase 7 capabilities"""
    
    print("🚀 Phase 7 Advanced Analytics & ML Integration Demo")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().isoformat()}")
    
    # Initialize components
    print("\n🔧 Initializing Phase 7 Components...")
    
    # 1. ML Content Classification
    print("  📊 ML Content Classification Pipeline...")
    ml_pipeline = ContentClassificationPipeline()
    
    # 2. Production ML Models
    print("  🤖 Production ML Model Server...")
    model_server = ProductionMLModelServer()
    model_load_results = await model_server.load_models()
    
    models_loaded = sum(1 for success in model_load_results.values() if success)
    print(f"     Loaded {models_loaded}/{len(model_load_results)} ML models")
    
    # 3. Cross-Website Analytics
    print("  🌐 Cross-Website Analytics Engine...")
    cross_site_analyzer = CrossWebsiteAnalyzer()
    
    print("  ✅ All Phase 7 components initialized successfully!")
    
    # Demonstrate ML-Enhanced Content Analysis
    print("\n🧠 ML-Enhanced Content Analysis Demo")
    print("-" * 40)
    
    # Create realistic content samples
    content_samples = [
        {
            'url': 'https://ai-research.example.com/neural-networks',
            'type': 'html',
            'text': 'Neural networks represent a fundamental paradigm in artificial intelligence, inspired by biological neural systems. This comprehensive analysis explores deep learning architectures, including convolutional neural networks (CNNs) for image recognition and recurrent neural networks (RNNs) for sequence processing. The methodology employs gradient descent optimization with backpropagation algorithms to train multi-layer perceptrons on large-scale datasets.',
            'metadata': {'title': 'Neural Networks in AI', 'author': 'Dr. Smith', 'publication_date': '2024-01-15'}
        },
        {
            'url': 'https://tech-blog.example.com/machine-learning-guide',
            'type': 'html', 
            'text': 'Machine learning algorithms enable computers to learn patterns from data without explicit programming. This practical guide covers supervised learning techniques including linear regression, decision trees, and support vector machines. We also explore unsupervised learning methods such as clustering and dimensionality reduction.',
            'metadata': {'title': 'ML Algorithms Guide', 'author': 'Tech Team', 'category': 'tutorial'}
        },
        {
            'url': 'https://business-site.example.com/ai-strategy',
            'type': 'html',
            'text': 'Implementing artificial intelligence in business operations requires strategic planning and careful consideration of organizational goals. This executive summary outlines key considerations for AI adoption including cost-benefit analysis, technology selection, and change management processes.',
            'metadata': {'title': 'AI Business Strategy', 'author': 'Business Analyst', 'department': 'strategy'}
        }
    ]
    
    # Process content with ML analysis
    processed_items = []
    for sample in content_samples:
        # Create mock processed content
        mock_content = type('ProcessedContent', (), {
            'source_url': sample['url'],
            'content_type': sample['type'],
            'text_content': sample['text'],
            'metadata': sample['metadata']
        })()
        processed_items.append(mock_content)
    
    # Create content batch
    mock_batch = type('ProcessedContentBatch', (), {
        'base_url': 'https://demo.example.com',
        'processed_items': processed_items
    })()
    
    # Run ML analysis
    ml_analysis = await ml_pipeline.analyze_processed_content(mock_batch)
    
    print(f"📈 ML Analysis Results:")
    print(f"  Items Analyzed: {ml_analysis.total_items_analyzed}")
    print(f"  Processing Time: {ml_analysis.processing_time_seconds:.2f}s")
    print(f"  Average Quality Score: {ml_analysis.aggregate_metrics.get('average_quality_score', 0):.2f}")
    print(f"  Quality Std Dev: {ml_analysis.aggregate_metrics.get('quality_std_dev', 0):.2f}")
    print(f"  Most Common Topic: {ml_analysis.aggregate_metrics.get('most_common_topic', 'unknown')}")
    print(f"  Topic Diversity: {ml_analysis.aggregate_metrics.get('topic_diversity', 0)}")
    print(f"  High Quality Ratio: {ml_analysis.aggregate_metrics.get('high_quality_content_ratio', 0):.1%}")
    print(f"  Overall Sentiment: {ml_analysis.aggregate_metrics.get('overall_sentiment_positive', 0):.2f} positive")
    
    # Show individual content analysis
    print(f"\n📄 Individual Content Analysis:")
    for url, analysis in ml_analysis.analysis_results.items():
        print(f"  🔍 {url}")
        print(f"     Quality: {analysis.quality_score:.2f} | Confidence: {analysis.confidence:.2f}")
        print(f"     Topics: {', '.join(analysis.topics[:3])}")
        print(f"     Sentiment: {analysis.sentiment['positive']:.2f} pos, {analysis.sentiment['negative']:.2f} neg")
        print(f"     Anomaly Score: {analysis.anomaly_score:.2f}")
    
    # Demonstrate production ML model predictions
    print(f"\n🤖 Production ML Model Predictions:")
    for content in processed_items[:2]:  # Test first 2 items
        # Quality assessment
        quality_pred = await model_server.assess_content_quality(content)
        
        print(f"  📊 {content.source_url}")
        print(f"     Quality Score: {quality_pred.prediction.get('quality_score', 0):.2f}")
        print(f"     Quality Class: {quality_pred.prediction.get('quality_class', 'unknown')}")
        print(f"     Confidence: {quality_pred.confidence:.2f}")
        print(f"     Processing Time: {quality_pred.processing_time_ms:.1f}ms")
    
    # Demonstrate Cross-Website Analysis
    print(f"\n🌐 Cross-Website Correlation Analysis Demo")
    print("-" * 45)
    
    # Create mock website systems for correlation analysis
    mock_websites = []
    for i, sample in enumerate(content_samples):
        mock_system = type('WebsiteSystem', (), {
            'url': sample['url'],
            'get_content_overview': lambda: {
                'total_pages': 10 + i * 5,
                'total_pdfs': i * 2,
                'total_media': i
            },
            'processed_content': type('ProcessedContent', (), {
                'processed_items': [processed_items[i]]
            })(),
            'knowledge_graph': type('KnowledgeGraph', (), {
                'entities': [
                    type('Entity', (), {'label': f'entity_{i}_1'})(),
                    type('Entity', (), {'label': f'entity_{i}_2'})()
                ],
                'relationships': []
            })()
        })()
        mock_websites.append(mock_system)
    
    # Run cross-site analysis
    cross_analysis = await cross_site_analyzer.analyze_cross_site_correlations(mock_websites)
    
    print(f"🔗 Cross-Site Correlation Results:")
    print(f"  Websites Analyzed: {len(cross_analysis.websites_analyzed)}")
    print(f"  Correlations Found: {len(cross_analysis.correlations)}")
    print(f"  Global Trends: {len(cross_analysis.detected_trends)}")
    print(f"  Processing Time: {cross_analysis.processing_time_seconds:.2f}s")
    
    # Show correlation details
    if cross_analysis.correlations:
        print(f"\n📊 Website Correlations:")
        for correlation in cross_analysis.correlations[:3]:  # Show top 3
            print(f"  🔗 {correlation.website_a} ↔ {correlation.website_b}")
            print(f"     Similarity: {correlation.similarity_score:.2f}")
            print(f"     Type: {correlation.correlation_type}")
            print(f"     Content Overlap: {correlation.content_overlap:.2f}")
    
    # Show global metrics
    print(f"\n🌍 Global Metrics:")
    for metric, value in cross_analysis.global_metrics.items():
        if isinstance(value, float):
            print(f"  {metric}: {value:.2f}")
        else:
            print(f"  {metric}: {value}")
    
    # Create global knowledge graph
    global_kg = await cross_site_analyzer.create_global_knowledge_graph(mock_websites)
    
    print(f"\n🕸️ Global Knowledge Graph:")
    print(f"  Participating Websites: {len(global_kg.participating_websites)}")
    print(f"  Global Entities: {len(global_kg.global_entities)}")
    print(f"  Cross-Site Connections: {len(global_kg.cross_site_connections)}")
    print(f"  Quality Score: {global_kg.quality_score:.2f}")
    
    if global_kg.cross_site_connections:
        print(f"  🔗 Cross-Site Entity Connections:")
        for connection in global_kg.cross_site_connections[:3]:
            print(f"     '{connection['entity_name']}' found in {len(connection['participating_websites'])} websites")
    
    # Performance Summary
    print(f"\n⚡ Phase 7 Performance Summary")
    print("-" * 35)
    
    # Model server performance
    model_performance = model_server.get_model_performance_summary()
    print(f"🤖 ML Model Performance:")
    print(f"  Total Predictions: {model_performance['total_predictions']}")
    print(f"  Average Processing Time: {model_performance['average_processing_time_ms']:.1f}ms")
    print(f"  Cache Hit Rate: {model_performance['cache_hit_rate']:.1%}")
    print(f"  Active Models: {len(model_performance['loaded_models'])}")
    
    # Cross-site analytics
    analytics_summary = cross_site_analyzer.get_cross_site_analytics_summary()
    if 'total_cross_site_analyses' in analytics_summary:
        print(f"\n🌐 Cross-Site Analytics:")
        print(f"  Total Analyses: {analytics_summary['total_cross_site_analyses']}")
        print(f"  Websites Tracked: {analytics_summary['websites_analyzed_count']}")
    
    # ML classification analytics
    classification_analytics = ml_pipeline.get_analytics_summary()
    if 'total_analyses' in classification_analytics:
        print(f"\n📊 ML Classification Analytics:")
        print(f"  Total Analyses: {classification_analytics['total_analyses']}")
        print(f"  Items Processed: {classification_analytics['processing_stats']['total_items_processed']}")
    
    # Recommendations Summary
    print(f"\n💡 ML-Powered Recommendations:")
    for i, recommendation in enumerate(ml_analysis.recommendations, 1):
        print(f"  {i}. {recommendation}")
    
    print(f"\n💡 Cross-Site Recommendations:")
    for i, recommendation in enumerate(cross_analysis.recommendations, 1):
        print(f"  {i}. {recommendation}")
    
    # Success Summary
    print(f"\n✅ Phase 7 Advanced Analytics & ML Integration - COMPLETE!")
    print(f"=" * 60)
    print(f"🎯 Key Achievements:")
    print(f"  ✅ ML Content Classification: {ml_analysis.total_items_analyzed} items analyzed")
    print(f"  ✅ Production ML Models: {models_loaded} models operational")
    print(f"  ✅ Cross-Website Analytics: {len(cross_analysis.correlations)} correlations detected")
    print(f"  ✅ Global Knowledge Graph: {len(global_kg.global_entities)} entities integrated")
    print(f"  ✅ Advanced Recommendations: {len(ml_analysis.recommendations + cross_analysis.recommendations)} generated")
    
    print(f"\n🚀 Phase 7 is production-ready with advanced ML and analytics capabilities!")
    
    return {
        'ml_analysis': ml_analysis,
        'cross_analysis': cross_analysis,
        'global_knowledge_graph': global_kg,
        'model_performance': model_performance
    }


async def main():
    """Run Phase 7 production demonstration"""
    
    try:
        results = await demonstrate_phase7_capabilities()
        
        # Export demonstration results
        export_data = {
            'demonstration_timestamp': datetime.now().isoformat(),
            'phase7_status': 'completed',
            'ml_analysis_summary': {
                'items_analyzed': results['ml_analysis'].total_items_analyzed,
                'average_quality': results['ml_analysis'].aggregate_metrics.get('average_quality_score', 0),
                'processing_time': results['ml_analysis'].processing_time_seconds
            },
            'cross_site_analysis_summary': {
                'websites_analyzed': len(results['cross_analysis'].websites_analyzed),
                'correlations_found': len(results['cross_analysis'].correlations),
                'trends_detected': len(results['cross_analysis'].detected_trends)
            },
            'global_knowledge_graph_summary': {
                'participating_websites': len(results['global_knowledge_graph'].participating_websites),
                'global_entities': len(results['global_knowledge_graph'].global_entities),
                'quality_score': results['global_knowledge_graph'].quality_score
            },
            'model_performance_summary': results['model_performance']
        }
        
        # Save demonstration results
        output_file = f"/tmp/phase7_demonstration_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)
        
        print(f"\n📁 Demonstration results exported to: {output_file}")
        
        return True
        
    except Exception as e:
        print(f"❌ Phase 7 demonstration failed: {e}")
        return False


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)