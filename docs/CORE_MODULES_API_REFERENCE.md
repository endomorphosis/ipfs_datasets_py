# Core Modules API Reference

**Version:** 1.0  
**Date:** 2026-02-18  
**Status:** Complete

## Overview

This document provides comprehensive API reference for the core modules extracted during Phase 4 refactoring. These modules are framework-independent and can be used in any Python application.

---

## Testing Module

**Package:** `ipfs_datasets_py.testing`  
**Location:** `ipfs_datasets_py/testing/`

### Classes

#### TestResult

Individual test result dataclass.

```python
@dataclass
class TestResult:
    """Individual test result."""
    name: str                      # Test name
    status: str                    # 'passed', 'failed', 'skipped', 'error'
    duration: float                # Execution time in seconds
    message: Optional[str] = None  # Error/skip message
    file_path: Optional[str] = None  # Test file path
    line_number: Optional[int] = None  # Line number in file
```

**Example:**
```python
result = TestResult(
    name="test_user_authentication",
    status="passed",
    duration=0.152,
    file_path="tests/test_auth.py",
    line_number=42
)
```

#### TestSuiteResult

Test suite execution results.

```python
@dataclass
class TestSuiteResult:
    """Results from a test suite run."""
    suite_name: str                          # Suite identifier
    tool: str                                # 'pytest', 'unittest', 'mypy', 'flake8'
    status: str                              # 'passed', 'failed', 'error'
    total_tests: int                         # Total test count
    passed: int                              # Passed count
    failed: int                              # Failed count
    skipped: int                             # Skipped count
    errors: int                              # Error count
    duration: float                          # Total duration in seconds
    coverage_percentage: Optional[float] = None  # Code coverage %
    tests: List[TestResult] = None          # Individual test results
    output: str = ""                         # Raw output
```

**Example:**
```python
suite_result = TestSuiteResult(
    suite_name="authentication_tests",
    tool="pytest",
    status="passed",
    total_tests=25,
    passed=24,
    failed=1,
    skipped=0,
    errors=0,
    duration=3.45,
    coverage_percentage=87.5
)
```

#### TestRunSummary

Complete test run summary with multiple suites.

```python
@dataclass
class TestRunSummary:
    """Complete test run summary."""
    timestamp: str                                    # ISO format timestamp
    project_path: str                                 # Project root path
    total_suites: int                                 # Total suite count
    suites_passed: int                                # Passed suite count
    suites_failed: int                                # Failed suite count
    total_duration: float                             # Total duration
    overall_status: str                               # 'passed', 'failed', 'error'
    suites: List[TestSuiteResult]                    # Suite results
    coverage_report: Optional[Dict[str, Any]] = None  # Coverage details
```

#### TestExecutor

Core test execution engine.

```python
class TestExecutor:
    """Core test execution functionality."""
    
    def __init__(self):
        """Initialize test executor with configuration."""
        ...
    
    def run_pytest(
        self,
        path: Path,
        coverage: bool = True,
        verbose: bool = False
    ) -> TestSuiteResult:
        """
        Run pytest test suite.
        
        Args:
            path: Test directory or file path
            coverage: Enable coverage reporting
            verbose: Enable verbose output
            
        Returns:
            TestSuiteResult with execution details
            
        Example:
            executor = TestExecutor()
            result = executor.run_pytest(
                Path("./tests"),
                coverage=True,
                verbose=True
            )
            print(f"Passed: {result.passed}/{result.total_tests}")
        """
        ...
    
    def run_unittest(
        self,
        path: Path,
        verbose: bool = False
    ) -> TestSuiteResult:
        """
        Run unittest test suite.
        
        Args:
            path: Test directory path
            verbose: Enable verbose output
            
        Returns:
            TestSuiteResult with execution details
        """
        ...
    
    def run_mypy(self, path: Path) -> TestSuiteResult:
        """
        Run mypy type checking.
        
        Args:
            path: Source directory path
            
        Returns:
            TestSuiteResult with type check results
            
        Example:
            result = executor.run_mypy(Path("./src"))
            if result.status == "failed":
                print(f"Type errors found: {result.failed}")
        """
        ...
    
    def run_flake8(self, path: Path) -> TestSuiteResult:
        """
        Run flake8 linting.
        
        Args:
            path: Source directory path
            
        Returns:
            TestSuiteResult with linting results
        """
        ...
```

