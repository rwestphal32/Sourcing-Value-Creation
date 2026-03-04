import streamlit as st
import pandas as pd
import numpy as np
import pulp
import io
import altair as alt
import math

st.set_page_config(page_title="Strategy& Value Creation: Sourcing Twin", layout="wide")

st.title("🌍 PE Value Creation: Two-Stage S&OP & LBO Twin")
st.markdown("**Context:** A post-deal Private Equity environment. The model uses a Two-Stage engine: An MILP optimizer sets the baseline Far-East container schedule based on the *Forecast*, and a Newsvendor Simulation reacts to the *Stochastic Reality* using Nearshore trucks.")

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

# --- 2. FORECAST VS ACTUAL DEMAND GENERATOR ---
if 'demand_locked' not in st.session_state:
    st.session_state.demand_locked = False
    st.session_state.actual_demand = {}

def generate_stochastic_demand(products, params):
    path = {}
    for p in products:
        mean, std = params[p]["mean"], params[p]["std"]
        path[p] = {}
        for w in WEEKS:
            path[p][w] = max(0, int(np.random.normal(mean, std)))
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
            log_data = [{"Week": w, "China Containers": res["logistics"]["fe"][w], "Poland Trucks": res["logistics"]["ns"][w], "Total Freight": res["logistics"]["cost"][w]} for w in WEEKS]
            pd.DataFrame(log_data).to_excel(writer, sheet_name=f"{prefix}Logistics", index=False)
            
            for p in ACTIVE_PRODUCTS:
                prod_data = [{"Week": w, "FCST": DEMAND_FCST[p][w], "ACTUAL": DEMAND_ACTUAL[p][w], "Sales": res["sales"][p][w], "Lost Sales": res["shortage"][p][w], "Ending Inv": res["inv"][p][w], "Base FE Order": res["order_fe_plan"][p][w], "Reactive NS Order": res["order_ns_react"][p][w]} for w in WEEKS]
                pd.DataFrame(prod_data).to_excel(writer, sheet_name=f"{prefix}{p[:20]}".replace(" ", ""), index=False)
    return output.getvalue()

# --- 4. SIDEBAR CONTROLS ---
with st.sidebar:
    ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS, FINANCIALS = DEFAULT_PRODUCTS, DEMAND_PARAMS, DEFAULT_ECO

    st.header("Step 1: Lock Market Volatility")
    if st.button("🔒 Lock 104-Week Actuals", use_container_width=True):
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS)
        st.success("Locked!")

    if not st.session_state.demand_locked:
        np.random.seed(42) 
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS)
    
    st.markdown("---")
    st.header("Step 2: LBO Mechanics")
    with st.form("lbo_panel"):
        y2_growth = st.slider("Year 2 Forecasted Growth (%)", 0.0, 30.0, 10.0) / 100.0
        entry_multiple = st.slider("Exit Multiple (x EBITDA)", 6.0, 15.0, 9.0)
        debt_ratio = st.slider("Debt Funding Ratio (%)", 0.0, 80.0, 60.0) / 100.0
        interest_rate = st.slider("Debt Interest Rate (%)", 5.0, 15.0, 9.0) / 100.0
        
        st.subheader("Operational Policy Levers")
        ss_weeks = st.slider("Strategic Safety Stock (Weeks)", 1.0, 4.0, 2.0)
        tariff_rate = st.slider("China Import Tariff (%)", 0.0, 20.0, 8.0) / 100.0
        wacc_weekly = (st.slider("WACC (%)", 5.0, 25.0, 12.0) / 100.0) / 52.0
        holding_cost = st.slider("UK 3PL Storage (£/unit/wk)", 0.05, 0.50, 0.15)
        stockout_penalty = st.slider("Lost Sale Penalty (£/unit)", 20, 150, 80)
        corp_tax = 0.25 
        submitted = st.form_submit_button("🚀 Run Two-Stage S&OP Engine")

