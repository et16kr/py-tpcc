# Altibase pyodbc 우선 실행 설계

작성일: 2026-05-30

## 배경

`/home/et16/work/altibase-python-driver`는 현재 변경 작업 중이라 기준 드라이버로 사용할 수 없다. 따라서 `py-tpcc`의 Altibase 대응은 먼저 `pyodbc` 하나만 대상으로 진행한다.

이 문서는 `pyodbc`로 Altibase `20101`에 TPC-C 스키마 생성, 데이터 적재, 트랜잭션 실행까지 통과시키기 위한 실행 상세 계획이다. Native `altibase` Python driver 비교는 pyodbc 경로가 안정화된 뒤 후속 작업으로 분리한다.

관련 사전 조사 문서:

- `ALTIBASE_TEST_NOTES.md`

## 목표

1. `py-tpcc`에 Altibase용 실행 target을 추가한다.
2. 첫 구현은 `pyodbc` DSN 연결만 지원한다.
3. Altibase에서 통과하는 TPC-C DDL을 별도로 만든다.
4. `--reset`, `--no-execute`, `--no-load` 조합으로 schema reset, load-only, execute-only를 각각 검증한다.
5. 작은 scale부터 시작해서 단일 클라이언트 실행을 먼저 안정화한다.
6. 기존 결과 출력 경로에 Altibase를 연결해 pyodbc baseline의 tpmC, retry, abort 수치를 남긴다.

## 비목표

- `altibase-python-driver` 사용
- PostgreSQL/SQLite/MongoDB 기존 드라이버 리팩터링
- TPC-C 공식 인증 수준의 엄격한 benchmark run
- 대규모 병렬 load 최적화
- iLoader/direct path load 연동

## 현재 확인된 환경

Altibase 서버:

```text
ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home
host=127.0.0.1
port=20101
```

ODBC 설정:

```text
DSN=ALTIBASE_LOCAL_20101
Driver=ALTIBASE_HDB_ODBC_64bit
PORT_NO=20101
```

연결은 다음 방식이 성공했다.

```python
pyodbc.connect("DSN=ALTIBASE_LOCAL_20101;UID=SYS;PWD=MANAGER")
```

드라이버명을 직접 넣은 연결 문자열은 `HY024 Invalid attribute value`로 실패했으므로 1차 구현은 DSN 기반으로 제한한다.

## 설계 방침

### 실행 위치

현재 `tpcc.py`의 `getDrivers()`는 `./drivers/*driver.py`를 현재 작업 디렉터리 기준으로 스캔한다. 따라서 1차 검증 명령은 모두 `/home/et16/work/py-tpcc/pytpcc`에서 실행한다. repo root에서 바로 실행하는 동작 개선은 이번 목표와 분리한다.

### Driver 이름

우선 `pytpcc/drivers/altibasedriver.py`를 추가하고 CLI target은 `altibase`로 둔다.

이름을 `altibaseodbc`로 만들 수도 있지만, 장기적으로는 Altibase DBMS target 하나가 있고 그 안에서 접속 backend를 바꾸는 편이 사용성이 좋다. 단, 1차 구현에서는 backend 옵션을 열어두더라도 실제 지원값은 `pyodbc`만 둔다.

예상 CLI:

```bash
python3 tpcc.py --config altibase-pyodbc.config --ddl tpcc_altibase.sql altibase
```

### 접속 방식

1차 지원 config:

```ini
[altibase]
dsn = ALTIBASE_LOCAL_20101
user = PYTPCC
password = PYTPCC
connection-timeout = 5
max-retries = 20
retry-delay = 0.1
fast-executemany = False
```

초기에는 `DSN=...;UID=...;PWD=...` 형태만 생성한다. `Server/Port/Driver` 직접 연결은 사전 조사에서 실패했으므로 구현하지 않는다.

`pyodbc` import는 module import 시점이 아니라 `_connect()` 또는 `loadConfig()`에서 lazy import한다. 그래야 `python3 tpcc.py --print-config altibase`가 실제 ODBC runtime 없이도 config 출력까지는 도달하고, pyodbc 누락 오류도 연결 단계에서 명확하게 제어할 수 있다.

### 트랜잭션 SQL

Altibase는 `pyodbc`에서 DB-API `qmark` placeholder를 사용한다. 따라서 SQL은 SQLite driver의 `?` 기반 쿼리를 출발점으로 삼는다.

