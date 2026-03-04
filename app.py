import streamlit as st
import pandas as pd
import numpy as np
import pulp
import io
import altair as alt

st.set_page_config(page_title="Strategy& Value Creation: LBO & Sourcing Twin", layout="wide")

st.title("🌍 PE Value Creation: LBO Sourcing & Cash Flow Twin")
st.markdown("**Context:** Evaluating a 2-Year PE Hold. Merging a Multi-Echelon Supply Chain Optimizer with an LBO Financial Model to demonstrate the impact of S&OP on Debt Paydown and Exit MOIC.")

# --- 1. CONFIGURATION & REALISTIC DATA ---
WEEKS = list(range(1, 105)) # 104 Weeks (2 Years)
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

FE_CONTAINER_CBM = 68.0   
FE_CONTAINER_COST = 6500  
NS_TRUCK_CBM = 80.0       
NS_TRUCK_COST = 2500      

# --- 2. STATE MANAGEMENT ---
if 'demand_locked' not in st.session_state:
    st.session_state.demand_locked = False
    st.session_state.demand_path = {}

def generate_stochastic_demand(products_list, params_dict):
    path = {}
    for p in products_list:
        mean, std = params_dict[p]["mean"], params_dict[p]["std"]
        path[p] = {}
        for w in WEEKS:
            path[p][w] = max(0, int(np.random.normal(mean, std)))
    st.session_state.demand_path = path
    st.session_state.demand_locked = True

# --- 3. EXCEL EXPORT ENGINE ---
def generate_cfo_ledger(results_dict, lbo_metrics):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        lbo_data = []
        for name, lbo in lbo_metrics.items():
            lbo_data.append({
                "Strategy": name, "Entry EV": lbo['entry_ev'], "Entry Equity": lbo['entry_equity'], "Starting Debt": lbo['starting_debt'],
                "Y1 EBITDA": lbo['y1_ebitda'], "Y1 Delta NWC": lbo['y1_delta_nwc'], "Y1 FCF": lbo['y1_fcf'],
                "Y2 EBITDA": lbo['y2_ebitda'], "Y2 Delta NWC": lbo['y2_delta_nwc'], "Y2 FCF": lbo['y2_fcf'],
                "Exit EV": lbo['exit_ev'], "Ending Debt": lbo['ending_debt'], "Exit Equity": lbo['exit_equity'], "MOIC": lbo['moic']
            })
        pd.DataFrame(lbo_data).to_excel(writer, sheet_name="LBO_Returns", index=False)
        
        for name, res in results_dict.items():
            prefix = "Legacy_" if "Legacy" in name else "Dual_"
            log_data = []
            for w in WEEKS:
                c_fe = int(get_val(res["containers_fe"][w]))
                t_ns = int(get_val(res["trucks_ns"][w]))
                log_data.append({"Week": w, "China Containers": c_fe, "Poland Trucks": t_ns, "Freight Cost": (c_fe*FE_CONTAINER_COST) + (t_ns*NS_TRUCK_COST)})
            pd.DataFrame(log_data).to_excel(writer, sheet_name=f"{prefix}Logistics", index=False)
            
            for p in ACTIVE_PRODUCTS:
                prod_data = []
                for w in WEEKS:
                    prod_data.append({
                        "Week": w, "Demand": int(DEMAND[p][w]), "Sales Fulfilled": int(get_val(res["sales"][p][w])), 
                        "Lost Sales": int(get_val(res["shortage"][p][w])), "Ending Inv": int(get_val(res["inv"][p][w])),
                        "PO to China": int(get_val(res["order_fe"][p][w])), "PO to Poland": int(get_val(res["order_ns"][p][w]))
                    })
                pd.DataFrame(prod_data).to_excel(writer, sheet_name=f"{prefix}{p[:20]}".replace(" ", ""), index=False)
    return output.getvalue()

