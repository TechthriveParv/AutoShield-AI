"""Engine prediction demo models trained on synthetic data, not real engine outcomes."""
from pathlib import Path
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, mean_absolute_error
BASE=Path(__file__).resolve().parent
DATA=BASE/"data"/"engine_health_training.csv"
FEATURES=["vehicle_age_years","odometer_km","services_last_5y","engine_fault_codes","harsh_driving_events"]
def train_models():
    df=pd.read_csv(DATA)
    X=df[FEATURES]
    Xtr,Xte,ytr,yte=train_test_split(X,df["maintenance_risk"],test_size=.25,random_state=42,stratify=df["maintenance_risk"])
    clf=RandomForestClassifier(n_estimators=160,max_depth=9,random_state=42,class_weight="balanced")
    clf.fit(Xtr,ytr); risk_acc=accuracy_score(yte,clf.predict(Xte))
    Xtr2,Xte2,ytr2,yte2=train_test_split(X,df["remaining_engine_km_demo"],test_size=.25,random_state=42)
    reg=RandomForestRegressor(n_estimators=160,max_depth=10,random_state=42)
    reg.fit(Xtr2,ytr2); mae=mean_absolute_error(yte2,reg.predict(Xte2))
    return clf,reg,{"rows":len(df),"risk_accuracy":risk_acc,"life_mae_km":mae,"feature_importances":sorted(zip(FEATURES,clf.feature_importances_),key=lambda x:x[1],reverse=True)}
