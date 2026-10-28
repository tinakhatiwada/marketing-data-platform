"""AdPulse dashboard: a local Streamlit stand-in for the Data Studio report.

Reads the reporting tables the pipeline builds in the local DuckDB warehouse:
  analytics.rpt_client_channel_daily      → Overview
  analytics.rpt_campaign_performance_daily → Campaigns
  analytics.rpt_budget_pacing             → Budget pacing
  ops.data_quality_results                → Pipeline health

Run it after the demo pipeline:
    pip install -e ".[dashboard]"
    adpulse run --mode demo --days 90
    streamlit run app.py

Metric rules follow docs/metric_definitions.md: ratios are SUM(numerator) / SUM(denominator)
over the selection, and GA4 ROAS uses paid-channel revenue only.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DUCKDB_PATH", ROOT / "warehouse" / "adpulse.duckdb"))

PAID_CHANNELS = ("paid_search", "paid_social")
CHANNEL_LABELS = {
    "paid_search": "Paid search", "paid_social": "Paid social",
    "organic_search": "Organic search", "direct": "Direct", "email": "Email",
    "referral": "Referral", "other": "Other",
}
PLATFORM_LABELS = {"google_ads": "Google Ads", "meta_ads": "Meta Ads"}
PLATFORM_COLORS = {"Google Ads": "#4C8BF5", "Meta Ads": "#F28C28"}
PACING_LABELS = {"overpacing": "Over-pacing", "underpacing": "Under-pacing",
                 "on_track": "On track"}

AUD = st.column_config.NumberColumn
COLUMNS = {
    "client": st.column_config.TextColumn("Client"),
    "platform": st.column_config.TextColumn("Platform", width=84),
    "channel": st.column_config.TextColumn("Channel"),
    "campaign": st.column_config.TextColumn("Campaign", width=264),
    "objective": st.column_config.TextColumn("Objective", width=120),
    "spend": AUD("Spend (AUD)", format="dollar", width=100),
    "cpa": AUD("CPA (AUD)", format="dollar", width=85),
    "cpa_text": st.column_config.TextColumn("CPA (AUD)"),
    "ctr_text": st.column_config.TextColumn("CTR"),
    "roas_text": st.column_config.TextColumn("GA4 ROAS"),
    "cpc": AUD("CPC (AUD)", format="dollar", width=80),
    "budget": AUD("Monthly budget (AUD)", format="dollar"),
    "mtd": AUD("Spend to date (AUD)", format="dollar"),
    "projected": AUD("Projected month-end (AUD)", format="dollar"),
    "impressions": AUD("Impressions", format="localized"),
    "clicks": AUD("Clicks", format="localized"),
    "sessions": AUD("GA4 sessions", format="localized"),
    "key_events": AUD("GA4 key events", format="localized"),
    "conversions": AUD("Conversions", format="%.1f", width=86,
                       help="Platform-reported conversions"),
    "ctr": AUD("CTR", format="percent", width=64),
    "engagement": AUD("Engagement rate", format="percent"),
    "pacing_ratio": AUD("Pacing ratio", format="percent"),
    "platform_roas": AUD("Platform ROAS", format="%.2fx", width=105),
    "ga4_roas": AUD("GA4 ROAS", format="%.2fx", width=85),
    "status": st.column_config.TextColumn("Status"),
    "through": st.column_config.DateColumn("Data through"),
    "checked_at": st.column_config.DatetimeColumn("Checked at (UTC)", format="YYYY-MM-DD HH:mm"),
    "check": st.column_config.TextColumn("Check"),
    "subject": st.column_config.TextColumn("Subject"),
    "message": st.column_config.TextColumn("Details", width="large"),
}

st.set_page_config(page_title="AdPulse | Marketing Intelligence", page_icon="📊",
                   layout="wide", initial_sidebar_state="expanded")
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
    [data-testid="stMetric"] {
        background: var(--secondary-background-color);
        padding: 16px; border-radius: 10px; border: 1px solid rgba(128,128,128,.18);
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------ helpers --
@st.cache_data(ttl=60)
def load(query: str) -> pd.DataFrame:
    """Read a reporting table from the local DuckDB warehouse (read-only)."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    with duckdb.connect(str(DB_PATH), read_only=True) as conn:
        # Same timestamps for every viewer, whatever their machine's time zone.
        conn.execute("SET TimeZone = 'UTC'")
        return conn.execute(query).fetchdf()


