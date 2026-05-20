from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from validation_engine import (
    ValidationSetup,
    read_table,
    clean_column_names,
    clean_reference_validation,
    timeseries_validation,
    degradation_penalty_table,
    compare_penalties_to_reference,
    policy_benchmark,
    fouling_benchmark,
    filter_benchmark,
    plot_bar_validation,
    plot_timeseries,
    plot_scatter,
    plot_penalties,
    write_excel_report,
    zip_folder,
    save_setup,
)

st.set_page_config(page_title="HVAC ROM-Degradation Validation Suite", layout="wide")

OUT_ROOT = Path("validation_outputs")
OUT_ROOT.mkdir(exist_ok=True)

if "run_id" not in st.session_state:
    st.session_state["run_id"] = datetime.now().strftime("%Y%m%d_%H%M%S")
if "sheets" not in st.session_state:
    st.session_state["sheets"] = {}
if "figures" not in st.session_state:
    st.session_state["figures"] = []
if "out_dir" not in st.session_state:
    st.session_state["out_dir"] = str(OUT_ROOT / f"validation_run_{st.session_state['run_id']}")

out_dir = Path(st.session_state["out_dir"])
out_dir.mkdir(parents=True, exist_ok=True)
fig_dir = out_dir / "figures"
fig_dir.mkdir(exist_ok=True)

st.title("HVAC ROM-Degradation Validation Suite")
st.caption("Upload model outputs and published/reference CSV data, then generate validation metrics, input tables, and graphs.")

with st.sidebar:
    st.header("Validation setup")
    project_name = st.text_input("Project name", "Mohsen HVAC ROM-Degradation Validation")
    building_name = st.text_input("Building / case name", "Validation case")
    area = st.number_input("Building area (m²)", min_value=1.0, value=19592.0, step=10.0)
    years = st.number_input("Simulation years represented by model file", min_value=0.1, value=1.0, step=0.5)
    weather_label = st.text_input("Weather / climate label", "DOE LA 3B-CA / Egyptian EPW / published case")
    reference_source = st.text_input("Reference source", "Published reference / DOE / DesignBuilder / LBNL")
    notes = st.text_area("Notes", "")
    setup = ValidationSetup(project_name, building_name, area, years, weather_label, reference_source, notes)
    if st.button("Save setup table"):
        save_setup(setup, out_dir)
        st.session_state["sheets"]["setup"] = pd.DataFrame([setup.__dict__])
        st.success("Setup saved.")

    st.divider()
    st.markdown("**Current output folder**")
    st.code(str(out_dir))


def show_df(df: pd.DataFrame, name: str):
    if df is not None and not df.empty:
        st.dataframe(df, use_container_width=True)
        st.download_button(
            f"Download {name}.csv",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=f"{name}.csv",
            mime="text/csv",
        )


def load_uploaded_table(label: str, key: str):
    f = st.file_uploader(label, type=["csv", "xlsx", "xls"], key=key)
    if f is not None:
        try:
            df = clean_column_names(read_table(f))
            st.success(f"Loaded {f.name}: {df.shape[0]} rows × {df.shape[1]} columns")
            return df
        except Exception as e:
            st.error(f"Could not read file: {e}")
    return pd.DataFrame()


def column_selector(label, df, key, default=None):
    opts = [""] + list(df.columns)
    idx = 0
    if default in opts:
        idx = opts.index(default)
    return st.selectbox(label, opts, index=idx, key=key)


tabs = st.tabs([
    "1 Upload & Setup",
    "2 Clean / EUI Validation",
    "3 Time-Series Validation",
    "4 Degradation / Fault Penalty",
    "5 S0-S3 Policy Benchmark",
    "6 Analytical Benchmarks",
    "7 Final Report & Export",
])

with tabs[0]:
    st.subheader("Upload model output and reference files")
    st.markdown("Use model CSVs exported from your Streamlit bundle, DesignBuilder results, DOE reference tables, or published datasets.")
    c1, c2 = st.columns(2)
    with c1:
        model_df = load_uploaded_table("Upload model output CSV/XLSX", "upload_model_general")
        if not model_df.empty:
            st.session_state["model_df"] = model_df
            show_df(model_df.head(30), "model_preview")
    with c2:
        reference_df = load_uploaded_table("Upload reference / published CSV/XLSX", "upload_ref_general")
        if not reference_df.empty:
            st.session_state["reference_df"] = reference_df
            show_df(reference_df.head(30), "reference_preview")

    st.subheader("What formats can I upload?")
    st.markdown(
        """
        **Clean / EUI reference template:** `kpi, reference_value, reference_unit, model_column, model_value_mode, tolerance_pct, notes`  
        **Time-series template:** one model CSV + one reference CSV, then select matching columns.  
        **Fault penalty reference template:** `fault_mechanism, metric, published_penalty_pct, tolerance_pct, notes`  
        **Policy benchmark:** a model summary file containing a strategy column and KPI columns.
        """
    )

