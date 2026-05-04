from datetime import datetime, timezone

from .models import Task

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.text import Text
    _rich = True
    _console = Console()
except ImportError:
    _rich = False


def _print(msg: str = "") -> None:
    if _rich:
        _console.print(msg)
    else:
        print(msg)


def _rule(title: str = "") -> None:
    if _rich:
        _console.print(Rule(title, style="bold yellow"))
    else:
        print(f"\n{'─' * 60}  {title}")


def checkpoint(task: Task, prior_output: str | None, project_id: str) -> tuple[str, str]:
    """
    Pause execution, show task context, and ask the user to approve/reject/modify.

    Returns (action, modified_instructions) where action is one of:
      'approved' | 'rejected' | 'modified'
    """
    _rule(f"  CHECKPOINT — {task.title}  ")
    _print()

    if _rich:
        _console.print(Panel(
            f"[bold]{task.title}[/bold]\n\n{task.description}",
            title=f"[yellow]Task {task.id}[/yellow]",
            border_style="yellow",
        ))
    else:
        print(f"Task: {task.id} — {task.title}")
        print(f"\n{task.description}\n")

    if prior_output:
        _rule("  Prior task output (preview)  ")
        preview = prior_output[:2000]
        if len(prior_output) > 2000:
            preview += "\n\n[... truncated ...]"
        _print(preview)
        _print()

    _rule("  Decision required  ")
    _print("[A] Approve and execute this task")
    _print("[R] Reject and skip this task")
    _print("[M] Modify instructions before executing")
    _print()

    while True:
        try:
            choice = input("Your choice (A/R/M): ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            _print("\nAborted — treating as Reject.")
            return "rejected", ""

        if choice in ("A", "R", "M"):
            break
        _print("Please enter A, R, or M.")

    modified_instructions = ""

    if choice == "R":
        _print("\nTask rejected. It will be skipped.\n")
        return "rejected", ""

    if choice == "M":
        _print("\nEnter your modified instructions (press Enter twice when done):")
        lines = []
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                break
            if line == "" and lines and lines[-1] == "":
                break
            lines.append(line)
        modified_instructions = "\n".join(lines).strip()
        _print("\nInstructions recorded. Task will execute with your modifications.\n")
        return "modified", modified_instructions

    _print("\nApproved. Executing task...\n")
    return "approved", ""
