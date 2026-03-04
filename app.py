import streamlit as st
import pandas as pd
import numpy as np
import pulp
import io
import altair as alt
import math
from scipy.stats import norm

st.set_page_config(page_title="Strategy& Value Creation: Sourcing Twin", layout="wide")

st.title("🌍 PE Value Creation: Optimized LBO Sourcing Twin")
st.markdown("**Context:** Evaluating a 2-Year PE Hold. This model uses a Mixed-Integer Linear Program (MILP) combined with dynamic Newsvendor Critical Ratios to find the mathematically optimal balance between fixed freight costs, working capital, and exit EBITDA.")

# --- 1. CONFIGURATION ---
WEEKS = list(range(1, 105)) # 2 Years
DEFAULT_PRODUCTS = ["Smart Thermostat", "HD Security Camera", "Wi-Fi Mesh Router", "Smart Plug (4-Pack)"]

DEMAND_PARAMS = {
    "Smart Thermostat": {"mean": 2000, "std": 450},
    "HD Security Camera": {"mean": 3500, "std": 800},
    "Wi-Fi Mesh Router": {"mean": 1200, "std": 300},
    "Smart Plug (4-Pack)": {"mean": 5000, "std": 1000}
}

DEFAULT_ECO = {
    "Smart Thermostat": {"price": 120.0, "unit_cbm": 0.005, "fe_fob": 35.0, "fe_lt": 10, "ns_fob": 39.0, "ns_lt": 2},
    "HD Security Camera": {"price": 85.0, "unit_cbm": 0.003, "fe_fob": 22.0, "fe_lt": 10, "ns_fob": 25.0, "ns_lt": 2},
    "Wi-Fi Mesh Router": {"price": 150.0, "unit_cbm": 0.015, "fe_fob": 45.0, "fe_lt": 10, "ns_fob": 51.0, "ns_lt": 2},
    "Smart Plug (4-Pack)": {"price": 30.0, "unit_cbm": 0.002, "fe_fob": 8.0, "fe_lt": 10, "ns_fob": 10.0, "ns_lt": 2}
}

FE_CONTAINER_CBM, FE_CONTAINER_COST = 68.0, 6500  
NS_TRUCK_CBM, NS_TRUCK_COST = 80.0, 2500      

# --- 2. DYNAMIC DEMAND GENERATOR ---
if 'demand_locked' not in st.session_state:
    st.session_state.demand_locked = False
    st.session_state.actual_demand = {}

def generate_stochastic_demand(products, params, y2_growth):
    path = {}
    for p in products:
        mean, std = params[p]["mean"], params[p]["std"]
        path[p] = {}
        for w in WEEKS:
            growth_multiplier = (1 + y2_growth) if w > 52 else 1
            path[p][w] = max(0, int(np.random.normal(mean * growth_multiplier, std * growth_multiplier)))
    st.session_state.actual_demand = path
    st.session_state.demand_locked = True

# --- 3. EXCEL EXPORT ENGINE ---
def generate_cfo_ledger(results_dict, lbo_metrics):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        lbo_data = [{"Strategy": n, **lbo} for n, lbo in lbo_metrics.items()]
        pd.DataFrame(lbo_data).to_excel(writer, sheet_name="LBO_Returns", index=False)
        for name, res in results_dict.items():
            prefix = "Legacy_" if "Legacy" in name else "Dual_"
            log_data = [{"Week": w, "China Containers": res["containers_fe"][w], "Poland Trucks": res["trucks_ns"][w], "Total Freight": res["cost_freight"][w]} for w in WEEKS]
            pd.DataFrame(log_data).to_excel(writer, sheet_name=f"{prefix}Logistics", index=False)
            for p in ACTIVE_PRODUCTS:
                prod_data = [{"Week": w, "Demand": DEMAND_ACTUAL[p][w], "Sales": res["sales"][p][w], "Lost Sales": res["shortage"][p][w], "Ending Inv": res["inv"][p][w], "China PO": res["order_fe"][p][w], "Poland PO": res["order_ns"][p][w]} for w in WEEKS]
                pd.DataFrame(prod_data).to_excel(writer, sheet_name=f"{prefix}{p[:20]}".replace(" ", ""), index=False)
    return output.getvalue()