확인된 사항:

- `?` placeholder는 WHERE 조건에서 동작한다.
- `LIMIT 1`은 동작한다.
- `FETCH FIRST 1 ROWS ONLY`는 현재 서버에서 실패했다.
- PostgreSQL driver의 `%s`, `%s::integer`, `set session_replication_role` 등은 사용할 수 없다.

따라서 `altibasedriver.py`에는 별도 `TXN_QUERIES`를 두고 `?` 기반 SQL을 사용한다.

Altibase용 쿼리는 기존 SQLite 쿼리를 그대로 복사하지 않고 다음 차이를 반영한다.

- `DELIVERY.getNewOrder`는 `ORDER BY NO_O_ID LIMIT 1`을 사용한다. 기존 쿼리는 `LIMIT 1`만 있어서 가장 오래된 new order를 고른다는 SQL 차원의 보장이 약하다.
- `NEW_ORDER.createOrder`는 PostgreSQL의 `%s::integer` cast를 쓰지 않는다.
- retry 루프 안에서 `all_local`, `items`, `item_data`, `total` 같은 transient 값을 매번 새로 만든다.
- New Order의 의도된 invalid item abort는 데이터 변경 전이라도 `rollback()` 후 `(None, retries)`를 반환해서 connection transaction 상태를 정리한다.

### DDL 분리

기본 `pytpcc/tpcc.sql`은 그대로 쓰지 않는다. Altibase 전용 DDL 파일을 추가한다.

예상 파일:

```text
pytpcc/tpcc_altibase.sql
```

변경 원칙:

- `TINYINT`는 `SMALLINT`로 바꾼다.
- `TIMESTAMP`는 `DATE`로 바꾼다.
- `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`는 사용하지 않는다.
- `DROP TABLE IF EXISTS`는 사용하지 않는다.
- 주석 처리된 SQL이 세미콜론 split에 섞이지 않도록 정리한다.
- TPC-C 실행에 필수적이지 않은 `CUSTOMER(C_W_ID,C_D_ID,C_LAST,C_FIRST)` unique 제약은 1차 DDL에서 제외한다. 조회에는 `IDX_CUSTOMER(C_W_ID,C_D_ID,C_LAST)`를 사용한다.

사전 조사에서 `DATE` 컬럼에는 Python `datetime.datetime` 바인딩이 pyodbc로 성공했고, `TIMESTAMP` 컬럼에는 실패했다.

### Foreign key 처리

1차 DDL은 foreign key를 제거한다.

이유:

- 현재 loader는 `ORDER_LINE`을 먼저 적재하고 `STOCK`은 warehouse 마지막에 적재한다.
- 기본 DDL의 `ORDER_LINE -> STOCK` foreign key가 있으면 load 순서상 실패할 수 있다.
- PostgreSQL driver는 load 중 constraint를 비활성화하지만 Altibase에서 같은 방식을 바로 쓸 수 있다고 가정하지 않는다.

1차 목표는 TPC-C 데이터 생성과 트랜잭션 실행 경로 검증이므로 primary key와 조회용 secondary index를 우선 유지하고 foreign key는 제외한다. 필요하면 후속 단계에서 `loadFinish()`에 FK 생성 또는 loader 순서 변경을 검토한다.

### Reset 처리

Altibase는 `DROP TABLE IF EXISTS`를 지원하지 않는 것으로 확인됐다. reset은 테이블을 의존성 역순으로 drop하고, 존재하지 않는 테이블 오류는 무시한다.

Drop 순서:

```text
ORDER_LINE
NEW_ORDER
ORDERS
HISTORY
CUSTOMER
STOCK
DISTRICT
ITEM
WAREHOUSE
```

Reset 절차:

1. pyodbc 연결을 연다.
2. 위 순서대로 `DROP TABLE <name>`을 실행한다.
3. "table not found" 계열 오류는 debug 로그만 남기고 계속한다. 사전 조사에서 확인한 대표 오류는 SQLSTATE `42S02`, vendor code `200753`이다.
4. Altibase DDL 파일을 statement 단위로 실행한다.
5. commit한다.

### Commit 정책

Load:

