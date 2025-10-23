#!/usr/bin/env python3
"""
GraphRAG Website Processing - Production Example

This example demonstrates the complete GraphRAG website processing pipeline
with real-world usage patterns and best practices.

Usage:
    python graphrag_website_example.py [URL]

Features demonstrated:
- Website content archiving and processing
- Multi-modal content extraction (HTML, PDFs, media detection)
- Knowledge graph construction from website content
- Advanced semantic search across all content types
- Performance optimization and resource management
- Dataset export for further analysis
"""

import sys
import os
import asyncio
import tempfile
import json
from datetime import datetime

# Add the project directory to Python path
sys.path.insert(0, '/home/runner/work/ipfs_datasets_py/ipfs_datasets_py')

from ipfs_datasets_py.website_graphrag_processor import WebsiteGraphRAGProcessor, WebsiteProcessingConfig


def create_sample_website_warc(output_path: str) -> str:
    """
    Create a sample WARC file representing a typical research website
    
    In production, this would be replaced with actual web crawling using
    the SimpleWebCrawler or external tools like wget/curl.
    """
    
    sample_pages = [
        {
            'url': 'https://airesearch.example.com/index.html',
            'content': '''<html>
<head>
    <title>Advanced AI Research Institute</title>
    <meta name="description" content="Leading research in artificial intelligence, machine learning, and deep learning">
</head>
<body>
    <header>
        <h1>Advanced AI Research Institute</h1>
        <nav>
            <a href="research.html">Research</a>
            <a href="publications.html">Publications</a>
            <a href="team.html">Team</a>
        </nav>
    </header>
    
    <main>
        <section id="about">
            <h2>About Our Research</h2>
            <p>We are a world-leading artificial intelligence research institute focused on advancing 
            the state-of-the-art in machine learning, natural language processing, computer vision, 
            and robotics. Our interdisciplinary team of researchers, engineers, and scientists work 
            on groundbreaking projects that push the boundaries of what's possible with AI.</p>
        </section>
        
        <section id="areas">
            <h2>Research Areas</h2>
            <ul>
                <li><strong>Deep Learning:</strong> Advanced neural network architectures and training methods</li>
                <li><strong>Natural Language Processing:</strong> Large language models and conversational AI</li>
                <li><strong>Computer Vision:</strong> Object detection, image segmentation, and visual reasoning</li>
                <li><strong>Robotics:</strong> Autonomous systems and human-robot interaction</li>
                <li><strong>AI Safety:</strong> Ensuring safe and beneficial artificial intelligence</li>
            </ul>
        </section>
        
        <section id="impact">
            <h2>Real-World Impact</h2>
            <p>Our research has been applied in healthcare for medical diagnosis, in education for 
            personalized learning systems, and in environmental science for climate modeling and 
            conservation efforts. We believe in AI that benefits humanity and addresses global challenges.</p>
        </section>
    </main>
    
    <footer>
        <p>Contact: research@airesearch.example.com | Phone: (555) 123-4567</p>
        <img src="lab_building.jpg" alt="AI Research Institute Building">
        <video src="research_overview.mp4" poster="video_thumb.jpg">Research Overview Video</video>
    </footer>
</body>
</html>'''
        },
        {
            'url': 'https://airesearch.example.com/research.html',
            'content': '''<html>
<head>
    <title>Current Research Projects - AI Research Institute</title>
</head>
<body>
    <h1>Current Research Projects</h1>
    
    <article id="project-alpha">
        <h2>Project Alpha: Multimodal Foundation Models</h2>
        <p><strong>Principal Investigator:</strong> Dr. Sarah Chen</p>
        <p><strong>Timeline:</strong> 2023-2026</p>
        <p>This project focuses on developing large-scale multimodal models that can understand 
        and generate text, images, and audio simultaneously. We're exploring novel transformer 
        architectures that enable cross-modal reasoning and few-shot learning across different 
        data modalities. The project has applications in content creation, accessibility tools, 
        and educational technology.</p>
        <p><strong>Key Technologies:</strong> Transformer networks, attention mechanisms, 
        self-supervised learning, contrastive learning</p>
        <a href="alpha_paper_2024.pdf">Download Latest Paper (PDF)</a>
        <audio src="alpha_presentation.mp3" controls>Project Alpha Presentation Audio</audio>
    </article>
    
    <article id="project-beta">
        <h2>Project Beta: AI for Climate Modeling</h2>
        <p><strong>Principal Investigator:</strong> Prof. Michael Rodriguez</p>
        <p><strong>Timeline:</strong> 2024-2027</p>
        <p>Climate change is one of the most pressing challenges of our time. This project 
        leverages advanced machine learning techniques including physics-informed neural networks 
        and graph neural networks to improve climate prediction accuracy. We're working with 
        meteorological data from satellites, weather stations, and ocean buoys to create more 
        precise long-term climate forecasts.</p>
        <p><strong>Collaborators:</strong> NOAA, NASA, European Centre for Medium-Range Weather Forecasts</p>
        <a href="beta_methodology.pdf">Methodology Paper (PDF)</a>
        <a href="beta_dataset.zip">Climate Dataset (ZIP)</a>
    </article>
    
    <article id="project-gamma">
        <h2>Project Gamma: Explainable AI for Healthcare</h2>
        <p><strong>Principal Investigator:</strong> Dr. Emily Watson</p>
        <p><strong>Timeline:</strong> 2024-2025</p>
        <p>Medical AI systems must be interpretable and trustworthy. This project develops 
        explainable AI techniques for medical image analysis, focusing on radiology and pathology. 
        We're creating neural networks that can not only make accurate diagnoses but also provide 
        clear explanations of their reasoning process to healthcare professionals.</p>
        <p><strong>Clinical Partners:</strong> Mayo Clinic, Johns Hopkins Hospital, Stanford Medicine</p>
        <video src="gamma_demo.mp4" controls poster="gamma_thumb.jpg">Project Gamma Demo Video</video>
    </article>
</body>
</html>'''
        },
        {
            'url': 'https://airesearch.example.com/team.html',
            'content': '''<html>
<head>
    <title>Research Team - AI Research Institute</title>
</head>
<body>
    <h1>Our Research Team</h1>
    
    <section id="faculty">
        <h2>Faculty Researchers</h2>
        
        <div class="researcher">
            <h3>Dr. Sarah Chen - Director of Research</h3>
            <p><strong>Education:</strong> PhD in Computer Science, MIT (2018)</p>
            <p><strong>Specialization:</strong> Large language models, multimodal AI, transformer architectures</p>
            <p>Dr. Chen is a leading expert in foundation models and has published over 40 papers 
            in top-tier AI conferences including NeurIPS, ICML, and ICLR. Before joining our institute, 
            she was a senior researcher at Google DeepMind where she contributed to breakthrough 
            developments in attention mechanisms and self-supervised learning.</p>
            <p><strong>Recent Awards:</strong> Rising Star Award (AAAI 2023), Best Paper Award (NeurIPS 2022)</p>
        </div>
        
        <div class="researcher">
            <h3>Prof. Michael Rodriguez - Climate AI Lab Director</h3>
            <p><strong>Education:</strong> PhD in Atmospheric Physics, Stanford (2015), PostDoc in ML, Berkeley (2017)</p>
            <p><strong>Specialization:</strong> Physics-informed neural networks, climate modeling, environmental AI</p>
            <p>Professor Rodriguez bridges the gap between climate science and artificial intelligence. 
            His interdisciplinary research combines deep domain expertise in atmospheric physics with 
            cutting-edge machine learning techniques. He has been featured in Nature Climate Change 
            and Science magazines for his innovative approaches to climate prediction.</p>
            <p><strong>Grants:</strong> NSF CAREER Award ($500K), NOAA Climate Modeling Grant ($1.2M)</p>
        </div>
        
        <div class="researcher">
            <h3>Dr. Emily Watson - Medical AI Research Lead</h3>
            <p><strong>Education:</strong> MD, Harvard Medical School (2016), PhD in Biomedical Informatics, Stanford (2020)</p>
            <p><strong>Specialization:</strong> Medical image analysis, explainable AI, clinical decision support</p>
            <p>Dr. Watson uniquely combines medical expertise with advanced AI research. As a practicing 
            radiologist and computer scientist, she understands both the clinical needs and technical 
            challenges in medical AI. Her work on explainable diagnostic systems has been adopted by 
            several major hospitals and has the potential to transform medical practice.</p>
            <p><strong>Patents:</strong> 3 US patents on medical imaging AI, 2 pending applications</p>
        </div>
    </section>
    
    <section id="students">
        <h2>Graduate Students & Postdocs</h2>
        <p>Our institute hosts 15 PhD students and 4 postdoctoral researchers working across 
        various AI domains including natural language processing, computer vision, reinforcement 
        learning, and AI safety. Students collaborate on cutting-edge research while pursuing 
        their doctoral studies in partnership with top universities worldwide.</p>
        
        <p><strong>Recent Graduate Placements:</strong></p>
        <ul>
            <li>Research Scientist positions at Google, Microsoft, OpenAI, Anthropic</li>
            <li>Faculty positions at UC Berkeley, Carnegie Mellon, University of Toronto</li>
            <li>Startup founders of AI companies with $10M+ in funding</li>
        </ul>
    </section>
    
    <footer>
        <img src="team_photo.jpg" alt="AI Research Institute Team Photo 2024">
        <p>Join our team! We're always looking for talented researchers passionate about AI.</p>
        <p>Contact: careers@airesearch.example.com</p>
    </footer>
</body>
</html>'''
        }
    ]
    
    # Create WARC file
    with open(output_path, 'w', encoding='utf-8') as f:
        # WARC file header
        f.write("WARC/1.0\n")
        f.write("WARC-Type: warcinfo\n")
        f.write(f"WARC-Date: {datetime.now().isoformat()}Z\n")
        f.write(f"WARC-Filename: {os.path.basename(output_path)}\n")
        f.write("Content-Length: 0\n")
        f.write("\n")
        
        # Write each page as WARC record
        for page in sample_pages:
            content = page['content']
            content_length = len(content.encode('utf-8'))
            
            f.write("WARC/1.0\n")
            f.write("WARC-Type: response\n")
            f.write(f"WARC-Target-URI: {page['url']}\n")
            f.write(f"WARC-Date: {datetime.now().isoformat()}Z\n")
            f.write("Content-Type: application/http; msgtype=response\n")
            f.write(f"Content-Length: {content_length + 100}\n")  # Extra for HTTP headers
            f.write("\n")
            
            # HTTP response
            f.write("HTTP/1.1 200 OK\n")
            f.write("Content-Type: text/html; charset=utf-8\n")
            f.write(f"Content-Length: {content_length}\n")
            f.write("\n")
            
            # HTML content
            f.write(content)
            f.write("\n\n")
    
    return output_path