def money(value: float) -> str:
    return f"A${value:,.2f}"


def money_short(value: float) -> str:
    """Compact amount for narrow KPI cards: A$115.4k."""
    return f"A${value / 1000:,.1f}k" if abs(value) >= 10_000 else money(value)


def ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else float("nan")


def show_ratio(value: float, fmt: str) -> str:
    return "—" if pd.isna(value) else fmt.format(value)


def safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    return num / den.where(den != 0)


def chart(fig, height: int = 380) -> None:
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=10),
                      legend_title_text="")
    st.plotly_chart(fig, width="stretch")


def table(df: pd.DataFrame, columns: dict[str, str], all_rows: bool = True) -> None:
    """Show `df` with readable headers: columns maps dataframe column → COLUMNS key.
    all_rows: size the table to show every row (up to 25) without inner scrolling."""
    height = min(len(df), 25) * 35 + 38 if all_rows else "auto"
    st.dataframe(df[list(columns)], width="stretch", hide_index=True, height=height,
                 column_config={col: COLUMNS[key] for col, key in columns.items()})


# -------------------------------------------------------------------- data --
try:
    channels_all = load("SELECT * FROM analytics.rpt_client_channel_daily")
    campaigns_all = load("SELECT * FROM analytics.rpt_campaign_performance_daily")
    budgets_all = load("SELECT * FROM analytics.rpt_budget_pacing")
    quality_all = load("SELECT * FROM ops.data_quality_results ORDER BY checked_at DESC")
except Exception as exc:  # noqa: BLE001 — show any database problem to the user
    st.error(f"Could not read the local reporting database: {exc}")
    st.info("Run the demo pipeline first: `adpulse run --mode demo --days 90`")
    st.stop()

for df in (channels_all, campaigns_all):
    df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
channels_all["channel_label"] = channels_all["channel"].map(CHANNEL_LABELS).fillna(
    channels_all["channel"])
campaigns_all["platform_label"] = campaigns_all["platform"].map(PLATFORM_LABELS)

# ----------------------------------------------------------------- sidebar --
st.sidebar.title("AdPulse")
st.sidebar.caption("Marketing intelligence · local demo warehouse")
page = st.sidebar.radio("Page", ["Overview", "Campaigns", "Budget pacing", "Pipeline health"])

clients = sorted(channels_all["client_name"].dropna().unique())
selected_client = st.sidebar.selectbox("Client", ["All clients", *clients])

# One reporting period for every page that uses one.
first_day = min(channels_all["report_date"].min(), campaigns_all["report_date"].min())
last_day = max(channels_all["report_date"].max(), campaigns_all["report_date"].max())
period = st.sidebar.date_input(
    "Reporting period",
    value=(max(first_day, last_day - timedelta(days=27)), last_day),
    min_value=first_day, max_value=last_day,
    help="Applies to Overview and Campaigns. Defaults to the last 28 days of data.",
)
start, end = (period if isinstance(period, tuple) and len(period) == 2
              else (first_day, last_day))

st.sidebar.divider()
st.sidebar.caption("Data source: local DuckDB · synthetic demo data")
st.sidebar.caption("Production design: BigQuery → Data Studio (see README)")


def in_scope(df: pd.DataFrame) -> pd.DataFrame:
    out = df[(df["report_date"] >= start) & (df["report_date"] <= end)]
    if selected_client != "All clients":
        out = out[out["client_name"] == selected_client]
    return out


channels = in_scope(channels_all)
campaigns = in_scope(campaigns_all)

st.title("AdPulse")
st.caption(f"Cross-channel reporting · {selected_client} · {start:%d %b %Y} – {end:%d %b %Y}")

