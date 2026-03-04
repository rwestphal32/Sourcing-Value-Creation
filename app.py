import streamlit as st
import pandas as pd
import numpy as np
import pulp
import io
import altair as alt
import math
from scipy.stats import norm

st.set_page_config(page_title="Strategy& Value Creation: 3-Statement LBO Twin", layout="wide")

st.title("🌍 PE Value Creation: The 100-Day Plan & 3-Statement Twin")
st.markdown("**Context:** Evaluating a 2-Year PE Hold. Simulating Network Optimization, Value Engineering, and Terms Optimization, resulting in a full GAAP 3-Statement CFO rollout.")

# --- 1. DEMO DATA (REDUCED NOISE TO REVEAL SEASONALITY) ---
WEEKS = list(range(1, 105)) 
DEFAULT_PRODUCTS = ["Smart Thermostat", "HD Security Camera", "Wi-Fi Mesh Router", "Smart Plug (4-Pack)"]

DEMAND_PARAMS = {
    "Smart Thermostat": {"mean": 2000, "std": 300},
    "HD Security Camera": {"mean": 3500, "std": 450},
    "Wi-Fi Mesh Router": {"mean": 1200, "std": 200},
    "Smart Plug (4-Pack)": {"mean": 5000, "std": 600}
}

DEFAULT_ECO = {
    "Smart Thermostat": {"price": 120.0, "unit_cbm": 0.005, "fe_fob": 35.0, "fe_lt": 10, "ns_fob": 37.0, "ns_lt": 2},
    "HD Security Camera": {"price": 85.0, "unit_cbm": 0.003, "fe_fob": 22.0, "fe_lt": 10, "ns_fob": 24.5, "ns_lt": 2},
    "Wi-Fi Mesh Router": {"price": 150.0, "unit_cbm": 0.015, "fe_fob": 45.0, "fe_lt": 10, "ns_fob": 48.0, "ns_lt": 2},
    "Smart Plug (4-Pack)": {"price": 30.0, "unit_cbm": 0.002, "fe_fob": 8.0, "fe_lt": 10, "ns_fob": 9.5, "ns_lt": 2}
}

FE_CONTAINER_CBM, FE_CONTAINER_COST = 68.0, 6500  
NS_TRUCK_CBM, NS_TRUCK_COST = 80.0, 2500      

# --- 2. DYNAMIC SEASONAL DEMAND GENERATOR ---
if 'demand_locked' not in st.session_state:
    st.session_state.demand_locked = False
    st.session_state.actual_demand = {}

def generate_stochastic_demand(products, params, y2_growth, seasonality):
    path = {}
    for p in products:
        mean, std = params[p]["mean"], params[p]["std"]
        path[p] = {}
        for w in WEEKS:
            season_idx = 1 + seasonality * math.sin(2 * math.pi * (w - 32) / 52)
            growth_multiplier = (1 + y2_growth) if w > 52 else 1
            path[p][w] = max(0, int(np.random.normal(mean * growth_multiplier * season_idx, std * growth_multiplier * season_idx)))
    st.session_state.actual_demand = path
    st.session_state.demand_locked = True

# --- 3. EXCEL EXPORT ENGINE ---
def generate_cfo_ledger(results_dict, lbo_metrics):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        pd.DataFrame([{"Strategy": n, **lbo} for n, lbo in lbo_metrics.items()]).to_excel(writer, sheet_name="LBO_Returns", index=False)
        for name, res in results_dict.items():
            prefix = "Legacy_" if "Legacy" in name else "Opt_"
            pd.DataFrame([{"Week": w, "China Containers": res["containers_fe"][w], "Poland Trucks": res["trucks_ns"][w], "Total Freight": res["cost_freight"][w]} for w in WEEKS]).to_excel(writer, sheet_name=f"{prefix}Logistics", index=False)
    return output.getvalue()