async def main():
    """
    Main demonstration of GraphRAG website processing
    """
    
    print("🌟 GraphRAG Website Processing - Production Example")
    print("=" * 80)
    
    # Configuration for production-ready processing
    config = WebsiteProcessingConfig(
        # Archive settings
        crawl_depth=3,
        include_robots_txt=True,
        archive_services=[],  # Skip external archiving for this demo
        
        # Content processing
        include_media=True,
        max_file_size_mb=50,
        supported_media_types=['audio/mpeg', 'audio/wav', 'video/mp4', 'video/webm'],
        
        # GraphRAG settings  
        enable_graphrag=True,
        vector_store_type="faiss",
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",  # Will fallback to dummy
        chunk_size=1000,
        chunk_overlap=200,
        
        # Performance settings
        max_parallel_processing=4,
        processing_timeout_minutes=15
    )
    
    print(f"📋 Configuration:")
    print(f"   • Crawl depth: {config.crawl_depth}")
    print(f"   • Include media: {config.include_media}")
    print(f"   • GraphRAG enabled: {config.enable_graphrag}")
    print(f"   • Parallel workers: {config.max_parallel_processing}")
    print(f"   • Vector store: {config.vector_store_type}")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        
        # Step 1: Create or crawl website content
        print(f"\n🕷️  Step 1: Website Content Acquisition")
        
        if len(sys.argv) > 1:
            url = sys.argv[1]
            print(f"   Target URL: {url}")
            print(f"   Note: In production, this would crawl the actual website")
            print(f"   For demo purposes, using sample research institute content")
        else:
            url = "https://airesearch.example.com"
            print(f"   Using sample website: {url}")
        
        # Create sample WARC file (in production, use SimpleWebCrawler or external tools)
        warc_file = os.path.join(temp_dir, "website.warc")
        create_sample_website_warc(warc_file)
        print(f"   ✅ WARC file created: {warc_file}")
        
        # Step 2: Initialize GraphRAG processor
        print(f"\n⚙️  Step 2: GraphRAG Processor Initialization")
        
        processor = WebsiteGraphRAGProcessor(config)
        print(f"   ✅ WebsiteGraphRAGProcessor initialized")
        print(f"   ✅ Content discovery engine ready")
        print(f"   ✅ Multi-modal processor ready")
        print(f"   ✅ Knowledge graph extractor ready")
        
        # Step 3: Process website through complete pipeline
        print(f"\n🔄 Step 3: Complete Pipeline Processing")
        
        start_time = datetime.now()
        
        # Content discovery
        print(f"   📊 Discovering content...")
        content_manifest = await processor.content_discovery.discover_content(warc_file)
        print(f"      → Found {content_manifest.total_assets} total assets")
        print(f"      → HTML pages: {len(content_manifest.html_pages)}")
        print(f"      → PDF documents: {len(content_manifest.pdf_documents)}")
        print(f"      → Media files: {len(content_manifest.media_files)}")
        
        # Multi-modal processing
        print(f"   🔤 Processing multi-modal content...")
        processed_content = await processor.multimodal_processor.process_content_batch(
            content_manifest=content_manifest,
            include_embeddings=True,
            include_media=True
        )
        print(f"      → Processed {processed_content.total_items} items")
        print(f"      → Success rate: {processed_content.success_rate:.1f}%")
        print(f"      → Generated {sum(1 for item in processed_content.processed_items if item.has_embeddings)} embeddings")
        
        # Knowledge graph extraction
        print(f"   🕸️  Extracting knowledge graph...")
        knowledge_graph = await processor._extract_knowledge_graph(processed_content)
        if knowledge_graph:
            print(f"      → Extracted {len(knowledge_graph.entities)} entities")
            print(f"      → Created {len(knowledge_graph.relationships)} relationships")
            
            # Show top entities
            top_entities = sorted(knowledge_graph.entities.values(), key=lambda e: e.confidence, reverse=True)[:5]
            print(f"      → Top entities:")
            for entity in top_entities:
                print(f"         • {entity.name} ({entity.entity_type}, confidence: {entity.confidence:.2f})")
        
        # Build final GraphRAG system
        print(f"   🏗️  Building GraphRAG system...")
        from ipfs_datasets_py.website_graphrag_system import WebsiteGraphRAGSystem
        
        website_system = WebsiteGraphRAGSystem(
            url=url,
            content_manifest=content_manifest,
            processed_content=processed_content,
            knowledge_graph=knowledge_graph,
            graphrag=None  # Simplified for demo
        )
        
        processing_time = (datetime.now() - start_time).total_seconds()
        print(f"   ✅ GraphRAG system created in {processing_time:.2f} seconds")
        
        # Step 4: Demonstrate search capabilities
        print(f"\n🔍 Step 4: Advanced Search Demonstration")
        
        search_queries = [
            ("AI research areas", "What research areas does this institute focus on?"),
            ("machine learning projects", "What machine learning projects are currently active?"),
            ("climate modeling", "How is AI being used for climate modeling?"),
            ("medical AI applications", "What are the medical applications of AI research?"),
            ("research team expertise", "What expertise do the research team members have?")
        ]
        
        search_results_summary = []
        
        for query_short, query_long in search_queries:
            print(f"\n   Query: '{query_long}'")
            
            results = website_system.query(
                query_text=query_long,
                content_types=['html'],
                reasoning_depth="moderate",
                max_results=3
            )
            
            print(f"   → Found {results.total_results} results in {results.processing_time_seconds:.3f}s")
            
            for i, result in enumerate(results.results[:2]):  # Show top 2
                print(f"      {i+1}. {result.title} (relevance: {result.relevance_score:.3f})")
                print(f"         {result.content_snippet[:100]}...")
            
            search_results_summary.append({
                'query': query_short,
                'results_count': results.total_results,
                'top_score': results.results[0].relevance_score if results.results else 0
            })
        
        # Step 5: Performance analysis
        print(f"\n📈 Step 5: Performance Analysis")
        
        from ipfs_datasets_py.performance_optimizer import WebsiteProcessingOptimizer
        
        optimizer = WebsiteProcessingOptimizer()
        optimization_plan = await optimizer.optimize_processing_pipeline(content_manifest)
        
        print(f"   Performance Metrics:")
        print(f"   • Total processing time: {processing_time:.2f} seconds")
        print(f"   • Items per second: {processed_content.total_items / processing_time:.2f}")
        print(f"   • Recommended workers: {optimization_plan.recommended_parallel_workers}")
        print(f"   • Estimated memory usage: {optimization_plan.memory_requirements_gb:.2f} GB")
        print(f"   • Optimal processing order: {' → '.join(optimization_plan.processing_order)}")
        
        # Step 6: Export and summary
        print(f"\n💾 Step 6: Dataset Export & Summary")
        
        # Export processed dataset
        dataset_file = website_system.export_dataset(output_format="json", include_embeddings=True)
        
        if os.path.exists(dataset_file):
            file_size_mb = os.path.getsize(dataset_file) / (1024 * 1024)
            print(f"   ✅ Dataset exported: {dataset_file} ({file_size_mb:.2f} MB)")
            
            # Show dataset structure
            with open(dataset_file, 'r', encoding='utf-8') as f:
                dataset = json.load(f)
            
            print(f"   📊 Dataset contents:")
            print(f"      • Total content items: {len(dataset['content'])}")
            print(f"      • Average text length: {sum(len(item.get('text_content', '')) for item in dataset['content']) / len(dataset['content']):.0f} chars")
            print(f"      • Items with embeddings: {sum(1 for item in dataset['content'] if 'embeddings' in item)}")
            
            # Cleanup
            os.remove(dataset_file)
        
        # Final summary
        print(f"\n🎯 Processing Summary")
        print(f"=" * 80)
        print(f"Website: {url}")
        print(f"Content processed: {processed_content.total_items} items")
        print(f"Knowledge extracted: {len(knowledge_graph.entities) if knowledge_graph else 0} entities")
        print(f"Search queries tested: {len(search_queries)}")
        print(f"Average search relevance: {sum(s['top_score'] for s in search_results_summary) / len(search_results_summary):.3f}")
        print(f"Processing efficiency: {processed_content.total_items / processing_time:.2f} items/sec")
        
        print(f"\n✅ GraphRAG Website Processing Complete!")
        print(f"   Ready for production deployment with:")
        print(f"   • Real website crawling using SimpleWebCrawler")
        print(f"   • External archive integration (Internet Archive, Archive.is)")
        print(f"   • Media transcription for audio/video content")
        print(f"   • Advanced GraphRAG reasoning")
        print(f"   • Scalable deployment with Docker/Kubernetes")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print(f"\n🌟 Demo completed successfully!")
        sys.exit(0)
    except KeyboardInterrupt:
        print(f"\n⚠️ Demo interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)