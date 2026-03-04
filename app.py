import streamlit as st
import pandas as pd
import numpy as np
import io
import altair as alt
import math

st.set_page_config(page_title="Strategy& Value Creation: Sourcing Twin", layout="wide")

st.title("🌍 PE Value Creation: Intelligent Base-Surge LBO Twin")
st.markdown("**Context:** Evaluating a 2-Year PE Hold. This engine uses dynamic Rolling-Horizon MRP and Newsvendor Critical Ratios to simulate intelligent 'Base-Surge' supply chain execution.")

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
            # FIX: Actual volatility physically shifts up with the growth curve
            growth_multiplier = (1 + y2_growth) if w > 52 else 1
            path[p][w] = max(0, int(np.random.normal(mean * growth_multiplier, std * growth_multiplier)))
    st.session_state.actual_demand = path
    st.session_state.demand_locked = True

# --- 3. SIDEBAR CONTROLS ---
with st.sidebar:
    st.header("Step 1: Market Volatility")
    y2_growth_ui = st.slider("Year 2 Market Growth (%)", 0.0, 30.0, 10.0) / 100.0
    
    if st.button("🔒 Lock 104-Week Actuals", use_container_width=True):
        generate_stochastic_demand(DEFAULT_PRODUCTS, DEMAND_PARAMS, y2_growth_ui)
        st.success("Locked!")

    if not st.session_state.demand_locked:
        np.random.seed(42) 
        generate_stochastic_demand(DEFAULT_PRODUCTS, DEMAND_PARAMS, y2_growth_ui)
    
    st.markdown("---")
    st.header("Step 2: LBO Mechanics")
    with st.form("lbo_panel"):
        entry_multiple = st.slider("Exit Multiple (x EBITDA)", 6.0, 15.0, 9.0)
        debt_ratio = st.slider("Debt Funding Ratio (%)", 0.0, 80.0, 60.0) / 100.0
        interest_rate = st.slider("Debt Interest Rate (%)", 5.0, 15.0, 9.0) / 100.0
        
        st.subheader("Operational Cost Levers")
        tariff_rate = st.slider("China Import Tariff (%)", 0.0, 20.0, 8.0) / 100.0
        wacc_weekly = (st.slider("WACC (%)", 5.0, 25.0, 12.0) / 100.0) / 52.0
        holding_cost = st.slider("UK 3PL Storage (£/unit/wk)", 0.05, 0.50, 0.15)
        stockout_penalty = st.slider("Lost Sale Penalty (£/unit)", 20, 150, 80)
        corp_tax = 0.25 
        submitted = st.form_submit_button("🚀 Run Dynamic Base-Surge Engine")

DEMAND_ACTUAL = st.session_state.actual_demand

def get_z_score(cr):
    """Tukey Lambda approximation for Normal Distribution Z-Score"""
    if cr >= 0.99: return 2.33
    if cr <= 0.01: return -2.33
    return 4.91 * (cr**0.14 - (1.0 - cr)**0.14)

