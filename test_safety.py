
###########################################################################
# Created : 2026-10-09 GB
# Purpose : Temporary RoofRunner HALTED and RESET safety tests.
# Notes   : Development-only. Remove before merging main.
#           Most code was generated with assistance from ChatGPT.
#           Chat title: Astrophotography N
#           OpenAI model/version: GPT-6
###########################################################################

import os
import unittest

from unittest.mock import patch

from smc_worker import SmcWorker


class FakeSerial:
    def __init__(self, variables=None):
        self.variables = {
            0: 0,
            3: 0,
            20: 0,
            21: 0,
            23: 12000,
            24: 250,
            28: 100,
            29: 0,
            44: 0,
        }

        if variables:
            self.variables.update(variables)

        self.writes = []
        self.pending_response = b""

    def write(self, data):
        data = bytes(data)
        self.writes.append(data)

        if len(data) == 2 and data[0] == 0xA1:
            variable_id = data[1]
            value = self.variables[variable_id]

            self.pending_response = (
                value & 0xFFFF
            ).to_bytes(2, "little")

        return len(data)

    def read(self, size):
        response = self.pending_response[:size]
        self.pending_response = self.pending_response[size:]
        return response


class TestSafety(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "PI_SERIAL_PORT": "/dev/serial0",
            "PI_SERIAL_BAUD": "9600",
            "SMC_POLL_INTERVAL_MS": "500",
            "SMC_COMMAND_TIMEOUT_MS": "3000",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

        self.worker = SmcWorker()
        self.serial = FakeSerial()

    def ready(self):
        """Simulate successful startup authorization."""
        self.worker._health_check(self.serial)
        self.worker._halted = False
        self.worker._halt_reason = None

    def test_initial_state_is_halted(self):
        snapshot = self.worker.get_snapshot()

        self.assertEqual(
            snapshot["controller"]["state"], "HALTED"
        )
        self.assertFalse(
            snapshot["controller"]["movement_allowed"]
        )

    def test_movement_rejected_while_halted(self):
        future = self.worker.submit_command("open")

        result = future.result()

        self.assertFalse(result["success"])
        self.assertEqual(
            result["error"]["code"], "CONTROLLER_HALTED"
        )
        self.assertEqual(self.serial.writes, [])

    def test_healthy_controller_passes_check(self):
        snapshot = self.worker._health_check(self.serial)

        self.assertTrue(snapshot["success"])
        self.assertEqual(
            snapshot["telemetry"]["input_voltage_mv"], 12000
        )

    def test_single_active_limit_is_acceptable(self):
        for limit in (128, 256):
            with self.subTest(limit=limit):
                serial_port = FakeSerial({3: limit})
                snapshot = self.worker._health_check(serial_port)
                self.assertTrue(snapshot["success"])

    def test_both_active_limits_fail(self):
        serial_port = FakeSerial({3: 384})

        with self.assertRaisesRegex(
            RuntimeError, "Both OPEN and CLOSED"
        ):
            self.worker._health_check(serial_port)

    def test_controller_error_fails_check(self):
        serial_port = FakeSerial({0: 1})

        with self.assertRaisesRegex(
            RuntimeError, "error_status"
        ):
            self.worker._health_check(serial_port)

    def test_zero_voltage_fails_check(self):
        serial_port = FakeSerial({23: 0})

        with self.assertRaisesRegex(
            RuntimeError, "zero input voltage"
        ):
            self.worker._health_check(serial_port)

    def test_stop_clears_movement_queue(self):
        self.ready()

        movement = self.worker.submit_command("open")
        stop = self.worker.submit_command("stop")

        self.assertTrue(movement.cancelled())

        self.worker._process_commands(self.serial)

        self.assertTrue(stop.result()["success"])
        self.assertEqual(
            self.worker.get_snapshot()["controller"]["state"],
            "HALTED",
        )
        self.assertEqual(
            self.serial.writes[-1],
            bytes([0x85, 0, 0]),
        )

    def test_stop_rejects_new_movement(self):
        self.ready()

        stop = self.worker.submit_command("stop")
        movement = self.worker.submit_command("close")

        self.worker._process_commands(self.serial)

        self.assertTrue(stop.result()["success"])
        self.assertFalse(movement.result()["success"])
        self.assertEqual(
            movement.result()["error"]["code"],
            "CONTROLLER_HALTED",
        )

    def test_reset_restores_ready(self):
        reset = self.worker.submit_command("reset")

        self.worker._process_commands(self.serial)

        self.assertTrue(reset.result()["success"])
        self.assertEqual(
            self.worker.get_snapshot()["controller"]["state"],
            "READY",
        )

    def test_failed_reset_remains_halted(self):
        serial_port = FakeSerial({3: 384})
        reset = self.worker.submit_command("reset")

        self.worker._process_commands(serial_port)

        self.assertFalse(reset.result()["success"])
        self.assertEqual(
            self.worker.get_snapshot()["controller"]["state"],
            "HALTED",
        )

    def test_reset_does_not_move_motor(self):
        reset = self.worker.submit_command("reset")

        self.worker._process_commands(self.serial)

        self.assertTrue(reset.result()["success"])

        motor_commands = [
            data for data in self.serial.writes
            if data[0] in (0x83, 0x85, 0x86)
        ]

        self.assertEqual(motor_commands, [])

    def test_repeated_stop_remains_halted(self):
        first = self.worker.submit_command("stop")
        self.worker._process_commands(self.serial)

        second = self.worker.submit_command("stop")
        self.worker._process_commands(self.serial)

        self.assertTrue(first.result()["success"])
        self.assertTrue(second.result()["success"])

        self.assertEqual(
            self.worker.get_snapshot()["controller"]["state"],
            "HALTED",
        )

    def test_reset_rejected_while_stop_pending(self):
        stop = self.worker.submit_command("stop")
        reset = self.worker.submit_command("reset")

        self.assertFalse(reset.result()["success"])
        self.assertEqual(
            reset.result()["error"]["code"],
            "CONTROLLER_BUSY",
        )

        self.worker._process_commands(self.serial)
        self.assertTrue(stop.result()["success"])

    def test_stop_cancels_pending_reset(self):
        reset = self.worker.submit_command("reset")
        stop = self.worker.submit_command("stop")

        self.assertTrue(reset.cancelled())

        self.worker._process_commands(self.serial)

        self.assertTrue(stop.result()["success"])
        self.assertEqual(
            self.worker.get_snapshot()["controller"]["state"],
            "HALTED",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
