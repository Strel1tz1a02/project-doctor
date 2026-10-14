import pytest

from project_doctor.features.repair.patch_files import extract_patch_locations

_MAPPER = "src/main/java/com/example/OrderMapper.java"

DIFF = (
    f"diff --git a/{_MAPPER} b/{_MAPPER}\n"
    """index 1111111..2222222 100644
--- a/src/main/java/com/example/OrderMapper.java
+++ b/src/main/java/com/example/OrderMapper.java
@@ -10,4 +10,5 @@ public interface OrderMapper {
     @Select("select * from orders")
     List<Order> findAll();
-    List<User> findById(Long id);
+    List<User> findByIds(@Param("ids") List<Long> ids);
+    // batch variant
     }
@@ -30,2 +32,2 @@ public interface OrderMapper {
     // second hunk
-    void legacy();
+    void legacyRemoved();
"""
)


def test_added_lines_use_new_side_numbers():
    assert extract_patch_locations(DIFF) == [
        {"path": "src/main/java/com/example/OrderMapper.java", "line": 12},
        {"path": "src/main/java/com/example/OrderMapper.java", "line": 13},
        {"path": "src/main/java/com/example/OrderMapper.java", "line": 33},
    ]


def test_multi_file_and_deletion_only_hunk():
    diff = (
        "diff --git a/a.java b/a.java\n"
        "--- a/a.java\n"
        "+++ b/a.java\n"
        "@@ -5,3 +5,2 @@\n"
        " ctx\n"
        "-old();\n"
        " ctx2\n"
        "diff --git a/b.java b/b.java\n"
        "--- a/b.java\n"
        "+++ b/b.java\n"
        "@@ -7,2 +7,3 @@\n"
        " ctx\n"
        "+newCall();\n"
        " ctx2\n"
    )
    assert extract_patch_locations(diff) == [
        {"path": "a.java", "line": 5},  # deletion-only hunk records the hunk start
        {"path": "b.java", "line": 8},
    ]


def test_empty_diff_rejected():
    with pytest.raises(ValueError, match="empty"):
        extract_patch_locations("   \n")


def test_binary_and_rename_rejected():
    with pytest.raises(ValueError, match="binary"):
        extract_patch_locations(
            "diff --git a/x.bin b/x.bin\nBinary files a/x.bin and b/x.bin differ\n"
        )
    with pytest.raises(ValueError, match="rename"):
        extract_patch_locations(
            "diff --git a/a.java b/b.java\nrename from a.java\nrename to b.java\n"
        )


def test_deleted_file_rejected():
    with pytest.raises(ValueError, match="deletion"):
        extract_patch_locations("diff --git a/a.java b/a.java\n+++ /dev/null\n")


def test_malformed_hunk_rejected():
    with pytest.raises(ValueError, match="hunk"):
        extract_patch_locations("+++ b/a.java\n@@ garbage @@\n+x\n")


def test_multi_file_diff_without_git_header_keeps_both_files():
    # difflib.unified_diff style: no "diff --git" separator between files.
    diff = (
        "--- a/a.java\n"
        "+++ b/a.java\n"
        "@@ -1,2 +1,2 @@\n"
        " ctx\n"
        "-old\n"
        "+new\n"
        "--- a/b.java\n"
        "+++ b/b.java\n"
        "@@ -5,1 +5,2 @@\n"
        " ctx\n"
        "+added\n"
    )
    assert extract_patch_locations(diff) == [
        {"path": "a.java", "line": 2},
        {"path": "b.java", "line": 6},
    ]


def test_removed_sql_comment_is_content_not_a_file_header():
    diff = "--- a/a.java\n+++ b/a.java\n@@ -1,2 +1,2 @@\n--- old comment\n+-- new comment\n ctx\n"
    assert extract_patch_locations(diff) == [{"path": "a.java", "line": 1}]


def test_hunk_without_any_change_is_rejected():
    diff = "--- a/a.java\n+++ b/a.java\n@@ -1,1 +1,1 @@\n ctx\n"
    with pytest.raises(ValueError, match="touches no source lines"):
        extract_patch_locations(diff)


def test_hunk_line_count_mismatch_is_rejected():
    diff = "--- a/a.java\n+++ b/a.java\n@@ -1,3 +1,3 @@\n ctx\n+added\n"
    with pytest.raises(ValueError, match="counts do not match"):
        extract_patch_locations(diff)


def test_gnu_timestamp_suffix_is_stripped_from_paths():
    diff = (
        "--- a/a.java\t2026-01-01 00:00:00\n"
        "+++ b/a.java\t2026-01-01 00:00:00\n"
        "@@ -1,1 +1,2 @@\n"
        " ctx\n"
        "+added\n"
    )
    assert extract_patch_locations(diff) == [{"path": "a.java", "line": 2}]
