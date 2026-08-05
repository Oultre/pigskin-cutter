"""Local web UI: a FastAPI front end over the CLI engine (CLAUDE.md: CLI before UI).

Every endpoint is a thin adapter over the same modules the CLI uses (filters,
render, ingest). No cut logic, filter logic, or schema logic lives here.
"""
