"""
Tests for the Logic Module REST API server.

Tests the FastAPI endpoints using the TestClient to verify:
- Health and capabilities endpoints
- Prove endpoint with TDFOL
- Convert endpoints (FOL, DCEC)
- Parse endpoint
- Error handling
"""

import pytest

try:
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="FastAPI not installed - skipping REST API tests",
)


@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the logic API server."""
    from ipfs_datasets_py.logic.api_server import create_app
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_200(self, client):
        """
        GIVEN the API server is running
        WHEN GET /health is called
        THEN should return 200 OK.
        """
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self, client):
        """
        GIVEN the API server is running
        WHEN GET /health is called
        THEN response body should contain status: ok.
        """
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "ok"

    def test_health_includes_module_status(self, client):
        """
        GIVEN the API server is running
        WHEN GET /health is called
        THEN response should include module availability flags.
        """
        response = client.get("/health")
        data = response.json()
        assert "modules" in data
        assert "fastapi" in data["modules"]
        assert data["modules"]["fastapi"] is True

    def test_health_includes_uptime(self, client):
        """
        GIVEN the API server is running
        WHEN GET /health is called
        THEN response should include uptime_seconds.
        """
        response = client.get("/health")
        data = response.json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0

    def test_health_includes_version(self, client):
        """
        GIVEN the API server is running
        WHEN GET /health is called
        THEN response should include version string.
        """
        response = client.get("/health")
        data = response.json()
        assert "version" in data
        assert data["version"] == "1.0.0"


class TestCapabilitiesEndpoint:
    """Tests for the /capabilities endpoint."""

    def test_capabilities_returns_200(self, client):
        """
        GIVEN the API server is running
        WHEN GET /capabilities is called
        THEN should return 200 OK.
        """
        response = client.get("/capabilities")
        assert response.status_code == 200

    def test_capabilities_includes_logics(self, client):
        """
        GIVEN the API server is running
        WHEN GET /capabilities is called
        THEN response should include supported logics.
        """
        response = client.get("/capabilities")
        data = response.json()
        assert "logics" in data
        assert "tdfol" in data["logics"]
        assert "cec" in data["logics"]

    def test_capabilities_includes_conversions(self, client):
        """
        GIVEN the API server is running
        WHEN GET /capabilities is called
        THEN response should include supported conversions.
        """
        response = client.get("/capabilities")
        data = response.json()
        assert "conversions" in data
        assert len(data["conversions"]) > 0

    def test_capabilities_includes_inference_rules(self, client):
        """
        GIVEN the API server is running
        WHEN GET /capabilities is called
        THEN response should include inference rule counts.
        """
        response = client.get("/capabilities")
        data = response.json()
        assert "inference_rules" in data
        # CEC has 67 rules exported in __all__
        assert data["inference_rules"].get("cec", 0) >= 60

    def test_capabilities_includes_features(self, client):
        """
        GIVEN the API server is running
        WHEN GET /capabilities is called
        THEN response should include feature list.
        """
        response = client.get("/capabilities")
        data = response.json()
        assert "features" in data
        assert "theorem_proving" in data["features"]


class TestProveEndpoint:
    """Tests for the /prove endpoint."""

    def test_prove_returns_response_for_tdfol(self, client):
        """
        GIVEN a simple TDFOL goal
        WHEN POST /prove is called
        THEN should return a prove response (not 5xx).
        """
        payload = {
            "goal": "P",
            "axioms": ["P"],
            "logic": "tdfol",
            "timeout_ms": 1000,
        }
        response = client.post("/prove", json=payload)
        # May return 200 (proved/error result) or 503 (module unavailable)
        assert response.status_code in (200, 503)

    def test_prove_returns_invalid_logic_error(self, client):
        """
        GIVEN an unsupported logic name
        WHEN POST /prove is called
        THEN should return 422 Unprocessable Entity.
        """
        payload = {
            "goal": "P",
            "logic": "invalid_logic",
        }
        response = client.post("/prove", json=payload)
        assert response.status_code == 422

    def test_prove_enforces_timeout_limits(self, client):
        """
        GIVEN a timeout_ms below the minimum (100)
        WHEN POST /prove is called
        THEN should return 422 Unprocessable Entity.
        """
        payload = {
            "goal": "P",
            "logic": "tdfol",
            "timeout_ms": 1,  # Below minimum of 100
        }
        response = client.post("/prove", json=payload)
        assert response.status_code == 422

    def test_prove_enforces_timeout_maximum(self, client):
        """
        GIVEN a timeout_ms above the maximum (30000)
        WHEN POST /prove is called
        THEN should return 422 Unprocessable Entity.
        """
        payload = {
            "goal": "P",
            "logic": "tdfol",
            "timeout_ms": 99999,  # Above maximum of 30000
        }
        response = client.post("/prove", json=payload)
        assert response.status_code == 422

    def test_prove_goal_required(self, client):
        """
        GIVEN a request without a goal
        WHEN POST /prove is called
        THEN should return 422 Unprocessable Entity.
        """
        payload = {"logic": "tdfol"}
        response = client.post("/prove", json=payload)
        assert response.status_code == 422

    def test_prove_response_structure(self, client):
        """
        GIVEN a valid TDFOL prove request
        WHEN POST /prove is called and returns 200
        THEN response should have expected structure.
        """
        payload = {
            "goal": "P",
            "axioms": [],
            "logic": "tdfol",
            "timeout_ms": 2000,
        }
        response = client.post("/prove", json=payload)
        if response.status_code == 200:
            data = response.json()
            assert "proved" in data
            assert "result" in data
            assert "elapsed_ms" in data
            assert isinstance(data["proved"], bool)
            assert isinstance(data["elapsed_ms"], (int, float))


class TestConvertFOLEndpoint:
    """Tests for the /convert/fol endpoint."""

    def test_convert_fol_returns_response(self, client):
        """
        GIVEN a text to convert
        WHEN POST /convert/fol is called
        THEN should return a response (200 or 422).
        """
        payload = {"text": "All humans are mortal"}
        response = client.post("/convert/fol", json=payload)
        assert response.status_code in (200, 422, 503)

    def test_convert_fol_text_required(self, client):
        """
        GIVEN a request without text
        WHEN POST /convert/fol is called
        THEN should return 422 Unprocessable Entity.
        """
        response = client.post("/convert/fol", json={})
        assert response.status_code == 422

    def test_convert_fol_response_has_output(self, client):
        """
        GIVEN a valid text
        WHEN POST /convert/fol returns 200
        THEN response should include output and output_format.
        """
        payload = {"text": "P implies Q"}
        response = client.post("/convert/fol", json=payload)
        if response.status_code == 200:
            data = response.json()
            assert "output" in data
            assert "output_format" in data
            assert data["output_format"] == "fol"


class TestConvertDCECEndpoint:
    """Tests for the /convert/dcec endpoint."""

    def test_convert_dcec_returns_response(self, client):
        """
        GIVEN a text to convert
        WHEN POST /convert/dcec is called
        THEN should return a response.
        """
        payload = {"text": "Alice believes that it is raining"}
        response = client.post("/convert/dcec", json=payload)
        assert response.status_code in (200, 422, 503)

    def test_convert_dcec_text_required(self, client):
        """
        GIVEN a request without text
        WHEN POST /convert/dcec is called
        THEN should return 422 Unprocessable Entity.
        """
        response = client.post("/convert/dcec", json={})
        assert response.status_code == 422


class TestParseEndpoint:
    """Tests for the /parse endpoint."""

    def test_parse_returns_response(self, client):
        """
        GIVEN a formula to parse
        WHEN POST /parse is called
        THEN should return a response.
        """
        payload = {"formula": "P ∧ Q → R"}
        response = client.post("/parse", json=payload)
        assert response.status_code in (200, 422)

    def test_parse_formula_required(self, client):
        """
        GIVEN a request without formula
        WHEN POST /parse is called
        THEN should return 422 Unprocessable Entity.
        """
        response = client.post("/parse", json={})
        assert response.status_code == 422

    def test_parse_response_structure(self, client):
        """
        GIVEN a valid formula string
        WHEN POST /parse returns 200
        THEN response should have expected structure.
        """
        payload = {"formula": "P ∧ Q"}
        response = client.post("/parse", json=payload)
        if response.status_code == 200:
            data = response.json()
            assert "formula_type" in data
            assert "is_valid" in data
            assert "elapsed_ms" in data


class TestInputValidation:
    """Tests for input size and validation constraints."""

    def test_prove_goal_too_long_rejected(self, client):
        """
        GIVEN a goal string exceeding 10000 characters
        WHEN POST /prove is called
        THEN should return 422 Unprocessable Entity.
        """
        payload = {
            "goal": "P" * 10001,
            "logic": "tdfol",
        }
        response = client.post("/prove", json=payload)
        assert response.status_code == 422

    def test_convert_text_too_long_rejected(self, client):
        """
        GIVEN text exceeding 10000 characters
        WHEN POST /convert/fol is called
        THEN should return 422 Unprocessable Entity.
        """
        payload = {"text": "word " * 2001}  # ~10005 chars
        response = client.post("/convert/fol", json=payload)
        assert response.status_code == 422


class TestOpenAPIDocumentation:
    """Tests that OpenAPI documentation is properly generated."""

    def test_openapi_schema_available(self, client):
        """
        GIVEN the API server is running
        WHEN GET /openapi.json is called
        THEN should return the OpenAPI schema.
        """
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data

    def test_all_endpoints_in_schema(self, client):
        """
        GIVEN the API server is running
        WHEN GET /openapi.json is called
        THEN all main endpoints should be documented.
        """
        response = client.get("/openapi.json")
        data = response.json()
        paths = data.get("paths", {})
        assert "/health" in paths
        assert "/capabilities" in paths
        assert "/prove" in paths
        assert "/convert/fol" in paths
        assert "/convert/dcec" in paths
        assert "/parse" in paths
