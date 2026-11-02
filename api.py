
###########################################################################
# Created : 2026-10-09 GB
# Purpose : RoofRunner HTTP API for telemetry and motor control.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: Astrophotography N
#           OpenAI model/version: GPT-6
###########################################################################

import asyncio
import os
import secrets

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException
from smc_worker import SmcWorker


worker = SmcWorker()


def require_api_key(x_api_key: str | None = Header(default=None)):
    expected = os.environ.get("ROOFRUNNER_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="API authentication not configured")
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")



async def execute_command(command):
    """Submit a command and await its result."""
    future = worker.submit_command(command)

    try:
        return await asyncio.wait_for(
            asyncio.shield(asyncio.wrap_future(future)),
            timeout=worker.command_timeout,
        )

    except asyncio.TimeoutError:
        cancelled = future.cancel()

        return {
            "success": False,
            "command": command,
            "error": {
                "code": (
                    "SMC_COMMAND_CANCELLED"
                    if cancelled
                    else "SMC_COMMAND_OUTCOME_UNKNOWN"
                ),
                "message": (
                    "Command cancelled before execution"
                    if cancelled
                    else "Execution began but outcome is unconfirmed"
                ),
            },
        }

    except asyncio.CancelledError:
        future.cancel()
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker.start()
    try:
        yield
    finally:
        worker.stop()


app = FastAPI(
    title="RoofRunner",
    lifespan=lifespan,
)


#####################################
# Roof movement commands
#####################################

@app.get("/api/dome/telemetry")
def get_telemetry():
    return worker.get_snapshot()


@app.post("/api/dome/close", dependencies=[Depends(require_api_key)])
async def close_shutter():
    return await execute_command("close")


@app.post("/api/dome/open", dependencies=[Depends(require_api_key)])
async def open_shutter():
    return await execute_command("open")


@app.post("/api/dome/reset", dependencies=[Depends(require_api_key)])
async def reset_controller():
    return await execute_command("reset")


@app.post("/api/dome/stop")
async def stop_shutter():
    return await execute_command("stop")
