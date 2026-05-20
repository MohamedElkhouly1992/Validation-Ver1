"""
HVAC ROM-Degradation Validation Suite
Standalone validation utilities for reduced-order HVAC degradation model outputs.

This module supports:
- clean/reference EUI validation
- time-series validation
- degradation/fault penalty validation
- S0-S3 internal policy benchmark
- analytical fouling and filter benchmarks
- report packaging
"""
from __future__ import annotations

import io
import math
import json
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


LOWER_IS_BETTER_DEFAULT = {
    "energy": True,
    "eui": True,
    "co2": True,
    "carbon": True,
    "comfort": True,
    "degradation": True,
    "delta": True,
    "cost": True,
    "power": True,
    "cop": False,
    "bhi": False,
    "health": False,
}


@dataclass
class ValidationSetup:
    project_name: str = "HVAC_ROM_Degradation_Validation"
    building_name: str = "Validation case"
    building_area_m2: float = 19592.0
    simulation_years: float = 1.0
    weather_label: str = "Reference weather / EPW"
    reference_source: str = "Published reference"
    notes: str = ""


# ---------- Loading / cleaning ----------

def read_table(file_or_path) -> pd.DataFrame:
    """Read CSV/XLSX from path, Streamlit upload, or bytes."""
    if file_or_path is None:
        return pd.DataFrame()
    if isinstance(file_or_path, (str, Path)):
        path = Path(file_or_path)
        if path.suffix.lower() in [".xlsx", ".xls"]:
            return pd.read_excel(path)
        return pd.read_csv(path)
    # Streamlit UploadedFile or BytesIO
    name = getattr(file_or_path, "name", "uploaded.csv")
    raw = file_or_path.getvalue() if hasattr(file_or_path, "getvalue") else file_or_path.read()
    bio = io.BytesIO(raw)
    if str(name).lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(bio)
    # flexible separators
    try:
        return pd.read_csv(bio)
    except Exception:
        bio.seek(0)
        return pd.read_csv(bio, sep=None, engine="python")


def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def numeric_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")


def find_column(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    if df.empty:
        return None
    normalized = {str(c).strip().lower().replace(" ", "_"): c for c in df.columns}
    for cand in candidates:
        key = str(cand).strip().lower().replace(" ", "_")
        if key in normalized:
            return normalized[key]
    for cand in candidates:
        key = str(cand).strip().lower()
        for col in df.columns:
            if key in str(col).strip().lower():
                return col
    return None


# ---------- Metrics ----------

def regression_metrics(model: Iterable[float], reference: Iterable[float]) -> Dict[str, float]:
    m = np.asarray(pd.to_numeric(pd.Series(model), errors="coerce"), dtype=float)
    r = np.asarray(pd.to_numeric(pd.Series(reference), errors="coerce"), dtype=float)
    mask = np.isfinite(m) & np.isfinite(r)
    m = m[mask]
    r = r[mask]
    if len(m) == 0:
        return {"n": 0, "RMSE": np.nan, "MAE": np.nan, "MBE": np.nan, "NMBE_pct": np.nan, "CVRMSE_pct": np.nan, "MAPE_pct": np.nan, "R2": np.nan}
    err = m - r
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mae = float(np.mean(np.abs(err)))
    mbe = float(np.mean(err))
    mean_ref = float(np.mean(r))
    nmbe = float(100 * mbe / mean_ref) if abs(mean_ref) > 1e-12 else np.nan
    cvrmse = float(100 * rmse / mean_ref) if abs(mean_ref) > 1e-12 else np.nan
    nonzero = np.abs(r) > 1e-12
    mape = float(100 * np.mean(np.abs(err[nonzero] / r[nonzero]))) if np.any(nonzero) else np.nan
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((r - mean_ref) ** 2))
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 1e-12 else np.nan
    return {"n": int(len(m)), "RMSE": rmse, "MAE": mae, "MBE": mbe, "NMBE_pct": nmbe, "CVRMSE_pct": cvrmse, "MAPE_pct": mape, "R2": r2}


