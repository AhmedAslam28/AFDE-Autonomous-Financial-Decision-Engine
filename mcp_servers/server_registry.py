"""
mcp_servers/server_registry.py

Manages all 5 MCP server connections using MCPServerStdio.
Each server runs as a subprocess; the agent SDK speaks MCP protocol over stdio.

Usage:
    from mcp_servers.server_registry import get_servers_for_agent
    servers = get_servers_for_agent("fundamental")
    agent = Agent(..., mcp_servers=servers)
"""

from __future__ import annotations
import os
import sys

from agents.mcp import MCPServerStdio

# Resolve paths to each server script
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_PY   = sys.executable   # use same Python interpreter as current process


def _make_server(script_name: str, env_extra: dict | None = None) -> MCPServerStdio:
    """
    Create an MCPServerStdio instance for a given server script.
    The agent SDK will start this as a subprocess when the agent runs.
    """
    script_path = os.path.join(_HERE, script_name)
    env = {**os.environ}
    if env_extra:
        env.update(env_extra)
    return MCPServerStdio(
        params={"command": _PY, "args": [script_path], "env": env},
        cache_tools_list=True,
        client_session_timeout_seconds=30,  # 30s — FRED/SEC calls can be slow
    )


# ── Server factory functions ──────────────────────────────────────────
# Each returns a fresh MCPServerStdio instance (context manager, not reusable)

def market_data_server() -> MCPServerStdio:
    return _make_server("market_data_server.py")

def sec_server() -> MCPServerStdio:
    return _make_server("sec_server.py")

def macro_server() -> MCPServerStdio:
    return _make_server("macro_server_proc.py")

def news_server() -> MCPServerStdio:
    return _make_server("news_server.py")

def document_server() -> MCPServerStdio:
    return _make_server("document_server.py")


# ── Per-agent server selection ────────────────────────────────────────
# Each specialist agent connects only to the servers it needs.
# document_server is added to fundamental + sentiment when a doc is uploaded.

def get_servers_for_agent(agent_name: str, has_document: bool = False) -> list[MCPServerStdio]:
    """
    Return the list of MCP server instances for a given agent.

    Args:
        agent_name:   "fundamental" | "sentiment" | "insider" | "macro"
        has_document: True if a document was uploaded — adds document_server
    """
    mapping = {
        "fundamental": [market_data_server, sec_server],
        "sentiment":   [news_server, market_data_server],
        "insider":     [sec_server],
        "macro":       [macro_server],
    }
    factories = mapping.get(agent_name, [market_data_server])
    if has_document:
        factories = factories + [document_server]
    return [f() for f in factories]