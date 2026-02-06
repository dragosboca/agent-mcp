"""Unit tests for agent_mcp.server (_reauth CLI)."""

from __future__ import annotations

from agent_mcp.server import _reauth


class TestReauth:
    def test_list_empty(self, tmp_path, capsys):
        _reauth([], tmp_path)
        assert "No cached OAuth tokens" in capsys.readouterr().out

    def test_list_existing_tokens(self, tmp_path, capsys):
        (tmp_path / "todoist.json").write_text("{}")
        (tmp_path / "github.json").write_text("{}")
        _reauth([], tmp_path)
        out = capsys.readouterr().out
        assert "todoist" in out
        assert "github" in out

    def test_clear_existing_token(self, tmp_path, capsys):
        token_file = tmp_path / "todoist.json"
        token_file.write_text("{}")
        _reauth(["todoist"], tmp_path)
        assert not token_file.exists()
        assert "Cleared" in capsys.readouterr().out

    def test_clear_nonexistent_token(self, tmp_path, capsys):
        _reauth(["nosuchserver"], tmp_path)
        assert "No cached tokens" in capsys.readouterr().out