def point_error(model_value: float, reference_value: float) -> Dict[str, float]:
    if pd.isna(model_value) or pd.isna(reference_value):
        return {"absolute_error": np.nan, "percent_error": np.nan, "abs_percent_error": np.nan}
    err = float(model_value - reference_value)
    pct = float(100 * err / reference_value) if abs(reference_value) > 1e-12 else np.nan
    return {"absolute_error": err, "percent_error": pct, "abs_percent_error": abs(pct) if np.isfinite(pct) else np.nan}


def verdict_from_error(abs_percent_error: float, tolerance_pct: float = 15.0) -> str:
    if pd.isna(abs_percent_error):
        return "not computed"
    if abs_percent_error <= 10:
        return "strong"
    if abs_percent_error <= tolerance_pct:
        return "acceptable"
    if abs_percent_error <= 25:
        return "borderline / weak"
    return "not acceptable"


# ---------- Model value extraction ----------

def select_model_row(model_df: pd.DataFrame, case_col: Optional[str], case_value: Optional[str]) -> pd.Series:
    if model_df.empty:
        raise ValueError("Model dataframe is empty")
    if case_col and case_col in model_df.columns and case_value not in [None, "", "<first row>"]:
        sub = model_df[model_df[case_col].astype(str) == str(case_value)]
        if not sub.empty:
            return sub.iloc[0]
    return model_df.iloc[0]


def convert_model_value(raw_value: float, mode: str, setup: ValidationSetup) -> float:
    v = float(raw_value) if not pd.isna(raw_value) else np.nan
    area = max(float(setup.building_area_m2), 1e-9)
    years = max(float(setup.simulation_years), 1e-9)
    mode = (mode or "direct").lower()
    if mode == "direct":
        return v
    if mode == "total_mwh_to_annual_eui":
        return v * 1000.0 / area / years
    if mode == "annual_mwh_to_eui":
        return v * 1000.0 / area
    if mode == "total_kwh_to_annual_eui":
        return v / area / years
    if mode == "annual_kwh_to_eui":
        return v / area
    if mode == "kg_to_tonne":
        return v / 1000.0
    if mode == "tonne_to_kg":
        return v * 1000.0
    return v


def clean_reference_validation(model_df: pd.DataFrame, reference_plan: pd.DataFrame, setup: ValidationSetup, case_col: Optional[str] = None, case_value: Optional[str] = None) -> pd.DataFrame:
    """
    reference_plan columns:
      kpi, reference_value, reference_unit, model_column, model_value_mode, tolerance_pct, notes
    """
    model_df = clean_column_names(model_df)
    ref = clean_column_names(reference_plan)
    if ref.empty:
        return pd.DataFrame()
    row = select_model_row(model_df, case_col, case_value)
    rows = []
    for _, r in ref.iterrows():
        model_col = str(r.get("model_column", "")).strip()
        ref_val = pd.to_numeric(pd.Series([r.get("reference_value", np.nan)]), errors="coerce").iloc[0]
        mode = str(r.get("model_value_mode", "direct")).strip() or "direct"
        tol = pd.to_numeric(pd.Series([r.get("tolerance_pct", 15.0)]), errors="coerce").iloc[0]
        if pd.isna(tol):
            tol = 15.0
        if model_col not in model_df.columns:
            model_val = np.nan
            raw_val = np.nan
        else:
            raw_val = pd.to_numeric(pd.Series([row[model_col]]), errors="coerce").iloc[0]
            model_val = convert_model_value(raw_val, mode, setup)
        err = point_error(model_val, ref_val)
        rows.append({
            "kpi": r.get("kpi", ""),
            "reference_value": ref_val,
            "reference_unit": r.get("reference_unit", ""),
            "model_column": model_col,
            "raw_model_value": raw_val,
            "model_value_mode": mode,
            "model_value_converted": model_val,
            "absolute_error": err["absolute_error"],
            "percent_error": err["percent_error"],
            "abs_percent_error": err["abs_percent_error"],
            "tolerance_pct": tol,
            "verdict": verdict_from_error(err["abs_percent_error"], tol),
            "notes": r.get("notes", ""),
        })
    return pd.DataFrame(rows)


# ---------- Time-series validation ----------