# --- 4. SIDEBAR CONTROLS ---
with st.sidebar:
    ACTIVE_PRODUCTS = DEFAULT_PRODUCTS
    ACTIVE_DEMAND_PARAMS = DEMAND_PARAMS
    FINANCIALS = DEFAULT_ECO

    st.header("Step 1: Lock Market Volatility")
    if st.button("🔒 Lock 104-Week Baseline Demand", use_container_width=True):
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS)
        st.success("Locked!")

    if not st.session_state.demand_locked:
        np.random.seed(42) 
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS)
    
    st.markdown("---")
    
    st.header("Step 2: Value Creation Mechanics")
    with st.form("lbo_panel"):
        st.subheader("Market Growth")
        y2_growth = st.slider("Year 2 Demand Growth (%)", 0.0, 30.0, 10.0) / 100.0
        
        st.subheader("Private Equity Assumptions")
        entry_multiple = st.slider("Entry / Exit Multiple (x EBITDA)", 6.0, 15.0, 9.0)
        debt_ratio = st.slider("Debt Funding Ratio (%)", 0.0, 80.0, 60.0) / 100.0
        interest_rate = st.slider("Debt Interest Rate (%)", 5.0, 15.0, 9.0) / 100.0
        
        st.subheader("Operational Levers")
        tariff_rate = st.slider("China Import Tariff (%)", 0.0, 20.0, 8.0) / 100.0
        wacc_annual = st.slider("Internal Cost of Capital (WACC %)", 5.0, 25.0, 12.0) / 100.0
        wacc_weekly = wacc_annual / 52.0
        holding_cost = st.slider("UK 3PL Storage (£/unit/wk)", 0.05, 0.50, 0.15)
        stockout_penalty = st.slider("Lost Sale Penalty (£/unit)", 20, 150, 80)
        corp_tax = 0.25 
        
        submitted = st.form_submit_button("🚀 Run LBO & Sourcing Optimizer")

# --- 4.5 DEMAND GROWTH CALCULATOR ---
# Dynamically scale Year 2 based on the slider, maintaining the locked stochastic volatility
DEMAND = {}
for p in ACTIVE_PRODUCTS:
    DEMAND[p] = {}
    for w in WEEKS:
        if w <= 52:
            DEMAND[p][w] = st.session_state.demand_path[p][w]
        else:
            DEMAND[p][w] = int(st.session_state.demand_path[p][w] * (1 + y2_growth))

