import streamlit as st
import pandas as pd
import numpy as np
import pulp
import altair as alt

st.set_page_config(page_title="PwC Strategy& Value Creation: Sourcing Optimizer", layout="wide")

st.title("🌍 PE Value Creation: Strategic Sourcing & Working Capital Twin")
st.markdown("**Context:** Post-Deal 100-Day Plan for a PE-backed Wholesaler. The objective is to optimize the supplier network, balancing Unit Cost (FOB) against Working Capital, Lead Times, and Agility.")

# --- 1. 52-WEEK STOCHASTIC DEMAND GENERATION ---
WEEKS = list(range(1, 53))

@st.cache_data
def generate_demand():
    np.random.seed(42) # Seeded for consistent presentation
    # Mean demand of 2,000/wk, highly volatile StDev of 600
    return {w: max(0, int(np.random.normal(2000, 600))) for w in WEEKS}

DEMAND = generate_demand()

# --- 2. SOURCING ECONOMICS ---
PRICE = 80 # Selling price to retailers

# Supplier A: Far-East (China) - Low Cost, Slow, Rigid
CHINA = {
    "FOB_Cost": 20.0,
    "Freight_Cost": 2.0,
    "Lead_Time": 10, # 10 weeks
    "MOQ": 10000
}

# Supplier B: Nearshore (Poland) - High Cost, Fast, Agile
POLAND = {
    "FOB_Cost": 26.0,
    "Freight_Cost": 1.0,
    "Lead_Time": 2, # 2 weeks
    "MOQ": 1000
}

# --- 3. SIDEBAR CONTROLS ---
with st.sidebar:
    st.header("🏢 Value Creation Playbook")
    strategy = st.radio("Sourcing Strategy", [
        "Legacy Strategy (100% Far-East)", 
        "Value Creation Mix (Dual-Sourcing)"
    ])
    
    st.markdown("---")
    st.header("Financial Levers")
    st.info("Watch how changing the Cost of Capital completely alters the mathematical viability of Far-East sourcing.")
    wacc_annual = st.slider("Cost of Capital (Annual WACC %)", 5.0, 25.0, 12.0) / 100.0
    wacc_weekly = wacc_annual / 52.0
    
    holding_cost = st.slider("3PL Storage (£/unit/wk)", 0.1, 1.0, 0.4)
    stockout_penalty = st.slider("Lost Sale Penalty (£/unit)", 20, 80, 40)
    st.caption("Lost sale penalty represents lost margin + reputational damage.")
    
    run_button = st.button("🚀 Run 52-Week Optimizer", type="primary", use_container_width=True)

