import serial
import time


class SmcG2Serial:
    def __init__(self, port):
        self.port = port

    def send_command(self, cmd, *data_bytes):
        self.port.write(bytes([cmd] + list(data_bytes)))

    def exit_safe_start(self):
        self.send_command(0x83)

    def set_target_speed(self, speed):
        if not -3200 <= speed <= 3200:
            raise ValueError("Speed must be between -3200 and 3200")

        cmd = 0x85 if speed >= 0 else 0x86
        speed = abs(speed)
        self.send_command(cmd, speed & 0x1F, (speed >> 5) & 0x7F)

    def get_variable(self, variable_id):
        self.send_command(0xA1, variable_id)
        result = self.port.read(2)

        if len(result) != 2:
            raise RuntimeError(
                f"Variable {variable_id}: expected 2 bytes, got {len(result)}"
            )

        return int.from_bytes(result, byteorder="little")

    def get_variable_signed(self, variable_id):
        value = self.get_variable(variable_id)
        return value - 65536 if value >= 32768 else value


VARIABLES = [
    (0,  "Error status",   False),
    (3,  "Limit status",   False),
    (20, "Target speed",   True),
    (21, "Current speed",  True),
    (23, "Input voltage",  False),
    (24, "Temperature",    False),
]


def report_variables(smc, heading):
    print(f"\n=== {heading} ===")

    for variable_id, name, signed in VARIABLES:
        if signed:
            value = smc.get_variable_signed(variable_id)
        else:
            value = smc.get_variable(variable_id)

        print(f"{name:<16} (ID {variable_id:>2}): {value}")

    print()


def main():
    with serial.Serial(
        "/dev/serial0",
        9600,
        timeout=0.5,
        write_timeout=0.5
    ) as port:

        smc = SmcG2Serial(port)
        smc.exit_safe_start()

        report_variables(smc, "INITIAL STATUS")

        print("Waiting 5 seconds...")
        time.sleep(5)

        print("Setting motor speed to +1600...")
        smc.set_target_speed(1600)

        try:
            while True:
                report_variables(smc, "MOTOR RUNNING")
                time.sleep(5)

        except KeyboardInterrupt:
            print("\nStopping motor...")
            smc.set_target_speed(0)
            time.sleep(1)
            report_variables(smc, "FINAL STATUS")
            print("Test complete.")


if __name__ == "__main__":
    main()