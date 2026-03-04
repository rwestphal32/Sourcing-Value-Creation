import streamlit as st
import pandas as pd
import numpy as np
import pulp
import io
import altair as alt

st.set_page_config(page_title="Strategy& Value Creation: Sourcing Twin", layout="wide")

st.title("🌍 PE Value Creation: Total Landed Cost & Network Twin")
st.markdown("**Context:** Post-Deal 100-Day Plan for a UK-based Smart Home Electronics brand. Moving from Unit-Cost obsession to a Total Landed Cost model (FOB + Tariffs + Container Yield + Working Capital).")

# --- 1. CONFIGURATION & REALISTIC DATA ---
WEEKS = list(range(1, 27)) # 26-Week Half-Year Horizon
DEFAULT_PRODUCTS = ["Smart Thermostat", "HD Security Camera", "Wi-Fi Mesh Router", "Smart Plug (4-Pack)"]

# Demand Params
DEMAND_PARAMS = {
    "Smart Thermostat": {"mean": 2000, "std": 450},
    "HD Security Camera": {"mean": 3500, "std": 800},
    "Wi-Fi Mesh Router": {"mean": 1200, "std": 300},
    "Smart Plug (4-Pack)": {"mean": 5000, "std": 1000}
}

# REALISTIC ECONOMICS: Narrower FOB gap, realistic CBMs
DEFAULT_ECO = {
    "Smart Thermostat": {"price": 120.0, "unit_cbm": 0.005, "fe_fob": 35.0, "fe_lt": 10, "ns_fob": 39.0, "ns_lt": 2},
    "HD Security Camera": {"price": 85.0, "unit_cbm": 0.003, "fe_fob": 22.0, "fe_lt": 10, "ns_fob": 25.0, "ns_lt": 2},
    "Wi-Fi Mesh Router": {"price": 150.0, "unit_cbm": 0.015, "fe_fob": 45.0, "fe_lt": 10, "ns_fob": 51.0, "ns_lt": 2},
    "Smart Plug (4-Pack)": {"price": 30.0, "unit_cbm": 0.002, "fe_fob": 8.0, "fe_lt": 10, "ns_fob": 10.0, "ns_lt": 2}
}

# Real-world Logistics Constraints (Post-Red Sea Crisis)
FE_CONTAINER_CBM = 68.0   
FE_CONTAINER_COST = 6500  # China -> UK Ocean (40ft HC)
NS_TRUCK_CBM = 80.0       
NS_TRUCK_COST = 2500      # Poland -> UK Lorry

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

