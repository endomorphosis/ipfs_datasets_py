#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File Converter CLI

Command-line interface for the file_converter module.
Provides easy access to file conversion, knowledge graph extraction,
text summarization, and vector embedding generation.
"""

import click
import anyio
import json
import sys
from pathlib import Path
from typing import Optional, List

# Import with error handling for when module is not yet installed
try:
    from ipfs_datasets_py.file_converter import (
        FileConverter,
        UniversalKnowledgeGraphPipeline,
        TextSummarizationPipeline,
        VectorEmbeddingPipeline,
        is_url
    )
except ImportError:
    # Try relative import for development
    from . import (
        FileConverter,
        UniversalKnowledgeGraphPipeline,
        TextSummarizationPipeline,
        VectorEmbeddingPipeline,
        is_url
    )


# ============================================================================
# Helper Functions
# ============================================================================

def async_run(coro):
    """Run async coroutine in sync context."""
    return anyio.run(coro)


def print_result(result, format_type='text', output_file=None):
    """Print or save result in specified format."""
    if format_type == 'json':
        if hasattr(result, '__dict__'):
            data = vars(result)
        else:
            data = result
        output = json.dumps(data, indent=2, default=str)
    elif format_type == 'markdown':
        if hasattr(result, 'text'):
            output = f"# Conversion Result\n\n{result.text}"
        else:
            output = str(result)
    else:  # text
        if hasattr(result, 'text'):
            output = result.text
        else:
            output = str(result)
    
    if output_file:
        Path(output_file).write_text(output)
        click.echo(f"Output saved to: {output_file}")
    else:
        click.echo(output)


# ============================================================================
# Main CLI Group
# ============================================================================

@click.group()
@click.version_option(version='0.6.4', prog_name='file-converter')
def cli():
    """
    File Converter CLI - Convert files to text, extract knowledge graphs,
    generate summaries, and create vector embeddings.
    
    Supports 30+ file formats including PDF, DOCX, XLSX, PPT, archives,
    and URLs. Integrates with IPFS storage and ML acceleration.
    """
    pass


# ============================================================================
# Convert Command
# ============================================================================

@cli.command()
@click.argument('input_path')
@click.option('--backend', '-b', default='native', 
              type=click.Choice(['native', 'markitdown', 'omni', 'auto']),
              help='Backend to use for conversion')
@click.option('--output', '-o', type=click.Path(), help='Output file path')
@click.option('--format', '-f', default='text',
              type=click.Choice(['text', 'json', 'markdown']),
              help='Output format')
@click.option('--extract-archives', is_flag=True,
              help='Extract and process archive contents')
@click.option('--ipfs', is_flag=True,
              help='Store result on IPFS')
def convert(input_path, backend, output, format, extract_archives, ipfs):
    """
    Convert a file or URL to text.
    
    Examples:
        file-converter convert document.pdf
        file-converter convert https://example.com/file.pdf --ipfs
        file-converter convert archive.zip --extract-archives
        file-converter convert report.docx -o output.txt
    """
    async def _convert():
        converter = FileConverter(backend=backend)
        click.echo(f"Converting: {input_path}")
        
        result = await converter.convert(
            input_path,
            extract_archives=extract_archives
        )
        
        if ipfs:
            click.echo("IPFS storage not yet implemented in CLI")
        
        print_result(result, format, output)
        
        if hasattr(result, 'metadata'):
            click.echo(f"\nMetadata: {result.metadata.get('format', 'unknown')}", err=True)
    
    async_run(_convert())


# ============================================================================
# Batch Command
# ============================================================================

@cli.command()
@click.argument('input_paths', nargs=-1, required=True)
@click.option('--backend', '-b', default='native',
              type=click.Choice(['native', 'markitdown', 'omni', 'auto']),
              help='Backend to use for conversion')
@click.option('--output-dir', '-o', type=click.Path(),
              help='Output directory for results')
@click.option('--format', '-f', default='text',
              type=click.Choice(['text', 'json', 'markdown']),
              help='Output format')
@click.option('--max-concurrent', '-c', default=5, type=int,
              help='Maximum concurrent conversions')
@click.option('--extract-archives', is_flag=True,
              help='Extract and process archive contents')
def batch(input_paths, backend, output_dir, format, max_concurrent, extract_archives):
    """
    Batch convert multiple files or URLs.
    
    Examples:
        file-converter batch *.pdf
        file-converter batch file1.docx file2.txt file3.html
        file-converter batch docs/*.pdf -o output_dir/
    """
    async def _batch():
        converter = FileConverter(backend=backend)
        click.echo(f"Processing {len(input_paths)} files...")
        
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        for i, path in enumerate(input_paths, 1):
            click.echo(f"[{i}/{len(input_paths)}] Converting: {path}")
            try:
                result = await converter.convert(
                    path,
                    extract_archives=extract_archives
                )
                
                if output_dir:
                    filename = Path(path).stem + '.txt'
                    output_path = Path(output_dir) / filename
                    print_result(result, format, str(output_path))
                else:
                    click.echo(f"--- Result for {path} ---")
                    print_result(result, format, None)
                    click.echo("")
            except Exception as e:
                click.echo(f"Error processing {path}: {e}", err=True)
    
    async_run(_batch())


# ============================================================================
# Knowledge Graph Command
# ============================================================================

@cli.command('knowledge-graph')
@click.argument('input_path')
@click.option('--output', '-o', type=click.Path(), help='Output file path (JSON)')
@click.option('--ipfs', is_flag=True, help='Store on IPFS')
def knowledge_graph(input_path, output, ipfs):
    """
    Extract knowledge graph (entities and relationships) from a file.
    
    Examples:
        file-converter knowledge-graph document.pdf
        file-converter knowledge-graph paper.pdf -o graph.json
    """
    async def _kg():
        pipeline = UniversalKnowledgeGraphPipeline(enable_ipfs=ipfs)
        click.echo(f"Extracting knowledge graph from: {input_path}")
        
        result = await pipeline.process(input_path)
        
        data = {
            'entities': result.entities,
            'relationships': result.relationships,
            'summary': result.summary if hasattr(result, 'summary') else None
        }
        
        if output:
            Path(output).write_text(json.dumps(data, indent=2, default=str))
            click.echo(f"Knowledge graph saved to: {output}")
        else:
            click.echo(json.dumps(data, indent=2, default=str))
        
        click.echo(f"\nEntities: {len(result.entities)}", err=True)
        click.echo(f"Relationships: {len(result.relationships)}", err=True)
    
    async_run(_kg())


# ============================================================================
# Summarize Command
# ============================================================================

@cli.command()
@click.argument('input_path')
@click.option('--output', '-o', type=click.Path(), help='Output file path')
@click.option('--format', '-f', default='text',
              type=click.Choice(['text', 'json', 'markdown']),
              help='Output format')
def summarize(input_path, output, format):
    """
    Generate a text summary from a file or URL.
    
    Examples:
        file-converter summarize document.pdf
        file-converter summarize report.docx -o summary.txt
    """
    async def _summarize():
        pipeline = TextSummarizationPipeline()
        click.echo(f"Generating summary for: {input_path}")
        
        result = await pipeline.summarize(input_path)
        
        if format == 'json':
            data = {
                'summary': result.summary,
                'key_entities': result.key_entities if hasattr(result, 'key_entities') else []
            }
            output_text = json.dumps(data, indent=2, default=str)
        else:
            output_text = result.summary
        
        if output:
            Path(output).write_text(output_text)
            click.echo(f"Summary saved to: {output}")
        else:
            click.echo(output_text)
    
    async_run(_summarize())


# ============================================================================
# Embed Command
# ============================================================================

@cli.command()
@click.argument('input_path')
@click.option('--model', '-m', default='sentence-transformers/all-MiniLM-L6-v2',
              help='Embedding model to use')
@click.option('--vector-store', '-v', default='faiss',
              type=click.Choice(['faiss', 'qdrant', 'elasticsearch']),
              help='Vector store type')
@click.option('--output', '-o', type=click.Path(),
              help='Output file for embeddings (JSON)')
@click.option('--ipfs', is_flag=True, help='Store on IPFS')
def embed(input_path, model, vector_store, output, ipfs):
    """
    Generate vector embeddings from a file or URL.
    
    Examples:
        file-converter embed document.pdf
        file-converter embed paper.pdf --model all-mpnet-base-v2
        file-converter embed docs.zip -o embeddings.json
    """
    async def _embed():
        pipeline = VectorEmbeddingPipeline(
            embedding_model=model,
            vector_store=vector_store,
            enable_ipfs=ipfs
        )
        click.echo(f"Generating embeddings for: {input_path}")
        
        result = await pipeline.process(input_path)
        
        click.echo(f"Generated {len(result.embeddings)} embeddings")
        
        if output:
            data = {
                'embeddings': result.embeddings,
                'vector_store_ids': result.vector_store_ids,
                'text_chunks': result.text_chunks[:10] if hasattr(result, 'text_chunks') else []
            }
            Path(output).write_text(json.dumps(data, indent=2, default=str))
            click.echo(f"Embeddings saved to: {output}")
    
    async_run(_embed())


# ============================================================================
# Info Command
# ============================================================================

@cli.command()
@click.argument('input_path')
def info(input_path):
    """
    Show information about a file (format, size, metadata).
    
    Examples:
        file-converter info document.pdf
        file-converter info archive.zip
    """
    async def _info():
        from ipfs_datasets_py.file_converter import (
            FormatDetector,
            extract_metadata
        )
        
        click.echo(f"File: {input_path}")
        
        # Detect format
        detector = FormatDetector()
        mime_type = detector.detect(input_path)
        click.echo(f"MIME Type: {mime_type}")
        
        # Get metadata
        try:
            metadata = extract_metadata(input_path)
            click.echo(f"\nMetadata:")
            click.echo(json.dumps(metadata, indent=2, default=str))
        except Exception as e:
            click.echo(f"Could not extract metadata: {e}", err=True)
    
    async_run(_info())


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main entry point for the CLI."""
    cli()


if __name__ == '__main__':
    main()
