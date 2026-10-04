"""Read-only HTTP boundary for runtime assignment evidence."""

from fastapi import HTTPException

from .runtime_assignments import PortableRuntimeAssignments, RuntimeAssignmentError


def register_runtime_assignment_routes(app, paths) -> None:
    service = PortableRuntimeAssignments(paths)

    @app.get("/api/runtime-assignments")
    def list_runtime_assignments():
        try:
            return service.overview()
        except RuntimeAssignmentError as exc:
            raise HTTPException(422, str(exc)) from exc
