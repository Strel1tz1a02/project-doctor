from typing import Protocol

from project_doctor.models.common import EvidenceCheck, EvidenceRef


class EvidenceReader(Protocol):
    """A reads artifacts and verifies containment, size and checksum, not just the index."""

    async def verify(self, refs: list[EvidenceRef]) -> EvidenceCheck: ...