# ---------------------------------------------------------------- overview --
if page == "Overview":
    st.subheader("Performance overview")
    paid = channels[channels["channel"].isin(PAID_CHANNELS)]
    spend = paid["spend_aud"].sum()
    conversions = paid["platform_conversions"].sum()
    paid_revenue = paid["ga4_revenue_aud"].sum()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Media spend", money_short(spend), help=money(spend))
    c2.metric("Platform conversions", f"{conversions:,.0f}")
    c3.metric("Platform CPA", show_ratio(ratio(spend, conversions), "A${:,.2f}"))
    c4.metric("GA4 ROAS (paid)", show_ratio(ratio(paid_revenue, spend), "{:.2f}x"),
              help="GA4 revenue from paid search and paid social ÷ media spend.")
    c5.metric("GA4 sessions (all)", f"{channels['ga4_sessions'].sum():,.0f}")

    if channels.empty:
        st.warning("No data for this client and period.")
    else:
        daily = (paid.groupby("report_date", as_index=False)
                 .agg(spend=("spend_aud", "sum"), conversions=("platform_conversions", "sum")))
        left, right = st.columns(2)
        with left:
            st.markdown("#### Daily media spend (AUD)")
            chart(px.area(daily, x="report_date", y="spend",
                          labels={"report_date": "Date", "spend": "Spend (AUD)"}), 320)
        with right:
            st.markdown("#### Daily platform conversions")
            chart(px.line(daily, x="report_date", y="conversions", markers=True,
                          labels={"report_date": "Date", "conversions": "Conversions"}), 320)

        st.markdown("#### Channel performance")
        by_channel = (channels.groupby("channel_label", as_index=False)
                      .agg(spend=("spend_aud", "sum"), clicks=("clicks", "sum"),
                           impressions=("impressions", "sum"),
                           conversions=("platform_conversions", "sum"),
                           sessions=("ga4_sessions", "sum"),
                           engaged=("ga4_engaged_sessions", "sum"),
                           key_events=("ga4_key_events", "sum"),
                           revenue=("ga4_revenue_aud", "sum")))
        by_channel["ctr"] = safe_div(by_channel["clicks"], by_channel["impressions"])
        by_channel["cpa"] = safe_div(by_channel["spend"], by_channel["conversions"])
        by_channel["engagement"] = safe_div(by_channel["engaged"], by_channel["sessions"])
        by_channel["ga4_roas"] = safe_div(by_channel["revenue"], by_channel["spend"])
        for col, fmt in (("ctr", "{:.2%}"), ("cpa", "A${:,.2f}"), ("ga4_roas", "{:.2f}x")):
            by_channel[col] = by_channel[col].map(lambda v, f=fmt: show_ratio(v, f))
        table(by_channel.sort_values("sessions", ascending=False),
              {"channel_label": "channel", "spend": "spend", "clicks": "clicks",
               "ctr": "ctr_text", "cpa": "cpa_text", "sessions": "sessions",
               "key_events": "key_events", "engagement": "engagement",
               "ga4_roas": "roas_text"})
        st.caption("Unpaid channels have no spend, so CTR, CPA and ROAS are blank for them.")

        st.markdown("#### Weekly GA4 sessions by channel")
        weekly = channels.assign(
            week=pd.to_datetime(channels["report_date"]).dt.to_period("W").dt.start_time)
        weekly = weekly.groupby(["week", "channel_label"], as_index=False)["ga4_sessions"].sum()
        chart(px.bar(weekly, x="week", y="ga4_sessions", color="channel_label",
                     labels={"week": "Week starting", "ga4_sessions": "GA4 sessions"}))
        st.caption("The first and last weeks can be partial, depending on the period selected.")