with tabs[1]:
    st.subheader("Clean / EUI validation")
    st.markdown("Use this for DOE/NREL reference building, DesignBuilder clean baseline, Egyptian benchmark EUI, or annual published values.")

    model_df = st.session_state.get("model_df", pd.DataFrame())
    if model_df.empty:
        model_df = load_uploaded_table("Upload model output for clean validation", "clean_model_upload")
    if not model_df.empty:
        st.session_state["model_df"] = model_df

    default_ref = pd.DataFrame([
        {"kpi": "Cooling EUI", "reference_value": 50.00, "reference_unit": "kWh/m2.year", "model_column": "Cooling Energy MWh", "model_value_mode": "total_mwh_to_annual_eui", "tolerance_pct": 15, "notes": "DOE Secondary School LA 3B-CA example"},
        {"kpi": "Fan EUI", "reference_value": 14.67, "reference_unit": "kWh/m2.year", "model_column": "Fan Energy MWh", "model_value_mode": "total_mwh_to_annual_eui", "tolerance_pct": 15, "notes": "DOE Secondary School LA 3B-CA example"},
        {"kpi": "Pump EUI", "reference_value": 0.30, "reference_unit": "kWh/m2.year", "model_column": "Pump Energy MWh", "model_value_mode": "total_mwh_to_annual_eui", "tolerance_pct": 15, "notes": "DOE Secondary School LA 3B-CA example"},
        {"kpi": "HVAC Electric EUI", "reference_value": 64.98, "reference_unit": "kWh/m2.year", "model_column": "Total Energy MWh", "model_value_mode": "total_mwh_to_annual_eui", "tolerance_pct": 15, "notes": "Use corrected model HVAC electric boundary"},
    ])

    uploaded_ref = load_uploaded_table("Optional: upload clean/EUI reference plan CSV", "clean_ref_upload")
    if uploaded_ref.empty:
        st.info("No reference plan uploaded. Edit the default DOE-style table below or replace it with your own values.")
        reference_plan = st.data_editor(default_ref, num_rows="dynamic", use_container_width=True, key="clean_ref_editor")
    else:
        reference_plan = st.data_editor(uploaded_ref, num_rows="dynamic", use_container_width=True, key="clean_ref_editor_uploaded")

    if not model_df.empty:
        case_col = column_selector("Optional model case column", model_df, "clean_case_col")
        case_value = "<first row>"
        if case_col:
            vals = ["<first row>"] + sorted(model_df[case_col].astype(str).unique().tolist())
            case_value = st.selectbox("Select model case row", vals, key="clean_case_value")
        st.markdown("**Model file columns:**")
        st.write(list(model_df.columns))

    if st.button("Run clean/EUI validation", type="primary"):
        if model_df.empty:
            st.error("Upload a model output file first.")
        else:
            try:
                res = clean_reference_validation(model_df, pd.DataFrame(reference_plan), setup, case_col or None, case_value)
                st.session_state["clean_validation"] = res
                st.session_state["sheets"]["clean_eui_validation"] = res
                st.session_state["sheets"]["clean_reference_plan"] = pd.DataFrame(reference_plan)
                res.to_csv(out_dir / "clean_eui_validation_metrics.csv", index=False)
                pd.DataFrame(reference_plan).to_csv(out_dir / "clean_reference_plan_used.csv", index=False)
                p = plot_bar_validation(res, fig_dir / "clean_eui_model_vs_reference.png", "Clean/EUI Validation: Model vs Reference")
                if p:
                    st.session_state["figures"].append(str(p))
                st.success("Clean/EUI validation completed.")
            except Exception as e:
                st.error(f"Validation failed: {e}")

    if "clean_validation" in st.session_state:
        show_df(st.session_state["clean_validation"], "clean_eui_validation_metrics")
        fig_path = fig_dir / "clean_eui_model_vs_reference.png"
        if fig_path.exists():
            st.image(str(fig_path), caption="Clean/EUI model-vs-reference comparison")

