"""API errors. Database rule violations surface as clear 409s, never as 500s."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError

log = logging.getLogger("lintel.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}


def not_found(what: str = "Not found") -> ApiError:
    return ApiError(404, "not_found", what)


def conflict(code: str, message: str, detail: dict | None = None) -> ApiError:
    return ApiError(409, code, message, detail)


def bad_request(code: str, message: str, detail: dict | None = None) -> ApiError:
    return ApiError(400, code, message, detail)


# Custom SQLSTATEs raised by the schema's triggers and functions.
DB_CODES = {
    "LN001": ("append_only", "That record is append-only."),
    "LN002": ("illegal_transition", "That change of state is not allowed."),
    "LN003": ("approval_invalid", "The approval is not valid for this submission."),
    "LN004": ("stale_fence", "This action belongs to an older attempt and was refused."),
    "LN005": ("terminal_state", "This application has finished; a correction is a new event."),
    "LN006": ("ledger_rule", "That fact change is not allowed."),
    "LN007": ("pairing", "Pairing failed."),
}


def db_error_response(exc: DBAPIError) -> JSONResponse | None:
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None)
    if sqlstate in DB_CODES:
        code, fallback = DB_CODES[sqlstate]
        message = str(getattr(orig, "diag", None) and orig.diag.message_primary or fallback)
        return JSONResponse(status_code=409, content={"error": {"code": code, "message": message}})
    if isinstance(exc, IntegrityError):
        constraint = getattr(getattr(orig, "diag", None), "constraint_name", None)
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "conflict", "message": "That conflicts with existing data.", "constraint": constraint}},
        )
    return None


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message, **({"detail": exc.detail} if exc.detail else {})}},
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid(_req: Request, exc: RequestValidationError) -> JSONResponse:
        # Same shape as every other error, so the web app can show one message.
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", ()) if x != "body")
        message = f"{where}: {first.get('msg', 'invalid')}" if where else str(first.get("msg", "The request was invalid."))
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": message,
                                                                "detail": {"errors": jsonable_encoder(exc.errors())}}})

    @app.exception_handler(DBAPIError)
    async def _db_error(_req: Request, exc: DBAPIError) -> JSONResponse:
        resp = db_error_response(exc)
        if resp is not None:
            return resp
        log.exception("database error")
        return JSONResponse(status_code=500, content={"error": {"code": "database", "message": "Database error."}})
