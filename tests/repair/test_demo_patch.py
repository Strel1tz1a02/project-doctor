"""A real Java/MyBatis batch rewrite passes the isolated patch boundary."""

import difflib
import shutil
import subprocess
from pathlib import Path

import pytest

from project_doctor.integrations.repair.build import build_image
from project_doctor.integrations.repair.source import apply_patch, inspect_target
from project_doctor.models.common import CodeLocation
from project_doctor.models.n_plus_one import BatchQuerySpec

ROOT = Path(__file__).resolve().parents[2] / "demo/slow-query-demo"
MAPPER = "src/main/java/com/example/slowquery/mapper/OrderMapper.java"
SERVICE = "src/main/java/com/example/slowquery/service/OrderService.java"


def _target():
    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    spec = BatchQuerySpec(
        strategy="batch_in",
        child_template="SELECT * FROM users WHERE id = ?",
        key_column="id",
        child_code_location=CodeLocation(
            commit=commit, path=MAPPER, line=40, association_evidence_ids=["source-location"]
        ),
        observed_child_count=20,
        parent_sql_call_ids=["parent-1"],
    )
    return inspect_target(ROOT, spec, commit)


def _batch_diff() -> str:
    mapper = (ROOT / MAPPER).read_text(encoding="utf-8")
    service = (ROOT / SERVICE).read_text(encoding="utf-8")
    revised_mapper = mapper.replace(
        '    @Select("SELECT * FROM users WHERE id = #{id}")\n'
        '    User findUserById(@Param("id") Long id);',
        '    @Select({"<script>", "SELECT * FROM users WHERE id IN",\n'
        "        \"<foreach item='id' collection='ids' "
        "open='(' separator=',' close=')'>\",\n"
        '        "#{id}", "</foreach>", "</script>"})\n'
        '    List<User> findUserById(@Param("ids") List<Long> ids);',
    )
    revised_service = (
        service.replace(
            "import java.util.List;",
            "import java.util.List;\nimport java.util.Map;\nimport java.util.HashMap;\n"
            "import java.util.Set;\nimport java.util.LinkedHashSet;",
        )
        .replace(
            "        List<OrderVO> result = new ArrayList<>();",
            "        List<OrderVO> result = new ArrayList<>();\n"
            "        Map<Long, User> usersById = new HashMap<>();\n"
            "        if (!orders.isEmpty()) {\n"
            "            Set<Long> userIds = new LinkedHashSet<>();\n"
            "            for (Order order : orders) userIds.add(order.getUserId());\n"
            "            for (User user : orderMapper.findUserById(new ArrayList<>(userIds))) {\n"
            "                usersById.put(user.getId(), user);\n"
            "            }\n"
            "        }",
        )
        .replace(
            "User user = orderMapper.findUserById(order.getUserId());",
            "User user = usersById.get(order.getUserId());",
        )
    )
    chunks = []
    for path, before, after in (
        (MAPPER, mapper, revised_mapper),
        (SERVICE, service, revised_service),
    ):
        assert before != after
        chunks.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
    return "".join(chunks)


def test_demo_batch_patch_changes_only_isolated_source(tmp_path: Path) -> None:
    target = _target()
    original_mapper = (ROOT / MAPPER).read_bytes()
    original_service = (ROOT / SERVICE).read_bytes()
    source = apply_patch(target, _batch_diff(), tmp_path / "isolated")
    assert source.changed_paths == (MAPPER, SERVICE)
    assert "List<User> findUserById" in (source.root / MAPPER).read_text(encoding="utf-8")
    assert "findUserById(order.getUserId())" not in (source.root / SERVICE).read_text(
        encoding="utf-8"
    )
    assert (ROOT / MAPPER).read_bytes() == original_mapper
    assert (ROOT / SERVICE).read_bytes() == original_service


def test_demo_batch_patch_builds_real_image_when_docker_available(tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI unavailable; real Java image build unverified")
    info = subprocess.run(["docker", "info"], capture_output=True, timeout=15, check=False)
    if info.returncode != 0:
        pytest.skip("Docker daemon unavailable; real Java image build unverified")
    source = apply_patch(_target(), _batch_diff(), tmp_path / "isolated")
    image = build_image(source, timeout_seconds=600)
    assert image.digest.startswith("sha256:")
