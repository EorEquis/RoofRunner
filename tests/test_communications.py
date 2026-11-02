"""Serial protocol, startup, and communication-loss behavior."""
import time

import pytest

from tests.fake_smc import FakeSMC


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for worker state")


def test_compact_protocol_reads_signed_speed(worker):
    port = FakeSMC()
    port.variables[21] = -1200
    snapshot = worker._read_telemetry(port)
    assert snapshot["telemetry"]["current_speed"] == -1200


def test_short_serial_read_raises_timeout(worker):
    class ShortRead(FakeSMC):
        def read(self, size):
            return bytes([0])
    with pytest.raises(TimeoutError):
        worker._read_telemetry(ShortRead())


def test_startup_becomes_ready_even_when_motor_moving(worker, monkeypatch):
    port = FakeSMC()
    port.variables[20] = 3200
    port.variables[21] = 2800
    monkeypatch.setattr("smc_worker.serial.Serial", lambda *a, **kw: port)
    worker.start()
    try:
        wait_until(lambda: worker.get_snapshot()["controller"]["state"] == "READY")
        assert not port.stop_commands
    finally:
        worker.stop()


def test_communication_loss_latches_halt_without_stop_on_reconnect(worker, monkeypatch):
    port = FakeSMC()
    port.variables[20] = 3200
    port.variables[21] = 2800
    monkeypatch.setattr("smc_worker.serial.Serial", lambda *a, **kw: port)
    worker.start()
    try:
        wait_until(lambda: worker.get_snapshot()["controller"]["state"] == "READY")
        port.fail_reads = True
        wait_until(lambda: worker.get_snapshot()["controller"]["reason"] is not None
                   and worker.get_snapshot()["controller"]["reason"].startswith("COMMUNICATION_ERROR"))
        port.fail_reads = False
        wait_until(lambda: worker.get_snapshot()["success"])
        assert worker.get_snapshot()["controller"]["state"] == "HALTED"
        assert not port.stop_commands
        assert port.variables[20] == 3200
    finally:
        worker.stop()


def test_failed_speed_write_halts_command_processing(worker):
    port = FakeSMC()
    worker._halted = False
    worker._halt_reason = None
    port.fail_writes = True
    command = worker.submit_command("open")
    worker._process_commands(port)
    assert not command.result()["success"]
    assert worker.get_snapshot()["controller"]["state"] == "HALTED"
