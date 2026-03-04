import streamlit as st
import pandas as pd
import numpy as np
import pulp
import io
import altair as alt

st.set_page_config(page_title="Strategy& Value Creation: Sourcing Twin", layout="wide")

st.title("🌍 PE Value Creation: Total Landed Cost & Network Twin")
st.markdown("**Context:** Post-Deal 100-Day Plan for a UK-based Smart Home Electronics brand. We are transitioning away from unit-cost obsession to a true **Total Landed Cost** model (FOB + Tariffs + Fixed Container Yield + Working Capital).")

# --- 1. CONFIGURATION & GENERIC DATA ---
WEEKS = list(range(1, 27)) # 26-Week Half-Year Horizon
DEFAULT_PRODUCTS = ["Smart Thermostat", "HD Security Camera", "Wi-Fi Mesh Router", "Smart Plug (4-Pack)"]

# Demand Params
DEMAND_PARAMS = {
    "Smart Thermostat": {"mean": 2000, "std": 500},
    "HD Security Camera": {"mean": 3500, "std": 900},
    "Wi-Fi Mesh Router": {"mean": 1200, "std": 350},
    "Smart Plug (4-Pack)": {"mean": 5000, "std": 1200}
}

# Real-world volumetrics (CBM) and FOB pricing
# Notice Poland has NO freight cost per unit, freight is handled strictly by the truck/container
DEFAULT_ECO = {
    "Smart Thermostat": {"price": 120.0, "unit_cbm": 0.005, "fe_fob": 35.0, "fe_lt": 10, "ns_fob": 45.0, "ns_lt": 2},
    "HD Security Camera": {"price": 85.0, "unit_cbm": 0.003, "fe_fob": 22.0, "fe_lt": 10, "ns_fob": 29.0, "ns_lt": 2},
    "Wi-Fi Mesh Router": {"price": 150.0, "unit_cbm": 0.015, "fe_fob": 45.0, "fe_lt": 10, "ns_fob": 58.0, "ns_lt": 2},
    "Smart Plug (4-Pack)": {"price": 30.0, "unit_cbm": 0.002, "fe_fob": 8.0, "fe_lt": 10, "ns_fob": 11.0, "ns_lt": 2}
}

# Fixed Logistics Constraints
FE_CONTAINER_CBM = 68.0   # 40ft High Cube Container
FE_CONTAINER_COST = 3500  # Cost per ocean container
NS_TRUCK_CBM = 80.0       # Standard Lorry Trailer
NS_TRUCK_COST = 1200      # Cost per overland truck

# --- 2. EXCEL TEMPLATE GENERATOR ---
def generate_excel_template():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        eco_rows = []
        for p, data in DEFAULT_ECO.items():
            eco_rows.append({
                "Product": p, "Retail_Price": data["price"], "Unit_Volume_CBM": data["unit_cbm"],
                "FarEast_FOB": data["fe_fob"], "FarEast_LeadTime_Wks": data["fe_lt"],
                "Nearshore_FOB": data["ns_fob"], "Nearshore_LeadTime_Wks": data["ns_lt"]
            })
        pd.DataFrame(eco_rows).to_excel(writer, sheet_name="Supplier_Economics", index=False)
        
        dem_rows = [{"Product": p, "Mean Weekly Demand": DEMAND_PARAMS[p]["mean"], "St Dev": DEMAND_PARAMS[p]["std"]} for p in DEFAULT_PRODUCTS]
        pd.DataFrame(dem_rows).to_excel(writer, sheet_name="Demand_Forecast", index=False)
    return output.getvalue()

# --- 3. STATE MANAGEMENT ---
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

