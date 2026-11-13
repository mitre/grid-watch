# Scenario 2: Unauthorized Control

## Overview

| Field | Value |
|---|---|
| **Tactic** | Impair Process Control, Impact |
| **Techniques** | [T0855 - Unauthorized Command Message](https://attack.mitre.org/techniques/T0855/), [T0831 - Manipulation of Control](https://attack.mitre.org/techniques/T0831/), [T0826 - Loss of Availability](https://attack.mitre.org/techniques/T0826/) |
| **Adversary** | Grid Watch DNP3 Unauthorized Control (`docs/adversaries/dnp3-unauthorized-control.yml`) |
| **Fact source** | Grid Watch Facts (`docs/sources/grid-watch-simulator-facts.yml`) |

## Description

The adversary sends DIRECT_OPERATE commands that trip the breaker and stop the generator. The outstation runs both without authentication, the bus voltage collapses and the load goes unserved. Start with the breaker closed and the generator on (use the HMI buttons) so there is something to disrupt.

![Grid Watch HMI unauthorized control state](../images/scenario-2-unauthorized-control.png)

## Facts Used

| Fact | Description | Type | Value |
|---|---|---|---|
| `dnp3.server.ip` | IP address of the outstation | string | `127.0.0.1` |
| `dnp3.local.link` | Link address of the master | int | `3` |
| `dnp3.remote.link` | Link address of the outstation | int | `1` |
| `dnp3.operate.indices` | Binary output to operate | string | `0` (breaker), `1` (generator) |
| `dnp3.operate.mode` | Operate mode | string | `DIRECT_OPERATE` |
| `dnp3.operate.type` | Control relay output block type | string | `LATCH_OFF` |
| `dnp3.operate.tcc` | Trip-close code | string | `NUL` |

## Control Data

| Control | DNP3 Point | Value |
|---|---|---|
| BreakerControl | `BO[0]` | `LATCH_OFF` (open) |
| GenControl | `BO[1]` | `LATCH_OFF` (off) |

## Steps

Add these abilities to an operation in this order and choose the facts shown for each step. If you run the adversary instead, Caldera runs each Operate step once for every combination of `dnp3.operate.indices`, `dnp3.operate.mode` and `dnp3.operate.type` in the fact source, which ends with the breaker and the generator latched on.

| # | Ability | ID | Facts |
|---|---|---|---|
| 1 | DNP3 (TCP) - Integrity Poll | `1d412b2f-f4ae-3ed2-822e-55a4490a7d1a` | baseline |
| 2 | DNP3 (TCP) - Operate | `5a073c32-e022-3724-85ad-7192464287b8` | trip breaker: `dnp3.operate.indices=0`, `dnp3.operate.mode=DIRECT_OPERATE`, `dnp3.operate.type=LATCH_OFF` |
| 3 | DNP3 (TCP) - Operate | `5a073c32-e022-3724-85ad-7192464287b8` | stop generator: `dnp3.operate.indices=1`, `dnp3.operate.mode=DIRECT_OPERATE`, `dnp3.operate.type=LATCH_OFF` |
| 4 | DNP3 (TCP) - Integrity Poll | `1d412b2f-f4ae-3ed2-822e-55a4490a7d1a` | verify |

## Expected Observations

- Each Operate step prints `Result Summary: SUCCESS`. The outstation accepts the commands without authentication, and the PLC logs `CONTROL: BO[0] <- False (code=LATCH_OFF)` and `CONTROL: BO[1] <- False (code=LATCH_OFF)`.
- The final integrity poll shows `BO[0]`, `BO[1]`, `BI[0]` and `BI[1]` at 0.
- `AI[0]` falls from 10 to 12 kV to 0 kV within about 10 seconds. DNP3 reports analog values as whole numbers.
- `AI[1]` rises to the whole load, 100 to 1500 kW.
- The HMI shows the breaker open, the generator off and the voltage trace dropping to zero.
