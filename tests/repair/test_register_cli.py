import json
from pathlib import Path

from project_doctor.models.task import TaskBundle
from scripts.register_repair_facts import main


def make_home(path: Path) -> TaskBundle:
    case = json.loads(
        (Path(__file__).parents[1] / "contracts/fixtures/verified_slow_query.json").read_text(
            encoding="utf-8"
        )
    )
    bundle = TaskBundle.model_validate(case["bundle"])
    path.mkdir()
    (path / "bundle.json").write_text(bundle.model_dump_json(), encoding="utf-8")
    return bundle


def test_cli_writes_and_clears_registration_files(tmp_path, monkeypatch):
    home = tmp_path / "home"
    bundle = make_home(home)
    transcript = tmp_path / "repair-session.jsonl"
    transcript.write_text('{"seq":1}\n', encoding="utf-8")
    argv = [
        "register_repair_facts",
        "--home",
        str(home),
        "--repair-session-id",
        "repair-session",
        "--repair-session-transcript",
        str(transcript),
        "--repair-decision-id",
        "decision-1",
        "--finding-id",
        bundle.findings[0].id,
    ]
    monkeypatch.setattr("sys.argv", argv)
    main()
    handoff = json.loads((home / "handoff.json").read_text(encoding="utf-8"))
    repair = json.loads((home / "repair.json").read_text(encoding="utf-8"))
    assert handoff["repair_id"] == "decision-1"
    assert repair["attempted"] is False
    # A later run without session evidence clears stale registrations.
    monkeypatch.setattr("sys.argv", ["register_repair_facts", "--home", str(home)])
    main()
    assert not (home / "handoff.json").exists()
    assert not (home / "repair.json").exists()
