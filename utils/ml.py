"""Model training, evaluation, loading, prediction and recommendations.

Training and prediction share ONE scikit-learn Pipeline (one-hot encoding +
Random Forest) and the same FEATURES list from schema.py, so preprocessing can
never drift between the two.
"""
import json
import os
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .schema import (
    CATEGORICAL_FEATURES, CATEGORY_VALUES, FEATURES, METRICS_PATH, MIN_TRAIN_ROWS,
    MODEL_PATH, NUMERIC_FEATURES, OUTPUT_DIR, RANDOM_STATE, SERVING_BUFFER, TARGET,
    TEST_SIZE, WASTAGE_HIGH_PCT, WASTAGE_LOW_PCT,
)

SCHEMA_VERSION = 1
_cache = {"mtime": None, "bundle": None}


def build_pipeline():
    pre = ColumnTransformer([
        ("cat", OneHotEncoder(categories=[CATEGORY_VALUES[c] for c in CATEGORICAL_FEATURES],
                              handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ("num", "passthrough", NUMERIC_FEATURES),
    ])
    model = RandomForestRegressor(n_estimators=300, min_samples_leaf=2,
                                  random_state=RANDOM_STATE, n_jobs=-1)
    return Pipeline([("prep", pre), ("model", model)])


def _atomic_json(path, payload):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _aggregate_importance(pipe):
    names = pipe.named_steps["prep"].get_feature_names_out()
    imps = pipe.named_steps["model"].feature_importances_
    totals = {f: 0.0 for f in FEATURES}
    for name, imp in zip(names, imps):
        clean = name.split("__", 1)[1]
        for feat in FEATURES:
            if clean == feat or clean.startswith(feat + "_"):
                totals[feat] += float(imp)
                break
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [{"feature": f, "importance": round(v, 4)} for f, v in ranked]


def train_and_evaluate(valid_df, dataset_meta, n_rows_in_file):
    """Train on an 80/20 split, evaluate on the held-out 20 %, save model + metrics.

    The saved model is the one trained on the 80 % split, so the reported test
    metrics describe exactly that model (no leakage from refitting on all data).
    Raises ValueError if there is not enough valid data.
    """
    if len(valid_df) < MIN_TRAIN_ROWS:
        raise ValueError(
            f"Only {len(valid_df)} valid rows are available; at least {MIN_TRAIN_ROWS} are "
            "needed to train and evaluate the model reliably.")

    X = valid_df[FEATURES]
    y = valid_df[TARGET].astype(float)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE)

    pipe = build_pipeline()
    pipe.fit(X_train, y_train)
    pred_test = pipe.predict(X_test)
    pred_train = pipe.predict(X_train)

    mse = float(mean_squared_error(y_test, pred_test))
    cv_scores = cross_val_score(build_pipeline(), X_train, y_train, cv=5, scoring="r2")
    baseline_mae = float(mean_absolute_error(y_test, np.full(len(y_test), y_train.mean())))

    trained_at = datetime.now().isoformat(timespec="seconds")
    per_student = (valid_df["food_prepared_kg"] / valid_df["students_present"])
    metrics = {
        "trained_at": trained_at,
        "algorithm": "RandomForestRegressor (300 trees, min_samples_leaf=2)",
        "features": FEATURES,
        "target": TARGET,
        "dataset_source": dataset_meta.get("source", "unknown"),
        "dataset_filename": dataset_meta.get("filename"),
        "dataset_updated_at": dataset_meta.get("updated_at"),
        "rows_in_file": int(n_rows_in_file),
        "rows_used": int(len(valid_df)),
        "rows_dropped_invalid": int(n_rows_in_file - len(valid_df)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "test_size": TEST_SIZE,
        "random_state": RANDOM_STATE,
        "r2": float(r2_score(y_test, pred_test)),
        "mae": float(mean_absolute_error(y_test, pred_test)),
        "mse": mse,
        "rmse": float(np.sqrt(mse)),
        "train_r2": float(r2_score(y_train, pred_train)),
        "cv_r2_mean": float(cv_scores.mean()),
        "cv_r2_std": float(cv_scores.std()),
        "baseline_mae": baseline_mae,
        "target_mean_kg": float(y.mean()),
        "feature_importance": _aggregate_importance(pipe),
        "feature_ranges": {
            "students_present": [float(valid_df["students_present"].min()), float(valid_df["students_present"].max())],
            "food_prepared_kg": [float(valid_df["food_prepared_kg"].min()), float(valid_df["food_prepared_kg"].max())],
            "prepared_per_student_kg": [float(per_student.min()), float(per_student.max())],
        },
        "actual_vs_predicted": [
            {"actual": round(float(a), 3), "predicted": round(float(p), 3)}
            for a, p in list(zip(y_test.to_numpy(), pred_test))[:300]
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp_model = MODEL_PATH.with_suffix(".tmp")
    joblib.dump({"pipeline": pipe, "features": FEATURES, "trained_at": trained_at,
                 "schema_version": SCHEMA_VERSION}, tmp_model)
    os.replace(tmp_model, MODEL_PATH)
    _atomic_json(METRICS_PATH, metrics)
    _cache.update(mtime=None, bundle=None)
    return metrics


def load_metrics():
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_bundle():
    """Return (bundle, error_message). Never raises."""
    if not MODEL_PATH.exists():
        return None, "No trained model found. Train the model on the Model Performance page first."
    try:
        mtime = MODEL_PATH.stat().st_mtime
        if _cache["bundle"] is not None and _cache["mtime"] == mtime:
            return _cache["bundle"], None
        bundle = joblib.load(MODEL_PATH)
        if bundle.get("features") != FEATURES or bundle.get("schema_version") != SCHEMA_VERSION:
            return None, "The saved model uses a different feature schema. Please retrain it."
        _cache.update(mtime=mtime, bundle=bundle)
        return bundle, None
    except Exception as exc:  # corrupt file, incompatible scikit-learn version, ...
        return None, f"The saved model could not be loaded ({exc}). Please retrain it."


def is_stale(dataset_meta, metrics):
    """True if the dataset changed after the model was trained."""
    if not metrics:
        return False
    return metrics.get("dataset_updated_at") != dataset_meta.get("updated_at")


def predict_wastage(bundle, values):
    row = pd.DataFrame([{f: values[f] for f in FEATURES}])[FEATURES]
    return float(bundle["pipeline"].predict(row)[0])


def wastage_tier(pct):
    """Return (bootstrap_class, label) for a wastage percentage."""
    if pct < WASTAGE_LOW_PCT:
        return "success", "Low"
    if pct < WASTAGE_HIGH_PCT:
        return "warning", "Moderate"
    return "danger", "High"


def recommend(pred_kg, prepared_kg, students, meal_type, menu_type, history):
    """Build a recommendation from the prediction and real historical data."""
    pct = pred_kg / prepared_kg * 100
    _, label = wastage_tier(pct)
    parts = []
    if label == "Low":
        parts.append(f"Expected wastage is low ({pct:.1f}%). The planned quantity looks well matched; "
                     "keep monitoring leftovers to keep it there.")
    elif label == "Moderate":
        parts.append(f"Expected wastage is moderate ({pct:.1f}%). A small reduction in the quantity "
                     "cooked should help.")
    else:
        parts.append(f"Expected wastage is high ({pct:.1f}%). Reduce the quantity cooked and consider "
                     "cooking in batches.")

    if history is not None and len(history):
        subset = history[history["meal_type"] == meal_type]
        same_menu = subset[subset["menu_type"] == menu_type]
        scope = f"{meal_type} ({menu_type} menu)"
        if len(same_menu) >= 10:
            subset = same_menu
        else:
            scope = meal_type
        if len(subset) >= 10:
            eaten_pp = ((subset["food_prepared_kg"] - subset["food_wasted_kg"])
                        / subset["students_present"]).median()
            target = students * eaten_pp * SERVING_BUFFER
            if prepared_kg > target * 1.02:
                parts.append(
                    f"Historically, students ate a median of {eaten_pp * 1000:.0f} g each for {scope}. "
                    f"Cooking about {target:.1f} kg (including a 5% buffer) instead of {prepared_kg:.1f} kg "
                    f"could avoid roughly {prepared_kg - target:.1f} kg of surplus.")
            else:
                parts.append("The planned quantity is already close to the historical consumption "
                             f"level for {scope}; avoid cutting it much further to prevent shortages.")
    parts.append("If attendance is uncertain, cook a base quantity first and add a second batch on demand.")
    return " ".join(parts)
