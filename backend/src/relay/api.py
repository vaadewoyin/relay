import json
import logging
import os
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal
from uuid import UUID, uuid4

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException

from relay.domain import (
    ActionItem,
    Conflict,
    Forbidden,
    Handover,
    HandoverReceipt,
    IntegrityFinding,
    ReviewDecision,
)
from relay.intelligence.analysis import AnalysisBudget, Analyzer
from relay.intelligence.contracts import Execution
from relay.intelligence.gemini import DEFAULT_MODEL, GeminiProvider
from relay.intelligence.provider import ModelProvider
from relay.intelligence.workflow import Intelligence
from relay.notion.client import NotionClient, NotionError, Sources
from relay.notion.records import ImportResult, Publication, SyncStatus
from relay.notion.sync import NotionSync
from relay.service import (
    AcceptHandover,
    ActionUpdate,
    InvalidInput,
    NotFound,
    PreviewHandover,
    RelayService,
    ReportDetails,
    ReportIntake,
    ReviewFinding,
)
from relay.store import SQLiteStore

logger = logging.getLogger("relay.api")


def database_path() -> Path:
    return Path(os.environ.get("RELAY_DB_PATH", "relay.sqlite3")).expanduser()


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class ReceiptView(HandoverReceipt):
    notion_sync: SyncStatus | None = None


