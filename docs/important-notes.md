# Important Notes

## READY while the roof is moving

If the Raspberry Pi restarts during roof movement, the SMC may continue the previously commanded movement. On startup, RoofRunner checks SMC communication, error status, limit consistency, and input voltage. If those checks pass, RoofRunner enters `READY` even if the motor is still moving. `READY` means the controller passed its health checks; it does not mean the roof is stationary.

## Movement after a communication failure

If serial communication fails during movement, RoofRunner latches `HALTED` with a `COMMUNICATION_ERROR` reason and rejects further movement commands. It cannot stop the motor while communication is unavailable. When communication returns, RoofRunner resumes telemetry but does not automatically send STOP. The SMC may continue the previously commanded movement until its configured limit stops it. RoofRunner remains `HALTED` until a successful RESET.