# --- 4. THE MILP OPTIMIZATION ENGINE ---
if run_button:
    with st.spinner("Solving 52-Week Multi-Echelon Linear Program..."):
        model = pulp.LpProblem("Strategic_Sourcing", pulp.LpMaximize)
        
        # Variables
        order_c = pulp.LpVariable.dicts("Order_China", WEEKS, lowBound=0, cat='Integer')
        order_c_bin = pulp.LpVariable.dicts("Order_China_Bin", WEEKS, cat='Binary')
        
        order_p = pulp.LpVariable.dicts("Order_Poland", WEEKS, lowBound=0, cat='Integer')
        order_p_bin = pulp.LpVariable.dicts("Order_Poland_Bin", WEEKS, cat='Binary')
        
        inv = pulp.LpVariable.dicts("Inv", [0] + WEEKS, lowBound=0, cat='Integer')
        sales = pulp.LpVariable.dicts("Sales", WEEKS, lowBound=0, cat='Integer')
        shortage = pulp.LpVariable.dicts("Shortage", WEEKS, lowBound=0, cat='Integer')
        
        # Starting Inventory (To cover the initial 10-week China lead time)
        model += inv[0] == 22000
        
        # Helper functions for Lead Time Arrivals
        def arr_china(w):
            if w <= CHINA["Lead_Time"]: return 2000 # Pre-existing pipeline arriving
            return order_c[w - CHINA["Lead_Time"]]
            
        def arr_poland(w):
            if w <= POLAND["Lead_Time"]: return 0
            return order_p[w - POLAND["Lead_Time"]]

        for w in WEEKS:
            # MOQ Logic (Big M constraint)
            model += order_c[w] >= CHINA["MOQ"] * order_c_bin[w]
            model += order_c[w] <= 100000 * order_c_bin[w]
            
            model += order_p[w] >= POLAND["MOQ"] * order_p_bin[w]
            model += order_p[w] <= 100000 * order_p_bin[w]
            
            # Legacy Strategy forces Poland to 0
            if strategy == "Legacy Strategy (100% Far-East)":
                model += order_p[w] == 0
                
            # Inventory Balance
            model += inv[w] == inv[w-1] + arr_china(w) + arr_poland(w) - sales[w]
            
            # Sales & Shortages
            model += sales[w] <= DEMAND[w]
            model += sales[w] <= inv[w-1] + arr_china(w) + arr_poland(w)
            model += shortage[w] == DEMAND[w] - sales[w]
            
        # Financial Objective Function
        revenue = pulp.lpSum([sales[w] * PRICE for w in WEEKS])
        cogs = pulp.lpSum([order_c[w] * CHINA["FOB_Cost"] + order_p[w] * POLAND["FOB_Cost"] for w in WEEKS])
        freight = pulp.lpSum([order_c[w] * CHINA["Freight_Cost"] + order_p[w] * POLAND["Freight_Cost"] for w in WEEKS])
        holding = pulp.lpSum([inv[w] * holding_cost for w in WEEKS])
        lost_sales_cost = pulp.lpSum([shortage[w] * stockout_penalty for w in WEEKS])
        
        # Working Capital Cost (WACC applied to cash trapped in-transit and on-hand)
        # Cash trapped in China ocean freight for 10 weeks
        wacc_transit_c = pulp.lpSum([order_c[w] * CHINA["FOB_Cost"] * CHINA["Lead_Time"] * wacc_weekly for w in WEEKS])
        # Cash trapped in Poland truck freight for 2 weeks
        wacc_transit_p = pulp.lpSum([order_p[w] * POLAND["FOB_Cost"] * POLAND["Lead_Time"] * wacc_weekly for w in WEEKS])
        # Cash trapped in On-Hand Warehouse Inventory (Blended ~£22/unit)
        wacc_on_hand = pulp.lpSum([inv[w] * 22.0 * wacc_weekly for w in WEEKS])
        
        total_wacc_cost = wacc_transit_c + wacc_transit_p + wacc_on_hand
        
        model += revenue - (cogs + freight + holding + lost_sales_cost + total_wacc_cost)
        model.solve(pulp.PULP_CBC_CMD(msg=0))
        
        # --- EXTRACT RESULTS ---
        def val(var): return var.varValue if var.varValue else 0
        
        t_rev = sum([val(sales[w]) * PRICE for w in WEEKS])
        t_cogs = sum([val(order_c[w]) * CHINA["FOB_Cost"] + val(order_p[w]) * POLAND["FOB_Cost"] for w in WEEKS])
        t_freight = sum([val(order_c[w]) * CHINA["Freight_Cost"] + val(order_p[w]) * POLAND["Freight_Cost"] for w in WEEKS])
        t_holding = sum([val(inv[w]) * holding_cost for w in WEEKS])
        t_lost = sum([val(shortage[w]) * stockout_penalty for w in WEEKS])
        t_wacc = sum([val(order_c[w]) * CHINA["FOB_Cost"] * CHINA["Lead_Time"] * wacc_weekly for w in WEEKS]) + \
                 sum([val(order_p[w]) * POLAND["FOB_Cost"] * POLAND["Lead_Time"] * wacc_weekly for w in WEEKS]) + \
                 sum([val(inv[w]) * 22.0 * wacc_weekly for w in WEEKS])
                 
        ebitda = t_rev - (t_cogs + t_freight + t_holding + t_wacc) # Internal Management EBITDA
        
        tot_dem = sum([DEMAND[w] for w in WEEKS])
        tot_sold = sum([val(sales[w]) for w in WEEKS])
        sl = (tot_sold / tot_dem) * 100
        
        avg_inv_value = (sum([val(inv[w]) for w in WEEKS]) / 52) * 22.0
        avg_transit_value = (sum([val(order_c[w])*CHINA["FOB_Cost"]*CHINA["Lead_Time"]/52 for w in WEEKS])) + \
                            (sum([val(order_p[w])*POLAND["FOB_Cost"]*POLAND["Lead_Time"]/52 for w in WEEKS]))
        total_working_capital = avg_inv_value + avg_transit_value
        
        roic = (ebitda / total_working_capital) * 100 if total_working_capital > 0 else 0

        # --- UI DASHBOARD ---
        tab1, tab2, tab3, tab4 = st.tabs(["📊 CFO Exec Summary", "💰 Total Landed P&L", "📦 Inventory & Cash Flow", "🚢 52-Week PO Schedule"])
        
        with tab1:
            st.subheader(f"Strategy Results: {strategy}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Annual EBITDA (£)", f"£{ebitda:,.0f}")
            c2.metric("Working Capital Tied Up", f"£{total_working_capital:,.0f}")
            c3.metric("Annualized ROIC", f"{roic:.1f}%")
            c4.metric("Customer Service Level", f"{sl:.1f}%")
            
            st.markdown("---")
            st.info("💡 **Strategy& Value Creation Thesis:** If you selected the 'Dual-Sourcing' mix, notice how ROIC skyrocketed despite paying Poland a higher unit cost. The solver mathematically proves that spending more on Unit Price to buy agility massively reduces trapped Working Capital and completely eliminates Lost Sales penalties.")
            
        with tab2:
            st.subheader("Annual P&L & Landed Costs")
            def pct(v): return f"{(abs(v)/t_rev)*100:.1f}%" if t_rev>0 else "0%"
            
            pl_df = pd.DataFrame({
                "Line Item": ["Gross Sales Revenue", "FOB Materials Cost (China + Poland)", "Freight Cost (Ocean + Truck)", "3PL Physical Holding Cost", "WACC Cost (Cash Opportunity Cost)", "EBITDA"],
                "Amount (£)": [f"£{t_rev:,.0f}", f"-£{t_cogs:,.0f}", f"-£{t_freight:,.0f}", f"-£{t_holding:,.0f}", f"-£{t_wacc:,.0f}", f"£{ebitda:,.0f}"],
                "% of Revenue": ["100%", pct(t_cogs), pct(t_freight), pct(t_holding), pct(t_wacc), pct(ebitda)]
            })
            st.table(pl_df)
            
            st.metric("Total Opportunity Cost of Stockouts", f"£{t_lost:,.0f}", delta="Avoidable Value Leakage", delta_color="inverse")
            
        with tab3:
            st.subheader("Operations: Inventory & Demand Agility")
            
            chart_data = []
            for w in WEEKS:
                chart_data.append({"Week": w, "Metric": "Customer Demand", "Units": DEMAND[w]})
                chart_data.append({"Week": w, "Metric": "Warehouse Inventory", "Units": val(inv[w])})
            
            c_df = pd.DataFrame(chart_data)
            chart = alt.Chart(c_df).mark_line().encode(
                x='Week:Q', y='Units:Q', color='Metric:N'
            ).properties(height=350, title="Inventory Cushion vs. Stochastic Demand")
            st.altair_chart(chart, use_container_width=True)

        with tab4:
            st.subheader("Optimal Sourcing Schedule (The 'To-Do' List)")
            po_data = []
            for w in WEEKS:
                po_data.append({
                    "Week": w,
                    "Forecasted Demand": DEMAND[w],
                    "PO to China (10 Wk LT)": int(val(order_c[w])) if val(order_c[w]) > 0 else "-",
                    "PO to Poland (2 Wk LT)": int(val(order_p[w])) if val(order_p[w]) > 0 else "-",
                    "Ending Inv": int(val(inv[w])),
                    "Lost Sales": int(val(shortage[w]))
                })
            st.dataframe(pd.DataFrame(po_data).set_index("Week"), use_container_width=True)
else:
    st.info("👈 Open the sidebar on the left and click 'Run 52-Week Optimizer' to start.")
