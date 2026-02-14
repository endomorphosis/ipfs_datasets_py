# Logic Modules - Integration Guide

This guide shows how to integrate the logic modules into your applications.

## Table of Contents

1. [Quick Start Integration](#quick-start-integration)
2. [Web Application Integration](#web-application-integration)
3. [Data Pipeline Integration](#data-pipeline-integration)
4. [Microservices Integration](#microservices-integration)
5. [CLI Tool Integration](#cli-tool-integration)
6. [Testing Integration](#testing-integration)

---

## Quick Start Integration

### Basic Setup

```python
# install.py
import subprocess
import sys

def setup_logic_modules():
    """Install and configure logic modules."""
    # Install base package
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", 
        "ipfs_datasets_py"
    ])
    
    # Optional: Install NLP support
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", 
        "spacy"
    ])
    subprocess.check_call([
        sys.executable, "-m", "spacy", "download", 
        "en_core_web_sm"
    ])
    
    # Optional: Install ML support
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "xgboost", "lightgbm"
    ])

if __name__ == "__main__":
    setup_logic_modules()
```

### Configuration

```python
# config.py
from dataclasses import dataclass
from pathlib import Path

@dataclass
class LogicConfig:
    """Configuration for logic modules."""
    # FOL Conversion
    use_nlp: bool = True
    confidence_threshold: float = 0.7
    
    # Proof Execution
    enable_caching: bool = True
    cache_size: int = 1000
    cache_ttl: int = 3600
    proof_timeout: int = 60
    default_prover: str = "z3"
    
    # Batch Processing
    batch_concurrency: int = 10
    chunk_size: int = 100
    
    # ML Confidence
    use_ml_confidence: bool = False
    ml_model_path: Path = Path("models/confidence.pkl")
    
    # Paths
    temp_dir: Path = Path("/tmp/logic_proofs")
    cache_dir: Path = Path("cache/proofs")
```

### Initialization

```python
# logic_service.py
import asyncio
from ipfs_datasets_py.logic.fol.text_to_fol import convert_text_to_fol
from ipfs_datasets_py.logic.integration.proof_execution_engine import ProofExecutionEngine
from ipfs_datasets_py.logic.batch_processing import FOLBatchProcessor
from config import LogicConfig

class LogicService:
    """Service class for logic operations."""
    
    def __init__(self, config: LogicConfig):
        self.config = config
        
        # Initialize proof engine
        self.proof_engine = ProofExecutionEngine(
            enable_caching=config.enable_caching,
            cache_size=config.cache_size,
            cache_ttl=config.cache_ttl,
            timeout=config.proof_timeout,
            default_prover=config.default_prover
        )
        
        # Initialize batch processor
        self.batch_processor = FOLBatchProcessor(
            max_concurrency=config.batch_concurrency
        )
    
    async def convert_to_fol(self, text: str) -> dict:
        """Convert text to FOL."""
        return await convert_text_to_fol(
            text,
            confidence_threshold=self.config.confidence_threshold,
            use_nlp=self.config.use_nlp
        )
    
    async def convert_batch(self, texts: list) -> dict:
        """Convert batch of texts."""
        return await self.batch_processor.convert_batch(
            texts,
            use_nlp=self.config.use_nlp,
            confidence_threshold=self.config.confidence_threshold
        )
```

---

## Web Application Integration

### FastAPI Integration

```python
# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from logic_service import LogicService, LogicConfig

app = FastAPI(title="Logic API")
logic_service = LogicService(LogicConfig())

class ConversionRequest(BaseModel):
    text: str
    use_nlp: Optional[bool] = True
    confidence_threshold: Optional[float] = 0.7

class BatchConversionRequest(BaseModel):
    texts: List[str]
    use_nlp: Optional[bool] = True

@app.post("/api/v1/convert")
async def convert_text(request: ConversionRequest):
    """Convert single text to FOL."""
    try:
        result = await logic_service.convert_to_fol(request.text)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/convert/batch")
async def convert_batch(request: BatchConversionRequest):
    """Convert batch of texts to FOL."""
    try:
        result = await logic_service.convert_batch(request.texts)
        return {
            "total": result.total_items,
            "successful": result.successful,
            "failed": result.failed,
            "results": result.results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/stats")
async def get_statistics():
    """Get cache and performance statistics."""
    cache_stats = logic_service.proof_engine.proof_cache.get_statistics()
    return {
        "cache": cache_stats,
        "service": "running"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Flask Integration

```python
# app.py
from flask import Flask, request, jsonify
from logic_service import LogicService, LogicConfig
import asyncio

app = Flask(__name__)
logic_service = LogicService(LogicConfig())

def run_async(coro):
    """Helper to run async code in Flask."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

@app.route('/api/v1/convert', methods=['POST'])
def convert_text():
    """Convert text to FOL."""
    data = request.get_json()
    text = data.get('text')
    
    if not text:
        return jsonify({"error": "Missing text"}), 400
    
    try:
        result = run_async(logic_service.convert_to_fol(text))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/v1/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
```

---

## Data Pipeline Integration

### Apache Airflow DAG

```python
# dags/logic_pipeline_dag.py
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import asyncio

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'logic_conversion_pipeline',
    default_args=default_args,
    description='Convert text data to FOL',
    schedule_interval=timedelta(days=1),
)

def extract_data(**context):
    """Extract text data from source."""
    # Your extraction logic
    texts = load_texts_from_source()
    return texts

def convert_to_fol(**context):
    """Convert texts to FOL."""
    from logic_service import LogicService, LogicConfig
    
    texts = context['task_instance'].xcom_pull(task_ids='extract_data')
    
    logic_service = LogicService(LogicConfig())
    
    def run_conversion():
        return asyncio.run(logic_service.convert_batch(texts))
    
    result = run_conversion()
    return result.to_dict()

def store_results(**context):
    """Store FOL results."""
    results = context['task_instance'].xcom_pull(task_ids='convert_to_fol')
    # Store to database, S3, etc.
    store_to_database(results)

extract_task = PythonOperator(
    task_id='extract_data',
    python_callable=extract_data,
    dag=dag,
)

convert_task = PythonOperator(
    task_id='convert_to_fol',
    python_callable=convert_to_fol,
    dag=dag,
)

store_task = PythonOperator(
    task_id='store_results',
    python_callable=store_results,
    dag=dag,
)

extract_task >> convert_task >> store_task
```

### Pandas Integration

```python
# data_processor.py
import pandas as pd
import asyncio
from logic_service import LogicService, LogicConfig

class LogicDataProcessor:
    """Process DataFrames with logic conversion."""
    
    def __init__(self):
        self.logic_service = LogicService(LogicConfig())
    
    async def process_dataframe(self, df: pd.DataFrame, text_column: str) -> pd.DataFrame:
        """Add FOL conversion to DataFrame."""
        texts = df[text_column].tolist()
        
        # Batch convert
        result = await self.logic_service.convert_batch(texts)
        
        # Add results to DataFrame
        df['fol_formula'] = [
            r['fol_formulas'][0]['fol_formula'] if r['fol_formulas'] 
            else None 
            for r in result.results
        ]
        
        df['confidence'] = [
            r['fol_formulas'][0]['confidence'] if r['fol_formulas']
            else 0.0
            for r in result.results
        ]
        
        return df

# Usage
async def main():
    processor = LogicDataProcessor()
    
    # Load data
    df = pd.read_csv('data.csv')
    
    # Process
    df = await processor.process_dataframe(df, text_column='sentence')
    
    # Save
    df.to_csv('data_with_fol.csv', index=False)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Microservices Integration

### gRPC Service

```python
# logic_grpc_service.py
import grpc
from concurrent import futures
import asyncio

# Generated from logic.proto
import logic_pb2
import logic_pb2_grpc

from logic_service import LogicService, LogicConfig

class LogicServicer(logic_pb2_grpc.LogicServiceServicer):
    """gRPC servicer for logic operations."""
    
    def __init__(self):
        self.logic_service = LogicService(LogicConfig())
    
    def ConvertToFOL(self, request, context):
        """Convert text to FOL."""
        try:
            result = asyncio.run(
                self.logic_service.convert_to_fol(request.text)
            )
            
            return logic_pb2.ConversionResponse(
                status=result['status'],
                formula=result['fol_formulas'][0]['fol_formula'] if result['fol_formulas'] else "",
                confidence=result['summary']['average_confidence']
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return logic_pb2.ConversionResponse()

def serve():
    """Start gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    logic_pb2_grpc.add_LogicServiceServicer_to_server(
        LogicServicer(), server
    )
    server.add_insecure_port('[::]:50051')
    server.start()
    print("gRPC server started on port 50051")
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

### Message Queue Integration (RabbitMQ)

```python
# logic_worker.py
import pika
import json
import asyncio
from logic_service import LogicService, LogicConfig

class LogicWorker:
    """RabbitMQ worker for logic operations."""
    
    def __init__(self, rabbitmq_url: str):
        self.connection = pika.BlockingConnection(
            pika.URLParameters(rabbitmq_url)
        )
        self.channel = self.connection.channel()
        self.logic_service = LogicService(LogicConfig())
        
        # Declare queues
        self.channel.queue_declare(queue='logic_requests', durable=True)
        self.channel.queue_declare(queue='logic_results', durable=True)
    
    def process_message(self, ch, method, properties, body):
        """Process incoming message."""
        try:
            data = json.loads(body)
            text = data['text']
            request_id = data['request_id']
            
            # Convert to FOL
            result = asyncio.run(
                self.logic_service.convert_to_fol(text)
            )
            
            # Publish result
            response = {
                'request_id': request_id,
                'result': result,
                'status': 'success'
            }
            
            self.channel.basic_publish(
                exchange='',
                routing_key='logic_results',
                body=json.dumps(response),
                properties=pika.BasicProperties(delivery_mode=2)
            )
            
            ch.basic_ack(delivery_tag=method.delivery_tag)
            
        except Exception as e:
            print(f"Error processing message: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    
    def start(self):
        """Start consuming messages."""
        self.channel.basic_qos(prefetch_count=1)
        self.channel.basic_consume(
            queue='logic_requests',
            on_message_callback=self.process_message
        )
        print("Worker started. Waiting for messages...")
        self.channel.start_consuming()

if __name__ == '__main__':
    worker = LogicWorker('amqp://localhost')
    worker.start()
```

---

## CLI Tool Integration

```python
# logic_cli.py
import click
import asyncio
import json
from pathlib import Path
from logic_service import LogicService, LogicConfig

@click.group()
def cli():
    """Logic modules CLI tool."""
    pass

@cli.command()
@click.argument('text')
@click.option('--nlp/--no-nlp', default=True, help='Use NLP extraction')
@click.option('--output', '-o', type=click.Path(), help='Output file')
def convert(text, nlp, output):
    """Convert text to FOL."""
    logic_service = LogicService(LogicConfig())
    
    result = asyncio.run(logic_service.convert_to_fol(text))
    
    if output:
        Path(output).write_text(json.dumps(result, indent=2))
        click.echo(f"Result written to {output}")
    else:
        click.echo(json.dumps(result, indent=2))

@cli.command()
@click.argument('input_file', type=click.Path(exists=True))
@click.argument('output_file', type=click.Path())
@click.option('--batch-size', default=100, help='Batch size')
def batch(input_file, output_file, batch_size):
    """Convert batch of texts from file."""
    from ipfs_datasets_py.logic.batch_processing import ChunkedBatchProcessor
    
    # Load texts
    texts = Path(input_file).read_text().split('\n')
    texts = [t.strip() for t in texts if t.strip()]
    
    # Process
    processor = ChunkedBatchProcessor(chunk_size=batch_size)
    
    async def process():
        return await processor.process_large_batch(
            items=texts,
            process_func=lambda t: convert_text_to_fol(t)
        )
    
    result = asyncio.run(process())
    
    # Save
    Path(output_file).write_text(json.dumps({
        'total': result.total_items,
        'successful': result.successful,
        'throughput': result.items_per_second
    }, indent=2))
    
    click.echo(f"Processed {result.total_items} texts in {result.total_time:.2f}s")

@cli.command()
def stats():
    """Show cache statistics."""
    from ipfs_datasets_py.logic.integration.proof_cache import get_global_cache
    
    cache = get_global_cache()
    stats = cache.get_statistics()
    
    click.echo("Cache Statistics:")
    click.echo(f"  Size: {stats['size']}/{stats['max_size']}")
    click.echo(f"  Hit rate: {stats['hit_rate']:.1%}")
    click.echo(f"  Hits: {stats['hits']}")
    click.echo(f"  Misses: {stats['misses']}")

if __name__ == '__main__':
    cli()
```

---

## Testing Integration

### pytest Integration

```python
# test_logic_integration.py
import pytest
import asyncio
from logic_service import LogicService, LogicConfig

@pytest.fixture
def logic_service():
    """Create logic service for testing."""
    config = LogicConfig(
        use_nlp=False,  # Faster for tests
        enable_caching=True,
        cache_size=100
    )
    return LogicService(config)

@pytest.mark.asyncio
async def test_convert_simple_text(logic_service):
    """Test simple text conversion."""
    result = await logic_service.convert_to_fol("All humans are mortal")
    
    assert result['status'] == 'success'
    assert len(result['fol_formulas']) > 0
    assert result['summary']['conversion_rate'] > 0

@pytest.mark.asyncio
async def test_batch_conversion(logic_service):
    """Test batch conversion."""
    texts = [
        "All dogs are animals",
        "Some cats are black",
        "Birds can fly"
    ]
    
    result = await logic_service.convert_batch(texts)
    
    assert result.total_items == 3
    assert result.successful >= 2
    assert result.items_per_second > 0

def test_cache_performance(logic_service):
    """Test cache improves performance."""
    formula = "test_formula"
    
    # First call (cache miss)
    import time
    start = time.time()
    logic_service.proof_engine.proof_cache.put(formula, "z3", {"result": "proven"})
    miss_time = time.time() - start
    
    # Second call (cache hit)
    start = time.time()
    result = logic_service.proof_engine.proof_cache.get(formula, "z3")
    hit_time = time.time() - start
    
    assert result is not None
    assert hit_time < miss_time  # Cache should be faster
```

### Integration Test Suite

```python
# test_end_to_end.py
import pytest
from logic_service import LogicService, LogicConfig

class TestEndToEnd:
    """End-to-end integration tests."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test environment."""
        self.service = LogicService(LogicConfig())
    
    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """Test complete conversion pipeline."""
        # Convert
        result = await self.service.convert_to_fol("All humans are mortal")
        assert result['status'] == 'success'
        
        # Verify formulas
        assert len(result['fol_formulas']) > 0
        formula = result['fol_formulas'][0]
        
        # Check structure
        assert 'fol_formula' in formula
        assert 'confidence' in formula
        assert formula['confidence'] > 0.5
    
    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Test error handling."""
        # Empty input
        result = await self.service.convert_to_fol("")
        assert result['status'] == 'success'
        assert len(result['fol_formulas']) == 0
```

---

## Best Practices

1. **Always use configuration objects** instead of hardcoding values
2. **Enable caching** in production for better performance
3. **Use batch processing** for large datasets
4. **Implement proper error handling** and logging
5. **Monitor cache statistics** to optimize hit rates
6. **Use async/await** for better concurrency
7. **Separate concerns** with service classes
8. **Test with realistic data** before production deployment

---

## Troubleshooting

See `docs/LOGIC_TROUBLESHOOTING.md` for common issues and solutions.
