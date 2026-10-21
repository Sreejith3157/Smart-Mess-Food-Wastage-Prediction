"""Smart Mess Food Wastage Prediction and Analysis System - Flask application."""
import logging
import math
import os
import secrets
import time
from datetime import date, datetime
from io import BytesIO

from flask import (Flask, abort, flash, redirect, render_template, request, send_file,
                   session, url_for)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from utils import data as D
from utils import db, ml, reports
from utils import schema as S

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("smart_mess")


# --------------------------------------------------------------------------
# App setup
# --------------------------------------------------------------------------
def _load_secret_key():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    S.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if S.SECRET_KEY_PATH.exists():
        return S.SECRET_KEY_PATH.read_text().strip()
    key = secrets.token_hex(32)
    S.SECRET_KEY_PATH.write_text(key)
    return key


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_load_secret_key(),
    MAX_CONTENT_LENGTH=S.MAX_UPLOAD_MB * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=8 * 3600,
)

S.DATA_DIR.mkdir(parents=True, exist_ok=True)
S.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
if db.init_db():
    log.warning("Default login created (admin / admin123). Set ADMIN_USERNAME and ADMIN_PASSWORD "
                "before the first run to choose your own credentials.")

# Simple in-memory login throttle: {ip: [failure_count, first_failure_time]}
_FAILED = {}
MAX_FAILS, LOCK_SECONDS = 5, 300
PUBLIC_ENDPOINTS = {"login", "static"}


def _locked(ip):
    rec = _FAILED.get(ip)
    if not rec:
        return False
    if time.time() - rec[1] > LOCK_SECONDS:
        _FAILED.pop(ip, None)
        return False
    return rec[0] >= MAX_FAILS


def _record_failure(ip):
    rec = _FAILED.get(ip)
    if not rec or time.time() - rec[1] > LOCK_SECONDS:
        _FAILED[ip] = [1, time.time()]
    else:
        rec[0] += 1


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def _safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else None


@app.before_request
def guard():
    """Require login on every route except login/static, and check CSRF on POST."""
    if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS and request.method != "POST":
        return None
    if request.endpoint not in PUBLIC_ENDPOINTS and not session.get("user"):
        flash("Please log in to continue.", "warning")
        nxt = request.path if request.method == "GET" else None
        return redirect(url_for("login", next=nxt) if nxt else url_for("login"))
    if request.method == "POST":
        sent = request.form.get("csrf_token", "").encode()
        expected = session.get("_csrf", "").encode()
        if not sent or not expected or not secrets.compare_digest(sent, expected):
            flash("Your session expired or the form was invalid. Please try again.", "danger")
            return redirect(url_for("dashboard") if session.get("user") else url_for("login"))
    return None


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.endpoint != "static":
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.context_processor
def inject_globals():
    return {"csrf_token": csrf_token, "current_user": session.get("user"), "now": datetime.now()}


@app.template_filter("tier")
def tier_filter(pct):
    return ml.wastage_tier(float(pct))


@app.template_filter("dt")
def dt_filter(value):
    return str(value).replace("T", " ") if value else "-"


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("dashboard"))
    nxt = _safe_next(request.values.get("next"))
    error, username = None, ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip = request.remote_addr or "unknown"
        if _locked(ip):
            error = "Too many failed attempts. Please wait a few minutes and try again."
        elif not username or not password:
            error = "Please enter both your username and password."
        else:
            user = db.get_user(username)
            if user and check_password_hash(user["password_hash"], password):
                _FAILED.pop(ip, None)
                session.clear()
                session["user"] = user["username"]
                session.permanent = True
                csrf_token()
                flash(f"Welcome back, {user['username']}.", "success")
                return redirect(nxt or url_for("dashboard"))
            _record_failure(ip)
            error = "Invalid username or password."
    return render_template("login.html", error=error, username=username, next=nxt)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@app.route("/dashboard")
