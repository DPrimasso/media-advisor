"""FastAPI server package.

This file exists so that `uvicorn server.api:app` works reliably
on Windows (especially with `--reload`, which uses a subprocess import).
"""

