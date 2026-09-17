"""Provider Worker稼働状況のREAD API。"""

from typing import Annotated

from fastapi import Depends

from .security import Permission, Principal


def install_worker_status_routes(app, authorize, service) -> None:
    read = authorize.require(Permission.READ)

    @app.get("/api/worker-status")
    def list_worker_status(
        _principal: Annotated[Principal, Depends(read)],
    ):
        return service.list_status()
