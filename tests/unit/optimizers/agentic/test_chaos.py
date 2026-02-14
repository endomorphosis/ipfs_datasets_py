"""Test suite for chaos engineering optimizer."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import ast

from ipfs_datasets_py.optimizers.agentic.methods.chaos import (
    ChaosOptimizer,
    FaultType,
    Vulnerability,
    ResilienceReport,
)
from ipfs_datasets_py.optimizers.agentic.base import (
    OptimizationTask,
    OptimizationResult,
)


class TestFaultType:
    """Test FaultType enum."""
    
    def test_fault_types(self):
        """Test all fault types are defined."""
        assert FaultType.NETWORK_TIMEOUT.value == "network_timeout"
        assert FaultType.NETWORK_ERROR.value == "network_error"
        assert FaultType.RESOURCE_EXHAUSTION.value == "resource_exhaustion"
        assert FaultType.NULL_INPUT.value == "null_input"
        assert FaultType.EMPTY_INPUT.value == "empty_input"
        assert FaultType.MALFORMED_INPUT.value == "malformed_input"


class TestVulnerability:
    """Test Vulnerability dataclass."""
    
    def test_vulnerability_creation(self):
        """Test creating a vulnerability."""
        vuln = Vulnerability(
            type=FaultType.NETWORK_TIMEOUT,
            location="line 10",
            description="No timeout handling",
            severity="high",
            suggested_fix="Add timeout parameter",
        )
        assert vuln.type == FaultType.NETWORK_TIMEOUT
        assert vuln.location == "line 10"
        assert vuln.severity == "high"
        assert "timeout" in vuln.suggested_fix


class TestResilienceReport:
    """Test ResilienceReport dataclass."""
    
    def test_report_creation(self):
        """Test creating resilience report."""
        vulnerabilities = [
            Vulnerability(
                FaultType.NULL_INPUT,
                "line 5",
                "No null check",
                "medium",
                "Add null check",
            )
        ]
        report = ResilienceReport(
            vulnerabilities=vulnerabilities,
            resilience_score=0.75,
            total_faults_injected=10,
            failures_detected=3,
        )
        assert len(report.vulnerabilities) == 1
        assert report.resilience_score == 0.75
        assert report.total_faults_injected == 10
        assert report.failures_detected == 3
    
    def test_report_score_calculation(self):
        """Test resilience score calculation."""
        report = ResilienceReport([], 0.8, 20, 4)
        # Score should be (20-4)/20 = 0.8
        assert report.resilience_score == 0.8


class TestChaosOptimizer:
    """Test ChaosOptimizer class."""
    
    @pytest.fixture
    def mock_llm_router(self):
        """Create mock LLM router."""
        router = Mock()
        router.generate = Mock(return_value="Fixed code with error handling")
        router.extract_code = Mock(return_value="def safe(): try: pass\nexcept: pass")
        return router
    
    @pytest.fixture
    def optimizer(self, mock_llm_router):
        """Create chaos optimizer instance."""
        return ChaosOptimizer(
            llm_router=mock_llm_router,
            fault_types=[
                FaultType.NETWORK_TIMEOUT,
                FaultType.NULL_INPUT,
                FaultType.EMPTY_INPUT,
            ],
        )
    
    @pytest.fixture
    def sample_task(self):
        """Create sample optimization task."""
        return OptimizationTask(
            task_id="task-1",
            target_files=["test.py"],
            description="Improve resilience",
            priority=70,
        )
    
    def test_init(self, mock_llm_router):
        """Test optimizer initialization."""
        optimizer = ChaosOptimizer(
            llm_router=mock_llm_router,
            fault_types=[FaultType.NETWORK_ERROR],
        )
        assert optimizer.llm_router == mock_llm_router
        assert len(optimizer.fault_types) == 1
        assert FaultType.NETWORK_ERROR in optimizer.fault_types
    
    def test_init_all_faults(self, mock_llm_router):
        """Test initialization with all fault types."""
        optimizer = ChaosOptimizer(llm_router=mock_llm_router)
        # Should have all 10 fault types by default
        assert len(optimizer.fault_types) >= 10
    
    def test_analyze_vulnerabilities(self, optimizer):
        """Test vulnerability analysis."""
        code = """
