
###########################################################################
# Created : 2026-10-09 GB
# Purpose : Provides the RoofRunner HTTP API for SMC G2 telemetry
#           and motor commands.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: Astrophotography N
#           OpenAI model/version: GPT-6
###########################################################################

import asyncio

from contextlib import asynccontextmanager
from fastapi import FastAPI
from smc_worker import SmcWorker


worker = SmcWorker()


async def execute_command(command):
    """Submit a command and await its execution result."""
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
                    "Command expired before execution"
                    if cancelled
                    else "Command execution began, but its outcome "
                         "was not confirmed before timeout"
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


@app.post("/api/dome/close")
async def close_shutter():
    return await execute_command("close")


@app.post("/api/dome/open")
async def open_shutter():
    return await execute_command("open")


@app.post("/api/dome/stop")
async def stop_shutter():
    return await execute_command("stop")
