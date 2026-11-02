# RoofRunner

A Raspberry Pi controller for the TriStar Observatory roll-off roof. A FastAPI service sends commands to a Pololu Simple Motor Controller over TTL UART and publishes cached telemetry.

**Status:** Motor control, telemetry, STOP/RESET, limit checks, and API-key authentication have been tested. An ASCOM dome driver is not yet implemented.

## Tested Hardware

- Raspberry Pi 3B, Pololu SMC G2 18v15, nominal 12 V motor supply, DC roof motor, and two normally-closed limit switches.

See [hardware wiring](docs/hardware.md).

## Setup

Requires Docker Compose, an enabled Pi UART, and a configured SMC. The provided Compose file maps host `/dev/ttyS0` to container `/dev/serial0` and exposes port 8001 on the LAN.

```bash
cp .env.example .env
stat -c '%g' /dev/ttyS0
```

Edit `.env` with the reported numeric serial group ID and a **new** API token:

```dotenv
PI_SERIAL_BAUD=9600
PI_SERIAL_PORT=/dev/serial0
SMC_COMMAND_TIMEOUT_MS=3000
SMC_POLL_INTERVAL_MS=500
ROOFRUNNER_SERIAL_GID=<numeric-GID-from-stat>
ROOFRUNNER_API_TOKEN=make_something_up
```

You can easily generate a token with `openssl rand -hex 32`, but it can be literally anything you wish. The serial group ID is used by Docker Compose to give the non-root container user access to the device. If your Pi uses a different UART device, adjust the Compose mapping and group ID accordingly.

The container runs as unprivileged UID 10001. Check with `docker exec roofrunner id`.

## HTTP API

Base URL: `http://<pi-ip>:8001`; interactive Swagger UI: `/docs`.

| Method | Path | Authentication | Purpose |
| --- | --- | --- | --- |
| GET | `/api/dome/telemetry` | None | Cached SMC telemetry and RoofRunner state |
| POST | `/api/dome/open` | `X-API-Key` | Request opening |
| POST | `/api/dome/close` | `X-API-Key` | Request closing |
| POST | `/api/dome/reset` | `X-API-Key` | Health-check and clear HALTED |
| POST | `/api/dome/stop` | None | Request zero speed and latch HALTED |

Example:

```bash
http://<pi-ip>:8001/api/dome/telemetry
```

For protected requests, send `X-API-Key: <token>` in the HTTP header (Swagger provides an `x-api-key` field for testing). Missing/invalid tokens return HTTP 401; an unset server token returns HTTP 503. The service uses **HTTP, not HTTPS**: keep it on a trusted network and do not forward port 8001 to the internet.

Command results can return HTTP 200 with `"success": false`; always inspect the JSON result. A timeout may leave the command outcome unknown.

## Safety behavior

- `READY` permits movement commands; `HALTED` rejects OPEN/CLOSE until a successful RESET.
- STOP latches HALTED, cancels queued commands, and prioritizes a zero-speed serial command. It cannot guarantee a stop if serial communication fails or a command is already in flight.
- RESET reads fresh telemetry and requires noncontradictory limit inputs, zero SMC error status, and nonzero input voltage. RESET does not move the roof.
- Both OPEN and CLOSED limit bits active cause an automatic STOP and latched `CONTRADICTORY_LIMITS` state.
- The HALTED latch is **not persisted** across container restarts; startup performs a new health check.
- `HALTED` describes software state, **not proof of physical motor stoppage**. Maintain an independent means of removing motor power.

Roof clearance, telescope parking, weather and other unattended-operation interlocks are your responsibility.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| API unreachable | `docker compose ps`, logs, Pi IP and port 8001 |
| No telemetry | SMC power, UART enable, TX/RX crossover, common ground, baud rate, serial mapping/group ID |
| HTTP 401 | `X-API-Key` header matches `.env` token |
| HTTP 503 on protected command | `ROOFRUNNER_API_TOKEN` missing; recreate container after fixing `.env` |
| `CONTROLLER_HALTED` | Inspect `controller.reason`; resolve cause before RESET |
| Command times out | Check physical motor state and subsequent telemetry; execution may be uncertain |

For protocol bytes, telemetry fields, and state transitions, see [docs/protocol.md](docs/protocol.md).