#### DatasetTestRunner

Specialized runner for dataset-related tests.

```python
class DatasetTestRunner:
    """Specialized test runner for dataset-related functionality."""
    
    def __init__(self):
        """Initialize dataset test runner."""
        ...
    
    def run_dataset_integrity_tests(self, path: Path) -> TestSuiteResult:
        """
        Run dataset integrity and validation tests.
        
        Automatically discovers and runs tests matching:
        - **/test*dataset*.py
        - **/test*ipfs*.py
        
        Args:
            path: Project root path
            
        Returns:
            TestSuiteResult with dataset test results
            
        Example:
            runner = DatasetTestRunner()
            result = runner.run_dataset_integrity_tests(Path("."))
            print(f"Dataset tests: {result.status}")
        """
        ...
```

---

## Indexing Module

**Package:** `ipfs_datasets_py.indexing`  
**Location:** `ipfs_datasets_py/indexing/`

### Enums

#### IndexType

```python
class IndexType(Enum):
    """Index type enumeration."""
    VECTOR = "vector"       # Vector/embedding index
    TEXT = "text"           # Full-text search index
    HYBRID = "hybrid"       # Combined vector + text
    GRAPH = "graph"         # Graph structure index
    TEMPORAL = "temporal"   # Time-series index
```

#### IndexStatus

```python
class IndexStatus(Enum):
    """Index status enumeration."""
    ACTIVE = "active"       # Operational
    LOADING = "loading"     # Loading data
    REBUILDING = "rebuilding"  # Rebuilding index
    ERROR = "error"         # Error state
    ARCHIVED = "archived"   # Archived/inactive
```

#### ShardingStrategy

```python
class ShardingStrategy(Enum):
    """Sharding strategy enumeration."""
    NONE = "none"           # No sharding
    HASH = "hash"           # Hash-based sharding
    RANGE = "range"         # Range-based sharding
    GEOGRAPHIC = "geographic"  # Geography-based sharding
    TEMPORAL = "temporal"   # Time-based sharding
```

### Classes

#### IndexManagerCore

Core index management functionality.

```python
class IndexManagerCore:
    """Core index management functionality."""
    
    def load_index(
        self,
        index_path: str,
        index_type: IndexType,
        force_rebuild: bool = False
    ) -> Dict[str, Any]:
        """
        Load an index from disk.
        
        Args:
            index_path: Path to index file
            index_type: Type of index (IndexType enum)
            force_rebuild: Force index rebuild if True
            
        Returns:
            Dictionary with index information:
            {
                'index_id': str,
                'index_type': str,
                'status': str,
                'index_size_mb': float,
                'document_count': int,
                'last_updated': str,
                'metadata': dict
            }
            
        Example:
            manager = IndexManagerCore()
            index = manager.load_index(
                "/data/embeddings.faiss",
                IndexType.VECTOR,
                force_rebuild=False
            )
            print(f"Loaded index: {index['index_id']}")
            print(f"Documents: {index['document_count']}")
        """
        ...
    
    def manage_shards(
        self,
        index_id: str,
        operation: str,
        strategy: ShardingStrategy,
        num_shards: int = 1
    ) -> Dict[str, Any]:
        """
        Manage index sharding.
        
        Args:
            index_id: Index identifier
            operation: 'create', 'rebalance', 'merge', 'split'
            strategy: Sharding strategy (ShardingStrategy enum)
            num_shards: Number of shards
            
        Returns:
            Dictionary with sharding details:
            {
                'index_id': str,
                'operation': str,
                'strategy': str,
                'num_shards': int,
                'shard_sizes_mb': List[float],
                'rebalance_needed': bool
            }
            
        Example:
            shard_info = manager.manage_shards(
                index_id="idx_123",
                operation="create",
                strategy=ShardingStrategy.HASH,
                num_shards=4
            )
        """
        ...
    
    def monitor_index_status(self, index_id: str) -> Dict[str, Any]:
        """
        Get current index status and metrics.
        
        Args:
            index_id: Index identifier
            
        Returns:
            Dictionary with status information:
            {
                'index_id': str,
                'status': str,
                'documents_indexed': int,
                'index_size_mb': float,
                'query_rate_per_sec': float,
                'avg_query_latency_ms': float,
                'last_updated': str,
                'error_message': Optional[str]
            }
            
        Example:
            status = manager.monitor_index_status("idx_123")
            print(f"Status: {status['status']}")
            print(f"Query rate: {status['query_rate_per_sec']:.2f} qps")
        """
        ...
    
    def manage_index_configuration(
        self,
        index_id: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update index configuration.
        
        Args:
            index_id: Index identifier
            config: Configuration dictionary with keys:
                - cache_size_mb: int
                - query_timeout_sec: int
                - enable_compression: bool
                - max_results: int
                - similarity_threshold: float
                
        Returns:
            Updated configuration dictionary
            
        Example:
            new_config = manager.manage_index_configuration(
                "idx_123",
                {
                    'cache_size_mb': 2048,
                    'query_timeout_sec': 30,
                    'enable_compression': True
                }
            )
        """
        ...
```

