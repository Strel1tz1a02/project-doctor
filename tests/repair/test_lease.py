"""Only one live worker can own a repair identity."""

from pathlib import Path

import pytest

from project_doctor.integrations.repair.lease import RepairBusy, repair_lease


def test_repair_lease_refuses_overlap_and_releases_after_exit(tmp_path: Path) -> None:
    with repair_lease(tmp_path, "repair-1"):
        with pytest.raises(RepairBusy, match="still running"):
            with repair_lease(tmp_path, "repair-1"):
                pytest.fail("second repair worker acquired an active lease")
        with repair_lease(tmp_path, "repair-2"):
            pass
    with repair_lease(tmp_path, "repair-1"):
        pass
