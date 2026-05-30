# Altibase pyodbc/native comparison

Date: 2026-05-30

This is a local smoke/performance comparison for the `altibase` target. It is
not an official TPC-C benchmark certification.

## Baseline

- Server: `127.0.0.1:$ALTIBASE_PORT_NO` (`20104` during these runs)
- DDL: `pytpcc/tpcc_altibase.sql`
- Schema credentials: both configs use `PYTPCC/PYTPCC`
- Scale: `warehouses=1`, `scalefactor=100`
- Workload: `duration=30`, `clients=1`
- Reset policy: every run used `--reset`, then loaded and executed with the
  backend being measured.
- Result labels: the SQL summary line includes `Altibase(pyodbc)` or
  `Altibase(native)`.

## Commands

Run from `pytpcc/`.

pyodbc:

```bash
ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
ALTIBASE_PORT_NO=${ALTIBASE_PORT_NO:?} \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
python3 tpcc.py --config ALTIBASE_ODBC_EXAMPLE --ddl tpcc_altibase.sql \
  --reset --warehouses 1 --scalefactor 100 \
  --duration 30 --clients 1 altibase --stop-on-error
```

native:

```bash
ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
ALTIBASE_PORT_NO=${ALTIBASE_PORT_NO:?} \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
PYTHONPATH=/home/et16/work/altibase-python-driver/src:${PYTHONPATH:-} \
python3 tpcc.py --config ALTIBASE_NATIVE_EXAMPLE --ddl tpcc_altibase.sql \
  --reset --warehouses 1 --scalefactor 100 \
  --duration 30 --clients 1 altibase --stop-on-error
```

## Results

The first pair was kept as a warm-up/repeatability check. The second pair is
the measured comparison.

| Backend | Role | Summary label | Load s | Elapsed s | tpmC | Total txns | Delivery | New Order | Order Status | Payment | Stock Level | Aborts | Retries | Warning |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| pyodbc | Warm-up | `Altibase(pyodbc)` | 1 | 30 | 6129 | 6856 | 239 | 3065 | 283 | 3035 | 234 | 37 | 0 | None emitted |
| native | Warm-up | `Altibase(native)` | 0 | 30 | 3964 | 4520 | 171 | 1982 | 176 | 2007 | 184 | 22 | 0 | None emitted |
| pyodbc | Measured | `Altibase(pyodbc)` | 0 | 30 | 6112 | 6698 | 259 | 3056 | 289 | 2831 | 263 | 25 | 0 | None emitted |
| native | Measured | `Altibase(native)` | 0 | 30 | 4193 | 4682 | 170 | 2097 | 184 | 2031 | 200 | 16 | 0 | None emitted |

Measured summary lines:

```text
2026-05-30 15:46:35 Altibase(pyodbc) TpmC for 1 thr 1 WH: 6112 3056 total 30 durSec, 0 retries 0.0% p50   6.98 p75   8.64 p90  10.43 p95  11.63 p99  14.65 max  28.90 6698 25
2026-05-30 15:47:13 Altibase(native) TpmC for 1 thr 1 WH: 4193 2097 total 30 durSec, 0 retries 0.0% p50  10.30 p75  12.76 p90  15.34 p95  17.61 p99  21.67 max  30.46 4682 16
```
