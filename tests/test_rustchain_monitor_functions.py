"""
Unit tests for rustchain_monitor.py core utility functions.
Covers: normalize_node_target, default_multi_node_targets, load_node_targets,
history_db_exists, init_history_db, _slugify_node_text, _coerce_float,
_coerce_int, _health_db_rw, render_daily_gain_chart.

Bounty: https://github.com/Scottcjn/rustchain-bounties/issues/1589
"""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

import rustchain_monitor as rcm


class TestSlugifyNodeText:
    def test_basic(self):
        assert rcm._slugify_node_text("Node 1") == "node-1"

    def test_spaces_become_hyphens(self):
        assert rcm._slugify_node_text("My Node Server") == "my-node-server"

    def test_special_chars_stripped(self):
        assert rcm._slugify_node_text("Server@#$%") == "server"

    def test_fallback_on_empty(self):
        assert rcm._slugify_node_text("", fallback="custom") == "custom"
        assert rcm._slugify_node_text(None, fallback="custom") == "custom"

    def test_fallback_default(self):
        assert rcm._slugify_node_text("") == "node"


class TestNormalizeNodeTarget:
    def test_minimal_target(self):
        result = rcm.normalize_node_target({"url": "https://node.example"}, index=0)
        assert result["url"] == "https://node.example"
        assert result["name"] == "Node 1"
        assert result["role"] == ""
        assert result["node_id"] == "node-1"

    def test_full_target(self):
        result = rcm.normalize_node_target(
            {"url": "http://x:8080", "name": "Primary", "role": "Validator", "node_id": "primary-1"},
            index=5,
        )
        assert result["url"] == "http://x:8080"
        assert result["name"] == "Primary"
        assert result["role"] == "Validator"
        assert result["node_id"] == "primary-1"

    def test_url_trailing_slash_stripped(self):
        result = rcm.normalize_node_target({"url": "https://node.example///"})
        assert result["url"] == "https://node.example"

    def test_url_whitespace_stripped(self):
        result = rcm.normalize_node_target({"url": "  https://node.example  "})
        assert result["url"] == "https://node.example"

    def test_missing_url_raises(self):
        with pytest.raises(ValueError, match="url is required"):
            rcm.normalize_node_target({})

    def test_node_name_alias(self):
        result = rcm.normalize_node_target({"url": "https://x", "node_name": "Alias Name"})
        assert result["name"] == "Alias Name"

    def test_node_role_alias(self):
        result = rcm.normalize_node_target({"url": "https://x", "node_role": "Backup"})
        assert result["role"] == "Backup"


class TestDefaultMultiNodeTargets:
    def test_returns_list(self):
        result = rcm.default_multi_node_targets()
        assert isinstance(result, list)
        assert len(result) == 3

    def test_all_have_required_keys(self):
        for target in rcm.default_multi_node_targets():
            assert "node_id" in target
            assert "name" in target
            assert "role" in target
            assert "url" in target
            assert target["url"]  # non-empty


class TestLoadNodeTargets:
    def test_list_format(self, tmp_path):
        config = tmp_path / "nodes.json"
        config.write_text(json.dumps([
            {"url": "https://a.example", "name": "A"},
            {"url": "https://b.example", "name": "B"},
        ]))
        targets = rcm.load_node_targets(config)
        assert len(targets) == 2
        assert targets[0]["name"] == "A"
        assert targets[1]["name"] == "B"

    def test_dict_with_nodes_key(self, tmp_path):
        config = tmp_path / "nodes.json"
        config.write_text(json.dumps({"nodes": [{"url": "https://x.example", "name": "X"}]}))
        targets = rcm.load_node_targets(config)
        assert len(targets) == 1
        assert targets[0]["name"] == "X"

    def test_empty_list_raises(self, tmp_path):
        config = tmp_path / "nodes.json"
        config.write_text("[]")
        with pytest.raises(ValueError, match="at least one"):
            rcm.load_node_targets(config)

    def test_wrong_type_raises(self, tmp_path):
        config = tmp_path / "nodes.json"
        config.write_text('{"foo": "bar"}')
        with pytest.raises(ValueError, match="must be a list"):
            rcm.load_node_targets(config)


