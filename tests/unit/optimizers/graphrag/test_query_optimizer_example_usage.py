from __future__ import annotations


def _install_example_usage_fakes(monkeypatch, qo):
    class _FakeStats:
        pass

    class _FakeBaseOptimizer:
        def __init__(self, query_stats=None):
            self.query_stats = query_stats

    class _FakeRewriter:
        def rewrite_query(self, original_query, graph_info):
            return {"original": original_query, "graph_info": graph_info}

    class _FakeBudgetManager:
        def allocate_budget(self, query, priority="normal"):
            return {"priority": priority, "max_nodes": 100}

        def track_consumption(self, *_args, **_kwargs):
            return None

        def get_current_consumption_report(self):
            return {"tracked": True}

    class _FakeUnifiedOptimizer:
        def __init__(self, rewriter=None, budget_manager=None, base_optimizer=None, graph_info=None):
            self.rewriter = rewriter
            self.budget_manager = budget_manager
            self.base_optimizer = base_optimizer
            self.graph_info = graph_info or {}
            self.visualizer = None
            self.last_query_id = None

        def get_execution_plan(self, query, priority="normal"):
            safe_query = dict(query)
            if "query_vector" in safe_query:
                safe_query["query_vector"] = "[vector]"
            return {
                "query": safe_query,
                "priority": priority,
                "optimization_applied": True,
                "execution_steps": [],
                "budget": {},
                "statistics": {},
                "caching": {},
            }

        def analyze_performance(self):
            return {"status": "ok"}

    monkeypatch.setattr(qo, "GraphRAGQueryStats", _FakeStats)
    monkeypatch.setattr(qo, "GraphRAGQueryOptimizer", _FakeBaseOptimizer)
    monkeypatch.setattr(qo, "QueryRewriter", _FakeRewriter)
    monkeypatch.setattr(qo, "QueryBudgetManager", _FakeBudgetManager)
    monkeypatch.setattr(qo, "UnifiedGraphRAGQueryOptimizer", _FakeUnifiedOptimizer)


def test_example_usage_handles_llm_processor_init_failure(monkeypatch, capsys):
    from ipfs_datasets_py.optimizers.graphrag import query_optimizer as qo

    class _FailingLLMProcessor:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("init failed")

    _install_example_usage_fakes(monkeypatch, qo)
    monkeypatch.setattr(qo, "GraphRAGLLMProcessor", _FailingLLMProcessor)
    monkeypatch.setattr(qo, "VISUALIZATION_AVAILABLE", False)

    result = qo.example_usage()
    captured = capsys.readouterr()

    assert result == "Example completed successfully"
    assert "Error instantiating GraphRAGLLMProcessor" in captured.out


def test_example_usage_handles_reasoning_failure(monkeypatch, capsys):
    from ipfs_datasets_py.optimizers.graphrag import query_optimizer as qo

    class _ProcessorWithReasoningFailure:
        def __init__(self, *args, **kwargs):
            pass

        def _format_connections_for_llm(self, connections, depth):
            return "mocked-connections"

        def synthesize_cross_document_reasoning(self, **kwargs):
            raise RuntimeError("reasoning failed")

    _install_example_usage_fakes(monkeypatch, qo)
    monkeypatch.setattr(qo, "GraphRAGLLMProcessor", _ProcessorWithReasoningFailure)
    monkeypatch.setattr(qo, "VISUALIZATION_AVAILABLE", False)

    result = qo.example_usage()
    captured = capsys.readouterr()

    assert result == "Example completed successfully"
    assert "Error during conceptual call to synthesize_cross_document_reasoning" in captured.out


def test_example_usage_successful_reasoning_path(monkeypatch, capsys):
    from ipfs_datasets_py.optimizers.graphrag import query_optimizer as qo

    class _SuccessfulProcessor:
        def __init__(self, *args, **kwargs):
            pass

        def _format_connections_for_llm(self, connections, depth):
            return "mocked-connections"

        def synthesize_cross_document_reasoning(self, **kwargs):
            return {"answer": "ok", "confidence": 0.9}

    _install_example_usage_fakes(monkeypatch, qo)
    monkeypatch.setattr(qo, "GraphRAGLLMProcessor", _SuccessfulProcessor)
    monkeypatch.setattr(qo, "VISUALIZATION_AVAILABLE", False)

    result = qo.example_usage()
    captured = capsys.readouterr()

    assert result == "Example completed successfully"
    assert "Reasoning Result (conceptual/mocked)" in captured.out
    assert "Consumption Report" in captured.out


def test_example_usage_survives_budget_allocate_failure_with_fallback(monkeypatch, capsys):
    from ipfs_datasets_py.optimizers.graphrag import query_optimizer as qo

    class _FakeStats:
        pass

    class _FakeBaseOptimizer:
        def __init__(self, query_stats=None):
            self.query_stats = query_stats

    class _FakeRewriter:
        def rewrite_query(self, original_query, graph_info):
            return {"original": original_query, "graph_info": graph_info}

    class _FlakyBudgetManager:
        def __init__(self):
            self.calls = 0

        def allocate_budget(self, query, priority="normal"):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("budget failure")
            return {"priority": priority, "max_nodes": 100}

        def track_consumption(self, *_args, **_kwargs):
            return None

        def get_current_consumption_report(self):
            return {"tracked": True}

    class _FallbackUnifiedOptimizer:
        def __init__(self, rewriter=None, budget_manager=None, base_optimizer=None, graph_info=None):
            self.rewriter = rewriter
            self.budget_manager = budget_manager
            self.base_optimizer = base_optimizer
            self.graph_info = graph_info or {}
            self.visualizer = None
            self.last_query_id = None

        def get_execution_plan(self, query, priority="normal"):
            safe_query = dict(query)
            if "query_vector" in safe_query:
                safe_query["query_vector"] = "[vector]"
            try:
                budget = self.budget_manager.allocate_budget(safe_query, priority)
            except RuntimeError:
                budget = {"fallback": True, "max_nodes": 10}
            return {
                "query": safe_query,
                "priority": priority,
                "optimization_applied": True,
                "execution_steps": [],
                "budget": budget,
                "statistics": {},
                "caching": {},
            }

        def analyze_performance(self):
            return {"status": "ok"}

    class _FailingLLMProcessor:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("init failed")

    monkeypatch.setattr(qo, "GraphRAGQueryStats", _FakeStats)
    monkeypatch.setattr(qo, "GraphRAGQueryOptimizer", _FakeBaseOptimizer)
    monkeypatch.setattr(qo, "QueryRewriter", _FakeRewriter)
    monkeypatch.setattr(qo, "QueryBudgetManager", _FlakyBudgetManager)
    monkeypatch.setattr(qo, "UnifiedGraphRAGQueryOptimizer", _FallbackUnifiedOptimizer)
    monkeypatch.setattr(qo, "GraphRAGLLMProcessor", _FailingLLMProcessor)
    monkeypatch.setattr(qo, "VISUALIZATION_AVAILABLE", False)

    result = qo.example_usage()
    captured = capsys.readouterr()

    assert result == "Example completed successfully"
    assert "Execution Plan" in captured.out
