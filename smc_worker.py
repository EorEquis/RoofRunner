
###########################################################################
# Created : 2026-10-09 GB
# Purpose : Pololu SMC G2 serial communication, telemetry, and safety state.
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

    CLOSED_LIMIT_BIT = 128
    OPEN_LIMIT_BIT = 256

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
        self._generation = 0
        self._stop_event = threading.Event()
        self._thread = None

        self._halted = True
        self._halt_reason = "STARTUP"
        self._reset_pending = False
        self._stop_pending = False

        self._snapshot = {
            "success": False,
            "timestamp_utc": None,
            "telemetry": None,
            "error": {
                "code": "NOT_READY",
                "message": "No telemetry collected yet",
            },
        }

    def _cancel_queue(self):
        """Cancel every command still waiting in the queue.

        Caller must hold self._lock.
        """
        while True:
            try:
                item = self._commands.get_nowait()
            except queue.Empty:
                break

            item[4].cancel()

    @staticmethod
    def _get_variable(port, variable_id, signed=False):
        """Read one SMC variable using Compact Protocol."""
        SmcWorker._write_command(
            port, bytes([0xA1, variable_id])
        )

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

    def _health_check(self, port):
        """Read telemetry and reject unsafe controller conditions."""
        snapshot = self._read_telemetry(port)
        telemetry = snapshot["telemetry"]

        errors = telemetry["error_status"]
        limits = telemetry["limit_status"]

        open_active = bool(limits & self.OPEN_LIMIT_BIT)
        closed_active = bool(limits & self.CLOSED_LIMIT_BIT)

        if open_active and closed_active:
            raise RuntimeError(
                "Both OPEN and CLOSED limit switches report active"
            )

        if errors != 0:
            raise RuntimeError(
                f"SMC error_status is nonzero: {errors}"
            )

        if telemetry["input_voltage_mv"] == 0:
            raise RuntimeError(
                "SMC reports zero input voltage"
            )

        # Temperature is collected and exposed for diagnosis.
        # A shutdown threshold is deliberately not invented here.

        return snapshot

    def _handle_limit_fault(self, port, snapshot):
        """Latch and stop if both travel limits report active."""
        telemetry = snapshot["telemetry"]

        if not (
            telemetry["open_limit_active"]
            and telemetry["closed_limit_active"]
        ):
            return

        with self._lock:
            if self._halt_reason == "CONTRADICTORY_LIMITS":
                return

            self._halted = True
            self._halt_reason = "CONTRADICTORY_LIMITS"
            self._reset_pending = False
            self._stop_pending = True
            self._generation += 1
            self._cancel_queue()

        # Only the serial worker writes to the SMC. Send STOP now,
        # before processing another movement command.
        self._set_speed(port, 0)

        with self._lock:
            self._stop_pending = False

    def _process_commands(self, port):
        """Execute queued commands, honoring the safety latch."""
        while not self._stop_event.is_set():
            try:
                priority, sequence, generation, command, future = (
                    self._commands.get_nowait()
                )
            except queue.Empty:
                break

            if future.cancelled():
                continue

            with self._lock:
                valid = (
                    generation == self._generation
                    and (
                        command == "stop"
                        or (
                            command == "reset"
                            and self._reset_pending
                            and not self._stop_pending
                        )
                        or (
                            command in ("open", "close")
                            and not self._halted
                            and not self._reset_pending
                            and not self._stop_pending
                            and sequence == self._sequence
                        )
                    )
                )

            if not valid:
                future.cancel()
                continue

            if not future.set_running_or_notify_cancel():
                continue

            try:
                if command == "stop":
                    self._set_speed(port, 0)

                    with self._lock:
                        if generation == self._generation:
                            self._stop_pending = False

                elif command == "reset":
                    self._health_check(port)

                    with self._lock:
                        if (
                            generation != self._generation
                            or not self._reset_pending
                            or self._stop_pending
                        ):
                            raise RuntimeError(
                                "RESET superseded by STOP"
                            )

                        self._halted = False
                        self._halt_reason = None
                        self._reset_pending = False

                else:
                    self._write_command(port, bytes([0x83]))
                    speed = 3200 if command == "open" else -3200
                    self._set_speed(port, speed)

                future.set_result({
                    "success": True,
                    "command": command,
                    "message": "Command transmitted or completed",
                })

            except Exception as exc:
                with self._lock:
                    if generation == self._generation:
                        if command == "reset":
                            self._halted = True
                            self._halt_reason = (
                                f"HEALTH_CHECK_FAILED: {exc}"
                            )
                            self._reset_pending = False

                        elif command == "stop":
                            self._halted = True
                            self._halt_reason = (
                                f"STOP_TRANSMISSION_FAILED: {exc}"
                            )
                            self._stop_pending = False

                        else:
                            self._halted = True
                            self._halt_reason = (
                                f"MOVEMENT_COMMAND_FAILED: {exc}"
                            )
                            self._generation += 1
                            self._cancel_queue()

                future.set_result({
                    "success": False,
                    "command": command,
                    "error": {
                        "code": "SMC_COMMAND_ERROR",
                        "message": str(exc),
                    },
                })

    def _publish(self, snapshot):
        """Replace the cached telemetry snapshot."""
        with self._lock:
            self._snapshot = snapshot

    def _read_telemetry(self, port):
        """Collect SMC telemetry without interpreting roof position."""
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

        limits = telemetry["limit_status"]

        telemetry["open_limit_active"] = bool(
            limits & self.OPEN_LIMIT_BIT
        )
        telemetry["closed_limit_active"] = bool(
            limits & self.CLOSED_LIMIT_BIT
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
        """Own the serial port and perform startup initialization."""
        next_poll = time.monotonic()

        while not self._stop_event.is_set():
            try:
                with serial.Serial(
                    self.port,
                    self.baud,
                    timeout=0.2,
                    write_timeout=0.2,
                ) as port:

                    with self._lock:
                        startup = self._halt_reason == "STARTUP"
                        startup_generation = self._generation

                    if startup:
                        try:
                            snapshot = self._health_check(port)
                            self._publish(snapshot)

                            with self._lock:
                                if (
                                    self._generation == startup_generation
                                    and self._halt_reason == "STARTUP"
                                    and not self._stop_pending
                                ):
                                    self._halted = False
                                    self._halt_reason = None

                        except Exception as exc:
                            with self._lock:
                                if (
                                    self._generation == startup_generation
                                    and self._halt_reason == "STARTUP"
                                ):
                                    self._halted = True
                                    self._halt_reason = (
                                        f"STARTUP_CHECK_FAILED: {exc}"
                                    )

                    while not self._stop_event.is_set():
                        self._process_commands(port)

                        now = time.monotonic()

                        if now >= next_poll:
                            snapshot = self._read_telemetry(port)
                            self._publish(snapshot)
                            self._handle_limit_fault(port, snapshot)

                            next_poll += self.poll_interval
                            now = time.monotonic()

                            if next_poll < now:
                                missed = int(
                                    (now - next_poll) / self.poll_interval
                                ) + 1
                                next_poll += (
                                    missed * self.poll_interval
                                )

                        self._stop_event.wait(
                            min(
                                0.02,
                                max(
                                    0,
                                    next_poll - time.monotonic(),
                                ),
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

                with self._lock:
                    self._halted = True
                    self._halt_reason = (
                        f"COMMUNICATION_ERROR: {exc}"
                    )
                    self._generation += 1
                    self._reset_pending = False
                    self._cancel_queue()

                self._stop_event.wait(1.0)
                next_poll = time.monotonic()

    @staticmethod
    def _set_speed(port, speed):
        """Transmit a signed motor speed using Compact Protocol."""
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
        """Transmit all bytes or report an incomplete write."""
        written = port.write(data)

        if written != len(data):
            raise IOError(
                f"Incomplete SMC write: {written}/{len(data)} bytes"
            )

    def get_snapshot(self):
        """Return telemetry together with controller safety state."""
        with self._lock:
            snapshot = copy.deepcopy(self._snapshot)

            snapshot["controller"] = {
                "state": (
                    "HALTED" if self._halted else "READY"
                ),
                "reason": self._halt_reason,
                "movement_allowed": (
                    not self._halted
                    and not self._reset_pending
                    and not self._stop_pending
                ),
            }

        return snapshot

    def start(self):
        """Start the single serial worker."""
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
        """Stop the worker thread."""
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def submit_command(self, command):
        """Queue a command or reject it without serial activity."""
        if command not in ("open", "close", "stop", "reset"):
            raise ValueError(f"Unsupported command: {command}")

        future = Future()

        with self._lock:
            if command in ("open", "close"):
                if (
                    self._halted
                    or self._reset_pending
                    or self._stop_pending
                ):
                    future.set_result({
                        "success": False,
                        "command": command,
                        "error": {
                            "code": "CONTROLLER_HALTED",
                            "message": "Movement is inhibited",
                        },
                    })
                    return future

            if command == "reset":
                if self._stop_pending or self._reset_pending:
                    future.set_result({
                        "success": False,
                        "command": command,
                        "error": {
                            "code": "CONTROLLER_BUSY",
                            "message": (
                                "STOP or RESET is still pending"
                            ),
                        },
                    })
                    return future

            self._sequence += 1
            sequence = self._sequence

            if command == "stop":
                self._halted = True
                self._halt_reason = "STOP_REQUESTED"
                self._stop_pending = True
                self._reset_pending = False
                self._generation += 1
                self._cancel_queue()

            elif command == "reset":
                self._halted = True
                self._halt_reason = "RESET_IN_PROGRESS"
                self._reset_pending = True
                self._generation += 1
                self._cancel_queue()

            generation = self._generation
            priority = 0 if command == "stop" else 1

            self._commands.put((
                priority,
                sequence,
                generation,
                command,
                future,
            ))

        return future