with tabs[2]:
    st.subheader("Time-series validation")
    st.markdown("Use this for monthly, daily, or hourly model-vs-reference comparison. It calculates RMSE, MAE, R², NMBE and CV-RMSE.")
    c1, c2 = st.columns(2)
    with c1:
        ts_model = load_uploaded_table("Upload model time-series CSV/XLSX", "ts_model_upload")
    with c2:
        ts_ref = load_uploaded_table("Upload reference time-series CSV/XLSX", "ts_ref_upload")

    if not ts_model.empty and not ts_ref.empty:
        model_time = column_selector("Model time column, optional", ts_model, "ts_model_time")
        ref_time = column_selector("Reference time column, optional", ts_ref, "ts_ref_time")
        nmap = st.number_input("Number of KPI mappings", min_value=1, max_value=10, value=1, step=1)
        mappings = []
        for i in range(int(nmap)):
            st.markdown(f"**Mapping {i+1}**")
            cc1, cc2, cc3 = st.columns(3)
            with cc1:
                kpi = st.text_input("KPI name", value=f"KPI_{i+1}", key=f"ts_kpi_{i}")
            with cc2:
                mcol = column_selector("Model column", ts_model, f"ts_mcol_{i}")
            with cc3:
                rcol = column_selector("Reference column", ts_ref, f"ts_rcol_{i}")
            mappings.append({"kpi": kpi, "model_column": mcol, "reference_column": rcol, "model_time_column": model_time, "reference_time_column": ref_time})

        if st.button("Run time-series validation", type="primary"):
            metrics, aligned = timeseries_validation(ts_model, ts_ref, mappings)
            st.session_state["ts_metrics"] = metrics
            st.session_state["sheets"]["timeseries_metrics"] = metrics
            metrics.to_csv(out_dir / "timeseries_validation_metrics.csv", index=False)
            for kpi, a in aligned.items():
                safe = str(kpi).replace("/", "_").replace(" ", "_")
                a.to_csv(out_dir / f"timeseries_aligned_{safe}.csv", index=False)
                p1 = plot_timeseries(a, fig_dir / f"timeseries_{safe}.png", f"Time-Series Validation: {kpi}")
                p2 = plot_scatter(a, fig_dir / f"scatter_{safe}.png", f"Model vs Reference: {kpi}")
                if p1: st.session_state["figures"].append(str(p1))
                if p2: st.session_state["figures"].append(str(p2))
            st.success("Time-series validation completed.")

    if "ts_metrics" in st.session_state:
        show_df(st.session_state["ts_metrics"], "timeseries_validation_metrics")
        for p in fig_dir.glob("timeseries_*.png"):
            st.image(str(p))
        for p in fig_dir.glob("scatter_*.png"):
            st.image(str(p))

with tabs[3]:
    st.subheader("Degradation / fault penalty validation")
    st.markdown("Use this for LBNL/Wang/Nassif/Yang-style published fault penalties. Compare normalized penalties, not absolute MWh.")
    model_df = st.session_state.get("model_df", pd.DataFrame())
    if model_df.empty:
        model_df = load_uploaded_table("Upload model summary or scenario CSV", "fault_model_upload")
    if not model_df.empty:
        st.session_state["model_df"] = model_df
        case_col = column_selector("Case / scenario column", model_df, "fault_case_col")
        if case_col:
            cases = sorted(model_df[case_col].astype(str).unique().tolist())
            baseline_case = st.selectbox("Baseline / clean case", cases, key="fault_baseline")
            scenario_cases = st.multiselect("Degraded/faulted cases", cases, default=[c for c in cases if c != baseline_case][:3], key="fault_cases")
            numeric_cols = [c for c in model_df.columns if pd.to_numeric(model_df[c], errors="coerce").notna().any()]
            default_metrics = [c for c in numeric_cols if any(k in c.lower() for k in ["energy", "fan", "pump", "cop", "co2", "power"])]
            metric_cols = st.multiselect("Model metric columns for penalty calculation", numeric_cols, default=default_metrics[:6], key="fault_metric_cols")

            default_pub = pd.DataFrame([
                {"fault_mechanism": "Chiller fouling", "metric": metric_cols[0] if metric_cols else "Cooling Energy MWh", "published_penalty_pct": 10.0, "tolerance_pct": 10.0, "notes": "Replace with value from the selected paper"},
                {"fault_mechanism": "Dirty filter / fan pressure", "metric": metric_cols[1] if len(metric_cols) > 1 else "Fan Energy MWh", "published_penalty_pct": 15.0, "tolerance_pct": 15.0, "notes": "Replace with value from the selected paper"},
            ])
            uploaded_pub = load_uploaded_table("Optional: upload published penalty reference CSV", "fault_pub_upload")
            if uploaded_pub.empty:
                published_ref = st.data_editor(default_pub, num_rows="dynamic", use_container_width=True, key="fault_pub_editor")
            else:
                published_ref = st.data_editor(uploaded_pub, num_rows="dynamic", use_container_width=True, key="fault_pub_editor_uploaded")

            if st.button("Run degradation/fault penalty validation", type="primary"):
                penalties = degradation_penalty_table(model_df, case_col, baseline_case, scenario_cases, metric_cols)
                comp = compare_penalties_to_reference(penalties, pd.DataFrame(published_ref))
                st.session_state["fault_penalties"] = penalties
                st.session_state["fault_comparison"] = comp
                st.session_state["sheets"]["fault_model_penalties"] = penalties
                st.session_state["sheets"]["fault_vs_published"] = comp
                penalties.to_csv(out_dir / "model_degradation_fault_penalties.csv", index=False)
                comp.to_csv(out_dir / "published_fault_penalty_comparison.csv", index=False)
                p = plot_penalties(penalties, fig_dir / "model_fault_penalties.png")
                if p: st.session_state["figures"].append(str(p))
                st.success("Fault/degradation validation completed.")

    if "fault_penalties" in st.session_state:
        st.markdown("### Model penalties")
        show_df(st.session_state["fault_penalties"], "model_degradation_fault_penalties")
    if "fault_comparison" in st.session_state:
        st.markdown("### Published penalty comparison")
        show_df(st.session_state["fault_comparison"], "published_fault_penalty_comparison")
        p = fig_dir / "model_fault_penalties.png"
        if p.exists():
            st.image(str(p))

