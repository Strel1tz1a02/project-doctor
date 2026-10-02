"""Load A-owned factories only at the composition boundary."""

import importlib
from typing import cast

from project_doctor.entrypoints.settings import Settings
from project_doctor.features.diagnosis.ports import EvidenceReader
from project_doctor.features.experiments.ports import Runtime
from project_doctor.workflows.task_ports import TaskStore
from project_doctor.workflows.tools import ToolWorkflows


def bootstrap(settings: Settings, repository_manifest: dict[str, object]) -> ToolWorkflows:
    try:
        store_factory = importlib.import_module("project_doctor.integrations.mysql.factory")
        runtime_factory = importlib.import_module("project_doctor.integrations.runtime_factory")
        reader_factory = importlib.import_module("project_doctor.integrations.artifacts.factory")
    except ModuleNotFoundError as exc:
        raise RuntimeError("A 的 Runtime／MySQL／制品工厂尚未就绪，不能启动真实服务。") from exc
    store = cast(TaskStore, store_factory.build_store(settings))
    runtime = cast(Runtime, runtime_factory.build_runtime(settings, store))
    reader = cast(EvidenceReader, reader_factory.build_evidence_reader(settings))
    return ToolWorkflows(
        runtime=runtime, store=store, reader=reader, repository_manifest=repository_manifest
    )
