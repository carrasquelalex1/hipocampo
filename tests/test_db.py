"""Tests for hipocampo/db.py — config validation and helpers."""

from hipocampo.db import validate_config


class TestValidateConfig:
    def test_valid_config_returns_empty(self):
        config = {
            "DB_HOST": "localhost",
            "DB_USER": "alex",
            "DB_PASSWORD": "secret",
            "DB_NAME": "hipocampo_db",
            "NVIDIA_API_KEY": "nv-key-123",
        }
        assert validate_config(config) == []

    def test_missing_db_host(self):
        config = {
            "DB_HOST": "",
            "DB_USER": "alex",
            "DB_PASSWORD": "secret",
            "DB_NAME": "hipocampo_db",
            "NVIDIA_API_KEY": "nv-key-123",
        }
        errors = validate_config(config)
        assert len(errors) == 1
        assert "DB_HOST" in errors[0]

    def test_missing_all_db_config(self):
        config = {
            "DB_HOST": "",
            "DB_USER": "",
            "DB_PASSWORD": "",
            "DB_NAME": "",
            "NVIDIA_API_KEY": "nv-key-123",
        }
        errors = validate_config(config)
        assert len(errors) == 1
        assert "DB_HOST, DB_USER, DB_NAME" in errors[0]

    def test_missing_nvidia_key(self):
        config = {
            "DB_HOST": "localhost",
            "DB_USER": "alex",
            "DB_PASSWORD": "secret",
            "DB_NAME": "hipocampo_db",
            "NVIDIA_API_KEY": "",
        }
        errors = validate_config(config)
        assert len(errors) == 1
        assert "NVIDIA_API_KEY" in errors[0]

    def test_missing_both(self):
        config = {
            "DB_HOST": "",
            "DB_USER": "",
            "DB_PASSWORD": "",
            "DB_NAME": "",
            "NVIDIA_API_KEY": "",
        }
        errors = validate_config(config)
        assert len(errors) == 2
        assert any("PostgreSQL" in e for e in errors)
        assert any("NVIDIA_API_KEY" in e for e in errors)

    def test_default_from_env_not_required(self):
        # When config is None, validate_config calls load_config which
        # may have defaults. The function should not crash.
        result = validate_config()
        assert isinstance(result, list)