# --------------------------------------------------------------- campaigns --
elif page == "Campaigns":
    st.subheader("Campaign performance")
    f1, f2 = st.columns(2)
    platform = f1.selectbox("Platform", ["All platforms", *PLATFORM_LABELS.values()])
    objectives = sorted(campaigns_all["objective"].dropna().unique())
    objective = f2.selectbox("Objective", ["All objectives", *objectives])

    view = campaigns
    if platform != "All platforms":
        view = view[view["platform_label"] == platform]
    if objective != "All objectives":
        view = view[view["objective"] == objective]

    if view.empty:
        st.warning("No campaigns match these filters.")
    else:
        spend = view["spend_aud"].sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Campaign spend", money(spend))
        c2.metric("Platform conversions", f"{view['platform_conversions'].sum():,.0f}")
        c3.metric("Platform ROAS",
                  show_ratio(ratio(view["platform_conversion_value_aud"].sum(), spend),
                             "{:.2f}x"))
        c4.metric("GA4 ROAS", show_ratio(ratio(view["ga4_revenue_aud"].sum(), spend), "{:.2f}x"))

        summary = (view.groupby(["client_name", "platform_label", "campaign_name", "objective",
                                 "follows_naming_convention"], as_index=False)
                   .agg(spend=("spend_aud", "sum"), impressions=("impressions", "sum"),
                        clicks=("clicks", "sum"), conversions=("platform_conversions", "sum"),
                        value=("platform_conversion_value_aud", "sum"),
                        key_events=("ga4_key_events", "sum"),
                        revenue=("ga4_revenue_aud", "sum")))
        summary["ctr"] = safe_div(summary["clicks"], summary["impressions"])
        summary["cpc"] = safe_div(summary["spend"], summary["clicks"])
        summary["cpa"] = safe_div(summary["spend"], summary["conversions"])
        summary["platform_roas"] = safe_div(summary["value"], summary["spend"])
        summary["ga4_roas"] = safe_div(summary["revenue"], summary["spend"])

        st.markdown("#### Campaigns")
        table(summary.sort_values("spend", ascending=False),
              {"campaign_name": "campaign", "platform_label": "platform",
               "spend": "spend", "ctr": "ctr", "cpc": "cpc",
               "conversions": "conversions", "cpa": "cpa",
               "platform_roas": "platform_roas", "ga4_roas": "ga4_roas"})
        st.caption("The client is the first part of each campaign name (TWO = Tidewater, "
                   "BGE = Brightgrid, KCR = Kereru). Platform ROAS uses each ad platform's "
                   "attribution, GA4 ROAS uses GA4's: they are shown side by side and are not "
                   "expected to match.")

        st.markdown("#### Spend versus CPA (conversion and lead campaigns)")
        scatter = summary[(summary["conversions"] > 0)
                          & summary["objective"].isin(["conversion", "lead_generation"])]
        if scatter.empty:
            st.info("No conversion or lead campaigns in this selection.")
        else:
            fig = px.scatter(scatter, x="spend", y="cpa", size="conversions",
                             color="platform_label", color_discrete_map=PLATFORM_COLORS,
                             hover_name="campaign_name",
                             hover_data={"client_name": True, "platform_label": False},
                             labels={"spend": "Spend (AUD)", "cpa": "CPA (AUD)",
                                     "platform_label": "Platform",
                                     "client_name": "Client"})
            fig.update_traces(marker=dict(line=dict(width=1, color="white"), opacity=0.85))
            chart(fig, 420)
            st.caption("Bubble size = platform conversions. Awareness and traffic campaigns are "
                       "excluded: they aren't optimised for conversions, so their CPA isn't "
                       "comparable.")

        st.markdown("#### Campaign naming-convention check")
        issues = summary[~summary["follows_naming_convention"]]
        if issues.empty:
            st.success("Every campaign follows the convention CLIENT_MARKET_OBJECTIVE_Descriptor.")
        else:
            st.warning(f"{len(issues)} campaign(s) break the convention "
                       "`CLIENT_MARKET_OBJECTIVE_Descriptor`. This is intentional in the demo "
                       "data, so the dbt warning and this panel have something to catch.")
            table(issues, {"client_name": "client", "platform_label": "platform",
                           "campaign_name": "campaign", "objective": "objective",
                           "spend": "spend"})

