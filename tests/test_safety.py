"""Startup checks, limit faults, and the HALTED safety latch."""
import pytest

from tests.fake_smc import FakeSMC


def test_healthy_controller_passes_startup_check(worker):
    snapshot = worker._health_check(FakeSMC())
    assert snapshot["success"]


def test_moving_controller_passes_health_check(worker):
    port = FakeSMC()
    port.variables[20] = 3200
    port.variables[21] = 2500
    snapshot = worker._health_check(port)
    assert snapshot["telemetry"]["current_speed"] == 2500


def test_between_limits_stopped_is_not_a_health_check_error(worker):
    port = FakeSMC()
    port.set_limits(open_active=False, closed_active=False)
    assert worker._health_check(port)["success"]


@pytest.mark.parametrize("variable,value", [(0, 1), (23, 0)])
def test_health_check_rejects_errors_and_zero_voltage(worker, variable, value):
    port = FakeSMC()
    port.variables[variable] = value
    with pytest.raises(RuntimeError):
        worker._health_check(port)


def test_health_check_rejects_both_limits_active(worker):
    port = FakeSMC()
    port.set_limits(open_active=True, closed_active=True)
    with pytest.raises(RuntimeError, match="Both OPEN and CLOSED"):
        worker._health_check(port)


def test_contradictory_limits_halt_and_stop_motor(worker):
    port = FakeSMC()
    worker._halted = False
    worker._halt_reason = None
    port.set_limits(open_active=True, closed_active=True)
    worker._handle_limit_fault(port, worker._read_telemetry(port))
    state = worker.get_snapshot()["controller"]
    assert state["state"] == "HALTED"
    assert state["reason"] == "CONTRADICTORY_LIMITS"
    assert port.stop_commands
    assert worker.submit_command("close").result()["error"]["code"] == "CONTROLLER_HALTED"


def test_single_limit_is_not_contradictory(worker):
    port = FakeSMC()
    port.set_limits(open_active=True)
    worker._handle_limit_fault(port, worker._read_telemetry(port))
    assert not port.stop_commands
    assert worker.get_snapshot()["controller"]["reason"] == "STARTUP"
