from __future__ import annotations

from ..contracts import DoctorCheck, DoctorResult
from ..infrastructure import project as project_ops


def run_doctor(project: project_ops.ProjectConfig) -> DoctorResult:
    backend = project_ops.resolve_backend(project)
    ok = True
    required_keys = project_ops.doctor_required_keys(project)
    checks: list[DoctorCheck] = []
    for name, result in project_ops.doctor_checks(project):
        checks.append(DoctorCheck(name=name, result=result, required=name in required_keys))
        if name in required_keys and (result == "MISSING" or result.startswith("MISSING:")):
            ok = False

    return DoctorResult(
        backend=backend,
        checks=checks,
        ok=ok,
        required_keys=list(required_keys),
    )