- `loadTuples()`는 `executemany()`만 수행한다.
- commit은 기존 구조와 맞춰 `loadFinish()`에서 수행한다.
- 초기에 안정성 문제가 있으면 config로 `commit-every-batch=True`를 추가할 수 있지만 1차 기본값은 기존 driver 흐름을 따른다.

Transaction:

- 각 TPC-C transaction method는 성공 시 commit한다.
- 예외 시 rollback한다.
- retry 횟수는 config의 `max-retries`로 제한한다.
- 예상된 New Order 1% invalid item은 `(None, retries)`를 반환해서 abort로 집계되게 한다.
- syntax, data conversion, integrity 오류처럼 재시도로 해결되지 않는 오류는 초기에 바로 드러나야 한다. 1차 구현에서는 SQLSTATE와 vendor code를 로그에 남기고, 명확한 deterministic 오류는 retry하지 않는 방향을 우선한다.

`postgresqldriver.py`는 retry loop가 무한 반복될 수 있으나 Altibase 1차 구현에서는 장시간 hang을 피하기 위해 bounded retry를 둔다.

## 파일 변경 계획

### 1. `pytpcc/tpcc_altibase.sql`

Altibase용 TPC-C schema.

주요 내용:

- 9개 table 생성
- primary key 유지
- `IDX_CUSTOMER`, `IDX_ORDERS`, `IDX_ORDER_LINE_TREE` 유지
- foreign key와 비필수 unique 제약은 1차 제외
- 시간 컬럼은 `DATE`

### 2. `pytpcc/drivers/altibasedriver.py`

pyodbc 기반 Altibase driver.

구성:

- `DEFAULT_CONFIG`
- `TXN_QUERIES`
- `loadConfig()`
- `_connect()`
- `_reset_schema()`
- `_execute_ddl_file()`
- `loadTuples()`
- `loadFinish()`
- `cleanup()`
- `doDelivery()`
- `doNewOrder()`
- `doOrderStatus()`
- `doPayment()`
- `doStockLevel()`
- `getNumberWH()`

쿼리 구현은 `postgresqldriver.py`의 반환 형태 `(value, retries)`를 따른다.

`pyodbc`는 lazy import한다. top-level import로 두면 `--print-config altibase`도 pyodbc 설치 여부에 묶이므로 피한다.

### 3. `pytpcc/util/results.py`

결과 출력에서 `AltibaseDriver`를 PostgreSQL 계열과 같은 짧은 SQL DB summary 경로에 포함한다.

현재 `results.show()`는 `PostgresqlDriver`와 `PostgresqljsonbDriver`만 `getNumberWH()` 기반 tpmC 한 줄 summary를 출력한다. Altibase driver에 `getNumberWH()`만 구현해도 이 분기에 들어가지 않으므로, pyodbc baseline 비교를 위해 `AltibaseDriver`도 명시적으로 포함한다.

### 4. `pytpcc/ALTIBASE_ODBC_EXAMPLE`

기본 config 예시.

```ini
[altibase]
dsn = ALTIBASE_LOCAL_20101
user = PYTPCC
password = PYTPCC
connection-timeout = 5
max-retries = 20
retry-delay = 0.1
fast-executemany = False
```

주의: `ConfigParser`는 모든 값을 문자열로 넘긴다. driver 구현에서 `connection-timeout`, `max-retries`, `retry-delay`, `fast-executemany`는 명시적으로 타입 변환한다. 특히 `bool("False")`는 `True`이므로 boolean parser를 별도로 둔다.

### 5. 문서 갱신

최소 문서만 갱신한다.

- `README.md`에 Altibase pyodbc 실행 섹션 추가 또는 별도 문서 링크
- 이 설계 문서와 `ALTIBASE_TEST_NOTES.md` 유지

## 상세 실행 계획

### Phase 0. 기준 환경 고정

목적: pyodbc로만 테스트할 수 있는 환경을 고정한다.

확인 명령:

```bash
export ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home
export LD_LIBRARY_PATH="$ALTIBASE_HOME/lib:${LD_LIBRARY_PATH:-}"

python3 - <<'PY'
import pyodbc
cn = pyodbc.connect("DSN=ALTIBASE_LOCAL_20101;UID=SYS;PWD=MANAGER", timeout=5)
cur = cn.cursor()
cur.execute("SELECT 1 FROM dual")
print(cur.fetchone())
cn.close()
PY
```

통과 기준:

```text
(1,)
```

