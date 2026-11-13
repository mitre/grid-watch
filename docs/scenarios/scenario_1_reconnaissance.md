# Scenario 1: Reconnaissance

## Overview

| Field | Value |
|---|---|
| **Tactic** | Collection |
| **Techniques** | [T0802 - Automated Collection](https://attack.mitre.org/techniques/T0802/), [T0861 - Point & Tag Identification](https://attack.mitre.org/techniques/T0861/) |
| **Adversary** | Grid Watch DNP3 Reconnaissance (`docs/adversaries/dnp3-reconnaissance.yml`) |
| **Fact source** | Grid Watch Facts (`docs/sources/grid-watch-simulator-facts.yml`) |

## Description

The adversary reads every point on the outstation without sending a command: an integrity poll, a read of all binary inputs, and a targeted read of binary inputs 0 and 1. The outstation answers any DNP3 master without authentication, so this gives the breaker and generator states, the bus voltage and the power deficit.

![Grid Watch HMI baseline state](../images/scenario-1-reconnaissance.png)

## Facts Used

| Fact | Description | Type | Value |
|---|---|---|---|
| `dnp3.server.ip` | IP address of the outstation | string | `127.0.0.1` |
| `dnp3.local.link` | Link address of the master | int | `3` |
| `dnp3.remote.link` | Link address of the outstation | int | `1` |
| `dnp3.data.group` | Object group to read | int | `1` (binary inputs) |
| `dnp3.data.start` | First index to read | int | `0` |
| `dnp3.data.end` | Last index to read | int | `1` |

## Steps

Run the adversary with the fact source above, or add these abilities to an operation in this order:

| # | Ability | ID | Facts |
|---|---|---|---|
| 1 | DNP3 (TCP) - Integrity Poll | `1d412b2f-f4ae-3ed2-822e-55a4490a7d1a` | poll |
| 2 | DNP3 (TCP) - Read All | `8d0889f8-6801-4986-baaf-83622bf08ced` | read: `dnp3.data.group=1` |
| 3 | DNP3 (TCP) - Read | `689ee6dd-9f24-352f-90da-8d06fae7d19c` | read: `dnp3.data.group=1`, `dnp3.data.start=0`, `dnp3.data.end=1` |

![Caldera - DNP3 (TCP) Read ability fact configuration](../images/caldera-read-ability.png)

## Expected Observations

- The outstation accepts every request without authentication, and the reads do not change the grid.
- The integrity poll returns 2 binary inputs (`Group1Var2`), 2 binary outputs (`Group10Var2`) and 2 analog inputs (`Group30Var1`), plus any events since the last poll.
- `AI[0]` is the bus voltage in whole kV: 10 to 12 with the breaker closed and the generator on, otherwise 0 once it settles (about 10 seconds).
- `AI[1]` is the power deficit in kW: the load minus 600 (at least 0) with the breaker closed and the generator on, and the whole load (100 to 1500) otherwise.
- `BO[0]` and `BI[0]` are the breaker (1 = closed); `BO[1]` and `BI[1]` are the generator (1 = on). They start at 0.
- Read All and Read of group 1 return binary inputs 0 and 1 with the same values as the poll.
