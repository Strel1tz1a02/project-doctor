from typing import Any, Protocol, runtime_checkable

from project_doctor.models.common import EvidenceCheck, EvidenceRef


class EvidenceReader(Protocol):
    """A reads artifacts and verifies containment, size and checksum, not just the index."""

    async def verify(self, refs: list[EvidenceRef]) -> EvidenceCheck: ...


@runtime_checkable
class VerifiedJsonReader(Protocol):
    """Optional capability; hash-check the exact bytes subsequently decoded."""

    async def read_verified_json(self, ref: EvidenceRef) -> dict[str, Any]: ...
