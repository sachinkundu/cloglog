"""ASGI entry point for gunicorn.

Gunicorn does not support uvicorn's --factory flag. This module calls
create_app() at import time so gunicorn can reference src.gateway.asgi:app.
"""

from src.gateway.app import create_app

app = create_app()
