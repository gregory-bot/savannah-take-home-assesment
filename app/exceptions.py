"""Custom exceptions for the Clinic API."""

from fastapi import HTTPException, status


class NotFoundError(HTTPException):
    """Resource not found (404)."""
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ConflictError(HTTPException):
    """Conflict with current state (409)."""
    def __init__(self, detail: str = "Conflict"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class ValidationError(HTTPException):
    """Unprocessable entity (422)."""
    def __init__(self, detail: str = "Validation error"):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


class SlotUnavailableError(HTTPException):
    """Slot is already taken (409)."""
    def __init__(self, detail: str = "Slot is not available"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)