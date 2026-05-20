# HVAC ROM-Degradation Validation Suite

Standalone Streamlit validation app for the Mohsen / Reduced-Order-Model-ROM--Degradation framework.

## Purpose

This bundle lets you upload:

- model outputs from your HVAC ROM-Degradation Streamlit app
- DesignBuilder / EnergyPlus results
- DOE/NREL reference building tables
- published reference CSV values
- LBNL/FDD or fault/degradation penalty tables

Then it generates:

- table of input data used for validation
- clean / annual EUI validation metrics
- time-series validation metrics: RMSE, MAE, R², NMBE, CV-RMSE, MAPE
- degradation/fault penalty comparison tables
- S0-S3 internal policy benchmark tables
- analytical fouling and filter benchmark verification
- graphs
- Excel report
- ZIP package of all outputs

## How to run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## How to deploy on Streamlit Community Cloud

1. Create a GitHub repository.
2. Upload these files:
   - `streamlit_app.py`
   - `validation_engine.py`
   - `requirements.txt`
   - `README.md`
   - `sample_data/`
3. Go to Streamlit Community Cloud.
4. New app → select repo → main file: `streamlit_app.py`.
5. Deploy.

## Main validation tabs

### 1 Upload & Setup
Upload model and reference files. Enter building area, simulation years, weather label and reference source.

### 2 Clean / EUI Validation
Use for DOE/NREL secondary school, DesignBuilder clean baseline, Egypt GBC EUI, or annual reference values.

Required reference plan columns:

```csv
kpi,reference_value,reference_unit,model_column,model_value_mode,tolerance_pct,notes
```

Allowed `model_value_mode` values:

- `direct`
- `total_mwh_to_annual_eui`
- `annual_mwh_to_eui`
- `total_kwh_to_annual_eui`
- `annual_kwh_to_eui`
- `kg_to_tonne`
- `tonne_to_kg`

### 3 Time-Series Validation
Use for monthly/daily/hourly model-vs-reference CSVs. Select model/reference columns and optional date columns.

### 4 Degradation / Fault Penalty
Use for LBNL/Wang/Nassif/Yang-style fault/degradation comparisons. Calculates normalized penalties vs a clean baseline.

Published penalty reference template:

```csv
fault_mechanism,metric,published_penalty_pct,tolerance_pct,notes
```

### 5 S0-S3 Policy Benchmark
Compares S1/S2/S3 against S0 or any selected baseline policy.

### 6 Analytical Benchmarks
Runs exact closed-form verification for:

- heat-exchanger fouling: `Rf(t)=Rf* [1-exp(-Bt)]`
- filter clogging: `dP(t)=dP0+K*m_dot*d*t`

### 7 Final Report & Export
Builds a full ZIP package with all tables, graphs and Excel report.

## Recommended validation workflow for your thesis/paper

1. Run clean DOE/DesignBuilder baseline validation with degradation OFF.
2. Run time-series validation if monthly/daily reference data are available.
3. Run degradation/fault penalty validation using published fault papers or LBNL FDD data.
4. Run S0-S3 policy benchmark to show internal strategy behaviour.
5. Run analytical fouling/filter benchmarks to verify degradation equations.
6. Export the ZIP and use it in your PhD defence and manuscript.

## Important scientific note

This tool does not prove that one published dataset validates the entire degradation-aware EMS framework. It supports a layered validation strategy:

- clean building-energy layer validation
- time-series validation where data exist
- degradation/fault behaviour validation
- internal S0-S3 policy benchmark
- analytical numerical verification

This is the defensible structure for a reduced-order HVAC degradation framework.