# --- 4. SIDEBAR CONTROLS ---
with st.sidebar:
    ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS, FINANCIALS = DEFAULT_PRODUCTS, DEMAND_PARAMS, DEFAULT_ECO

    st.header("Step 1: Market Volatility")
    y2_growth_ui = st.slider("Year 2 Market Growth (%)", 0.0, 30.0, 10.0) / 100.0
    
    if st.button("🔒 Lock 104-Week Actuals", use_container_width=True):
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS, y2_growth_ui)
        st.success("Locked!")

    if not st.session_state.demand_locked:
        np.random.seed(42) 
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS, y2_growth_ui)
    
    st.markdown("---")
    st.header("Step 2: LBO Mechanics")
    with st.form("lbo_panel"):
        entry_multiple = st.slider("Exit Multiple (x EBITDA)", 6.0, 15.0, 9.0)
        debt_ratio = st.slider("Debt Funding Ratio (%)", 0.0, 80.0, 60.0) / 100.0
        interest_rate = st.slider("Debt Interest Rate (%)", 5.0, 15.0, 9.0) / 100.0
        
        st.subheader("Operational Cost Levers")
        tariff_rate = st.slider("China Import Tariff (%)", 0.0, 20.0, 8.0) / 100.0
        wacc_annual = st.slider("Cost of Capital (WACC %)", 5.0, 25.0, 12.0) / 100.0
        wacc_weekly = wacc_annual / 52.0
        holding_cost = st.slider("UK 3PL Storage (£/unit/wk)", 0.05, 0.50, 0.15)
        stockout_penalty = st.slider("Lost Sale Penalty (£/unit)", 20, 150, 80)
        corp_tax = 0.25 
        submitted = st.form_submit_button("🚀 Run Value Creation Optimizer")

DEMAND_ACTUAL = st.session_state.actual_demand

