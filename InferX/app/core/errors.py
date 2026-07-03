from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError


class InferXError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(InferXError)
    async def inferx_error_handler(_: Request, exc: InferXError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"message": exc.message}},
        )

    @app.exception_handler(ValidationError)
    async def validation_error_handler(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"message": "Validation failed", "details": exc.errors()}},
        )
