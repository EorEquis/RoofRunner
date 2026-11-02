# Important Notes

Here are a few RoofRunner behaviors to be aware of.  These are "by design".  The system trusts the motor controller to do its job with every movement, however these specific edge cases could allow behavior that seems unexpected or surprising.  They do not represent risk beyond any normal movement command.

## READY while the roof is moving

If the Raspberry Pi restarts during roof movement, the SMC may continue the previously commanded movement. On startup, RoofRunner checks SMC communication, error status, limit consistency, and input voltage. If those checks pass, RoofRunner enters `READY` even if the motor is still moving. `READY` means the controller passed its health checks; it does not mean the roof is stationary.

## Movement after a communication failure

If serial communication fails during movement, RoofRunner latches `HALTED` with a `COMMUNICATION_ERROR` reason and rejects further movement commands. It cannot stop the motor while communication is unavailable. When communication returns, RoofRunner resumes telemetry but does not automatically send STOP. The SMC may continue the previously commanded movement until its configured limit stops it. RoofRunner remains `HALTED` until a successful RESET.

## Communication failure while STOP is pending

If serial communication fails while a STOP command is pending, RoofRunner enters `HALTED` and cancels queued commands, but may retain the pending STOP flag. After communication returns, RESET can continue to return `CONTROLLER_BUSY` even though no STOP command is being processed. Restarting RoofRunner clears this in-memory condition; startup then performs its normal health check.