# --- 4. THE INTELLIGENT ROLLING S&OP ENGINE ---
def simulate_intelligent_sop(strategy_type):
    inv = {p: {} for p in DEFAULT_PRODUCTS}
    sales = {p: {} for p in DEFAULT_PRODUCTS}
    shortage = {p: {} for p in DEFAULT_PRODUCTS}
    order_fe = {p: {} for p in DEFAULT_PRODUCTS}
    order_ns = {p: {} for p in DEFAULT_PRODUCTS}
    
    containers_fe, trucks_ns, cost_freight = {}, {}, {}

    for p in DEFAULT_PRODUCTS:
        # Initial inventory covers 12 weeks
        inv[p][0] = int(DEMAND_PARAMS[p]["mean"] * (DEFAULT_ECO[p]["fe_lt"] + 2))
        for w in range(-15, 1): order_fe[p][w] = 0; order_ns[p][w] = 0
    
    for w in WEEKS:
        weekly_fe_cbm, weekly_ns_cbm = 0, 0
        
        for p in DEFAULT_PRODUCTS:
            mean_dem = DEMAND_PARAMS[p]["mean"] * ((1 + y2_growth_ui) if w > 52 else 1)
            std_dem = DEMAND_PARAMS[p]["std"] * ((1 + y2_growth_ui) if w > 52 else 1)
            
            # 1. Receive Arrivals
            arr_fe = order_fe[p].get(w - DEFAULT_ECO[p]["fe_lt"], 0)
            arr_ns = order_ns[p].get(w - DEFAULT_ECO[p]["ns_lt"], 0)
            
            curr_inv = inv[p][w-1] + arr_fe + arr_ns
            
            # 2. Sell
            act_dem = DEMAND_ACTUAL[p][w]
            sold = min(curr_inv, act_dem)
            sales[p][w] = sold
            shortage[p][w] = act_dem - sold
            inv[p][w] = curr_inv - sold
            
            # 3. Intelligent Planner (Lookahead)
            pipeline_fe = sum([order_fe[p].get(kw, 0) for kw in range(w - DEFAULT_ECO[p]["fe_lt"] + 1, w)])
            pipeline_ns = sum([order_ns[p].get(kw, 0) for kw in range(w - DEFAULT_ECO[p]["ns_lt"] + 1, w)])
            
            if strategy_type == "Legacy":
                # Newsvendor: High penalty for stockout (Lost Sale)
                cu = DEFAULT_ECO[p]["price"] - (DEFAULT_ECO[p]["fe_fob"] * (1+tariff_rate))
                co = holding_cost * 26 + wacc_weekly * 26 * DEFAULT_ECO[p]["fe_fob"]
                z = get_z_score(cu / (cu + co)) # e.g. 98th percentile (Z=2.0)
                
                target_inv = mean_dem * (DEFAULT_ECO[p]["fe_lt"] + 1) + z * std_dem * math.sqrt(DEFAULT_ECO[p]["fe_lt"])
                proj_inv = inv[p][w] + pipeline_fe
                
                order_fe[p][w] = max(0, int(target_inv - proj_inv)) if w <= 104 - DEFAULT_ECO[p]["fe_lt"] else 0
                order_ns[p][w] = 0
                
            elif strategy_type == "Dual":
                # BASE (China): Penalty is just the extra cost to buy from Poland
                cu_base = DEFAULT_ECO[p]["ns_fob"] - (DEFAULT_ECO[p]["fe_fob"] * (1+tariff_rate))
                co = holding_cost * 26 + wacc_weekly * 26 * DEFAULT_ECO[p]["fe_fob"]
                z_base = get_z_score(cu_base / (cu_base + co)) # e.g. 50th percentile (Z=0.0) -> No bloated buffer!
                
                target_fe = mean_dem * (DEFAULT_ECO[p]["fe_lt"] + 1) + z_base * std_dem * math.sqrt(DEFAULT_ECO[p]["fe_lt"])
                proj_inv_fe = inv[p][w] + pipeline_fe + pipeline_ns
                
                order_fe[p][w] = max(0, int(target_fe - proj_inv_fe)) if w <= 104 - DEFAULT_ECO[p]["fe_lt"] else 0
                
                # SURGE (Poland): Chasing the actual volatility
                cu_surge = DEFAULT_ECO[p]["price"] - DEFAULT_ECO[p]["ns_fob"]
                z_surge = get_z_score(cu_surge / (cu_surge + co)) # e.g. 98th percentile
                
                target_ns = mean_dem * (DEFAULT_ECO[p]["ns_lt"] + 1) + z_surge * std_dem * math.sqrt(DEFAULT_ECO[p]["ns_lt"])
                proj_inv_ns = inv[p][w] + sum([order_fe[p].get(kw, 0) for kw in range(w - DEFAULT_ECO[p]["fe_lt"] + 1, w + DEFAULT_ECO[p]["ns_lt"])]) + pipeline_ns
                
                order_ns[p][w] = max(0, int(target_ns - proj_inv_ns)) if w <= 104 - DEFAULT_ECO[p]["ns_lt"] else 0

            weekly_fe_cbm += order_fe[p][w] * DEFAULT_ECO[p]["unit_cbm"]
            weekly_ns_cbm += order_ns[p][w] * DEFAULT_ECO[p]["unit_cbm"]
            
        containers_fe[w] = int(np.ceil(weekly_fe_cbm / FE_CONTAINER_CBM))
        trucks_ns[w] = int(np.ceil(weekly_ns_cbm / NS_TRUCK_CBM))
        cost_freight[w] = (containers_fe[w] * FE_CONTAINER_COST) + (trucks_ns[w] * NS_TRUCK_COST)

    return {"sales": sales, "shortage": shortage, "inv": inv, "order_fe": order_fe, "order_ns": order_ns, "containers_fe": containers_fe, "trucks_ns": trucks_ns, "cost_freight": cost_freight}

