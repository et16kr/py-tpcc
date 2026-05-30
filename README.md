## TPC-C in Python for MongoDB
Approved in July of 1992, TPC Benchmark C is an on-line transaction processing (OLTP) benchmark. TPC-C is more complex than previous OLTP benchmarks such as TPC-A because of its multiple transaction types, more complex database and overall execution structure. TPC-C involves a mix of five concurrent transactions of different types and complexity either executed on-line or queued for deferred execution. The database is comprised of nine types of tables with a wide range of record and population sizes. TPC-C is measured in transactions per minute (tpmC). While the benchmark portrays the activity of a wholesale supplier, TPC-C is not limited to the activity of any particular business segment, but, rather represents any industry that must manage, sell, or distribute a product or service.

To learn more about TPC-C, please see the [TPC-C](https://www.tpc.org/tpcc/) documentation.

This repo is an experimental variant of Python TPC-C implementation based on the original [here](http://github.com/apavlo/py-tpcc).

The structure of the repo is:

1. **pytpcc** - the code for pytpcc with driver (DB) specific code in **drivers** subdirectory.
2. **vldb2019** - 2019 VLDB paper, poster and results generated from this code
   * [VLDB Paper](vldb2019/paper.pdf)
   * [VLDB Poster](vldb2019/poster.pdf)
   * [Result directory](vldb2019/results)

All the tests were run using [MongoDB Atlas](https://www.mongodb.com/cloud/atlas?jmp=VLDB2019).
Use code `VLDB2019` to get $150 credit to get started with MongoDB Atlas.

## Altibase Backends

The Altibase target is selected as `altibase` for both connection paths. Choose
the backend in the config file:

- `pytpcc/ALTIBASE_ODBC_EXAMPLE`: `backend = pyodbc`, DSN-based connection.
- `pytpcc/ALTIBASE_NATIVE_EXAMPLE`: `backend = native`, keyword connection
  through `/home/et16/work/altibase-python-driver`.

For implementation notes and known compatibility constraints, see
[`ALTIBASE_PYODBC_EXECUTION_DESIGN.md`](ALTIBASE_PYODBC_EXECUTION_DESIGN.md)
and [`ALTIBASE_TEST_NOTES.md`](ALTIBASE_TEST_NOTES.md). For the local
pyodbc/native comparison commands and measured smoke results, see
[`ALTIBASE_BACKEND_COMPARISON.md`](ALTIBASE_BACKEND_COMPARISON.md).

For pyodbc, define an ODBC DSN such as `ALTIBASE_LOCAL` and keep
`ALTIBASE_PORT_NO` in the environment for the Altibase ODBC driver. For native,
set `PYTHONPATH=/home/et16/work/altibase-python-driver/src` unless the package
is installed, and keep `ALTIBASE_PORT_NO` set because `port-env` reads it by
default. If the benchmark schema credentials differ locally, use an untracked
local config file.

Run from `pytpcc/`:

```bash
cd pytpcc
```

Pyodbc reset-only smoke, run twice to verify repeatable schema reset:

```bash
ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
ALTIBASE_PORT_NO=${ALTIBASE_PORT_NO:?} \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
python3 tpcc.py --config ALTIBASE_ODBC_EXAMPLE --ddl tpcc_altibase.sql \
  --reset --no-load --no-execute altibase --debug
```

Native reset-only smoke:

```bash
ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
ALTIBASE_PORT_NO=${ALTIBASE_PORT_NO:?} \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
PYTHONPATH=/home/et16/work/altibase-python-driver/src:${PYTHONPATH:-} \
python3 tpcc.py --config ALTIBASE_NATIVE_EXAMPLE --ddl tpcc_altibase.sql \
  --reset --no-load --no-execute altibase --debug
```

Load-only smoke, using either config file:

```bash
CONFIG=ALTIBASE_ODBC_EXAMPLE
ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
ALTIBASE_PORT_NO=${ALTIBASE_PORT_NO:?} \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
PYTHONPATH=/home/et16/work/altibase-python-driver/src:${PYTHONPATH:-} \
python3 tpcc.py --config "$CONFIG" --ddl tpcc_altibase.sql \
  --reset --no-execute --warehouses 1 --scalefactor 100 \
  --duration 10 --clients 1 altibase --stop-on-error --debug
```

Execute-only smoke, using the same config selected for load:

```bash
CONFIG=ALTIBASE_ODBC_EXAMPLE
ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
ALTIBASE_PORT_NO=${ALTIBASE_PORT_NO:?} \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
PYTHONPATH=/home/et16/work/altibase-python-driver/src:${PYTHONPATH:-} \
python3 tpcc.py --config "$CONFIG" --ddl tpcc_altibase.sql \
  --no-load --warehouses 1 --scalefactor 100 \
  --duration 30 --clients 1 altibase --stop-on-error --debug
```

Combined reset/load/execute smoke, using either config file:

```bash
CONFIG=ALTIBASE_ODBC_EXAMPLE
ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home \
ALTIBASE_PORT_NO=${ALTIBASE_PORT_NO:?} \
LD_LIBRARY_PATH=/home/et16/work/altidev4/altibase_home/lib:${LD_LIBRARY_PATH:-} \
PYTHONPATH=/home/et16/work/altibase-python-driver/src:${PYTHONPATH:-} \
python3 tpcc.py --config "$CONFIG" --ddl tpcc_altibase.sql \
  --reset --warehouses 1 --scalefactor 100 \
  --duration 30 --clients 1 altibase --stop-on-error
```

## Sharded MongoDB Driver

1. Create ana activate a python env.

```bash
mkdir ~/python_envs
cd ~/python_envs
~/python_envs$ python -m venv py-tpcc-env
source ~/python_envs/py-tpcc-env/bin/activate
```
2. Install pymongo

```bash
pip install pymongo 
```

3. Print your config.

```bash
cd ~/py-tpcc/pytpcc
~/py-tpcc/pytpcc$ python ./tpcc.py --print-config mongodb > mongodb.config
```

4. Edit the configuration for Postgres in the mongodb.config. 
   * Change shards to the number of `shards`
   * Change the mongodb connection `uri` string
   * Change the database `name`

```bash
# MongodbDriver Configuration File
# Created 2025-10-08 14:18:24.378446
[mongodb]

# The mongodb connection string or URI
uri                  = mongodb://user:pass@10.2.1.119:27017/admin?ssl=true&tlsAllowInvalidHostnames=true&tlsAllowInvalidCertificates=true

# Database name
name                 = tpcc

# If true, data will be denormalized using MongoDB schema design best practices
denormalize          = True

# If true, transactions will not be used (benchmarking only)
notransactions       =

# If true, all things to update will be fetched via findAndModify
findandmodify        = True

# If true, aggregation queries will be used
agg                  =

# If true, we will allow secondary reads
secondary_reads      = True

# If true, we will enable retryable writes
retry_writes         = True

# If true, we will perform causal reads
causal_consistency   = True

# If true, we will have use only one 'unsharded' items collection
no_global_items      =

# If > 0 then sharded
shards               = 3
```

4. Run pytpcc using --warehouses=XXX

   * Reset the database and load the data
   ```bash
   python ./tpcc.py --reset --no-execute --clients=100 --duration=10 --warehouses=21 --config=mongodb.config mongodb --stop-on-error
   ```

   * Only load the data
   ```bash
   python ./tpcc.py --no-execute --clients=100 --duration=10 --warehouses=21 --config=mongodb.config mongodb --stop-on-error
   ```
   
   * Execute the tests without loading data.
   ```bash
   python ./tpcc.py --no-load --clients=100 --duration=10 --warehouses=21 --config=mongodb.config mongodb --stop-on-error
   ```

   * Execute the tests with loading
   ```bash
   python ./tpcc.py --clients=100 --duration=10 --warehouses=21 --config=mongodb.config mongodb --stop-on-error
   ```

## Postgres JSONB Driver

This branch contains a Postgres JSONB Driver.

Steps to run the PostgreSQL JSONB Driver

1. Start Postgres.

```bash
sudo systemctl start postgresql
```

2. Create ana activate a python env.

```bash
mkdir ~/python_envs
cd ~/python_envs
~/python_envs$ python -m venv py-tpcc-env
source ~/python_envs/py-tpcc-env/bin/activate
```

3. Print your config.

```bash
cd ~/py-tpcc/pytpcc
~/py-tpcc/pytpcc$ python ./tpcc.py --print-config postgresqljsonb > postgresqljsonb.config
```

3. Edit the configuraiton for Postgres in the postgresqljsonb.config. Add a password.

```bash
# PostgresqljsonbDriver Configuration File
# Created 2025-03-18 23:00:45.340852
[postgresqljsonb]

# The name of the PostgreSQL database
database             = tpcc

# The host address of the PostgreSQL server
host                 = localhost

# The port number of the PostgreSQL server
port                 = 5432

# The username to connect to the PostgreSQL database
user                 = postgres

# The password to connect to the PostgreSQL database
password             = <ADD_PASSWORD_HERE>
```

4. Run the PostgreSQL JSONB driver tests with resetting the database.

```bash
~/py-tpcc/pytpcc$ python ./tpcc.py --reset --clients=1 --duration=1 --warehouses=1 --ddl tpcc_jsonb.sql --config=postgresqljsonb.config postgresqljsonb --stop-on-error
```

5. Run the PostgreSQL JSONB driver tests with no load phase to use the data that is already loaded in the Postgres database.

```bash
~/py-tpcc/pytpcc$ python ./tpcc.py --no-load --clients=1 --duration=1 --warehouses=1 --ddl tpcc_jsonb.sql --config=postgresqljsonb.config postgresqljsonb --stop-on-error
```

6. If you need to connect to Postgres and check the database size

```bash
psql -U postgres # and type the password
postgres=# \l+

# For any SQL command first use the database
\c tpcc;
```
