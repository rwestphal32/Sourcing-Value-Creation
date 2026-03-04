import streamlit as st
import pandas as pd
import numpy as np
import pulp
import io
import altair as alt

st.set_page_config(page_title="PwC Strategy& Value Creation: Sourcing Twin", layout="wide")

st.title("🌍 PE Value Creation: Strategic Sourcing & Working Capital Twin")
st.markdown("**Context:** Post-Deal 100-Day Plan for a UK-based Wholesaler. Evaluate shifting from a 100% Far-East (Shenzhen) supply chain to a Dual-Sourcing mix (Shenzhen + Nearshore Warsaw) to optimize Working Capital and Service Level.")

# --- 1. CONFIGURATION & GENERIC DATA ---
WEEKS = list(range(1, 53))
DEFAULT_PRODUCTS = ["Lifting Straps", "Weight Belts", "Knee Sleeves", "Gloves"]

# Default Demand Params
DEMAND_PARAMS = {
    "Lifting Straps": {"mean": 3252, "std": 600},
    "Weight Belts": {"mean": 1800, "std": 450},
    "Knee Sleeves": {"mean": 1000, "std": 300},
    "Gloves": {"mean": 3000, "std": 800}
}

# Supplier Economics (Far-East vs Nearshore)
DEFAULT_ECO = {
    "Lifting Straps": {"price": 15.0, "fe_fob": 3.0, "fe_freight": 0.5, "fe_lt": 10, "fe_moq": 15000, "ns_fob": 4.2, "ns_freight": 0.2, "ns_lt": 2, "ns_moq": 1000},
    "Weight Belts": {"price": 45.0, "fe_fob": 12.0, "fe_freight": 1.5, "fe_lt": 10, "fe_moq": 8000, "ns_fob": 16.0, "ns_freight": 0.8, "ns_lt": 2, "ns_moq": 500},
    "Knee Sleeves": {"price": 35.0, "fe_fob": 8.0, "fe_freight": 0.8, "fe_lt": 10, "fe_moq": 5000, "ns_fob": 11.5, "ns_freight": 0.4, "ns_lt": 2, "ns_moq": 500},
    "Gloves": {"price": 20.0, "fe_fob": 4.0, "fe_freight": 0.4, "fe_lt": 10, "fe_moq": 15000, "ns_fob": 5.8, "ns_freight": 0.2, "ns_lt": 2, "ns_moq": 1000}
}

# --- 2. EXCEL TEMPLATE GENERATOR ---
def generate_excel_template():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        eco_rows = []
        for p, data in DEFAULT_ECO.items():
            eco_rows.append({
                "Product": p, "Retail_Price": data["price"], 
                "FarEast_FOB": data["fe_fob"], "FarEast_Freight": data["fe_freight"], "FarEast_LeadTime_Wks": data["fe_lt"], "FarEast_MOQ": data["fe_moq"],
                "Nearshore_FOB": data["ns_fob"], "Nearshore_Freight": data["ns_freight"], "Nearshore_LeadTime_Wks": data["ns_lt"], "Nearshore_MOQ": data["ns_moq"]
            })
        pd.DataFrame(eco_rows).to_excel(writer, sheet_name="Supplier_Economics", index=False)
        
        dem_rows = [{"Product": p, "Mean Weekly Demand": DEMAND_PARAMS[p]["mean"], "St Dev": DEMAND_PARAMS[p]["std"]} for p in DEFAULT_PRODUCTS]
        pd.DataFrame(dem_rows).to_excel(writer, sheet_name="Demand_Forecast", index=False)
    return output.getvalue()

# --- 3. STATE MANAGEMENT FOR APPLES-TO-APPLES DEMAND ---
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
    st.download_button("📥 Download Master Template", data=generate_excel_template(), file_name="sourcing_digital_twin.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_sourcing_template")
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
    if st.button("🔒 Lock 52-Week Demand Path", use_container_width=True, key="lock_demand_btn"):
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
        
        st.subheader("Financial Levers")
        wacc_annual = st.slider("Cost of Capital (Annual WACC %)", 5.0, 25.0, 12.0) / 100.0
        wacc_weekly = wacc_annual / 52.0
        
        holding_cost = st.slider("UK 3PL Storage (£/unit/wk)", 0.1, 1.0, 0.2)
        stockout_penalty = st.slider("Lost Sale Penalty (£/unit)", 10, 100, 40)
        
        corp_tax = 0.25 
        submitted = st.form_submit_button("🚀 Run 52-Week Optimizer")

