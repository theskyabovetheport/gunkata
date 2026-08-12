import pytest

from gunkata.device_config import (
    DEFAULT_LIST_CONFIG_YAML,
    Column,
    Getter,
    ListConfig,
    ListConfigError,
)


def test_parse_reads_getprop_and_shell_columns():
    body = """\
columns:
  - name: MODEL
    getprop: ro.product.model
  - name: UPTIME
    shell: uptime
"""
    config = ListConfig.parse(body)
    assert config.columns == (
        Column("MODEL", Getter("getprop", "ro.product.model")),
        Column("UPTIME", Getter("shell", "uptime")),
    )


def test_parse_rejects_malformed_yaml():
    with pytest.raises(ListConfigError, match="not valid YAML"):
        ListConfig.parse("columns: [")


def test_parse_rejects_missing_columns_key():
    with pytest.raises(ListConfigError, match="columns"):
        ListConfig.parse("foo: bar")


def test_parse_rejects_a_column_with_no_getter():
    with pytest.raises(ListConfigError, match="MODEL"):
        ListConfig.parse("columns:\n  - name: MODEL\n")


def test_parse_rejects_a_column_with_both_getters():
    body = "columns:\n  - name: MODEL\n    getprop: a\n    shell: b\n"
    with pytest.raises(ListConfigError, match="MODEL"):
        ListConfig.parse(body)


def test_parse_rejects_an_unknown_key():
    body = "columns:\n  - name: MODEL\n    builtin: name\n"
    with pytest.raises(ListConfigError, match="unknown keys"):
        ListConfig.parse(body)


def test_load_falls_back_to_the_built_in_default_when_the_file_is_absent(tmp_path):
    """No config file yet must not mean no columns -- see DEFAULT_LIST_CONFIG_YAML."""
    config = ListConfig.load(tmp_path / "list-config.yaml")
    assert config == ListConfig.parse(DEFAULT_LIST_CONFIG_YAML)
    assert config.columns


def test_load_reads_an_existing_file_instead_of_the_default(tmp_path):
    path = tmp_path / "list-config.yaml"
    path.write_text("columns:\n  - name: X\n    getprop: x\n")
    config = ListConfig.load(path)
    assert config.columns == (Column("X", Getter("getprop", "x")),)


def test_load_propagates_a_malformed_existing_file(tmp_path):
    path = tmp_path / "list-config.yaml"
    path.write_text("not: [valid")
    with pytest.raises(ListConfigError):
        ListConfig.load(path)