권장: SYS가 아닌 전용 유저를 만든다.

```sql
CREATE USER PYTPCC IDENTIFIED BY PYTPCC;
GRANT CREATE SESSION, CREATE TABLE TO PYTPCC;
```

1차 실행은 `PYTPCC` 같은 전용 schema에서 수행한다. SYS로 TPC-C table을 만들면 reset이 SYS schema의 같은 이름 table을 drop하게 되므로 피한다.

### Phase 1. Altibase DDL 작성과 단독 검증

작업:

1. `pytpcc/tpcc_altibase.sql` 작성
2. 임시 유저 또는 `PYTPCC` 유저에서 DDL만 실행
3. 생성된 table 목록 확인

검증 SQL:

```sql
SELECT table_name
FROM system_.sys_tables_
WHERE user_id = (
  SELECT user_id FROM system_.sys_users_ WHERE user_name = 'PYTPCC'
)
ORDER BY table_name;
```

통과 기준:

- 9개 table 생성
- DDL 재실행 전 reset drop이 동작
- `DATE` 컬럼에 Python `datetime.datetime` insert 성공

### Phase 2. Driver skeleton 추가

작업:

1. `altibasedriver.py` 추가
2. `python3 tpcc.py --print-config altibase`가 동작하게 한다.
3. `loadConfig()`에서 DSN 연결과 reset schema 실행을 구현한다.
4. `results.show()`가 `AltibaseDriver`를 SQL DB summary 대상으로 인식하게 한다.

검증:

```bash
cd /home/et16/work/py-tpcc/pytpcc
python3 tpcc.py --print-config altibase
```

통과 기준:

- `altibase`가 choices에 노출
- 기본 config 출력
- `pyodbc` import 실패 시 명확한 오류 메시지

### Phase 3. Reset-only 검증

명령:

```bash
cd /home/et16/work/py-tpcc/pytpcc

ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
python3 tpcc.py --config ALTIBASE_ODBC_EXAMPLE --ddl tpcc_altibase.sql \
  --reset --no-load --no-execute altibase --debug
```

통과 기준:

- 모든 기존 TPC-C table drop 시도 완료
- 없는 table은 무시
- 9개 table 생성
- 두 번 연속 실행해도 성공

### Phase 4. Load-only 단일 클라이언트 검증

작은 scale부터 시작한다.

명령:

```bash
cd /home/et16/work/py-tpcc/pytpcc

ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
python3 tpcc.py --config ALTIBASE_ODBC_EXAMPLE --ddl tpcc_altibase.sql \
  --reset --no-execute --warehouses 1 --scalefactor 100 \
  --duration 10 --clients 1 altibase --stop-on-error --debug
```

예상 scale:

- items: `100000 / 100 = 1000`
- warehouses: `1`
- districts: `10`
- customers per district: `3000 / 100 = 30`
- new orders per district: `900 / 100 = 9`

통과 기준:

- load 완료
- commit 완료
- table count가 예상치와 맞음

Count 확인:

```sql
SELECT COUNT(*) FROM ITEM;
SELECT COUNT(*) FROM WAREHOUSE;
SELECT COUNT(*) FROM DISTRICT;
SELECT COUNT(*) FROM CUSTOMER;
SELECT COUNT(*) FROM HISTORY;
SELECT COUNT(*) FROM ORDERS;
SELECT COUNT(*) FROM NEW_ORDER;
SELECT COUNT(*) FROM STOCK;
SELECT COUNT(*) FROM ORDER_LINE;
```

예상:

- `ITEM = 1000`
- `WAREHOUSE = 1`
- `DISTRICT = 10`
- `CUSTOMER = 300`
- `HISTORY = 300`
- `ORDERS = 300`
- `NEW_ORDER = 90`
- `STOCK = 1000`
- `ORDER_LINE > 0`

`ORDER_LINE`은 주문별 line 수가 random이라 고정 숫자가 아니다.

### Phase 5. Execute-only 단일 클라이언트 검증

명령:

```bash
cd /home/et16/work/py-tpcc/pytpcc

ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
python3 tpcc.py --config ALTIBASE_ODBC_EXAMPLE --ddl tpcc_altibase.sql \
  --no-load --warehouses 1 --scalefactor 100 \
  --duration 30 --clients 1 altibase --stop-on-error --debug
```

통과 기준:

