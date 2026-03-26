from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="inspectio-notification", version="0.0.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "notification"}


def _not_implemented() -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={
            "detail": "not_implemented",
            "ref": "plans/IMPLEMENTATION_PHASES.md",
        },
    )


@app.post("/internal/v1/outcomes/terminal")
async def post_terminal() -> JSONResponse:
    return _not_implemented()


@app.get("/internal/v1/outcomes/success")
async def get_outcomes_success() -> JSONResponse:
    return _not_implemented()


@app.get("/internal/v1/outcomes/failed")
async def get_outcomes_failed() -> JSONResponse:
    return _not_implemented()
