"""A model patch is constrained to the diagnosed Java/MyBatis call chain."""

import difflib
import hashlib
import subprocess
from pathlib import Path

import pytest

from project_doctor.integrations.repair.source import (
    _patched_select_sql,
    apply_patch,
    inspect_target,
)
from project_doctor.models.common import CodeLocation
from project_doctor.models.n_plus_one import BatchQuerySpec

MAPPER = """package demo;
import org.apache.ibatis.annotations.Select;
interface UserMapper {
    @Select("SELECT * FROM users WHERE id = #{id}")
    User findUserById(Long id);
}
"""
SERVICE = """package demo;
class OrderService {
    UserMapper mapper;
    void search() {
        for (Order order : orders) {
            mapper.findUserById(order.getUserId());
        }
    }
}
"""
MAPPER_PATH = "src/main/java/demo/UserMapper.java"
SERVICE_PATH = "src/main/java/demo/OrderService.java"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _project(tmp_path: Path) -> tuple[Path, BatchQuerySpec, str]:
    root = tmp_path / "target"
    for path, content in ((MAPPER_PATH, MAPPER), (SERVICE_PATH, SERVICE)):
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
    (root / ".gitignore").write_text("secret.env\n", encoding="utf-8")
    (root / "secret.env").write_text("private-build-input", encoding="utf-8")
    _git(root, "init")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-m", "base")
    commit = _git(root, "rev-parse", "HEAD")
    spec = BatchQuerySpec(
        strategy="batch_in",
        child_template="SELECT * FROM users WHERE id = ?",
        key_column="id",
        child_code_location=CodeLocation(
            commit=commit,
            path=MAPPER_PATH,
            line=4,
            association_evidence_ids=["location-evidence"],
        ),
        observed_child_count=20,
        parent_sql_call_ids=["parent-call"],
    )
    return root, spec, commit


def _patch(*, hardcoded: bool = False) -> str:
    revised_mapper = MAPPER.replace(
        '    @Select("SELECT * FROM users WHERE id = #{id}")\n    User findUserById(Long id);',
        '    @Select({"<script>", "SELECT * FROM users WHERE id IN",\n'
        "        \"<foreach item='id' collection='ids' open='(' separator=',' close=')'>\",\n"
        '        "#{id}", "</foreach>", "</script>"})\n'
        "    java.util.List<User> findUserById(java.util.List<Long> ids);",
    )
    if hardcoded:
        revised_mapper = revised_mapper.replace(
            '    @Select({"<script>", "SELECT * FROM users WHERE id IN",\n'
            "        \"<foreach item='id' collection='ids' open='(' separator=',' close=')'>\",\n"
            '        "#{id}", "</foreach>", "</script>"})',
            '    @Select("SELECT * FROM users WHERE id IN (1, 2)")',
        )
    revised_service = SERVICE.replace(
        "        for (Order order : orders) {\n            mapper.findUserById(order.getUserId());",
        "        mapper.findUserById(ids);\n"
        "        for (Order order : orders) {\n"
        "            // use prefetched users",
    )
    parts = []
    for path, before, after in (
        (MAPPER_PATH, MAPPER, revised_mapper),
        (SERVICE_PATH, SERVICE, revised_service),
    ):
        parts.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
    return "".join(parts)


def test_inspect_and_apply_patch_only_in_isolated_copy(tmp_path: Path) -> None:
    root, spec, commit = _project(tmp_path)
    target = inspect_target(root, spec, commit)
    assert target.mapper_method == "findUserById"
    assert target.caller_path == SERVICE_PATH
    assert target.caller_line == 6
    assert target.parent_key_column == "user_id"
    patched = apply_patch(target, _patch(), tmp_path / "workspaces")
    assert patched.patch_sha256
    assert "mapper.findUserById(ids)" in (patched.root / SERVICE_PATH).read_text(encoding="utf-8")
    assert (root / SERVICE_PATH).read_text(encoding="utf-8") == SERVICE
    assert not (patched.root / "secret.env").exists()


def test_inspection_rejects_ambiguous_or_stale_source(tmp_path: Path) -> None:
    root, spec, commit = _project(tmp_path)
    with pytest.raises(ValueError, match="commit"):
        inspect_target(root, spec, "wrong-commit")
    (root / SERVICE_PATH).write_text(SERVICE + "// changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dirty"):
        inspect_target(root, spec, commit)


def test_patch_rejects_out_of_scope_paths(tmp_path: Path) -> None:
    root, spec, commit = _project(tmp_path)
    target = inspect_target(root, spec, commit)
    bad = _patch().replace("src/main/java/demo/UserMapper.java", "tests/Answer.java")
    with pytest.raises(ValueError, match="scope"):
        apply_patch(target, bad, tmp_path / "workspaces")


def test_patch_rejects_hardcoded_or_unrelated_in_query(tmp_path: Path) -> None:
    root, spec, commit = _project(tmp_path)
    target = inspect_target(root, spec, commit)
    hardcoded = _patch(hardcoded=True)
    with pytest.raises(ValueError, match="parameterized batch IN"):
        apply_patch(target, hardcoded, tmp_path / "hardcoded")


def test_patch_accepts_mcp_diff_without_final_newline(tmp_path: Path) -> None:
    root, spec, commit = _project(tmp_path)
    target = inspect_target(root, spec, commit)
    submitted = _patch().rstrip("\n")
    patched = apply_patch(target, submitted, tmp_path / "no-final-lf")
    assert patched.changed_paths == tuple(sorted((MAPPER_PATH, SERVICE_PATH)))
    assert patched.patch_sha256 == hashlib.sha256(submitted.encode()).hexdigest()


def test_patched_select_reads_escaped_java_string_attributes() -> None:
    mapper = (
        '@Select("<script>" + "SELECT * FROM users WHERE id IN " + '
        '"<foreach collection=\\"ids\\" item=\\"id\\">#{id}</foreach>" + "</script>")\n'
        "List<User> findUserById(List<Long> ids);"
    )
    assert '<foreach collection="ids" item="id">#{id}</foreach>' in _patched_select_sql(
        mapper, "findUserById"
    )


def test_inspect_current_demo_mybatis_call_chain() -> None:
    root = Path(__file__).resolve().parents[2] / "demo/slow-query-demo"
    commit = _git(root, "rev-parse", "HEAD")
    spec = BatchQuerySpec(
        strategy="batch_in",
        child_template="SELECT * FROM users WHERE id = ?",
        key_column="id",
        child_code_location=CodeLocation(
            commit=commit,
            path="src/main/java/com/example/slowquery/mapper/OrderMapper.java",
            line=40,
            association_evidence_ids=["location-evidence"],
        ),
        observed_child_count=20,
        parent_sql_call_ids=["parent-call"],
    )
    target = inspect_target(root, spec, commit)
    assert target.mapper_method == "findUserById"
    assert target.caller_path.endswith("service/OrderService.java")
    assert target.caller_line == 29