---

## Medical Scrapers Module

**Package:** `ipfs_datasets_py.scrapers.medical`  
**Location:** `ipfs_datasets_py/scrapers/medical/`

### Classes

#### MedicalResearchCore

PubMed and clinical trials scraping.

```python
class MedicalResearchCore:
    """Core medical research scraping functionality."""
    
    def search_pubmed(
        self,
        query: str,
        max_results: int = 100,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search PubMed for scientific papers.
        
        Args:
            query: Search query string
            max_results: Maximum number of results
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            
        Returns:
            Dictionary with search results:
            {
                'query': str,
                'total_results': int,
                'results': List[Dict] with keys:
                    - pmid: str
                    - title: str
                    - authors: List[str]
                    - abstract: str
                    - journal: str
                    - publication_date: str
                    - doi: str
                    - keywords: List[str]
            }
            
        Example:
            research = MedicalResearchCore()
            papers = research.search_pubmed(
                "machine learning drug discovery",
                max_results=50,
                date_from="2023-01-01"
            )
            for paper in papers['results']:
                print(f"{paper['title']} ({paper['publication_date']})")
        """
        ...
    
    def scrape_clinical_trials(
        self,
        condition: str,
        intervention: Optional[str] = None,
        status: str = "recruiting"
    ) -> Dict[str, Any]:
        """
        Scrape clinical trials data.
        
        Args:
            condition: Medical condition
            intervention: Intervention type (optional)
            status: Trial status ('recruiting', 'completed', 'all')
            
        Returns:
            Dictionary with trial results
            
        Example:
            trials = research.scrape_clinical_trials(
                condition="Type 2 Diabetes",
                intervention="metformin",
                status="completed"
            )
        """
        ...
```

#### MedicalTheoremCore

Medical theorem generation and validation.

```python
class MedicalTheoremCore:
    """Medical theorem generation and validation."""
    
    def generate_theorem(
        self,
        hypothesis: str,
        evidence_papers: List[Dict]
    ) -> Dict[str, Any]:
        """
        Generate medical theorem from hypothesis and evidence.
        
        Args:
            hypothesis: Medical hypothesis statement
            evidence_papers: List of supporting papers
            
        Returns:
            Dictionary with theorem:
            {
                'statement': str,
                'hypothesis': str,
                'confidence_score': float,
                'supporting_evidence': List[Dict],
                'contradicting_evidence': List[Dict],
                'validation_status': str
            }
            
        Example:
            theorem_gen = MedicalTheoremCore()
            theorem = theorem_gen.generate_theorem(
                "Vitamin D reduces COVID-19 severity",
                evidence_papers=papers_list
            )
            print(f"Confidence: {theorem['confidence_score']:.2%}")
        """
        ...
```

#### BiomoleculeDiscoveryCore

Protein binders and enzyme inhibitors discovery.

