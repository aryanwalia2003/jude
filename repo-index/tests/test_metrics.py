"""Tests for code metrics and architecture health analysis."""

import pytest

from repo_index import db, indexer, metrics

# Test Python code
_CODE_A = """
class ServiceA:
    def setup(self):
        self.fetch()

    def process(self):
        process_data()

    def cleanup(self):
        pass

def unused_helper():
    pass

def long_function():
    '''
    This is a very long function that goes on and on
    '''
    x = 1
    y = 2
    z = 3
    a = 4
    b = 5
    c = 6
    d = 7
    e = 8
    f = 9
    g = 10
    h = 11
    i = 12
    j = 13
    k = 14
    l = 15
    m = 16
    n = 17
    o = 18
    p = 19
    q = 20
    return x + y
"""

_CODE_B = """
class ServiceB:
    def fetch(self):
        cleanup()
        return None

    def notify(self):
        pass

def process_data():
    pass
"""


@pytest.fixture
def metricsdb(tmp_path):
    """Indexed test DB with sample Python code."""
    conn = db.open_db(tmp_path / "test.db")

    # Create repo structure
    root = tmp_path / "repo"
    root.mkdir()
    (root / "module_a.py").write_text(_CODE_A)
    (root / "module_b.py").write_text(_CODE_B)

    # Index
    indexer.build_index(conn, root, branch="main")

    return conn


class TestSymbolMetrics:
    def test_symbol_metrics_returns_list(self, metricsdb):
        all_metrics = metrics.symbol_metrics(metricsdb)
        assert isinstance(all_metrics, list)
        assert len(all_metrics) > 0

    def test_symbol_metrics_has_required_fields(self, metricsdb):
        all_metrics = metrics.symbol_metrics(metricsdb)
        m = all_metrics[0]
        assert hasattr(m, "name")
        assert hasattr(m, "kind")
        assert hasattr(m, "line_count")
        assert hasattr(m, "fan_in")
        assert hasattr(m, "fan_out")
        assert hasattr(m, "method_count")

    def test_symbol_metrics_computes_line_counts(self, metricsdb):
        all_metrics = metrics.symbol_metrics(metricsdb)
        long = next((m for m in all_metrics if m.name == "long_function"), None)
        assert long is not None
        assert long.line_count > 10  # long_function should be > 10 lines

    def test_symbol_metrics_counts_methods(self, metricsdb):
        all_metrics = metrics.symbol_metrics(metricsdb)
        svc_a = next((m for m in all_metrics if m.name == "ServiceA"), None)
        assert svc_a is not None
        assert svc_a.method_count == 3  # setup, process, cleanup

    def test_symbol_metrics_excludes_module_sentinels(self, metricsdb):
        all_metrics = metrics.symbol_metrics(metricsdb)
        assert all(m.kind != "module" for m in all_metrics)


class TestHotspots:
    def test_hotspots_returns_list(self, metricsdb):
        top = metrics.hotspots(metricsdb, top_n=5)
        assert isinstance(top, list)

    def test_hotspots_respects_limit(self, metricsdb):
        top = metrics.hotspots(metricsdb, top_n=2)
        assert len(top) <= 2

    def test_hotspots_sorted_by_fan_in(self, metricsdb):
        top = metrics.hotspots(metricsdb, top_n=10)
        if len(top) > 1:
            # If there are multiple hotspots, they should be sorted by fan_in descending
            assert top[0].fan_in >= top[1].fan_in


class TestDeadCode:
    def test_dead_code_finds_unused_helper(self, metricsdb):
        dead = metrics.dead_code(metricsdb)
        unused = next((m for m in dead if m.name == "unused_helper"), None)
        assert unused is not None
        assert unused.fan_in == 0

    def test_dead_code_excludes_certain_patterns(self, metricsdb):
        dead = metrics.dead_code(metricsdb)
        # Should exclude methods/functions with common safe patterns
        assert all(m.name != "__init__" for m in dead)
        assert all(m.name != "main" for m in dead)

    def test_dead_code_excludes_handlers(self, metricsdb):
        dead = metrics.dead_code(metricsdb)
        # Should exclude handler suffixes
        assert all(not m.name.endswith("Handler") for m in dead)


class TestGodObjects:
    def test_god_objects_identifies_large_classes(self, metricsdb):
        gods = metrics.god_objects(metricsdb, threshold=2)
        svc_a = next((m for m in gods if m.name == "ServiceA"), None)
        assert svc_a is not None
        assert svc_a.method_count >= 2

    def test_god_objects_respects_threshold(self, metricsdb):
        gods = metrics.god_objects(metricsdb, threshold=5)
        # ServiceA has 3 methods, ServiceB has 2; both should be excluded at threshold 5
        assert len(gods) == 0

    def test_god_objects_returns_classes_only(self, metricsdb):
        gods = metrics.god_objects(metricsdb, threshold=1)
        assert all(m.kind == "class" for m in gods)


class TestLongFunctions:
    def test_long_functions_identifies_long_code(self, metricsdb):
        long = metrics.long_functions(metricsdb, threshold=20)
        long_func = next((m for m in long if m.name == "long_function"), None)
        assert long_func is not None
        assert long_func.line_count >= 20

    def test_long_functions_respects_threshold(self, metricsdb):
        long = metrics.long_functions(metricsdb, threshold=200)
        # long_function is ~25 lines, so should not appear at 200 threshold
        assert not any(m.name == "long_function" for m in long)

    def test_long_functions_returns_functions_only(self, metricsdb):
        long = metrics.long_functions(metricsdb, threshold=1)
        assert all(m.kind in ("function", "method") for m in long)


class TestModuleCoupling:
    def test_module_coupling_returns_list(self, metricsdb):
        coupling = metrics.module_coupling(metricsdb)
        assert isinstance(coupling, list)

    def test_module_coupling_returns_cross_module_only(self, metricsdb):
        coupling = metrics.module_coupling(metricsdb)
        # All entries should have different from and to modules
        assert all(c.from_module != c.to_module for c in coupling)

    def test_module_coupling_has_call_counts(self, metricsdb):
        coupling = metrics.module_coupling(metricsdb)
        assert all(c.call_count > 0 for c in coupling)


class TestCircularDependencies:
    def test_circular_dependencies_returns_list(self, metricsdb):
        cycles = metrics.circular_dependencies(metricsdb)
        assert isinstance(cycles, list)

    def test_circular_dependencies_cycles_are_lists(self, metricsdb):
        cycles = metrics.circular_dependencies(metricsdb)
        assert all(isinstance(cycle, list) for cycle in cycles)


class TestHealthSummary:
    def test_health_summary_returns_dict(self, metricsdb):
        summary = metrics.health_summary(metricsdb)
        assert isinstance(summary, dict)
        assert "total_symbols" in summary
        assert "dead_code_count" in summary
        assert "god_objects_count" in summary
        assert "circular_deps_count" in summary
        assert "hotspots_top_5" in summary
        assert "longest_functions_top_5" in summary

    def test_health_summary_values_are_reasonable(self, metricsdb):
        summary = metrics.health_summary(metricsdb)
        assert summary["total_symbols"] > 0
        assert summary["dead_code_count"] >= 0
        assert summary["god_objects_count"] >= 0
        assert summary["circular_deps_count"] >= 0
