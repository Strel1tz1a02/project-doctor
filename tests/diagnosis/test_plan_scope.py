"""Plan-estimate scope checks read every nested table node and never trust bad input."""

from project_doctor.features.diagnosis.plan_scope import all_filtered


def test_flat_v1_table_node_is_read() -> None:
    plan = {"query_block": {"table": {"table_name": "orders", "filtered": "10.00"}}}
    assert all_filtered(plan) == [10.0]


def test_nested_v1_nodes_and_joins_are_all_read() -> None:
    plan = {
        "query_block": {
            "ordering_operation": {
                "using_filesort": True,
                "table": {"table_name": "orders", "filtered": "100.00"},
            },
            "nested_loop": [
                {"table": {"table_name": "orders", "filtered": 10}},
                {"table": {"table_name": "users", "filtered": "0.50"}},
            ],
        }
    }
    assert all_filtered(plan) == [100.0, 10.0, 0.5]


def test_v2_query_plan_tree_is_read() -> None:
    plan = {
        "query_plan": {
            "operation": "Filter",
            "inputs": [
                {
                    "table_name": "orders",
                    "access_type": "index",
                    "index_name": "pd_status_created",
                    "filtered": 100,
                }
            ],
        }
    }
    assert all_filtered(plan) == [100.0]


def test_malformed_and_out_of_range_estimates_are_ignored() -> None:
    plan = {
        "query_block": {
            "table": [
                {"table_name": "a", "filtered": None},
                {"table_name": "b", "filtered": "not-a-number"},
                {"table_name": "c", "filtered": -1},
                {"table_name": "d", "filtered": 150},
                {"table_name": "e", "filtered": float("nan")},
                {"table_name": "f", "filtered": float("inf")},
                {"table_name": "g", "filtered": {"nested": 1}},
                {"table_name": "h", "filtered": "12.5"},
                {"table_name": "i"},
            ]
        }
    }
    assert all_filtered(plan) == [12.5]


def test_non_mapping_or_empty_plan_yields_no_estimate() -> None:
    assert all_filtered({}) == []
    assert all_filtered({"query_block": None}) == []
    assert all_filtered({"query_block": {"table": "unexpected"}}) == []
