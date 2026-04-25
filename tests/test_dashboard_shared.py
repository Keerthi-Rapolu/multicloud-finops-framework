from __future__ import annotations

import pandas as pd

import dashboard._shared as shared
from dashboard._shared import (
    apply_owner_assignments,
    load_scoped_df,
    overlay_recommendation_actions,
    save_recommendation_action,
)


class _FakeSidebar:
    def __init__(self, state: dict):
        self._state = state

    def title(self, _text: str) -> None:
        return None

    def markdown(self, _text: str) -> None:
        return None

    def caption(self, _text: str) -> None:
        return None

    def selectbox(self, _label, options, index=0, key=None):
        if key and self._state.get(key) in options:
            return self._state[key]

        value = options[index]
        if key:
            self._state[key] = value
        return value


class _FakeStreamlit:
    def __init__(self, state: dict | None = None):
        self.session_state = {} if state is None else dict(state)
        self.sidebar = _FakeSidebar(self.session_state)

    def error(self, _text: str) -> None:
        raise AssertionError("Unexpected st.error call")

    def stop(self) -> None:
        raise AssertionError("Unexpected st.stop call")


def test_apply_owner_assignments_only_fills_unattributed_rows():
    df = pd.DataFrame(
        [
            {
                "cloud_provider": "aws",
                "account_id": "a-1",
                "allocated_team": "unattributed",
            },
            {
                "cloud_provider": "aws",
                "account_id": "a-2",
                "allocated_team": "backend",
            },
        ]
    )

    out = apply_owner_assignments(df, {"aws::a-1": "platform"})

    assert list(out["effective_team"]) == ["platform", "backend"]
    assert list(out["is_manually_assigned"]) == [True, False]


def test_apply_owner_assignments_supports_legacy_account_only_mapping():
    df = pd.DataFrame(
        [
            {
                "cloud_provider": "azure",
                "account_id": "acct-9",
                "allocated_team": "unattributed",
            }
        ]
    )

    out = apply_owner_assignments(df, {}, fallback_by_account={"acct-9": "ml"})

    assert out.iloc[0]["effective_team"] == "ml"
    assert bool(out.iloc[0]["is_manually_assigned"]) is True


def test_load_scoped_df_defaults_to_latest_month_on_direct_page_open(monkeypatch):
    fake_st = _FakeStreamlit()
    loaded_months: list[str | None] = []
    source_df = pd.DataFrame(
        [
            {"cloud_provider": "aws", "nec": 10},
            {"cloud_provider": "gcp", "nec": 15},
        ]
    )

    monkeypatch.setattr(shared, "st", fake_st)
    monkeypatch.setattr(shared, "available_months", lambda: ["2026-04", "2026-03"])
    monkeypatch.setattr(
        shared,
        "load_df",
        lambda month: loaded_months.append(month) or source_df.copy(),
    )

    out, month_filter, selected_cloud = load_scoped_df(render_sidebar=True)

    assert loaded_months == ["2026-04"]
    assert month_filter == "2026-04"
    assert selected_cloud == "All"
    assert list(out["cloud_provider"]) == ["aws", "gcp"]
    assert fake_st.session_state["billing_month"] == "2026-04"
    assert fake_st.session_state["month"] == "2026-04"


def test_load_scoped_df_respects_saved_legacy_scope(monkeypatch):
    fake_st = _FakeStreamlit({"month": "2026-03", "cloud": "aws"})
    source_df = pd.DataFrame(
        [
            {"cloud_provider": "aws", "nec": 10},
            {"cloud_provider": "azure", "nec": 15},
        ]
    )

    monkeypatch.setattr(shared, "st", fake_st)
    monkeypatch.setattr(shared, "available_months", lambda: ["2026-04", "2026-03"])
    monkeypatch.setattr(shared, "load_df", lambda month: source_df.copy())

    out, month_filter, selected_cloud = load_scoped_df(render_sidebar=False)

    assert month_filter == "2026-03"
    assert selected_cloud == "aws"
    assert list(out["cloud_provider"]) == ["aws"]
    assert fake_st.session_state["billing_month"] == "2026-03"


def test_overlay_recommendation_actions_applies_saved_status(tmp_path, monkeypatch):
    action_path = tmp_path / "recommendation_actions.json"
    monkeypatch.setattr(shared, "_RECOMMENDATION_ACTIONS_PATH", action_path)

    save_recommendation_action(
        "rec-1",
        {
            "action_status": "implemented",
            "action_owner": "finops@company.com",
            "created_date": "2026-04-24",
            "implementation_date": "2026-04-24",
            "realized_savings": 42.0,
        },
    )

    out = overlay_recommendation_actions(
        [
            {
                "recommendation_id": "rec-1",
                "allocated_team": "platform",
                "owner_email": "platform-owner@company.com",
            }
        ]
    )

    assert out[0]["action_status"] == "implemented"
    assert out[0]["action_owner"] == "finops@company.com"
    assert out[0]["realized_savings"] == 42.0
