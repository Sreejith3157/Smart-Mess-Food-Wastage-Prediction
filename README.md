# Smart Mess – Food Wastage Prediction and Analysis System

A Flask web application that helps a hostel/college mess track food prepared vs. wasted, predict
wastage for an upcoming meal with a Random Forest model, and export reports.

**Features:** session login · responsive Bootstrap 5 dashboard with Chart.js charts · wastage prediction
with recommendations · dataset upload with strict validation · model training/evaluation with real metrics ·
SQLite prediction history · CSV and PDF report downloads.

> **About the data.** This project was rebuilt from scratch (the original files were unavailable), so it
> ships with a **synthetic demo dataset** that is labelled as such everywhere in the UI, the saved metadata,
> the prediction history and the PDF. Replace it with your real records (Dataset page → Upload) before relying
> on any number the app produces.

## Project structure

```
app.py                 Flask routes (auth, dashboard, predict, dataset, performance, reports)
requirements.txt
README.md
.gitignore
utils/
  schema.py            ONE definition of columns, categories, features, paths, thresholds
  data.py              CSV reading/validation, profiling, summaries, synthetic data generator
  ml.py                shared preprocessing+model Pipeline, training/evaluation, prediction, recommendations
  db.py                SQLite (users + prediction history)
  reports.py           CSV and PDF builders
templates/             base, login, dashboard, predict, dataset, performance, reports, error
static/css/style.css   static/js/app.js   static/js/charts.js
data/                  mess_data.csv (synthetic demo), dataset_meta.json (records the data source)
outputs/               created at runtime: model.joblib, metrics.json, smart_mess.db
```

## Dataset schema (used everywhere)

One row = one meal service.

| Column | Type / allowed values |
|---|---|
| `date` | `YYYY-MM-DD` |
| `meal_type` | Breakfast, Lunch, Dinner |
| `day_type` | Weekday, Weekend, Holiday |
| `menu_type` | Regular, Special |
| `students_present` | whole number > 0 |
| `food_prepared_kg` | number > 0 |
| `food_wasted_kg` | 0 ≤ value ≤ `food_prepared_kg` — **the prediction target** |

**Model features:** `meal_type, day_type, menu_type, students_present, food_prepared_kg`
(`date` is stored for reporting but is not a model input).

Derived values: *consumption = prepared − wasted* and *wastage % = wasted ÷ prepared × 100*. For a
prediction, the app predicts wasted kg, then computes consumption and percentage from the prepared amount you
entered. The dashboard's "students served" is the sum of `students_present` over all meals (student-meals).

## Windows setup (step by step)

1. **Install Python 3.10 – 3.13** from <https://www.python.org/downloads/>. Tick **"Add python.exe to PATH"**
   in the installer. Check in a new terminal: `python --version`.
2. **Open PowerShell** in the project folder (in File Explorer: open the folder, click the address bar, type
   `powershell`, press Enter).
3. **Create and activate a virtual environment:**
   ```powershell
   python -m venv venv
   venv\Scripts\Activate.ps1
   ```
   If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope Process Bypass` and activate again, or use
   Command Prompt and run `venv\Scripts\activate.bat`.
4. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```
5. **(Recommended) choose your own admin login before the first run.** The database is created on first start and
   the credentials are read only then:
   ```powershell
   $env:ADMIN_USERNAME = "yourname"
   $env:ADMIN_PASSWORD = "a-strong-password"
   ```
   If you skip this, the default account is **admin / admin123**. Change it before sharing the app
   (delete `outputs\smart_mess.db` and restart to re-seed; this also erases prediction history).
6. **Run the app:**
   ```powershell
   python app.py
   ```
7. **Open** <http://127.0.0.1:5000> in your browser and **log in**.
8. **Train and evaluate the model:** sidebar → **Model performance** → **Train & evaluate model**. The page then shows
   R², MAE, MSE, RMSE and the charts, all from the real test-set results.
9. **Make a prediction:** sidebar → **Predict wastage**, fill in the form, press **Predict wastage**. The result
   (predicted kg, estimated consumption, wastage %, recommendation) is saved automatically.
10. **Download reports:** sidebar → **Reports** → **Download CSV** or **Download PDF**.
11. **Stop the server** with `Ctrl + C`.

An internet connection is needed in the browser: Bootstrap, Bootstrap Icons, Chart.js and the Google font load from
CDNs. (The font falls back to system fonts; without the other CDNs the layout and charts will not render.)

