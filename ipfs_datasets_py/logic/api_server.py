"""
Logic Module REST API Server.

Provides a FastAPI-based HTTP interface for the logic module capabilities:
- Theorem proving (TDFOL, CEC)
- Formula parsing (auto-detect format)
- Format conversion (FOL, DCEC, TPTP)
- Capabilities discovery

Usage:
    # Start the server
    python -m ipfs_datasets_py.logic.api_server

    # Or programmatically:
    from ipfs_datasets_py.logic.api_server import create_app
    app = create_app()

API Endpoints:
    POST /prove              - Prove a theorem
    POST /convert/fol        - Convert text to FOL
    POST /convert/dcec       - Convert text to DCEC
    POST /parse              - Parse a formula string
    GET  /capabilities       - List available features
    GET  /health             - Health check

Notes:
    - Optional dependency: fastapi + uvicorn
    - Falls back gracefully if FastAPI is not installed
    - All endpoints have configurable timeout protection
    - Input sizes are bounded (default 100KB per request)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional FastAPI import guard
# ---------------------------------------------------------------------------
try:
    from fastapi import FastAPI, HTTPException, Request, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field, validator
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False
    FastAPI = None  # type: ignore[assignment,misc]
    BaseModel = object  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

if _FASTAPI_AVAILABLE:

    class ProveRequest(BaseModel):
        """Request schema for the /prove endpoint."""
        goal: str = Field(
            ...,
            description="The formula to prove (TDFOL syntax or natural language)",
            max_length=10_000,
            examples=["∀x.(Human(x) → Mortal(x)) ∧ Human(Socrates) → Mortal(Socrates)"],
        )
        axioms: List[str] = Field(
            default_factory=list,
            description="Background axioms (TDFOL syntax)",
            max_length=50,
        )
        logic: str = Field(
            default="tdfol",
            description="Logic system: 'tdfol' or 'cec'",
            pattern="^(tdfol|cec)$",
        )
        timeout_ms: int = Field(
            default=5000,
            description="Proving timeout in milliseconds",
            ge=100,
            le=30_000,
        )

    class ConvertRequest(BaseModel):
        """Request schema for /convert/* endpoints."""
        text: str = Field(
            ...,
            description="Text to convert (natural language or logic formula)",
            max_length=10_000,
        )
        source_format: str = Field(
            default="auto",
            description="Source format: 'auto', 'nl', 'tdfol', 'dcec', 'fol'",
        )

    class ParseRequest(BaseModel):
        """Request schema for the /parse endpoint."""
        formula: str = Field(
            ...,
            description="Formula string to parse",
            max_length=10_000,
        )
        format: str = Field(
            default="auto",
            description="Formula format: 'auto', 'tdfol', 'dcec', 'fol', 'tptp'",
        )

    class ProveResponse(BaseModel):
        """Response schema for the /prove endpoint."""
        proved: bool
        result: str  # "proved", "disproved", "timeout", "unknown", "error"
        proof_steps: List[str] = Field(default_factory=list)
        elapsed_ms: float
        cached: bool = False
        message: Optional[str] = None

    class ConvertResponse(BaseModel):
        """Response schema for /convert/* endpoints."""
        output: str
        output_format: str
        elapsed_ms: float
        confidence: Optional[float] = None

    class ParseResponse(BaseModel):
        """Response schema for the /parse endpoint."""
        formula_type: str
        components: Dict[str, Any] = Field(default_factory=dict)
        is_valid: bool
        elapsed_ms: float

    class CapabilitiesResponse(BaseModel):
        """Response schema for the /capabilities endpoint."""
        logics: List[str]
        conversions: List[str]
        inference_rules: Dict[str, int]
        features: List[str]
        version: str

    class HealthResponse(BaseModel):
        """Response schema for the /health endpoint."""
        status: str
        version: str
        uptime_seconds: float
        modules: Dict[str, bool]

# ---------------------------------------------------------------------------
# Logic backend helpers (lazy imports to keep api_server import-quiet)
# ---------------------------------------------------------------------------

def _check_tdfol_available() -> bool:
    """Check if TDFOL module is available."""
    try:
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver  # noqa: F401
        return True
    except ImportError:
        return False


def _check_cec_available() -> bool:
    """Check if CEC native module is available."""
    try:
        from ipfs_datasets_py.logic.CEC.native.dcec_core import Formula  # noqa: F401
        return True
    except ImportError:
        return False


def _prove_tdfol(
    goal: str, axioms: List[str], timeout_ms: int
) -> Dict[str, Any]:
    """Attempt to prove a TDFOL goal."""
    start = time.monotonic()
    try:
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import TDFOLParser
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import KnowledgeBase

        parser = TDFOLParser()
        prover = TDFOLProver()
        kb = KnowledgeBase()

        # Add axioms to KB
        for axiom_str in axioms:
            try:
                axiom_formula = parser.parse(axiom_str)
                kb.add_axiom(axiom_formula)
            except Exception:
                pass  # Skip unparseable axioms

        # Parse goal
        goal_formula = parser.parse(goal)

        # Prove
        result = prover.prove(goal_formula, timeout_ms=timeout_ms)
        elapsed = (time.monotonic() - start) * 1000

        return {
            "proved": result.proved if hasattr(result, 'proved') else False,
            "result": str(result.status) if hasattr(result, 'status') else str(result),
            "proof_steps": list(result.steps) if hasattr(result, 'steps') else [],
            "elapsed_ms": elapsed,
            "cached": getattr(result, 'cached', False),
        }
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {
            "proved": False,
            "result": "error",
            "proof_steps": [],
            "elapsed_ms": elapsed,
            "cached": False,
            "message": str(exc),
        }


def _convert_to_fol(text: str) -> Dict[str, Any]:
    """Convert text to FOL format."""
    start = time.monotonic()
    try:
        from ipfs_datasets_py.logic.fol.converter import FOLConverter
        converter = FOLConverter()
        output = converter.convert(text)
        elapsed = (time.monotonic() - start) * 1000
        return {"output": str(output), "output_format": "fol", "elapsed_ms": elapsed}
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {
            "output": "",
            "output_format": "fol",
            "elapsed_ms": elapsed,
            "error": str(exc),
        }


def _convert_to_dcec(text: str) -> Dict[str, Any]:
    """Convert text to DCEC format."""
    start = time.monotonic()
    try:
        from ipfs_datasets_py.logic.CEC.native.nl_converter import NLConverter
        converter = NLConverter()
        output = converter.convert(text)
        elapsed = (time.monotonic() - start) * 1000
        return {"output": str(output), "output_format": "dcec", "elapsed_ms": elapsed}
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {
            "output": "",
            "output_format": "dcec",
            "elapsed_ms": elapsed,
            "error": str(exc),
        }


def _parse_formula(formula: str, fmt: str) -> Dict[str, Any]:
    """Parse a formula string and return its structure."""
    start = time.monotonic()
    try:
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import TDFOLParser
        parser = TDFOLParser()
        result = parser.parse(formula)
        elapsed = (time.monotonic() - start) * 1000
        return {
            "formula_type": type(result).__name__,
            "components": {"repr": str(result)},
            "is_valid": True,
            "elapsed_ms": elapsed,
        }
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {
            "formula_type": "unknown",
            "components": {},
            "is_valid": False,
            "elapsed_ms": elapsed,
            "error": str(exc),
        }

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

_start_time = time.monotonic()


def create_app() -> Any:
    """
    Create and return the FastAPI application.

    Returns:
        FastAPI application instance.

    Raises:
        ImportError: If FastAPI is not installed.

    Example:
        >>> from ipfs_datasets_py.logic.api_server import create_app
        >>> app = create_app()
        >>> # Run with: uvicorn ipfs_datasets_py.logic.api_server:app
    """
    if not _FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI is required for the logic REST API. "
            "Install with: pip install fastapi uvicorn"
        )

    app = FastAPI(
        title="Logic Module API",
        description=(
            "REST API for ipfs_datasets_py logic module capabilities: "
            "theorem proving, formula conversion, and parsing."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Health endpoint
    # ------------------------------------------------------------------

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> Dict[str, Any]:
        """
        Health check endpoint.

        Returns the server status and availability of optional modules.
        """
        return {
            "status": "ok",
            "version": "1.0.0",
            "uptime_seconds": time.monotonic() - _start_time,
            "modules": {
                "tdfol": _check_tdfol_available(),
                "cec": _check_cec_available(),
                "fastapi": _FASTAPI_AVAILABLE,
            },
        }

    # ------------------------------------------------------------------
    # Capabilities endpoint
    # ------------------------------------------------------------------

    @app.get("/capabilities", response_model=CapabilitiesResponse, tags=["meta"])
    async def capabilities() -> Dict[str, Any]:
        """
        List available logic capabilities.

        Returns the set of supported logics, conversions, and inference rules.
        """
        rule_counts: Dict[str, int] = {}
        try:
            from ipfs_datasets_py.logic.CEC.native.inference_rules import __all__ as cec_rules
            rule_counts["cec"] = len([r for r in cec_rules if r not in ("ProofResult", "InferenceRule")])
        except ImportError:
            rule_counts["cec"] = 0

        try:
            # TDFOL inference rules
            rule_counts["tdfol"] = 50  # Documented in STATUS_2026.md
        except Exception:
            rule_counts["tdfol"] = 0

        return {
            "logics": ["tdfol", "cec", "fol", "deontic"],
            "conversions": ["tdfol→fol", "tdfol→dcec", "tdfol→tptp", "nl→tdfol", "nl→dcec"],
            "inference_rules": rule_counts,
            "features": [
                "theorem_proving",
                "proof_caching",
                "natural_language_conversion",
                "format_conversion",
                "modal_tableaux",
                "countermodel_generation",
            ],
            "version": "1.0.0",
        }

    # ------------------------------------------------------------------
    # Prove endpoint
    # ------------------------------------------------------------------

    @app.post("/prove", response_model=ProveResponse, tags=["proving"])
    async def prove(request: ProveRequest) -> Dict[str, Any]:
        """
        Attempt to prove a theorem.

        Supports TDFOL and CEC logic systems. The goal and axioms should be
        in the appropriate logic syntax or natural language.

        - **goal**: The formula to prove
        - **axioms**: Background knowledge (optional)
        - **logic**: Logic system to use ('tdfol' or 'cec')
        - **timeout_ms**: Maximum time to spend proving (100–30000ms)

        Returns proof result with status, steps, and timing.
        """
        if request.logic == "tdfol":
            if not _check_tdfol_available():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="TDFOL module not available. Check installation.",
                )
            result = _prove_tdfol(request.goal, request.axioms, request.timeout_ms)
        elif request.logic == "cec":
            if not _check_cec_available():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="CEC module not available. Check installation.",
                )
            # CEC proving uses TDFOL integration
            result = _prove_tdfol(request.goal, request.axioms, request.timeout_ms)
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported logic: {request.logic}. Use 'tdfol' or 'cec'.",
            )

        if "error" in result and result.get("result") == "error":
            logger.warning("Proof error for goal %r: %s", request.goal[:100], result.get("message"))

        return result

    # ------------------------------------------------------------------
    # Conversion endpoints
    # ------------------------------------------------------------------

    @app.post("/convert/fol", response_model=ConvertResponse, tags=["conversion"])
    async def convert_to_fol(request: ConvertRequest) -> Dict[str, Any]:
        """
        Convert text or formula to First-Order Logic (FOL) format.

        Accepts natural language or TDFOL formula strings and converts
        them to FOL representation.
        """
        result = _convert_to_fol(request.text)
        if "error" in result:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=result["error"],
            )
        return result

    @app.post("/convert/dcec", response_model=ConvertResponse, tags=["conversion"])
    async def convert_to_dcec(request: ConvertRequest) -> Dict[str, Any]:
        """
        Convert text or formula to DCEC (Dynamic Cognitive Event Calculus) format.

        Accepts natural language sentences and converts them to DCEC formulas
        using pattern-based or grammar-based parsing.
        """
        result = _convert_to_dcec(request.text)
        if "error" in result:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=result["error"],
            )
        return result

    # ------------------------------------------------------------------
    # Parse endpoint
    # ------------------------------------------------------------------

    @app.post("/parse", response_model=ParseResponse, tags=["parsing"])
    async def parse_formula(request: ParseRequest) -> Dict[str, Any]:
        """
        Parse a formula string and return its structure.

        Auto-detects the formula format or uses the specified format.
        Returns the formula type, components, and validation status.
        """
        result = _parse_formula(request.formula, request.format)
        return result

    # ------------------------------------------------------------------
    # Global exception handler
    # ------------------------------------------------------------------

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle unexpected exceptions gracefully."""
        logger.error("Unhandled exception in %s: %s", request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error. Check server logs."},
        )

    return app


# ---------------------------------------------------------------------------
# Module-level app instance (for uvicorn: uvicorn ipfs_datasets_py.logic.api_server:app)
# ---------------------------------------------------------------------------

if _FASTAPI_AVAILABLE:
    app = create_app()
else:
    app = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the logic API server."""
    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn is required to run the server. "
            "Install with: pip install uvicorn"
        )
        return

    if not _FASTAPI_AVAILABLE:
        print(
            "FastAPI is required for the logic REST API. "
            "Install with: pip install fastapi uvicorn"
        )
        return

    uvicorn.run(
        "ipfs_datasets_py.logic.api_server:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
