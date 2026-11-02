from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort
from werkzeug.utils import secure_filename
from pathlib import Path
from datetime import date, datetime, timedelta
import sqlite3, csv, io, json, os
from traffic_ml import train_model, FEATURES

BASE = Path(__file__).resolve().parent
DB = BASE / "autoshield.db"
UPLOADS = BASE / "uploads"
UPLOADS.mkdir(exist_ok=True)
app = Flask(__name__)
app.secret_key = os.environ.get("AUTOSHIELD_SECRET", "local-demo-secret-change-before-deploy")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
ALLOWED = {"png", "jpg", "jpeg", "webp"}

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def log(action, detail=""):
    with conn() as c:
        c.execute("INSERT INTO audit_log(time,action,detail) VALUES(?,?,?)",
                  (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), action, detail[:300]))
        c.commit()

def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS vehicles(
          id INTEGER PRIMARY KEY, plate TEXT UNIQUE, make TEXT, model TEXT, year INTEGER,
          color TEXT, fuel TEXT, owner TEXT, reg_status TEXT, insurer TEXT,
          insurance_expiry TEXT, puc_expiry TEXT, reg_expiry TEXT, notes TEXT);
        CREATE TABLE IF NOT EXISTS violations(
          id INTEGER PRIMARY KEY, vehicle_id INTEGER, kind TEXT, occurred TEXT, location TEXT,
          status TEXT DEFAULT 'Pending review', notes TEXT, source TEXT DEFAULT 'Demo record',
          FOREIGN KEY(vehicle_id) REFERENCES vehicles(id));
        CREATE TABLE IF NOT EXISTS accidents(
          id INTEGER PRIMARY KEY, vehicle_id INTEGER, occurred TEXT, location TEXT, severity TEXT,
          reference TEXT, notes TEXT, FOREIGN KEY(vehicle_id) REFERENCES vehicles(id));
        CREATE TABLE IF NOT EXISTS camera_reviews(
          id INTEGER PRIMARY KEY, filename TEXT, uploaded TEXT, objects TEXT,
          status TEXT DEFAULT 'Unverified - human review required', notes TEXT);
        CREATE TABLE IF NOT EXISTS audit_log(
          id INTEGER PRIMARY KEY, time TEXT, action TEXT, detail TEXT);
        """)
        # Backward-compatible vehicle intelligence fields (preserves existing records).
        existing = {row[1] for row in c.execute("PRAGMA table_info(vehicles)").fetchall()}
        additions = {
          "engine_cc": "INTEGER", "odometer_km": "INTEGER DEFAULT 0",
          "annual_km": "INTEGER DEFAULT 12000", "services_last_5y": "INTEGER DEFAULT 0",
          "engine_fault_codes": "INTEGER DEFAULT 0", "harsh_driving_events": "INTEGER DEFAULT 0",
          "last_service_date": "TEXT", "sample_record": "INTEGER DEFAULT 1"
        }
        for column, definition in additions.items():
            if column not in existing:
                c.execute(f"ALTER TABLE vehicles ADD COLUMN {column} {definition}")
        c.execute("""CREATE TABLE IF NOT EXISTS inspections(
          id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL, inspected_at TEXT NOT NULL,
          odometer_km INTEGER NOT NULL, services_last_5y INTEGER NOT NULL,
          engine_fault_codes INTEGER NOT NULL, harsh_driving_events INTEGER NOT NULL,
          annual_km INTEGER NOT NULL, maintenance_risk TEXT NOT NULL,
          remaining_engine_km INTEGER, estimated_years REAL, model_note TEXT,
          FOREIGN KEY(vehicle_id) REFERENCES vehicles(id))""")
        if c.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 0:
            d = date.today()
            samples = [
              ("MH02AB1234","Tata","Nexon",2022,"Blue","Petrol","Aarav Demo","Active","Demo Secure",(d+timedelta(days=120)).isoformat(),(d+timedelta(days=45)).isoformat(),(d+timedelta(days=300)).isoformat()),
              ("MH01CD5678","Hyundai","i20",2020,"White","Petrol","Priya Sample","Active","Example General",(d-timedelta(days=12)).isoformat(),(d+timedelta(days=30)).isoformat(),(d+timedelta(days=210)).isoformat()),
              ("MH03EF9012","Mahindra","XUV300",2023,"Grey","Diesel","Rohan Test","Active","Demo Secure",(d+timedelta(days=250)).isoformat(),(d-timedelta(days=3)).isoformat(),(d+timedelta(days=500)).isoformat()),
              ("MH04GH3456","Maruti Suzuki","Baleno",2019,"Red","CNG","Neha Example","Under review","Sample Mutual",(d+timedelta(days=15)).isoformat(),(d-timedelta(days=80)).isoformat(),(d+timedelta(days=60)).isoformat()),
              ("MH12JK7890","Honda","City",2021,"Black","Petrol","Demo Owner 05","Active","Example General",(d+timedelta(days=60)).isoformat(),(d+timedelta(days=10)).isoformat(),(d+timedelta(days=180)).isoformat())
            ]
            c.executemany("""INSERT INTO vehicles(plate,make,model,year,color,fuel,owner,reg_status,insurer,insurance_expiry,puc_expiry,reg_expiry)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", samples)
            ids = {r["plate"]:r["id"] for r in c.execute("SELECT id,plate FROM vehicles")}
            v = [
              (ids["MH02AB1234"],"Possible signal violation",(d-timedelta(days=9)).isoformat()+" 08:45","Demo Junction","Pending review","Fictional sample; verify evidence."),
              (ids["MH02AB1234"],"Seat-belt observation",(d-timedelta(days=4)).isoformat()+" 17:20","Demo Road","Reviewed - not confirmed","Fictional training example."),
              (ids["MH01CD5678"],"Parking violation",(d-timedelta(days=15)).isoformat()+" 12:10","Sample Market Street","Confirmed in demo","Fictional training example."),
              (ids["MH03EF9012"],"Possible speeding",(d-timedelta(days=2)).isoformat()+" 19:05","Demo Highway","Pending review","Speed needs calibrated measurement."),
              (ids["MH04GH3456"],"Possible tinted-window concern",(d-timedelta(days=35)).isoformat()+" 11:35","Example Checkpoint","Pending review","Visual observation is not legal proof.")
            ]
            c.executemany("INSERT INTO violations(vehicle_id,kind,occurred,location,status,notes) VALUES(?,?,?,?,?,?)", v)
            a = [
              (ids["MH02AB1234"],(d-timedelta(days=180)).isoformat(),"Demo Ring Road","Minor","DEMO-ACC-001","Fictional demo entry."),
              (ids["MH01CD5678"],(d-timedelta(days=410)).isoformat(),"Sample Avenue","Property damage only","DEMO-ACC-002","Fictional demo entry."),
              (ids["MH04GH3456"],(d-timedelta(days=60)).isoformat(),"Demo Service Road","Unknown","DEMO-ACC-003","Fictional demo entry.")
            ]
            c.executemany("INSERT INTO accidents(vehicle_id,occurred,location,severity,reference,notes) VALUES(?,?,?,?,?,?)", a)
        # Populate sensible fictional baseline readings for demo vehicles only when blank.
        demo_readings = [(1199,42000,12000,4,0,1),(1197,68000,14000,3,1,2),(1497,31000,15000,4,0,0),(1197,89000,11000,2,2,3),(1497,54000,10000,4,0,1)]
        for row, values in zip(c.execute("SELECT id FROM vehicles ORDER BY id").fetchall(), demo_readings):
            c.execute("UPDATE vehicles SET engine_cc=COALESCE(engine_cc,?), odometer_km=CASE WHEN odometer_km IS NULL OR odometer_km=0 THEN ? ELSE odometer_km END, annual_km=COALESCE(annual_km,?), services_last_5y=COALESCE(services_last_5y,?), engine_fault_codes=COALESCE(engine_fault_codes,?), harsh_driving_events=COALESCE(harsh_driving_events,?) WHERE id=?", (*values,row[0]))
        c.commit()

