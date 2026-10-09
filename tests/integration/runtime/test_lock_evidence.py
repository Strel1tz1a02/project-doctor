"""Positive controls in a disposable, network-isolated MySQL container.

Enable explicitly with PROJECT_DOCTOR_LOCK_CONTROLS=1; no evaluation data is used.
"""

import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from project_doctor.integrations.artifacts.publish import publish_artifact
from project_doctor.integrations.observation.lock_probe import LockProbe
from project_doctor.integrations.observation.sql_probe import (
    attach_lock_evidence,
    perf_schema_row_to_sql_call,
)
from project_doctor.models.task import CallContext


@pytest.fixture(scope="module")
def mysql_control():
    if os.environ.get("PROJECT_DOCTOR_LOCK_CONTROLS") != "1":
        pytest.skip("real lock controls not enabled")
    docker = shutil.which("docker")
    if not docker:
        pytest.fail("lock controls enabled but Docker CLI missing")
    name = "pd-lock-control-" + uuid.uuid4().hex[:10]
    password = uuid.uuid4().hex
    env = dict(os.environ, MYSQL_ROOT_PASSWORD=password)
    subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "-e",
            "MYSQL_ROOT_PASSWORD",
            "mysql:8.4",
        ],
        env=env,
        check=True,
        capture_output=True,
    )

    def query(sql: str) -> str:
        completed = subprocess.run(
            [
                docker,
                "exec",
                "-i",
                name,
                "mysql",
                "-uroot",
                f"-p{password}",
                "--batch",
                "--raw",
                "--skip-column-names",
            ],
            input=sql,
            encoding="utf-8",
            capture_output=True,
            timeout=45,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr.replace(password, "<redacted>"))
        return completed.stdout.strip()

    def background(sql: str):
        process = subprocess.Popen(
            [
                docker,
                "exec",
                "-i",
                name,
                "mysql",
                "-uroot",
                f"-p{password}",
                "--batch",
                "--raw",
                "--skip-column-names",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process.stdin.write(sql.encode())
        process.stdin.close()
        return process

    try:
        deadline = time.monotonic() + 90
        while True:
            try:
                query("SELECT 1;")
                break
            except RuntimeError:
                if time.monotonic() > deadline:
                    pytest.fail("disposable MySQL did not become ready")
                time.sleep(0.25)
        query(
            "CREATE DATABASE app; "
            "CREATE TABLE app.control (id INT PRIMARY KEY, n INT) ENGINE=InnoDB; "
            "INSERT INTO app.control VALUES (1,1); "
            "UPDATE performance_schema.setup_consumers SET ENABLED='YES' "
            "WHERE NAME IN ('events_statements_current','events_statements_history_long'); "
            "UPDATE performance_schema.setup_instruments SET ENABLED='YES',TIMED='YES' "
            "WHERE NAME='wait/lock/metadata/sql/mdl';"
        )
        yield query, background
    finally:
        subprocess.run([docker, "rm", "-f", name], check=True, capture_output=True)


@pytest.mark.parametrize("kind", ["innodb_data", "metadata"])
def test_real_wait_is_associated_to_request(mysql_control, tmp_path: Path, kind: str) -> None:
    query, background = mysql_control
    blocker_sql = (
        "START TRANSACTION; SELECT * FROM app.control WHERE id=1 FOR UPDATE;"
        if kind == "innodb_data"
        else "LOCK TABLES app.control WRITE;"
    )
    blocker = background(blocker_sql + " DO SLEEP(30);")
    target = None
    try:
        deadline = time.monotonic() + 15
        while not query("SELECT ID FROM information_schema.PROCESSLIST WHERE INFO='DO SLEEP(30)';"):
            if time.monotonic() > deadline:
                pytest.fail("blocking transaction did not acquire its lock")
            time.sleep(0.05)

        async def exercise():
            nonlocal target
            request_id = uuid.uuid4().hex
            sql = f"/* pd:control.py:1 request={request_id} */ SELECT * FROM app.control WHERE id=1"
            if kind == "innodb_data":
                sql += " FOR UPDATE"

            async def fetch(context, sql):
                return await asyncio.to_thread(query, sql)

            async def publish(path, raw, media, version):
                return await publish_artifact(tmp_path, path, raw, media, version)

            capture = await LockProbe(query=fetch, publish=publish, interval=0.05).begin(
                CallContext(
                    task_id="control",
                    operation_id=kind,
                    missing_correlation=["agh_session_id", "tool_call_id"],
                ),
                request_id,
            )
            try:
                target = background(sql + ";")
                deadline = time.monotonic() + 10
                while not any(sample["events"] for sample in capture.samples):
                    if time.monotonic() > deadline:
                        pytest.fail("lock collector missed a sustained positive control")
                    await asyncio.sleep(0.05)
            finally:
                await capture.finish()
            event = next(event for sample in capture.samples for event in sample["events"])
            assert event["kind"] == kind
            proof = capture.evidence_for(sql, event["thread_id"], event["event_id"], None)
            assert proof.status == "observed" and proof.coverage == "partial"
            assert len(proof.evidence_refs) == 3
            assert not capture.errors, json.dumps(capture.errors)

        asyncio.run(exercise())
    finally:
        # Only this disposable container is queried/killed.
        for connection in query(
            "SELECT ID FROM information_schema.PROCESSLIST WHERE INFO='DO SLEEP(30)';"
        ).splitlines():
            query(f"KILL {int(connection)};")
        blocker.wait(timeout=10)
        if target:
            target.wait(timeout=10)


def test_real_completed_statement_has_valid_lock_metric_or_bound(mysql_control, tmp_path):
    query, _ = mysql_control

    async def run():
        request_id = uuid.uuid4().hex
        sql = f"/* pd:control.py:1 request={request_id} */ SELECT * FROM app.control"

        async def fetch(context, statement):
            return await asyncio.to_thread(query, statement)

        async def publish(path, raw, media, version):
            return await publish_artifact(tmp_path, path, raw, media, version)

        capture = await LockProbe(query=fetch, publish=publish).begin(
            CallContext(
                task_id="zero-control",
                operation_id="read",
                missing_correlation=["agh_session_id", "tool_call_id"],
            ),
            request_id,
        )
        await asyncio.to_thread(query, sql)
        await capture.finish()
        raw = query(
            "SELECT JSON_OBJECT('SQL_TEXT',SQL_TEXT,'TIMER_WAIT',TIMER_WAIT,"
            "'LOCK_TIME',LOCK_TIME,'ROWS_EXAMINED',ROWS_EXAMINED,'ROWS_SENT',ROWS_SENT,"
            "'THREAD_ID',THREAD_ID,'EVENT_ID',EVENT_ID) "
            "FROM performance_schema.events_statements_history_long "
            f"WHERE SQL_TEXT LIKE '/* pd:% request={request_id} */%' LIMIT 1;"
        )
        row = json.loads(raw)
        call = perf_schema_row_to_sql_call(
            row, commit="a" * 40, evidence_id="statement", call_id="s"
        )
        table_ms = float(row["LOCK_TIME"]) / 1_000_000_000
        evidence = capture.evidence_for(sql, row["THREAD_ID"], row["EVENT_ID"], table_ms)
        assert evidence.status == ("observed" if table_ms else "covered_no_wait"), evidence.reasons
        assert evidence.coverage == "complete"
        assert capture.exact_row_zero()
        assert evidence.residual_ms is None or evidence.residual_ms < 1
        associated = attach_lock_evidence(call, evidence)
        assert associated.lock_wait_ms == (0 if evidence.residual_ms is None else None)
        type(associated).model_validate(associated.model_dump())

    asyncio.run(run())
