# Scenario 3: Grid Disruption

## Overview

| Field | Value |
|---|---|
| **Tactic** | Impair Process Control, Impact |
| **Techniques** | [T0855 - Unauthorized Command Message](https://attack.mitre.org/techniques/T0855/), [T0831 - Manipulation of Control](https://attack.mitre.org/techniques/T0831/), [T0826 - Loss of Availability](https://attack.mitre.org/techniques/T0826/) |
| **Adversary** | Grid Watch DNP3 Grid Disruption (`docs/adversaries/dnp3-grid-disruption.yml`) |
| **Fact source** | Grid Watch Facts (`docs/sources/grid-watch-simulator-facts.yml`) |

## Description

The adversary uses both DNP3 command paths, DIRECT_OPERATE and SELECT_BEFORE_OPERATE. It stops the generator and trips the breaker, restores both, then trips the breaker again over SELECT_BEFORE_OPERATE. The outstation runs every command without authentication. Start with the breaker closed and the generator on (use the HMI buttons).

![Grid Watch HMI grid disruption state](../images/scenario-3-grid-disruption.png)

## Facts Used

| Fact | Description | Type | Value |
|---|---|---|---|
| `dnp3.server.ip` | IP address of the outstation | string | `127.0.0.1` |
| `dnp3.local.link` | Link address of the master | int | `3` |
| `dnp3.remote.link` | Link address of the outstation | int | `1` |
| `dnp3.operate.indices` | Binary output to operate | string | `0` (breaker), `1` (generator) |
| `dnp3.operate.mode` | Operate mode | string | `DIRECT_OPERATE`, `SELECT_BEFORE_OPERATE` |
| `dnp3.operate.type` | Control relay output block type | string | `LATCH_ON`, `LATCH_OFF` |
| `dnp3.operate.tcc` | Trip-close code | string | `NUL` |

## Control Data

| Control | DNP3 Point | Value |
|---|---|---|
| BreakerControl | `BO[0]` | `LATCH_OFF` (open), `LATCH_ON` (closed) |
| GenControl | `BO[1]` | `LATCH_OFF` (off), `LATCH_ON` (on) |

## Steps

Add these abilities to an operation in this order and choose the facts shown for each step. If you run the adversary instead, Caldera runs each Operate step once for every combination of `dnp3.operate.indices`, `dnp3.operate.mode` and `dnp3.operate.type` in the fact source, which ends with the breaker and the generator latched on.

| # | Ability | ID | Facts |
|---|---|---|---|
| 1 | DNP3 (TCP) - Integrity Poll | `1d412b2f-f4ae-3ed2-822e-55a4490a7d1a` | baseline |
| 2 | DNP3 (TCP) - Operate | `5a073c32-e022-3724-85ad-7192464287b8` | stop generator: `dnp3.operate.indices=1`, `dnp3.operate.mode=DIRECT_OPERATE`, `dnp3.operate.type=LATCH_OFF` |
| 3 | DNP3 (TCP) - Operate | `5a073c32-e022-3724-85ad-7192464287b8` | trip breaker: `dnp3.operate.indices=0`, `dnp3.operate.mode=DIRECT_OPERATE`, `dnp3.operate.type=LATCH_OFF` |
| 4 | DNP3 (TCP) - Operate | `5a073c32-e022-3724-85ad-7192464287b8` | close breaker: `dnp3.operate.indices=0`, `dnp3.operate.mode=DIRECT_OPERATE`, `dnp3.operate.type=LATCH_ON` |
| 5 | DNP3 (TCP) - Operate | `5a073c32-e022-3724-85ad-7192464287b8` | start generator: `dnp3.operate.indices=1`, `dnp3.operate.mode=DIRECT_OPERATE`, `dnp3.operate.type=LATCH_ON` |
| 6 | DNP3 (TCP) - Operate | `5a073c32-e022-3724-85ad-7192464287b8` | trip breaker: `dnp3.operate.indices=0`, `dnp3.operate.mode=SELECT_BEFORE_OPERATE`, `dnp3.operate.type=LATCH_OFF` |
| 7 | DNP3 (TCP) - Integrity Poll | `1d412b2f-f4ae-3ed2-822e-55a4490a7d1a` | verify |

## Expected Observations

- Every Operate step prints `Result Summary: SUCCESS`, over DIRECT_OPERATE and SELECT_BEFORE_OPERATE alike. The outstation asks for no authentication.
- After steps 2 and 3 the HMI shows the generator off and the breaker open, the voltage trace falls to 0 kV and the deficit rises to the whole load.
- After steps 4 and 5 the voltage climbs back to 10 to 12 kV within about 10 seconds.
- After step 6 the breaker is open again and the voltage falls to 0 kV.
- The final integrity poll shows `BO[0]` at 0, `BO[1]` at 1, `AI[0]` falling to 0 kV and `AI[1]` at the whole load, 100 to 1500 kW. DNP3 reports analog values as whole numbers.
