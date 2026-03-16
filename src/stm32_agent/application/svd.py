from __future__ import annotations

from pathlib import Path

from ..contracts import SvdFetchResult
from ..infrastructure import svd as svd_ops


def fetch_svd_file(
    *,
    chip: str,
    workspace: Path,
    output: Path | None = None,
    force: bool = False,
) -> SvdFetchResult:
    result = svd_ops.fetch_svd(chip=chip, workspace=workspace, output=output, force=force)
    return SvdFetchResult(
        chip=str(result["chip"]),
        family_dir=str(result["family_dir"]),
        candidate_name=str(result["candidate_name"]),
        local_path=str(result["local_path"]).replace("\\", "/"),
        source_url=str(result["source_url"]),
        reused=bool(result["reused"]),
    )
