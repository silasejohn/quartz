# Quartz

Tournament scouting and draft analysis pipeline for amateur League of Legends tournaments.

Quartz ingests player roster data, enriches it with OP.GG rank history, computes Point Value (PV) scores, and exports a draft pool for Google Sheets. Includes a draft simulator for captain threshold analysis.

## Quickstart

```bash
brew install uv
uv venv && source .venv/bin/activate
uv pip install -e .
```

See `CLAUDE.md` for full usage.
