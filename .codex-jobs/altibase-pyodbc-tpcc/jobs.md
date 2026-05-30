# Altibase pyodbc TPC-C enablement

- Kind: `mixed`
- Status values: `ToDo`, `Progress`, `Done`, `Fail`
- User-run command: `./run-all.sh` from this directory
- Codex workdir: repository root by default, override with `CODEX_WORKDIR=/path`
- Default behavior: continue through all jobs until completion or failure
- Optional single-job mode: `RUN_ONE=1 ./run-all.sh`
- Handoff gate: uncommitted project files stop the workflow before the next job starts
- Commit gate: each successful job must pass review and create a focused commit containing both job output and `jobs.tsv`/`jobs.md` `Done` state

## Preflight

- Source design: `ALTIBASE_PYODBC_EXECUTION_DESIGN.md`
- Source notes: `ALTIBASE_TEST_NOTES.md`
- Run from this directory: `cd /home/et16/work/py-tpcc/.codex-jobs/altibase-pyodbc-tpcc && ./run-all.sh`
- The workflow intentionally refuses to start if project files or workflow definition files are dirty. Runtime files under `.runtime/`, `logs/`, and `rollbacks/` are ignored.
- Bootstrap commit is required before launch: include this workflow directory plus the two source documents. Later job commits are intentionally allowed to update only `jobs.tsv` and `jobs.md` under `.codex-jobs/`; prompt and runner changes must not be hidden inside implementation job commits.
- Local Altibase smoke checks use `ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home`, `LD_LIBRARY_PATH=$ALTIBASE_HOME/lib`, `ALTIBASE_PORT_NO`, and DSN `ALTIBASE_LOCAL`.
- Benchmark live smoke and comparison jobs use the `PYTPCC/PYTPCC` schema credentials from the config examples. `SYS/MANAGER` connectivity is only an environment probe; `J001` must verify or safely provision `PYTPCC` before later live smoke jobs are treated as runnable.
- Jobs `J001` through `J004` intentionally build and validate the pyodbc baseline first.
- Jobs `J005` and `J006` then add and compare `/home/et16/work/altibase-python-driver` without rewriting the pyodbc baseline.
- `J005` reads and tests `/home/et16/work/altibase-python-driver`, but must not leave that repository with new tracked or untracked changes.
- Native driver connection state checked on 2026-05-30:
  - Repo: `/home/et16/work/altibase-python-driver`, branch `master`, HEAD `b54fc61`, with untracked `.claude-jobs/` only.
  - Runtime import works with `PYTHONPATH=/home/et16/work/altibase-python-driver/src`; `altibase.Connection` and `altibase.Cursor` are available.
  - Server smoke succeeds against `host=127.0.0.1`, `port=$ALTIBASE_PORT_NO` (`20104` in the current shell), user `SYS`: `SELECT 1 FROM dual` returned `(1,)`, `driver_info().dbms_name` reported `Altibase`, and round-trip `ping()` returned `True`.
  - `.venv/bin/python -m pytest -q tests/test_integration_connection.py::test_connection_close_is_idempotent tests/test_integration_connection.py::test_connection_information_and_health_methods_against_server` passed.
  - `python3 -m altibase.diagnose --server-probe` reports the server probe as OK when `ALTIBASE_PASSWORD` is set, but overall diagnostics still fail because the current SDK include directory lacks `sqlcli.h`; treat that as a build-time SDK/header issue, not a runtime connection failure.

## Jobs

| ID | Status | Title | Goal |
| --- | --- | --- | --- |
| `J001` | `Done` | Altibase DDL and config | Create Altibase-specific TPC-C DDL and pyodbc config example, then validate schema syntax against the local Altibase DSN where available. |
| `J002` | `ToDo` | Altibase driver reset and load | Add the pyodbc-backed Altibase driver with DSN connection, schema reset, DDL execution, loadTuples, loadFinish, cleanup, and basic driver discovery. |
| `J003` | `ToDo` | TPC-C transaction implementation | Implement and validate the five TPC-C transaction methods for Altibase using qmark SQL, bounded retry, rollback handling, and correct New Order abort behavior. |
| `J004` | `ToDo` | Results integration and smoke runs | Integrate Altibase into result summaries, add single-client cleanup, run reset/load/execute smoke checks, update docs, and commit the verified baseline. |
| `J005` | `ToDo` | Native Altibase driver backend | Extend the Altibase TPC-C target so it can run through `/home/et16/work/altibase-python-driver` while preserving the pyodbc baseline. |
| `J006` | `ToDo` | pyodbc/native comparison runs | Run comparable pyodbc and native Altibase TPC-C smoke/performance runs, capture the results, and document how to repeat the comparison. |

## Resume Rules

- `Fail`: stop before starting later jobs.
- Dirty project files: stop before starting or advancing to another job.
- `Progress`: preserve interruption evidence, set the job back to `ToDo`, then rerun only when project files are clean.
- `Done`: skip.
- Nonzero `codex exec` exits leave the job as uncommitted `Progress` by default. A repository reset to the last successful job commit returns that job to `ToDo`; otherwise the next manual run stops if project files are dirty, or resets runtime state and retries when clean.

## Acceptance Checklist

- Each job has a matching prompt in `prompts/`.
- Each job has concrete acceptance criteria.
- Each successful job leaves project files clean and advances HEAD with a commit containing both job output and workflow state.
- `bash -n run-all.sh` passes.
- Job prompts require final diff review, focused commit, and workflow status updates.