# --- 5. THE MILP SOLVER ---
def solve_sourcing(strategy_type):
    prob = pulp.LpProblem(f"Sourcing_{strategy_type.replace(' ', '')}", pulp.LpMaximize)
    
    order_fe = pulp.LpVariable.dicts("Order_FE", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    order_ns = pulp.LpVariable.dicts("Order_NS", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    containers_fe = pulp.LpVariable.dicts("Containers_FE", WEEKS, lowBound=0, cat='Integer')
    trucks_ns = pulp.LpVariable.dicts("Trucks_NS", WEEKS, lowBound=0, cat='Integer')
    inv = pulp.LpVariable.dicts("Inv", (ACTIVE_PRODUCTS, [0] + WEEKS), lowBound=0, cat='Integer')
    sales = pulp.LpVariable.dicts("Sales", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    shortage = pulp.LpVariable.dicts("Shortage", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')

    for p in ACTIVE_PRODUCTS:
        prob += inv[p][0] == int(ACTIVE_DEMAND_PARAMS[p]["mean"] * (FINANCIALS[p]["fe_lt"] + 1))
        
        # Going Concern Constraint: Must end with 4 weeks of stock scaled to the NEW Year 2 demand volume
        prob += inv[p][104] >= int(ACTIVE_DEMAND_PARAMS[p]["mean"] * (1 + y2_growth) * 4)

        for w in WEEKS:
            arr_fe = order_fe[p][w - int(FINANCIALS[p]["fe_lt"])] if w > FINANCIALS[p]["fe_lt"] else int(ACTIVE_DEMAND_PARAMS[p]["mean"])
            arr_ns = order_ns[p][w - int(FINANCIALS[p]["ns_lt"])] if w > FINANCIALS[p]["ns_lt"] else 0

            if strategy_type == "Legacy Strategy (100% Far-East)": 
                prob += order_ns[p][w] == 0
                
            prob += inv[p][w] == inv[p][w-1] + arr_fe + arr_ns - sales[p][w]
            prob += sales[p][w] <= DEMAND[p][w]
            prob += sales[p][w] <= inv[p][w-1] + arr_fe + arr_ns
            prob += shortage[p][w] == DEMAND[p][w] - sales[p][w]

    for w in WEEKS:
        prob += pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS]) <= containers_fe[w] * FE_CONTAINER_CBM
        prob += pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS]) <= trucks_ns[w] * NS_TRUCK_CBM

    revenue = pulp.lpSum([sales[p][w] * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    salvage_value = pulp.lpSum([inv[p][104] * FINANCIALS[p]["fe_fob"] * 0.90 for p in ACTIVE_PRODUCTS])
    cogs_fe = pulp.lpSum([order_fe[p][w] * (FINANCIALS[p]["fe_fob"] * (1 + tariff_rate)) for p in ACTIVE_PRODUCTS for w in WEEKS])
    cogs_ns = pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["ns_fob"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    logistics = pulp.lpSum([containers_fe[w] * FE_CONTAINER_COST + trucks_ns[w] * NS_TRUCK_COST for w in WEEKS])
    holding = pulp.lpSum([inv[p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in WEEKS])
    lost_sales_cost = pulp.lpSum([shortage[p][w] * stockout_penalty for p in ACTIVE_PRODUCTS for w in WEEKS])
    wacc_penalty = pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["fe_fob"] * FINANCIALS[p]["fe_lt"] * wacc_weekly + order_ns[p][w] * FINANCIALS[p]["ns_fob"] * FINANCIALS[p]["ns_lt"] * wacc_weekly + inv[p][w] * FINANCIALS[p]["fe_fob"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    prob += (revenue + salvage_value) - (cogs_fe + cogs_ns + logistics + holding + lost_sales_cost + wacc_penalty)
    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=20, gapRel=0.03))
    
    return {"status": pulp.LpStatus[prob.status], "sales": sales, "order_fe": order_fe, "order_ns": order_ns, "containers_fe": containers_fe, "trucks_ns": trucks_ns, "inv": inv, "shortage": shortage}

def get_val(var): return var.varValue if var.varValue else 0

# --- 6. LBO FINANCIAL ENGINE ---
def calculate_lbo_metrics(res, is_baseline=False, entry_ebitda=None):
    def get_period_ebitda(start_w, end_w):
        rev = sum([get_val(res["sales"][p][w]) * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in range(start_w, end_w)])
        cogs = sum([get_val(res["order_fe"][p][w]) * (FINANCIALS[p]["fe_fob"] * (1+tariff_rate)) + get_val(res["order_ns"][p][w]) * FINANCIALS[p]["ns_fob"] for p in ACTIVE_PRODUCTS for w in range(start_w, end_w)])
        freight = sum([get_val(res["containers_fe"][w]) * FE_CONTAINER_COST + get_val(res["trucks_ns"][w]) * NS_TRUCK_COST for w in range(start_w, end_w)])
        holding = sum([get_val(res["inv"][p][w]) * holding_cost for p in ACTIVE_PRODUCTS for w in range(start_w, end_w)])
        return rev - (cogs + freight + holding)

    y1_ebitda = get_period_ebitda(1, 53)
    y2_ebitda = get_period_ebitda(53, 105)
    
    start_nwc = sum([get_val(res["inv"][p][0]) * FINANCIALS[p]["fe_fob"] for p in ACTIVE_PRODUCTS])
    y1_nwc = sum([get_val(res["inv"][p][52]) * FINANCIALS[p]["fe_fob"] for p in ACTIVE_PRODUCTS])
    y2_nwc = sum([get_val(res["inv"][p][104]) * FINANCIALS[p]["fe_fob"] for p in ACTIVE_PRODUCTS])
    
    y1_delta_nwc = y1_nwc - start_nwc
    y2_delta_nwc = y2_nwc - y1_nwc

    base_ebitda = y1_ebitda if is_baseline else entry_ebitda
    entry_ev = base_ebitda * entry_multiple
    starting_debt = entry_ev * debt_ratio
    entry_equity = entry_ev - starting_debt

    y1_interest = starting_debt * interest_rate
    y1_taxes = (y1_ebitda - y1_interest) * corp_tax if (y1_ebitda - y1_interest) > 0 else 0
    y1_fcf = y1_ebitda - y1_taxes - y1_interest - y1_delta_nwc
    end_y1_debt = starting_debt - y1_fcf
    
    y2_interest = end_y1_debt * interest_rate
    y2_taxes = (y2_ebitda - y2_interest) * corp_tax if (y2_ebitda - y2_interest) > 0 else 0
    y2_fcf = y2_ebitda - y2_taxes - y2_interest - y2_delta_nwc
    ending_debt = end_y1_debt - y2_fcf
    
    exit_ev = y2_ebitda * entry_multiple
    exit_equity = exit_ev - ending_debt
    moic = exit_equity / entry_equity if entry_equity > 0 else 0

    return {
        "y1_ebitda": y1_ebitda, "y2_ebitda": y2_ebitda, "entry_ev": entry_ev, 
        "starting_debt": starting_debt, "entry_equity": entry_equity, 
        "y1_delta_nwc": y1_delta_nwc, "y1_fcf": y1_fcf, "y2_delta_nwc": y2_delta_nwc, "y2_fcf": y2_fcf,
        "exit_ev": exit_ev, "ending_debt": ending_debt, "exit_equity": exit_equity, "moic": moic
    }

# --- 7. EXECUTION ---
with st.spinner("Solving Baseline Legacy Strategy to set Deal Valuation..."):
    res_legacy = solve_sourcing("Legacy Strategy (100% Far-East)")
    lbo_legacy = calculate_lbo_metrics(res_legacy, is_baseline=True)

with st.spinner("Solving Optimized Value Creation Strategy..."):
    res_opt = solve_sourcing("Optimized Value Creation")
    lbo_opt = calculate_lbo_metrics(res_opt, is_baseline=False, entry_ebitda=lbo_legacy["y1_ebitda"])

results = {"Legacy (China Only)": res_legacy, "Dual-Sourcing": res_opt}
lbo_results = {"Legacy (China Only)": lbo_legacy, "Dual-Sourcing": lbo_opt}

# --- 8. VISUAL DASHBOARDS ---
tab1, tab2, tab3, tab4 = st.tabs(["🚀 Private Equity LBO Returns", "💸 Free Cash Flow Waterfall", "📦 2-Year S&OP Inventory Curve", "📥 Download CFO Ledger"])

with tab1:
    st.subheader("The PE Deal Scorecard (Returns Bridge)")
    cols = st.columns(2)
    for i, (name, lbo) in enumerate(lbo_results.items()):
        with cols[i]:
            st.markdown(f"### {name}")
            st.metric("Total Equity MOIC", f"{lbo['moic']:.2f}x")
            st.metric("Exit Enterprise Value", f"£{lbo['exit_ev']:,.0f}")
            st.metric("Total Free Cash Flow Generated", f"£{lbo['y1_fcf'] + lbo['y2_fcf']:,.0f}")
            
    st.markdown("---")
    st.info("💡 **Notice the LBO Mechanics:** If you increase the Year 2 Demand Growth slider, the solver uses Poland to catch the top-line growth without blowing up the Working Capital. This accelerates EBITDA growth and Debt Paydown simultaneously, creating a massive divergence in the Equity MOIC between the two strategies.")

with tab2:
    st.subheader("Debt & Cash Flow Waterfall (2-Year Hold)")
    waterfall_data = []
    for name, lbo in lbo_results.items():
        waterfall_data.append({
            "Strategy": name,
            "1. Entry EBITDA": f"£{lbo_legacy['y1_ebitda']:,.0f}",
            "2. Entry Debt Load": f"£{lbo['starting_debt']:,.0f}",
            "3. Y1 Operating Cash Flow (FCF)": f"£{lbo['y1_fcf']:,.0f}",
            "4. Y1 Change in Net Working Capital": f"£{-lbo['y1_delta_nwc']:,.0f}",
            "5. Y2 Operating Cash Flow (FCF)": f"£{lbo['y2_fcf']:,.0f}",
            "6. Y2 Change in Net Working Capital": f"£{-lbo['y2_delta_nwc']:,.0f}",
            "7. Remaining Debt at Exit": f"£{lbo['ending_debt']:,.0f}",
            "8. Final Exit EBITDA": f"£{lbo['y2_ebitda']:,.0f}"
        })
    st.table(pd.DataFrame(waterfall_data).set_index("Strategy").T)

with tab3:
    st.subheader("Operations: 2-Year S&OP Inventory Curve Overlay")
    view_prod = st.selectbox("Select Product to Graph:", ACTIVE_PRODUCTS)
    
    chart_data = []
    for w in WEEKS:
        chart_data.append({"Week": w, "Metric": "Customer Demand", "Units": int(DEMAND[view_prod][w])})
        for name, res in results.items():
            inv_val = int(get_val(res["inv"][view_prod][w]))
            chart_data.append({"Week": w, "Metric": f"Inv ({name})", "Units": inv_val})
            
    c_df = pd.DataFrame(chart_data)
    domain = ["Customer Demand"] + [f"Inv ({name})" for name in results.keys()]
    range_ = ['#FF4B4B', '#1f77b4', '#2ca02c']
    
    chart = alt.Chart(c_df).mark_line(strokeWidth=3).encode(
        x='Week:Q', y='Units:Q', color=alt.Color('Metric:N', scale=alt.Scale(domain=domain, range=range_)),
        strokeDash=alt.condition(alt.datum.Metric == 'Customer Demand', alt.value([5, 5]), alt.value([0]))
    ).properties(height=450)
    st.altair_chart(chart, use_container_width=True)

with tab4:
    st.subheader("Download Complete CFO Audit Ledger")
    excel_data = generate_cfo_ledger(results, lbo_results)
    st.download_button(
        label="📥 Download CFO Audit Ledger (.xlsx)", 
        data=excel_data, 
        file_name="LBO_Audit_Ledger.xlsx", 
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
        key="dl_cfo_ledger",
        type="primary"
    )
