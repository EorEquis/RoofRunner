# RoofRunner

**A Raspberry Pi–powered controller for a roll-off-roof astronomical observatory.**

RoofRunner connects a Raspberry Pi to a Pololu Simple Motor Controller G2, exposes a small HTTP API, and provides a foundation for eventual ASCOM integration. Its job is straightforward: open the observatory roof, close the observatory roof, report what the controller knows, and stop when something is wrong.

> **Project status:** Initial development / hardware validation. The Pi-to-SMC communication, API, movement commands, limit-switch telemetry, STOP/RESET behavior, and automatic contradictory-limit shutdown have been tested with real hardware. This is **not** a claim that the complete observatory installation, roof mechanics, or ASCOM driver has been commissioned.

## What it does

- Commands **OPEN**, **CLOSE**, **STOP**, and **RESET** over HTTP.
- Reads Pololu controller telemetry over TTL UART, caching it for clients.
- Reports controller readiness independently of motor telemetry.
- Refuses movement while the RoofRunner safety latch is HALTED.
- Detects contradictory travel-limit indications during operation, commands zero speed, and latches HALTED.
- Runs as a Docker container on a headless Raspberry Pi.

**Not yet implemented:** an ASCOM dome driver, a physical GPIO RESET button, a SHINY RED HISTORY ERASER BUTTON, and any additional observatory-wide interlocks. Do not infer their existence from the intended architecture.

## Hardware and architecture

| Component | Role |
| --- | --- |
| Raspberry Pi 3B | Runs RoofRunner's HTTP API and serial worker |
| Pololu Simple Motor Controller G2 18v15 | Drives the DC roof motor and implements its configured motor/limit behavior |
| Nominal 12 V DC supply | Powers the motor controller and motor circuit |
| Two normally closed limit switches | Indicate fully OPEN and fully CLOSED travel limits through SMC inputs |
| DC motor, chain, and roof mechanism | Moves the actual roof |

```text
Future ASCOM client / HTTP client
               |
               | HTTP :8001
               v
      Raspberry Pi / RoofRunner
       FastAPI + serial worker
               |
               | TTL UART, 9600 baud
               v
      Pololu SMC G2 18v15
        |              |
        |              +-- NC travel limits (AN1 / AN2)
        |
        +-- DC motor --> chain --> roll-off roof
```

The Pi sends commands to the SMC; **the Pi does not directly drive the motor**. The SMC applies its own configured motor-control parameters and limit behavior.

### Electrical connections

| Raspberry Pi | Pololu SMC | Purpose |
| --- | --- | --- |
| 5V Pin 4 | N/A | 5V power for case fan |
| GND Pin 6 | N/A | GND for fan |
| UART TX Pin 8 / GPIO 14 | RX | Commands and variable requests |
| UART RX Pin 10 / GPIO 15 | TX | Responses / telemetry |
| GPIO input Pin 12 / GPIO 18 | ERR | GPIO-based error monitoring is not yet implemented; SMC error status is currently read through UART and exposed in telemetry. |
| GND Pin 14 | GND | Common signal reference |

The SMC's motor supply is connected to its **VIN/GND motor-power terminals**; that supply also powers the SMC electronics. The Raspberry Pi requires its own appropriate power arrangement. Connecting the SMC's 12 V motor supply directly to a Pi GPIO or Pi power pin would be bad.  Don't do that.

### Limit-switches

Switches are **normally closed (NC)** reed switches. An active limit is open. The SMC's configuration is responsible for interpreting these inputs as travel limits; RoofRunner reads their reported state and checks for contradictions.

### Possible limit switch states, just because I think this is funny.

```text
When open is open and closed is closed, roof is open.
When open is closed, and closed is open, roof is closed.
When open is closed and closed is closed roof is hopefully moving.
When open is open and closed is open something has gone horribly wrong.
```

Translated into telemetry:

| OPEN limit active | CLOSED limit active | Interpretation |
| --- | --- | --- |
| Yes | No | At the OPEN travel limit |
| No | Yes | At the CLOSED travel limit |
| No | No | Between limits |
| Yes | Yes | **Contradictory indication: automatic HALT** |

**Important:** Neither limit active does **not** prove the roof is moving. It only means neither endpoint switch is reporting active. Use motor telemetry and other appropriate observation to determine motion.

## Software design

RoofRunner is deliberately small:

- **`api.py`** defines the FastAPI application, lifecycle, and HTTP endpoints.
- **`smc_worker.py`** owns the serial port, polls the SMC, serializes commands, caches telemetry, and maintains the controller safety state.
- **`compose.yaml`** runs the service in Docker and passes through the Pi's serial device.
- **`Dockerfile`** builds the Python runtime.
- **`requirements.txt`** lists Python dependencies.
- **`.env.example`** documents runtime configuration.

A **single serial worker** owns all SMC reads and writes. API requests do not independently open the serial port or compete to exchange bytes with the controller. The worker uses a command queue with STOP priority, generation tracking, and cancellation of superseded queued commands.

