from app.models import File
from app.schemas.file import FileInfoResponse


def file_to_info(file: File) -> FileInfoResponse:
    return FileInfoResponse.model_validate(file, from_attributes=True)