```python
class BiomoleculeDiscoveryCore:
    """Biomolecule discovery and analysis."""
    
    def find_protein_binders(
        self,
        target_protein: str,
        binding_affinity_threshold: float = -8.0
    ) -> List[Dict[str, Any]]:
        """
        Find potential protein binders.
        
        Args:
            target_protein: Target protein name or ID
            binding_affinity_threshold: Minimum affinity (kcal/mol)
            
        Returns:
            List of potential binders:
            [{
                'smiles': str,
                'binding_affinity': float,
                'confidence': float,
                'protein_id': str
            }]
            
        Example:
            discovery = BiomoleculeDiscoveryCore()
            binders = discovery.find_protein_binders(
                "ACE2",
                binding_affinity_threshold=-9.0
            )
        """
        ...
    
    def find_enzyme_inhibitors(
        self,
        enzyme: str,
        ic50_threshold: float = 100.0
    ) -> List[Dict[str, Any]]:
        """
        Find potential enzyme inhibitors.
        
        Args:
            enzyme: Enzyme name or ID
            ic50_threshold: Maximum IC50 (nM)
            
        Returns:
            List of potential inhibitors
            
        Example:
            inhibitors = discovery.find_enzyme_inhibitors(
                "tau protein kinase",
                ic50_threshold=50.0
            )
        """
        ...
```

#### AIDatasetBuilderCore

AI-powered dataset generation.

```python
class AIDatasetBuilderCore:
    """AI dataset builder for medical research."""
    
    def build_ai_dataset(
        self,
        task_type: str,
        data_sources: Dict[str, List],
        output_format: str = "huggingface"
    ) -> Dict[str, Any]:
        """
        Build AI training dataset from medical data.
        
        Args:
            task_type: 'drug_discovery', 'diagnosis', 'prognosis'
            data_sources: Dictionary of data sources
            output_format: 'huggingface', 'tensorflow', 'pytorch'
            
        Returns:
            Dataset information dictionary
            
        Example:
            builder = AIDatasetBuilderCore()
            dataset = builder.build_ai_dataset(
                task_type="drug_discovery",
                data_sources={
                    'papers': pubmed_results,
                    'trials': clinical_trials,
                    'molecules': compounds
                },
                output_format="huggingface"
            )
        """
        ...
```

---

## P2P Monitoring

**Package:** `ipfs_datasets_py.mcp_server.monitoring`  
**Location:** `ipfs_datasets_py/mcp_server/monitoring.py`

### Classes

#### P2PMetricsCollector

P2P-specific metrics collection and monitoring.

```python
class P2PMetricsCollector:
    """P2P-specific metrics collector."""
    
    def __init__(self, base_collector: Optional[EnhancedMetricsCollector] = None):
        """
        Initialize P2P metrics collector.
        
        Args:
            base_collector: Base metrics collector (optional)
        """
        ...
    
    def track_peer_discovery(
        self,
        source: str,
        peers_found: int,
        success: bool,
        duration_ms: Optional[float] = None
    ) -> None:
        """
        Track peer discovery operation.
        
        Args:
            source: Discovery source ('github_issues', 'dht', 'local_file')
            peers_found: Number of peers discovered
            success: Whether discovery succeeded
            duration_ms: Operation duration in milliseconds
            
        Example:
            collector = P2PMetricsCollector()
            collector.track_peer_discovery(
                source="github_issues",
                peers_found=5,
                success=True,
                duration_ms=120.5
            )
        """
        ...
    
    def track_workflow_execution(
        self,
        workflow_id: str,
        status: str,
        execution_time_ms: Optional[float] = None
    ) -> None:
        """
        Track workflow execution.
        
        Args:
            workflow_id: Workflow identifier
            status: 'running', 'completed', 'failed'
            execution_time_ms: Execution time in milliseconds
            
        Example:
            collector.track_workflow_execution(
                workflow_id="etl_pipeline",
                status="completed",
                execution_time_ms=5200.0
            )
        """
        ...
    
    def track_bootstrap_operation(
        self,
        method: str,
        success: bool,
        duration_ms: Optional[float] = None
    ) -> None:
        """
        Track bootstrap operation.
        
        Args:
            method: Bootstrap method ('ipfs_nodes', 'file_based', 'environment')
            success: Whether bootstrap succeeded
            duration_ms: Operation duration in milliseconds
        """
        ...
    
    def get_dashboard_data(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Get P2P metrics formatted for dashboard display.
        
        Results are cached for 30 seconds to reduce overhead.
        
        Args:
            force_refresh: Force cache refresh
            
        Returns:
            Dashboard data dictionary with peer_discovery,
            workflows, and bootstrap sections
            
        Example:
            dashboard = collector.get_dashboard_data()
            print(f"Success rate: {dashboard['peer_discovery']['success_rate']}%")
        """
        ...
    
    def get_alert_conditions(self) -> List[Dict[str, Any]]:
        """
        Check for P2P-specific alert conditions.
        
        Returns:
            List of alert dictionaries
            
        Example:
            alerts = collector.get_alert_conditions()
            for alert in alerts:
                if alert['type'] == 'critical':
                    print(f"CRITICAL: {alert['message']}")
        """
        ...
```