# Separate Forecast vs Actuals
DEMAND_ACTUAL = st.session_state.actual_demand
DEMAND_FCST = {p: {w: int(ACTIVE_DEMAND_PARAMS[p]["mean"] * (1 + y2_growth if w > 52 else 1)) for w in WEEKS} for p in ACTIVE_PRODUCTS}

# --- 5. STAGE 1: MILP MASTER PLANNER (Forecast Only) ---
def build_base_plan():
    prob = pulp.LpProblem("Base_MPS", pulp.LpMinimize)
    order_fe = pulp.LpVariable.dicts("Order_FE", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    containers_fe = pulp.LpVariable.dicts("Containers_FE", WEEKS, lowBound=0, cat='Integer')
    inv = pulp.LpVariable.dicts("Inv", (ACTIVE_PRODUCTS, [0] + WEEKS), lowBound=0, cat='Integer')

    for p in ACTIVE_PRODUCTS:
        prob += inv[p][0] == int(DEMAND_FCST[p][1] * (FINANCIALS[p]["fe_lt"] + ss_weeks))
        
        for w in WEEKS:
            arr_fe = order_fe[p][w - FINANCIALS[p]["fe_lt"]] if w > FINANCIALS[p]["fe_lt"] else DEMAND_FCST[p][w]
            prob += inv[p][w] == inv[p][w-1] + arr_fe - DEMAND_FCST[p][w]
            prob += inv[p][w] >= int(DEMAND_FCST[p][w] * ss_weeks) # Baseline safety stock
            if w > 104 - FINANCIALS[p]["fe_lt"]: prob += order_fe[p][w] == 0

    for w in WEEKS:
        prob += pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS]) <= containers_fe[w] * FE_CONTAINER_CBM

    holding = pulp.lpSum([inv[p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in WEEKS])
    freight = pulp.lpSum([containers_fe[w] * FE_CONTAINER_COST for w in WEEKS])
    prob += holding + freight
    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=10))
    
    return {p: {w: int(order_fe[p][w].varValue if order_fe[p][w].varValue else 0) for w in WEEKS} for p in ACTIVE_PRODUCTS}