class TestHistoryDbExists:
    def test_returns_false_for_nonexistent(self, tmp_path):
        db_path = tmp_path / "nonexistent.db"
        assert rcm.history_db_exists(db_path) is False

    def test_returns_true_after_init(self, tmp_path):
        db_path = tmp_path / "test.db"
        rcm.init_history_db(db_path)
        assert rcm.history_db_exists(db_path) is True


class TestInitHistoryDb:
    def test_creates_file_and_table(self, tmp_path):
        db_path = tmp_path / "history.db"
        result = rcm.init_history_db(db_path)
        assert result.exists()
        conn = sqlite3.connect(result)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='miner_history'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_idempotent(self, tmp_path):
        db_path = tmp_path / "history.db"
        rcm.init_history_db(db_path)
        rcm.init_history_db(db_path)  # should not raise
        assert db_path.exists()

    def test_creates_parent_directory(self, tmp_path):
        db_path = tmp_path / "subdir" / "nested" / "history.db"
        result = rcm.init_history_db(db_path)
        assert result.parent.exists()


class TestCoerce:
    def test_coerce_float_valid(self):
        assert rcm._coerce_float(1.5) == 1.5
        assert rcm._coerce_float("2.5") == 2.5
        assert rcm._coerce_float(3) == 3.0

    def test_coerce_float_none_or_empty(self):
        assert rcm._coerce_float(None) == 0.0
        assert rcm._coerce_float("") == 0.0
        assert rcm._coerce_float(None, default=99.0) == 99.0

    def test_coerce_float_invalid(self):
        assert rcm._coerce_float("not a number") == 0.0
        assert rcm._coerce_float([1, 2]) == 0.0

    def test_coerce_int_valid(self):
        assert rcm._coerce_int(5) == 5
        assert rcm._coerce_int("10") == 10
        assert rcm._coerce_int(3.9) == 3

    def test_coerce_int_none_or_empty(self):
        assert rcm._coerce_int(None) == 0
        assert rcm._coerce_int("") == 0

    def test_coerce_int_invalid(self):
        assert rcm._coerce_int("bad") == 0


class TestHealthDbRw:
    def test_explicit_true(self):
        health = {"db_rw": True}
        assert rcm._health_db_rw(health) is True

    def test_explicit_false(self):
        health = {"db_rw": False}
        assert rcm._health_db_rw(health) is False

    def test_db_string_rw(self):
        assert rcm._health_db_rw({"db": "rw"}) is True
        assert rcm._health_db_rw({"db": "ro"}) is False
        assert rcm._health_db_rw({"db": "rw-only"}) is True

    def test_missing_db(self):
        assert rcm._health_db_rw({}) is False


class TestRenderDailyGainChart:
    def test_empty_rows(self):
        result = rcm.render_daily_gain_chart([])
        assert "No daily history" in result

    def test_single_bar(self):
        rows = [{"day": "2026-04-01", "gain": 1.5}]
        result = rcm.render_daily_gain_chart(rows)
        assert "2026-04-01" in result
        assert "+1.500000" in result

    def test_positive_and_negative(self):
        rows = [
            {"day": "2026-04-01", "gain": 2.0},
            {"day": "2026-04-02", "gain": -0.5},
        ]
        result = rcm.render_daily_gain_chart(rows)
        assert "+2.000000" in result
        assert "-0.500000" in result

    def test_width_parameter(self):
        rows = [{"day": "2026-04-01", "gain": 1.0}]
        result_narrow = rcm.render_daily_gain_chart(rows, width=5)
        result_wide = rcm.render_daily_gain_chart(rows, width=40)
        # Both should contain the gain value
        assert "+1.000000" in result_narrow
        assert "+1.000000" in result_wide