with tabs[4]:
    st.subheader("S0-S3 internal policy benchmark")
    st.markdown("This compares your internal strategy family under the same building/weather setup.")
    model_df = st.session_state.get("model_df", pd.DataFrame())
    if model_df.empty:
        model_df = load_uploaded_table("Upload S0-S3 summary CSV", "policy_model_upload")
    if not model_df.empty:
        st.session_state["model_df"] = model_df
        strategy_col = column_selector("Strategy column", model_df, "policy_strategy_col")
        if strategy_col:
            strategies = sorted(model_df[strategy_col].astype(str).unique().tolist())
            baseline_strategy = st.selectbox("Baseline strategy", strategies, index=0, key="policy_baseline_strategy")
            numeric_cols = [c for c in model_df.columns if pd.to_numeric(model_df[c], errors="coerce").notna().any()]
            default_metrics = [c for c in numeric_cols if any(k in c.lower() for k in ["energy", "co2", "comfort", "delta", "degradation", "cost"])]
            metric_cols = st.multiselect("KPI columns for policy improvement", numeric_cols, default=default_metrics[:6], key="policy_metric_cols")
            if st.button("Run S0-S3 policy benchmark", type="primary"):
                res = policy_benchmark(model_df, strategy_col, baseline_strategy, metric_cols)
                st.session_state["policy_benchmark"] = res
                st.session_state["sheets"]["policy_benchmark"] = res
                res.to_csv(out_dir / "s0_s3_policy_benchmark.csv", index=False)
                st.success("Policy benchmark completed.")
    if "policy_benchmark" in st.session_state:
        show_df(st.session_state["policy_benchmark"], "s0_s3_policy_benchmark")

