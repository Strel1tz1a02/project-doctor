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

ROW_COUNTERS_SQL = (
    "SELECT JSON_MERGE_PATCH(JSON_OBJECTAGG(VARIABLE_NAME,VARIABLE_VALUE),JSON_OBJECT("
    "'metadata_time',(SELECT SUM_TIMER_WAIT FROM "
    "performance_schema.events_waits_summary_global_by_event_name "
    "WHERE EVENT_NAME='wait/lock/metadata/sql/mdl'),"
    "'metadata_count',(SELECT COUNT_STAR FROM "
    "performance_schema.events_waits_summary_global_by_event_name "
    "WHERE EVENT_NAME='wait/lock/metadata/sql/mdl'),"
    "'metadata_enabled',(SELECT IF(ENABLED='YES' AND TIMED='YES' AND "
    "(SELECT COUNT(*) FROM performance_schema.setup_consumers WHERE ENABLED='YES' "
    "AND NAME IN ('global_instrumentation','thread_instrumentation'))=2,1,0) "
    "FROM performance_schema.setup_instruments WHERE NAME='wait/lock/metadata/sql/mdl'))) "
    "FROM performance_schema.global_status WHERE VARIABLE_NAME IN "
    "('Innodb_row_lock_waits','Innodb_row_lock_time','Innodb_row_lock_current_waits','Uptime')"
)


