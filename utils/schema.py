"""Single source of truth for the dataset schema, file paths and thresholds.

Every other module (data validation, training, prediction, reports, UI) imports
from here so the schema stays consistent throughout the application.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"

DATASET_PATH = DATA_DIR / "mess_data.csv"
DATASET_BACKUP_PATH = DATA_DIR / "mess_data.previous.csv"
DATASET_META_PATH = DATA_DIR / "dataset_meta.json"

MODEL_PATH = OUTPUT_DIR / "model.joblib"
METRICS_PATH = OUTPUT_DIR / "metrics.json"
DB_PATH = OUTPUT_DIR / "smart_mess.db"
SECRET_KEY_PATH = OUTPUT_DIR / ".secret_key"

# ---- Dataset schema -------------------------------------------------------
# One row = one meal service (e.g. Lunch on a given date).
COLUMNS = [
    "date",              # YYYY-MM-DD
    "meal_type",         # Breakfast | Lunch | Dinner
    "day_type",          # Weekday | Weekend | Holiday
    "menu_type",         # Regular | Special
    "students_present",  # whole number of students who ate / were expected
    "food_prepared_kg",  # total food cooked (kg)
    "food_wasted_kg",    # leftover / discarded food (kg)  <- prediction target
]

CATEGORY_VALUES = {
    "meal_type": ["Breakfast", "Lunch", "Dinner"],
    "day_type": ["Weekday", "Weekend", "Holiday"],
    "menu_type": ["Regular", "Special"],
}

CATEGORICAL_FEATURES = ["meal_type", "day_type", "menu_type"]
NUMERIC_FEATURES = ["students_present", "food_prepared_kg"]
FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES   # exact model input order
TARGET = "food_wasted_kg"
NUMERIC_COLUMNS = ["students_present", "food_prepared_kg", "food_wasted_kg"]
MEAL_ORDER = CATEGORY_VALUES["meal_type"]

# ---- Training / app settings ---------------------------------------------
MIN_TRAIN_ROWS = 50        # refuse to train on fewer valid rows than this
TEST_SIZE = 0.2
RANDOM_STATE = 42
MAX_UPLOAD_MB = 5

# Wastage-percentage bands used for labels/recommendations. These are
# application guidelines, not universal standards - adjust to your mess policy.
WASTAGE_LOW_PCT = 5.0
WASTAGE_HIGH_PCT = 10.0
SERVING_BUFFER = 1.05      # 5 % safety buffer used in the quantity recommendation

# Input limits for the prediction form
MAX_STUDENTS = 20000
MAX_PREPARED_KG = 20000.0
MIN_PREPARED_KG = 0.1