def fetch_data(url):
    response = requests.get(url)
    return response.json()
"""
        vulnerabilities = optimizer.analyze_vulnerabilities(code)
        
        assert isinstance(vulnerabilities, list)
        # Should detect network call without timeout
        assert any(v.type == FaultType.NETWORK_TIMEOUT for v in vulnerabilities)
    
    def test_analyze_vulnerabilities_null_input(self, optimizer):
        """Test detection of missing null checks."""
        code = """
def process(data):
    return data.upper()  # No null check
"""
        vulnerabilities = optimizer.analyze_vulnerabilities(code)
        
        # Should detect potential null input issue
        assert any(v.type == FaultType.NULL_INPUT for v in vulnerabilities)
    
    def test_analyze_vulnerabilities_empty_input(self, optimizer):
        """Test detection of missing empty checks."""
        code = """
def get_first(items):
    return items[0]  # No empty check
"""
        vulnerabilities = optimizer.analyze_vulnerabilities(code)
        
        # Should detect potential empty input issue
        assert any(v.type == FaultType.EMPTY_INPUT for v in vulnerabilities)
    
    def test_inject_fault_network_timeout(self, optimizer):
        """Test injecting network timeout fault."""
        code = """
def fetch():
    response = requests.get("http://example.com")
    return response
"""
        faulty_code = optimizer.inject_fault(code, FaultType.NETWORK_TIMEOUT)
        
        assert isinstance(faulty_code, str)
        # Should have modified the code to simulate timeout
        assert "timeout" in faulty_code.lower() or "sleep" in faulty_code.lower()
    
    def test_inject_fault_null_input(self, optimizer):
        """Test injecting null input."""
        code = """
def process(data):
    return data.strip()
"""
        faulty_code = optimizer.inject_fault(code, FaultType.NULL_INPUT)
        
        assert isinstance(faulty_code, str)
        assert "None" in faulty_code or "null" in faulty_code.lower()
    
    def test_inject_fault_empty_input(self, optimizer):
        """Test injecting empty input."""
        code = """
def sum_list(items):
    return sum(items)
"""
        faulty_code = optimizer.inject_fault(code, FaultType.EMPTY_INPUT)
        
        assert isinstance(faulty_code, str)
        assert "[]" in faulty_code or "empty" in faulty_code.lower()
    
    def test_execute_with_fault(self, optimizer):
        """Test executing code with injected fault."""
        code = """