# ----------------------------------------------------------- budget pacing --
elif page == "Budget pacing":
    st.subheader("Monthly budget pacing")
    budgets = budgets_all.copy()
    if selected_client != "All clients":
        budgets = budgets[budgets["client_name"] == selected_client]

    if budgets.empty:
        st.warning("No budget data for this client.")
    else:
        budgets["month"] = pd.to_datetime(budgets["month_start"]).dt.strftime("%B %Y")
        months = (budgets.sort_values("month_start", ascending=False)["month"]
                  .drop_duplicates().tolist())
        month = st.selectbox("Month", months)
        budgets = budgets[budgets["month"] == month].copy()
        budgets["status"] = budgets["pacing_status"].map(PACING_LABELS)
        budgets["through"] = pd.to_datetime(budgets["data_through_date"]).dt.date

        c1, c2, c3 = st.columns(3)
        c1.metric("Monthly budget", money(budgets["monthly_budget_aud"].sum()))
        c2.metric("Spend to date", money(budgets["spend_mtd_aud"].sum()))
        c3.metric("Projected month-end spend", money(budgets["projected_spend_aud"].sum()))

        st.markdown("#### Budget, spend to date and projected month-end spend")
        long = budgets.melt(id_vars="client_name",
                            value_vars=["monthly_budget_aud", "spend_mtd_aud",
                                        "projected_spend_aud"],
                            var_name="measure", value_name="amount")
        long["measure"] = long["measure"].map({
            "monthly_budget_aud": "Monthly budget", "spend_mtd_aud": "Spend to date",
            "projected_spend_aud": "Projected month-end"})
        chart(px.bar(long, x="client_name", y="amount", color="measure", barmode="group",
                     color_discrete_sequence=["#9AA5B1", "#4C8BF5", "#F28C28"],
                     labels={"client_name": "Client", "amount": "Amount (AUD)"}))

        st.markdown("#### Pacing by client")
        table(budgets, {"client_name": "client", "monthly_budget_aud": "budget",
                        "spend_mtd_aud": "mtd", "projected_spend_aud": "projected",
                        "pacing_ratio": "pacing_ratio", "status": "status",
                        "through": "through"})
        st.caption("Projection = spend to date ÷ days elapsed × days in month. Over-pacing "
                   "means a projection more than 10 % above budget; under-pacing, more than "
                   "10 % below.")

# --------------------------------------------------------- pipeline health --
elif page == "Pipeline health":
    st.subheader("Data quality and pipeline health")
    quality = quality_all.copy()
    if quality.empty:
        st.info("No data-quality results yet. Run the pipeline first.")
    else:
        if selected_client != "All clients":
            code = channels_all.loc[channels_all["client_name"] == selected_client,
                                    "client_code"].iloc[0]
            all_codes = channels_all["client_code"].dropna().unique()
            subject = quality["subject"].fillna("")
            mentions_any = subject.str.contains("|".join(all_codes), regex=True)
            quality = quality[~mentions_any | subject.str.contains(code, regex=False)]

        latest = quality[quality["run_id"] == quality["run_id"].iloc[0]]
        statuses = latest["status"].str.lower()
        c1, c2, c3 = st.columns(3)
        c1.metric("Checks in latest run", len(latest))
        c2.metric("Failures", int((statuses == "fail").sum()))
        c3.metric("Warnings", int((statuses == "warn").sum()))
        if (statuses == "fail").any():
            st.error("At least one check failed in the latest run.")
        elif (statuses == "warn").any():
            st.warning("The latest run has warnings. Review the details below.")
        else:
            st.success("Every check passed in the latest run.")

        st.markdown("#### Latest run")
        latest = latest.assign(status=latest["status"].str.upper())
        table(latest.sort_values(["status", "check_name"]),
              {"check_name": "check", "subject": "subject", "status": "status",
               "message": "message", "checked_at": "checked_at"})

        st.markdown("#### Problems caught over time")
        problems = quality[quality["status"].str.lower().isin(["fail", "warn"])]
        if problems.empty:
            st.info("No failed or warned checks in the stored history. "
                    "Run `make demo-anomaly` to see the spend-anomaly check fail.")
        else:
            runs = (quality.groupby("run_id", as_index=False)["checked_at"].min()
                    .rename(columns={"checked_at": "run_started"}))
            history = (problems.merge(runs, on="run_id")
                       .assign(status=lambda d: d["status"].str.upper()))
            table(history.sort_values("run_started", ascending=False),
                  {"run_started": "checked_at", "check_name": "check", "subject": "subject",
                   "status": "status", "message": "message"})
        st.caption("History covers the pipeline runs stored in this local DuckDB database.")

st.divider()
st.caption("AdPulse portfolio demo · synthetic data for three fictional clients · amounts in "
           "AUD (NZD converted at the rate in dbt/seeds/fx_rates.csv)")
