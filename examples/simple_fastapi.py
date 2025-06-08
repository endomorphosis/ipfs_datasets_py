"""
Simple FastAPI Service for IPFS Datasets

A minimal working FastAPI service for testing and development.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import logging
from datetime import datetime
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="IPFS Datasets API",
    description="REST API for IPFS Datasets with embedding capabilities",
    version="1.0.0"
)

@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "IPFS Datasets API", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "IPFS Datasets API"
    }

@app.get("/api/status")
async def api_status():
    """API status endpoint."""
    return {
        "api": "IPFS Datasets API",
        "version": "1.0.0",
        "status": "operational",
        "features": [
            "Dataset management",
            "Embedding generation", 
            "Vector search",
            "IPFS integration",
            "MCP tools"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