# --- 5. DATA PROCESSING ---
try:
    if uploaded_file is not None:
        eco_df = pd.read_excel(uploaded_file, sheet_name="Supplier_Economics")
        FINANCIALS = {}
        for _, row in eco_df.iterrows():
            FINANCIALS[row["Product"]] = {
                "price": row["Retail_Price"], 
                "fe_fob": row["FarEast_FOB"], "fe_freight": row["FarEast_Freight"], "fe_lt": row["FarEast_LeadTime_Wks"], "fe_moq": row["FarEast_MOQ"],
                "ns_fob": row["Nearshore_FOB"], "ns_freight": row["Nearshore_Freight"], "ns_lt": row["Nearshore_LeadTime_Wks"], "ns_moq": row["Nearshore_MOQ"]
            }
    else:
        FINANCIALS = DEFAULT_ECO
except Exception as e:
    st.error(f"❌ Excel Parsing Error. {str(e)}")
    st.stop()

DEMAND = st.session_state.demand_path

# --- 6. THE MILP SOLVER ---
def solve_sourcing(strategy_type):
    prob = pulp.LpProblem(f"Sourcing_{strategy_type.replace(' ', '')}", pulp.LpMaximize)
    
    order_fe = pulp.LpVariable.dicts("Order_FE", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    order_fe_bin = pulp.LpVariable.dicts("Order_FE_Bin", (ACTIVE_PRODUCTS, WEEKS), cat='Binary')
    
    order_ns = pulp.LpVariable.dicts("Order_NS", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    order_ns_bin = pulp.LpVariable.dicts("Order_NS_Bin", (ACTIVE_PRODUCTS, WEEKS), cat='Binary')
    
    inv = pulp.LpVariable.dicts("Inv", (ACTIVE_PRODUCTS, [0] + WEEKS), lowBound=0, cat='Integer')
    sales = pulp.LpVariable.dicts("Sales", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    shortage = pulp.LpVariable.dicts("Shortage", (ACTIVE_PRODUCTS, WEEKS), lowBound=0, cat='Integer')
    
    BIG_M = 1000000

    for p in ACTIVE_PRODUCTS:
        # Starting inventory required to survive the initial Far-East lead time pipeline
        prob += inv[p][0] == int(ACTIVE_DEMAND_PARAMS[p]["mean"] * FINANCIALS[p]["fe_lt"] * 1.1)

        def arr_fe(w):
            lt = int(FINANCIALS[p]["fe_lt"])
            if w <= lt: return int(ACTIVE_DEMAND_PARAMS[p]["mean"]) # Pipeline arriving
            return order_fe[p][w - lt]
            
        def arr_ns(w):
            lt = int(FINANCIALS[p]["ns_lt"])
            if w <= lt: return 0
            return order_ns[p][w - lt]

        for w in WEEKS:
            # MOQ Constraints
            prob += order_fe[p][w] >= FINANCIALS[p]["fe_moq"] * order_fe_bin[p][w]
            prob += order_fe[p][w] <= BIG_M * order_fe_bin[p][w]
            
            prob += order_ns[p][w] >= FINANCIALS[p]["ns_moq"] * order_ns_bin[p][w]
            prob += order_ns[p][w] <= BIG_M * order_ns_bin[p][w]
            
            if "Legacy" in strategy_type:
                prob += order_ns[p][w] == 0
                
            prob += inv[p][w] == inv[p][w-1] + arr_fe(w) + arr_ns(w) - sales[p][w]
            prob += sales[p][w] <= DEMAND[p][w]
            prob += sales[p][w] <= inv[p][w-1] + arr_fe(w) + arr_ns(w)
            prob += shortage[p][w] == DEMAND[p][w] - sales[p][w]

    revenue = pulp.lpSum([sales[p][w] * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    cogs = pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["fe_fob"] + order_ns[p][w] * FINANCIALS[p]["ns_fob"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    freight = pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["fe_freight"] + order_ns[p][w] * FINANCIALS[p]["ns_freight"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    holding = pulp.lpSum([inv[p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in WEEKS])
    lost_sales_cost = pulp.lpSum([shortage[p][w] * stockout_penalty for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    # Working Capital Costs
    wacc_transit_fe = pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["fe_fob"] * FINANCIALS[p]["fe_lt"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
    wacc_transit_ns = pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["ns_fob"] * FINANCIALS[p]["ns_lt"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
    wacc_on_hand = pulp.lpSum([inv[p][w] * FINANCIALS[p]["fe_fob"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    prob += revenue - (cogs + freight + holding + lost_sales_cost + wacc_transit_fe + wacc_transit_ns + wacc_on_hand)
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    
    return {
        "status": pulp.LpStatus[prob.status],
        "sales": sales, "order_fe": order_fe, "order_ns": order_ns, "inv": inv, "shortage": shortage,
        "metrics": extract_metrics(sales, order_fe, order_ns, inv, shortage)
    }

def get_val(var): return var.varValue if var.varValue else 0

def extract_metrics(sales, order_fe, order_ns, inv, shortage):
    t_rev = sum([get_val(sales[p][w]) * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    t_cogs = sum([get_val(order_fe[p][w]) * FINANCIALS[p]["fe_fob"] + get_val(order_ns[p][w]) * FINANCIALS[p]["ns_fob"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    t_freight = sum([get_val(order_fe[p][w]) * FINANCIALS[p]["fe_freight"] + get_val(order_ns[p][w]) * FINANCIALS[p]["ns_freight"] for p in ACTIVE_PRODUCTS for w in WEEKS])
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
    
    avg_inv_value = sum([get_val(inv[p][w]) * FINANCIALS[p]["fe_fob"] for p in ACTIVE_PRODUCTS for w in WEEKS]) / 52
    avg_transit_value = (sum([get_val(order_fe[p][w])*FINANCIALS[p]["fe_fob"]*FINANCIALS[p]["fe_lt"] for p in ACTIVE_PRODUCTS for w in WEEKS]) / 52) + \
                        (sum([get_val(order_ns[p][w])*FINANCIALS[p]["ns_fob"]*FINANCIALS[p]["ns_lt"] for p in ACTIVE_PRODUCTS for w in WEEKS]) / 52)
    total_wc = avg_inv_value + avg_transit_value
    roic = (nopat / total_wc) * 100 if total_wc > 0 else 0
    
    return {"t_rev": t_rev, "t_cogs": t_cogs, "t_freight": t_freight, "t_holding": t_holding, "t_lost": t_lost, "t_wacc": t_wacc, "ebitda": ebitda, "nopat": nopat, "sl": sl, "wc": total_wc, "roic": roic}

# --- 7. EXECUTION ---
if "Compare Both" in active_scenario:
    with st.spinner("Simulating Legacy 100% Far-East Strategy..."):
        res_A = solve_sourcing("Legacy Strategy")
    with st.spinner("Simulating Value Creation Dual-Sourcing..."):
        res_B = solve_sourcing("Dual-Sourcing Mix")
    results = {"Legacy (Far-East)": res_A, "Value Creation (Dual)": res_B}
else:
    with st.spinner(f"Simulating {active_scenario}..."):
        results = {active_scenario: solve_sourcing(active_scenario)}

# --- 8. VISUAL DASHBOARDS ---
tab1, tab2, tab3, tab4 = st.tabs(["📊 CFO Exec Summary", "💰 Total Landed P&L", "📦 Inventory Overlay", "🚢 PO Schedule"])

with tab1:
    st.subheader("Working Capital & ROI Performance")
    
    # Render metrics side-by-side if comparison mode
    cols = st.columns(len(results))
    for i, (name, res) in enumerate(results.items()):
        m = res["metrics"]
        with cols[i]:
            st.markdown(f"### {name}")
            st.metric("Annual EBITDA (£)", f"£{m['ebitda']:,.0f}")
            st.metric("Working Capital Tied Up", f"£{m['wc']:,.0f}")
            st.metric("Annualized ROIC", f"{m['roic']:.1f}%")
            st.metric("Customer Service Level", f"{m['sl']:.1f}%")
    
    st.markdown("---")
    st.info("💡 **Strategy& Value Creation Thesis:** By blending cheaper Far-East supply with agile Nearshore supply, the business can drastically reduce safety stock and in-transit cash, eliminating lost sales and yielding a significantly higher Return on Invested Capital (ROIC).")

with tab2:
    st.subheader("Annual P&L & Landed Costs")
    
    pl_data = {"Line Item": ["Gross Sales Revenue", "FOB Materials Cost", "Freight Cost (Ocean + Truck)", "UK 3PL Holding Cost", "WACC Cost (Cash Opportunity Cost)", "EBITDA"]}
    for name, res in results.items():
        m = res["metrics"]
        def pct(v): return f"{(abs(v)/m['t_rev'])*100:.1f}%" if m['t_rev']>0 else "0%"
        pl_data[f"{name} (£)"] = [f"£{m['t_rev']:,.0f}", f"-£{m['t_cogs']:,.0f}", f"-£{m['t_freight']:,.0f}", f"-£{m['t_holding']:,.0f}", f"-£{m['t_wacc']:,.0f}", f"£{m['ebitda']:,.0f}"]
        pl_data[f"{name} Margin %"] = ["100.0%", pct(m['t_cogs']), pct(m['t_freight']), pct(m['t_holding']), pct(m['t_wacc']), pct(m['ebitda'])]
    
    st.table(pd.DataFrame(pl_data))
    
    for name, res in results.items():
        st.write(f"**{name}** -> Avoidable Value Leakage (Stockouts): £{res['metrics']['t_lost']:,.0f}")

with tab3:
    st.subheader("Operations: Total Inventory Cushion Overlay")
    
    chart_data = []
    # Aggregate total demand and inventory across all products for the chart
    for w in WEEKS:
        tot_dem = sum([DEMAND[p][w] for p in ACTIVE_PRODUCTS])
        chart_data.append({"Week": w, "Metric": "Total Customer Demand", "Units": tot_dem})
        
        for name, res in results.items():
            tot_inv = sum([get_val(res["inv"][p][w]) for p in ACTIVE_PRODUCTS])
            chart_data.append({"Week": w, "Metric": f"UK Inventory ({name})", "Units": int(tot_inv)})
    
    c_df = pd.DataFrame(chart_data)
    
    # Custom color mapping to ensure Demand is distinct
    domain = ["Total Customer Demand"] + [f"UK Inventory ({name})" for name in results.keys()]
    range_ = ['#FF4B4B'] + ['#1f77b4', '#2ca02c'][:len(results)]
    
    chart = alt.Chart(c_df).mark_line(strokeWidth=3).encode(
        x='Week:Q', 
        y='Units:Q', 
        color=alt.Color('Metric:N', scale=alt.Scale(domain=domain, range=range_)),
        strokeDash=alt.condition(alt.datum.Metric == 'Total Customer Demand', alt.value([5, 5]), alt.value([0]))
    ).properties(height=450, title="UK Warehouse Stock vs. Customer Demand Volatility")
    st.altair_chart(chart, use_container_width=True)

with tab4:
    st.subheader("Optimal PO Routing Schedule")
    
    # If in compare mode, select which one to view
    if len(results) > 1:
        view_target = st.selectbox("Select Strategy to View Schedule:", list(results.keys()))
    else:
        view_target = list(results.keys())[0]
        
    res = results[view_target]
    prod_target = st.selectbox("Select Product to Audit:", ACTIVE_PRODUCTS)
    
    po_data = []
    for w in WEEKS:
        fe_val = int(get_val(res["order_fe"][prod_target][w]))
        ns_val = int(get_val(res["order_ns"][prod_target][w]))
        po_data.append({
            "Week": w,
            "UK Demand": DEMAND[prod_target][w],
            "PO -> Far-East": fe_val if fe_val > 0 else "-",
            "PO -> Nearshore": ns_val if ns_val > 0 else "-",
            "Ending UK Inv": int(get_val(res["inv"][prod_target][w])),
            "Lost Sales": int(get_val(res["shortage"][prod_target][w]))
        })
    st.dataframe(pd.DataFrame(po_data).set_index("Week"), use_container_width=True)
    
    st.markdown("---")
    st.download_button(label="📥 Download This Schedule (CSV)", data=pd.DataFrame(po_data).to_csv(index=False).encode('utf-8'), file_name=f"po_schedule_{view_target.replace(' ', '_')}.csv", mime="text/csv", key="dl_po_schedule")