def safe_division(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return 0
"""
        fault_type = FaultType.RESOURCE_EXHAUSTION
        
        result = optimizer.execute_with_fault(code, fault_type, timeout=2)
        
        assert isinstance(result, dict)
        assert "success" in result
        assert "error" in result
        assert "execution_time" in result
    
    def test_execute_with_fault_timeout(self, optimizer):
        """Test execution timeout handling."""
        infinite_loop = """
while True:
    pass
"""
        result = optimizer.execute_with_fault(
            infinite_loop,
            FaultType.CPU_SPIKE,
            timeout=1,
        )
        
        assert result["success"] is False
        assert "timeout" in result["error"].lower() or "time" in result["error"].lower()
    
    def test_generate_fix(self, optimizer):
        """Test generating fix for vulnerability."""
        vulnerability = Vulnerability(
            type=FaultType.NETWORK_TIMEOUT,
            location="line 10",
            description="Missing timeout in network call",
            severity="high",
            suggested_fix="Add timeout parameter",
        )
        code = "response = requests.get(url)"
        
        fixed_code = optimizer.generate_fix(code, vulnerability)
        
        assert isinstance(fixed_code, str)
        assert len(fixed_code) > 0
        assert optimizer.llm_router.generate.called
    
    def test_generate_fix_multiple_vulnerabilities(self, optimizer):
        """Test generating fixes for multiple vulnerabilities."""
        vulns = [
            Vulnerability(FaultType.NULL_INPUT, "line 1", "No null check", "high", "Add check"),
            Vulnerability(FaultType.EMPTY_INPUT, "line 2", "No empty check", "medium", "Add check"),
        ]
        code = "def unsafe(data): return data[0]"
        
        for vuln in vulns:
            fixed = optimizer.generate_fix(code, vuln)
            assert isinstance(fixed, str)
    
    def test_verify_resilience(self, optimizer):
        """Test resilience verification."""
        code = """
def safe_process(data):
    if data is None:
        return None
    if not data:
        return []
    try:
        return [x.upper() for x in data]
    except AttributeError:
        return data
"""
        report = optimizer.verify_resilience(code)
        
        assert isinstance(report, ResilienceReport)
        assert report.resilience_score >= 0
        assert report.total_faults_injected > 0
        assert isinstance(report.vulnerabilities, list)
    
    def test_verify_resilience_poor_code(self, optimizer):
        """Test resilience of poor code."""
        bad_code = """
def unsafe(data):
    return data[0].upper()
"""
        report = optimizer.verify_resilience(bad_code)
        
        # Should find multiple vulnerabilities
        assert len(report.vulnerabilities) > 0
        # Score should be low
        assert report.resilience_score < 0.8
    
    def test_verify_resilience_good_code(self, optimizer):
        """Test resilience of well-protected code."""
        good_code = """
def safe(data):
    if data is None:
        raise ValueError("Data cannot be None")
    if not data:
        return []
    if not isinstance(data, list):
        return [data]
    try:
        return [x.upper() if isinstance(x, str) else str(x) for x in data]
    except Exception as e:
        print(f"Error: {e}")
        return []
"""
        report = optimizer.verify_resilience(good_code)
        
        # Should have few vulnerabilities
        # Score should be high
        assert report.resilience_score > 0.5
    
    def test_optimize_full_workflow(self, optimizer, sample_task):
        """Test complete chaos engineering optimization."""
        code = """
def fetch_and_process(url):
    response = requests.get(url)
    data = response.json()
    return data['items'][0]
"""
        with patch.object(optimizer, 'analyze_vulnerabilities') as mock_analyze:
            with patch.object(optimizer, 'generate_fix') as mock_fix:
                with patch.object(optimizer, 'verify_resilience') as mock_verify:
                    # Setup mocks
                    mock_analyze.return_value = [
                        Vulnerability(
                            FaultType.NETWORK_TIMEOUT,
                            "line 2",
                            "No timeout",
                            "high",
                            "Add timeout",
                        )
                    ]
                    mock_fix.return_value = "fixed code"
                    mock_verify.return_value = ResilienceReport(
                        vulnerabilities=[],
                        resilience_score=0.95,
                        total_faults_injected=10,
                        failures_detected=0,
                    )
                    
                    result = optimizer.optimize(task=sample_task, code=code)
        
        assert isinstance(result, OptimizationResult)
        assert result.success is True
        assert mock_analyze.called
        assert mock_fix.called
        assert mock_verify.called
    
    def test_optimize_no_vulnerabilities(self, optimizer, sample_task):
        """Test optimization when code is already resilient."""
        perfect_code = "def safe(): return 42"
        
        with patch.object(optimizer, 'analyze_vulnerabilities', return_value=[]):
            result = optimizer.optimize(task=sample_task, code=perfect_code)
        
        assert isinstance(result, OptimizationResult)
        # Should indicate no changes needed
        assert result.optimized_code == perfect_code or "no vulnerabilities" in result.description.lower()
    
    def test_fault_injection_coverage(self, optimizer):
        """Test that all fault types can be injected."""
        code = "def test(): pass"
        
        for fault_type in optimizer.fault_types:
            faulty_code = optimizer.inject_fault(code, fault_type)
            assert isinstance(faulty_code, str)
            assert len(faulty_code) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