def expiry(value):
    if not value: return "Unknown"
    try:
        days = (date.fromisoformat(value)-date.today()).days
        return "Expired" if days < 0 else ("Expiring soon" if days <= 30 else "Valid")
    except ValueError: return "Unknown"

@app.context_processor
def globals_for_templates():
    return {"expiry": expiry}

@app.route("/")
def dashboard():
    with conn() as c:
        total=c.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
        inspection_count=c.execute("SELECT COUNT(*) FROM inspections").fetchone()[0]
        high_risk=c.execute("SELECT COUNT(*) FROM inspections WHERE maintenance_risk='High'").fetchone()[0]
        uninspected=c.execute("SELECT COUNT(*) FROM vehicles v WHERE NOT EXISTS (SELECT 1 FROM inspections i WHERE i.vehicle_id=v.id)").fetchone()[0]
        recent_inspections=c.execute("SELECT i.*,v.plate,v.make,v.model FROM inspections i JOIN vehicles v ON v.id=i.vehicle_id ORDER BY i.id DESC LIMIT 8").fetchall()
        risks=c.execute("SELECT maintenance_risk label,COUNT(*) n FROM inspections GROUP BY maintenance_risk").fetchall()
    return render_template("dashboard.html",total=total,inspection_count=inspection_count,high_risk=high_risk,uninspected=uninspected,recent_inspections=recent_inspections,chart=json.dumps({"types":[dict(x) for x in risks]}))

