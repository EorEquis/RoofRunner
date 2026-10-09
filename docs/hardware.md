# RoofRunner — Hardware Documentation

## 1. Overview

RoofRunner is a Raspberry Pi-based controller for the TriStar Observatory roll-off roof.

Its primary hardware components are:

- **Raspberry Pi 3 Model B** — application logic, GPIO monitoring, serial communication, and network interface.
- **Pololu Simple Motor Controller G2 18v15** — controls the roof motor.
- **12V DC motor supply** — supplies motor power through the Pololu controller.
- **Two NC roof limit reed switches** — identify fully open and fully closed positions.
- **5V cooling fan** — powered directly from the Raspberry Pi GPIO header.
- **Custom 3D-printed PLA enclosure** — houses the Pi, SMC, fan, and connectors.

The Raspberry Pi communicates with the Pololu controller using TTL UART. The Pololu handles motor power and its configured limit-switch behavior.

---

## 2. Raspberry Pi GPIO Wiring

### 2.1 Physical header connections

| Physical pin | BCM GPIO | Wire color | Function | Destination |
|---|---|---|---|---|
| 4 | — | 🔴 Red | +5V | Cooling fan positive |
| 6 | — | ⚫ Black | Ground | Cooling fan negative |
| 8 | GPIO14 | 🟡 Yellow | UART TX | Pololu RX |
| 10 | GPIO15 | 🟢 Green | UART RX | Pololu TX |
| 12 | GPIO18 | 🟠 Orange | SMC error input | Pololu ERR |
| 14 | — | ⚫ Black | Common ground | Pololu GND |

**Important:** Pin numbers in this table are physical Raspberry Pi header pin numbers, not BCM GPIO numbers.

### 2.2 UART crossover

```text
Raspberry Pi                 Pololu SMC G2
------------                 -------------

GPIO14 / TX  (YELLOW) -----> RX

GPIO15 / RX  (GREEN)  <----- TX

GPIO18      (ORANGE) <----- ERR

GND         (BLACK)  ------ GND
```

## 3. Power

### 3.1 Motor supply

The Pololu SMC G2 18v15 receives a nominal **12V DC supply** through its VIN and GND power connections.

The roof motor connects to the SMC motor-output terminals.

### 3.2 Raspberry Pi supply

5V power via micro-usb

### 3.3 Enclosure connections

Two distinct Powerpole connector pairs.

| Connector pair | Purpose |
|---|---|
| Power pair | 12V motor supply input and motor output connections |
| Limit-switch pair | Roof open/closed limit-switch connections |

---

## 4. Roof Limit Switches

Two **normally-closed (NC)** limit reed switches:

