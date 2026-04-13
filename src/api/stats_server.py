"""
FastAPI stats endpoint for signal filter analytics and paper trading.

GET /stats → JSON summary of signal activity.
GET /health → Health check.
GET /paper/status → Paper trading orchestrator status.
GET /paper/positions → Open paper positions.
GET /paper/stats → Aggregate paper trading statistics.
"""

from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI(title="ATS Signal Filter Stats", version="2.0.0")

# Pipeline reference — set at startup by run_pipeline.py
_pipeline = None
# Orchestrator reference — set at startup by run_paper_trading.py
_orchestrator = None


def set_pipeline(pipeline):
    """Set the pipeline instance for the stats server."""
    global _pipeline
    _pipeline = pipeline


def set_orchestrator(orchestrator):
    """Set the orchestrator instance for paper trading endpoints."""
    global _orchestrator
    _orchestrator = orchestrator


@app.get("/stats")
async def get_stats(hours: int = Query(default=24, ge=1, le=168)):
    """Get signal statistics for the specified time window."""
    if _pipeline is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Pipeline not initialized"},
        )

    stats = _pipeline.get_stats(hours=hours)
    return stats


@app.get("/health")
async def health():
    """Health check endpoint."""
    status = {"status": "ok", "service": "signal-filter"}
    if _orchestrator is not None:
        status["paper_trading"] = "active"
    return status


@app.get("/paper/status")
async def paper_status():
    """Full orchestrator + paper trading status."""
    if _orchestrator is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Paper trading orchestrator not initialized"},
        )
    return _orchestrator.get_status()


@app.get("/paper/positions")
async def paper_positions():
    """List open paper trading positions."""
    if _orchestrator is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Paper trading orchestrator not initialized"},
        )
    return {"positions": _orchestrator.paper_trader.get_open_positions_summary()}


@app.get("/paper/stats")
async def paper_stats():
    """Aggregate paper trading statistics."""
    if _orchestrator is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Paper trading orchestrator not initialized"},
        )
    return _orchestrator.paper_trader.get_stats().model_dump()
