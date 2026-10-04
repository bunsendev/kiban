"""HTTP read and manual rescan boundary for the Portable drop folder."""

from fastapi import HTTPException

from .drop_folder import DropFolderBusyError, DropFolderError


def register_drop_folder_routes(app, service) -> None:
    @app.get("/api/drop-folder")
    def drop_folder():
        return service.view()

    @app.post("/api/drop-folder/scan")
    def scan_drop_folder():
        try:
            return service.scan(force=True)
        except DropFolderBusyError as exc:
            raise HTTPException(409, str(exc)) from exc
        except DropFolderError as exc:
            raise HTTPException(422, str(exc)) from exc
