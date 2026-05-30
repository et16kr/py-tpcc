#!/usr/bin/env bash
set -Eeuo pipefail

# User-run script. Default mode continues through all jobs until completion or failure.
# Optional controls:
#   RUN_ONE=1 ./run-all.sh          # stop after one completed ToDo job
#   FAIL_ON_NONZERO=1 ./run-all.sh  # mark nonzero codex exits as terminal Fail
#   CODEX_WORKDIR=/path ./run-all.sh # override the codex execution directory

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOBS_FILE="${JOBS_FILE:-$SCRIPT_DIR/jobs.tsv}"
PROMPT_DIR="${PROMPT_DIR:-$SCRIPT_DIR/prompts}"
LOG_DIR="${LOG_DIR:-$SCRIPT_DIR/logs}"
ROLLBACK_DIR="${ROLLBACK_DIR:-$SCRIPT_DIR/rollbacks}"
RUNTIME_DIR="${RUNTIME_DIR:-$SCRIPT_DIR/.runtime}"

CODEX_BIN="${CODEX_BIN:-codex}"
CODEX_SUBCOMMAND="${CODEX_SUBCOMMAND:-exec}"
CODEX_WORKDIR="${CODEX_WORKDIR:-}"
AUTO_ROLLBACK="${AUTO_ROLLBACK:-1}"
RUN_ONE="${RUN_ONE:-0}"
FAIL_ON_NONZERO="${FAIL_ON_NONZERO:-0}"
REQUIRE_CLEAN_START="${REQUIRE_CLEAN_START:-1}"
REQUIRE_CLEAN_AFTER_JOB="${REQUIRE_CLEAN_AFTER_JOB:-1}"
REQUIRE_COMMIT_AFTER_JOB="${REQUIRE_COMMIT_AFTER_JOB:-1}"

mkdir -p "$LOG_DIR" "$ROLLBACK_DIR" "$RUNTIME_DIR"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

status_of() {
  awk -F '\t' -v id="$1" 'NR > 1 && $1 == id { print $2; found = 1; exit } END { if (!found) exit 1 }' "$JOBS_FILE"
}

title_of() {
  awk -F '\t' -v id="$1" 'NR > 1 && $1 == id { print $4; found = 1; exit } END { if (!found) exit 1 }' "$JOBS_FILE"
}

set_status() {
  local id="$1"
  local status="$2"
  local tmp
  tmp="$(mktemp)"
  awk -F '\t' -v OFS='\t' -v id="$id" -v status="$status" '
    NR == 1 { print; next }
    $1 == id { $2 = status }
    { print }
  ' "$JOBS_FILE" > "$tmp"
  mv "$tmp" "$JOBS_FILE"
}

first_job_with_status() {
  awk -F '\t' -v status="$1" 'NR > 1 && $2 == status { print $1; exit }' "$JOBS_FILE"
}

job_ids() {
  awk -F '\t' 'NR > 1 && $1 != "" { print $1 }' "$JOBS_FILE"
}

inside_git_repo() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1
}

git_repo_root() {
  git rev-parse --show-toplevel
}