# --- 6. STAGE 2: EXECUTION SIMULATION (Stochastic Actuals & Newsvendor Logic) ---
def execute_sop_simulation(strategy_type, base_fe_plan):
    sim_inv = {p: {0: int(DEMAND_FCST[p][1] * (FINANCIALS[p]["fe_lt"] + ss_weeks))} for p in ACTIVE_PRODUCTS}
    sim_sales = {p: {} for p in ACTIVE_PRODUCTS}
    sim_shortage = {p: {} for p in ACTIVE_PRODUCTS}
    sim_ns_react = {p: {w: 0 for w in WEEKS} for p in ACTIVE_PRODUCTS}
    
    # Walk through time week by week
    for w in WEEKS:
        for p in ACTIVE_PRODUCTS:
            arr_fe = base_fe_plan[p][w - FINANCIALS[p]["fe_lt"]] if w > FINANCIALS[p]["fe_lt"] else DEMAND_FCST[p][w]
            arr_ns = sim_ns_react[p][w - FINANCIALS[p]["ns_lt"]] if w > FINANCIALS[p]["ns_lt"] else 0
            
            curr_inv = sim_inv[p][w-1] + arr_fe + arr_ns
            actual_demand = DEMAND_ACTUAL[p][w]
            
            sold = min(curr_inv, actual_demand)
            sim_sales[p][w] = sold
            sim_shortage[p][w] = actual_demand - sold
            sim_inv[p][w] = curr_inv - sold
            
            # NEWSVENDOR AGILE CHASE LOGIC (Dual-Sourcing Only)
            if "Dual" in strategy_type and w <= 104 - FINANCIALS[p]["ns_lt"]:
                # What is our pipeline for the next 2 weeks?
                pipe_fe = sum([base_fe_plan[p][kw - FINANCIALS[p]["fe_lt"]] for kw in range(w+1, w+3) if kw > FINANCIALS[p]["fe_lt"]])
                pipe_ns = sum([sim_ns_react[p][kw - FINANCIALS[p]["ns_lt"]] for kw in range(w+1, w+3) if kw > FINANCIALS[p]["ns_lt"]])
                
                exp_inv = sim_inv[p][w] + pipe_fe + pipe_ns - (DEMAND_FCST[p][w+1] + DEMAND_FCST[p][w+2])
                
                # Z-Score (1.645 = 95% Service Level) * StdDev * sqrt(LeadTime)
                volatility_ss = 1.645 * ACTIVE_DEMAND_PARAMS[p]["std"] * math.sqrt(FINANCIALS[p]["ns_lt"])
                policy_ss = DEMAND_FCST[p][w] * ss_weeks
                target_ip = int(volatility_ss + policy_ss)
                
                if exp_inv < target_ip:
                    sim_ns_react[p][w] = target_ip - int(exp_inv)

    # Calculate Financials & Container Yields post-simulation
    containers_fe, trucks_ns, cost_freight = {}, {}, {}
    for w in WEEKS:
        cbm_fe = sum([base_fe_plan[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS])
        containers_fe[w] = int(np.ceil(cbm_fe / FE_CONTAINER_CBM))
        cbm_ns = sum([sim_ns_react[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS])
        trucks_ns[w] = int(np.ceil(cbm_ns / NS_TRUCK_CBM))
        cost_freight[w] = (containers_fe[w] * FE_CONTAINER_COST) + (trucks_ns[w] * NS_TRUCK_COST)

    return {
        "sales": sim_sales, "shortage": sim_shortage, "inv": sim_inv, 
        "order_fe_plan": base_fe_plan, "order_ns_react": sim_ns_react,
        "logistics": {"fe": containers_fe, "ns": trucks_ns, "cost": cost_freight}
    }

# --- 7. LBO FINANCIAL ENGINE ---
def calc_lbo(res, is_baseline, entry_ebitda=None):
    def get_ebitda(s_w, e_w):
        rev = sum([res["sales"][p][w] * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        cogs = sum([res["order_fe_plan"][p][w] * (FINANCIALS[p]["fe_fob"] * (1+tariff_rate)) + res["order_ns_react"][p][w] * FINANCIALS[p]["ns_fob"] for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        freight = sum([res["logistics"]["cost"][w] for w in range(s_w, e_w)])
        holding = sum([res["inv"][p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        short = sum([res["shortage"][p][w] * stockout_penalty for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        return rev - (cogs + freight + holding + short)

    y1_ebitda, y2_ebitda = get_ebitda(1, 53), get_ebitda(53, 105)
    
    start_nwc = sum([res["inv"][p][0] * FINANCIALS[p]["fe_fob"] for p in ACTIVE_PRODUCTS])
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
    # Add terminal salvage value to Exit EV
    salvage = sum([res["inv"][p][104] * FINANCIALS[p]["fe_fob"] * 0.9 for p in ACTIVE_PRODUCTS])
    exit_equity = (exit_ev + salvage) - ending_debt
    
    return {"entry_ev": entry_ev, "starting_debt": starting_debt, "entry_equity": entry_equity, "y1_ebitda": y1_ebitda, "y1_delta_nwc": y1_nwc-start_nwc, "y1_fcf": y1_fcf, "y2_ebitda": y2_ebitda, "y2_delta_nwc": y2_nwc-y1_nwc, "y2_fcf": y2_fcf, "exit_ev": exit_ev, "ending_debt": ending_debt, "exit_equity": exit_equity, "moic": exit_equity / entry_equity if entry_equity > 0 else 0}

# --- 8. EXECUTION ---
with st.spinner("Generating MILP Master Production Schedule (Base Plan)..."):
    master_fe_plan = build_base_plan()

with st.spinner("Simulating Stochastic Reality: Legacy China Strategy..."):
    res_leg = execute_sop_simulation("Legacy", master_fe_plan)
    lbo_leg = calc_lbo(res_leg, True)

with st.spinner("Simulating Stochastic Reality: Dual-Sourcing Z-Score Chase..."):
    res_dual = execute_sop_simulation("Dual", master_fe_plan)
    lbo_dual = calc_lbo(res_dual, False, lbo_leg["y1_ebitda"])

results = {"Legacy (China Only)": res_leg, "Dual-Sourcing S&OP": res_dual}
lbo_results = {"Legacy (China Only)": lbo_leg, "Dual-Sourcing S&OP": lbo_dual}

# --- 9. DASHBOARDS ---
tab1, tab2, tab3, tab4 = st.tabs(["🚀 LBO Return Multiples", "💸 FCF Waterfall", "📦 Real-World S&OP Sawtooth", "📥 CFO Audit Ledger"])

with tab1:
    st.subheader("The Deal Scorecard: Multiple on Invested Capital (MOIC)")
    cols = st.columns(2)
    for i, (name, lbo) in enumerate(lbo_results.items()):
        with cols[i]:
            st.markdown(f"### {name}")
            st.metric("Total Equity MOIC", f"{lbo['moic']:.2f}x")
            st.metric("Exit Enterprise Value", f"£{lbo['exit_ev']:,.0f}")
            st.metric("Total Free Cash Flow Generated", f"£{lbo['y1_fcf'] + lbo['y2_fcf']:,.0f}")

with tab2:
    st.subheader("Debt & Cash Flow Waterfall (2-Year Hold)")
    waterfall_data = [{"Strategy": n, "1. PE Entry EBITDA": f"£{lbo_leg['y1_ebitda']:,.0f}", "2. Entry Debt": f"£{l['starting_debt']:,.0f}", "3. Y1 FCF": f"£{l['y1_fcf']:,.0f}", "4. Y1 NWC Cash Trapped": f"£{-l['y1_delta_nwc']:,.0f}", "5. Y2 FCF": f"£{l['y2_fcf']:,.0f}", "6. Y2 NWC Cash Trapped": f"£{-l['y2_delta_nwc']:,.0f}", "7. Remaining Debt": f"£{l['ending_debt']:,.0f}", "8. Final Exit EBITDA": f"£{l['y2_ebitda']:,.0f}"} for n, l in lbo_results.items()]
    st.table(pd.DataFrame(waterfall_data).set_index("Strategy").T)

with tab3:
    st.subheader("Operations: Two-Stage S&OP Volatility Execution")
    view_prod = st.selectbox("Select Product to Graph:", ACTIVE_PRODUCTS)
    
    chart_data = [{"Week": w, "Metric": "Actual Customer Demand", "Units": int(DEMAND_ACTUAL[view_prod][w])} for w in WEEKS]
    for name, res in results.items():
        chart_data.extend([{"Week": w, "Metric": f"Inv ({name})", "Units": int(res["inv"][view_prod][w])} for w in WEEKS])
            
    c_df = pd.DataFrame(chart_data)
    domain = ["Actual Customer Demand", "Inv (Legacy (China Only))", "Inv (Dual-Sourcing S&OP)"]
    range_ = ['#FF4B4B', '#1f77b4', '#2ca02c']
    
    chart = alt.Chart(c_df).mark_line(strokeWidth=3).encode(
        x='Week:Q', y='Units:Q', color=alt.Color('Metric:N', scale=alt.Scale(domain=domain, range=range_)),
        strokeDash=alt.condition(alt.datum.Metric == 'Actual Customer Demand', alt.value([5, 5]), alt.value([0]))
    ).properties(height=450)
    
    ss_line = alt.Chart(pd.DataFrame({'y': [int(DEMAND_FCST[view_prod][1] * ss_weeks)]})).mark_rule(color='red', strokeDash=[2,2]).encode(y='y:Q')
    st.altair_chart(chart + ss_line, use_container_width=True)

with tab4:
    st.subheader("Download Complete CFO Audit Ledger")
    st.download_button("📥 Download CFO Audit Ledger (.xlsx)", data=generate_cfo_ledger(results, lbo_results), file_name="LBO_Audit_Ledger.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