macOS / Linux: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt && python app.py`.

## Using your own data

1. **Dataset** → *Download blank template*, fill it with your records (or match the columns above).
2. **Upload.** Validation is strict: if **any** row is invalid, the upload is rejected, nothing changes, and the first
   problems are listed with CSV row numbers. Column names are case/space-insensitive; extra columns are ignored.
3. The previous file is kept as `data/mess_data.previous.csv`.
4. Go to **Model performance** and **retrain**. The app warns whenever the dataset changed after training.

At least **50 valid rows** are required to train. Realistically you need far more, covering all meals, day types
and menu types.

## How training and evaluation work

* One scikit-learn `Pipeline` (one-hot encoding of the three categorical columns with a fixed category list +
  `RandomForestRegressor`, 300 trees, `min_samples_leaf=2`, `random_state=42`) is used for **both** training and
  prediction, so preprocessing cannot differ between them.
* Valid rows are split **80 % train / 20 % test** (`random_state=42`). The model is fitted on the training part and
  scored on the held-out part. The saved model is that same model, so the displayed metrics describe it exactly.
* Reported: **R², MAE, MSE, RMSE** (test set), plus training R², 5-fold cross-validated R² (training rows only) and a
  *baseline MAE* (always predicting the training mean) so you can tell whether the model adds value.
* Metrics are saved to `outputs/metrics.json` and read back from there; nothing is hard-coded or invented.
* Predictions are limited to the physically possible range 0 … food prepared, and a warning is shown (and saved) if the
  inputs are outside the range seen in training.
* **Performance depends on dataset quality and size.** Small, noisy or unrepresentative data gives unreliable scores
  and predictions.

### Example from the development test run (synthetic data)
Training on the 540-row synthetic dataset gave: R² = 0.636, MAE = 10.67 kg, MSE = 207.36 kg², RMSE = 14.40 kg
(432 train / 108 test rows; baseline MAE 18.85 kg). These are **synthetic-data numbers**. Your run should give
similar values (same seed) but may differ slightly across library versions, and they say nothing about a real mess.

## Recommendations

The recommendation text combines (a) the predicted wastage band — Low < 5 %, Moderate 5–10 %, High ≥ 10 %
(guideline values in `utils/schema.py`; change them to fit your policy) — and (b) the **median food eaten per
student for that meal** in your dataset, used to suggest a quantity (plus a 5 % buffer). Part (b) appears only when
the dataset has at least 10 comparable rows.

## Security notes

* All pages except the login are protected by a session; forms use CSRF tokens; passwords are hashed; logout is a POST.
* Repeated failed logins from one IP are temporarily blocked (in memory; resets when the server restarts).
* The secret key is generated once into `outputs/.secret_key` (or set the `SECRET_KEY` environment variable).
* There is one user table and no user-management screen. Use the built-in development server only on a trusted
  network; for real deployment put the app behind a production server (e.g. `waitress` on Windows) and HTTPS.

## Configuration (optional environment variables)

`ADMIN_USERNAME`, `ADMIN_PASSWORD` (first run only), `SECRET_KEY`, `PORT` (default 5000), `FLASK_DEBUG=1`.

## Testing status — what was and was not verified

**Verified** (automated script using Flask's test client, plus a live server run with `curl`; Linux, Python 3.12,
Flask 3.1, pandas 3.0, scikit-learn 1.8): login/logout, route protection, CSRF rejection, wrong-credential messages,
login throttling, dashboard rendering, model training and the metrics file, prediction validation (invalid, NaN,
infinite and out-of-range inputs), saving to SQLite, CSV/PDF downloads (valid files; the PDF was visually inspected),
dataset upload accept/reject cases, missing/corrupt dataset and model handling, and retrain-after-change warnings.

**Not verified:** running on Windows itself, and how the pages look and behave in a real browser. The HTML was
rendered and checked for content, but not screenshotted, and the Chart.js charts were not drawn in a browser.
Package versions in `requirements.txt` are minimums (`>=`); a very old Python may fail to install them.

## Troubleshooting

* *`python` not recognised* – reinstall Python with "Add to PATH", then reopen the terminal.
* *Port 5000 busy* – `$env:PORT = 5001` then `python app.py`.
* *Charts/styles missing* – the browser could not reach the CDNs (no internet, or blocked).
* *"The saved model could not be loaded"* – scikit-learn was upgraded after training; retrain on Model performance.
* *Forgot password* – stop the app, delete `outputs\smart_mess.db`, set `ADMIN_USERNAME`/`ADMIN_PASSWORD`, restart
  (this also clears prediction history).
