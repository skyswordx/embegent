from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from ..contracts import CommandRunResult


def safe_echo(text: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    normalized = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    typer.echo(normalized, err=err)


def run_command(
    command: list[str],
    cwd: Path | None = None,
    dry_run: bool = False,
    *,
    echo: bool = True,
) -> CommandRunResult:
    if echo:
        typer.echo("$ " + " ".join(command))
    command_result = CommandRunResult(
        command=list(command),
        cwd=str(cwd).replace("\\", "/") if cwd is not None else None,
        dry_run=dry_run,
    )
    if dry_run:
        return command_result

    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    command_result.stdout = completed.stdout
    command_result.stderr = completed.stderr
    command_result.returncode = completed.returncode
    if echo and completed.stdout:
        safe_echo(completed.stdout.rstrip())
    if completed.returncode != 0:
        if echo and completed.stderr:
            safe_echo(completed.stderr.rstrip(), err=True)
        raise typer.Exit(completed.returncode)
    if echo and completed.stderr:
        safe_echo(completed.stderr.rstrip(), err=True)
    return command_result
