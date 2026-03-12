from __future__ import annotations

from pathlib import Path

import typer

from .. import svd as svd_ops
from . import verify as verify_tools


def run_fetch_svd(
    *,
    chip: str,
    workspace: Path,
    output: Path | None = None,
    force: bool = False,
) -> None:
    resolved_workspace = workspace.resolve()
    result = svd_ops.fetch_svd(chip=chip, workspace=resolved_workspace, output=output, force=force)
    if not result["reused"]:
        verify_tools.record_verification(
            resolved_workspace,
            action="svd_fetch",
            ok=True,
            summary=f"Fetched SVD for {result['chip']}: {result['candidate_name']}",
            verification_status="cli_verified",
            evidence={
                "source_url": result["source_url"],
                "local_path": str(result["local_path"]).replace("\\", "/"),
            },
            state={"chip": result["chip"], "family_dir": result["family_dir"]},
        )
    typer.echo(f"SVD fetched: {result['local_path']}")