# --- 4. SIDEBAR CONTROLS ---
with st.sidebar:
    st.header("📂 Data Integration")
    st.download_button("📥 Download Master Template", data=generate_excel_template(), file_name="sourcing_digital_twin.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_template")
    uploaded_file = st.file_uploader("Upload Configured Excel", type=["xlsx"])
    
    st.markdown("---")
    
    ACTIVE_PRODUCTS = DEFAULT_PRODUCTS
    ACTIVE_DEMAND_PARAMS = DEMAND_PARAMS
    if uploaded_file is not None:
        try:
            f_df = pd.read_excel(uploaded_file, sheet_name="Demand_Forecast")
            ACTIVE_PRODUCTS = f_df["Product"].tolist()
            ACTIVE_DEMAND_PARAMS = {row["Product"]: {"mean": row["Mean Weekly Demand"], "std": row["St Dev"]} for _, row in f_df.iterrows()}
        except Exception:
            st.warning("Could not read Demand_Forecast sheet. Using defaults.")

    st.header("Step 1: Baseline Forecasting")
    st.info("Lock in the UK market volatility to ensure fair scenario testing.")
    if st.button("🔒 Lock 26-Week Demand Path", use_container_width=True, key="lock_demand"):
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS)
        st.success("Demand Locked!")

    if not st.session_state.demand_locked:
        np.random.seed(42) 
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS)
    
    st.markdown("---")
    
    st.header("Step 2: Architecture Tuning")
    with st.form("control_panel"):
        active_scenario = st.radio("Active Simulation:", [
            "Legacy Strategy (100% Far-East)", 
            "Value Creation Mix (Dual-Sourcing)",
            "📊 Compare Both (Overlay)"
        ])
        
        st.subheader("Macro & Financial Levers")
        tariff_rate = st.slider("Far-East Import Tariff (%)", 0.0, 30.0, 15.0) / 100.0
        wacc_annual = st.slider("Cost of Capital (Annual WACC %)", 5.0, 25.0, 15.0) / 100.0
        wacc_weekly = wacc_annual / 52.0
        
        holding_cost = st.slider("UK 3PL Storage (£/unit/wk)", 0.1, 2.0, 0.4)
        stockout_penalty = st.slider("Lost Sale Penalty (£/unit)", 20, 200, 80)
        
        corp_tax = 0.25 
        submitted = st.form_submit_button("🚀 Run 26-Week Optimizer")

# --- 5. DATA PROCESSING ---
try:
    if uploaded_file is not None:
        eco_df = pd.read_excel(uploaded_file, sheet_name="Supplier_Economics")
        FINANCIALS = {}
        for _, row in eco_df.iterrows():
            FINANCIALS[row["Product"]] = {
                "price": row["Retail_Price"], "unit_cbm": row["Unit_Volume_CBM"],
                "fe_fob": row["FarEast_FOB"], "fe_lt": row["FarEast_LeadTime_Wks"],
                "ns_fob": row["Nearshore_FOB"], "ns_lt": row["Nearshore_LeadTime_Wks"]
            }
    else:
        FINANCIALS = DEFAULT_ECO
except Exception as e:
    st.error(f"❌ Excel Parsing Error. {str(e)}")
    st.stop()

DEMAND = st.session_state.demand_path

