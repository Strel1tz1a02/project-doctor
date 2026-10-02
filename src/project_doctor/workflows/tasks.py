import hashlib

from project_doctor.models.common import Limits, Usage
from project_doctor.models.environment import ProjectInput
from project_doctor.models.task import CallContext, TaskRecord
from project_doctor.workflows.task_ports import TaskStore


async def create_task(
    project: ProjectInput, limits: Limits, operation_id: str, store: TaskStore
) -> TaskRecord:
    if not operation_id.strip():
        raise ValueError("creation operation_id cannot be empty")
    task_id = "task-" + hashlib.sha256(operation_id.encode()).hexdigest()[:24]
    try:
        previous = await store.get(task_id)
    except KeyError:
        previous = None
    if previous is not None:
        if previous.project != project or previous.limits != limits:
            raise ValueError("operation_conflict: same creation key with different input")
        return previous
    context = CallContext(
        task_id=task_id,
        operation_id=operation_id,
        missing_correlation=["agh_session_id", "tool_call_id"],
    )
    record = TaskRecord(
        id=task_id,
        project=project,
        status="created",
        limits=limits,
        usage=Usage(),
        correlation=context,
    )
    await store.create(record)
    return await store.get(task_id)
