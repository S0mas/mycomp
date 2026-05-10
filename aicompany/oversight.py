from .models import TaskStub

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule
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


def _display_task(stub: TaskStub, prior_output: str | None) -> None:
    """Render task details and prior output preview."""
    _rule(f"  CHECKPOINT — {stub.title}  ")
    _print()
    if _rich:
        _console.print(Panel(
            f"[bold]{stub.title}[/bold]",
            title=f"[yellow]Task {stub.id}[/yellow]",
            border_style="yellow",
        ))
    else:
        print(f"Task: {stub.id} — {stub.title}")

    if prior_output:
        _rule("  Prior task output (preview)  ")
        preview = prior_output[:2000]
        if len(prior_output) > 2000:
            preview += "\n\n[... truncated ...]"
        _print(preview)
        _print()


def _prompt_decision() -> str:
    """Prompt A/R/M and return 'approved', 'rejected', or 'modified'."""
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
            return "rejected"
        if choice in ("A", "R", "M"):
            return {"A": "approved", "R": "rejected", "M": "modified"}[choice]
        _print("Please enter A, R, or M.")


def _collect_modified_instructions() -> str:
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
    return "\n".join(lines).strip()


def checkpoint(stub: TaskStub, prior_output: str | None, project_id: str) -> tuple[str, str]:
    """
    Pause execution, show task context, and ask the user to approve/reject/modify.
    Returns (action, modified_instructions).
    """
    _display_task(stub, prior_output)
    action = _prompt_decision()

    if action == "rejected":
        _print("\nTask rejected. It will be skipped.\n")
        return "rejected", ""

    if action == "modified":
        modified = _collect_modified_instructions()
        _print("\nInstructions recorded. Task will execute with your modifications.\n")
        return "modified", modified

    _print("\nApproved. Executing task...\n")
    return "approved", ""
