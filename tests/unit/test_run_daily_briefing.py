"""Unit tests for run_daily_briefing helpers."""

from __future__ import annotations

import json

import run_daily_briefing


class TestLlmModelKwargs:
    def test_returns_model_and_fallback_when_present(self, sample_config):
        out = run_daily_briefing.llm_model_kwargs(sample_config)
        assert out == {
            "model": "gpt-5-nano",
            "fallback_model": "gpt-5.4-nano",
        }

    def test_omits_unset_values(self):
        assert run_daily_briefing.llm_model_kwargs({"llm": {}}) == {}
        assert run_daily_briefing.llm_model_kwargs({"llm": {"model": "gpt-5-mini"}}) == {
            "model": "gpt-5-mini"
        }


class TestWriteProgress:
    def test_writes_progress_json(self, tmp_path):
        run_daily_briefing.write_progress(tmp_path, "discovery", candidate_count=3)

        progress = json.loads((tmp_path / "progress.json").read_text())
        assert progress["phase"] == "discovery"
        assert progress["candidate_count"] == 3
        assert progress["updated_at"]


class TestCheckIdempotency:
    def test_returns_true_when_briefing_exists_and_not_forced(self, tmp_path, capsys):
        (tmp_path / "briefing.md").write_text("done")

        assert run_daily_briefing.check_idempotency(tmp_path, force=False) is True
        assert "Briefing already exists" in capsys.readouterr().out

    def test_returns_false_when_force_is_true(self, tmp_path):
        (tmp_path / "briefing.md").write_text("done")
        assert run_daily_briefing.check_idempotency(tmp_path, force=True) is False


class TestAlertFailure:
    def test_swallows_send_failure_alert_exceptions(self, monkeypatch, capsys):
        def boom(cfg, subject, body):
            raise RuntimeError("smtp down")

        monkeypatch.setattr("send_briefing_email.send_failure_alert", boom)

        run_daily_briefing.alert_failure({}, "subject", "body")

        assert "Failed to send failure alert: smtp down" in capsys.readouterr().err