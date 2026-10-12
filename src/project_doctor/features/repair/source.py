"""Present only bounded, versioned source context to the patch proposing model."""

from __future__ import annotations

import hashlib

from project_doctor.models.repair import RepairTarget, RepairTargetView


def present_target(finding_id: str, target: RepairTarget) -> RepairTargetView:
    identity = "\n".join(
        (
            finding_id,
            target.source_commit,
            target.mapper_path,
            str(target.mapper_line),
            target.mapper_sha256,
            target.caller_path,
            str(target.caller_line),
            target.caller_sha256,
            target.parent_key_column,
            target.child_table,
            target.key_column,
        )
    )
    return RepairTargetView(
        finding_id=finding_id,
        source_commit=target.source_commit,
        target_sha256=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        mapper_path=target.mapper_path,
        mapper_line=target.mapper_line,
        mapper_method=target.mapper_method,
        child_table=target.child_table,
        key_column=target.key_column,
        mapper_sha256=target.mapper_sha256,
        mapper_context=target.mapper_context,
        caller_path=target.caller_path,
        caller_line=target.caller_line,
        parent_key_column=target.parent_key_column,
        caller_sha256=target.caller_sha256,
        caller_context=target.caller_context,
    )