def dashboard():
    ds = D.get_dataset()
    summary = None
    if ds["valid"] is not None and len(ds["valid"]):
        summary = D.summarize(ds["valid"])
    metrics = ml.load_metrics()
    chart = None
    if summary:
        last = summary["daily"][-30:]
        chart = {
            "page": "dashboard",
            "daily": {"labels": [r["date"] for r in last],
                      "prepared": [r["prepared"] for r in last],
                      "wasted": [r["wasted"] for r in last],
                      "pct": [round(r["wastage_pct"], 2) for r in last]},
            "meal": {"labels": [r["meal_type"] for r in summary["meal"]],
                     "prepared": [r["prepared"] for r in summary["meal"]],
                     "wasted": [r["wasted"] for r in summary["meal"]]},
            "split": {"consumed": round(summary["totals"]["consumed"], 2),
                      "wasted": round(summary["totals"]["wasted"], 2)},
        }
    return render_template(
        "dashboard.html", ds=ds, summary=summary, chart=chart, metrics=metrics,
        recent_days=list(reversed(summary["daily"][-10:])) if summary else [],
        synthetic=D.is_synthetic(ds["meta"]), source=D.source_label(ds["meta"]),
        stale=ml.is_stale(ds["meta"], metrics), pred_stats=db.prediction_stats(),
        model_ready=S.MODEL_PATH.exists())


# --------------------------------------------------------------------------
# Prediction
# --------------------------------------------------------------------------
def _parse_prediction_form(form):
    values, errors = {}, {}

    raw_date = form.get("meal_date", "").strip()
    try:
        parsed = datetime.strptime(raw_date, "%Y-%m-%d")
        if not 2000 <= parsed.year <= 2100:
            raise ValueError
        values["meal_date"] = parsed.strftime("%Y-%m-%d")
    except ValueError:
        errors["meal_date"] = "Enter a valid date."

    for field, label in (("meal_type", "meal"), ("day_type", "day type"), ("menu_type", "menu type")):
        val = form.get(field, "").strip().title()
        if val in S.CATEGORY_VALUES[field]:
            values[field] = val
        else:
            errors[field] = f"Select a valid {label}."

    raw = form.get("students_present", "").strip()
    try:
        num = float(raw)
        if not math.isfinite(num) or num % 1 != 0:
            raise ValueError
        num = int(num)
        if not 1 <= num <= S.MAX_STUDENTS:
            raise ValueError
        values["students_present"] = num
    except ValueError:
        errors["students_present"] = f"Enter a whole number between 1 and {S.MAX_STUDENTS:,}."

    raw = form.get("food_prepared_kg", "").strip()
    try:
        num = float(raw)
        if not math.isfinite(num) or not S.MIN_PREPARED_KG <= num <= S.MAX_PREPARED_KG:
            raise ValueError
        values["food_prepared_kg"] = round(num, 2)
    except ValueError:
        errors["food_prepared_kg"] = f"Enter an amount between {S.MIN_PREPARED_KG} and {S.MAX_PREPARED_KG:,.0f} kg."
    return values, errors


def _range_notes(values, metrics):
    notes = []
    if not metrics:
        return notes
    r = metrics.get("feature_ranges", {})
    checks = (("students_present", "Student count", values["students_present"], ""),
              ("food_prepared_kg", "Food prepared", values["food_prepared_kg"], " kg"),
              ("prepared_per_student_kg", "Food per student",
               values["food_prepared_kg"] / values["students_present"], " kg"))
    for key, label, v, unit in checks:
        lo, hi = r.get(key, (None, None))
        if lo is not None and not lo <= v <= hi:
            notes.append(f"{label} ({v:,.2f}{unit}) is outside the training range "
                         f"({lo:,.2f}-{hi:,.2f}{unit}); the prediction may be less reliable.")
    return notes