class AnalyzeShift(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shift_id: UUID
    operation_id: UUID


class ValidationIssue(BaseModel):
    location: list[str | int]
    code: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    issues: list[ValidationIssue] | None = None


def get_service(request: Request) -> RelayService:
    return request.app.state.service


Service = Annotated[RelayService, Depends(get_service)]


def log_event(event: str, **fields: object) -> None:
    logger.info(
        json.dumps(
            {"timestamp": datetime.now(UTC).isoformat(), "event": event, **fields}
        )
    )


def create_app(
    db_path: Path | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
    model_provider: ModelProvider | None = None,
) -> FastAPI:
    store = SQLiteStore(db_path or database_path())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.initialize()
        app.state.service = RelayService(store, clock) if clock else RelayService(store)
        try:
            provider = model_provider or GeminiProvider.from_environment()
            budget = AnalysisBudget.from_environment()
        except ValueError:
            log_event("ai_configuration_invalid")
            provider, budget = GeminiProvider(None, DEFAULT_MODEL), AnalysisBudget()
        app.state.intelligence = Intelligence(
            store,
            Analyzer(provider, budget),
            allow_operational_data=os.getenv("RELAY_AI_ALLOW_OPERATIONAL_DATA") == "1",
        )
        notion_client = None
        app.state.notion = None
        if token := os.getenv("NOTION_TOKEN"):
            try:
                sources = Sources.from_environment()
            except (KeyError, ValueError):
                log_event("notion_configuration_incomplete")
            else:
                notion_client = NotionClient(token)
                app.state.notion = NotionSync(notion_client, sources, store)
        log_event("database_ready")
        try:
            yield
        finally:
            if notion_client is not None:
                notion_client.close()

    app = FastAPI(
        title="Relay",
        version="0.1.0",
        description="Deterministic facilities handover API for a trusted local demonstration.",
        lifespan=lifespan,
        responses={
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )

    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = str(uuid4())
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                json.dumps(
                    {
                        "event": "unhandled_request_error",
                        "request_id": request.state.request_id,
                        "exception_type": type(exc).__name__,
                    }
                )
            )
            response = error(
                request, 500, "internal_error", "An internal error occurred."
            )
        response.headers["X-Request-ID"] = request.state.request_id
        route = request.scope.get("route")
        log_event(
            "http_request",
            request_id=request.state.request_id,
            method=request.method,
            route=getattr(route, "path", None),
            status=response.status_code,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
        return response

    def error(
        request: Request,
        status: int,
        code: str,
        message: str,
        issues: list[ValidationIssue] | None = None,
    ) -> JSONResponse:
        payload = ErrorResponse(
            code=code,
            message=message,
            request_id=request.state.request_id,
            issues=issues,
        )
        return JSONResponse(
            status_code=status, content=payload.model_dump(exclude_none=True)
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        issues = [
            ValidationIssue(location=list(issue["loc"]), code=issue["type"])
            for issue in exc.errors()
        ]
        return error(
            request, 422, "validation_error", "Request validation failed.", issues
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code, message = {
            404: ("not_found", "Route does not exist."),
            405: ("method_not_allowed", "Method is not allowed on this route."),
        }.get(exc.status_code, ("http_error", "HTTP request failed."))
        response = error(request, exc.status_code, code, message)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(Conflict)
    async def conflict(request: Request, exc: Conflict) -> JSONResponse:
        return error(request, 409, exc.code, str(exc))

    @app.exception_handler(NotFound)
    async def missing(request: Request, exc: NotFound) -> JSONResponse:
        return error(request, 404, "not_found", str(exc))

    @app.exception_handler(Forbidden)
    async def forbidden(request: Request, exc: Forbidden) -> JSONResponse:
        return error(request, 403, "forbidden", str(exc))

    @app.exception_handler(InvalidInput)
    async def invalid(request: Request, exc: InvalidInput) -> JSONResponse:
        return error(request, 422, "invalid_operation", str(exc))

    @app.exception_handler(sqlite3.OperationalError)
    async def storage_error(
        request: Request, exc: sqlite3.OperationalError
    ) -> JSONResponse:
        if exc.sqlite_errorcode & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            response = error(
                request, 503, "database_busy", "Retry the same operation after a delay."
            )
            response.headers["Retry-After"] = "1"
            return response
        logger.error(
            json.dumps(
                {
                    "event": "storage_error",
                    "request_id": request.state.request_id,
                    "sqlite_error": exc.sqlite_errorname,
                }
            )
        )
        return error(request, 500, "storage_error", "A storage error occurred.")

    @app.get("/health")
    def health() -> Health:
        return Health()

    @app.post("/reports", status_code=201)
    def intake(command: ReportIntake, service: Service) -> ReportDetails:
        return service.intake(command)

    @app.get("/reports/{report_id}")
    def report(report_id: UUID, service: Service) -> ReportDetails:
        return service.report(report_id)

    @app.patch("/actions/{action_id}")
    def update_action(
        action_id: UUID, command: ActionUpdate, service: Service
    ) -> ActionItem:
        return service.update_action(action_id, command)

    @app.get("/actions/{action_id}")
    def get_action(action_id: UUID, service: Service) -> ActionItem:
        return service.get(ActionItem, action_id)

    @app.get("/findings")
    def findings(service: Service) -> list[IntegrityFinding]:
        return service.findings()

    @app.post("/ai/analyses")
    async def analyze(command: AnalyzeShift, request: Request) -> Execution:
        intelligence: Intelligence = request.app.state.intelligence
        return await intelligence.run(
            command.shift_id, command.operation_id, request.state.request_id
        )

    @app.get("/ai/analyses/{execution_id}")
    def analysis(execution_id: UUID, service: Service) -> Execution:
        return service.get(Execution, execution_id)

    @app.get("/findings/{finding_id}")
    def finding(finding_id: UUID, service: Service) -> IntegrityFinding:
        return service.finding(finding_id)

    @app.post("/findings/{finding_id}/reviews", status_code=201)
    def review(
        finding_id: UUID, command: ReviewFinding, service: Service
    ) -> ReviewDecision:
        return service.review(finding_id, command)

    @app.get("/reviews/{review_id}")
    def get_review(review_id: UUID, service: Service) -> ReviewDecision:
        return service.get(ReviewDecision, review_id)

    @app.post("/handovers", status_code=201)
    def preview(command: PreviewHandover, service: Service) -> Handover:
        return service.preview(command)

    @app.get("/handovers/{handover_id}")
    def get_handover(handover_id: UUID, service: Service) -> Handover:
        return service.get(Handover, handover_id)

    @app.post("/handovers/{handover_id}/acceptance", status_code=201)
    def accept(
        handover_id: UUID, command: AcceptHandover, service: Service
    ) -> HandoverReceipt:
        return service.accept(handover_id, command)

    def get_notion(request: Request) -> NotionSync:
        sync = request.app.state.notion
        if sync is None:
            raise NotionError("not_configured")
        return sync

    @app.exception_handler(NotionError)
    async def notion_failure(request: Request, exc: NotionError) -> JSONResponse:
        return error(request, 503, exc.code, "Notion request unavailable.")

    @app.get("/notion/connection")
    def notion_connection(request: Request) -> Health:
        get_notion(request).verify()
        return Health()

    @app.post("/notion/import")
    def import_notion(request: Request) -> ImportResult:
        result = get_notion(request).pull()
        log_event(
            "notion_import",
            request_id=request.state.request_id,
            **result.model_dump(exclude={"report_ids", "failures"}),
        )
        return result

    @app.post("/notion/receipts/{receipt_id}/sync")
    def sync_receipt(
        receipt_id: UUID, service: Service, request: Request
    ) -> tuple[Publication, ...]:
        stored = service.get(HandoverReceipt, receipt_id)
        result = get_notion(request).publish(stored)
        log_event(
            "notion_publication",
            request_id=request.state.request_id,
            receipt_id=str(receipt_id),
            states=[item.state for item in result],
        )
        return result

    @app.get("/handover-receipts/{receipt_id}", response_model_exclude_unset=True)
    def receipt(receipt_id: UUID, service: Service, request: Request) -> ReceiptView:
        stored = service.get(HandoverReceipt, receipt_id)
        sync: NotionSync | None = request.app.state.notion
        return ReceiptView(
            **stored.model_dump(),
            **({"notion_sync": sync.status(stored)} if sync else {}),
        )

    return app


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("RELAY_LOG_LEVEL", "INFO"), format="%(message)s"
    )
    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=int(os.environ.get("RELAY_PORT", "8000")),
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
