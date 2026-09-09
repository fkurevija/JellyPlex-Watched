import importlib.util
from pathlib import Path


def load_validate_ci_marklog_module():
    path = Path(__file__).with_name("validate_ci_marklog.py")
    spec = importlib.util.spec_from_file_location("validate_ci_marklog", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_unique_mark_entries_removes_duplicates_preserving_order():
    module = load_validate_ci_marklog_module()
    assert module.unique_mark_entries(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]
