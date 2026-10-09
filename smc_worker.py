
###########################################################################
# Created : 2026-10-09 GB
# Purpose : Communicates over serial with the Pololu SMC G2.
#           Collects and caches telemetry; executes queued motor commands.
# Notes   : Most code was generated with assistance from ChatGPT.
#           Chat title: Astrophotography N
#           OpenAI model/version: GPT-6
###########################################################################

import copy
import os
import queue
import serial
import threading
import time

from concurrent.futures import Future
from datetime import datetime, timezone
from dotenv import load_dotenv


load_dotenv()


class SmcWorker:
    VARIABLES = {
        "error_status": (0, False),
        "limit_status": (3, False),
        "target_speed": (20, True),
        "current_speed": (21, True),
        "input_voltage_mv": (23, False),
        "temperature_tenths_c": (24, False),
        "motor_current_ma": (44, False),
    }

    def __init__(self):
        self.port = os.environ["PI_SERIAL_PORT"]
        self.baud = int(os.environ["PI_SERIAL_BAUD"])
        self.poll_interval = (
            int(os.environ["SMC_POLL_INTERVAL_MS"]) / 1000.0
        )
        self.command_timeout = (
            int(os.environ["SMC_COMMAND_TIMEOUT_MS"]) / 1000.0
        )

        if self.poll_interval <= 0:
            raise ValueError("SMC_POLL_INTERVAL_MS must be positive")

        if self.command_timeout <= 0:
            raise ValueError("SMC_COMMAND_TIMEOUT_MS must be positive")

        self._commands = queue.PriorityQueue()
        self._lock = threading.Lock()
        self._sequence = 0
        self._stop_event = threading.Event()
        self._thread = None

        self._snapshot = {
            "success": False,
            "timestamp_utc": None,
            "telemetry": None,
            "error": {
                "code": "NOT_READY",
                "message": "No telemetry collected yet",
            },
        }

    @staticmethod
    def _get_variable(port, variable_id, signed=False):
        """Read a 16-bit SMC variable using Compact Protocol."""
        port.write(bytes([0xA1, variable_id]))
        response = port.read(2)

        if len(response) != 2:
            raise TimeoutError(
                f"SMC variable {variable_id}: "
                f"expected 2 bytes, received {len(response)}"
            )

        return int.from_bytes(
            response,
            byteorder="little",
            signed=signed,
        )

    def _process_commands(self, port):
        """Execute valid commands, prioritizing STOP."""
        while not self._stop_event.is_set():
            try:
                priority, sequence, command, deadline, future = (
                    self._commands.get_nowait()
                )
            except queue.Empty:
                break

            if future.cancelled():
                continue

            if time.monotonic() >= deadline:
                future.cancel()
                continue

            with self._lock:
                superseded = sequence < self._sequence

            if superseded and command != "stop":
                future.cancel()
                continue

            # Atomically mark the command as executing.
            # Once this succeeds, cancellation cannot claim
            # the command was never transmitted.
            if not future.set_running_or_notify_cancel():
                continue

            try:
                if command == "stop":
                    self._set_speed(port, 0)
                else:
                    self._write_command(port, bytes([0x83]))
                    speed = 3200 if command == "open" else -3200
                    self._set_speed(port, speed)

                future.set_result({
                    "success": True,
                    "command": command,
                    "message": "Command transmitted to SMC",
                })

            except Exception as exc:
                future.set_result({
                    "success": False,
                    "command": command,
                    "error": {
                        "code": "SMC_COMMAND_ERROR",
                        "message": str(exc),
                    },
                })

    def _publish(self, snapshot):
        """Atomically replace the shared telemetry snapshot."""
        with self._lock:
            self._snapshot = snapshot

    def _read_telemetry(self, port):
        """Read the agreed SMC telemetry variables."""
        telemetry = {}

        for name, (variable_id, signed) in self.VARIABLES.items():
            telemetry[name] = self._get_variable(
                port, variable_id, signed
            )

        uptime_low = self._get_variable(port, 28)
        uptime_high = self._get_variable(port, 29)

        telemetry["uptime_ms"] = (
            (uptime_high << 16) | uptime_low
        )

        timestamp = datetime.now(
            timezone.utc
        ).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )

        return {
            "success": True,
            "timestamp_utc": timestamp,
            "telemetry": telemetry,
        }

    def _run(self):
        """Own the UART, process commands, and poll telemetry."""
        next_poll = time.monotonic()

        while not self._stop_event.is_set():
            try:
                with serial.Serial(
                    self.port,
                    self.baud,
                    timeout=0.2,
                    write_timeout=0.2,
                ) as port:

                    while not self._stop_event.is_set():
                        self._process_commands(port)

                        now = time.monotonic()

                        if now >= next_poll:
                            snapshot = self._read_telemetry(port)
                            self._publish(snapshot)

                            next_poll += self.poll_interval
                            now = time.monotonic()

                            if next_poll < now:
                                missed = int(
                                    (now - next_poll) / self.poll_interval
                                ) + 1
                                next_poll += missed * self.poll_interval

                        self._stop_event.wait(
                            min(
                                0.02,
                                max(0, next_poll - time.monotonic()),
                            )
                        )

            except Exception as exc:
                previous = self.get_snapshot()

                self._publish({
                    "success": False,
                    "timestamp_utc": previous["timestamp_utc"],
                    "telemetry": None,
                    "error": {
                        "code": "SMC_COMMUNICATION_ERROR",
                        "message": str(exc),
                    },
                })

                self._stop_event.wait(1.0)
                next_poll = time.monotonic()

    @staticmethod
    def _set_speed(port, speed):
        """Send a signed motor speed using SMC Compact Protocol."""
        # Clamp speed to protocol limits. The SMC enforces its
        # configured motor speed limits.
        speed = max(-3200, min(3200, speed))

        command = 0x85 if speed >= 0 else 0x86
        magnitude = abs(speed)

        SmcWorker._write_command(port, bytes([
            command,
            magnitude & 0x1F,
            (magnitude >> 5) & 0x7F,
        ]))

    @staticmethod
    def _write_command(port, data):
        """Write a complete SMC command or report failure."""
        written = port.write(data)

        if written != len(data):
            raise IOError(
                f"Incomplete SMC write: {written}/{len(data)} bytes"
            )

    def get_snapshot(self):
        """Return the latest published telemetry snapshot."""
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def start(self):
        """Start the single serial I/O worker."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("SMC worker is already running")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="smc-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """Request worker shutdown and wait for it to exit."""
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def submit_command(self, command):
        """Queue a command with a deadline and return its Future."""
        if command not in ("open", "close", "stop"):
            raise ValueError(f"Unsupported command: {command}")

        future = Future()
        deadline = time.monotonic() + self.command_timeout

        with self._lock:
            self._sequence += 1
            sequence = self._sequence

            priority = 0 if command == "stop" else 1

            self._commands.put((
                priority,
                sequence,
                command,
                deadline,
                future,
            ))

        return future
