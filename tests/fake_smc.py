"""Minimal in-memory Pololu SMC Compact Protocol serial simulator."""
import threading

from smc_worker import SmcWorker


class FakeSMC:
    def __init__(self):
        self.variables = {
            0: 0, 3: 0, 20: 0, 21: 0, 23: 12000,
            24: 250, 44: 0, 28: 100, 29: 0,
        }
        self.writes = []
        self.fail_reads = False
        self.fail_writes = False
        self._pending_variable = None
        self._lock = threading.Lock()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def write(self, data):
        with self._lock:
            if self.fail_writes:
                raise OSError("simulated serial write failure")
            data = bytes(data)
            self.writes.append(data)
            if len(data) == 2 and data[0] == 0xA1:
                self._pending_variable = data[1]
            elif len(data) == 3 and data[0] in (0x85, 0x86):
                magnitude = data[1] | (data[2] << 5)
                speed = magnitude if data[0] == 0x85 else -magnitude
                self.variables[20] = speed
            return len(data)

    def read(self, size):
        with self._lock:
            if self.fail_reads:
                raise OSError("simulated serial read failure")
            if self._pending_variable is None:
                return b""
            variable = self._pending_variable
            self._pending_variable = None
            signed = SmcWorker.VARIABLES.get(
                next((name for name, pair in SmcWorker.VARIABLES.items()
                      if pair[0] == variable), ""), (None, False)
            )[1]
            return int(self.variables.get(variable, 0)).to_bytes(
                2, "little", signed=signed
            )

    def set_limits(self, *, open_active=False, closed_active=False):
        self.variables[3] = (
            (SmcWorker.OPEN_LIMIT_BIT if open_active else 0)
            | (SmcWorker.CLOSED_LIMIT_BIT if closed_active else 0)
        )

    @property
    def stop_commands(self):
        return [w for w in self.writes if w == b"\\x85\\x00\\x00"]

    @property
    def speed_commands(self):
        return [w for w in self.writes if len(w) == 3 and w[0] in (0x85, 0x86)]
