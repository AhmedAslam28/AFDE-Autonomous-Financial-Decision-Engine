"""
main.py — AFDE entry point.

CLI:    python main.py "Should I invest in Tesla?"
Server: python main.py --serve   (then POST to /analyse)
Docs:   http://localhost:8000/docs
"""

from __future__ import annotations
import asyncio
import json
import sys

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from rich.console import Console

from engine import run_afde
from config import OPENAI_API_KEY

console = Console()

app = FastAPI(
    title="Autonomous Financial Decision Engine",
    description=(
        "Multi-agent autonomous financial analysis. "
        "Runs specialist agents, self-corrects via reflection loop, "
        "then runs Bull vs Bear debate to produce an evidence-weighted decision."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class AnalyseRequest(BaseModel):
    model_config = {"json_schema_extra": {"example": {"goal": "Should I buy Apple stock?"}}}
    goal: str = Field(..., min_length=10, description="Natural language financial goal")


@app.get("/health")
async def health():
    return {"status": "ok", "openai_configured": bool(OPENAI_API_KEY)}


@app.post("/analyse")
async def analyse(req: AnalyseRequest):
    if not OPENAI_API_KEY:
        raise HTTPException(503, "OPENAI_API_KEY not set in .env")
    try:
        return await run_afde(req.goal, verbose=False)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Engine error: {e}")


async def _cli(goal: str) -> None:
    if not OPENAI_API_KEY:
        console.print("[red]ERROR: OPENAI_API_KEY not set. Copy .env.example to .env and add your key.[/red]")
        sys.exit(1)
    result = await run_afde(goal, verbose=True)
    console.print("\n[bold]JSON output:[/bold]")
    console.print(json.dumps(result, indent=2))


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--serve" in args:
        console.print("[green]Starting AFDE API server → http://localhost:8000/docs[/green]")
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    elif args:
        asyncio.run(_cli(" ".join(args)))
    else:
        console.print(
            "[yellow]Usage:[/yellow]\n"
            "  python main.py 'Should I invest in Tesla?'\n"
            "  python main.py --serve"
        )
