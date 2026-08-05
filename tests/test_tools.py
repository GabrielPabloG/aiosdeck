"""Tests for native agent tools — ask_user, etc."""

from unittest.mock import patch

from aios.tools import ask_user


def test_ask_user_tool_prints_prompt():
    with (
        patch("builtins.input", return_value="sim"),
        patch("builtins.print") as mock_print,
    ):
        result = ask_user("Deseja continuar?")

        mock_print.assert_called_once_with("Deseja continuar?")
        assert result == "sim"


def test_ask_user_tool_returns_user_input():
    with patch("builtins.input", return_value="nao"):
        result = ask_user("Confirma?")

        assert result == "nao"
