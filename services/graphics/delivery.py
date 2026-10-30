"""Preverified disk spools, bounded response memory, and disconnect cleanup."""
from pathlib import Path
import tempfile

from starlette.responses import FileResponse
from evidence import verified_copy


class TemporaryFileResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            Path(self.path).unlink(missing_ok=True)


def temporary_path(suffix):
    descriptor = tempfile.NamedTemporaryFile(prefix="scriptor-export-", suffix=suffix, delete=False)
    path = Path(descriptor.name)
    descriptor.close()
    return path


def artifact_response(folder, name, digest, media_type):
    path = temporary_path(".artifact")
    try:
        with path.open("wb") as stream:
            verified_copy(folder, name, digest, stream)
        return TemporaryFileResponse(path, media_type=media_type)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
