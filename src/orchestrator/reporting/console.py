from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from orchestrator.reporting.events import LogEvent, clean_context


def _fmt_time(value: str | datetime | None) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, str) and value:
        return value
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass(slots=True)
class ConsoleReporter:
    mode: str = "default"  # default | verbose | debug
    warnings_in_run: int = 0

    def _print(self, text: str = "") -> None:
        print(text)

    def render(self, event: LogEvent) -> None:
        if self.mode == "debug":
            self._print(str(event.to_dict()))
            return

        name = event.name
        context = clean_context(event.context)

        if name == "loop_started":
            self._print("=" * 60)
            self._print("Execforge Loop Started")
            self._print(f"  Time: {_fmt_time(context.get('time'))}")
            self._print(f"  Agent: {context.get('agent')}")
            self._print(f"  Project: {context.get('project')}")
            self._print(f"  Prompt Source: {context.get('prompt_source')}")
            self._print(f"  Interval: {context.get('interval_seconds')}s")
            self._print(f"  Reset Only New Baseline: {str(context.get('reset_only_new_baseline', False)).lower()}")
            self._print(f"  Allow Dirty Working Tree: {str(context.get('allow_dirty_worktree', False)).lower()}")
            if context.get("branch_strategy"):
                self._print(f"  Branch Strategy: {context.get('branch_strategy')}")
            self._print("=" * 60)
            self._print("")
            return

        if name == "run_started":
            self.warnings_in_run = 0
            self._print("-" * 60)
            self._print("Execforge Run")
            self._print(f"  Run: {context.get('run_id')}")
            self._print(f"  Time: {_fmt_time(context.get('time'))}")
            self._print(f"  Agent: {context.get('agent')}")
            self._print(f"  Project: {context.get('project')}")
            self._print(f"  Prompt Source: {context.get('prompt_source')}")
            self._print("-" * 60)
            self._print("")
            return

        if name in {"prompt_sync_started", "repo_validate_started", "task_select_started", "branch_prepare_started", "steps_started"}:
            idx = event.phase_index or 0
            total = event.phase_total or 0
            self._print(f"[{idx}/{total}] {event.title}...")
            return

        if name == "prompt_synced":
            self._print(f"  Found {context.get('discovered_tasks', 0)} task")
            return

        if name == "repo_validated":
            branch = context.get("current_branch")
            if branch:
                self._print(f"  Current branch: {branch}")
            return

        if name == "task_selection_completed":
            if context.get("selected_task_id"):
                self._print(f"  Selected: {context.get('selected_task_id')}")
            else:
                self._print("  No task selected")
                self._print(f"  Reason: {context.get('reason')}")
                self._print(f"  Eligible tasks: {context.get('eligible_count', 0)}")
                self._print(f"  Excluded tasks: {context.get('excluded_count', 0)}")
                if self.mode == "verbose":
                    self._print(f"  Discovered tasks: {context.get('discovered_count', 0)}")
            return

        if name == "branch_prepared":
            if context.get("base_branch"):
                self._print(f"  Base: {context.get('base_branch')}")
            if context.get("branch"):
                self._print(f"  Branch: {context.get('branch')}")
            return

        if name == "step_completed":
            i = context.get("step_index")
            total = context.get("step_total")
            step = context.get("step")
            backend = context.get("backend")
            symbol = context.get("symbol", "✓")
            self._print(f"  [{i}/{total}] {symbol} {step:<16} {backend}")
            return

        if name == "step_failed":
            i = context.get("step_index", "?")
            total = context.get("step_total", "?")
            step = context.get("step", "unknown")
            backend = context.get("backend", "runtime")
            self._print(f"  [{i}/{total}] ✗ {step:<16} {backend}")
            self._print("")
            if context.get("base_branch"):
                self._print(f"      Base: {context.get('base_branch')}")
            if context.get("branch"):
                self._print(f"      Branch: {context.get('branch')}")
            if context.get("task_id"):
                self._print(f"      Task: {context.get('task_id')}")
            if context.get("error"):
                self._print(f"      Error: {context.get('error')}")
            return

        if name == "warning":
            self.warnings_in_run += 1
            self._print(f"⚠ {event.message}")
            if context.get("branch"):
                self._print(f"  Branch: {context.get('branch')}")
            if context.get("task_id"):
                self._print(f"  Task: {context.get('task_id')}")
            return

        if name == "run_noop":
            self._print("")
            self._print("Run complete")
            self._print("  Status: noop")
            self._print(f"  Reason: {context.get('reason', 'no actionable task found')}")
            if context.get("project"):
                self._print(f"  Project: {context.get('project')}")
            if context.get("warnings") is not None:
                self._print(f"  Warnings: {context.get('warnings')}")
            return

        if name == "run_completed":
            self._print("")
            self._print("Run complete")
            self._print(f"  Status: {context.get('status', 'success')}")
            if context.get("reason"):
                self._print(f"  Reason: {context.get('reason')}")
            if context.get("task_id"):
                self._print(f"  Task: {context.get('task_id')}")
            if context.get("branch"):
                self._print(f"  Branch: {context.get('branch')}")
            if context.get("steps_total") is not None and context.get("steps_passed") is not None:
                self._print(f"  Steps: {context.get('steps_passed')}/{context.get('steps_total')} passed")
            warnings = context.get("warnings", self.warnings_in_run)
            self._print(f"  Warnings: {warnings}")
            if context.get("log_path"):
                self._print(f"  Log File: {context.get('log_path')}")
            return

        if name == "run_failed":
            if self.mode == "verbose":
                self._print(f"  Failure reason: {context.get('reason')}")
            return

        if name == "loop_waiting":
            interval = int(context.get("interval_seconds", 0) or 0)
            next_at = context.get("next_run_at")
            if not next_at:
                next_at = _fmt_time(datetime.now() + timedelta(seconds=interval))
            self._print("")
            self._print("Waiting for next poll...")
            self._print(f"  Next run in: {interval}s")
            self._print(f"  Next run at: {next_at}")
            self._print("")
            return

        if self.mode == "verbose" and event.message:
            self._print(f"  {event.message}")


class NullReporter(ConsoleReporter):
    def __init__(self):
        super().__init__(mode="default")

    def render(self, event: LogEvent) -> None:
        return