workflow_rel_path() {
  local root="$1"
  case "$SCRIPT_DIR/" in
    "$root"/*) printf '%s\n' "${SCRIPT_DIR#$root/}" ;;
    *) return 1 ;;
  esac
}

workflow_file_rel_path() {
  local root="$1"
  local file="$2"
  local dir base abs
  dir="$(cd "$(dirname "$file")" && pwd)"
  base="$(basename "$file")"
  abs="$dir/$base"
  case "$abs" in
    "$root"/*) printf '%s\n' "${abs#$root/}" ;;
    *) return 1 ;;
  esac
}

workflow_state_paths() {
  inside_git_repo || return 0
  local root
  root="$(git_repo_root)"
  workflow_file_rel_path "$root" "$JOBS_FILE" || true
  if [[ -f "$SCRIPT_DIR/jobs.md" ]]; then
    workflow_file_rel_path "$root" "$SCRIPT_DIR/jobs.md" || true
  fi
}

is_workflow_state_path() {
  local path="$1"
  local state_path
  while IFS= read -r state_path; do
    [[ -n "$state_path" ]] || continue
    if [[ "$path" == "$state_path" ]]; then
      return 0
    fi
  done < <(workflow_state_paths)
  return 1
}

workflow_state_dirty_status() {
  inside_git_repo || return 0
  local root paths=()
  root="$(git_repo_root)"
  while IFS= read -r path; do
    [[ -n "$path" ]] && paths+=("$path")
  done < <(workflow_state_paths)
  if [[ "${#paths[@]}" -eq 0 ]]; then
    return 0
  fi
  git -C "$root" status --porcelain --untracked-files=all -- "${paths[@]}"
}

git_head() {
  git rev-parse --verify HEAD 2>/dev/null || printf '%s\n' "__NO_HEAD__"
}

git_blocking_status() {
  inside_git_repo || return 0
  local root rel status
  root="$(git_repo_root)"
  rel="$(workflow_rel_path "$root" || true)"

  if [[ -n "$rel" ]]; then
    local pathspecs=(
      .
      ":(exclude)$rel/.runtime"
      ":(exclude)$rel/.runtime/**"
      ":(exclude)$rel/logs"
      ":(exclude)$rel/logs/**"
      ":(exclude)$rel/rollbacks"
      ":(exclude)$rel/rollbacks/**"
    )
    local progress_job jobs_tsv_rel
    progress_job="$(first_job_with_status Progress || true)"
    if [[ -n "$progress_job" ]]; then
      jobs_tsv_rel="$(workflow_file_rel_path "$root" "$JOBS_FILE" || true)"
      [[ -n "$jobs_tsv_rel" ]] && pathspecs+=(":(exclude)$jobs_tsv_rel")
    fi
    status="$(git -C "$root" status --porcelain --untracked-files=all -- "${pathspecs[@]}")"
  else
    status="$(git -C "$root" status --porcelain --untracked-files=all)"
  fi

  printf '%s\n' "$status"
}

git_dirty_blocking() {
  local status
  status="$(git_blocking_status)"
  [[ -n "$status" ]]
}

print_blocking_status() {
  local status
  status="$(git_blocking_status)"
  if [[ -n "$status" ]]; then
    printf 'Blocking uncommitted project files:\n%s\n' "$status" >&2
  fi
}

codex_workdir() {
  if [[ -n "$CODEX_WORKDIR" ]]; then
    (cd "$CODEX_WORKDIR" && pwd)
  elif inside_git_repo; then
    git_repo_root
  else
    printf '%s\n' "$SCRIPT_DIR"
  fi
}

preserve_and_clear_progress() {
  local id="$1"
  local timestamp
  timestamp="$(date +%Y%m%d-%H%M%S)"
  local dir="$ROLLBACK_DIR/$id-$timestamp"
  mkdir -p "$dir"

  if [[ "$AUTO_ROLLBACK" != "1" ]]; then
    die "Job $id is Progress. AUTO_ROLLBACK=0, so resolve it manually and set status to ToDo or Done."
  fi

  if ! inside_git_repo; then
    die "Job $id is Progress, but this is not a git repository. Rollback manually, then set status to ToDo."
  fi

  local root
  root="$(git_repo_root)"
  git -C "$root" status --porcelain --untracked-files=all > "$dir/status.txt" || true
  git -C "$root" diff > "$dir/unstaged.diff" || true
  git -C "$root" diff --staged > "$dir/staged.diff" || true
  git -C "$root" ls-files -o --exclude-standard > "$dir/untracked.txt" || true

  if git_dirty_blocking; then
    print_blocking_status
    die "Job $id is Progress and uncommitted project files exist. Commit, stash, or inspect them manually before retrying."
  else
    printf 'No uncommitted project files to preserve. Workflow runtime state was left in place.\n' > "$dir/resume.txt"
  fi

  set_status "$id" "ToDo"
  printf 'Reset interrupted job %s to ToDo. Preserved details in %s\n' "$id" "$dir"
}

ensure_clean_before_job() {
  local id="$1"
  if [[ "$REQUIRE_COMMIT_AFTER_JOB" == "1" ]] && ! inside_git_repo; then
    die "Job $id cannot start because this is not a git repository and successful jobs must commit."
  fi
  if [[ "$REQUIRE_CLEAN_START" == "1" ]] && git_dirty_blocking; then
    print_blocking_status
    die "Uncommitted project files exist before starting $id. Commit or stash them before running jobs."
  fi
}

ensure_clean_after_job() {
  local id="$1"
  if [[ "$REQUIRE_CLEAN_AFTER_JOB" == "1" ]] && git_dirty_blocking; then
    print_blocking_status
    set_status "$id" "Fail"
    die "Job $id finished but left uncommitted project files. Commit or clean them, then rerun."
  fi
}

ensure_commit_after_job() {
  local id="$1"
  local before_head="$2"

  if [[ "$REQUIRE_COMMIT_AFTER_JOB" != "1" ]]; then
    return 0
  fi

  if ! inside_git_repo; then
    set_status "$id" "Fail"
    die "Job $id cannot be accepted because this is not a git repository and successful jobs must commit."
  fi

  local after_head
  after_head="$(git_head)"
  if [[ "$after_head" == "$before_head" ]]; then
    set_status "$id" "Fail"
    die "Job $id finished without creating a commit. A successful reviewed job must commit its result."
  fi

  if [[ "$(status_of "$id")" != "Done" ]]; then
    die "Job $id advanced HEAD but did not commit its Done state in $JOBS_FILE. Reset to the last successful commit or amend the job commit with workflow status."
  fi

  local root changed_paths path disallowed_paths has_non_workflow has_jobs_tsv has_jobs_md jobs_tsv_rel jobs_md_rel
  root="$(git_repo_root)"
  changed_paths="$(git -C "$root" diff --name-only "$before_head..$after_head" --)"
  if [[ -z "$changed_paths" ]]; then
    set_status "$id" "Fail"
    die "Job $id advanced HEAD but no changed paths were found in the commit range."
  fi

  has_non_workflow=0
  has_jobs_tsv=0
  has_jobs_md=0
  disallowed_paths=""
  jobs_tsv_rel="$(workflow_file_rel_path "$root" "$JOBS_FILE" || true)"
  jobs_md_rel=""
  if [[ -f "$SCRIPT_DIR/jobs.md" ]]; then
    jobs_md_rel="$(workflow_file_rel_path "$root" "$SCRIPT_DIR/jobs.md" || true)"
  fi

  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    if [[ "$path" == .codex-jobs/* ]]; then
      if is_workflow_state_path "$path"; then
        [[ "$path" == "$jobs_tsv_rel" ]] && has_jobs_tsv=1
        [[ -n "$jobs_md_rel" && "$path" == "$jobs_md_rel" ]] && has_jobs_md=1
      else
        disallowed_paths+="$path"$'\n'
      fi
    else
      has_non_workflow=1
    fi
  done <<< "$changed_paths"

  if [[ -n "$disallowed_paths" ]]; then
    set_status "$id" "Fail"
    die "Job $id committed disallowed .codex-jobs paths. Only this workflow's jobs.tsv/jobs.md state files may be committed: ${disallowed_paths%$'\n'}"
  fi
  if [[ "$has_non_workflow" -ne 1 ]]; then
    set_status "$id" "Fail"
    die "Job $id committed workflow state but no project output outside .codex-jobs."
  fi
  if [[ "$has_jobs_tsv" -ne 1 ]]; then
    set_status "$id" "Fail"
    die "Job $id commit must include this workflow's jobs.tsv Done-state update."
  fi
  if [[ -n "$jobs_md_rel" && "$has_jobs_md" -ne 1 ]]; then
    set_status "$id" "Fail"
    die "Job $id commit must include this workflow's jobs.md Done-state update."
  fi

  local dirty_state
  dirty_state="$(workflow_state_dirty_status)"
  if [[ -n "$dirty_state" ]]; then
    die "Job $id left workflow state files uncommitted:\n$dirty_state"
  fi
}

build_runtime_prompt() {
  local id="$1"
  local prompt_file="$PROMPT_DIR/$id.md"
  local runtime_prompt="$RUNTIME_DIR/$id.prompt.md"
  local workflow_rel

  [[ -f "$prompt_file" ]] || die "Missing prompt file: $prompt_file"
  workflow_rel="the current workflow"
  if inside_git_repo; then
    workflow_rel="$(workflow_rel_path "$(git_repo_root)" || printf '%s' "the current workflow")"
  fi

  {
    cat "$prompt_file"
    printf '\n## Orchestrator Contract\n\n'
    printf -- '- This job id is `%s`.\n' "$id"
    printf -- '- The orchestrator sets this job to `Progress` before invoking Codex; that state is intentionally uncommitted.\n'
    printf -- '- The orchestrator invokes Codex from the repository root by default; use repository-relative paths.\n'
    printf -- '- Complete only this job and preserve unrelated user changes.\n'
    printf -- '- Before editing, stop if uncommitted project files exist outside `.codex-jobs/` workflow directories.\n'
    printf -- '- If the job cannot be completed safely, stop with a clear failure.\n'
    printf -- '- Before the final commit, mark this job `Done` in `%s/jobs.tsv` and `%s/jobs.md`.\n' "$workflow_rel" "$workflow_rel"
    printf -- '- After review and verification pass, create one focused git commit containing both the scoped job output and the workflow `jobs.tsv`/`jobs.md` state update. Do not commit logs, rollbacks, or `.runtime` files.\n'
    printf -- '- A successful job must leave project files clean and must advance HEAD with a commit.\n'
  } > "$runtime_prompt"

  printf '%s\n' "$runtime_prompt"
}

run_job() {
  local id="$1"
  local title
  title="$(title_of "$id")"
  local runtime_prompt
  runtime_prompt="$(build_runtime_prompt "$id")"
  local log_file="$LOG_DIR/$id.log"
  local exec_root
  exec_root="$(codex_workdir)"

  printf '\n==> %s: %s\n' "$id" "$title"
  printf 'Codex workdir: %s\n' "$exec_root"
  ensure_clean_before_job "$id"
  local before_head
  before_head="$(git_head)"
  set_status "$id" "Progress"

  set +e
  "$CODEX_BIN" "$CODEX_SUBCOMMAND" --cd "$exec_root" - < "$runtime_prompt" > "$log_file" 2>&1
  local rc=$?
  set -e

  cat "$log_file"

  if [[ "$rc" -ne 0 ]]; then
    if [[ "$FAIL_ON_NONZERO" == "1" ]]; then
      set_status "$id" "Fail"
      die "Job $id failed. See $log_file"
    fi
    die "Job $id stopped with exit code $rc and remains Progress. Next run stops if project files are dirty, or resets runtime state and retries when clean. See $log_file"
  fi

  ensure_clean_after_job "$id"
  ensure_commit_after_job "$id" "$before_head"
  printf 'Done: %s\n' "$id"
}

[[ -f "$JOBS_FILE" ]] || die "Missing jobs file: $JOBS_FILE"

failed_job="$(first_job_with_status Fail || true)"
if [[ -n "$failed_job" ]]; then
  die "Job $failed_job is Fail. Fix it or reset its status before continuing."
fi

if [[ "$REQUIRE_CLEAN_START" == "1" ]] && git_dirty_blocking; then
  print_blocking_status
  die "Uncommitted project files exist. Commit or stash them before running jobs."
fi

while true; do
  progress_job="$(first_job_with_status Progress || true)"
  [[ -n "$progress_job" ]] || break
  preserve_and_clear_progress "$progress_job"
done

for id in $(job_ids); do
  status="$(status_of "$id")"
  case "$status" in
    Done)
      printf 'Skip Done: %s\n' "$id"
      ;;
    ToDo)
      run_job "$id"
      if [[ "$RUN_ONE" == "1" ]]; then
        printf 'RUN_ONE=1, stopping after one completed job.\n'
        exit 0
      fi
      ;;
    Progress)
      die "Unexpected Progress state after rollback handling: $id"
      ;;
    Fail)
      die "Job $id is Fail. Stop."
      ;;
    *)
      die "Unknown status for $id: $status"
      ;;
  esac
done

printf '\nAll jobs completed.\n'
