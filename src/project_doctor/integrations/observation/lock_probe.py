"""Conservative MySQL lock sampling. Empty polling never establishes zero wait."""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from project_doctor.models.common import EvidenceRef
from project_doctor.models.lock import LOCK_KINDS, LockEvidence
from project_doctor.models.task import CallContext

Query = Callable[[CallContext, str], Awaitable[str]]
Publisher = Callable[[str, bytes, str, str], Awaitable[EvidenceRef]]

CAPABILITIES_SQL = (
    "SELECT JSON_OBJECT('version',VERSION(),'consumers',"
    "(SELECT JSON_ARRAYAGG(JSON_OBJECT('name',NAME,'enabled',ENABLED)) "
    "FROM performance_schema.setup_consumers),'instruments',"
    "(SELECT JSON_ARRAYAGG(JSON_OBJECT('name',NAME,'enabled',ENABLED,'timed',TIMED)) "
    "FROM performance_schema.setup_instruments WHERE NAME LIKE 'wait/lock/%'),"
    "'history_capacity',@@performance_schema_events_waits_history_long_size)"
)


def current_locks_sql(request_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise ValueError("invalid lock request correlation ID")
    scope = f"s.SQL_TEXT LIKE '/* pd:% request={request_id} */%'"
    return (
        "SELECT JSON_OBJECT('kind','innodb_data','thread_id',s.THREAD_ID,"
        "'event_id',s.EVENT_ID,'sql_text',s.SQL_TEXT,"
        "'blocking_thread_id',l.BLOCKING_THREAD_ID,'lock_id',l.REQUESTING_ENGINE_LOCK_ID) "
        "FROM performance_schema.data_lock_waits l JOIN "
        "performance_schema.events_statements_current s ON s.THREAD_ID=l.REQUESTING_THREAD_ID "
        f"WHERE {scope} UNION ALL "
        "SELECT JSON_OBJECT('kind','metadata','thread_id',s.THREAD_ID,"
        "'event_id',s.EVENT_ID,'sql_text',s.SQL_TEXT,'object',m.OBJECT_NAME) "
        "FROM performance_schema.metadata_locks m JOIN "
        "performance_schema.events_statements_current s ON s.THREAD_ID=m.OWNER_THREAD_ID "
        f"WHERE m.LOCK_STATUS='PENDING' AND {scope}"
    )


class LockCapture:
    def __init__(self, probe: "LockProbe", context: CallContext, request_id: str) -> None:
        self.probe = probe
        self.context = context
        self.request_id = request_id
        self.start = datetime.now(UTC)
        self.end = self.start
        self.capabilities: dict[str, Any] = {}
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.stop = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.refs: list[EvidenceRef] = []

    async def sample(self) -> None:
        try:
            raw = await self.probe.query(self.context, current_locks_sql(self.request_id))
            events = [json.loads(line) for line in raw.splitlines() if line.strip()]
            self.samples.append({"at": datetime.now(UTC).isoformat(), "events": events})
        except Exception as exc:
            self.errors.append(str(exc) or type(exc).__name__)

    async def poll(self) -> None:
        while not self.stop.is_set():
            try:
                await asyncio.wait_for(self.stop.wait(), self.probe.interval)
            except TimeoutError:
                await self.sample()

    async def finish(self) -> None:
        self.stop.set()
        if self.task is not None:
            await self.task
        self.end = datetime.now(UTC)
        base = (
            f"tasks/{self.context.task_id}/experiments/"
            f"{self.context.operation_id}/locks/{self.request_id}"
        )
        for name, payload in (
            ("capabilities", self.capabilities),
            ("raw-events", {"samples": self.samples, "errors": self.errors}),
            (
                "coverage",
                {
                    "request_id": self.request_id,
                    "start": self.start.isoformat(),
                    "end": self.end.isoformat(),
                    "poll_interval_seconds": self.probe.interval,
                    "coverage": "partial",
                    "zero_wait_supported": False,
                    "reason": "Current-lock sampling cannot exclude waits between samples",
                },
            ),
        ):
            self.refs.append(
                await self.probe.publish(
                    f"{base}/{name}.json",
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    "application/json",
                    "lock-sampling.v1",
                )
            )

    def evidence_for(
        self,
        sql_text: str,
        thread_id: int | None,
        event_id: int | None,
        table_wait_ms: float | None,
    ) -> LockEvidence:
        observed = table_wait_ms is not None and table_wait_ms > 0
        for sample in self.samples:
            for event in sample["events"]:
                # Current rows are associated to the active statement, not to
                # a lock's acquisition event (which may belong to a prior SQL).
                if (
                    " ".join(str(event.get("sql_text", "")).split()) == " ".join(sql_text.split())
                    and thread_id is not None
                    and event.get("thread_id") == thread_id
                    and event.get("event_id") == event_id
                ):
                    observed = True
        return LockEvidence(
            status="observed" if observed else "unknown",
            coverage="partial",
            missing_kinds=sorted(LOCK_KINDS),
            thread_id=thread_id,
            statement_event_id=event_id,
            window_start=self.start,
            window_end=self.end,
            evidence_refs=self.refs,
            reasons=["轮询当前锁不能排除采样间隙中的等待，完整总时长未知。"] + self.errors,
        )


class LockProbe:
    def __init__(self, *, query: Query, publish: Publisher, interval: float = 0.05) -> None:
        if interval <= 0:
            raise ValueError("lock polling interval must be positive")
        self.query = query
        self.publish = publish
        self.interval = interval

    async def begin(self, context: CallContext, request_id: str) -> LockCapture:
        current_locks_sql(request_id)
        capture = LockCapture(self, context, request_id)
        try:
            capture.capabilities = json.loads(await self.query(context, CAPABILITIES_SQL))
        except Exception as exc:
            capture.errors.append(str(exc) or type(exc).__name__)
        await capture.sample()
        capture.task = asyncio.create_task(capture.poll())
        return capture