# --- 4. SIDEBAR CONTROLS ---
with st.sidebar:
    ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS, FINANCIALS = DEFAULT_PRODUCTS, DEMAND_PARAMS, DEFAULT_ECO

    st.header("Step 1: Market Dynamics")
    seasonality_ui = st.slider("Q4 Seasonal Peak Variance (%)", 0.0, 50.0, 30.0) / 100.0
    y2_growth_ui = st.slider("Year 2 Market Growth (%)", 0.0, 30.0, 10.0) / 100.0
    
    if st.button("🔒 Lock 104-Week Actuals", use_container_width=True):
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS, y2_growth_ui, seasonality_ui)
        st.success("Locked!")

    if not st.session_state.demand_locked:
        np.random.seed(42) 
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS, y2_growth_ui, seasonality_ui)
    
    st.markdown("---")
    st.header("Step 2: Strategy& 100-Day Plan")
    ve_savings = st.slider("Value Engineering BOM Reduction (%)", 0.0, 15.0, 5.0) / 100.0
    ve_dev_weeks = st.slider("VE Development Lag (Weeks)", 12, 52, 39)
    ve_investment = st.slider("VE One-Time Investment (£)", 0, 1000000, 250000, step=50000)
    dpo_days = st.slider("Accounts Payable (DPO Days)", 30, 120, 60)
    dso_days = st.slider("Accounts Receivable (DSO Days)", 30, 90, 45)
    
    st.markdown("---")
    st.header("Step 3: LBO Mechanics")
    with st.form("lbo_panel"):
        entry_multiple = st.slider("Exit Multiple (x EBITDA)", 6.0, 15.0, 10.0)
        debt_ratio = st.slider("Debt Funding Ratio (%)", 0.0, 80.0, 65.0) / 100.0
        interest_rate = st.slider("Debt Interest Rate (%)", 5.0, 15.0, 9.0) / 100.0
        st.subheader("Operational Constraints")
        tariff_rate = st.slider("China Import Tariff (%)", 0.0, 20.0, 8.0) / 100.0
        wacc_weekly = (st.slider("Cost of Capital (WACC %)", 5.0, 25.0, 15.0) / 100.0) / 52.0
        holding_cost = st.slider("UK 3PL Storage (£/unit/wk)", 0.05, 0.50, 0.35)
        stockout_penalty = st.slider("Lost Sale Penalty (£/unit)", 20, 150, 80)
        corp_tax = 0.25 
        submitted = st.form_submit_button("🚀 Run 3-Statement Optimizer")

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

    is_legacy = "Legacy" in strategy_type

    def get_fob(p, w, node):
        if is_legacy or w <= ve_dev_weeks: return FINANCIALS[p][f"{node}_fob"]
        return FINANCIALS[p][f"{node}_fob"] * (1 - ve_savings)

    for p in ACTIVE_PRODUCTS:
        cu = stockout_penalty
        co_fe_start = (holding_cost + wacc_weekly * FINANCIALS[p]["fe_fob"]) * FINANCIALS[p]["fe_lt"]
        z_fe_start = norm.ppf(cu / (cu + co_fe_start))
        start_season_idx = 1 + seasonality_ui * math.sin(2 * math.pi * (1 - 32) / 52)
        start_std = ACTIVE_DEMAND_PARAMS[p]["std"] * start_season_idx
        ss_legacy = int(z_fe_start * start_std * math.sqrt(FINANCIALS[p]["fe_lt"]))
        prob += inv[p][0] == int(ACTIVE_DEMAND_PARAMS[p]["mean"] * start_season_idx * 2) + ss_legacy

        for w in WEEKS:
            season_idx = 1 + seasonality_ui * math.sin(2 * math.pi * (w - 32) / 52)
            growth_multiplier = (1 + y2_growth_ui) if w > 52 else 1
            current_std = ACTIVE_DEMAND_PARAMS[p]["std"] * growth_multiplier * season_idx
            
            if is_legacy:
                co_fe = (holding_cost + wacc_weekly * get_fob(p, w, 'fe')) * FINANCIALS[p]["fe_lt"]
                ss_floor = int(norm.ppf(cu / (cu + co_fe)) * current_std * math.sqrt(FINANCIALS[p]["fe_lt"]))
            else:
                co_ns = (holding_cost + wacc_weekly * get_fob(p, w, 'ns')) * FINANCIALS[p]["ns_lt"]
                ss_floor = int(norm.ppf(cu / (cu + co_ns)) * current_std * math.sqrt(FINANCIALS[p]["ns_lt"]))

            prob += inv[p][w] >= ss_floor
            
            # Align arriving historical containers with the exact seasonality to prevent Day 1 shocks
            hist_season = 1 + seasonality_ui * math.sin(2 * math.pi * ((w - FINANCIALS[p]["fe_lt"]) - 32) / 52)
            arr_fe = order_fe[p][w - FINANCIALS[p]["fe_lt"]] if w > FINANCIALS[p]["fe_lt"] else int(ACTIVE_DEMAND_PARAMS[p]["mean"] * hist_season)
            arr_ns = order_ns[p][w - FINANCIALS[p]["ns_lt"]] if w > FINANCIALS[p]["ns_lt"] else 0

            if is_legacy: prob += order_ns[p][w] == 0
                
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
    cogs_fe = pulp.lpSum([order_fe[p][w] * (get_fob(p, w, 'fe') * (1+tariff_rate)) for p in ACTIVE_PRODUCTS for w in WEEKS])
    cogs_ns = pulp.lpSum([order_ns[p][w] * get_fob(p, w, 'ns') for p in ACTIVE_PRODUCTS for w in WEEKS])
    freight = pulp.lpSum([containers_fe[w] * FE_CONTAINER_COST + trucks_ns[w] * NS_TRUCK_COST for w in WEEKS])
    holding = pulp.lpSum([inv[p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in WEEKS])
    penalties = pulp.lpSum([shortage[p][w] * stockout_penalty for p in ACTIVE_PRODUCTS for w in WEEKS])
    salvage_value = pulp.lpSum([inv[p][104] * get_fob(p, 104, 'fe') * 0.90 for p in ACTIVE_PRODUCTS])
    
    ve_cost = 0 if is_legacy else ve_investment
    prob += (revenue + salvage_value) - (cogs_fe + cogs_ns + freight + holding + penalties + ve_cost)
    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=20, gapRel=0.03))
    
    def get_val(var): return var.varValue if var.varValue else 0
    return {
        "sales": {p: {w: int(get_val(sales[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "inv": {p: {w: int(get_val(inv[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "inv_pre_sale": {p: {w: int(get_val(inv[p][w]) + get_val(sales[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "inv_0": {p: int(get_val(inv[p][0])) for p in ACTIVE_PRODUCTS},
        "order_fe": {p: {w: int(get_val(order_fe[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "order_ns": {p: {w: int(get_val(order_ns[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "cost_freight": {w: (int(get_val(containers_fe[w])) * FE_CONTAINER_COST) + (int(get_val(trucks_ns[w])) * NS_TRUCK_COST) for w in WEEKS},
        "shortage": {p: {w: int(get_val(shortage[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS}
    }

# --- 6. LBO FINANCIAL ENGINE (GAAP COMPLIANT) ---
def generate_three_statements(res, is_baseline, entry_ebitda=None):
    def get_fob(p, w, node):
        if is_baseline or w <= ve_dev_weeks: return FINANCIALS[p][f"{node}_fob"]
        return FINANCIALS[p][f"{node}_fob"] * (1 - ve_savings)

    def get_ebitda_and_purchases(s_w, e_w, is_year_1=False):
        rev = sum([res["sales"][p][w] * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        
        purchases = sum([res["order_fe"][p][w] * (get_fob(p, w, 'fe') * (1+tariff_rate)) + res["order_ns"][p][w] * get_fob(p, w, 'ns') for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        
        fob_mult = 1 if is_baseline else (1 - ve_savings)
        inv_start_val = sum([res["inv"][p][s_w-1] * (FINANCIALS[p]["fe_fob"] * fob_mult) for p in ACTIVE_PRODUCTS]) if s_w > 1 else sum([res["inv_0"][p] * (FINANCIALS[p]["fe_fob"] * fob_mult) for p in ACTIVE_PRODUCTS])
        inv_end_val = sum([res["inv"][p][e_w-1] * (FINANCIALS[p]["fe_fob"] * fob_mult) for p in ACTIVE_PRODUCTS])
        
        # GAAP COGS: Matching Principle
        cogs = purchases - (inv_end_val - inv_start_val)
        
        freight = sum([res["cost_freight"][w] for w in range(s_w, e_w)])
        holding = sum([res["inv"][p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        short = sum([res["shortage"][p][w] * stockout_penalty for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        ve_opex = ve_investment if not is_baseline and is_year_1 else 0
        
        ebitda = rev - (cogs + freight + holding + short + ve_opex)
        return rev, cogs, purchases, freight + holding + short + ve_opex, ebitda

    y1_rev, y1_cogs, y1_purchases, y1_opex, y1_ebitda = get_ebitda_and_purchases(1, 53, True)
    y2_rev, y2_cogs, y2_purchases, y2_opex, y2_ebitda = get_ebitda_and_purchases(53, 105, False)

    dpo = 30 if is_baseline else dpo_days
    dso = 30 if is_baseline else dso_days
    fob_mult = 1 if is_baseline else (1 - ve_savings)
    
    inv_val_0 = sum([res["inv_0"][p] * (FINANCIALS[p]["fe_fob"] * fob_mult) for p in ACTIVE_PRODUCTS])
    inv_val_1 = sum([res["inv"][p][52] * (FINANCIALS[p]["fe_fob"] * fob_mult) for p in ACTIVE_PRODUCTS])
    inv_val_2 = sum([res["inv"][p][104] * (FINANCIALS[p]["fe_fob"] * fob_mult) for p in ACTIVE_PRODUCTS])

    ar_0 = (y1_rev / 365) * 30 
    ar_1 = (y1_rev / 365) * dso
    ar_2 = (y2_rev / 365) * dso
    
    # AP is calculated on Raw Purchases, not COGS
    ap_0 = (y1_purchases / 365) * 30
    ap_1 = (y1_purchases / 365) * dpo
    ap_2 = (y2_purchases / 365) * dpo

    nwc_0 = (inv_val_0 + ar_0) - ap_0
    nwc_1 = (inv_val_1 + ar_1) - ap_1
    nwc_2 = (inv_val_2 + ar_2) - ap_2

    entry_ev = (y1_ebitda if is_baseline else entry_ebitda) * entry_multiple
    starting_debt = entry_ev * debt_ratio
    entry_equity = entry_ev - starting_debt

    y1_interest = starting_debt * interest_rate
    y1_taxes = (y1_ebitda - y1_interest) * corp_tax if (y1_ebitda - y1_interest) > 0 else 0
    y1_fcf = y1_ebitda - y1_taxes - y1_interest - (nwc_1 - nwc_0)
    debt_1 = starting_debt - y1_fcf
    
    y2_interest = debt_1 * interest_rate
    y2_taxes = (y2_ebitda - y2_interest) * corp_tax if (y2_ebitda - y2_interest) > 0 else 0
    y2_fcf = y2_ebitda - y2_taxes - y2_interest - (nwc_2 - nwc_1)
    debt_2 = debt_1 - y2_fcf
    
    exit_ev = y2_ebitda * entry_multiple
    exit_equity = exit_ev - debt_2

    return {
        "IS": {"Y1 Rev": y1_rev, "Y1 COGS": -y1_cogs, "Y1 OPEX": -y1_opex, "Y1 EBITDA": y1_ebitda, "Y2 Rev": y2_rev, "Y2 COGS": -y2_cogs, "Y2 OPEX": -y2_opex, "Y2 EBITDA": y2_ebitda},
        "BS": {"Inv 0": inv_val_0, "AR 0": ar_0, "AP 0": ap_0, "Debt 0": starting_debt, "Equity 0": entry_equity, "Inv 2": inv_val_2, "AR 2": ar_2, "AP 2": ap_2, "Debt 2": debt_2, "Equity 2": exit_equity},
        "CF": {"Y1 FCF": y1_fcf, "Y2 FCF": y2_fcf, "MOIC": exit_equity / entry_equity if entry_equity > 0 else 0, "Exit EV": exit_ev}
    }

# --- 7. EXECUTION ---
with st.spinner("Analyzing Pre-Deal Baseline (Legacy)..."):
    res_leg = run_milp_optimizer("Legacy (China Only)")
    stmt_leg = generate_three_statements(res_leg, True)

with st.spinner("Executing Post-Deal 100-Day Plan..."):
    res_opt = run_milp_optimizer("100-Day Plan Optimized")
    stmt_opt = generate_three_statements(res_opt, False, stmt_leg["IS"]["Y1 EBITDA"])

# --- 8. DASHBOARDS ---
tab1, tab2, tab3 = st.tabs(["📊 The 3-Statement LBO Model", "📦 Seasonal Base-Surge Sawtooth", "📈 Value Creation Bridge"])

with tab1:
    st.subheader("CFO View: The GAAP 3-Statement Financial Rollout")
    
    st.markdown("### 1. Income Statement (Hold Period)")
    is_data = {
        "Line Item": ["Revenue", "COGS (GAAP Matching)", "OPEX (Holding/Freight/VE Invest)", "EBITDA"],
        "Legacy Y1": [f"£{stmt_leg['IS']['Y1 Rev']:,.0f}", f"£{stmt_leg['IS']['Y1 COGS']:,.0f}", f"£{stmt_leg['IS']['Y1 OPEX']:,.0f}", f"£{stmt_leg['IS']['Y1 EBITDA']:,.0f}"],
        "Legacy Y2": [f"£{stmt_leg['IS']['Y2 Rev']:,.0f}", f"£{stmt_leg['IS']['Y2 COGS']:,.0f}", f"£{stmt_leg['IS']['Y2 OPEX']:,.0f}", f"£{stmt_leg['IS']['Y2 EBITDA']:,.0f}"],
        "Opt 100-Day Y1": [f"£{stmt_opt['IS']['Y1 Rev']:,.0f}", f"£{stmt_opt['IS']['Y1 COGS']:,.0f}", f"£{stmt_opt['IS']['Y1 OPEX']:,.0f}", f"£{stmt_opt['IS']['Y1 EBITDA']:,.0f}"],
        "Opt 100-Day Y2": [f"£{stmt_opt['IS']['Y2 Rev']:,.0f}", f"£{stmt_opt['IS']['Y2 COGS']:,.0f}", f"£{stmt_opt['IS']['Y2 OPEX']:,.0f}", f"£{stmt_opt['IS']['Y2 EBITDA']:,.0f}"]
    }
    st.table(pd.DataFrame(is_data).set_index("Line Item"))

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 2. Balance Sheet (Entry vs Exit)")
        bs_data = {
            "Line Item": ["Assets: Inventory", "Assets: Accts Receivable", "Liabilities: Accts Payable", "Liabilities: LBO Debt", "Total Equity"],
            "Legacy (Exit Y2)": [f"£{stmt_leg['BS']['Inv 2']:,.0f}", f"£{stmt_leg['BS']['AR 2']:,.0f}", f"£{-stmt_leg['BS']['AP 2']:,.0f}", f"£{-stmt_leg['BS']['Debt 2']:,.0f}", f"£{stmt_leg['BS']['Equity 2']:,.0f}"],
            "Opt 100-Day (Exit Y2)": [f"£{stmt_opt['BS']['Inv 2']:,.0f}", f"£{stmt_opt['BS']['AR 2']:,.0f}", f"£{-stmt_opt['BS']['AP 2']:,.0f}", f"£{-stmt_opt['BS']['Debt 2']:,.0f}", f"£{stmt_opt['BS']['Equity 2']:,.0f}"]
        }
        st.table(pd.DataFrame(bs_data).set_index("Line Item"))
        
    with col2:
        st.markdown("### 3. Cash Flow & Returns")
        cf_data = {
            "Line Item": ["Free Cash Flow (Y1)", "Free Cash Flow (Y2)", "Exit Enterprise Value", "Equity MOIC"],
            "Legacy": [f"£{stmt_leg['CF']['Y1 FCF']:,.0f}", f"£{stmt_leg['CF']['Y2 FCF']:,.0f}", f"£{stmt_leg['CF']['Exit EV']:,.0f}", f"{stmt_leg['CF']['MOIC']:.2f}x"],
            "Opt 100-Day": [f"£{stmt_opt['CF']['Y1 FCF']:,.0f}", f"£{stmt_opt['CF']['Y2 FCF']:,.0f}", f"£{stmt_opt['CF']['Exit EV']:,.0f}", f"{stmt_opt['CF']['MOIC']:.2f}x"]
        }
        st.table(pd.DataFrame(cf_data).set_index("Line Item"))

with tab2:
    st.subheader("Operations: Available Pre-Sale Inventory Sawtooth")
    view_prod = st.selectbox("Select Product to Graph:", ACTIVE_PRODUCTS)
    
    chart_data = [{"Week": w, "Metric": "Actual Seasonal Demand", "Units": int(DEMAND_ACTUAL[view_prod][w])} for w in WEEKS]
    for name, res in {"Legacy (Baseline)": res_leg, "Strategy& 100-Day Plan": res_opt}.items():
        chart_data.extend([{"Week": w, "Metric": f"Available Inv ({name})", "Units": int(res["inv_pre_sale"][view_prod][w])} for w in WEEKS])
            
    c_df = pd.DataFrame(chart_data)
    domain = ["Actual Seasonal Demand", "Available Inv (Legacy (Baseline))", "Available Inv (Strategy& 100-Day Plan)"]
    range_ = ['#FF4B4B', '#1f77b4', '#2ca02c']
    
    chart = alt.Chart(c_df).mark_line(strokeWidth=3).encode(
        x='Week:Q', y='Units:Q', color=alt.Color('Metric:N', scale=alt.Scale(domain=domain, range=range_)),
        strokeDash=alt.condition(alt.datum.Metric == 'Actual Seasonal Demand', alt.value([5, 5]), alt.value([0]))
    ).properties(height=450)
    st.altair_chart(chart, use_container_width=True)
    st.caption("**Insight:** The graph plots *Available Inventory* (Starting Inventory + Incoming Trucks) against Weekly Demand. Notice how the green 100-Day Plan perfectly rides the red demand wave, flawlessly executing JIT delivery without holding millions in dead stock.")

with tab3:
    st.subheader("The PE Value Creation Bridge")
    bridge_data = {
        "Value Driver": ["1. Entry Equity", "2. Total FCF Generated", "3. Debt Paid Down", "4. Exit Enterprise Value", "5. Remaining Debt Subtracted", "FINAL EXIT EQUITY VALUE"],
        "Legacy": [f"£{stmt_leg['BS']['Equity 0']:,.0f}", f"£{stmt_leg['CF']['Y1 FCF'] + stmt_leg['CF']['Y2 FCF']:,.0f}", f"£{stmt_leg['BS']['Debt 0'] - stmt_leg['BS']['Debt 2']:,.0f}", f"£{stmt_leg['CF']['Exit EV']:,.0f}", f"-£{stmt_leg['BS']['Debt 2']:,.0f}", f"£{stmt_leg['BS']['Equity 2']:,.0f}"],
        "Opt 100-Day Plan": [f"£{stmt_opt['BS']['Equity 0']:,.0f}", f"£{stmt_opt['CF']['Y1 FCF'] + stmt_opt['CF']['Y2 FCF']:,.0f}", f"£{stmt_opt['BS']['Debt 0'] - stmt_opt['BS']['Debt 2']:,.0f}", f"£{stmt_opt['CF']['Exit EV']:,.0f}", f"-£{stmt_opt['BS']['Debt 2']:,.0f}", f"£{stmt_opt['BS']['Equity 2']:,.0f}"]
    }
    st.table(pd.DataFrame(bridge_data).set_index("Value Driver"))
