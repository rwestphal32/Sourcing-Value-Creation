import streamlit as st
import pandas as pd
import numpy as np
import pulp
import io
import altair as alt
import math
import plotly.graph_objects as go
from scipy.stats import norm

st.set_page_config(page_title="Strategy& Value Creation: 3-Statement LBO Twin", layout="wide")

st.title("🌍 PE Value Creation: The 100-Day Plan & 3-Statement Twin")
st.markdown("**Context:** Evaluating a 2-Year PE Hold. Simulating Network Optimization, Value Engineering, and Terms Optimization to generate a GAAP-compliant 3-Statement CFO rollout.")

# --- 1. FALLBACK DEMO DATA ---
WEEKS = list(range(1, 105)) 

DEFAULT_PRODUCTS = ["Smart Thermostat", "HD Security Camera", "Wi-Fi Mesh Router", "Smart Plug (4-Pack)"]

DEMAND_PARAMS = {
    "Smart Thermostat": {"mean": 2000, "std": 300},
    "HD Security Camera": {"mean": 3500, "std": 450},
    "Wi-Fi Mesh Router": {"mean": 1200, "std": 200},
    "Smart Plug (4-Pack)": {"mean": 5000, "std": 600}
}

DEFAULT_ECO = {
    "Smart Thermostat": {"price": 120.0, "unit_cbm": 0.005, "fe_fob": 32.0, "fe_lt": 10, "fe_moq": 3000, "ns_fob": 37.0, "ns_lt": 2, "ns_moq": 500},
    "HD Security Camera": {"price": 85.0, "unit_cbm": 0.003, "fe_fob": 18.0, "fe_lt": 10, "fe_moq": 4000, "ns_fob": 24.0, "ns_lt": 2, "ns_moq": 1000},
    "Wi-Fi Mesh Router": {"price": 150.0, "unit_cbm": 0.015, "fe_fob": 38.0, "fe_lt": 10, "fe_moq": 2000, "ns_fob": 50.0, "ns_lt": 2, "ns_moq": 500},
    "Smart Plug (4-Pack)": {"price": 30.0, "unit_cbm": 0.002, "fe_fob": 6.5, "fe_lt": 10, "fe_moq": 8000, "ns_fob": 8.0, "ns_lt": 2, "ns_moq": 2000}
}

FE_CONTAINER_CBM, FE_CONTAINER_COST = 68.0, 6500  
FE_LCL_CBM_COST = 140.0 
NS_TRUCK_CBM, NS_TRUCK_COST = 80.0, 2500      
BIG_M = 1000000

# --- 2. FILE UPLOAD & TEMPLATE ENGINE ---
def generate_upload_template():
    data = {
        "Product": ["Smart Thermostat", "HD Security Camera", "Wi-Fi Mesh Router", "Smart Plug (4-Pack)"],
        "Mean_Demand": [2000, 3500, 1200, 5000],
        "Std_Dev": [300, 450, 200, 600],
        "Sale_Price": [120.0, 85.0, 150.0, 30.0],
        "Unit_CBM": [0.005, 0.003, 0.015, 0.002],
        "China_FOB": [32.0, 18.0, 38.0, 6.5],
        "China_LT_Weeks": [10, 10, 10, 10],
        "China_MOQ": [3000, 4000, 2000, 8000],
        "Poland_FOB": [37.0, 24.0, 50.0, 8.0],
        "Poland_LT_Weeks": [2, 2, 2, 2],
        "Poland_MOQ": [500, 1000, 500, 2000]
    }
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        pd.DataFrame(data).to_excel(writer, sheet_name="SKU_Data", index=False)
    return output.getvalue()

def process_uploaded_file(df):
    custom_products = df["Product"].tolist()
    custom_demand = {}
    custom_eco = {}
    for _, row in df.iterrows():
        p = row["Product"]
        custom_demand[p] = {"mean": row["Mean_Demand"], "std": row["Std_Dev"]}
        custom_eco[p] = {
            "price": row["Sale_Price"], "unit_cbm": row["Unit_CBM"],
            "fe_fob": row["China_FOB"], "fe_lt": row["China_LT_Weeks"], "fe_moq": row["China_MOQ"],
            "ns_fob": row["Poland_FOB"], "ns_lt": row["Poland_LT_Weeks"], "ns_moq": row["Poland_MOQ"]
        }
    return custom_products, custom_demand, custom_eco

