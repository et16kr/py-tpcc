# Altibase TPC-C 테스트 사전 조사

작성일: 2026-05-30

## 목적

`py-tpcc`를 로컬 Altibase 서버(`/home/et16/work/altidev4`, port `$ALTIBASE_PORT_NO`) 대상으로 실행하고, Python 접속 경로를 다음 두 가지로 비교할 수 있는지 확인했다.

- `pyodbc`
- `/home/et16/work/altibase-python-driver`

## 현재 환경 확인

Altibase 서버는 `ALTIBASE_PORT_NO`가 가리키는 포트에서 실행 중이다. 현재 확인 값은 `20104`이다.

```bash
test -n "${ALTIBASE_PORT_NO:-}" && ss -ltnp | rg ":(${ALTIBASE_PORT_NO}|20300|17730)\b"
```

확인 결과:

```text
LISTEN 0 128 0.0.0.0:20104 0.0.0.0:* users:(("altibase",pid=680140,fd=51))
```

ODBC 설정은 다음처럼 등록되어 있다.

```text
/etc/odbcinst.ini
[ALTIBASE_HDB_ODBC_64bit]
Driver=/home/et16/work/altidev4/altibase_home/lib/libaltibase_odbc-64bit-ul64.so

/etc/odbc.ini
[ALTIBASE_LOCAL]
Driver=ALTIBASE_HDB_ODBC_64bit
Server=127.0.0.1
Database=mydb
NLS_USE=US7ASCII
LongDataCompat=ON
```

## Python 드라이버 상태

시스템 Python 기준:

- `pyodbc`는 설치되어 있음: `5.1.0`, `paramstyle=qmark`
- `altibase` 모듈은 전역 Python에 설치되어 있지 않음
- `PYTHONPATH=/home/et16/work/altibase-python-driver/src`를 주면 import 가능

`altibase-python-driver`는 DB-API 2.0 드라이버이며 `paramstyle=qmark`이다. 따라서 `pyodbc`와 같은 `?` placeholder SQL을 공유할 수 있다.

필요 환경 예:

```bash
export ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home
export LD_LIBRARY_PATH="$ALTIBASE_HOME/lib:${LD_LIBRARY_PATH:-}"
export PYTHONPATH=/home/et16/work/altibase-python-driver/src
```

## 연결 확인 결과

### pyodbc

DSN 연결은 성공했다.

```python
pyodbc.connect("DSN=ALTIBASE_LOCAL;UID=SYS;PWD=MANAGER")
```

`SELECT 1 FROM dual` 결과:

```text
ok DSN=ALTIBASE_LOCAL (1,)
```

드라이버명을 직접 넣은 연결 문자열은 실패했다.

```text
Driver=ALTIBASE_HDB_ODBC_64bit;Server=127.0.0.1;Port=${ALTIBASE_PORT_NO};...
```

오류:

```text
HY024 Invalid attribute value
```

따라서 `pyodbc` 경로는 우선 DSN 기반으로 사용하는 것이 안전하다.

### altibase-python-driver

키워드 연결과 raw connection string 연결 모두 성공했다.

```python
import os

altibase.connect(
    host="127.0.0.1",
    port=int(os.environ["ALTIBASE_PORT_NO"]),
    user="SYS",
    password="MANAGER",
    nls_use="UTF8",
    connect_timeout=5,
)
```

결과:

```text
ok kwargs (1,)
ok connstr (1,)
```

2026-05-30 재확인:

- `PYTHONPATH=/home/et16/work/altibase-python-driver/src`로 import 성공
- `altibase.Connection`, `altibase.Cursor` 사용 가능
- `SELECT 1 FROM dual` 결과 `(1,)`
- `driver_info().dbms_name` 결과 `Altibase`
- `ping(roundtrip=True)` 결과 `True`
- `/home/et16/work/altibase-python-driver/.venv/bin/python -m pytest -q tests/test_integration_connection.py::test_connection_close_is_idempotent tests/test_integration_connection.py::test_connection_information_and_health_methods_against_server` 결과 `2 passed`
- `ALTIBASE_PASSWORD`를 설정한 `python3 -m altibase.diagnose --server-probe`는 server probe를 `OK connected and SELECT 1 FROM DUAL returned a row`로 보고함
- 단, 전체 diagnose 결과는 SDK include 디렉터리에 `sqlcli.h`가 없어 `Build-time SDK: FAIL`이다. 현재 runtime import와 server connection에는 문제가 없지만, 새 native extension rebuild에는 header 보강이 필요하다.

## py-tpcc 구조 확인

`py-tpcc`는 `pytpcc/drivers/*driver.py` 파일명을 CLI의 target system으로 사용한다.

관련 위치:

- `pytpcc/tpcc.py`
  - `createDriverClass(name)`이 `drivers.<name>driver`를 import한다.
  - `getDrivers()`가 `./drivers/*driver.py`를 스캔한다.
- 현재 Altibase 전용 드라이버는 없음
- SQL 계열 구현은 `sqlitedriver.py`, `postgresqldriver.py`가 참고 대상

즉 `py-tpcc`를 Altibase에서 실행하려면 `pytpcc/drivers/altibasedriver.py` 또는 비교용으로 `altibaseodbcdriver.py`를 추가해야 한다.

## DDL 호환성 확인

기본 `pytpcc/tpcc.sql`은 Altibase에 그대로 적용되지 않는다.

실패한 항목:

