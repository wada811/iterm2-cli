from __future__ import annotations

from iterm2_cli.labels import LabelStore, normalize_label

UUID = "3970511E-DDB7-4CE6-9364-3E200AF48272"


def test_normalize_label():
    assert normalize_label("feature/foo bar") == "feature-foo-bar"
    assert normalize_label("  worker  ") == "worker"


def test_set_get_roundtrip(tmp_path):
    store = LabelStore(tmp_path / "labels.json")
    store.set("worker", UUID)
    assert store.get("worker") == UUID


def test_get_missing_is_none(tmp_path):
    store = LabelStore(tmp_path / "labels.json")
    assert store.get("absent") is None


def test_set_normalizes_key(tmp_path):
    store = LabelStore(tmp_path / "labels.json")
    store.set("feature/foo", UUID)
    assert store.get("feature-foo") == UUID
    assert "feature-foo" in store.all()


def test_remove(tmp_path):
    store = LabelStore(tmp_path / "labels.json")
    store.set("worker", UUID)
    assert store.remove("worker") is True
    assert store.get("worker") is None
    assert store.remove("worker") is False


def test_persists_across_instances(tmp_path):
    p = tmp_path / "labels.json"
    LabelStore(p).set("a", UUID)
    assert LabelStore(p).get("a") == UUID


def test_corrupt_file_treated_as_empty(tmp_path):
    p = tmp_path / "labels.json"
    p.write_text("not json", encoding="utf-8")
    assert LabelStore(p).all() == {}