@app.route("/vehicles")
def vehicles():
    q=request.args.get("q","").strip().upper()
    with conn() as c:
        rows=c.execute("SELECT * FROM vehicles WHERE UPPER(plate) LIKE ? OR UPPER(make) LIKE ? OR UPPER(model) LIKE ? ORDER BY plate",
          (f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    return render_template("vehicles.html",vehicles=rows,q=q)

@app.route("/vehicles/<int:vid>")
def vehicle(vid):
    with conn() as c:
        v=c.execute("SELECT * FROM vehicles WHERE id=?",(vid,)).fetchone()
        if not v: abort(404)
        violations=c.execute("SELECT * FROM violations WHERE vehicle_id=? ORDER BY occurred DESC",(vid,)).fetchall()
        accidents=c.execute("SELECT * FROM accidents WHERE vehicle_id=? ORDER BY occurred DESC",(vid,)).fetchall()
    return render_template("vehicle.html",v=v,violations=violations,accidents=accidents)

@app.route("/violations",methods=["GET","POST"])
def violations():
    if request.method=="POST":
        vid=request.form.get("vehicle_id","")
        kind=request.form.get("kind","").strip()
        if not vid or not kind:
            flash("Choose a vehicle and observation type.","error")
            return redirect(url_for("violations"))
        with conn() as c:
            c.execute("INSERT INTO violations(vehicle_id,kind,occurred,location,status,notes,source) VALUES(?,?,?,?,?,?,?)",
              (vid,kind,request.form.get("occurred") or datetime.now().strftime("%Y-%m-%d %H:%M"),
               request.form.get("location","").strip(),"Pending review",request.form.get("notes","").strip(),"Manually entered demo record"))
            c.commit()
        log("Observation added",f"vehicle_id={vid}; type={kind}")
        flash("Observation saved as Pending review.","success")
        return redirect(url_for("violations"))
    status=request.args.get("status","")
    with conn() as c:
        sql="""SELECT x.*,v.plate,v.make,v.model FROM violations x JOIN vehicles v ON v.id=x.vehicle_id"""
        rows=c.execute(sql+(" WHERE x.status=?" if status else "")+" ORDER BY x.occurred DESC",((status,) if status else ())).fetchall()
        cars=c.execute("SELECT id,plate,make,model FROM vehicles ORDER BY plate").fetchall()
    return render_template("violations.html",rows=rows,cars=cars,status=status)

@app.route("/violations/<int:xid>/status",methods=["POST"])
def status_update(xid):
    status=request.form.get("status","")
    if status not in {"Pending review","Reviewed - not confirmed","Confirmed in demo","Dismissed"}:
        flash("Invalid review status.","error")
        return redirect(url_for("violations"))
    with conn() as c:
        c.execute("UPDATE violations SET status=? WHERE id=?",(status,xid)); c.commit()
    log("Review status updated",f"violation_id={xid}; status={status}")
    flash("Review status updated.","success")
    return redirect(url_for("violations"))

@app.route("/camera",methods=["GET","POST"])
def camera():
    result=None
    if request.method=="POST":
        f=request.files.get("evidence")
        if not f or not f.filename:
            flash("Choose an image first.","error")
        elif "." not in f.filename or f.filename.rsplit(".",1)[1].lower() not in ALLOWED:
            flash("Allowed image formats: PNG, JPG, JPEG, WEBP.","error")
        else:
            filename=datetime.now().strftime("%Y%m%d_%H%M%S_%f")+"_"+secure_filename(f.filename)
            path=UPLOADS/filename; f.save(path)
            # This project uses Random Forest on structured vehicle records, not image detection.
            # Camera uploads are stored as evidence for human review; no ML image claims are made.
            objects=[]
            message="Image saved for human review. This version does not run an image-detection model and does not automatically determine an offence."
            with conn() as c:
                cur=c.execute("INSERT INTO camera_reviews(filename,uploaded,objects,status,notes) VALUES(?,?,?,?,?)",
                    (filename,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),json.dumps(objects),"Unverified - human review required",request.form.get("notes","").strip() or message))
                rid=cur.lastrowid;c.commit()
            log("Camera image uploaded",f"review_id={rid}; filename={filename}")
            result={"id":rid,"filename":filename,"objects":objects,"message":message}
            flash("Evidence uploaded. Human review is required.","success")
    with conn() as c: reviews=c.execute("SELECT * FROM camera_reviews ORDER BY id DESC LIMIT 10").fetchall()
    return render_template("camera.html",reviews=reviews,result=result,json_loads=json.loads)

@app.route("/uploads/<path:filename>")
def upload_file(filename):
    path=(UPLOADS/filename).resolve()
    if UPLOADS.resolve() not in path.parents or not path.is_file(): abort(404)
    return send_file(path)

@app.route("/analytics")
def analytics():
    with conn() as c:
        kinds=c.execute("SELECT kind label,COUNT(*) n FROM violations GROUP BY kind").fetchall()
        months=c.execute("SELECT substr(occurred,1,7) label,COUNT(*) n FROM violations GROUP BY label ORDER BY label").fetchall()
        statuses=c.execute("SELECT status label,COUNT(*) n FROM violations GROUP BY status").fetchall()
        makes=c.execute("SELECT make label,COUNT(*) n FROM vehicles GROUP BY make").fetchall()
        cars=c.execute("SELECT * FROM vehicles").fetchall()
    watch=[v for v in cars if expiry(v["insurance_expiry"]) in ("Expired","Expiring soon") or expiry(v["puc_expiry"]) in ("Expired","Expiring soon")]
    data={k:[dict(x) for x in rows] for k,rows in [("kinds",kinds),("months",months),("statuses",statuses),("makes",makes)]}
    return render_template("analytics.html",data=json.dumps(data),watch=watch)

@app.route("/ml-insights")
def ml_insights():
    """Train a Random Forest on the labelled CSV and classify current vehicle records."""
    try:
        result = train_model()
        features = result["features"]
        today = date.today()
        predictions = []
        with conn() as c:
            cars = c.execute("SELECT * FROM vehicles ORDER BY plate").fetchall()
            for car in cars:
                violation_count = c.execute(
                    "SELECT COUNT(*) FROM violations WHERE vehicle_id=? AND date(occurred) >= date(?)",
                    (car["id"], (today-timedelta(days=90)).isoformat())
                ).fetchone()[0]
                pending_count = c.execute(
                    "SELECT COUNT(*) FROM violations WHERE vehicle_id=? AND status='Pending review'",
                    (car["id"],)
                ).fetchone()[0]
                accident_count = c.execute(
                    "SELECT COUNT(*) FROM accidents WHERE vehicle_id=? AND date(occurred) >= date(?)",
                    (car["id"], (today-timedelta(days=365)).isoformat())
                ).fetchone()[0]
                try:
                    vehicle_age = max(0, today.year - int(car["year"])) if car["year"] else 0
                except (TypeError, ValueError):
                    vehicle_age = 0
                def expired_flag(value):
                    try: return int(bool(value) and date.fromisoformat(value) < today)
                    except (TypeError, ValueError): return 0
                row = {
                    "vehicle_age": vehicle_age,
                    "violations_90d": violation_count,
                    "accidents_365d": accident_count,
                    "pending_reviews": pending_count,
                    "insurance_expired": expired_flag(car["insurance_expiry"]),
                    "puc_expired": expired_flag(car["puc_expiry"]),
                    "registration_expired": expired_flag(car["reg_expiry"]),
                }
                prediction = str(result["model"].predict([[row[name] for name in features]])[0])
                probabilities = result["model"].predict_proba([[row[name] for name in features]])[0]
                confidence = float(max(probabilities))
                predictions.append({"plate":car["plate"],"make":car["make"],"model":car["model"],
                    "pattern":prediction,"confidence":confidence,"features":row})
        predictions.sort(key=lambda x: ["Priority Review","Monitor","Routine"].index(x["pattern"]) if x["pattern"] in {"Priority Review","Monitor","Routine"} else 9)
        return render_template("ml_insights.html", result=result, predictions=predictions,
            synthetic_data=True, labels=sorted(result["class_counts"].keys()))
    except (FileNotFoundError, ValueError, ImportError) as exc:
        return render_template("ml_insights.html", error=str(exc), result=None, predictions=[], synthetic_data=True)

@app.route("/data-quality")
def data_quality():
    issues=[]
    with conn() as c:
        cars=c.execute("SELECT * FROM vehicles").fetchall()
        violations=c.execute("SELECT * FROM violations").fetchall()
        reviews=c.execute("SELECT COUNT(*) FROM camera_reviews").fetchone()[0]
        logs=c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 30").fetchall()
    for v in cars:
        for field in ("owner","insurance_expiry","puc_expiry","reg_expiry"):
            if not v[field]: issues.append((v["plate"],field,"Missing value"))
    for x in violations:
        if not x["location"]: issues.append((f"Violation #{x['id']}","location","Missing location"))
        if x["status"]=="Pending review": issues.append((f"Violation #{x['id']}","status","Human review pending"))
    return render_template("quality.html",issues=issues,cars=len(cars),vcount=len(violations),reviews=reviews,logs=logs)

@app.route("/reports")
def reports():
    with conn() as c:
        totals=[c.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0],
          c.execute("SELECT COUNT(*) FROM violations").fetchone()[0],
          c.execute("SELECT COUNT(*) FROM accidents").fetchone()[0],
          c.execute("SELECT COUNT(*) FROM violations WHERE status='Pending review'").fetchone()[0]]
    return render_template("reports.html",totals=totals)

