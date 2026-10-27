# Cell PLC

The robot cell is controlled by an Allen-Bradley **1769-L32E** CompactLogix PLC. The AMS and the IMU nodes don't control it; they only **read** three of its tags over EtherNet/IP (CIP, TCP port 44818) with [pycomm3](https://github.com/ottowayi/pycomm3).

| | |
| --- | --- |
| Address | 192.168.1.103 |
| Identity | `1769-L32E/A LOGIX5332E`, firmware 17.4 |
| Read by | `fastapi-app` (`fast_server/plc_listener.py`) and the IMU edge nodes (`imu_edge/plc_signals.py`) |

## Tags

All three are **DINT** pulses (0 → 1 → 0). Readers count rising edges, polling every 50 ms.

| Tag | Meaning | Used by |
| --- | --- | --- |
| `Data_Start` | The robot run is starting | IMU nodes in PLC trigger mode start sending |
| `IMU_Tare` | Tare the IMUs | IMU nodes tare |
| `Db_Stop` | The robot run is done | IMU nodes stop sending; `fastapi-app` stops the recording session |

How these are used is described in [PLC auto stop](/operations/plc-auto-stop).

::: info Placeholder
TODO: where the PLC program lives, who maintains it, and how the tags are set in the robot/PLC logic.
:::
