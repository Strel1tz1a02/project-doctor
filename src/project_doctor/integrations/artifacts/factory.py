"""Composition factory for the file-backed EvidenceReader."""

from __future__ import annotations

from project_doctor.entrypoints.settings import Settings
from project_doctor.features.diagnosis.ports import EvidenceReader
from project_doctor.integrations.artifacts.verify import FileEvidenceReader


def build_evidence_reader(settings: Settings) -> EvidenceReader:
    """Return the real file-backed reader; construction is synchronous, reads are async."""
    return FileEvidenceReader(settings.artifact_root)