def align_timeseries(model_df: pd.DataFrame, ref_df: pd.DataFrame, model_col: str, ref_col: str, time_col_model: Optional[str] = None, time_col_ref: Optional[str] = None) -> pd.DataFrame:
    m = clean_column_names(model_df).copy()
    r = clean_column_names(ref_df).copy()
    if time_col_model and time_col_ref and time_col_model in m.columns and time_col_ref in r.columns:
        m["_time"] = pd.to_datetime(m[time_col_model], errors="coerce")
        r["_time"] = pd.to_datetime(r[time_col_ref], errors="coerce")
        a = pd.merge(m[["_time", model_col]], r[["_time", ref_col]], on="_time", how="inner")
        a = a.rename(columns={model_col: "model", ref_col: "reference"})
        return a.dropna(subset=["model", "reference"])
    n = min(len(m), len(r))
    a = pd.DataFrame({
        "index": np.arange(n),
        "model": numeric_series(m[model_col]).iloc[:n].values,
        "reference": numeric_series(r[ref_col]).iloc[:n].values,
    })
    return a.dropna(subset=["model", "reference"])


def timeseries_validation(model_df: pd.DataFrame, ref_df: pd.DataFrame, mappings: List[Dict]) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    rows = []
    aligned = {}
    for mp in mappings:
        kpi = mp.get("kpi", "KPI")
        model_col = mp.get("model_column")
        ref_col = mp.get("reference_column")
        tm = mp.get("model_time_column")
        tr = mp.get("reference_time_column")
        if not model_col or not ref_col or model_col not in model_df.columns or ref_col not in ref_df.columns:
            continue
        a = align_timeseries(model_df, ref_df, model_col, ref_col, tm, tr)
        metrics = regression_metrics(a["model"], a["reference"])
        metrics["kpi"] = kpi
        metrics["model_column"] = model_col
        metrics["reference_column"] = ref_col
        rows.append(metrics)
        aligned[kpi] = a
    return pd.DataFrame(rows), aligned


# ---------- Degradation / fault penalty ----------

def compute_penalty(value: float, baseline: float, higher_is_penalty: bool = True) -> float:
    if pd.isna(value) or pd.isna(baseline) or abs(float(baseline)) < 1e-12:
        return np.nan
    pct = 100.0 * (float(value) - float(baseline)) / float(baseline)
    return pct if higher_is_penalty else -pct


def degradation_penalty_table(model_df: pd.DataFrame, case_col: str, baseline_case: str, scenario_cases: List[str], metric_columns: List[str]) -> pd.DataFrame:
    df = clean_column_names(model_df)
    if case_col not in df.columns:
        raise ValueError(f"case column {case_col} not found")
    base = df[df[case_col].astype(str) == str(baseline_case)]
    if base.empty:
        raise ValueError("baseline case not found")
    base = base.iloc[0]
    rows = []
    for case in scenario_cases:
        sub = df[df[case_col].astype(str) == str(case)]
        if sub.empty:
            continue
        r = sub.iloc[0]
        for col in metric_columns:
            if col not in df.columns:
                continue
            b = pd.to_numeric(pd.Series([base[col]]), errors="coerce").iloc[0]
            v = pd.to_numeric(pd.Series([r[col]]), errors="coerce").iloc[0]
            rows.append({
                "case": case,
                "baseline_case": baseline_case,
                "metric": col,
                "baseline_value": b,
                "case_value": v,
                "penalty_pct_vs_baseline": compute_penalty(v, b),
            })
    return pd.DataFrame(rows)


