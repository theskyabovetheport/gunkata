from datetime import UTC, datetime

import pytest

from gunkata.common.paths import Paths
from gunkata.inventory.info import DeviceInfo, DeviceInfoStore


@pytest.fixture
def store(tmp_path) -> DeviceInfoStore:
    return DeviceInfoStore(Paths(root=tmp_path))


def test_load_with_no_file_yet_returns_an_empty_device_info(store):
    assert store.load("emulator-5554") == DeviceInfo()


def test_set_name_persists_and_load_reflects_it(store):
    store.set_name("emulator-5554", "my phone")
    assert store.load("emulator-5554").name == "my phone"


def test_set_name_replaces_a_previous_name(store):
    store.set_name("emulator-5554", "first")
    store.set_name("emulator-5554", "second")
    assert store.load("emulator-5554").name == "second"


def test_add_tag_is_idempotent(store):
    """Adding the same tag twice must not duplicate it."""
    store.add_tag("emulator-5554", "rooted")
    store.add_tag("emulator-5554", "rooted")
    assert store.load("emulator-5554").tags == ("rooted",)


def test_add_tag_keeps_tags_sorted(store):
    store.add_tag("emulator-5554", "zzz")
    store.add_tag("emulator-5554", "aaa")
    assert store.load("emulator-5554").tags == ("aaa", "zzz")


def test_remove_tag_drops_it(store):
    store.add_tag("emulator-5554", "rooted")
    store.remove_tag("emulator-5554", "rooted")
    assert store.load("emulator-5554").tags == ()


def test_remove_tag_on_an_absent_tag_is_a_no_op(store):
    store.add_tag("emulator-5554", "rooted")
    store.remove_tag("emulator-5554", "not-there")
    assert store.load("emulator-5554").tags == ("rooted",)


def test_name_and_tags_are_kept_per_serial(store):
    store.set_name("emulator-5554", "a")
    store.set_name("emulator-5556", "b")
    assert store.load("emulator-5554").name == "a"
    assert store.load("emulator-5556").name == "b"


def test_name_is_stored_as_the_files_plain_contents(store, tmp_path):
    """The name file holds exactly the name, nothing else -- no YAML, no framing."""
    store.set_name("emulator-5554", "my phone")
    path = Paths(root=tmp_path).device_name_path("emulator-5554")
    assert path.read_text() == "my phone\n"


def test_tags_are_stored_one_per_line(store, tmp_path):
    store.add_tag("emulator-5554", "zzz")
    store.add_tag("emulator-5554", "aaa")
    path = Paths(root=tmp_path).device_tags_path("emulator-5554")
    assert path.read_text() == "aaa\nzzz\n"


def test_add_note_appends_a_timestamped_entry(store, tmp_path):
    when = datetime(2026, 8, 12, 16, 30, 0, tzinfo=UTC)
    store.add_note("emulator-5554", "first note", when=when)
    path = Paths(root=tmp_path).device_note_path("emulator-5554")
    assert path.read_text() == "### 2026-08-12T16:30:00+00:00\nfirst note\n\n"


def test_add_note_appends_rather_than_overwrites(store, tmp_path):
    when = datetime(2026, 8, 12, 16, 30, 0, tzinfo=UTC)
    store.add_note("emulator-5554", "first", when=when)
    store.add_note("emulator-5554", "second", when=when)
    contents = Paths(root=tmp_path).device_note_path("emulator-5554").read_text()
    assert contents.count("###") == 2
    assert "first" in contents
    assert "second" in contents


def test_add_note_strips_surrounding_whitespace(store, tmp_path):
    when = datetime(2026, 8, 12, 16, 30, 0, tzinfo=UTC)
    store.add_note("emulator-5554", "  padded note  \n\n", when=when)
    path = Paths(root=tmp_path).device_note_path("emulator-5554")
    assert path.read_text() == "### 2026-08-12T16:30:00+00:00\npadded note\n\n"