### Functions

```python
def get_p2p_metrics_collector() -> P2PMetricsCollector:
    """
    Get or create global P2P metrics collector instance.
    
    Returns:
        P2PMetricsCollector singleton instance
        
    Example:
        collector = get_p2p_metrics_collector()
        collector.track_peer_discovery(...)
    """
    ...
```

---

## Usage Patterns

### Pattern 1: Comprehensive Testing

```python
from pathlib import Path
from ipfs_datasets_py.testing import TestExecutor, DatasetTestRunner, TestRunSummary

def run_full_test_suite(project_path: Path) -> TestRunSummary:
    """Run complete test suite."""
    executor = TestExecutor()
    dataset_runner = DatasetTestRunner()
    
    results = []
    
    # Unit tests
    results.append(executor.run_pytest(project_path / "tests/unit"))
    
    # Integration tests
    results.append(executor.run_pytest(project_path / "tests/integration"))
    
    # Type checking
    results.append(executor.run_mypy(project_path / "src"))
    
    # Linting
    results.append(executor.run_flake8(project_path / "src"))
    
    # Dataset tests
    results.append(dataset_runner.run_dataset_integrity_tests(project_path))
    
    # Create summary
    summary = TestRunSummary(
        timestamp=datetime.utcnow().isoformat(),
        project_path=str(project_path),
        total_suites=len(results),
        suites_passed=sum(1 for r in results if r.status == "passed"),
        suites_failed=sum(1 for r in results if r.status != "passed"),
        total_duration=sum(r.duration for r in results),
        overall_status="passed" if all(r.status == "passed" for r in results) else "failed",
        suites=results
    )
    
    return summary
```

### Pattern 2: Index Management Pipeline

```python
from ipfs_datasets_py.indexing import IndexManagerCore, IndexType, ShardingStrategy

def setup_large_scale_index(data_path: str) -> str:
    """Set up sharded index for large dataset."""
    manager = IndexManagerCore()
    
    # Load index
    index = manager.load_index(data_path, IndexType.VECTOR)
    index_id = index['index_id']
    
    # Create shards for large dataset
    if index['document_count'] > 1000000:
        manager.manage_shards(
            index_id,
            operation="create",
            strategy=ShardingStrategy.HASH,
            num_shards=8
        )
    
    # Optimize configuration
    manager.manage_index_configuration(
        index_id,
        {
            'cache_size_mb': 4096,
            'query_timeout_sec': 60,
            'enable_compression': True
        }
    )
    
    return index_id
```

### Pattern 3: Medical Research Pipeline

```python
from ipfs_datasets_py.scrapers.medical import (
    MedicalResearchCore,
    MedicalTheoremCore,
    BiomoleculeDiscoveryCore
)

def research_drug_target(condition: str, target: str):
    """Complete drug discovery research pipeline."""
    research = MedicalResearchCore()
    theorem_gen = MedicalTheoremCore()
    discovery = BiomoleculeDiscoveryCore()
    
    # Gather evidence
    papers = research.search_pubmed(f"{condition} {target}", max_results=100)
    trials = research.scrape_clinical_trials(condition)
    
    # Generate theorem
    theorem = theorem_gen.generate_theorem(
        f"{target} modulation treats {condition}",
        papers['results'] + trials['results']
    )
    
    # Discover molecules
    if theorem['confidence_score'] > 0.7:
        inhibitors = discovery.find_enzyme_inhibitors(target)
        return {
            'theorem': theorem,
            'candidates': inhibitors[:10]
        }
    
    return None
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-18  
**Status:** Complete
