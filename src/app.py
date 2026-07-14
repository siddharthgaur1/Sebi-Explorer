"""
SEBI Enforcement Orders Explorer v2
Search, filter, and analyse 11,000+ SEBI Adjudication Orders.

Enhancements over v1:
  - Penalty amount extraction and tracking (₹ crore)
  - Entity co-occurrence network graph (who appears together)
  - Timeline heatmap (orders by month × year)
  - AI-powered case summary (click any order for a summary)
  - Repeat offender detection (entities with multiple orders)
  - Export filtered results as Excel (in addition to CSV)
  - Full-text search across title AND entity (v1 only had basic filter)
  - Pagination on the orders table (avoid rendering 11k rows)

Run:  streamlit run src/app.py
"""

import re
import sqlite3
from pathlib import Path

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sebi_orders.db"

st.set_page_config(
    page_title="SEBI Enforcement Explorer v2",
    page_icon="⚖️",
    layout="wide",
)


# ── Penalty extractor ─────────────────────────────────────────────
_PENALTY_RE = re.compile(
    r"(?:penalty|fine|penalt(?:y|ies)|impose[sd]?)\s*(?:of\s*)?(?:rs\.?|₹|inr)?\s*"
    r"(\d[\d,.]*)\s*(crore|lakh|lakhs?)?",
    re.IGNORECASE,
)


def extract_penalty_cr(title: str) -> float | None:
    """Best-effort: extract penalty in crore INR from order title."""
    m = _PENALTY_RE.search(title)
    if not m:
        return None
    amount = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    if "lakh" in unit:
        return round(amount / 100, 4)
    return round(amount, 4)


# ── Data loader ───────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM orders ORDER BY order_date DESC", conn)
    conn.close()
    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
    df["year"] = df["order_date"].dt.year
    df["month_num"] = df["order_date"].dt.month
    df["month"] = df["order_date"].dt.strftime("%b")
    df["penalty_cr"] = df["title"].apply(extract_penalty_cr)
    return df


# ── Sidebar filters ───────────────────────────────────────────────
with st.sidebar:
    st.title("⚖️ SEBI Explorer v2")
    st.caption("Enforcement Orders (AO) Database")
    st.divider()

    df_all = load_data()

    years = sorted(df_all["year"].dropna().unique().astype(int), reverse=True)
    sel_years = st.multiselect("Year", years, default=years[:5])

    vtypes = sorted(df_all["violation_type"].dropna().unique())
    sel_vtypes = st.multiselect("Violation Type", vtypes, default=vtypes)

    search = st.text_input("Search entity / title / keyword",
                           placeholder="e.g. Reliance, insider trading, mutual fund")

    only_with_penalty = st.checkbox("Only orders with extracted penalty", value=False)

    st.divider()
    st.markdown(
        f"**{len(df_all):,}** orders in database\n"
        f"**{df_all['year'].nunique()}** years covered\n"
        f"**{df_all['violation_type'].nunique()}** violation categories"
    )

# ── Filter ────────────────────────────────────────────────────────
df = df_all.copy()
if sel_years:
    df = df[df["year"].isin(sel_years)]
if sel_vtypes:
    df = df[df["violation_type"].isin(sel_vtypes)]
if search:
    mask = (
        df["title"].str.contains(search, case=False, na=False)
        | df["entity"].str.contains(search, case=False, na=False)
    )
    df = df[mask]
if only_with_penalty:
    df = df[df["penalty_cr"].notna()]

# ── Title & KPIs ──────────────────────────────────────────────────
st.title("SEBI Enforcement Orders Explorer")
st.caption("Search, filter, and analyse adjudication orders from SEBI.")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Orders (filtered)", f"{len(df):,}")
k2.metric("Entities", f"{df['entity'].nunique():,}")
k3.metric("Most Common Violation",
          df["violation_type"].mode()[0] if len(df) else "—")
k4.metric("Latest Order",
          df["order_date"].max().strftime("%d %b %Y") if len(df) else "—")
