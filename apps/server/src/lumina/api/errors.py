from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError


class ApiProblem(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        field: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field
        self.details = details


def problem_payload(request: Request, problem: ApiProblem) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": problem.code,
        "message": problem.message,
        "requestId": getattr(request.state, "request_id", None),
    }
    if problem.field is not None:
        payload["field"] = problem.field
    if problem.details is not None:
        payload["details"] = problem.details
    return payload


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiProblem)
    async def handle_problem(request: Request, exc: ApiProblem) -> JSONResponse:
        return JSONResponse(problem_payload(request, exc), status_code=exc.status_code)

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(
        request: Request, exc: IntegrityError
    ) -> JSONResponse:
        del exc
        problem = ApiProblem(
            409,
            "conflict",
            "다른 변경과 충돌했습니다. 최신 상태를 불러온 뒤 다시 시도해 주세요.",
        )
        return JSONResponse(problem_payload(request, problem), status_code=409)

    @app.exception_handler(ValidationError)
    async def handle_validation_error(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        problem = ApiProblem(
            422,
            "validation_failed",
            "입력값을 확인해 주세요.",
            details=exc.errors(include_url=False),
        )
        return JSONResponse(problem_payload(request, problem), status_code=422)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        problem = ApiProblem(
            422,
            "validation_failed",
            "입력값을 확인해 주세요.",
            details=exc.errors(),
        )
        return JSONResponse(problem_payload(request, problem), status_code=422)