Telemetry is polled on a schedule; API GET requests return the most recent cached snapshot rather than starting a new serial transaction. That keeps the HTTP interface responsive and avoids competing UART traffic.

### Serial protocol

RoofRunner uses the Pololu **Compact Protocol** [documented here](https://www.pololu.com/docs/0J77/6.2):

| Function | Command |
| --- | --- |
| Read variable | `0xA1`, variable ID; expect two little-endian response bytes |
| Exit Safe Start | `0x83` |
| Forward / OPEN | `0x85` followed by encoded speed |
| Reverse / CLOSE | `0x86` followed by encoded speed |
| STOP | Forward command with speed zero: `0x85 0x00 0x00` |

OPEN and CLOSE request speed magnitude **3200**. This is a requested target only. The Pololu enforces its own configured limits. 

## HTTP API

Default service addresses: 

- API: `http://<IP Adress>:8001`
- Interactive API documentation: `http://<IP Address>:8001/docs`

| Method | Endpoint | Action |
| --- | --- | --- |
| `GET` | `/api/dome/telemetry` | Return cached SMC telemetry and RoofRunner controller state |
| `POST` | `/api/dome/open` | Request forward/open movement |
| `POST` | `/api/dome/close` | Request reverse/close movement |
| `POST` | `/api/dome/stop` | Request immediate zero-speed command and latch HALTED |
| `POST` | `/api/dome/reset` | Perform a health check and clear HALTED if checks pass |

Operational failures may return **HTTP 200 with `"success": false`**. Clients must inspect the JSON response; HTTP success alone does not mean the motor command succeeded.

Example telemetry shape (values are illustrative, not live readings):

```json
{
  "success": true,
  "timestamp_utc": "2026-10-09T17:40:43.186Z",
  "telemetry": {
    "error_status": 0,
    "limit_status": 128,
    "target_speed": 0,
    "current_speed": 0,
    "input_voltage_mv": 11797,
    "temperature_tenths_c": 278,
    "motor_current_ma": 0,
    "uptime_ms": 27646829,
    "open_limit_active": false,
    "closed_limit_active": true
  },
  "controller": {
    "state": "READY",
    "reason": null,
    "movement_allowed": true
  }
}
```

### Controller state is not motor state

The `controller` object describes **RoofRunner's API authorization and safety latch**:

- `READY`: RoofRunner is prepared to accept movement requests.
- `HALTED`: RoofRunner rejects OPEN/CLOSE until the latch is explicitly cleared.
- `reason`: the current reason for HALTED, when applicable.
- `movement_allowed`: whether RoofRunner currently permits new movement commands.

**`HALTED` does not, by itself, prove the motor has physically stopped.** That distinction is intentional. Clients should inspect the `telemetry` object (`target_speed`, `current_speed`, errors, and limits) when determining the SMC's reported condition. A communications failure can prevent confirmation of actual motor behavior.

### STOP and RESET

**STOP**:

1. Immediately latches RoofRunner HALTED.
2. Invalidates waiting commands.
3. Queues a priority zero-speed command to the SMC.
4. Rejects subsequent OPEN/CLOSE requests until RESET succeeds.

**RESET**:

1. Does **not** command roof movement.
2. Reads fresh SMC telemetry.
3. Rejects contradictory limits, nonzero SMC error status, or zero reported input voltage.
4. Returns the API to READY only if the health check succeeds and RESET has not been superseded.

Rebooting the application starts a fresh startup health check; the software HALTED latch is not persisted across restarts. **No ASCOM client should silently issue RESET to bypass a halt.**

### Automatic contradictory-limit protection

If both endpoint limit bits are active during periodic telemetry polling, RoofRunner:

1. Latches `HALTED` with reason `CONTRADICTORY_LIMITS`.
2. Invalidates queued commands.
3. Sends a zero-speed command over the worker's existing serial connection.
4. Remains HALTED after the switch condition clears, until an explicit successful RESET.

This behavior has been verified with the motor energized: activating both limits caused the motor to stop and RoofRunner to report HALTED without a manual STOP request.

## Configuration

Copy `.env.example` to `.env` and adjust for the target Pi:

```dotenv
PI_SERIAL_BAUD=9600
PI_SERIAL_PORT=/dev/serial0
SMC_COMMAND_TIMEOUT_MS=3000
SMC_POLL_INTERVAL_MS=500
```

| Setting | Meaning |
| --- | --- |
| `PI_SERIAL_BAUD` | UART speed; must match the SMC configuration |
| `PI_SERIAL_PORT` | Serial device **inside the container** |
| `SMC_COMMAND_TIMEOUT_MS` | API wait limit for command completion |
| `SMC_POLL_INTERVAL_MS` | Telemetry polling interval |

There is deliberately **no `SMC_MOTOR_SPEED` setting**. Motor speed and acceleration limits are configured on the Pololu controller.

## Running on the Raspberry Pi

Prerequisites: a configured Raspberry Pi with Docker and Docker Compose, UART enabled and available, the correct Pololu configuration, and safe electrical/mechanical connections. These instructions assume the repository has already been cloned onto the Pi.

```bash
cd ~/RoofRunner
cp .env.example .env
# Review .env before starting.
sudo docker compose up -d --build
```

Useful commands:

```bash
sudo docker compose ps
sudo docker compose logs --tail=100 roofrunner
sudo docker compose down
```

To rebuild after code changes:

```bash
sudo docker compose down
sudo docker compose up -d --build
```

The Compose configuration passes the Pi's `/dev/ttyS0` through as `/dev/serial0` inside the container and publishes port **8001**. If the host's serial mapping differs, update Compose and `.env` consistently.

Check the API:

```bash
curl http://<IP Address>:8001/api/dome/telemetry
```

For command testing, use Swagger at `/docs` or an HTTP client.

## Safety and operating assumptions

RoofRunner is a control component, **not a safety system**. In particular:

- The SMC must be correctly configured for motor limits, acceleration, current handling, and the two NC travel switches.
- The Pi, UART, SMC, wiring, and power system can fail independently.
- A HALTED API state is not a substitute for verifying physical motor behavior.
- If UART communication fails while the motor is energized, RoofRunner cannot guarantee delivery of a STOP command. Maintain a means to physically remove motor power.
- Automatic contradictory-limit shutdown is software detection layered on top of the SMC's own configured protections.
- The present API has **no authentication**. Do not expose port 8001 directly to the public internet or an untrusted network.
- Roof clearance, telescope parking, weather, collision avoidance, and site-specific interlocks must be addressed before unattended observatory operation. Their existence is **not** implied by this repository.

**Commission with the motor/roof mechanism safely isolated where practical.** Verify direction, limit polarity, limit action, STOP, RESET, and recovery behavior before connecting to a structure capable of damaging itself, its operator, or the equipment beneath it.

### A deliberately accepted timing characteristic

If STOP arrives while an OPEN/CLOSE command is already being transmitted, the serial worker may finish that in-flight command before sending zero speed. Waiting movement commands are invalidated; STOP remains the next priority operation. This short ordering window is understood and accepted for the current installation, which has conservative SMC acceleration and a heavy, mechanically coupled roof. It is **not** a hard real-time STOP latency guarantee.

## Troubleshooting

| Symptom | Things to check |
| --- | --- |
| API not reachable | `sudo docker compose ps`, container logs, port 8001, Pi network connectivity |
| No telemetry / `SMC_COMMUNICATION_ERROR` | UART enabled, TX/RX crossover, common GND, device mapping, baud rate, SMC power |
| OPEN/CLOSE returns `CONTROLLER_HALTED` | Read `controller.reason`; correct the underlying condition, then explicitly RESET |
| RESET fails with contradictory limits | Check AN1/AN2 switch wiring, NC polarity, and both endpoint states |
| RESET fails with nonzero `error_status` | Inspect the SMC's actual error condition and configuration |
| RESET fails with zero input voltage | Check motor supply and SMC telemetry |
| Command request times out | Inspect subsequent telemetry and physical motor condition; a timeout does not prove the command did or did not execute |
| Motor direction is wrong | Verify wiring and SMC direction configuration before connecting the roof |
| Motor doesn't reach requested speed | Check SMC-configured speed, acceleration, current limits, and active limit conditions |
| Operator is cursing | All of the above, again, in case one of the obstinate snots decides to work this time |

The serial worker polls every 500 ms by default. Cached telemetry may lag physical changes slightly.

## Hardware validation completed

The initial bench validation included:

- Startup health check and READY state.
- Telemetry reads for SMC status, speeds, voltage, temperature, current, uptime, and limit bits.
- OPEN motor operation, with the SMC enforcing its configured speed cap.
- Manual STOP of a running motor, including zero observed motor voltage and latched HALTED.
- Rejection of movement while HALTED.
- RESET after STOP, without unintended motor movement.
- RESET at an intermediate position where neither limit is active.
- Rejection of RESET while both limits are active.
- Automatic contradictory-limit HALT while stationary.
- **Automatic contradictory-limit HALT while the motor is running**, including motor stop without a manual STOP request.
- Persistence of the HALTED latch after a contradictory-limit condition clears, until successful RESET.

These tests establish observed behavior of the development hardware. They are not a substitute for final on-roof commissioning.

## Roadmap

- **ASCOM dome integration:** a separate driver/client mapping observatory operations to RoofRunner's API. 
- **Physical RESET control:** a momentary Pi GPIO button invoking the same safety checks as API RESET. Pin assignment and implementation remain pending.
- **Observatory integration:** any necessary park, clearance, weather, and operational interlocks appropriate to the finished installation.
- **Installation documentation:** final wiring, enclosure, SMC configuration export, and on-roof commissioning results.

## Development notes

The initial implementation was developed and hardware-tested on the `roofrunner-initial-dev` branch. Python code was written with assistance from ChatGPT; source files carry attribution headers. Human judgment and responsibility are suggested.  They may not be present, but they're strongly suggested.

---

*RoofRunner: because an observatory roof should open on command, close on command, stop on command, and otherwise refrain from creative interpretation.*
