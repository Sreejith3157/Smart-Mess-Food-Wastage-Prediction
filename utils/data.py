"""Dataset loading, validation, profiling, summarising and synthetic demo data."""
import json
import os
import shutil
from datetime import datetime

import numpy as np
import pandas as pd

from .schema import (
    CATEGORY_VALUES, COLUMNS, DATA_DIR, DATASET_BACKUP_PATH, DATASET_META_PATH,
    DATASET_PATH, MEAL_ORDER, NUMERIC_COLUMNS,
)

MAX_ROWS = 200_000
SOURCE_LABELS = {
    "synthetic_demo": "Synthetic demo data",
    "uploaded": "Uploaded dataset",
}


# --------------------------------------------------------------------------
# Metadata (records where the current dataset came from)
# --------------------------------------------------------------------------
def read_meta():
    try:
        return json.loads(DATASET_META_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_meta(source, filename, rows):
    meta = {
        "source": source,
        "filename": filename,
        "rows": int(rows),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    tmp = DATASET_META_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp, DATASET_META_PATH)
    return meta


def is_synthetic(meta):
    return meta.get("source") == "synthetic_demo"


def source_label(meta):
    return SOURCE_LABELS.get(meta.get("source"), "Unknown source (no metadata)")


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------
def _clean_str(value):
    return value.strip() if isinstance(value, str) else value


def _normalise_frame(df):
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    df = df.apply(lambda col: col.map(_clean_str))
    df = df.replace(r"^\s*$", np.nan, regex=True)
    return df.reset_index(drop=True)


def read_csv_source(source):
    """Read a CSV (path or file-like) as text and normalise it.

    Raises ValueError with a user-friendly message if it cannot be used.
    """
    try:
        df = pd.read_csv(source, dtype=str, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        raise ValueError("The CSV file is empty.")
    except pd.errors.ParserError as exc:
        raise ValueError(f"The file is not a valid CSV: {exc}")
    except UnicodeDecodeError:
        raise ValueError("The file is not UTF-8 text. Save it as 'CSV UTF-8' and try again.")
    df = _normalise_frame(df)
    if df.columns.duplicated().any():
        raise ValueError("The CSV contains duplicate column names.")
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "Missing required column(s): " + ", ".join(missing)
            + ". Required columns: " + ", ".join(COLUMNS) + "."
        )
    if df.empty:
        raise ValueError("The CSV has a header but no data rows.")
    if len(df) > MAX_ROWS:
        raise ValueError(f"The CSV has {len(df):,} rows; the limit is {MAX_ROWS:,}.")
    return df[COLUMNS].copy()


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def coerce_and_check(df):
    """Convert columns to their proper types and find invalid rows.

    Returns (typed_df, issues, invalid_mask). `typed_df` has the same index as
    the input; invalid cells are NaN/NaT. `issues` is a list of
    {message, count, rows} where `rows` are CSV row numbers (header = row 1).
    """
    df = df.reset_index(drop=True)
    work = df[COLUMNS].copy()
    typed = pd.DataFrame(index=work.index)
    checks = []

    def add(mask, message):
        checks.append((message, pd.Series(mask, index=work.index).fillna(False).astype(bool)))

    for col in COLUMNS:
        add(work[col].isna(), f"Missing value in '{col}'")

    parsed = pd.to_datetime(work["date"], format="%Y-%m-%d", errors="coerce")
    add(work["date"].notna() & parsed.isna(), "Invalid 'date' (expected YYYY-MM-DD)")
    typed["date"] = parsed.dt.strftime("%Y-%m-%d")

    for col, allowed in CATEGORY_VALUES.items():
        norm = work[col].map(lambda v: v.strip().title() if isinstance(v, str) else np.nan)
        typed[col] = norm
        add(norm.notna() & ~norm.isin(allowed),
            f"Invalid value in '{col}' (allowed: {', '.join(allowed)})")

    for col in NUMERIC_COLUMNS:
        num = pd.to_numeric(work[col], errors="coerce")
        finite = np.isfinite(num)
        add(work[col].notna() & ~finite, f"Non-numeric or infinite value in '{col}'")
        typed[col] = num.where(finite)

    s, p, w = typed["students_present"], typed["food_prepared_kg"], typed["food_wasted_kg"]
    add(s.notna() & (s % 1 != 0), "'students_present' must be a whole number")
    add(s.notna() & (s <= 0), "'students_present' must be greater than 0")
    add(p.notna() & (p <= 0), "'food_prepared_kg' must be greater than 0")
    add(w.notna() & (w < 0), "'food_wasted_kg' cannot be negative")
    add(w.notna() & p.notna() & (w > p), "'food_wasted_kg' cannot exceed 'food_prepared_kg'")

    invalid = pd.Series(False, index=work.index)
    issues = []
    for message, mask in checks:
        if mask.any():
            invalid |= mask
            positions = np.flatnonzero(mask.to_numpy())
            issues.append({
                "message": message,
                "count": int(mask.sum()),
                "rows": [int(i) + 2 for i in positions[:5]],
            })
    return typed[COLUMNS], issues, invalid


def get_dataset():
    """Load the current dataset and everything the views need about it.

    Never raises for missing/broken files; returns a dict describing the state.
    """
    state = {"exists": DATASET_PATH.exists(), "error": None, "raw": None, "valid": None,
             "issues": [], "n_invalid": 0, "meta": read_meta()}
    if not state["exists"]:
        return state
    try:
        raw = read_csv_source(DATASET_PATH)
    except ValueError as exc:
        state["error"] = f"The dataset file cannot be used: {exc}"
        return state
    except OSError as exc:
        state["error"] = f"The dataset file cannot be read: {exc}"
        return state
    typed, issues, invalid = coerce_and_check(raw)
    state.update(raw=raw, valid=typed[~invalid].copy(), issues=issues, n_invalid=int(invalid.sum()))
    return state


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
def save_dataset(df, source, filename):
    """Atomically replace the dataset (previous file is kept as a backup)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DATASET_PATH.exists():
        shutil.copy2(DATASET_PATH, DATASET_BACKUP_PATH)
    tmp = DATASET_PATH.with_suffix(".tmp")
    df[COLUMNS].to_csv(tmp, index=False, encoding="utf-8")
    os.replace(tmp, DATASET_PATH)
    return write_meta(source, filename, len(df))


def template_csv():
    return ",".join(COLUMNS) + "\n"


# --------------------------------------------------------------------------
# Profiling & summaries
# --------------------------------------------------------------------------
def _records(df):
    return json.loads(df.to_json(orient="records"))


def profile(state):
    raw, valid = state["raw"], state["valid"]
    missing = {c: int(raw[c].isna().sum()) for c in COLUMNS}
    stats = []
    for col in NUMERIC_COLUMNS:
        if len(valid):
            d = valid[col].describe()
            stats.append({
                "column": col, "count": int(d["count"]), "mean": round(float(d["mean"]), 2),
                "std": round(float(d["std"]), 2) if pd.notna(d["std"]) else 0.0,
                "min": round(float(d["min"]), 2), "q25": round(float(d["25%"]), 2),
                "median": round(float(d["50%"]), 2), "q75": round(float(d["75%"]), 2),
                "max": round(float(d["max"]), 2),
            })
    return {
        "rows": int(len(raw)),
        "columns": len(COLUMNS),
        "missing_total": int(sum(missing.values())),
        "missing": missing,
        "valid_rows": int(len(valid)),
        "invalid_rows": state["n_invalid"],
        "date_min": valid["date"].min() if len(valid) else None,
        "date_max": valid["date"].max() if len(valid) else None,
        "stats": stats,
    }


def summarize(valid):
    prepared = float(valid["food_prepared_kg"].sum())
    wasted = float(valid["food_wasted_kg"].sum())
    totals = {
        "meals": int(len(valid)),
        "days": int(valid["date"].nunique()),
        "student_meals": int(valid["students_present"].sum()),
        "avg_students": float(valid["students_present"].mean()),
        "prepared": prepared,
        "wasted": wasted,
        "consumed": prepared - wasted,
        "wastage_pct": (wasted / prepared * 100) if prepared else 0.0,
        "date_min": valid["date"].min(),
        "date_max": valid["date"].max(),
    }

    def aggregate(group_col):
        g = valid.groupby(group_col).agg(
            meals=("date", "size"),
            students=("students_present", "sum"),
            prepared=("food_prepared_kg", "sum"),
            wasted=("food_wasted_kg", "sum"),
        )
        g["consumed"] = g["prepared"] - g["wasted"]
        g["wastage_pct"] = g["wasted"] / g["prepared"] * 100
        return g

    daily = aggregate("date").sort_index().round(2).reset_index()
    meal = aggregate("meal_type").reindex([m for m in MEAL_ORDER if m in set(valid["meal_type"])])
    meal = meal.round(2).reset_index()
    return {"totals": totals, "daily": _records(daily), "meal": _records(meal)}


# --------------------------------------------------------------------------
# Synthetic demo data
# --------------------------------------------------------------------------
def generate_synthetic(days=180, seed=42):
    """Create a reproducible SYNTHETIC dataset in the application schema.

    Wastage is generated as (food prepared) - (students x appetite), so the
    data follows a simple rule. Model metrics computed on it show how well the
    model recovers that rule - they say nothing about a real mess.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-07-01", periods=days)
    holiday_idx = set(rng.choice(np.flatnonzero(dates.dayofweek < 5),
                                 size=max(1, days // 30), replace=False).tolist())
    base_students = {"Breakfast": 300, "Lunch": 400, "Dinner": 420}
    appetite_kg = {"Breakfast": 0.30, "Lunch": 0.48, "Dinner": 0.50}   # eaten per student
    attendance = {"Weekday": 1.0, "Weekend": 0.78, "Holiday": 0.55}
    rows = []
    for i, d in enumerate(dates):
        day_type = "Holiday" if i in holiday_idx else ("Weekend" if d.dayofweek >= 5 else "Weekday")
        for meal in MEAL_ORDER:
            students = max(20, int(round(base_students[meal] * attendance[day_type] * rng.normal(1, 0.06))))
            special_p = 0.30 if (d.dayofweek == 6 and meal != "Breakfast") else 0.08
            menu = "Special" if rng.random() < special_p else "Regular"
            eaten = students * appetite_kg[meal] * (1.10 if menu == "Special" else 1.0) * rng.normal(1, 0.08)
            over = rng.uniform(1.10, 1.60) if day_type == "Holiday" else rng.uniform(1.00, 1.40)
            prepared = students * appetite_kg[meal] * over
            wasted = float(np.clip(prepared - eaten, 0.01 * prepared, 0.6 * prepared))
            rows.append({
                "date": d.strftime("%Y-%m-%d"), "meal_type": meal, "day_type": day_type,
                "menu_type": menu, "students_present": students,
                "food_prepared_kg": round(prepared, 2), "food_wasted_kg": round(wasted, 2),
            })
    return pd.DataFrame(rows, columns=COLUMNS)
