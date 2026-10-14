import pytest

from project_doctor.features.repair.patch_files import extract_patch_locations

DIFF = """diff --git a/src/main/java/com/example/OrderMapper.java b/src/main/java/com/example/OrderMapper.java
index 1111111..2222222 100644
--- a/src/main/java/com/example/OrderMapper.java
+++ b/src/main/java/com/example/OrderMapper.java
@@ -10,7 +10,9 @@ public interface OrderMapper {
     @Select("select * from orders")
     List<Order> findAll();
-    List<User> findById(Long id);
+    List<User> findByIds(@Param("ids") List<Long> ids);
+    // batch variant
     }
@@ -30,4 +32,3 @@ public interface OrderMapper {
     // second hunk
-    void legacy();
+    void legacyRemoved();
"""


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
