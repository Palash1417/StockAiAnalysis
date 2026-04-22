"""Production entry-point for Render / uvicorn.

Start command:
    uvicorn phase_9_api.main:app --host 0.0.0.0 --port $PORT
"""
from phase_9_api.app import create_app

app = create_app()
