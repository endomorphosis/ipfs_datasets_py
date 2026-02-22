"""Tests for OntologyOptimizer export stubs and LogicValidator TDFOL cache."""
import pytest


@pytest.fixture
def sample_ontology():
    return {
        "entities": [
            {"id": "e1", "text": "Alice", "type": "Person"},
            {"id": "e2", "text": "Wonderland", "type": "Place"},
        ],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "visits"},
        ],
    }


# ── GraphML export ───────────────────────────────────────────────────────────

class TestExportToGraphML:
    @pytest.fixture
    def optimizer(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
        return OntologyOptimizer()

    def test_returns_string(self, optimizer, sample_ontology):
        result = optimizer.export_to_graphml(ontology=sample_ontology)
        assert isinstance(result, str)

    def test_graphml_header(self, optimizer, sample_ontology):
        result = optimizer.export_to_graphml(ontology=sample_ontology)
        assert result.startswith("<?xml")
        assert "graphml" in result

    def test_entities_in_output(self, optimizer, sample_ontology):
        result = optimizer.export_to_graphml(ontology=sample_ontology)
        assert 'id="e1"' in result
        assert "Alice" in result

    def test_edge_in_output(self, optimizer, sample_ontology):
        result = optimizer.export_to_graphml(ontology=sample_ontology)
        assert 'source="e1"' in result
        assert 'target="e2"' in result

    def test_empty_ontology(self, optimizer):
        result = optimizer.export_to_graphml(ontology={})
        assert "graphml" in result

    def test_writes_to_file(self, optimizer, sample_ontology, tmp_path):
        path = str(tmp_path / "out.graphml")
        ret = optimizer.export_to_graphml(ontology=sample_ontology, filepath=path)
        assert ret is None
        with open(path) as fh:
            content = fh.read()
        assert "Alice" in content


# ── RDF export ───────────────────────────────────────────────────────────────

class TestExportToRDF:
    @pytest.fixture
    def optimizer(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
        return OntologyOptimizer()

    def test_raises_on_missing_rdflib(self, optimizer, sample_ontology, monkeypatch):
        import sys
        monkeypatch.setitem(sys.modules, "rdflib", None)
        with pytest.raises((ImportError, TypeError)):
            optimizer.export_to_rdf(ontology=sample_ontology)

    def test_works_with_rdflib(self, optimizer, sample_ontology):
        rdflib = pytest.importorskip("rdflib")
        result = optimizer.export_to_rdf(ontology=sample_ontology)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_writes_to_file_with_rdflib(self, optimizer, sample_ontology, tmp_path):
        pytest.importorskip("rdflib")
        path = str(tmp_path / "out.ttl")
        ret = optimizer.export_to_rdf(ontology=sample_ontology, filepath=path)
        assert ret is None
        with open(path) as fh:
            content = fh.read()
        assert len(content) > 0


# ── TDFOL cache ──────────────────────────────────────────────────────────────

class TestTDFOLCache:
    @pytest.fixture
    def validator(self):
        from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
        return LogicValidator(use_cache=True)

    @pytest.fixture
    def no_cache_validator(self):
        from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
        return LogicValidator(use_cache=False)

    def test_cache_hit_returns_same_result(self, validator, sample_ontology):
        f1 = validator.ontology_to_tdfol(sample_ontology)
        f2 = validator.ontology_to_tdfol(sample_ontology)
        assert f1 == f2

    def test_cache_populated_after_first_call(self, validator, sample_ontology):
        assert validator._cache is not None
        assert len(validator._cache) == 0
        validator.ontology_to_tdfol(sample_ontology)
        assert len(validator._cache) == 1

    def test_different_ontologies_different_cache_entries(self, validator):
        ont1 = {"entities": [{"id": "a", "type": "X", "text": "a"}], "relationships": []}
        ont2 = {"entities": [{"id": "b", "type": "Y", "text": "b"}], "relationships": []}
        validator.ontology_to_tdfol(ont1)
        validator.ontology_to_tdfol(ont2)
        assert len(validator._cache) == 2

    def test_no_cache_validator_has_none_cache(self, no_cache_validator, sample_ontology):
        assert no_cache_validator._cache is None
        result = no_cache_validator.ontology_to_tdfol(sample_ontology)
        assert isinstance(result, list)

    def test_cache_key_is_deterministic(self, validator, sample_ontology):
        k1 = validator._get_cache_key(sample_ontology)
        k2 = validator._get_cache_key(sample_ontology)
        assert k1 == k2 and len(k1) == 64  # SHA-256 hex digest


# ── optimizers.__version__ ───────────────────────────────────────────────────

class TestOptimizersVersion:
    def test_version_importable(self):
        from ipfs_datasets_py.optimizers import __version__
        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_version_matches_package(self):
        from ipfs_datasets_py.optimizers import __version__ as opt_ver
        from ipfs_datasets_py import __version__ as pkg_ver
        assert opt_ver == pkg_ver


# ── clear_tdfol_cache ────────────────────────────────────────────────────────

class TestClearTDFOLCache:
    @pytest.fixture
    def validator(self):
        from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
        return LogicValidator(use_cache=True)

    def test_clear_returns_count(self, validator, sample_ontology):
        validator.ontology_to_tdfol(sample_ontology)
        n = validator.clear_tdfol_cache()
        assert n == 1

    def test_clear_empties_cache(self, validator, sample_ontology):
        validator.ontology_to_tdfol(sample_ontology)
        validator.clear_tdfol_cache()
        assert len(validator._cache) == 0

    def test_clear_on_empty_cache_returns_zero(self, validator):
        assert validator.clear_tdfol_cache() == 0

    def test_clear_on_no_cache_validator_returns_zero(self):
        from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
        v = LogicValidator(use_cache=False)
        assert v.clear_tdfol_cache() == 0


# ── OntologyCritic.dimension_weights ─────────────────────────────────────────

class TestDimensionWeights:
    def test_returns_dict(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        c = OntologyCritic()
        assert isinstance(c.dimension_weights, dict)

    def test_all_five_dimensions_present(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        c = OntologyCritic()
        w = c.dimension_weights
        for dim in ("completeness", "consistency", "clarity", "granularity", "domain_alignment"):
            assert dim in w, f"Missing dimension: {dim}"

    def test_weights_sum_to_one(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        c = OntologyCritic()
        assert sum(c.dimension_weights.values()) == pytest.approx(1.0, abs=1e-6)

    def test_is_copy_not_mutable_reference(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, DIMENSION_WEIGHTS
        c = OntologyCritic()
        w = c.dimension_weights
        w["completeness"] = 999.0
        assert DIMENSION_WEIGHTS["completeness"] != 999.0