# --- 3. CFO LEDGER EXPORT ENGINE ---
def generate_cfo_ledger(results_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # 1. Executive KPI Summary
        kpi_data = []
        for name, res in results_dict.items():
            m = res["metrics"]
            kpi_data.append({
                "Strategy": name, "EBITDA": m["ebitda"], "Avg Working Capital": m["wc"], 
                "Annualized ROIC (%)": m["roic"]*2, "Service Level (%)": m["sl"], 
                "Total Sales": m["t_rev"], "Total COGS": m["t_cogs"], "Total Logistics": m["t_freight"], 
                "Total 3PL Holding": m["t_holding"], "Total WACC Cost": m["t_wacc"], "Lost Sales Cost": m["t_lost"]
            })
        pd.DataFrame(kpi_data).to_excel(writer, sheet_name="Executive_KPIs", index=False)
        
        # 2. Detailed Data per Strategy
        for name, res in results_dict.items():
            prefix = "Legacy_" if "Legacy" in name else "Dual_"
            
            # Logistics Ledger
            log_data = []
            for w in WEEKS:
                c_fe = int(get_val(res["containers_fe"][w]))
                t_ns = int(get_val(res["trucks_ns"][w]))
                fe_cbm = sum([get_val(res["order_fe"][p][w]) * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS])
                ns_cbm = sum([get_val(res["order_ns"][p][w]) * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS])
                log_data.append({
                    "Week": w, "China Containers Booked": c_fe, "China CBM Used": fe_cbm, "China Container Yield %": (fe_cbm/(c_fe*FE_CONTAINER_CBM))*100 if c_fe>0 else 0,
                    "Poland Trucks Booked": t_ns, "Poland CBM Used": ns_cbm, "Poland Truck Yield %": (ns_cbm/(t_ns*NS_TRUCK_CBM))*100 if t_ns>0 else 0,
                    "Total Weekly Freight Cost": (c_fe*FE_CONTAINER_COST) + (t_ns*NS_TRUCK_COST)
                })
            pd.DataFrame(log_data).to_excel(writer, sheet_name=f"{prefix}Logistics", index=False)
            
            # Product Level Ledgers
            for p in ACTIVE_PRODUCTS:
                prod_data = []
                for w in WEEKS:
                    prod_data.append({
                        "Week": w,
                        "Demand": DEMAND[p][w],
                        "Sales Fulfilled": int(get_val(res["sales"][p][w])),
                        "Lost Sales (Shortage)": int(get_val(res["shortage"][p][w])),
                        "Ending Inventory": int(get_val(res["inv"][p][w])),
                        "PO Placed to China": int(get_val(res["order_fe"][p][w])),
                        "PO Placed to Poland": int(get_val(res["order_ns"][p][w])),
                        "China Units Arriving": int(get_val(res["order_fe"][p][w - int(FINANCIALS[p]["fe_lt"])])) if w > FINANCIALS[p]["fe_lt"] else int(ACTIVE_DEMAND_PARAMS[p]["mean"]),
                        "Poland Units Arriving": int(get_val(res["order_ns"][p][w - int(FINANCIALS[p]["ns_lt"])])) if w > FINANCIALS[p]["ns_lt"] else 0,
                        "WACC Cost Incurred (£)": (int(get_val(res["inv"][p][w])) * FINANCIALS[p]["fe_fob"] * wacc_weekly)
                    })
                # Truncate sheet name to avoid Excel 31-char limit
                sheet_name = f"{prefix}{p[:20]}".replace(" ", "")
                pd.DataFrame(prod_data).to_excel(writer, sheet_name=sheet_name, index=False)
                
    return output.getvalue()

# --- 4. SIDEBAR CONTROLS ---
with st.sidebar:
    st.header("📂 Market Data")
    
    ACTIVE_PRODUCTS = DEFAULT_PRODUCTS
    ACTIVE_DEMAND_PARAMS = DEMAND_PARAMS
    FINANCIALS = DEFAULT_ECO

    st.info("Lock in the UK market volatility to ensure fair scenario testing.")
    col1, col2, col3 = st.columns([1, 4, 1])
    with col2:
        if st.button("🔒 Lock 26-Week Demand", use_container_width=True, key="lock_demand"):
            generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS)
            st.success("Locked!")

    if not st.session_state.demand_locked:
        np.random.seed(42) 
        generate_stochastic_demand(ACTIVE_PRODUCTS, ACTIVE_DEMAND_PARAMS)
    
    st.markdown("---")
    
    st.header("⚙️ Architecture Tuning")
    with st.form("control_panel"):
        active_scenario = st.radio("Active Simulation:", [
            "Legacy Strategy (100% Far-East)", 
            "Value Creation Mix (Dual-Sourcing)",
            "📊 Compare Both (Overlay)"
        ])
        
        st.subheader("Macro & Financial Levers")
        tariff_rate = st.slider("Far-East Import Tariff (%)", 0.0, 20.0, 8.0) / 100.0
        wacc_annual = st.slider("Cost of Capital (Annual WACC %)", 5.0, 25.0, 12.0) / 100.0
        wacc_weekly = wacc_annual / 52.0
        
        holding_cost = st.slider("UK 3PL Storage (£/unit/wk)", 0.05, 0.50, 0.15)
        stockout_penalty = st.slider("Lost Sale Penalty (£/unit)", 20, 150, 80)
        
        corp_tax = 0.25 
        submitted = st.form_submit_button("🚀 Run 26-Week Optimizer")

DEMAND = st.session_state.demand_path