# --- 5. THE MASTER MILP OPTIMIZER ---
def run_milp_optimizer(strategy_type):
    prob = pulp.LpProblem(f"Sourcing_{strategy_type.replace(' ', '')}", pulp.LpMaximize)
    
    order_fe = pulp.LpVariable.dicts("Order_FE", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    order_ns = pulp.LpVariable.dicts("Order_NS", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    containers_fe = pulp.LpVariable.dicts("Containers_FE", WEEKS, lowBound=0, cat='Integer')
    trucks_ns = pulp.LpVariable.dicts("Trucks_NS", WEEKS, lowBound=0, cat='Integer')
    inv = pulp.LpVariable.dicts("Inv", (ACTIVE_PRODUCTS, [0] + WEEKS), lowBound=0, cat='Integer')
    sales = pulp.LpVariable.dicts("Sales", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    shortage = pulp.LpVariable.dicts("Shortage", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')

    # Calculate specific Newsvendor Starting Inventory to prevent Day 1 shocks
    for p in ACTIVE_PRODUCTS:
        stdev_base = ACTIVE_DEMAND_PARAMS[p]["std"]
        cu = stockout_penalty
        
        if strategy_type == "Legacy (China Only)":
            co_fe = (holding_cost + wacc_weekly * FINANCIALS[p]["fe_fob"]) * FINANCIALS[p]["fe_lt"]
            cr_fe = cu / (cu + co_fe)
            z_fe = norm.ppf(cr_fe)
            ss_initial = int(z_fe * stdev_base * math.sqrt(FINANCIALS[p]["fe_lt"]))
        else:
            co_ns = (holding_cost + wacc_weekly * FINANCIALS[p]["ns_fob"]) * FINANCIALS[p]["ns_lt"]
            cr_ns = cu / (cu + co_ns)
            z_ns = norm.ppf(cr_ns)
            ss_initial = int(z_ns * stdev_base * math.sqrt(FINANCIALS[p]["ns_lt"]))
            
        prob += inv[p][0] == int(ACTIVE_DEMAND_PARAMS[p]["mean"] * FINANCIALS[p]["fe_lt"]) + ss_initial

        for w in WEEKS:
            # DYNAMIC NEWSVENDOR SAFETY STOCK FLOOR
            growth_multiplier = (1 + y2_growth_ui) if w > 52 else 1
            stdev = ACTIVE_DEMAND_PARAMS[p]["std"] * growth_multiplier
            
            if strategy_type == "Legacy (China Only)":
                ss_floor = int(z_fe * stdev * math.sqrt(FINANCIALS[p]["fe_lt"]))
            else:
                ss_floor = int(z_ns * stdev * math.sqrt(FINANCIALS[p]["ns_lt"]))

            prob += inv[p][w] >= ss_floor
            
            arr_fe = order_fe[p][w - FINANCIALS[p]["fe_lt"]] if w > FINANCIALS[p]["fe_lt"] else int(ACTIVE_DEMAND_PARAMS[p]["mean"])
            arr_ns = order_ns[p][w - FINANCIALS[p]["ns_lt"]] if w > FINANCIALS[p]["ns_lt"] else 0

            if strategy_type == "Legacy (China Only)": 
                prob += order_ns[p][w] == 0
                
            prob += inv[p][w] == inv[p][w-1] + arr_fe + arr_ns - sales[p][w]
            prob += sales[p][w] <= DEMAND_ACTUAL[p][w]
            prob += sales[p][w] <= inv[p][w-1] + arr_fe + arr_ns
            prob += shortage[p][w] == DEMAND_ACTUAL[p][w] - sales[p][w]
            
            if w > 104 - FINANCIALS[p]["fe_lt"]: prob += order_fe[p][w] == 0
            if w > 104 - FINANCIALS[p]["ns_lt"]: prob += order_ns[p][w] == 0

    for w in WEEKS:
        prob += pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS]) <= containers_fe[w] * FE_CONTAINER_CBM
        prob += pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS]) <= trucks_ns[w] * NS_TRUCK_CBM

    revenue = pulp.lpSum([sales[p][w] * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    cogs_fe = pulp.lpSum([order_fe[p][w] * (FINANCIALS[p]["fe_fob"] * (1+tariff_rate)) for p in ACTIVE_PRODUCTS for w in WEEKS])
    cogs_ns = pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["ns_fob"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    freight = pulp.lpSum([containers_fe[w] * FE_CONTAINER_COST + trucks_ns[w] * NS_TRUCK_COST for w in WEEKS])
    holding = pulp.lpSum([inv[p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in WEEKS])
    penalties = pulp.lpSum([shortage[p][w] * stockout_penalty for p in ACTIVE_PRODUCTS for w in WEEKS])
    wacc_cost = pulp.lpSum([order_fe[p][w]*FINANCIALS[p]["fe_fob"]*FINANCIALS[p]["fe_lt"]*wacc_weekly + order_ns[p][w]*FINANCIALS[p]["ns_fob"]*FINANCIALS[p]["ns_lt"]*wacc_weekly + inv[p][w]*FINANCIALS[p]["fe_fob"]*wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    salvage_value = pulp.lpSum([inv[p][104] * FINANCIALS[p]["fe_fob"] * 0.90 for p in ACTIVE_PRODUCTS])
    
    prob += (revenue + salvage_value) - (cogs_fe + cogs_ns + freight + holding + penalties + wacc_cost)
    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=20, gapRel=0.03))
    
    def get_val(var): return var.varValue if var.varValue else 0
    return {
        "sales": {p: {w: int(get_val(sales[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "shortage": {p: {w: int(get_val(shortage[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "inv": {p: {w: int(get_val(inv[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "inv_0": {p: int(get_val(inv[p][0])) for p in ACTIVE_PRODUCTS},
        "order_fe": {p: {w: int(get_val(order_fe[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "order_ns": {p: {w: int(get_val(order_ns[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "containers_fe": {w: int(get_val(containers_fe[w])) for w in WEEKS},
        "trucks_ns": {w: int(get_val(trucks_ns[w])) for w in WEEKS},
        "cost_freight": {w: (int(get_val(containers_fe[w])) * FE_CONTAINER_COST) + (int(get_val(trucks_ns[w])) * NS_TRUCK_COST) for w in WEEKS}
    }

# --- 6. LBO FINANCIAL ENGINE ---
def calc_lbo(res, is_baseline, entry_ebitda=None):
    def get_ebitda(s_w, e_w):
        rev = sum([res["sales"][p][w] * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        cogs = sum([res["order_fe"][p][w] * (FINANCIALS[p]["fe_fob"] * (1+tariff_rate)) + res["order_ns"][p][w] * FINANCIALS[p]["ns_fob"] for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        freight = sum([res["cost_freight"][w] for w in range(s_w, e_w)])
        holding = sum([res["inv"][p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        short = sum([res["shortage"][p][w] * stockout_penalty for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        return rev - (cogs + freight + holding + short)

    y1_ebitda, y2_ebitda = get_ebitda(1, 53), get_ebitda(53, 105)
    
    start_nwc = sum([res["inv_0"][p] * FINANCIALS[p]["fe_fob"] for p in ACTIVE_PRODUCTS])
    y1_nwc = sum([res["inv"][p][52] * FINANCIALS[p]["fe_fob"] for p in ACTIVE_PRODUCTS])
    y2_nwc = sum([res["inv"][p][104] * FINANCIALS[p]["fe_fob"] for p in ACTIVE_PRODUCTS])
    
    entry_ev = (y1_ebitda if is_baseline else entry_ebitda) * entry_multiple
    starting_debt = entry_ev * debt_ratio
    entry_equity = entry_ev - starting_debt

    y1_fcf = y1_ebitda - (starting_debt * interest_rate) - (y1_nwc - start_nwc)
    end_y1_debt = starting_debt - y1_fcf
    
    y2_fcf = y2_ebitda - (end_y1_debt * interest_rate) - (y2_nwc - y1_nwc)
    ending_debt = end_y1_debt - y2_fcf
    
    exit_ev = y2_ebitda * entry_multiple
    salvage = sum([res["inv"][p][104] * FINANCIALS[p]["fe_fob"] * 0.9 for p in ACTIVE_PRODUCTS])
    exit_equity = (exit_ev + salvage) - ending_debt
    
    return {"entry_ev": entry_ev, "starting_debt": starting_debt, "entry_equity": entry_equity, "y1_ebitda": y1_ebitda, "y1_delta_nwc": y1_nwc-start_nwc, "y1_fcf": y1_fcf, "y2_ebitda": y2_ebitda, "y2_delta_nwc": y2_nwc-y1_nwc, "y2_fcf": y2_fcf, "exit_ev": exit_ev, "ending_debt": ending_debt, "exit_equity": exit_equity, "moic": exit_equity / entry_equity if entry_equity > 0 else 0}

# --- 7. EXECUTION ---
with st.spinner("Optimizing Legacy Strategy (China Only)..."):
    res_leg = run_milp_optimizer("Legacy (China Only)")
    lbo_leg = calc_lbo(res_leg, True)

with st.spinner("Optimizing Dual-Sourcing Strategy..."):
    res_dual = run_milp_optimizer("Dual-Sourcing")
    lbo_dual = calc_lbo(res_dual, False, lbo_leg["y1_ebitda"])

results = {"Legacy (China Only)": res_leg, "Optimized Dual-Sourcing": res_dual}
lbo_results = {"Legacy (China Only)": lbo_leg, "Optimized Dual-Sourcing": lbo_dual}

# --- 8. DASHBOARDS ---
tab1, tab2, tab3, tab4 = st.tabs(["🚀 LBO Return Multiples", "📊 Newsvendor OR Parameters", "📦 Base-Surge Dynamics", "📥 CFO Audit Ledger"])

with tab1:
    st.subheader("The Deal Scorecard: Multiple on Invested Capital (MOIC)")
    cols = st.columns(2)
    for i, (name, lbo) in enumerate(lbo_results.items()):
        with cols[i]:
            st.markdown(f"### {name}")
            st.metric("Total Equity MOIC", f"{lbo['moic']:.2f}x")
            st.metric("Exit Enterprise Value", f"£{lbo['exit_ev']:,.0f}")
            st.metric("Total Free Cash Flow Generated", f"£{lbo['y1_fcf'] + lbo['y2_fcf']:,.0f}")
            st.metric("Year 2 EBITDA (Exit Basis)", f"£{lbo['y2_ebitda']:,.0f}")

with tab2:
    st.subheader("Operations Research: Dynamic Safety Stock Math")
    st.info("Instead of hardcoding a 95% service level heuristic, the model uses the **Newsvendor Critical Ratio** to calculate the mathematically optimal risk tolerance for each strategy, scaling the safety stock by the square root of the lead time.")
    
    or_data = []
    cu = stockout_penalty
    for p in ACTIVE_PRODUCTS:
        stdev = ACTIVE_DEMAND_PARAMS[p]["std"]
        
        # Legacy Math
        co_fe = (holding_cost + wacc_weekly * FINANCIALS[p]["fe_fob"]) * FINANCIALS[p]["fe_lt"]
        cr_fe = cu / (cu + co_fe)
        ss_fe = int(norm.ppf(cr_fe) * stdev * math.sqrt(FINANCIALS[p]["fe_lt"]))
        
        # Dual Math
        co_ns = (holding_cost + wacc_weekly * FINANCIALS[p]["ns_fob"]) * FINANCIALS[p]["ns_lt"]
        cr_ns = cu / (cu + co_ns)
        ss_ns = int(norm.ppf(cr_ns) * stdev * math.sqrt(FINANCIALS[p]["ns_lt"]))
        
        or_data.append({
            "Product": p,
            "Legacy Critical Ratio": f"{cr_fe*100:.1f}%",
            "Legacy SS Floor (10-Wk Risk)": ss_fe,
            "Dual-Sourcing Critical Ratio": f"{cr_ns*100:.1f}%",
            "Dual-Sourcing SS Floor (2-Wk Risk)": ss_ns,
            "Working Capital Units Released": ss_fe - ss_ns
        })
    st.table(pd.DataFrame(or_data))

with tab3:
    st.subheader("Operations: Base-Surge Container Sawtooth")
    view_prod = st.selectbox("Select Product to Graph:", ACTIVE_PRODUCTS)
    
    chart_data = [{"Week": w, "Metric": "Actual Customer Demand", "Units": int(DEMAND_ACTUAL[view_prod][w])} for w in WEEKS]
    for name, res in results.items():
        chart_data.extend([{"Week": w, "Metric": f"Inv ({name})", "Units": int(res["inv"][view_prod][w])} for w in WEEKS])
            
    c_df = pd.DataFrame(chart_data)
    domain = ["Actual Customer Demand", "Inv (Legacy (China Only))", "Inv (Optimized Dual-Sourcing)"]
    range_ = ['#FF4B4B', '#1f77b4', '#2ca02c']
    
    chart = alt.Chart(c_df).mark_line(strokeWidth=3).encode(
        x='Week:Q', y='Units:Q', color=alt.Color('Metric:N', scale=alt.Scale(domain=domain, range=range_)),
        strokeDash=alt.condition(alt.datum.Metric == 'Actual Customer Demand', alt.value([5, 5]), alt.value([0]))
    ).properties(height=450)
    
    # Calculate SS lines for the graph
    stdev_base = ACTIVE_DEMAND_PARAMS[view_prod]["std"]
    co_fe = (holding_cost + wacc_weekly * FINANCIALS[view_prod]["fe_fob"]) * FINANCIALS[view_prod]["fe_lt"]
    z_fe = norm.ppf(stockout_penalty / (stockout_penalty + co_fe))
    
    co_ns = (holding_cost + wacc_weekly * FINANCIALS[view_prod]["ns_fob"]) * FINANCIALS[view_prod]["ns_lt"]
    z_ns = norm.ppf(stockout_penalty / (stockout_penalty + co_ns))
    
    ss_leg_data, ss_dual_data = [], []
    for w in WEEKS:
        growth = (1 + y2_growth_ui) if w > 52 else 1
        ss_leg_data.append({'Week': w, 'Safety Stock (Legacy)': int(z_fe * stdev_base * growth * math.sqrt(FINANCIALS[view_prod]["fe_lt"]))})
        ss_dual_data.append({'Week': w, 'Safety Stock (Dual)': int(z_ns * stdev_base * growth * math.sqrt(FINANCIALS[view_prod]["ns_lt"]))})
    
    ss_chart_leg = alt.Chart(pd.DataFrame(ss_leg_data)).mark_line(color='#1f77b4', strokeDash=[2,2], opacity=0.5).encode(x='Week:Q', y='Safety Stock (Legacy):Q')
    ss_chart_dual = alt.Chart(pd.DataFrame(ss_dual_data)).mark_line(color='#2ca02c', strokeDash=[2,2], opacity=0.5).encode(x='Week:Q', y='Safety Stock (Dual):Q')
    
    st.altair_chart(chart + ss_chart_leg + ss_chart_dual, use_container_width=True)

with tab4:
    st.subheader("Download Complete CFO Audit Ledger")
    st.download_button("📥 Download CFO Audit Ledger (.xlsx)", data=generate_cfo_ledger(results, lbo_results), file_name="LBO_Audit_Ledger.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