# --- 5. LBO FINANCIAL ENGINE ---
def calc_lbo(res, is_baseline, entry_ebitda=None):
    def get_ebitda(s_w, e_w):
        rev = sum([res["sales"][p][w] * DEFAULT_ECO[p]["price"] for p in DEFAULT_PRODUCTS for w in range(s_w, e_w)])
        cogs_fe = sum([res["order_fe"][p][w] * (DEFAULT_ECO[p]["fe_fob"] * (1+tariff_rate)) for p in DEFAULT_PRODUCTS for w in range(s_w, e_w)])
        cogs_ns = sum([res["order_ns"][p][w] * DEFAULT_ECO[p]["ns_fob"] for p in DEFAULT_PRODUCTS for w in range(s_w, e_w)])
        freight = sum([res["cost_freight"][w] for w in range(s_w, e_w)])
        holding = sum([res["inv"][p][w] * holding_cost for p in DEFAULT_PRODUCTS for w in range(s_w, e_w)])
        short = sum([res["shortage"][p][w] * stockout_penalty for p in DEFAULT_PRODUCTS for w in range(s_w, e_w)])
        return rev - (cogs_fe + cogs_ns + freight + holding + short)

    y1_ebitda, y2_ebitda = get_ebitda(1, 53), get_ebitda(53, 105)
    
    start_nwc = sum([res["inv"][p][0] * DEFAULT_ECO[p]["fe_fob"] for p in DEFAULT_PRODUCTS])
    y1_nwc = sum([res["inv"][p][52] * DEFAULT_ECO[p]["fe_fob"] for p in DEFAULT_PRODUCTS])
    y2_nwc = sum([res["inv"][p][104] * DEFAULT_ECO[p]["fe_fob"] for p in DEFAULT_PRODUCTS])
    
    entry_ev = (y1_ebitda if is_baseline else entry_ebitda) * entry_multiple
    starting_debt = entry_ev * debt_ratio
    entry_equity = entry_ev - starting_debt

    y1_fcf = y1_ebitda - (starting_debt * interest_rate) - (y1_nwc - start_nwc)
    end_y1_debt = starting_debt - y1_fcf
    
    y2_fcf = y2_ebitda - (end_y1_debt * interest_rate) - (y2_nwc - y1_nwc)
    ending_debt = end_y1_debt - y2_fcf
    
    exit_ev = y2_ebitda * entry_multiple
    salvage = sum([res["inv"][p][104] * DEFAULT_ECO[p]["fe_fob"] * 0.9 for p in DEFAULT_PRODUCTS])
    exit_equity = (exit_ev + salvage) - ending_debt
    
    return {"entry_ev": entry_ev, "starting_debt": starting_debt, "entry_equity": entry_equity, "y1_ebitda": y1_ebitda, "y1_delta_nwc": y1_nwc-start_nwc, "y1_fcf": y1_fcf, "y2_ebitda": y2_ebitda, "y2_delta_nwc": y2_nwc-y1_nwc, "y2_fcf": y2_fcf, "exit_ev": exit_ev, "ending_debt": ending_debt, "exit_equity": exit_equity, "moic": exit_equity / entry_equity if entry_equity > 0 else 0}

# --- 6. EXECUTION ---
with st.spinner("Simulating Legacy China Strategy (Rolling S&OP)..."):
    res_leg = simulate_intelligent_sop("Legacy")
    lbo_leg = calc_lbo(res_leg, True)

with st.spinner("Simulating Intelligent Base-Surge (Newsvendor)..."):
    res_dual = simulate_intelligent_sop("Dual")
    lbo_dual = calc_lbo(res_dual, False, lbo_leg["y1_ebitda"])

results = {"Legacy (China Only)": res_leg, "Intelligent Base-Surge": res_dual}
lbo_results = {"Legacy (China Only)": lbo_leg, "Intelligent Base-Surge": lbo_dual}

# --- 7. DASHBOARDS ---
tab1, tab2, tab3 = st.tabs(["🚀 LBO Return Multiples", "💸 FCF Waterfall", "📦 Base-Surge Dynamics"])

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
    waterfall_data = [{"Strategy": n, "1. PE Entry EBITDA": f"£{lbo_leg['y1_ebitda']:,.0f}", "2. Entry Debt Load": f"£{l['starting_debt']:,.0f}", "3. Y1 Operating FCF": f"£{l['y1_fcf']:,.0f}", "4. Y1 NWC Cash Trapped": f"£{-l['y1_delta_nwc']:,.0f}", "5. Y2 Operating FCF": f"£{l['y2_fcf']:,.0f}", "6. Y2 NWC Cash Trapped": f"£{-l['y2_delta_nwc']:,.0f}", "7. Remaining Debt": f"£{l['ending_debt']:,.0f}", "8. Final Exit EBITDA": f"£{l['y2_ebitda']:,.0f}"} for n, l in lbo_results.items()]
    st.table(pd.DataFrame(waterfall_data).set_index("Strategy").T)

with tab3:
    st.subheader("Operations: Intelligent Base-Surge Reaction")
    view_prod = st.selectbox("Select Product to Graph:", DEFAULT_PRODUCTS)
    
    chart_data = [{"Week": w, "Metric": "Actual Customer Demand", "Units": int(DEMAND_ACTUAL[view_prod][w])} for w in WEEKS]
    for name, res in results.items():
        chart_data.extend([{"Week": w, "Metric": f"Inv ({name})", "Units": int(res["inv"][view_prod][w])} for w in WEEKS])
            
    c_df = pd.DataFrame(chart_data)
    domain = ["Actual Customer Demand", "Inv (Legacy (China Only))", "Inv (Intelligent Base-Surge)"]
    range_ = ['#FF4B4B', '#1f77b4', '#2ca02c']
    
    chart = alt.Chart(c_df).mark_line(strokeWidth=3).encode(
        x='Week:Q', y='Units:Q', color=alt.Color('Metric:N', scale=alt.Scale(domain=domain, range=range_)),
        strokeDash=alt.condition(alt.datum.Metric == 'Actual Customer Demand', alt.value([5, 5]), alt.value([0]))
    ).properties(height=450)
    st.altair_chart(chart, use_container_width=True)
