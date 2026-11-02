# RoofRunner Protocol

RoofRunner exposes an HTTP API on port **8001** and communicates with a Pololu Simple Motor Controller G2 18v15 using its **Compact Protocol** over TTL UART (default **9600 baud**).

## HTTP API

| Method | Endpoint | Header | Behavior |
| --- | --- | --- | --- |
| GET | `/api/dome/telemetry` | None | Returns latest cached telemetry and controller state |
| POST | `/api/dome/open` | `X-API-Key: <token>` | Forward motor command |
| POST | `/api/dome/close` | `X-API-Key: <token>` | Reverse motor command |
| POST | `/api/dome/reset` | `X-API-Key: <token>` | Fresh health check; clear HALTED on success |
| POST | `/api/dome/stop` | None | Latch HALTED; queue priority zero-speed command |

The token comes from `ROOFRUNNER_API_TOKEN` in the server's `.env`. Protected endpoints return **401** for a missing/wrong key and **503** when the server token is unset. STOP and telemetry remain accessible without a token. No endpoint accepts a client-selected serial device or motor speed.

Responses to commands include `success` and `command`; failures include `error.code` and `error.message`. Operational failures may still use **HTTP 200**. A timeout can return `SMC_COMMAND_CANCELLED` (not executed) or `SMC_COMMAND_OUTCOME_UNKNOWN` (execution began, outcome unconfirmed).

## Telemetry

`GET /api/dome/telemetry` returns a cached snapshot:

- `success`, `timestamp_utc` (UTC ISO 8601)
- `telemetry`: `error_status`, `limit_status`, `target_speed`, `current_speed`, `input_voltage_mv`, `temperature_tenths_c`, `motor_current_ma`, `uptime_ms`, `open_limit_active`, `closed_limit_active`
- `controller`: `state` (`READY` or `HALTED`), `reason` (string or null), `movement_allowed` (boolean)
- `error` on telemetry failure (and `telemetry: null`)

SMC telemetry is sampled every `SMC_POLL_INTERVAL_MS` (default 500 ms); GET requests do not perform serial reads.

## Serial commands

Reference: [Pololu SMC G2 Compact Protocol](https://www.pololu.com/docs/0J77/6.2).

| Operation | Bytes / format |
| --- | --- |
| Get variable | `A1 <variable-id>` → 2-byte little-endian value |
| Exit Safe Start | `83` |
| Forward (OPEN) | `85 <speed-low-5-bits> <speed-high-7-bits>` |
| Reverse (CLOSE) | `86 <speed-low-5-bits> <speed-high-7-bits>` |
| Zero speed (STOP) | `85 00 00` |

Speed is clamped to 0–3200. OPEN sends `83 85 00 64` (3200); CLOSE sends `83 86 00 64`. The SMC applies its own configured limits and acceleration.

Polled variables (ID; signedness): error status (0, unsigned), limit status (3, unsigned), target speed (20, signed), current speed (21, signed), input voltage (23, unsigned), temperature (24, unsigned), motor current (44, unsigned), uptime low/high words (28/29, unsigned). Uptime combines the two words into milliseconds.

Limit bits: **OPEN = 256**, **CLOSED = 128**. Both active is contradictory and triggers a latched halt and zero-speed command. Neither active does not establish motion.

## Command ordering and safety

One worker owns the serial port. It serializes all reads and writes; API requests enqueue commands. STOP takes priority and invalidates pending movement commands, but cannot interrupt a serial write already underway.

- Startup checks SMC error status, limit consistency, and nonzero input voltage before entering READY.
- STOP latches HALTED until RESET succeeds.
- RESET performs the same health checks; it does **not** issue motor movement.
- Communications errors latch HALTED; physical motor stoppage cannot be guaranteed when serial communication is lost.
- HALTED is in-memory only; a restart repeats startup checks.

**The API is HTTP without TLS and is intended for trusted LAN use only.** Do not expose port 8001 publicly. The Pololu's configured hardware limits and an independent motor-power disconnect remain essential.