with tabs[5]:
    st.subheader("Analytical fouling and filter benchmarks")
    st.markdown("Use these to verify your degradation equations independently of published datasets.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Fouling benchmark")
        rf_star = st.number_input("Rf* (m²K/W)", value=2e-4, format="%.8f")
        b_foul = st.number_input("B fouling rate (day⁻¹)", value=0.015, format="%.6f")
    with c2:
        st.markdown("### Filter benchmark")
        dust_rate = st.number_input("Dust rate (kg/day)", value=1.2, format="%.4f")
        alpha_flow = st.number_input("Airflow fraction", min_value=0.0, max_value=2.0, value=1.0, format="%.3f")
        k_clog = st.number_input("K clog (Pa/kg)", value=6.0, format="%.3f")
        dp_clean = st.number_input("Clean dP (Pa)", value=150.0, format="%.2f")
    days = st.number_input("Benchmark duration (days)", min_value=1, value=365, step=1)

    if st.button("Run analytical benchmarks", type="primary"):
        f_df, f_met = fouling_benchmark(rf_star, b_foul, int(days))
        flt_df, flt_met = filter_benchmark(dust_rate, alpha_flow, k_clog, dp_clean, int(days))
        metrics = pd.concat([f_met, flt_met], ignore_index=True)
        st.session_state["analytical_metrics"] = metrics
        st.session_state["sheets"]["analytical_metrics"] = metrics
        st.session_state["sheets"]["fouling_benchmark"] = f_df
        st.session_state["sheets"]["filter_benchmark"] = flt_df
        metrics.to_csv(out_dir / "analytical_benchmark_metrics.csv", index=False)
        f_df.to_csv(out_dir / "analytical_fouling_timeseries.csv", index=False)
        flt_df.to_csv(out_dir / "analytical_filter_timeseries.csv", index=False)

        # create plots
        import matplotlib.pyplot as plt
        p1 = fig_dir / "analytical_fouling.png"
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(f_df["t_days"], f_df["Rf_sim"], label="simulated")
        ax.plot(f_df["t_days"], f_df["Rf_exact"], linestyle="--", label="analytical")
        ax.set_xlabel("Days"); ax.set_ylabel("Rf (m²K/W)"); ax.set_title("Analytical fouling verification"); ax.legend(); fig.tight_layout(); fig.savefig(p1, dpi=200); plt.close(fig)
        p2 = fig_dir / "analytical_filter_dp.png"
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(flt_df["t_days"], flt_df["dP_sim_Pa"], label="simulated")
        ax.plot(flt_df["t_days"], flt_df["dP_exact_Pa"], linestyle="--", label="analytical")
        ax.set_xlabel("Days"); ax.set_ylabel("dP (Pa)"); ax.set_title("Analytical filter pressure verification"); ax.legend(); fig.tight_layout(); fig.savefig(p2, dpi=200); plt.close(fig)
        st.session_state["figures"].extend([str(p1), str(p2)])
        st.success("Analytical benchmarks completed.")

    if "analytical_metrics" in st.session_state:
        show_df(st.session_state["analytical_metrics"], "analytical_benchmark_metrics")
        for p in [fig_dir / "analytical_fouling.png", fig_dir / "analytical_filter_dp.png"]:
            if p.exists():
                st.image(str(p))

with tabs[6]:
    st.subheader("Final report and export")
    st.markdown("Collect all generated tables, setup inputs, metrics, and graphs into one ZIP package.")
    if st.button("Build final validation report package", type="primary"):
        save_setup(setup, out_dir)
        st.session_state["sheets"]["setup"] = pd.DataFrame([setup.__dict__])
        report_xlsx = write_excel_report(out_dir / "HVAC_ROM_validation_report.xlsx", st.session_state.get("sheets", {}))
        readme = out_dir / "README_VALIDATION_OUTPUTS.md"
        readme.write_text(
            f"""# HVAC ROM-Degradation Validation Outputs

Project: {setup.project_name}
Building/case: {setup.building_name}
Area: {setup.building_area_m2} m²
Simulation years: {setup.simulation_years}
Weather: {setup.weather_label}
Reference source: {setup.reference_source}

This package may contain:
- validation_setup.csv / validation_setup.json
- clean_eui_validation_metrics.csv
- timeseries_validation_metrics.csv
- model_degradation_fault_penalties.csv
- published_fault_penalty_comparison.csv
- s0_s3_policy_benchmark.csv
- analytical_benchmark_metrics.csv
- HVAC_ROM_validation_report.xlsx
- figures/*.png

Interpretation guide:
- Clean/EUI error <10%: strong, 10-15%: acceptable, 15-25%: weak/borderline, >25%: not acceptable.
- Time-series CV-RMSE and NMBE should be reported with the selected validation standard.
- Degradation/BHI should be interpreted through validated components: Rf, dP, COP, fan/pump penalty and energy penalty.
""",
            encoding="utf-8",
        )
        zip_path = zip_folder(out_dir, out_dir / "HVAC_ROM_validation_outputs.zip")
        st.session_state["final_zip"] = str(zip_path)
        st.success("Final package created.")
        st.write("Excel report:", str(report_xlsx))
        st.write("ZIP package:", str(zip_path))

    final_zip = st.session_state.get("final_zip")
    if final_zip and Path(final_zip).exists():
        st.download_button(
            "Download full validation output ZIP",
            data=Path(final_zip).read_bytes(),
            file_name="HVAC_ROM_validation_outputs.zip",
            mime="application/zip",
        )

    st.markdown("### Current collected sheets")
    st.write(list(st.session_state.get("sheets", {}).keys()))
    st.markdown("### Current figures")
    for p in sorted(set(st.session_state.get("figures", []))):
        if Path(p).exists():
            st.image(p, caption=Path(p).name)