@app.route("/reports/violations.csv")
def csv_report():
    with conn() as c:
        rows=c.execute("""SELECT v.plate,v.make,v.model,x.kind,x.occurred,x.location,x.status,x.source,x.notes
          FROM violations x JOIN vehicles v ON v.id=x.vehicle_id ORDER BY x.occurred DESC""").fetchall()
    buf=io.StringIO(); w=csv.writer(buf); w.writerow(["Registration","Make","Model","Observation","Date/time","Location","Status","Source","Notes"])
    for r in rows: w.writerow(list(r))
    mem=io.BytesIO(buf.getvalue().encode("utf-8-sig"));mem.seek(0);log("CSV exported",f"{len(rows)} records")
    return send_file(mem,mimetype="text/csv",as_attachment=True,download_name="autoshield_violations.csv")

@app.route("/reports/summary.pdf")
def pdf_report():
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError:
        flash("Install PDF dependency: python -m pip install reportlab","error")
        return redirect(url_for("reports"))
    with conn() as c:
        totals=[("Vehicles",c.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]),
          ("Violation records",c.execute("SELECT COUNT(*) FROM violations").fetchone()[0]),
          ("Pending review",c.execute("SELECT COUNT(*) FROM violations WHERE status='Pending review'").fetchone()[0]),
          ("Accident records",c.execute("SELECT COUNT(*) FROM accidents").fetchone()[0])]
        rows=c.execute("""SELECT v.plate,x.kind,x.occurred,x.status FROM violations x JOIN vehicles v ON v.id=x.vehicle_id ORDER BY x.occurred DESC LIMIT 25""").fetchall()
    b=io.BytesIO();doc=SimpleDocTemplate(b,pagesize=A4,title="AutoShield AI demo report");s=getSampleStyleSheet()
    story=[Paragraph("AutoShield AI — Demo Summary",s["Title"]),Paragraph("Fictional demonstration data only. Not an official record.",s["BodyText"]),Spacer(1,14),
      Table([["Metric","Count"]]+[[k,str(v)] for k,v in totals]),Spacer(1,14),Paragraph("Recent observations",s["Heading2"])]
    t=Table([["Registration","Observation","Date/time","Status"]]+[[r["plate"],r["kind"],r["occurred"],r["status"]] for r in rows],repeatRows=1,colWidths=[85,155,105,105])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#10233f")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.4,colors.grey),("FONTSIZE",(0,0),(-1,-1),7)]));story.append(t);doc.build(story);b.seek(0);log("PDF exported","summary report")
    return send_file(b,mimetype="application/pdf",as_attachment=True,download_name="autoshield_summary.pdf")


