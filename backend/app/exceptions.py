from fastapi import HTTPException, status


class NotFoundError(HTTPException):
    def __init__(self, resource: str, resource_id: int):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} with id {resource_id} not found.",
        )


class SlotUnavailableError(HTTPException):
    def __init__(self, reason: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=reason,
        )


class ValidationError(HTTPException):
    def __init__(self, reason: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=reason,
        )


class ConflictError(HTTPException):
    def __init__(self, reason: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=reason,
        )
