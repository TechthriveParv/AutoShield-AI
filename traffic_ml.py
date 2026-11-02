"""Train a Random Forest from the project's labelled CSV dataset.
The included CSV is synthetic demonstration data and must be replaced with validated data.
"""
from pathlib import Path
import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "traffic_patterns.csv"
MODEL_DIR = BASE_DIR / "models"
MODEL_PATH = MODEL_DIR / "traffic_pattern_rf.joblib"
FEATURES = [
    "vehicle_age", "violations_90d", "accidents_365d", "pending_reviews",
    "insurance_expired", "puc_expired", "registration_expired",
]
TARGET = "traffic_pattern"
ALLOWED_LABELS = {"Routine", "Monitor", "Priority Review"}

def train_model():
    """Train a new model on the current CSV and return model + honest holdout metrics."""
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Training CSV not found: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    required = FEATURES + [TARGET]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError("CSV is missing required columns: " + ", ".join(missing))
    df = df[required].dropna()
    if len(df) < 15:
        raise ValueError("Add at least 15 labelled rows to data/traffic_patterns.csv before training.")
    if df[TARGET].nunique() < 2:
        raise ValueError("The training CSV must contain at least two different traffic_pattern labels.")
    X = df[FEATURES].apply(pd.to_numeric, errors="raise")
    y = df[TARGET].astype(str)
    # Hold out test rows; stratify only when each class has enough examples.
    stratify = y if y.value_counts().min() >= 2 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=stratify
    )
    model = RandomForestClassifier(
        n_estimators=200, max_depth=8, min_samples_leaf=2,
        class_weight="balanced", random_state=42, n_jobs=-1
    )
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    report = classification_report(y_test, predictions, output_dict=True, zero_division=0)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    counts = y.value_counts().to_dict()
    importances = sorted(
        [{"feature": name, "importance": float(value)} for name, value in zip(FEATURES, model.feature_importances_)],
        key=lambda item: item["importance"], reverse=True
    )
    return {
        "model": model,
        "accuracy": accuracy,
        "report": report,
        "rows": len(df),
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "class_counts": counts,
        "importances": importances,
        "features": FEATURES,
        "target": TARGET,
        "model_path": str(MODEL_PATH),
    }
