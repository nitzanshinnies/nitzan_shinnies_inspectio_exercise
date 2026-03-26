from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="inspectio-api", version="0.0.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


def _not_implemented() -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={
            "detail": "not_implemented",
            "ref": "plans/IMPLEMENTATION_PHASES.md",
        },
    )


@app.post("/messages")
async def post_messages() -> JSONResponse:
    return _not_implemented()


@app.post("/messages/repeat")
async def post_messages_repeat() -> JSONResponse:
    return _not_implemented()


@app.get("/messages/success")
async def get_messages_success() -> JSONResponse:
    return _not_implemented()


@app.get("/messages/failed")
async def get_messages_failed() -> JSONResponse:
    return _not_implemented()