# --- 5. THE MILP SOLVER (Total Landed Cost / Container Yield) ---
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
        # Starting inventory: exactly 11 weeks (Lead time + 1 week buffer)
        prob += inv[p][0] == int(ACTIVE_DEMAND_PARAMS[p]["mean"] * (FINANCIALS[p]["fe_lt"] + 1))

        for w in WEEKS:
            arr_fe = order_fe[p][w - int(FINANCIALS[p]["fe_lt"])] if w > FINANCIALS[p]["fe_lt"] else int(ACTIVE_DEMAND_PARAMS[p]["mean"])
            arr_ns = order_ns[p][w - int(FINANCIALS[p]["ns_lt"])] if w > FINANCIALS[p]["ns_lt"] else 0

            if "Legacy" in strategy_type: prob += order_ns[p][w] == 0
                
            prob += inv[p][w] == inv[p][w-1] + arr_fe + arr_ns - sales[p][w]
            prob += sales[p][w] <= DEMAND[p][w]
            prob += sales[p][w] <= inv[p][w-1] + arr_fe + arr_ns
            prob += shortage[p][w] == DEMAND[p][w] - sales[p][w]
            
            if w > 26 - FINANCIALS[p]["fe_lt"]: prob += order_fe[p][w] == 0
            if w > 26 - FINANCIALS[p]["ns_lt"]: prob += order_ns[p][w] == 0

    for w in WEEKS:
        prob += pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS]) <= containers_fe[w] * FE_CONTAINER_CBM
        prob += pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS]) <= trucks_ns[w] * NS_TRUCK_CBM

    revenue = pulp.lpSum([sales[p][w] * FINANCIALS[p]["price"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    # THE HORIZON FIX: Salvage Value for ending inventory (valued at 85% of FOB cost) to prevent intentional stockouts
    salvage_value = pulp.lpSum([inv[p][26] * FINANCIALS[p]["fe_fob"] * 0.85 for p in ACTIVE_PRODUCTS])
    
    cogs_fe = pulp.lpSum([order_fe[p][w] * (FINANCIALS[p]["fe_fob"] * (1 + tariff_rate)) for p in ACTIVE_PRODUCTS for w in WEEKS])
    cogs_ns = pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["ns_fob"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    logistics = pulp.lpSum([containers_fe[w] * FE_CONTAINER_COST + trucks_ns[w] * NS_TRUCK_COST for w in WEEKS])
    holding = pulp.lpSum([inv[p][w] * holding_cost for p in ACTIVE_PRODUCTS for w in WEEKS])
    lost_sales_cost = pulp.lpSum([shortage[p][w] * stockout_penalty for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    wacc_transit_fe = pulp.lpSum([order_fe[p][w] * FINANCIALS[p]["fe_fob"] * FINANCIALS[p]["fe_lt"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
    wacc_transit_ns = pulp.lpSum([order_ns[p][w] * FINANCIALS[p]["ns_fob"] * FINANCIALS[p]["ns_lt"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
    wacc_on_hand = pulp.lpSum([inv[p][w] * FINANCIALS[p]["fe_fob"] * wacc_weekly for p in ACTIVE_PRODUCTS for w in WEEKS])
    
    prob += (revenue + salvage_value) - (cogs_fe + cogs_ns + logistics + holding + lost_sales_cost + wacc_transit_fe + wacc_transit_ns + wacc_on_hand)
    
    prob.solve(pulp.PULP_CBC_CMD(msg=0, gapRel=0.01)) # 1% Optimality gap for extreme speed
    
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
    
    tot_fe_cbm = sum([get_val(order_fe[p][w]) * FINANCIALS[p]["unit_cbm"] for p in ACTIVE_PRODUCTS for w in WEEKS])
    tot_fe_cap = sum([get_val(containers_fe[w]) * FE_CONTAINER_CBM for w in WEEKS])
    fill_rate = (tot_fe_cbm / tot_fe_cap * 100) if tot_fe_cap > 0 else 0
    
    return {"t_rev": t_rev, "t_cogs": t_cogs, "t_freight": t_freight, "t_holding": t_holding, "t_lost": t_lost, "t_wacc": t_wacc, "ebitda": ebitda, "sl": sl, "wc": total_wc, "roic": roic, "fill_rate": fill_rate}

# --- 6. EXECUTION ---
if "Compare Both" in active_scenario:
    with st.spinner("Solving Legacy Strategy..."):
        res_A = solve_sourcing("Legacy Strategy")
    with st.spinner("Solving Dual-Sourcing Strategy..."):
        res_B = solve_sourcing("Dual-Sourcing Mix")
    results = {"Legacy (Far-East)": res_A, "Value Creation (Dual)": res_B}
else:
    with st.spinner(f"Simulating {active_scenario}..."):
        results = {active_scenario: solve_sourcing(active_scenario)}

# --- 7. VISUAL DASHBOARDS ---
tab1, tab2, tab3, tab4 = st.tabs(["📊 CFO Exec Summary", "💰 Total Landed P&L", "📦 Inventory Curve", "🚢 Download CFO Audit Ledger"])

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

with tab2:
    st.subheader("Half-Year P&L & True Landed Costs")
    pl_data = {"Line Item": ["Gross Sales Revenue", "FOB Materials Cost (+ Import Tariffs)", "Fixed Logistics (Ocean Cont. + Trucks)", "UK 3PL Holding Cost", "WACC Cost (Cash Opportunity Cost)", "TRUE EBITDA"]}
    for name, res in results.items():
        m = res["metrics"]
        def pct(v): return f"{(abs(v)/m['t_rev'])*100:.1f}%" if m['t_rev']>0 else "0%"
        pl_data[f"{name} (£)"] = [f"£{m['t_rev']:,.0f}", f"-£{m['t_cogs']:,.0f}", f"-£{m['t_freight']:,.0f}", f"-£{m['t_holding']:,.0f}", f"-£{m['t_wacc']:,.0f}", f"£{m['ebitda']:,.0f}"]
        pl_data[f"{name} Margin %"] = ["100.0%", pct(m['t_cogs']), pct(m['t_freight']), pct(m['t_holding']), pct(m['t_wacc']), pct(m['ebitda'])]
    
    st.table(pd.DataFrame(pl_data))
    for name, res in results.items():
        st.write(f"**{name}** -> Avoidable Value Leakage (Stockouts): £{res['metrics']['t_lost']:,.0f}")

with tab3:
    st.subheader("Operations: S&OP Inventory Curve")
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
    st.subheader("Download Detailed Financial & Operational Ledger")
    st.info("Download the complete week-by-week audit trail. This Excel file contains the Executive KPIs, the container/truck packing schedule, and a dedicated tab for every single product showing POs, Arrivals, Sales, and WACC calculations.")
    
    excel_data = generate_cfo_ledger(results)
    st.download_button(
        label="📥 Download CFO Audit Ledger (.xlsx)", 
        data=excel_data, 
        file_name="CFO_Audit_Ledger.xlsx", 
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
        key="dl_cfo_ledger",
        type="primary"
    )