# --- 3. SESSION STATE INITIALIZATION ---
if 'demand_locked' not in st.session_state:
    st.session_state.demand_locked = False
if 'actual_demand' not in st.session_state:
    st.session_state.actual_demand = {}
if 'last_uploaded_file' not in st.session_state:
    st.session_state.last_uploaded_file = None
if 'custom_products' not in st.session_state:
    st.session_state.custom_products = DEFAULT_PRODUCTS
if 'custom_demand' not in st.session_state:
    st.session_state.custom_demand = DEMAND_PARAMS
if 'custom_eco' not in st.session_state:
    st.session_state.custom_eco = DEFAULT_ECO

def generate_stochastic_demand(products, params, y2_growth, seasonality):
    path = {}
    for p in products:
        path[p] = {}
        for w in WEEKS:
            season_idx = 1 + seasonality * math.sin(2 * math.pi * (w - 32) / 52)
            growth_multiplier = (1 + y2_growth) if w > 52 else 1
            path[p][w] = max(0, int(np.random.normal(params[p]["mean"] * growth_multiplier * season_idx, params[p]["std"] * growth_multiplier * season_idx)))
    st.session_state.actual_demand = path
    st.session_state.demand_locked = True

# --- 4. SIDEBAR CONTROLS ---
with st.sidebar:
    st.header("Step 1: Data Ingestion")
    st.download_button("📥 Download Excel Template", data=generate_upload_template(), file_name="PortCo_Data_Template.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    
    uploaded_file = st.file_uploader("Upload PortCo SKU Data (.xlsx)", type=["xlsx"])
    
    if uploaded_file is not None:
        if st.session_state.last_uploaded_file != uploaded_file.name:
            df = pd.read_excel(uploaded_file)
            st.session_state.custom_products, st.session_state.custom_demand, st.session_state.custom_eco = process_uploaded_file(df)
            st.session_state.last_uploaded_file = uploaded_file.name
            st.session_state.demand_locked = False 
            
        ACTIVE_PRODUCTS = st.session_state.custom_products
        ACTIVE_DEMAND_PARAMS = st.session_state.custom_demand
        FINANCIALS = st.session_state.custom_eco
        st.success(f"Loaded {len(ACTIVE_PRODUCTS)} SKUs.")
    else:
        ACTIVE_PRODUCTS = st.session_state.custom_products
        ACTIVE_DEMAND_PARAMS = st.session_state.custom_demand
        FINANCIALS = st.session_state.custom_eco

    st.markdown("---")
    st.header("Step 2: Market Dynamics")
    seasonality_ui = st.slider("Q4 Seasonal Peak Variance (%)", 0.0, 50.0, 30.0) / 100.0
    y2_growth_ui = st.slider("Year 2 Market Growth (%)", 0.0, 30.0, 10.0) / 100.0
    
    if st.button("🔒 Regenerate & Lock Demand", use_container_width=True):
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS, y2_growth_ui, seasonality_ui)
        st.success("Demand path locked!")

    if not st.session_state.demand_locked:
        np.random.seed(42) 
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS, y2_growth_ui, seasonality_ui)
    
    st.markdown("---")
    st.header("Step 3: Strategy& 100-Day Plan")
    ve_savings = st.slider("Value Engineering BOM Reduction (%)", 0.0, 15.0, 5.0) / 100.0
    ve_dev_weeks = st.slider("VE Development Lag (Weeks)", 12, 52, 39)
    ve_investment = st.slider("VE One-Time Investment (£)", 0, 1000000, 250000, step=50000)
    dpo_days = st.slider("Accounts Payable (DPO Days)", 30, 120, 60)
    dso_days = st.slider("Accounts Receivable (DSO Days)", 30, 90, 45)
    
    st.markdown("---")
    st.header("Step 4: LBO Mechanics")
    with st.form("lbo_panel"):
        entry_multiple = st.slider("Exit Multiple (x EBITDA)", 6.0, 15.0, 10.0)
        debt_ratio = st.slider("Debt Funding Ratio (%)", 0.0, 80.0, 65.0) / 100.0
        interest_rate = st.slider("Debt Interest Rate (%)", 5.0, 15.0, 9.0) / 100.0
        
        st.subheader("P&L Constraints")
        sga_margin = st.slider("SG&A Overhead (% of Rev)", 10.0, 40.0, 22.0) / 100.0
        tariff_rate = st.slider("China Import Tariff (%)", 0.0, 20.0, 8.0) / 100.0
        
        st.subheader("Operational Constraints")
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
    
    order_fe_bin = pulp.LpVariable.dicts("FE_Bin", (ACTIVE_PRODUCTS, WEEKS), cat='Binary')
    order_ns_bin = pulp.LpVariable.dicts("NS_Bin", (ACTIVE_PRODUCTS, WEEKS), cat='Binary')
    
    containers_fe = pulp.LpVariable.dicts("Containers_FE", WEEKS, lowBound=0, cat='Integer')
    lcl_fe = pulp.LpVariable.dicts("LCL_FE", WEEKS, lowBound=0, cat='Continuous')
    trucks_ns = pulp.LpVariable.dicts("Trucks_NS", WEEKS, lowBound=0, cat='Continuous')
    
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
        
        prob += inv[p][0] == ss_legacy + int(ACTIVE_DEMAND_PARAMS[p]["mean"] * start_season_idx * 0.5)

        for w in WEEKS:
            prob += order_fe[p][w] >= FINANCIALS[p]["fe_moq"] * order_fe_bin[p][w]
            prob += order_fe[p][w] <= BIG_M * order_fe_bin[p][w]
            
            prob += order_ns[p][w] >= FINANCIALS[p]["ns_moq"] * order_ns_bin[p][w]
            prob += order_ns[p][w] <= BIG_M * order_ns_bin[p][w]

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
            
            hist_season = 1 + seasonality_ui * math.sin(2 * math.pi * ((w - FINANCIALS[p]["fe_lt"]) - 32) / 52)
            expected_demand = int(ACTIVE_DEMAND_PARAMS[p]["mean"] * hist_season)
            arr_fe = order_fe[p][w - FINANCIALS[p]["fe_lt"]] if w > FINANCIALS[p]["fe_lt"] else expected_demand
            arr_ns = order_ns[p][w - FINANCIALS[p]["ns_lt"]] if w > FINANCIALS[p]["ns_lt"] else 0

            if is_legacy: 
                prob += order_ns[p][w] == 0
                prob += order_ns_bin[p][w] == 0
                
            prob += inv[p][w] == inv[p][w-1] + arr_fe + arr_ns - sales[p][w]
            prob += sales[p][w] <= DEMAND_ACTUAL[p][w]
            prob += sales[p][w] <= inv[p][w-1] + arr_fe + arr_ns
            prob += shortage[p][w] == DEMAND_ACTUAL[p][w] - sales[p][w]
            
            if w > 104 - FINANCIALS[p]["fe_lt"]: 
                prob += order_fe[p][w] == 0
                prob += order_fe_bin[p][w] == 0
            if w > 104 - FINANCIALS[p]["ns_lt"]: 
                prob += order_ns[p][w] == 0
                prob += order_ns_bin[p][w] == 0

    for w in WEEKS:
        prob += pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS]) <= containers_fe[w] * FE_CONTAINER_CBM + lcl_fe[w]
        prob += pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS]) <= trucks_ns[w] * NS_TRUCK_CBM

    revenue = pulp.lpSum([sales[p][w] * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    purchases_fe = pulp.lpSum([order_fe[p][w] * (get_fob(p, w, 'fe') * (1+tariff_rate)) for p in ACTIVE_PRODUCTS for w in WEEKS])
    purchases_ns = pulp.lpSum([order_ns[p][w] * get_fob(p, w, 'ns') for p in ACTIVE_PRODUCTS for w in WEEKS])
    freight = pulp.lpSum([containers_fe[w] * FE_CONTAINER_COST + lcl_fe[w] * FE_LCL_CBM_COST + trucks_ns[w] * NS_TRUCK_COST for w in WEEKS])
    holding = pulp.lpSum([inv[p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in WEEKS])
    penalties = pulp.lpSum([shortage[p][w] * stockout_penalty for p in ACTIVE_PRODUCTS for w in WEEKS])
    ve_cost = 0 if is_legacy else ve_investment
    salvage_value = pulp.lpSum([inv[p][104] * get_fob(p, 104, 'fe') * 0.90 for p in ACTIVE_PRODUCTS])
    
    prob += (revenue + salvage_value) - (purchases_fe + purchases_ns + freight + holding + penalties + ve_cost)
    
    try:
        prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=30, gapRel=0.05))
    except:
        prob.solve()
    
    def get_val(var): return var.varValue if var.varValue else 0
    return {
        "sales": {p: {w: int(get_val(sales[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "inv": {p: {w: int(get_val(inv[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "inv_0": {p: int(get_val(inv[p][0])) for p in ACTIVE_PRODUCTS},
        "order_fe": {p: {w: int(get_val(order_fe[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "order_ns": {p: {w: int(get_val(order_ns[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "cost_freight": {w: (get_val(containers_fe[w]) * FE_CONTAINER_COST) + (get_val(lcl_fe[w]) * FE_LCL_CBM_COST) + (get_val(trucks_ns[w]) * NS_TRUCK_COST) for w in WEEKS},
        "shortage": {p: {w: int(get_val(shortage[p][w])) for w in WEEKS} for p in ACTIVE_PRODUCTS},
        "containers_fe": {w: get_val(containers_fe[w]) for w in WEEKS},
        "lcl_fe": {w: get_val(lcl_fe[w]) for w in WEEKS},
        "trucks_ns": {w: get_val(trucks_ns[w]) for w in WEEKS}
    }

# --- 6. LBO FINANCIAL ENGINE (GAAP COMPLIANT) ---
def generate_three_statements(res, is_baseline, entry_ebitda=None):
    def get_fob(p, w, node):
        if is_baseline or w <= ve_dev_weeks: return FINANCIALS[p][f"{node}_fob"]
        return FINANCIALS[p][f"{node}_fob"] * (1 - ve_savings)

    def generate_is(s_w, e_w, is_year_1=False):
        rev = sum([res["sales"][p][w] * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        cogs = sum([res["sales"][p][w] * (get_fob(p, w, 'fe') * (1+tariff_rate)) for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        sga = rev * sga_margin
        freight = sum([res["cost_freight"][w] for w in range(s_w, e_w)])
        holding = sum([res["inv"][p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        short = sum([res["shortage"][p][w] * stockout_penalty for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        ve_opex = ve_investment if not is_baseline and is_year_1 else 0
        ebitda = rev - (cogs + sga + freight + holding + short + ve_opex)
        purchases = sum([res["order_fe"][p][w] * (get_fob(p, w, 'fe') * (1+tariff_rate)) + res["order_ns"][p][w] * get_fob(p, w, 'ns') for p in ACTIVE_PRODUCTS for w in range(s_w, e_w)])
        return rev, cogs, sga, purchases, freight + holding + short + ve_opex, ebitda

    y1_rev, y1_cogs, y1_sga, y1_purchases, y1_opex, y1_ebitda = generate_is(1, 53, True)
    y2_rev, y2_cogs, y2_sga, y2_purchases, y2_opex, y2_ebitda = generate_is(53, 105, False)

    dpo = 30 if is_baseline else dpo_days
    dso = 30 if is_baseline else dso_days
    
    cash_base = 5000000
    ppe_base = 15000000
    
    inv_val_0 = sum([res["inv_0"][p] * (FINANCIALS[p]["fe_fob"] * (1+tariff_rate)) for p in ACTIVE_PRODUCTS])
    inv_val_1 = sum([res["inv"][p][52] * (get_fob(p, 52, 'fe') * (1+tariff_rate)) for p in ACTIVE_PRODUCTS])
    inv_val_2 = sum([res["inv"][p][104] * (get_fob(p, 104, 'fe') * (1+tariff_rate)) for p in ACTIVE_PRODUCTS])

    ar_0 = (y1_rev / 365) * 30 
    ar_1 = (y1_rev / 365) * dso
    ar_2 = (y2_rev / 365) * dso
    
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
    salvage = inv_val_2 * 0.9
    exit_equity = (exit_ev + salvage + cash_base) - debt_2

    return {
        "IS": {"Y1 Rev": y1_rev, "Y1 COGS": -y1_cogs, "Y1 SGA": -y1_sga, "Y1 OPEX": -y1_opex, "Y1 EBITDA": y1_ebitda, 
               "Y2 Rev": y2_rev, "Y2 COGS": -y2_cogs, "Y2 SGA": -y2_sga, "Y2 OPEX": -y2_opex, "Y2 EBITDA": y2_ebitda},
        "BS": {"Cash": cash_base, "PPE": ppe_base, "Inv 0": inv_val_0, "AR 0": ar_0, "AP 0": ap_0, "Debt 0": starting_debt, "Equity 0": entry_equity, 
               "Inv 2": inv_val_2, "AR 2": ar_2, "AP 2": ap_2, "Debt 2": debt_2, "Equity 2": exit_equity},
        "CF": {"Y1 FCF": y1_fcf, "Y2 FCF": y2_fcf, "MOIC": exit_equity / entry_equity if entry_equity > 0 else 0, "Exit EV": exit_ev}
    }

def generate_excel_export(results_dict, lbo_metrics):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        pd.DataFrame([{"Strategy": n, **lbo["CF"]} for n, lbo in lbo_metrics.items()]).to_excel(writer, sheet_name="LBO_Returns", index=False)
        for name, res in results_dict.items():
            prefix = "Legacy_" if "Legacy" in name else "Opt_"
            pd.DataFrame([{"Week": w, "China FCL Containers": res["containers_fe"][w], "China LCL (CBM)": res["lcl_fe"][w], "Poland Trucks": res["trucks_ns"][w], "Total Freight": res["cost_freight"][w]} for w in WEEKS]).to_excel(writer, sheet_name=f"{prefix}Logistics", index=False)
            for p in ACTIVE_PRODUCTS:
                prod_data = [{"Week": w, "Demand": DEMAND_ACTUAL[p][w], "Sales": res["sales"][p][w], "Lost Sales": res["shortage"][p][w], "Ending Inv": res["inv"][p][w], "China PO": res["order_fe"][p][w], "Poland PO": res["order_ns"][p][w]} for w in WEEKS]
                pd.DataFrame(prod_data).to_excel(writer, sheet_name=f"{prefix}{p[:20]}".replace(" ", ""), index=False)
    return output.getvalue()

# --- 7. STATE MANAGEMENT ---
if 'results' not in st.session_state:
    st.session_state.results = None
    st.session_state.lbo_results = None

if submitted:
    with st.spinner("Analyzing Pre-Deal Baseline (Legacy China)... This may take up to 30s due to MOQ binary logic."):
        res_leg = run_milp_optimizer("Legacy (China Only)")
        stmt_leg = generate_three_statements(res_leg, True)

    with st.spinner("Executing Post-Deal 100-Day Plan..."):
        res_opt = run_milp_optimizer("100-Day Plan Optimized")
        stmt_opt = generate_three_statements(res_opt, False, stmt_leg["IS"]["Y1 EBITDA"])

    st.session_state.results = {"Legacy (Baseline)": res_leg, "Strategy& 100-Day Plan": res_opt}
    st.session_state.lbo_results = {"Legacy (Baseline)": stmt_leg, "Strategy& 100-Day Plan": stmt_opt}

# --- 8. DASHBOARDS ---
if st.session_state.results is None:
    st.info("👋 Welcome to the Value Creation Digital Twin. Upload your PortCo Data, configure your levers, and click **Run 3-Statement Optimizer**.")
else:
    results = st.session_state.results
    lbo_results = st.session_state.lbo_results

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🚀 Executive Summary", "📊 3-Statement LBO", "📦 Ending Inventory", "📈 Strategy Comparison", "📥 Export"])

    with tab1:
        st.subheader("100-Day Plan Scorecard: LBO Returns")
        st.markdown("This details the absolute return profile for the Equity Investors under the highly optimized Strategy& 100-Day Plan.")

        opt_lbo = lbo_results['Strategy& 100-Day Plan']
        leg_lbo = lbo_results['Legacy (Baseline)'] # Used strictly for the entry valuation basis
        
        entry_eq = opt_lbo['BS']['Equity 0']
        exit_eq = opt_lbo['BS']['Equity 2']
        
        # Absolute Bridge Components
        entry_ebitda = leg_lbo['IS']['Y1 EBITDA'] # Entry valuation basis
        exit_ebitda = opt_lbo['IS']['Y2 EBITDA']
        ebitda_expansion = (exit_ebitda - entry_ebitda) * entry_multiple
        
        total_fcf = opt_lbo['CF']['Y1 FCF'] + opt_lbo['CF']['Y2 FCF']
        terminal_assets = opt_lbo['BS']['Cash'] + (opt_lbo['BS']['Inv 2'] * 0.9)

        fig = go.Figure(go.Waterfall(
            name="Value Bridge",
            orientation="v",
            measure=["absolute", "relative", "relative", "relative", "total"],
            x=["Initial Equity Check", "EBITDA Expansion (x Multiple)", "Free Cash Flow (Debt Paydown)", "Terminal Cash & Salvage", "Final Exit Equity"],
            textposition="outside",
            text=[f"£{entry_eq:,.0f}", f"+£{ebitda_expansion:,.0f}", f"+£{total_fcf:,.0f}", f"+£{terminal_assets:,.0f}", f"£{exit_eq:,.0f}"],
            y=[entry_eq, ebitda_expansion, total_fcf, terminal_assets, 0],
            connector={"line":{"color":"rgb(63, 63, 63)"}},
            decreasing={"marker":{"color":"#FF4B4B"}},
            increasing={"marker":{"color":"#2ca02c"}},
            totals={"marker":{"color":"#1f77b4"}}
        ))
        
        fig.update_layout(title="Standard LBO Value Creation Bridge (Optimized Strategy)", showlegend=False, height=500)
        st.plotly_chart(fig, use_container_width=True)

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Total Equity MOIC", f"{opt_lbo['CF']['MOIC']:.2f}x")
        col_b.metric("Gross Profit to Equity", f"£{exit_eq - entry_eq:,.0f}")
        col_c.metric("Exit Enterprise Value", f"£{opt_lbo['CF']['Exit EV']:,.0f}")
        
        st.markdown("---")
        st.markdown("### Operational Value Drivers")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info("**1. Value Engineering (Margin)**")
            st.caption(f"Driven by the **{ve_savings*100:.1f}%** BOM reduction post-{ve_dev_weeks}-week lag. Directly expands Year 2 EBITDA, which scales Exit EV by {entry_multiple}x.")
        with col2:
            st.info("**2. Base-Surge (Inventory Cash)**")
            st.caption("Driven by mathematically compressing the 10-week China safety stock buffer, using highly targeted 2-week Poland LTL top-ups. Generates hard FCF.")
        with col3:
            st.info("**3. Terms Optimization (AP Cash)**")
            st.caption(f"Driven by extending standard supplier payment terms to **{dpo_days} days**. Physically shifts Working Capital leverage back to the PortCo.")

    with tab2:
        st.subheader("CFO View: GAAP 3-Statement Financial Rollout")
        
        st.markdown("### 1. Income Statement (Hold Period)")
        is_data = {
            "Line Item": ["Revenue", "COGS", "SG&A Overhead", "OPEX (Holding/Freight/VE Invest)", "EBITDA"],
            "Legacy Y1": [f"£{lbo_results['Legacy (Baseline)']['IS']['Y1 Rev']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['IS']['Y1 COGS']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['IS']['Y1 SGA']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['IS']['Y1 OPEX']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['IS']['Y1 EBITDA']:,.0f}"],
            "Legacy Y2": [f"£{lbo_results['Legacy (Baseline)']['IS']['Y2 Rev']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['IS']['Y2 COGS']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['IS']['Y2 SGA']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['IS']['Y2 OPEX']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['IS']['Y2 EBITDA']:,.0f}"],
            "Opt 100-Day Y1": [f"£{lbo_results['Strategy& 100-Day Plan']['IS']['Y1 Rev']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['IS']['Y1 COGS']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['IS']['Y1 SGA']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['IS']['Y1 OPEX']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['IS']['Y1 EBITDA']:,.0f}"],
            "Opt 100-Day Y2": [f"£{lbo_results['Strategy& 100-Day Plan']['IS']['Y2 Rev']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['IS']['Y2 COGS']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['IS']['Y2 SGA']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['IS']['Y2 OPEX']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['IS']['Y2 EBITDA']:,.0f}"]
        }
        st.table(pd.DataFrame(is_data).set_index("Line Item"))

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 2. Balance Sheet (Exit View)")
            bs_data = {
                "Line Item": ["Operating Cash", "PP&E", "Inventory", "Accts Receivable", "Accts Payable", "LBO Debt"],
                "Legacy (Exit)": [f"£{lbo_results['Legacy (Baseline)']['BS']['Cash']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['BS']['PPE']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['BS']['Inv 2']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['BS']['AR 2']:,.0f}", f"£{-lbo_results['Legacy (Baseline)']['BS']['AP 2']:,.0f}", f"£{-lbo_results['Legacy (Baseline)']['BS']['Debt 2']:,.0f}"],
                "Opt (Exit)": [f"£{lbo_results['Strategy& 100-Day Plan']['BS']['Cash']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['BS']['PPE']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['BS']['Inv 2']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['BS']['AR 2']:,.0f}", f"£{-lbo_results['Strategy& 100-Day Plan']['BS']['AP 2']:,.0f}", f"£{-lbo_results['Strategy& 100-Day Plan']['BS']['Debt 2']:,.0f}"]
            }
            st.table(pd.DataFrame(bs_data).set_index("Line Item"))
            
        with col2:
            st.markdown("### 3. Cash Flow & Returns")
            cf_data = {
                "Line Item": ["FCF (Y1)", "FCF (Y2)", "Exit Enterprise Value", "Equity MOIC"],
                "Legacy": [f"£{lbo_results['Legacy (Baseline)']['CF']['Y1 FCF']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['CF']['Y2 FCF']:,.0f}", f"£{lbo_results['Legacy (Baseline)']['CF']['Exit EV']:,.0f}", f"{lbo_results['Legacy (Baseline)']['CF']['MOIC']:.2f}x"],
                "Opt 100-Day": [f"£{lbo_results['Strategy& 100-Day Plan']['CF']['Y1 FCF']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['CF']['Y2 FCF']:,.0f}", f"£{lbo_results['Strategy& 100-Day Plan']['CF']['Exit EV']:,.0f}", f"{lbo_results['Strategy& 100-Day Plan']['CF']['MOIC']:.2f}x"]
            }
            st.table(pd.DataFrame(cf_data).set_index("Line Item"))

    with tab3:
        st.subheader("Operations: Ending Inventory Sawtooth")
        view_prod = st.selectbox("Select Product to Graph:", ACTIVE_PRODUCTS)
        
        chart_data = [{"Week": w, "Metric": "Actual Seasonal Demand", "Units": int(DEMAND_ACTUAL[view_prod][w])} for w in WEEKS]
        for name, res in results.items():
            chart_data.extend([{"Week": w, "Metric": f"Ending Inv ({name})", "Units": int(res["inv"][view_prod][w])} for w in WEEKS])
                
        c_df = pd.DataFrame(chart_data)
        domain = ["Actual Seasonal Demand", "Ending Inv (Legacy (Baseline))", "Ending Inv (Strategy& 100-Day Plan)"]
        range_ = ['#FF4B4B', '#1f77b4', '#2ca02c']
        
        chart = alt.Chart(c_df).mark_line(strokeWidth=3).encode(
            x='Week:Q', y='Units:Q', color=alt.Color('Metric:N', scale=alt.Scale(domain=domain, range=range_)),
            strokeDash=alt.condition(alt.datum.Metric == 'Actual Seasonal Demand', alt.value([5, 5]), alt.value([0]))
        ).properties(height=450)
        st.altair_chart(chart, use_container_width=True)

    with tab4:
        st.subheader("Legacy vs. 100-Day Plan Comparison")
        st.markdown("For reference and audit logic, this explicitly bridges the difference if the PE firm had kept the legacy management team versus executing the Strategy& plan.")
        
        bridge_data = {
            "Value Driver": ["1. Entry Equity", "2. Total FCF Generated", "3. Debt Paid Down", "4. Exit Enterprise Value", "5. Terminal Operating Cash", "6. Terminal Inventory Salvage", "7. Remaining LBO Debt", "FINAL EXIT EQUITY VALUE"],
            "Legacy": [
                f"£{lbo_results['Legacy (Baseline)']['BS']['Equity 0']:,.0f}", 
                f"£{lbo_results['Legacy (Baseline)']['CF']['Y1 FCF'] + lbo_results['Legacy (Baseline)']['CF']['Y2 FCF']:,.0f}", 
                f"£{lbo_results['Legacy (Baseline)']['BS']['Debt 0'] - lbo_results['Legacy (Baseline)']['BS']['Debt 2']:,.0f}", 
                f"£{lbo_results['Legacy (Baseline)']['CF']['Exit EV']:,.0f}", 
                f"£{lbo_results['Legacy (Baseline)']['BS']['Cash']:,.0f}", 
                f"£{lbo_results['Legacy (Baseline)']['BS']['Inv 2'] * 0.9:,.0f}",
                f"-£{lbo_results['Legacy (Baseline)']['BS']['Debt 2']:,.0f}", 
                f"£{lbo_results['Legacy (Baseline)']['BS']['Equity 2']:,.0f}"
            ],
            "Opt 100-Day Plan": [
                f"£{lbo_results['Strategy& 100-Day Plan']['BS']['Equity 0']:,.0f}", 
                f"£{lbo_results['Strategy& 100-Day Plan']['CF']['Y1 FCF'] + lbo_results['Strategy& 100-Day Plan']['CF']['Y2 FCF']:,.0f}", 
                f"£{lbo_results['Strategy& 100-Day Plan']['BS']['Debt 0'] - lbo_results['Strategy& 100-Day Plan']['BS']['Debt 2']:,.0f}", 
                f"£{lbo_results['Strategy& 100-Day Plan']['CF']['Exit EV']:,.0f}", 
                f"£{lbo_results['Strategy& 100-Day Plan']['BS']['Cash']:,.0f}", 
                f"£{lbo_results['Strategy& 100-Day Plan']['BS']['Inv 2'] * 0.9:,.0f}",
                f"-£{lbo_results['Strategy& 100-Day Plan']['BS']['Debt 2']:,.0f}", 
                f"£{lbo_results['Strategy& 100-Day Plan']['BS']['Equity 2']:,.0f}"
            ]
        }
        st.table(pd.DataFrame(bridge_data).set_index("Value Driver"))

    with tab5:
        st.subheader("Full CFO Audit Download")
        st.download_button("📥 Download PE Audit Ledger (.xlsx)", data=generate_excel_export(results, lbo_results), file_name="PE_100_Day_Audit.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
