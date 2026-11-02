"""Command queue, STOP priority, RESET, and movement inhibition."""
from tests.fake_smc import FakeSMC


def ready(worker):
    worker._halted = False
    worker._halt_reason = None


def test_open_and_close_send_expected_speeds(worker):
    port = FakeSMC()
    ready(worker)
    assert worker.submit_command("open")
    worker._process_commands(port)
    assert port.variables[20] == 3200
    assert worker.submit_command("close")
    worker._process_commands(port)
    assert port.variables[20] == -3200


def test_stop_cancels_queued_movement_and_latches_halted(worker):
    port = FakeSMC()
    ready(worker)
    movement = worker.submit_command("open")
    stop = worker.submit_command("stop")
    assert movement.cancelled()
    assert worker.get_snapshot()["controller"]["state"] == "HALTED"
    worker._process_commands(port)
    assert stop.result()["success"]
    assert port.stop_commands
    assert not any(w == bytes([0x83]) for w in port.writes)


def test_movement_rejected_while_halted(worker):
    port = FakeSMC()
    result = worker.submit_command("open").result()
    assert result["error"]["code"] == "CONTROLLER_HALTED"
    worker._process_commands(port)
    assert port.writes == []


def test_reset_after_stop_restores_ready(worker):
    port = FakeSMC()
    worker.submit_command("stop")
    worker._process_commands(port)
    reset = worker.submit_command("reset")
    worker._process_commands(port)
    assert reset.result()["success"]
    assert worker.get_snapshot()["controller"]["state"] == "READY"


def test_reset_rejected_on_controller_error(worker):
    port = FakeSMC()
    port.variables[0] = 1
    reset = worker.submit_command("reset")
    worker._process_commands(port)
    assert not reset.result()["success"]
    assert worker.get_snapshot()["controller"]["state"] == "HALTED"


def test_latest_queued_movement_wins(worker):
    port = FakeSMC()
    ready(worker)
    first = worker.submit_command("open")
    second = worker.submit_command("close")
    worker._process_commands(port)
    assert first.cancelled()
    assert second.result()["success"]
    assert port.variables[20] == -3200


def test_invalid_command_rejected(worker):
    import pytest
    with pytest.raises(ValueError):
        worker.submit_command("dance")
