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
- The workflow intentionally refuses to start if project files outside `.codex-jobs/` are dirty. Commit or stash the two source documents and any other local changes before launching `run-all.sh`.
- Bootstrap commit is recommended before launch: include this workflow directory plus the two source documents. Later job commits are intentionally allowed to update only `jobs.tsv` and `jobs.md` under `.codex-jobs/`; prompt and runner changes must not be hidden inside implementation job commits.
- Local Altibase smoke checks use `ALTIBASE_HOME=/home/et16/work/altidev4/altibase_home`, `LD_LIBRARY_PATH=$ALTIBASE_HOME/lib`, and DSN `ALTIBASE_LOCAL_20101`.
- The first implementation target is pyodbc only. Do not use `/home/et16/work/altibase-python-driver` in these jobs.

## Jobs

| ID | Status | Title | Goal |
| --- | --- | --- | --- |
| `J001` | `ToDo` | Altibase DDL and config | Create Altibase-specific TPC-C DDL and pyodbc config example, then validate schema syntax against the local Altibase DSN where available. |
| `J002` | `ToDo` | Altibase driver reset and load | Add the pyodbc-backed Altibase driver with DSN connection, schema reset, DDL execution, loadTuples, loadFinish, cleanup, and basic driver discovery. |
| `J003` | `ToDo` | TPC-C transaction implementation | Implement and validate the five TPC-C transaction methods for Altibase using qmark SQL, bounded retry, rollback handling, and correct New Order abort behavior. |
| `J004` | `ToDo` | Results integration and smoke runs | Integrate Altibase into result summaries, add single-client cleanup, run reset/load/execute smoke checks, update docs, and commit the verified baseline. |

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
