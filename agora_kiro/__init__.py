"""
agora-kiro: Persistent memory for Kiro AI coding sessions.

Exposes the memory MCP server and CLI tools for session continuity,
learnings, symbol indexing, and token-efficient file reads.

Quick start:
    agora-kiro memory-server   # start the MCP server (add to .kiro/settings/mcp.json)
    agora-kiro inject          # load last session context
    agora-kiro status          # check DB stats
"""

__version__ = "0.1.0"