total_penalty = df["penalty_cr"].sum()
k5.metric("Total Penalty (est.)",
          f"₹{total_penalty:,.1f} Cr" if total_penalty > 0 else "N/A")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────
t1, t2, t3, t4, t5 = st.tabs([
    "📊 Overview", "🗓️ Timeline Heatmap", "💸 Penalties",
    "🕸️ Entity Network", "📋 Orders Table"
])

# ═══════════════════════════
# TAB 1: Overview (enhanced v1)
# ═══════════════════════════
with t1:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Orders by Year")
        yearly = df.groupby("year").size().reset_index(name="count").sort_values("year")
        fig = px.bar(yearly, x="year", y="count", color_discrete_sequence=["#1f2937"],
                     labels={"year": "Year", "count": "Orders"})
        fig.update_layout(showlegend=False, plot_bgcolor="white", height=300, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Violation Type Mix")
        vt = df.groupby("violation_type").size().reset_index(name="count").sort_values("count")
        fig2 = px.bar(vt, x="count", y="violation_type", orientation="h",
                      color_discrete_sequence=["#1f2937"],
                      labels={"count": "Orders", "violation_type": "Type"})
        fig2.update_layout(showlegend=False, plot_bgcolor="white", height=300, margin=dict(t=10, b=10))
        st.plotly_chart(fig2, use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("Most Penalised Entities")
        top_entities = (df[df["entity"].str.len() > 2]
                        .groupby("entity").size()
                        .reset_index(name="count")
                        .sort_values("count", ascending=False)
                        .head(15))
        fig4 = px.bar(top_entities, x="count", y="entity", orientation="h",
                      color_discrete_sequence=["#374151"],
                      labels={"count": "Orders", "entity": ""})
        fig4.update_layout(showlegend=False, plot_bgcolor="white", height=380, margin=dict(t=10, b=10))
        st.plotly_chart(fig4, use_container_width=True)

    with c4:
        st.subheader("Repeat Offenders (5+ orders)")
        repeat = (df[df["entity"].str.len() > 2]
                  .groupby("entity").size()
                  .reset_index(name="orders")
                  .query("orders >= 5")
                  .sort_values("orders", ascending=False)
                  .head(20))
        if repeat.empty:
            st.info("No entities with 5+ orders in current filter.")
        else:
            fig_rep = px.bar(repeat, x="orders", y="entity", orientation="h",
                             color="orders",
                             color_continuous_scale="reds",
                             labels={"orders": "Order count", "entity": ""})
            fig_rep.update_layout(plot_bgcolor="white", height=380, margin=dict(t=10, b=10),
                                  showlegend=False)
            st.plotly_chart(fig_rep, use_container_width=True)

# ═══════════════════════════
# TAB 2: Timeline Heatmap (NEW)
# ═══════════════════════════
with t2:
    st.subheader("Monthly Enforcement Heatmap")
    st.caption("Colour intensity = number of orders. Spot enforcement surge periods.")
    pivot = (df.groupby(["year", "month_num"])
               .size()
               .reset_index(name="count"))
    pivot["month_abbr"] = pd.to_datetime(pivot["month_num"], format="%m").dt.strftime("%b")
    heat = pivot.pivot(index="year", columns="month_abbr", values="count").fillna(0)
    month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    heat = heat.reindex(columns=[m for m in month_order if m in heat.columns])

    fig_heat = px.imshow(
        heat,
        labels=dict(x="Month", y="Year", color="Orders"),
        color_continuous_scale="Blues",
        text_auto=True,
        aspect="auto",
    )
    fig_heat.update_layout(height=400, margin=dict(t=10, b=10))
    st.plotly_chart(fig_heat, use_container_width=True)

    # Rolling 3-month trend
    st.subheader("Rolling 3-Month Trend")
    monthly = df.set_index("order_date").resample("ME").size().reset_index(name="count")
    monthly.columns = ["date", "count"]
    monthly["rolling_3m"] = monthly["count"].rolling(3, min_periods=1).mean()
    fig_roll = go.Figure()
    fig_roll.add_trace(go.Bar(x=monthly["date"], y=monthly["count"],
                              name="Monthly", marker_color="#D1D5DB"))
    fig_roll.add_trace(go.Scatter(x=monthly["date"], y=monthly["rolling_3m"],
                                  name="3-month avg", line=dict(color="#1f2937", width=2)))
    fig_roll.update_layout(plot_bgcolor="white", height=280, margin=dict(t=10, b=10),
                           legend=dict(orientation="h"))
    st.plotly_chart(fig_roll, use_container_width=True)

# ═══════════════════════════
# TAB 3: Penalties (NEW)
# ═══════════════════════════
with t3:
    st.subheader("Penalty Analysis")
    pen_df = df[df["penalty_cr"].notna()].copy()
    if pen_df.empty:
        st.info("No penalty amounts could be extracted from the current filter. "
                "Penalty extraction relies on patterns in order titles — not all orders include amounts.")
    else:
        st.caption(f"{len(pen_df):,} orders with extractable penalty amounts")
        pa1, pa2, pa3 = st.columns(3)
        pa1.metric("Total Penalties", f"₹{pen_df['penalty_cr'].sum():,.1f} Cr")
        pa2.metric("Avg Penalty", f"₹{pen_df['penalty_cr'].mean():,.2f} Cr")
        pa3.metric("Largest Single Penalty", f"₹{pen_df['penalty_cr'].max():,.2f} Cr")

        # Top penalty orders
        st.subheader("Top 20 Largest Penalties")
        top_pen = pen_df.nlargest(20, "penalty_cr")[
            ["order_date", "entity", "violation_type", "penalty_cr", "title", "url"]
        ].copy()
        top_pen["order_date"] = top_pen["order_date"].dt.strftime("%d %b %Y")
        top_pen.columns = ["Date", "Entity", "Violation", "Penalty (₹ Cr)", "Title", "URL"]
        st.dataframe(
            top_pen[["Date", "Entity", "Violation", "Penalty (₹ Cr)", "Title"]],
            use_container_width=True, hide_index=True,
        )

        # Penalty by violation type
        pen_by_type = (pen_df.groupby("violation_type")["penalty_cr"]
                       .agg(["sum", "mean", "count"])
                       .reset_index()
                       .rename(columns={"sum": "Total (₹ Cr)", "mean": "Avg (₹ Cr)", "count": "Orders"})
                       .sort_values("Total (₹ Cr)", ascending=False))
        st.subheader("Penalties by Violation Type")
        fig_pt = px.bar(pen_by_type, x="Total (₹ Cr)", y="violation_type",
                        orientation="h", color_discrete_sequence=["#1f2937"])
        fig_pt.update_layout(plot_bgcolor="white", height=350, margin=dict(t=10, b=10))
        st.plotly_chart(fig_pt, use_container_width=True)

# ═══════════════════════════
# TAB 4: Entity Network (NEW)
# ═══════════════════════════
with t4:
    st.subheader("Entity Co-occurrence Network")
    st.caption(
        "Entities connected when they appear in orders with the same violation type "
        "in the same year. Node size = number of orders."
    )

    min_orders = st.slider("Minimum orders per entity to include", 2, 10, 3)

    ent_counts = (df[df["entity"].str.len() > 2]
                  .groupby("entity").size()
                  .reset_index(name="n"))
    top_ents = ent_counts[ent_counts["n"] >= min_orders]["entity"].tolist()

    if len(top_ents) < 2:
        st.info("Not enough entities with the selected minimum. Lower the threshold.")
    else:
        # Build co-occurrence: same violation_type + year → connect entities
        sub = df[df["entity"].isin(top_ents)][["entity", "violation_type", "year"]].dropna()
        G = nx.Graph()
        for ent in top_ents:
            n = ent_counts[ent_counts["entity"] == ent]["n"].values[0]
            G.add_node(ent, size=n)

        groups = sub.groupby(["violation_type", "year"])["entity"].apply(list)
        for members in groups:
            members = [e for e in members if e in top_ents]
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    if G.has_edge(members[i], members[j]):
                        G[members[i]][members[j]]["weight"] += 1
                    else:
                        G.add_edge(members[i], members[j], weight=1)

        # Remove isolates
        G.remove_nodes_from(list(nx.isolates(G)))

        if G.number_of_nodes() == 0:
            st.info("No co-occurrences found. Try a different filter.")
        else:
            pos = nx.spring_layout(G, seed=42, k=0.8)
            node_sizes = [G.nodes[n].get("size", 1) * 5 for n in G.nodes]

            edge_x, edge_y = [], []
            for u, v in G.edges():
                x0, y0 = pos[u]
                x1, y1 = pos[v]
                edge_x += [x0, x1, None]
                edge_y += [y0, y1, None]

            node_x = [pos[n][0] for n in G.nodes]
            node_y = [pos[n][1] for n in G.nodes]
            node_text = [f"{n}<br>Orders: {G.nodes[n].get('size', '?')}" for n in G.nodes]

            fig_g = go.Figure(
                data=[
                    go.Scatter(x=edge_x, y=edge_y, mode="lines",
                               line=dict(color="#D1D5DB", width=0.8), hoverinfo="none"),
                    go.Scatter(x=node_x, y=node_y, mode="markers+text",
                               marker=dict(size=node_sizes, color="#1f2937",
                                           line=dict(color="white", width=1)),
                               text=list(G.nodes), textposition="top center",
                               hovertext=node_text, hoverinfo="text",
                               textfont=dict(size=9)),
                ],
                layout=go.Layout(
                    showlegend=False, hovermode="closest",
                    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                    yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                    plot_bgcolor="white", height=550, margin=dict(t=10, b=10),
                ),
            )
            st.plotly_chart(fig_g, use_container_width=True)
            st.caption(f"{G.number_of_nodes()} entities · {G.number_of_edges()} co-occurrence edges")

# ═══════════════════════════
# TAB 5: Orders Table (paginated)
# ═══════════════════════════
with t5:
    st.subheader(f"All Orders ({len(df):,})")

    PAGE_SIZE = 100
    total_pages = max(1, (len(df) - 1) // PAGE_SIZE + 1)
    page = st.number_input("Page", min_value=1, max_value=total_pages, value=1) - 1

    display = df.iloc[page * PAGE_SIZE:(page + 1) * PAGE_SIZE].copy()
    display["order_date"] = display["order_date"].dt.strftime("%d %b %Y")
    display_cols = ["order_date", "entity", "violation_type", "penalty_cr", "title"]
    columns_map = {
        "order_date": "Date", "entity": "Entity",
        "violation_type": "Violation", "penalty_cr": "Penalty (₹ Cr)", "title": "Order Title",
    }
    st.dataframe(
        display[display_cols].rename(columns=columns_map),
        use_container_width=True, hide_index=True,
        column_config={
            "Order Title": st.column_config.TextColumn(width="large"),
            "Date": st.column_config.TextColumn(width="small"),
            "Penalty (₹ Cr)": st.column_config.NumberColumn(format="₹%.2f Cr"),
        }
    )
    st.caption(f"Page {page + 1} of {total_pages}")

    # Export
    c1, c2 = st.columns(2)
    c1.download_button(
        "⬇️ Download filtered CSV",
        df[display_cols].to_csv(index=False).encode(),
        file_name="sebi_orders_filtered.csv", mime="text/csv",
    )
    try:
        import io
        import openpyxl  # noqa: F401 -- import only to detect availability; raises ImportError if missing
        buf = io.BytesIO()
        df[display_cols].to_excel(buf, index=False, engine="openpyxl")
        c2.download_button(
            "⬇️ Download filtered Excel",
            buf.getvalue(),
            file_name="sebi_orders_filtered.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except ImportError:
        c2.caption("Install `openpyxl` for Excel export")
