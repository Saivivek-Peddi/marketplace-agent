"""Tests for tool handlers and validation."""

import pytest

from agent.tools import execute, ToolResult
from agent.validation import validate_address, validate_id, ValidationError


class TestValidation:
    def test_valid_address(self):
        assert validate_address("123 Main St", "pickup") == "123 Main St"

    def test_address_strips_whitespace(self):
        assert validate_address("  123 Main St  ", "pickup") == "123 Main St"

    def test_empty_address_raises(self):
        with pytest.raises(ValidationError):
            validate_address("", "pickup")

    def test_short_address_raises(self):
        with pytest.raises(ValidationError):
            validate_address("x", "pickup")

    def test_long_address_raises(self):
        with pytest.raises(ValidationError):
            validate_address("x" * 201, "pickup")

    def test_valid_id(self):
        assert validate_id("est_abc12345", "estimate_id") == "est_abc12345"

    def test_empty_id_raises(self):
        with pytest.raises(ValidationError):
            validate_id("", "estimate_id")

    def test_long_id_raises(self):
        with pytest.raises(ValidationError):
            validate_id("x" * 65, "estimate_id")


class TestToolResult:
    def test_tool_result_creation(self):
        r = ToolResult(display="hello", data={"key": "value"})
        assert r.display == "hello"
        assert r.data["key"] == "value"

    def test_tool_result_defaults(self):
        r = ToolResult(display="hello")
        assert r.data == {}


class TestExecuteDispatch:
    def test_unknown_tool(self):
        result = execute("nonexistent_tool", {}, None, None)
        assert isinstance(result, ToolResult)
        assert "Unknown tool" in result.display
        assert result.data.get("error") == "unknown_tool"

    def test_validation_error_caught(self):
        # search_rides with empty pickup should fail validation
        from unittest.mock import MagicMock
        mock_adapter = MagicMock()
        mock_profile = MagicMock()
        mock_profile.resolve_address.return_value = ""

        result = execute("search_rides", {"pickup": "", "dropoff": "airport"}, mock_adapter, mock_profile)
        assert "Validation error" in result.display or "error" in result.data