| 항목 | 현재 DDL | 결과 | 대응 |
| --- | --- | --- | --- |
| 작은 정수 타입 | `TINYINT` | `Data type module (Name="TINYINT") not found` | `SMALLINT`로 변경 |
| timestamp default | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL` | `No default value can be specified for a TIMESTAMP column` | Altibase용 DDL에서 `DATE` 사용 권장 |
| 조건부 drop | `DROP TABLE IF EXISTS ...` | SQL syntax error | 테이블 의존성 역순 drop 후 "없음" 오류 무시 |

`TINYINT -> SMALLINT`, `TIMESTAMP -> DATE`, 주석 처리된 SQL 라인 제거를 적용한 DDL은 임시 유저에서 전체 생성에 성공했다.

생성 확인 테이블:

```text
CUSTOMER
DISTRICT
HISTORY
ITEM
NEW_ORDER
ORDERS
ORDER_LINE
STOCK
WAREHOUSE
```

## datetime 바인딩 확인

Altibase `TIMESTAMP` 컬럼에 Python `datetime.datetime` 값을 바인딩하면 두 드라이버 모두 실패했다.

오류:

```text
Invalid literal
```

같은 값을 `DATE` 컬럼에 바인딩하면 두 드라이버 모두 성공했다.

따라서 Altibase용 TPC-C DDL에서는 `C_SINCE`, `H_DATE`, `O_ENTRY_D`, `OL_DELIVERY_D` 같은 시간 컬럼을 `DATE`로 정의하는 것이 현재 확인된 안전 경로다.

## SQL 호환성 확인

확인 결과:

- `?` placeholder는 WHERE 조건에서 정상 동작
- `LIMIT 1`은 Altibase에서 정상 동작
- `SELECT ? FROM dual`은 host variable 사용 위치 문제로 실패
- `FETCH FIRST 1 ROWS ONLY`는 현재 서버에서 실패

기존 SQLite 스타일 쿼리의 `?` placeholder와 `LIMIT 1`은 대체로 Altibase에 맞다. PostgreSQL 드라이버의 `%s`, `%s::integer`, PostgreSQL 전용 reset/loadStart SQL은 그대로 사용할 수 없다.

## 필요한 py-tpcc 변경 범위

최소 변경:

1. Altibase용 DDL 추가
   - 예: `pytpcc/tpcc_altibase.sql`
   - `TINYINT`를 `SMALLINT`로 변경
   - `TIMESTAMP`를 `DATE`로 변경
   - 주석 처리된 SQL이 statement split에 섞이지 않도록 정리

2. Altibase DB-API 공통 드라이버 추가
   - 예: `pytpcc/drivers/altibasedriver.py`
   - `altibase-python-driver`와 `pyodbc`가 같은 SQL/transaction 구현을 공유하도록 구성
   - config에서 backend를 선택:
     - `backend = native`
     - `backend = pyodbc`

3. reset 구현
   - Altibase는 `DROP TABLE IF EXISTS`가 안 되므로 의존성 역순으로 drop
   - 권장 순서:
     - `ORDER_LINE`
     - `NEW_ORDER`
     - `ORDERS`
     - `HISTORY`
     - `CUSTOMER`
     - `STOCK`
     - `DISTRICT`
     - `ITEM`
     - `WAREHOUSE`

4. config 예시 추가
   - native:
     - host `127.0.0.1`
     - port from `ALTIBASE_PORT_NO`
     - user/password
     - nls_use `UTF8`
   - pyodbc:
     - dsn `ALTIBASE_LOCAL`
     - user/password

## 실행 예시 초안

Native driver 경로:

```bash
cd /home/et16/work/py-tpcc/pytpcc

ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
ALTIBASE_PORT_NO=${ALTIBASE_PORT_NO:?} \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
PYTHONPATH=/home/et16/work/altibase-python-driver/src \
python3 tpcc.py --config altibase-native.config --ddl tpcc_altibase.sql \
  --reset --warehouses 1 --scalefactor 100 --duration 10 --clients 1 \
  altibase --stop-on-error
```

pyodbc 경로:

```bash
cd /home/et16/work/py-tpcc/pytpcc

ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
ALTIBASE_PORT_NO=${ALTIBASE_PORT_NO:?} \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
python3 tpcc.py --config altibase-pyodbc.config --ddl tpcc_altibase.sql \
  --reset --warehouses 1 --scalefactor 100 --duration 10 --clients 1 \
  altibase --stop-on-error
```

위 명령은 드라이버/DDL 추가 후의 예상 형태다. 현재 레포 상태에서는 아직 `altibase` target driver가 없어서 바로 실행할 수 없다.

## 주의 사항

- `/home/et16/work/altibase-python-driver`는 `altibase` 모듈 import와 기본 연결은 성공했지만, `CREATE USER/GRANT/DROP USER` 후 프로세스 종료 시 한 차례 segfault가 관찰되었다.
- 이후 짧은 connection integration pytest 2건은 통과했으며, 단순 connection close/info/ping 경로에서는 재현되지 않았다.
- 일반 `SELECT`, DDL 생성, `DATE` 바인딩, 기본 insert 검증은 가능했다.
- TPC-C 실행 전에 단일 클라이언트, 작은 scale factor로 load-only와 execute-only를 분리해서 검증하는 것이 좋다.

## 결론

현재 환경은 `ALTIBASE_PORT_NO`가 가리키는 Altibase에 대해 두 Python 접속 경로 모두 기본 연결이 가능하다. 다만 `py-tpcc`에는 Altibase 드라이버가 없고 기본 DDL도 Altibase와 맞지 않으므로, Altibase 전용 DDL과 DB-API 드라이버를 추가해야 실제 TPC-C load/workload 비교를 진행할 수 있다.
