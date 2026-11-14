# Feature Forge

Local feature-planning tool. You describe a feature; a grill session (Agent Manager chat plugin, read-only access to the target repo) turns it into a plan and a checklist of self-contained tasks; Feature Forge files the tasks into Agent Manager and tracks them to merged. Every feature stays in the library, Done ones included.

Design and decisions: `Docs/DESIGN.md`. Planned port: 7466 (127.0.0.1). Status: design agreed 2026-11-13, nothing built yet.

## Requirements

- Python 3 (with `venv` support)

## Run

```
./run.sh
```

This creates `.venv` if it is missing, installs `requirements.txt`, and starts the server. Open `http://127.0.0.1:7466`. The server binds to 127.0.0.1 only. To use another port, set `FEATUREFORGE_PORT`, for example `FEATUREFORGE_PORT=8000 ./run.sh`; the default is 7466.

## Test

Run `./run.sh` once to create `.venv` and install dependencies, then run:

```
.venv/bin/pytest tests/
```
