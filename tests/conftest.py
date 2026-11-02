"""Shared fixtures for RoofRunner tests; never opens a real serial device."""
import pytest
from smc_worker import SmcWorker


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setenv("PI_SERIAL_PORT", "FAKE")
    monkeypatch.setenv("PI_SERIAL_BAUD", "115200")
    monkeypatch.setenv("SMC_POLL_INTERVAL_MS", "20")
    monkeypatch.setenv("SMC_COMMAND_TIMEOUT_MS", "1000")
    return SmcWorker()