- 30초 실행 완료
- `NEW_ORDER`, `PAYMENT`, `ORDER_STATUS`, `DELIVERY`, `STOCK_LEVEL` 중 적어도 주요 transaction이 실행됨
- invalid item에 따른 New Order abort는 정상 abort로 집계
- invalid item abort 뒤에도 다음 transaction이 같은 connection에서 정상 실행됨
- `AltibaseDriver.getNumberWH()`가 결과 summary에서 호출됨
- driver 예외로 프로세스가 중단되지 않음

### Phase 6. Reset + load + execute 통합 검증

명령:

```bash
cd /home/et16/work/py-tpcc/pytpcc

ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
python3 tpcc.py --config ALTIBASE_ODBC_EXAMPLE --ddl tpcc_altibase.sql \
  --reset --warehouses 1 --scalefactor 100 \
  --duration 30 --clients 1 altibase --stop-on-error
```

통과 기준:

- reset 성공
- load 성공
- execute 성공
- 최종 결과 table과 Altibase용 tpmC 한 줄 summary 출력

### Phase 7. 소규모 병렬 검증

단일 클라이언트가 안정화된 뒤에만 진행한다.

명령:

```bash
cd /home/et16/work/py-tpcc/pytpcc

ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
python3 tpcc.py --config ALTIBASE_ODBC_EXAMPLE --ddl tpcc_altibase.sql \
  --reset --warehouses 2 --scalefactor 100 \
  --duration 60 --clients 2 altibase --stop-on-error
```

통과 기준:

- multiprocessing load에서 각 worker가 별도 pyodbc connection을 사용
- transaction retry가 무한 대기하지 않음
- lock/deadlock/serialization류 오류 발생 시 bounded retry 후 결과가 명확히 보임

## 구현 상세 메모

### DDL statement split

간단한 구현은 다음 수준이면 충분하다.

- 라인 단위로 `--` 주석 제거
- 빈 라인 제거
- `;` 기준 split
- 각 statement strip 후 실행

현재 DDL에는 procedure/function body가 없으므로 복잡한 SQL parser는 필요 없다.

### pyodbc cursor 사용

`pyodbc`는 list와 tuple parameter를 모두 받을 수 있다. 기존 loader는 list tuple을 생성하므로 그대로 `executemany(sql, tuples)`에 넘긴다.

`fast_executemany`는 기본 비활성화한다. Altibase ODBC에서 안정성이 확인된 뒤 별도 성능 옵션으로 켠다.

### Cleanup

`tpcc.py`의 multi-process helper는 `cleanup()`이 있으면 호출하지만, 현재 단일 클라이언트 main path는 명시적으로 `cleanup()`을 호출하지 않는다. 1차 구현은 process exit에 의존해도 동작은 가능하지만, ODBC handle을 깨끗하게 닫으려면 `tpcc.py`에 작은 final cleanup 처리를 추가하는 편이 낫다.

Altibase driver 자체에는 `cleanup()`을 두고 cursor/connection close가 여러 번 호출돼도 안전하게 만든다.

### getNumberWH

결과 출력에서 PostgreSQL driver와 비슷하게 warehouse 수를 보여주려면 driver에 다음 쿼리를 구현하고, `results.show()`의 SQL DB summary 조건에 `AltibaseDriver`를 추가한다.

```sql
SELECT MAX(W_ID) FROM WAREHOUSE
```

## 위험과 대응

### `ORDER_LINE -> STOCK` FK 문제

위험: 기본 schema의 FK를 유지하면 현재 loader 순서상 load 실패 가능성이 높다.

대응: 1차 Altibase DDL에서는 FK를 제외한다. 후속으로 loader 순서를 조정하거나 `loadFinish()`에서 FK를 생성한다.

### 날짜 타입 문제

위험: `TIMESTAMP` 컬럼에 Python `datetime` 바인딩이 실패한다.

대응: Altibase DDL에서 시간 컬럼은 `DATE`로 정의한다.

### pyodbc 직접 Driver 연결 실패

위험: DSN 없이 실행하려는 사용자가 실패할 수 있다.

대응: 1차 config는 DSN 필수로 둔다. direct connection string은 후속 검증 후 추가한다.

### 무한 retry

위험: lock 또는 SQL 오류가 transaction retry loop 안에서 무한 반복될 수 있다.

대응: `max-retries`를 두고 초과 시 예외를 올린다.

