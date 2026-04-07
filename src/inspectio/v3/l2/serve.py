"""ASGI app for ``uvicorn inspectio.v3.l2.serve:app``."""

from inspectio.v3.l2.factory import create_l2_app_from_env

app = create_l2_app_from_env()