def row_counters(raw: str) -> dict[str, int]:
    values = json.loads(raw)
    keys = (
        "Innodb_row_lock_waits",
        "Innodb_row_lock_time",
        "Innodb_row_lock_current_waits",
        "Uptime",
        "metadata_time",
        "metadata_count",
        "metadata_enabled",
    )
    result = {key: int(values[key]) for key in keys}
    if any(value < 0 for value in result.values()):
        raise ValueError("invalid row-lock counter")
    if result["metadata_enabled"] != 1:
        raise ValueError("metadata lock timing/instrumentation unavailable")
    return result


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
        self.counters_before: dict[str, int] | None = None
        self.counters_after: dict[str, int] | None = None

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
        try:
            self.counters_after = row_counters(
                await self.probe.query(self.context, ROW_COUNTERS_SQL)
            )
        except Exception as exc:
            self.errors.append(str(exc) or type(exc).__name__)
        self.end = datetime.now(UTC)
        base = (
            f"tasks/{self.context.task_id}/experiments/"
            f"{self.context.operation_id}/locks/{self.request_id}"
        )
        for name, payload in (
            ("capabilities", self.capabilities),
            (
                "raw-events",
                {
                    "samples": self.samples,
                    "errors": self.errors,
                    "counters_before": self.counters_before,
                    "counters_after": self.counters_after,
                },
            ),
            (
                "coverage",
                {
                    "request_id": self.request_id,
                    "start": self.start.isoformat(),
                    "end": self.end.isoformat(),
                    "poll_interval_seconds": self.probe.interval,
                    "coverage": "unknown"
                    if self.errors or self.metadata_bound_ms() is None
                    else "complete"
                    if self.exact_row_zero() and self.metadata_bound_ms() is not None
                    else "bounded",
                    "row_and_metadata_zero": self.exact_row_zero()
                    and self.metadata_bound_ms() == 0,
                    "residual_ms": self.metadata_bound_ms()
                    if self.exact_row_zero()
                    else self.residual_ms,
                    "reason": (
                        "原始全局行锁计数前后无增长且无活跃等待时支持行锁零等待；"
                        "否则仅以整个采集窗口约束未观测累计等待，采集失败不提供覆盖保证。"
                    ),
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

    @property
    def residual_ms(self) -> float:
        # Multiple short waits can fall between polls. A configured sleep is not
        # an upper bound on their total: use the entire capture window instead.
        return max((self.end - self.start).total_seconds() * 1000, self.probe.residual_ms)

    def exact_row_zero(self) -> bool:
        before, after = self.counters_before, self.counters_after
        return bool(
            not self.errors
            and before is not None
            and after is not None
            and after["Uptime"] >= before["Uptime"]
            and before["Innodb_row_lock_current_waits"]
            == after["Innodb_row_lock_current_waits"]
            == 0
            and before["Innodb_row_lock_waits"] == after["Innodb_row_lock_waits"]
            and before["Innodb_row_lock_time"] == after["Innodb_row_lock_time"]
        )

    def metadata_bound_ms(self) -> float | None:
        before, after = self.counters_before, self.counters_after
        if before is None or after is None:
            return None
        if (
            before["metadata_enabled"] != 1
            or after["metadata_enabled"] != 1
            or after["metadata_time"] < before["metadata_time"]
            or after["metadata_count"] < before["metadata_count"]
            or after["Uptime"] < before["Uptime"]
        ):
            return None
        # All timed metadata acquisitions in the DB window bound this SQL's
        # metadata delay, including waits that polling could not see.
        return (after["metadata_time"] - before["metadata_time"]) / 1_000_000_000

    def evidence_for(
        self,
        sql_text: str,
        thread_id: int | None,
        event_id: int | None,
        table_wait_ms: float | None,
    ) -> LockEvidence:
        """Classify lock evidence per statement.

        ``table_wait_ms`` is the statement's own ``LOCK_TIME`` (table lock
        wait, an actual measurement, not a sample). InnoDB row locks have no
        persistent per-statement history. Zero requires unchanged global counters
        around the request; empty polling alone only permits a capture-window bound.
        """
        normalized = " ".join(sql_text.split())
        row_wait_observed = False
        for sample in self.samples:
            for event in sample["events"]:
                # Current rows are associated to the active statement, not to
                # a lock's acquisition event (which may belong to a prior SQL).
                if (
                    " ".join(str(event.get("sql_text", "")).split()) == normalized
                    and thread_id is not None
                    and event.get("thread_id") == thread_id
                    and event.get("event_id") == event_id
                ):
                    row_wait_observed = True

        if row_wait_observed:
            return LockEvidence(
                status="observed",
                coverage="partial",
                missing_kinds=sorted(LOCK_KINDS),
                reasons=["观测到表/元数据或行锁等待。"] + self.errors,
                thread_id=thread_id,
                statement_event_id=event_id,
                window_start=self.start,
                window_end=self.end,
                evidence_refs=self.refs,
            )
        if (
            self.errors
            or not self.samples
            or table_wait_ms is None
            or thread_id is None
            or event_id is None
            or self.metadata_bound_ms() is None
        ):
            return LockEvidence(
                status="unknown",
                coverage="partial",
                missing_kinds=sorted(LOCK_KINDS),
                reasons=["采集或语句关联不完整，无法排除锁等待。"] + self.errors,
                thread_id=thread_id,
                statement_event_id=event_id,
                window_start=self.start,
                window_end=self.end,
                evidence_refs=self.refs,
            )
        row_zero = self.exact_row_zero()
        metadata_bound = self.metadata_bound_ms()
        assert metadata_bound is not None
        assert table_wait_ms is not None
        exact = row_zero and metadata_bound == 0 and table_wait_ms == 0
        bound = table_wait_ms + metadata_bound if row_zero else self.residual_ms
        # A zero global increment in the isolated request window is conservative:
        # unrelated waits prevent zero certification rather than being attributed
        # to this SQL. A nonzero/uncertain increment only permits a window bound.
        return LockEvidence(
            status="observed" if table_wait_ms > 0 else "covered_no_wait",
            coverage="complete",
            covered_kinds=sorted(LOCK_KINDS) if row_zero else ["table", "metadata"],
            missing_kinds=[],
            residual_ms=None if exact else bound,
            reasons=[
                "表锁 LOCK_TIME=0；行锁全局计数无增长且无活跃等待，元数据锁全局耗时无增长。"
                if exact
                else (
                    f"表锁实测 LOCK_TIME={table_wait_ms:g}ms；"
                    "元数据锁由启用计时的全局汇总差值约束；"
                    "行锁计数无增长时排除行锁，否则累计未观测等待以上下文整个窗口为界。"
                )
            ]
            + self.errors,
            thread_id=thread_id,
            statement_event_id=event_id,
            window_start=self.start,
            window_end=self.end,
            evidence_refs=self.refs,
        )


class LockProbe:
    def __init__(self, *, query: Query, publish: Publisher, interval: float = 0.05) -> None:
        if interval <= 0:
            raise ValueError("lock polling interval must be positive")
        self.query = query
        self.publish = publish
        self.interval = interval

    @property
    def residual_ms(self) -> float:
        """Minimum capture-window bound; the sleep alone is not a total-wait bound."""
        return self.interval * 1000

    async def begin(self, context: CallContext, request_id: str) -> LockCapture:
        current_locks_sql(request_id)
        capture = LockCapture(self, context, request_id)
        try:
            capture.capabilities = json.loads(await self.query(context, CAPABILITIES_SQL))
        except Exception as exc:
            capture.errors.append(str(exc) or type(exc).__name__)
        try:
            capture.counters_before = row_counters(await self.query(context, ROW_COUNTERS_SQL))
        except Exception as exc:
            capture.errors.append(str(exc) or type(exc).__name__)
        await capture.sample()
        capture.task = asyncio.create_task(capture.poll())
        return capture