@app.route("/engine-forecast", methods=["GET", "POST"])
def engine_forecast():
    from engine_ml import train_models
    clf, reg, metrics = train_models()
    result = None
    plate = ""
    if request.method == "POST":
        plate = request.form.get("plate", "").strip().upper()
        try:
            with conn() as c:
                car = c.execute("SELECT * FROM vehicles WHERE UPPER(plate)=?", (plate,)).fetchone()
            if not car:
                flash("Registration not found in the local demo database. Try MH02AB1234, MH01CD5678 or MH04GH3456.", "error")
            else:
                age = max(0, date.today().year - int(car["year"] or date.today().year))
                km = max(0, int(request.form.get("odometer_km", "85000")))
                services = max(0, min(50, int(request.form.get("services_last_5y", "5"))))
                faults = max(0, min(30, int(request.form.get("engine_fault_codes", "0"))))
                harsh = max(0, min(30, int(request.form.get("harsh_driving_events", "1"))))
                import pandas as pd
                features = pd.DataFrame([[age, km, services, faults, harsh]], columns=["vehicle_age_years","odometer_km","services_last_5y","engine_fault_codes","harsh_driving_events"])
                risk = str(clf.predict(features)[0])
                remaining = max(0, int(reg.predict(features)[0]))
                annual = max(1, int(request.form.get("annual_km", "12000")))
                result = {"car":car,"age":age,"km":km,"risk":risk,"remaining":remaining,"years":round(remaining/annual,1),"services":services,"faults":faults,"harsh":harsh}
        except (ValueError, TypeError):
            flash("Enter valid non-negative numbers in the vehicle usage fields.", "error")
    with conn() as c:
        cars = c.execute("SELECT plate,make,model,year,color,fuel FROM vehicles ORDER BY plate").fetchall()
    return render_template("engine_forecast.html", cars=cars, result=result, metrics=metrics, plate=plate)

