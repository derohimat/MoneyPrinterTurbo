
import streamlit as st
import pandas as pd
import json
import os
import sys

# Path setup
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from app.utils import analytics_db, script_scorer
from app.services import task as tm

st.set_page_config(page_title="Analytics", page_icon="📈", layout="wide")

st.title("📈 Analytics Dashboard")

# Initialize DB if needed (failsafe)
analytics_db.init_analytics_db()

# Tabs
tab_overview, tab_hooks, tab_ab, tab_scorer = st.tabs(["Overview", "Hook Performance", "A/B Testing", "Script Scorer"])

with tab_overview:
    st.header("Performance Overview")
    
    # Summary Metrics
    col1, col2, col3, col4 = st.columns(4)
    
    # Get all performance data for summary
    # We don't have a get_all_performance_summary function yet, let's just use get_performance_summary (top 50)
    # or better, add a simple count/avg query. 
    # For now, let's assume we fetch a reasonable amount to calc stats or add a summary query later.
    # Actually get_category_performance gives us category averages.
    # get_daily_views gives us trend.
    
    cat_perf = analytics_db.get_category_performance()
    daily_views = analytics_db.get_daily_views(30)
    
    total_videos = sum(c["video_count"] for c in cat_perf) if cat_perf else 0
    avg_retention = sum(c["avg_retention"] * c["video_count"] for c in cat_perf) / total_videos if total_videos > 0 else 0
    
    total_views_30d = sum(d["total_views"] for d in daily_views) if daily_views else 0

    col1.metric("Total Videos Tracked", total_videos)
    col2.metric("Avg Retention Rate", f"{avg_retention*100:.1f}%")
    col3.metric("Views (Last 30 Days)", total_views_30d)
    
    if cat_perf:
        best_cat = max(cat_perf, key=lambda x: x["avg_retention"])
        col4.metric("Best Category", best_cat["category"], f"{best_cat['avg_retention']*100:.1f}% Ret.")
    else:
        col4.metric("Best Category", "N/A")

    st.divider()

    # Charts
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("Daily Views (30 Days)")
        if daily_views:
            df_daily = pd.DataFrame(daily_views)
            st.bar_chart(df_daily, x="date", y="total_views")
        else:
            st.info("No view data available yet.")
            
    with c2:
        st.subheader("Retention by Category")
        if cat_perf:
            df_cat = pd.DataFrame(cat_perf)
            # Normalize retention to percentage
            df_cat["avg_retention"] = df_cat["avg_retention"] * 100
            st.bar_chart(df_cat, x="category", y="avg_retention")
        else:
            st.info("No category data available yet.")

with tab_hooks:
    st.header("🪝 Hook Effectiveness")
    
    hook_limit = st.slider("Number of hooks", 5, 20, 10)
    min_samples = st.slider("Min samples", 1, 10, 2)
    
    top_hooks = analytics_db.get_top_hooks(limit=hook_limit, min_samples=min_samples)
    
    if top_hooks:
        df_hooks = pd.DataFrame(top_hooks)
        df_hooks["avg_retention"] = df_hooks["avg_retention"] * 100
        df_hooks["avg_ctr"] = df_hooks["avg_ctr"] * 100
        
        st.dataframe(
            df_hooks,
            column_config={
                "hook_template": "Hook Template",
                "use_count": "Usage Count",
                "avg_retention": st.column_config.ProgressColumn(
                    "Avg Retention (%)", format="%.1f%%", min_value=0, max_value=100
                ),
                "avg_ctr": st.column_config.NumberColumn("Avg CTR (%)", format="%.2f%%")
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("Not enough data to analyze hooks. Try lowering min samples.")

with tab_ab:
    st.header("⚖️ A/B Testing")
    
    with st.expander("Create New Test"):
        with st.form("new_ab_test"):
            test_name = st.text_input("Test Name", placeholder="e.g. Hook Style A vs B")
            min_views = st.number_input("Min Views to Conclude", value=1000, step=100)
            
            # Need a way to select task IDs. 
            # ideally separate input or pasted IDs.
            variants_input = st.text_area("Variant Task IDs (comma separated)", placeholder="task-123, task-456")
            
            submitted = st.form_submit_button("Create Test")
            if submitted and test_name and variants_input:
                variant_ids = [v.strip() for v in variants_input.split(",") if v.strip()]
                if len(variant_ids) < 2:
                    st.error("Need at least 2 variants.")
                else:
                    tid = analytics_db.create_ab_test(test_name, variant_ids, min_views)
                    if tid:
                        st.success(f"Test created! ID: {tid}")
                    else:
                        st.error("Failed to create test.")

    st.subheader("Active Tests")
    tests = analytics_db.get_ab_tests()
    if tests:
        # Check active tests logic
        for test in tests:
            if test["status"] == "active":
                # Auto-evaluate on page load? Or manual button.
                # Let's add an Evaluate button.
                col_t1, col_t2 = st.columns([3, 1])
                with col_t1:
                    st.markdown(f"**{test['test_name']}** (ID: `{test['test_id']}`)")
                    st.caption(f"Status: {test['status']} | Min Views: {test['min_views']}")
                with col_t2:
                    if st.button("Evaluate", key=f"eval_{test['test_id']}"):
                        winner = analytics_db.evaluate_ab_test(test['test_id'])
                        if winner:
                            st.success(f"Winner found: {winner}")
                            st.rerun()
                        else:
                            st.info("Not enough data yet.")
                st.divider()
    else:
        st.info("No A/B tests found.")

with tab_scorer:
    st.header("📝 Script Scorer")
    st.write("Analyze your script before generating to predict engagement.")
    
    script_input = st.text_area("Paste Script Here", height=200)
    if st.button("Analyze Script"):
        if script_input:
            res = script_scorer.score_script(script_input)
            
            s_col1, s_col2 = st.columns([1, 2])
            
            with s_col1:
                st.metric("Engagement Score", f"{res['score']}/100")
                if res['score'] < 50:
                    st.error("Needs Improvement")
                elif res['score'] < 80:
                    st.warning("Good")
                else:
                    st.success("Excellent!")
            
            with s_col2:
                st.subheader("Breakdown")
                st.json(res["breakdown"])
            
            if res["feedback"]:
                st.subheader("Tips")
                for tip in res["feedback"]:
                    st.info(f"💡 {tip}")