### deterministic 오류 은폐

위험: syntax 오류, DDL mismatch, 날짜 변환 오류까지 retry하면 실제 구현 버그가 `max-retries` 이후에야 보인다.

대응: SQLSTATE와 vendor code를 로그에 남기고, 명확한 deterministic 오류는 즉시 실패시킨다. lock/deadlock/serialization처럼 재시도 가능한 오류만 retry 대상으로 좁힌다.

### 결과 summary 누락

위험: `AltibaseDriver.getNumberWH()`를 구현해도 `results.show()`가 class name으로 PostgreSQL 계열만 분기하므로 Altibase용 tpmC 한 줄 summary가 빠질 수 있다.

대응: `pytpcc/util/results.py`의 SQL DB summary 분기에 `AltibaseDriver`를 추가한다.

### config 타입 변환 오류

위험: `ConfigParser`가 `False`, `20`, `0.1`을 모두 문자열로 전달한다. 특히 `bool("False")`는 `True`다.

대응: driver에서 int, float, bool parser를 명시적으로 사용한다.

### pyodbc top-level import

위험: `altibasedriver.py`가 top-level에서 `import pyodbc`를 수행하면 `--print-config altibase`도 pyodbc 설치 상태에 의존한다.

대응: `_connect()` 또는 `loadConfig()` 안에서 lazy import하고, 실패 시 설치 안내가 포함된 명확한 예외를 낸다.

### 단일 클라이언트 cleanup 누락

위험: `clients=1` 실행은 현재 main path에서 `cleanup()`을 호출하지 않는다.

대응: process exit로도 정리는 되지만, pyodbc handle 정리를 명확히 하려면 `tpcc.py`에 final cleanup을 추가한다. 이 변경은 작게 유지하고 기존 driver에 영향이 없도록 `hasattr(driver, "cleanup")` 조건으로 제한한다.

### custom starting warehouse의 ITEM load 누락

위험: 현재 loader worker는 `w_ids`에 warehouse `1`이 있을 때만 ITEM을 적재한다. `--starting-warehouse`가 1보다 크면 ITEM table이 비어 transaction이 실패할 수 있다.

대응: 1차 검증은 `starting_warehouse=1` 범위에서만 수행한다. custom range 지원은 별도 후속 작업으로 둔다.

### 기존 target 실행 영향

위험: 공통 runtime을 바꾸면 기존 PostgreSQL/MongoDB 실행에 영향이 갈 수 있다.

대응: 1차 구현은 새 파일 추가 위주로 진행한다. 공통 변경이 필요한 경우는 `results.show()`의 Altibase 분기 추가와 선택적 single-client cleanup처럼 좁은 변경으로 제한한다. `getDrivers()`의 cwd 의존성 수정은 이번 목표에 필수는 아니므로 별도 작업으로 분리한다.

## 완료 기준

1차 완료 기준:

- `python3 tpcc.py --print-config altibase` 성공
- `--reset --no-load --no-execute` 두 번 연속 성공
- `--reset --no-execute --warehouses 1 --scalefactor 100 --clients 1` 성공
- table count가 예상치와 일치
- `--no-load --duration 30 --clients 1` 성공
- 결과 table과 Altibase용 tpmC 한 줄 summary가 출력됨

2차 완료 기준:

- `warehouses=2`, `clients=2`, `scalefactor=100` 통합 실행 성공
- retry/abort 집계가 비정상적으로 폭증하지 않음
- `fast-executemany=False` 기준으로 안정성 확보

후속 비교 단계:

- `altibase-python-driver`가 안정화된 뒤 동일 DDL, 동일 transaction SQL, 동일 scale로 native backend를 추가한다.
- pyodbc 결과를 baseline으로 삼고 load time, tpmC, abort/retry count를 비교한다.

## 권장 작업 순서

1. `pytpcc/tpcc_altibase.sql` 추가
2. `pytpcc/drivers/altibasedriver.py` skeleton 추가
3. `pytpcc/util/results.py`에 `AltibaseDriver` summary 분기 추가
4. `--print-config altibase` 검증
5. reset-only 검증
6. load-only 검증
7. count 검증
8. execute-only 검증
9. 통합 실행 검증
10. clients 2 이상으로 확장
11. 결과와 발견 이슈를 이 문서 또는 별도 run log에 기록