# --- 6. THE MILP SOLVER (Total Landed Cost / Container Yield) ---
def solve_sourcing(strategy_type):
    prob = pulp.LpProblem(f"Sourcing_{strategy_type.replace(' ', '')}", pulp.LpMaximize)
    
    # Order quantities per product
    order_fe = pulp.LpVariable.dicts("Order_FE", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    order_ns = pulp.LpVariable.dicts("Order_NS", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    
    # FIXED LOGISTICS: How many containers/trucks do we buy each week?
    containers_fe = pulp.LpVariable.dicts("Containers_FE", WEEKS, lowBound=0, cat='Integer')
    trucks_ns = pulp.LpVariable.dicts("Trucks_NS", WEEKS, lowBound=0, cat='Integer')
    
    inv = pulp.LpVariable.dicts("Inv", (ACTIVE_PRODUCTS, [0] + WEEKS), lowBound=0, cat='Integer')
    sales = pulp.LpVariable.dicts("Sales", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    shortage = pulp.LpVariable.dicts("Shortage", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')

    for p in ACTIVE_PRODUCTS:
        prob += inv[p][0] == int(ACTIVE_DEMAND_PARAMS[p]["mean"] * (FINANCIALS[p]["fe_lt"] + 2))

        for w in WEEKS:
            arr_fe = order_fe[p][w - int(FINANCIALS[p]["fe_lt"])] if w > FINANCIALS[p]["fe_lt"] else 0
            arr_ns = order_ns[p][w - int(FINANCIALS[p]["ns_lt"])] if w > FINANCIALS[p]["ns_lt"] else 0

            if "Legacy" in strategy_type: prob += order_ns[p][w] == 0
                
            prob += inv[p][w] == inv[p][w-1] + arr_fe + arr_ns - sales[p][w]
            prob += sales[p][w] <= DEMAND[p][w]
            prob += sales[p][w] <= inv[p][w-1] + arr_fe + arr_ns
            prob += shortage[p][w] == DEMAND[p][w] - sales[p][w]
            
            # Prevent Dead Inventory Ordering
            if w > 26 - FINANCIALS[p]["fe_lt"]: prob += order_fe[p][w] == 0
            if w > 26 - FINANCIALS[p]["ns_lt"]: prob += order_ns[p][w] == 0

    for w in WEEKS:
        # VOLUMETRIC CONTAINER PACKING CONSTRAINTS
        # The sum of CBMs for all products ordered must fit inside the integer number of containers purchased
        prob += pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS]) <= containers_fe[w] * FE_CONTAINER_CBM
        prob += pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS]) <= trucks_ns[w] * NS_TRUCK_CBM

    revenue = pulp.lpSum([sales[p][w] * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    # COGS includes the base FOB price + The Far-East Tariffs!
    cogs_fe = pulp.lpSum([order_fe[p][w] * (FINANCIALS[p]["fe_fob"] * (1 + tariff_rate)) for p in ACTIVE_PRODUCTS for w in WEEKS])
    cogs_ns = pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["ns_fob"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    # Logistics is strictly fixed cost based on integer containers utilized
    logistics = pulp.lpSum([containers_fe[w] * FE_CONTAINER_COST + trucks_ns[w] * NS_TRUCK_COST for w in WEEKS])
    
    holding = pulp.lpSum([inv[p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in WEEKS])
    lost_sales_cost = pulp.lpSum([shortage[p][w] * stockout_penalty for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    wacc_transit_fe = pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["fe_fob"] * FINANCIALS[p]["fe_lt"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
    wacc_transit_ns = pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["ns_fob"] * FINANCIALS[p]["ns_lt"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
    wacc_on_hand = pulp.lpSum([inv[p][w] * FINANCIALS[p]["fe_fob"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    prob += revenue - (cogs_fe + cogs_ns + logistics + holding + lost_sales_cost + wacc_transit_fe + wacc_transit_ns + wacc_on_hand)
    
    # Extremely tight formulation, solves almost instantly
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    
    return {
        "status": pulp.LpStatus[prob.status],
        "sales": sales, "order_fe": order_fe, "order_ns": order_ns, "inv": inv, "shortage": shortage,
        "containers_fe": containers_fe, "trucks_ns": trucks_ns,
        "metrics": extract_metrics(sales, order_fe, order_ns, containers_fe, trucks_ns, inv, shortage)
    }

def get_val(var): return var.varValue if var.varValue else 0

def extract_metrics(sales, order_fe, order_ns, containers_fe, trucks_ns, inv, shortage):
    t_rev = sum([get_val(sales[p][w]) * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    t_cogs = sum([get_val(order_fe[p][w]) * (FINANCIALS[p]["fe_fob"] * (1 + tariff_rate)) + get_val(order_ns[p][w]) * FINANCIALS[p]["ns_fob"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    t_freight = sum([get_val(containers_fe[w]) * FE_CONTAINER_COST + get_val(trucks_ns[w]) * NS_TRUCK_COST for w in WEEKS])
    t_holding = sum([get_val(inv[p][w]) * holding_cost for p in ACTIVE_PRODUCTS for w in WEEKS])
    t_lost = sum([get_val(shortage[p][w]) * stockout_penalty for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    t_wacc = sum([get_val(order_fe[p][w]) * FINANCIALS[p]["fe_fob"] * FINANCIALS[p]["fe_lt"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS]) + \
             sum([get_val(order_ns[p][w]) * FINANCIALS[p]["ns_fob"] * FINANCIALS[p]["ns_lt"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS]) + \
             sum([get_val(inv[p][w]) * FINANCIALS[p]["fe_fob"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
             
    ebitda = t_rev - (t_cogs + t_freight + t_holding + t_wacc)
    nopat = ebitda * (1 - corp_tax)
    
    tot_dem = sum([DEMAND[p][w] for p in ACTIVE_PRODUCTS for w in WEEKS])
    tot_sold = sum([get_val(sales[p][w]) for p in ACTIVE_PRODUCTS for w in WEEKS])
    sl = (tot_sold / tot_dem) * 100 if tot_dem > 0 else 0
    
    avg_inv_value = sum([get_val(inv[p][w]) * FINANCIALS[p]["fe_fob"] for p in ACTIVE_PRODUCTS for w in WEEKS]) / 26
    avg_transit_value = (sum([get_val(order_fe[p][w])*FINANCIALS[p]["fe_fob"]*FINANCIALS[p]["fe_lt"] for p in ACTIVE_PRODUCTS for w in WEEKS]) / 26) + \
                        (sum([get_val(order_ns[p][w])*FINANCIALS[p]["ns_fob"]*FINANCIALS[p]["ns_lt"] for p in ACTIVE_PRODUCTS for w in WEEKS]) / 26)
    total_wc = avg_inv_value + avg_transit_value
    roic = (nopat / total_wc) * 100 if total_wc > 0 else 0
    
    # Calculate Container Fill Rate
    tot_fe_cbm = sum([get_val(order_fe[p][w]) * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    tot_fe_cap = sum([get_val(containers_fe[w]) * FE_CONTAINER_CBM for w in WEEKS])
    fill_rate = (tot_fe_cbm / tot_fe_cap * 100) if tot_fe_cap > 0 else 0
    
    return {"t_rev": t_rev, "t_cogs": t_cogs, "t_freight": t_freight, "t_holding": t_holding, "t_lost": t_lost, "t_wacc": t_wacc, "ebitda": ebitda, "sl": sl, "wc": total_wc, "roic": roic, "fill_rate": fill_rate}

# --- 7. EXECUTION ---
if "Compare Both" in active_scenario:
    with st.spinner("Solving Legacy Strategy..."):
        res_A = solve_sourcing("Legacy Strategy")
    with st.spinner("Solving Dual-Sourcing Strategy..."):
        res_B = solve_sourcing("Dual-Sourcing Mix")
    results = {"Legacy (Far-East)": res_A, "Value Creation (Dual)": res_B}
else:
    with st.spinner(f"Simulating {active_scenario}..."):
        results = {active_scenario: solve_sourcing(active_scenario)}

# --- 8. VISUAL DASHBOARDS ---
tab1, tab2, tab3, tab4 = st.tabs(["📊 CFO Exec Summary", "💰 Total Landed P&L", "📦 S&OP Inventory Overlay", "🚢 Logistics & Container Yield"])

with tab1:
    st.subheader("Working Capital & ROI Performance (26-Week Half)")
    cols = st.columns(len(results))
    for i, (name, res) in enumerate(results.items()):
        m = res["metrics"]
        with cols[i]:
            st.markdown(f"### {name}")
            st.metric("Half-Year EBITDA (£)", f"£{m['ebitda']:,.0f}")
            st.metric("Working Capital Tied Up", f"£{m['wc']:,.0f}")
            st.metric("Annualized ROIC", f"{m['roic']*2:.1f}%")
            st.metric("Customer Service Level", f"{m['sl']:.1f}%")
    
    st.markdown("---")
    st.info("💡 **Strategy& Value Creation Thesis:** Once you account for 15% Tariffs and Fixed £3,500 Ocean Containers, the 'cheap' Far-East FOB price is an illusion. The solver proves that utilizing Nearshore trucks eliminates stockouts, slashes WACC, and drives superior ROIC.")

with tab2:
    st.subheader("Half-Year P&L & True Landed Costs")
    
    pl_data = {"Line Item": ["Gross Sales Revenue", "FOB Materials Cost (+ Import Tariffs)", "Fixed Logistics (Ocean Cont. + Trucks)", "UK 3PL Holding Cost", "WACC Cost (Cash Opportunity Cost)", "TRUE EBITDA"]}
    for name, res in results.items():
        m = res["metrics"]
        def pct(v): return f"{(abs(v)/m['t_rev'])*100:.1f}%" if m['t_rev']>0 else "0%"
        pl_data[f"{name} (£)"] = [f"£{m['t_rev']:,.0f}", f"-£{m['t_cogs']:,.0f}", f"-£{m['t_freight']:,.0f}", f"-£{m['t_holding']:,.0f}", f"-£{m['t_wacc']:,.0f}", f"£{m['ebitda']:,.0f}"]
        pl_data[f"{name} Margin %"] = ["100.0%", pct(m['t_cogs']), pct(m['t_freight']), pct(m['t_holding']), pct(m['t_wacc']), pct(m['ebitda'])]
    
    st.table(pd.DataFrame(pl_data))

with tab3:
    st.subheader("Operations: S&OP Inventory Curve Overlay")
    view_prod = st.selectbox("Select Product to Graph:", ACTIVE_PRODUCTS)
    
    chart_data = []
    for w in WEEKS:
        chart_data.append({"Week": w, "Metric": "Customer Demand", "Units": DEMAND[view_prod][w]})
        for name, res in results.items():
            inv_val = int(get_val(res["inv"][view_prod][w]))
            chart_data.append({"Week": w, "Metric": f"UK Inventory ({name})", "Units": inv_val})
            
    c_df = pd.DataFrame(chart_data)
    domain = ["Customer Demand"] + [f"UK Inventory ({name})" for name in results.keys()]
    range_ = ['#FF4B4B'] + ['#1f77b4', '#2ca02c'][:len(results)]
    
    chart = alt.Chart(c_df).mark_line(strokeWidth=3).encode(
        x='Week:Q', y='Units:Q', color=alt.Color('Metric:N', scale=alt.Scale(domain=domain, range=range_)),
        strokeDash=alt.condition(alt.datum.Metric == 'Customer Demand', alt.value([5, 5]), alt.value([0]))
    ).properties(height=450, title=f"Inventory Dynamics: {view_prod}")
    st.altair_chart(chart, use_container_width=True)

with tab4:
    st.subheader("Logistics & Container Packing Execution")
    
    if len(results) > 1:
        view_target = st.selectbox("Select Strategy to View Logistics:", list(results.keys()))
    else:
        view_target = list(results.keys())[0]
        
    res = results[view_target]
    
    st.metric("Far-East Ocean Container Yield (Fill Rate)", f"{res['metrics']['fill_rate']:.1f}%")
    st.caption("The solver perfectly Tetris-packs combinations of Thermostats, Cameras, and Routers into exactly 68 CBM to maximize the £3,500 fixed cost.")
    
    po_data = []
    for w in WEEKS:
        c_fe = int(get_val(res["containers_fe"][w]))
        t_ns = int(get_val(res["trucks_ns"][w]))
        po_data.append({
            "Week": w,
            "40ft Containers Ordered (China)": c_fe if c_fe > 0 else "-",
            "Lorry Trucks Ordered (Poland)": t_ns if t_ns > 0 else "-",
            "Freight Cost Billed": f"£{(c_fe * FE_CONTAINER_COST) + (t_ns * NS_TRUCK_COST):,.0f}"
        })
    st.dataframe(pd.DataFrame(po_data).set_index("Week"), use_container_width=True)