@app.route("/predict", methods=["GET", "POST"])
def predict():
    bundle, model_error = ml.load_bundle()
    metrics = ml.load_metrics()
    meta = D.read_meta()
    form = {"meal_date": date.today().isoformat(), "meal_type": "", "day_type": "",
            "menu_type": "Regular", "students_present": "", "food_prepared_kg": ""}
    errors = {}

    if request.method == "POST":
        form.update({k: request.form.get(k, "") for k in form})
        if bundle is None:
            flash(model_error, "danger")
        else:
            values, errors = _parse_prediction_form(request.form)
            if errors:
                flash("Please correct the highlighted fields.", "danger")
            else:
                try:
                    raw_pred = ml.predict_wastage(bundle, values)
                    if not math.isfinite(raw_pred):
                        raise ValueError("non-finite model output")
                except Exception:
                    log.exception("Prediction failed")
                    flash("The model could not produce a prediction for these inputs.", "danger")
                else:
                    prepared = values["food_prepared_kg"]
                    pred = min(max(raw_pred, 0.0), prepared)
                    notes = _range_notes(values, metrics)
                    if pred != raw_pred:
                        notes.append(f"The raw model output ({raw_pred:.2f} kg) was limited to the "
                                     f"valid range of 0 to {prepared:.2f} kg.")
                    ds = D.get_dataset()
                    rec_text = ml.recommend(pred, prepared, values["students_present"], values["meal_type"],
                                            values["menu_type"], ds["valid"])
                    pred_id = db.add_prediction({
                        **{k: values[k] for k in ("meal_date", "meal_type", "day_type", "menu_type",
                                                   "students_present", "food_prepared_kg")},
                        "created_by": session["user"],
                        "predicted_wastage_kg": round(pred, 2),
                        "est_consumption_kg": round(prepared - pred, 2),
                        "wastage_pct": round(pred / prepared * 100, 2),
                        "recommendation": rec_text,
                        "notes": " ".join(notes),
                        "model_trained_at": bundle["trained_at"],
                        "dataset_source": metrics.get("dataset_source") if metrics else meta.get("source"),
                    })
                    flash("Prediction saved to your history.", "success")
                    return redirect(url_for("predict", result=pred_id))

    result = None
    rid = request.args.get("result", type=int)
    if rid:
        result = db.get_prediction(rid)
        if result is None:
            flash("That prediction was not found.", "warning")
    return render_template(
        "predict.html", form=form, errors=errors, result=result, model_ready=bundle is not None,
        model_error=model_error, metrics=metrics, categories=S.CATEGORY_VALUES,
        stale=ml.is_stale(meta, metrics) if bundle else False,
        synthetic=metrics.get("dataset_source") == "synthetic_demo" if metrics else False,
        max_students=S.MAX_STUDENTS, max_kg=S.MAX_PREPARED_KG, min_kg=S.MIN_PREPARED_KG)


# --------------------------------------------------------------------------
# Dataset management
# --------------------------------------------------------------------------
PAGE_SIZE = 25


