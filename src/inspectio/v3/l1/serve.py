"""ASGI entry for ``uvicorn inspectio.v3.l1.serve:app``."""

from inspectio.v3.l1.app import create_l1_app

app = create_l1_app()