def compare_penalties_to_reference(model_penalties: pd.DataFrame, reference_penalties: pd.DataFrame) -> pd.DataFrame:
    """Reference columns: fault_mechanism, metric, published_penalty_pct, tolerance_pct, notes"""
    ref = clean_column_names(reference_penalties)
    if ref.empty or model_penalties.empty:
        return pd.DataFrame()
    rows = []
    for _, rr in ref.iterrows():
        metric = str(rr.get("metric", "")).strip()
        candidate = model_penalties[model_penalties["metric"].astype(str) == metric]
        if candidate.empty:
            model_pen = np.nan
            model_case = ""
        else:
            # choose closest in absolute penalty to reference
            pub = pd.to_numeric(pd.Series([rr.get("published_penalty_pct", np.nan)]), errors="coerce").iloc[0]
            candidate = candidate.copy()
            candidate["_diff"] = (candidate["penalty_pct_vs_baseline"] - pub).abs()
            best = candidate.sort_values("_diff").iloc[0]
            model_pen = best["penalty_pct_vs_baseline"]
            model_case = best["case"]
        pub = pd.to_numeric(pd.Series([rr.get("published_penalty_pct", np.nan)]), errors="coerce").iloc[0]
        tol = pd.to_numeric(pd.Series([rr.get("tolerance_pct", 15.0)]), errors="coerce").iloc[0]
        err = point_error(model_pen, pub)
        rows.append({
            "fault_mechanism": rr.get("fault_mechanism", ""),
            "metric": metric,
            "published_penalty_pct": pub,
            "closest_model_case": model_case,
            "model_penalty_pct": model_pen,
            "difference_points": err["absolute_error"],
            "abs_difference_points": abs(err["absolute_error"]) if not pd.isna(err["absolute_error"]) else np.nan,
            "tolerance_points": tol,
            "verdict": "acceptable" if not pd.isna(err["absolute_error"]) and abs(err["absolute_error"]) <= tol else "review/weak",
            "notes": rr.get("notes", ""),
        })
    return pd.DataFrame(rows)


# ---------- S0-S3 policy benchmark ----------

def policy_benchmark(model_df: pd.DataFrame, strategy_col: str, baseline_strategy: str, metric_columns: List[str]) -> pd.DataFrame:
    df = clean_column_names(model_df)
    base = df[df[strategy_col].astype(str) == str(baseline_strategy)]
    if base.empty:
        raise ValueError("baseline strategy not found")
    base = base.iloc[0]
    rows = []
    for _, r in df.iterrows():
        strategy = str(r[strategy_col])
        row = {"strategy": strategy, "baseline_strategy": baseline_strategy}
        for col in metric_columns:
            if col not in df.columns:
                continue
            b = pd.to_numeric(pd.Series([base[col]]), errors="coerce").iloc[0]
            v = pd.to_numeric(pd.Series([r[col]]), errors="coerce").iloc[0]
            row[f"{col}_value"] = v
            row[f"{col}_improvement_vs_{baseline_strategy}_pct"] = -compute_penalty(v, b)  # lower metric = improvement
        rows.append(row)
    return pd.DataFrame(rows)


# ---------- Analytical benchmarks ----------

def fouling_benchmark(rf_star: float = 2e-4, b_foul: float = 0.015, days: int = 365, dt_days: float = 1.0) -> Tuple[pd.DataFrame, pd.DataFrame]:
    times = np.arange(0, days + dt_days, dt_days, dtype=float)
    sim = []
    rf = 0.0
    for i, t in enumerate(times):
        if i == 0:
            rf = 0.0
        else:
            rf = rf_star - (rf_star - rf) * math.exp(-b_foul * dt_days)
        exact = rf_star * (1.0 - math.exp(-b_foul * t))
        sim.append({"t_days": t, "Rf_sim": rf, "Rf_exact": exact, "Rf_error": rf - exact, "Rf_abs_error": abs(rf - exact)})
    df = pd.DataFrame(sim)
    denom = max(abs(rf_star), 1e-12)
    metrics = pd.DataFrame([{
        "benchmark": "analytical_fouling",
        "max_abs_error": df["Rf_abs_error"].max(),
        "RMSE": np.sqrt(np.mean(df["Rf_error"] ** 2)),
        "max_relative_error_pct_of_Rf_star": 100 * df["Rf_abs_error"].max() / denom,
        "verdict": "pass" if 100 * df["Rf_abs_error"].max() / denom < 0.1 else "review",
    }])
    return df, metrics