@app.route("/vehicles/add", methods=["GET", "POST"])
def add_vehicle():
    if request.method == "POST":
        plate=request.form.get("plate","").strip().upper()
        required=[plate,request.form.get("make",""),request.form.get("model",""),request.form.get("year","")]
        if not all(required):
            flash("Registration, make, model and year are required.","error")
            return redirect(url_for("add_vehicle"))
        try:
            with conn() as c:
                c.execute("""INSERT INTO vehicles(plate,make,model,year,color,fuel,owner,reg_status,notes,engine_cc,odometer_km,annual_km,services_last_5y,engine_fault_codes,harsh_driving_events,sample_record)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",(plate,request.form["make"].strip(),request.form["model"].strip(),int(request.form["year"]),request.form.get("color",""),request.form.get("fuel","Petrol"),request.form.get("owner","User added"),"Active",request.form.get("notes",""),int(request.form.get("engine_cc") or 0),int(request.form.get("odometer_km") or 0),int(request.form.get("annual_km") or 12000),int(request.form.get("services_last_5y") or 0),int(request.form.get("engine_fault_codes") or 0),int(request.form.get("harsh_driving_events") or 0)))
                c.commit()
            log("Vehicle added",plate); flash("Vehicle added to your registry.","success")
            return redirect(url_for("vehicles"))
        except sqlite3.IntegrityError:
            flash("That registration number already exists.","error")
        except ValueError:
            flash("Enter valid numeric vehicle details.","error")
    return render_template("vehicle_add.html")

@app.route("/inspections", methods=["GET", "POST"])
def inspections():
    result=None
    with conn() as c:
        cars=c.execute("SELECT id,plate,make,model,year,odometer_km,annual_km,services_last_5y,engine_fault_codes,harsh_driving_events FROM vehicles ORDER BY plate").fetchall()
    if request.method == "POST":
        try:
            vid=int(request.form["vehicle_id"])
            km=int(request.form["odometer_km"]); services=int(request.form["services_last_5y"])
            faults=int(request.form["engine_fault_codes"]); harsh=int(request.form["harsh_driving_events"]); annual=max(1,int(request.form["annual_km"]))
            if min(km,services,faults,harsh)<0 or services>50 or faults>30 or harsh>30: raise ValueError
            with conn() as c:
                car=c.execute("SELECT * FROM vehicles WHERE id=?",(vid,)).fetchone()
                if not car: abort(404)
                age=max(0,date.today().year-int(car["year"] or date.today().year))
                import pandas as pd
                from engine_ml import train_models
                clf,reg,metrics=train_models()
                frame=pd.DataFrame([[age,km,services,faults,harsh]],columns=["vehicle_age_years","odometer_km","services_last_5y","engine_fault_codes","harsh_driving_events"])
                risk=str(clf.predict(frame)[0]); remaining=max(0,int(reg.predict(frame)[0])); years=round(remaining/annual,1)
                c.execute("UPDATE vehicles SET odometer_km=?,annual_km=?,services_last_5y=?,engine_fault_codes=?,harsh_driving_events=? WHERE id=?",(km,annual,services,faults,harsh,vid))
                c.execute("INSERT INTO inspections(vehicle_id,inspected_at,odometer_km,services_last_5y,engine_fault_codes,harsh_driving_events,annual_km,maintenance_risk,remaining_engine_km,estimated_years,model_note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(vid,datetime.now().strftime("%Y-%m-%d %H:%M"),km,services,faults,harsh,annual,risk,remaining,years,"Experimental model trained on synthetic demonstration data."))
                c.commit()
                result={"car":dict(car),"risk":risk,"remaining":remaining,"years":years,"metrics":metrics}
            log("Inspection completed",f"vehicle_id={vid}; risk={risk}")
        except (ValueError,KeyError,TypeError):
            flash("Please enter valid non-negative inspection readings.","error")
    with conn() as c:
        history=c.execute("SELECT i.*,v.plate,v.make,v.model FROM inspections i JOIN vehicles v ON v.id=i.vehicle_id ORDER BY i.id DESC LIMIT 30").fetchall()
    return render_template("inspections.html",cars=cars,result=result,history=history)

@app.route("/inspections/<int:iid>")
def inspection_detail(iid):
    with conn() as c:
        row=c.execute("SELECT i.*,v.plate,v.make,v.model,v.year FROM inspections i JOIN vehicles v ON v.id=i.vehicle_id WHERE i.id=?",(iid,)).fetchone()
    if not row: abort(404)
    return render_template("inspection_detail.html",item=row)

@app.route("/engine-analytics")
def engine_analytics():
    with conn() as c:
        risks=c.execute("SELECT maintenance_risk label,COUNT(*) n FROM inspections GROUP BY maintenance_risk").fetchall()
        mileage=c.execute("SELECT v.plate,AVG(i.odometer_km) km,COUNT(i.id) checks FROM vehicles v JOIN inspections i ON i.vehicle_id=v.id GROUP BY v.id ORDER BY km").fetchall()
        trend=c.execute("SELECT substr(inspected_at,1,10) day,COUNT(*) n FROM inspections GROUP BY day ORDER BY day").fetchall()
        total=c.execute("SELECT COUNT(*) FROM inspections").fetchone()[0]
    return render_template("engine_analytics.html",risks=json.dumps([dict(x) for x in risks]),mileage=json.dumps([dict(x) for x in mileage]),trend=json.dumps([dict(x) for x in trend]),total=total)

@app.route("/health")
def health(): return {"status":"ok","database":"autoshield.db","records":"fictional demo"}

@app.errorhandler(413)
def too_large(e):
    flash("File too large. Maximum upload is 12 MB.","error");return redirect(url_for("camera"))

@app.errorhandler(404)
def missing(e): return render_template("404.html"),404

init_db()
if __name__=="__main__":
    app.run(debug=True)