@app.route("/dataset")
def dataset():
    ds = D.get_dataset()
    prof = page_rows = None
    page = max(request.args.get("page", 1, type=int), 1)
    pages = 1
    if ds["raw"] is not None:
        prof = D.profile(ds)
        pages = max(math.ceil(len(ds["raw"]) / PAGE_SIZE), 1)
        page = min(page, pages)
        chunk = ds["raw"].iloc[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        page_rows = chunk.fillna("").to_dict("records")
    return render_template(
        "dataset.html", ds=ds, prof=prof, rows=page_rows, page=page, pages=pages,
        page_size=PAGE_SIZE, columns=S.COLUMNS, categories=S.CATEGORY_VALUES,
        synthetic=D.is_synthetic(ds["meta"]), source=D.source_label(ds["meta"]),
        max_mb=S.MAX_UPLOAD_MB, backup_exists=S.DATASET_BACKUP_PATH.exists())


@app.route("/dataset/upload", methods=["POST"])
def dataset_upload():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a CSV file to upload.", "danger")
        return redirect(url_for("dataset"))
    if not file.filename.lower().endswith(".csv"):
        flash("Only .csv files are accepted.", "danger")
        return redirect(url_for("dataset"))
    try:
        raw = D.read_csv_source(file.stream)
    except ValueError as exc:
        flash(f"Upload rejected: {exc}", "danger")
        return redirect(url_for("dataset"))
    typed, issues, invalid = D.coerce_and_check(raw)
    if invalid.any():
        flash(f"Upload rejected: {int(invalid.sum())} of {len(raw)} rows have problems. "
              "Nothing was changed.", "danger")
        for issue in issues[:8]:
            rows = ", ".join(str(r) for r in issue["rows"])
            flash(f"{issue['message']} - {issue['count']} row(s), e.g. CSV row {rows}", "danger")
        return redirect(url_for("dataset"))
    D.save_dataset(typed, "uploaded", secure_filename(file.filename) or "upload.csv")
    flash(f"Dataset uploaded: {len(typed):,} rows. Retrain the model to use the new data.", "success")
    return redirect(url_for("dataset"))


@app.route("/dataset/demo", methods=["POST"])
def dataset_demo():
    if D.get_dataset()["exists"] and request.form.get("confirm") != "yes":
        flash("Tick the confirmation box to replace the current dataset with synthetic demo data.", "warning")
        return redirect(url_for("dataset"))
    df = D.generate_synthetic()
    D.save_dataset(df, "synthetic_demo", "generated_synthetic_demo.csv")
    flash(f"Synthetic DEMO dataset created ({len(df):,} rows). It is artificial - not real mess data.", "warning")
    return redirect(url_for("dataset"))


@app.route("/dataset/download")
def dataset_download():
    if not S.DATASET_PATH.exists():
        flash("There is no dataset to download.", "warning")
        return redirect(url_for("dataset"))
    return send_file(S.DATASET_PATH, mimetype="text/csv", as_attachment=True, download_name="mess_data.csv")


@app.route("/dataset/template.csv")
def dataset_template():
    return send_file(BytesIO(D.template_csv().encode()), mimetype="text/csv", as_attachment=True,
                     download_name="mess_data_template.csv")


# --------------------------------------------------------------------------
# Model performance
# --------------------------------------------------------------------------
@app.route("/performance")
def performance():
    metrics = ml.load_metrics()
    ds_meta = D.read_meta()
    bundle, model_error = ml.load_bundle()
    chart = None
    if metrics:
        chart = {"page": "performance", "points": metrics["actual_vs_predicted"],
                 "importance": metrics["feature_importance"]}
    return render_template(
        "performance.html", metrics=metrics, chart=chart, model_error=model_error if not bundle else None,
        stale=ml.is_stale(ds_meta, metrics), dataset_exists=S.DATASET_PATH.exists(),
        synthetic_now=D.is_synthetic(ds_meta),
        synthetic_metrics=bool(metrics) and metrics.get("dataset_source") == "synthetic_demo",
        min_rows=S.MIN_TRAIN_ROWS)


@app.route("/performance/train", methods=["POST"])
def performance_train():
    ds = D.get_dataset()
    if not ds["exists"]:
        flash("No dataset found. Upload a CSV or generate the synthetic demo dataset first.", "danger")
        return redirect(url_for("dataset"))
    if ds["error"]:
        flash(ds["error"], "danger")
        return redirect(url_for("dataset"))
    try:
        m = ml.train_and_evaluate(ds["valid"], ds["meta"], len(ds["raw"]))
    except ValueError as exc:
        flash(str(exc), "danger")
    except Exception:
        log.exception("Training failed")
        flash("Training failed unexpectedly. See the server console for details.", "danger")
    else:
        msg = (f"Model trained and evaluated on {m['n_test']} held-out rows: "
               f"R² = {m['r2']:.3f}, MAE = {m['mae']:.2f} kg.")
        if m["rows_dropped_invalid"]:
            msg += f" {m['rows_dropped_invalid']} invalid row(s) were excluded."
        flash(msg, "success")
    return redirect(url_for("performance"))


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
@app.route("/reports")
def reports_page():
    return render_template("reports.html", predictions=db.list_predictions(limit=100),
                           stats=db.prediction_stats())


@app.route("/reports/download/csv")
def report_csv():
    payload = reports.build_csv(db.list_predictions())
    return send_file(BytesIO(payload), mimetype="text/csv", as_attachment=True,
                     download_name=f"prediction_history_{datetime.now():%Y%m%d_%H%M%S}.csv")


@app.route("/reports/download/pdf")
def report_pdf():
    try:
        ds = D.get_dataset()
        summary = D.summarize(ds["valid"]) if ds["valid"] is not None and len(ds["valid"]) else None
        pdf = reports.build_pdf(db.list_predictions(), summary, ds["meta"], ml.load_metrics())
    except Exception:
        log.exception("PDF generation failed")
        flash("The PDF report could not be generated. See the server console for details.", "danger")
        return redirect(url_for("reports_page"))
    return send_file(BytesIO(pdf), mimetype="application/pdf", as_attachment=True,
                     download_name=f"smart_mess_report_{datetime.now():%Y%m%d_%H%M%S}.pdf")


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, title="Page not found",
                           message="The page you were looking for does not exist."), 404


@app.errorhandler(413)
def too_large(_):
    flash(f"That file is too large. The limit is {S.MAX_UPLOAD_MB} MB.", "danger")
    return redirect(url_for("dataset") if session.get("user") else url_for("login"))


@app.errorhandler(500)
def server_error(_):
    return render_template("error.html", code=500, title="Something went wrong",
                           message="An unexpected error occurred. Details are in the server console."), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG") == "1")