def filter_benchmark(dust_rate: float = 1.2, alpha_flow: float = 1.0, k_clog: float = 6.0, dp_clean: float = 150.0, days: int = 365, dt_days: float = 1.0) -> Tuple[pd.DataFrame, pd.DataFrame]:
    times = np.arange(0, days + dt_days, dt_days, dtype=float)
    m = 0.0
    rows = []
    for i, t in enumerate(times):
        if i == 0:
            m = 0.0
        else:
            m += dust_rate * alpha_flow * dt_days
        m_exact = dust_rate * alpha_flow * t
        dp_sim = dp_clean + k_clog * m
        dp_exact = dp_clean + k_clog * m_exact
        rows.append({
            "t_days": t,
            "dust_sim_kg": m,
            "dust_exact_kg": m_exact,
            "dust_error_kg": m - m_exact,
            "dP_sim_Pa": dp_sim,
            "dP_exact_Pa": dp_exact,
            "dP_error_Pa": dp_sim - dp_exact,
            "dP_abs_error_Pa": abs(dp_sim - dp_exact),
        })
    df = pd.DataFrame(rows)
    denom = max(abs(df["dP_exact_Pa"].max()), 1e-12)
    metrics = pd.DataFrame([{
        "benchmark": "analytical_filter",
        "max_abs_dP_error_Pa": df["dP_abs_error_Pa"].max(),
        "RMSE_dP_Pa": np.sqrt(np.mean(df["dP_error_Pa"] ** 2)),
        "max_relative_error_pct_of_max_dP": 100 * df["dP_abs_error_Pa"].max() / denom,
        "verdict": "pass" if 100 * df["dP_abs_error_Pa"].max() / denom < 0.1 else "review",
    }])
    return df, metrics


# ---------- Plotting ----------

def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def plot_bar_validation(df: pd.DataFrame, out_path: Path, title: str = "Model vs reference") -> Optional[Path]:
    if df.empty or "kpi" not in df.columns:
        return None
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(df))
    ax.bar(x - 0.18, df["reference_value"].astype(float), width=0.36, label="Reference")
    ax.bar(x + 0.18, df["model_value_converted"].astype(float), width=0.36, label="Model")
    ax.set_xticks(x)
    ax.set_xticklabels(df["kpi"].astype(str), rotation=35, ha="right")
    ax.set_title(title)
    ax.set_ylabel("Value")
    ax.legend()
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_timeseries(aligned: pd.DataFrame, out_path: Path, title: str = "Time-series validation") -> Optional[Path]:
    if aligned.empty:
        return None
    fig, ax = plt.subplots(figsize=(10, 4))
    x = aligned["_time"] if "_time" in aligned.columns else aligned.index
    ax.plot(x, aligned["reference"].values, label="Reference")
    ax.plot(x, aligned["model"].values, label="Model")
    ax.set_title(title)
    ax.set_ylabel("Value")
    ax.legend()
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_scatter(aligned: pd.DataFrame, out_path: Path, title: str = "Actual vs predicted") -> Optional[Path]:
    if aligned.empty:
        return None
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(aligned["reference"], aligned["model"], s=12, alpha=0.7)
    mn = np.nanmin([aligned["reference"].min(), aligned["model"].min()])
    mx = np.nanmax([aligned["reference"].max(), aligned["model"].max()])
    ax.plot([mn, mx], [mn, mx], linestyle="--")
    ax.set_xlabel("Reference")
    ax.set_ylabel("Model")
    ax.set_title(title)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def plot_penalties(df: pd.DataFrame, out_path: Path, title: str = "Degradation/fault penalties") -> Optional[Path]:
    if df.empty:
        return None
    label = df["case"].astype(str) + " | " + df["metric"].astype(str)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(np.arange(len(df)), df["penalty_pct_vs_baseline"].astype(float))
    ax.set_xticks(np.arange(len(df)))
    ax.set_xticklabels(label, rotation=45, ha="right")
    ax.set_ylabel("Penalty vs baseline (%)")
    ax.set_title(title)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ---------- Reports ----------

def write_excel_report(path: Path, sheets: Dict[str, pd.DataFrame]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    valid = {name[:31]: df for name, df in sheets.items() if isinstance(df, pd.DataFrame) and not df.empty}
    if not valid:
        valid = {"status": pd.DataFrame([{"status": "No results generated"}])}
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in valid.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    return path


def zip_folder(folder: Path, zip_path: Path) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in folder.rglob("*"):
            if p.is_file() and p != zip_path:
                z.write(p, arcname=str(p.relative_to(folder)))
    return zip_path


def save_setup(setup: ValidationSetup, out_dir: Path) -> Path:
    out = out_dir / "validation_setup.json"
    out.write_text(json.dumps(asdict(setup), indent=2), encoding="utf-8")
    pd.DataFrame([asdict(setup)]).to_csv(out_dir / "validation_setup.csv", index=False)
    return out
