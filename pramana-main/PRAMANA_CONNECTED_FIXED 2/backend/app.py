from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3, json, os, hashlib, datetime, time
BASE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE)
UPLOAD_DIR = os.path.join(BASE, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

DB_PATH = os.path.join(BASE, 'pramana.db')
FRONTEND = os.path.join(PROJECT_ROOT, 'frontend')
app=Flask(__name__, static_folder=FRONTEND, static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25MB (inspection photo uploads)

CORS(app, supports_credentials=True)

def conn():
    c=sqlite3.connect(DB_PATH)
    c.row_factory=sqlite3.Row
    return c

# ------------------------------------------------------------------
# Structured reason catalogs (stored as codes, displayed with labels)
# ------------------------------------------------------------------
FAILURE_REASONS = {
    "third_party_issue": "Third-party / unapproved component detected",
    "tampered_seal": "Tampered or broken lead seal",
    "mpe_exceeded": "Measurement error exceeds MPE tolerance",
    "overdue_verification": "Verification overdue",
    "model_approval_invalid": "Model approval invalid / missing",
    "documentation_invalid": "Invalid or incomplete documentation",
    "other": "Other verification failure"
}
GATC_REJECTION_REASONS = {
    "not_authorized": "Instrument category not authorized for this GATC",
    "capacity_full": "Testing capacity currently full",
    "invalid_details": "Application or instrument details invalid / incomplete",
    "out_of_service_area": "Instrument out of the GATC service area",
    "duplicate_request": "Duplicate request already exists",
    "other": "Other reason"
}
AUTHORIZATION_REASONS = {
    "outside_district": "Case is located outside my jurisdiction / district",
    "equipment_unavailable": "Required test equipment not available in my district",
    "workload_escalation": "Escalation requested due to workload",
    "other": "Other reason"
}
REVOKE_REASONS = {
    "surrendered": "Certificate surrendered by owner / trader",
    "instrument_retired": "Instrument retired from trade",
    "incorrect_issuance": "Certificate issued in error",
    "tampering_found": "Tampering detected after issuance",
    "other": "Other reason"
}

GATC_CENTRES = [
    { "id": 21, "code": "GATC-021", "name": "ABC Legal Metrology Verification Centre", "organization": "ABC Compliance Services Pvt. Ltd.", "location": "Lucknow, Uttar Pradesh", "district": "Lucknow", "state": "Uttar Pradesh", "contact": "+91-98765-21021", "status": "active", "approval_date": "2026-01-15", "valid_until": "2027-12-31", "authorized": ["CNG Dispenser", "LPG Dispenser", "Petrol/Diesel Dispenser", "Platform Scale", "Weighbridge"], "equipment": ["Master Prover", "Standard Test Weights", "Flow Test Rig"], "workload": "Low", "availability": "Available", "capacity": 40, "completed": 124, "failed": 5, "avg_days": 2.1, "staff": 8 },
    { "id": 34, "code": "GATC-034", "name": "North UP Verification Lab", "organization": "North UP Testing Services", "location": "Lucknow, Uttar Pradesh", "district": "Lucknow", "state": "Uttar Pradesh", "contact": "+91-98765-34034", "status": "active", "approval_date": "2025-09-01", "valid_until": "2027-08-31", "authorized": ["CNG Dispenser", "LPG Dispenser", "Platform Scale"], "equipment": ["Standard Test Weights", "Electrical Test Bench"], "workload": "High", "availability": "Limited", "capacity": 30, "completed": 98, "failed": 8, "avg_days": 3.4, "staff": 6 },
    { "id": 41, "code": "GATC-041", "name": "Central Instrument Test Centre", "organization": "Central Metrology Services", "location": "Kanpur Nagar, Uttar Pradesh", "district": "Kanpur Nagar", "state": "Uttar Pradesh", "contact": "+91-98765-41041", "status": "active", "approval_date": "2026-02-10", "valid_until": "2028-02-09", "authorized": ["CNG Dispenser", "Petrol/Diesel Dispenser", "Weighbridge"], "equipment": ["Flow Test Rig", "Master Prover", "Calibrated Weights"], "workload": "Medium", "availability": "Available", "capacity": 35, "completed": 76, "failed": 2, "avg_days": 1.8, "staff": 7 }
]

def init_db():
    c=conn(); cur=c.cursor()
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, role TEXT, org TEXT, district TEXT, lmo_code TEXT, password TEXT);
    CREATE TABLE IF NOT EXISTS instruments(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS applications(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS complaints(id TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS certificates(id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, instrument_id INTEGER, transaction_id TEXT UNIQUE, amount REAL, status TEXT, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS gatcs(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS gatc_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS inspections(id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS authorizations(id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
    ''')
    users=[
      (1,'Rajesh Sharma','trader@pramana.in','user','Sharma Stores','Lucknow',None,'password123'),
      (2,'Rahul Sharma','officer@pramana.in','officer','District Inspectorate','Lucknow','LMO-LKO-01','password123'),
      (3,'Priya Verma','officer2@pramana.in','officer','District Inspectorate','Lucknow','LMO-LKO-02','password123'),
      (21,'GATC Operator','gatc@pramana.in','gatc','ABC Legal Metrology Verification Centre','Lucknow','GATC-021','password123'),
      (99,'Director General','admin@pramana.in','admin','Legal Metrology Dept, UP','Lucknow','LMO-HQ-00','password123')]
    for u in users: cur.execute('INSERT OR IGNORE INTO users VALUES (?,?,?,?,?,?,?,?)',u)
    if cur.execute('SELECT COUNT(*) FROM instruments').fetchone()[0]==0:
      instruments=json.load(open(os.path.join(os.path.dirname(BASE),'db_seed.json')))['instruments']
      for x in instruments: cur.execute('INSERT INTO instruments(id,data) VALUES (?,?)',(x['id'],json.dumps(x)))
    seed=json.load(open(os.path.join(os.path.dirname(BASE),'db_seed.json')))
    if cur.execute('SELECT COUNT(*) FROM applications').fetchone()[0]==0:
      # enrich demo applications with workflow/ownership so officer + admin queues work out of the box
      app_enrichment={101:{'workflow':'verification','owner_id':1,'officer_id':2,'assignment_status':'assigned','assigned_officer':'Rahul Sharma (LMO-LKO-01)'},
                      102:{'workflow':'verification','owner_id':1,'officer_id':3,'assignment_status':'assigned','assigned_officer':'Priya Verma (LMO-LKO-02)'},
                      103:{'workflow':'verification','owner_id':None,'officer_id':None,'assignment_status':'unassigned','assigned_officer':'Unassigned'}}
      for x in seed['applications']:
        x.update(app_enrichment.get(x['id'],{'workflow':'verification'}))
        cur.execute('INSERT INTO applications(id,data) VALUES (?,?)',(x['id'],json.dumps(x)))
    if cur.execute('SELECT COUNT(*) FROM complaints').fetchone()[0]==0:
      for x in seed['complaints']: cur.execute('INSERT INTO complaints(id,data) VALUES (?,?)',(x['id'],json.dumps(x)))
    if cur.execute('SELECT COUNT(*) FROM certificates').fetchone()[0]==0:
      for x in seed['certificates']: cur.execute('INSERT INTO certificates(data) VALUES (?)',(json.dumps(x),))
    if cur.execute('SELECT COUNT(*) FROM audit').fetchone()[0]==0:
      for x in seed['audit']: cur.execute('INSERT INTO audit(data) VALUES (?)',(json.dumps(x),))
    if cur.execute('SELECT COUNT(*) FROM notifications').fetchone()[0]==0:
      for x in seed['notifications']: cur.execute('INSERT OR REPLACE INTO notifications(id,data) VALUES (?,?)',(int(x.get('id',0)),json.dumps(x)))
    if cur.execute('SELECT COUNT(*) FROM gatcs').fetchone()[0]==0:
      for g in GATC_CENTRES: cur.execute('INSERT OR REPLACE INTO gatcs(id,data) VALUES (?,?)',(g['id'],json.dumps(g)))
    if cur.execute('SELECT COUNT(*) FROM gatc_requests').fetchone()[0]==0:
      today=datetime.date.today().isoformat()
      demo=[
        {"id":1,"code":"GATC-REQ-1001","officer_id":2,"officer_name":"Rahul Sharma","officer_code":"LMO-LKO-01","gatc_id":21,"gatc_code":"GATC-021","application_id":102,"public_id":"APP-2026-904","instrument_id":2,"serial":"LM-UP-000431","instrument_name":"Bharat Fuels Dispenser #3","subject":"GATC testing request","message":"Requesting bench test for fuel dispenser #3 after re-sealing.","status":"approved","reason_code":None,"reason_note":"","created_on":today,"decided_on":today,"decided_by":"GATC-021"},
        {"id":2,"code":"GATC-REQ-1002","officer_id":2,"officer_name":"Rahul Sharma","officer_code":"LMO-LKO-01","gatc_id":34,"gatc_code":"GATC-034","application_id":103,"public_id":"APP-2026-920","instrument_id":3,"serial":"LM-UP-000821","instrument_name":"Kanpur Central Weighbridge","subject":"GATC testing request","message":"Weighbridge first verification - requesting test slot.","status":"pending","reason_code":None,"reason_note":"","created_on":today,"decided_on":None,"decided_by":None}
      ]
      for r in demo: cur.execute('INSERT INTO gatc_requests(id,data) VALUES (?,?)',(r['id'],json.dumps(r)))
    if cur.execute('SELECT COUNT(*) FROM inspections').fetchone()[0]==0:
      today=datetime.date.today().isoformat()
      demo_insp={"id":1,"code":"INS-9001","application_id":101,"instrument_id":1,"serial":"LM-UP-000127","instrument_name":"Sharma Kirana Platform Scale","district":"Lucknow","officer_id":2,"officer_name":"Rahul Sharma","officer_code":"LMO-LKO-01","inspected_on":today+" 10:30","measurements":[{"load_kg":0,"indicated_kg":0.0,"error_kg":0.0},{"load_kg":50,"indicated_kg":50.02,"error_kg":0.02},{"load_kg":150,"indicated_kg":150.05,"error_kg":0.05},{"load_kg":300,"indicated_kg":300.1,"error_kg":0.1}],"seal_condition":"intact","verdict":"pass","failure_reason_code":None,"failure_reason_label":None,"failure_note":"","notes":"Within MPE at all test loads.","photos":[],"gps":{"lat":26.8467,"lng":80.9462,"accuracy":None,"captured_at":today+" 10:28"},"status":"completed"}
      cur.execute('INSERT INTO inspections(id,data) VALUES (?,?)',(demo_insp['id'],json.dumps(demo_insp)))
    c.commit(); c.close()

SESSIONS={}
def current_user():
    token=request.headers.get('X-Session-Token') or request.cookies.get('pramana_session')
    return SESSIONS.get(token)

def require_role(*roles):
    """Returns (user, error_response). error_response is None when authorized."""
    u=current_user()
    if not u:
        return None, (jsonify({'error':'Authentication required'}), 401)
    if roles and u.get('role') not in roles:
        return None, (jsonify({'error':'Your role is not permitted to perform this action'}), 403)
    return u, None

def rows(table):
    c=conn(); out=[json.loads(r['data']) for r in c.execute(f'SELECT data FROM {table}').fetchall()]; c.close(); return out

def save_json(table, keycol, key, data):
    c=conn(); c.execute(f'INSERT OR REPLACE INTO {table}({keycol},data) VALUES (?,?)',(key,json.dumps(data))); c.commit(); c.close()

def audit_log(actor, action, entity, entity_id, detail=''):
    try:
        c=conn()
        ev={"ts":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "actor_name":(actor or {}).get('name','System'),"actor_role":(actor or {}).get('role','system'),
            "action":action,"entity":entity,"entity_id":str(entity_id),
            "detail":detail,"chain_hash":hashlib.sha256(f"{action}:{entity_id}:{time.time()}".encode()).hexdigest()[:20]}
        c.execute('INSERT INTO audit(data) VALUES (?)',(json.dumps(ev),)); c.commit(); c.close()
    except Exception:
        pass

def next_code(prefix, table, start):
    c=conn()
    n=c.execute(f'SELECT COALESCE(MAX(id),{start-1})+1 FROM {table}').fetchone()[0]
    c.close()
    return f"{prefix}-{n}", n

@app.get('/')
def index(): return send_from_directory(FRONTEND,'index.html')

@app.get('/uploads/<path:p>')
def uploads(p): return send_from_directory(UPLOAD_DIR,p)

@app.get('/api/bootstrap')
def bootstrap():
    return jsonify({'instruments':rows('instruments'),'applications':rows('applications'),'complaints':rows('complaints'),'certificates':rows('certificates'),'audit':rows('audit'),'notifications':rows('notifications'),'gatcs':rows('gatcs'),'gatc_requests':rows('gatc_requests'),'inspections':rows('inspections'),'authorizations':rows('authorizations')})

@app.get('/api/meta')
def meta():
    return jsonify({'failure_reasons':FAILURE_REASONS,'gatc_rejection_reasons':GATC_REJECTION_REASONS,'authorization_reasons':AUTHORIZATION_REASONS,'revoke_reasons':REVOKE_REASONS})

@app.post('/api/login')
def login():
    b = request.get_json(silent=True) or {}

    email = b.get('email', '').strip().lower()
    password = b.get('password', '')
    role = b.get('role', 'user').strip().lower()

    # Frontend "trader" role ko database ke "user" role se map karo
    if role == 'trader':
        role = 'user'

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    c = conn()

    r = c.execute(
        'SELECT * FROM users WHERE LOWER(email)=? AND role=?',
        (email, role)
    ).fetchone()

    c.close()

    # User nahi mila
    if not r:
        return jsonify({'error': 'Invalid credentials or role'}), 401

    # Password verify
    if r['password'] != password:
        return jsonify({'error': 'Invalid credentials or role'}), 401

    # User information
    user = dict(r)

    # Password frontend ko kabhi return nahi karna
    user.pop('password', None)

    # Session token
    token = hashlib.sha256(
        f"{email}:{role}:{datetime.datetime.now().timestamp()}".encode()
    ).hexdigest()

    SESSIONS[token] = user

    # Response
    resp = jsonify({
        'user': user
    })

    resp.set_cookie(
        'pramana_session',
        token,
        httponly=True,
        samesite='Lax'
    )

    return resp

@app.post('/api/logout')
def logout():
    SESSIONS.pop(request.headers.get('X-Session-Token') or request.cookies.get('pramana_session'),None); resp=jsonify({'ok':True}); resp.delete_cookie('pramana_session'); return resp

@app.get('/api/me')
def me():
    u=current_user()
    if not u: return jsonify({'error':'Authentication required'}),401
    return jsonify({'user':u})

@app.get('/api/instruments')
def instruments(): return jsonify({'instruments':rows('instruments')})

@app.put('/api/instruments/<int:iid>')
def update_instrument(iid):
    u=current_user()
    if not u: return jsonify({'error':'Authentication required'}),401
    data=request.get_json(silent=True) or {}; data['id']=iid
    c=conn(); r=c.execute('SELECT id FROM instruments WHERE id=?',(iid,)).fetchone()
    if not r: c.close(); return jsonify({'error':'Instrument not found'}),404
    c.execute('UPDATE instruments SET data=? WHERE id=?',(json.dumps(data),iid)); c.commit(); c.close()
    return jsonify({'ok':True,'instrument':data})

@app.get('/api/instruments/<int:iid>')
def instrument(iid):
    c=conn(); r=c.execute('SELECT data FROM instruments WHERE id=?',(iid,)).fetchone(); c.close()
    if not r: return jsonify({'error':'Instrument not found'}),404
    x=json.loads(r['data']); x['certificate']=next((c for c in rows('certificates') if c.get('instrument_id')==iid),None); return jsonify(x)

@app.post('/api/instruments')
def create_instrument():
    u, err = require_role('user','officer','admin')
    if err: return err
    data=request.get_json(silent=True) or {}; c=conn(); nid=(c.execute('SELECT COALESCE(MAX(id),0)+1 FROM instruments').fetchone()[0]); data['id']=nid; c.execute('INSERT INTO instruments(id,data) VALUES (?,?)',(nid,json.dumps(data))); c.commit(); c.close(); return jsonify({'ok':True,'instrument':data}),201

@app.get('/api/applications')
def applications(): return jsonify({'applications':rows('applications')})

@app.get('/api/applications/<int:aid>')
def application_detail(aid):
    c=conn(); r=c.execute('SELECT data FROM applications WHERE id=?',(aid,)).fetchone(); c.close()
    if not r: return jsonify({'error':'Application not found'}),404
    return jsonify(json.loads(r['data']))

@app.post('/api/verification/apply')
def apply_verification():
    u, err = require_role('user')
    if err: return err
    data=request.get_json(silent=True) or {}; c=conn(); nid=c.execute('SELECT COALESCE(MAX(id),100)+1 FROM applications').fetchone()[0]; data.setdefault('id',nid); data.setdefault('applicant_name',u['name']); data.setdefault('org',u['org']); data.setdefault('status','submitted'); data.setdefault('submitted_date',datetime.date.today().isoformat()); data.setdefault('public_id',f"APP-{datetime.date.today().year}-{nid}"); c.execute('INSERT INTO applications(id,data) VALUES (?,?)',(data['id'],json.dumps(data))); c.commit(); c.close(); return jsonify({'ok':True,'application':data}),201

@app.post('/api/verification/approve')
def approve():
    u, err = require_role('officer','admin')
    if err: return err
    b=request.get_json(silent=True) or {}; aid=b.get('id'); c=conn(); r=c.execute('SELECT data FROM applications WHERE id=?',(aid,)).fetchone()
    if not r: c.close(); return jsonify({'error':'Application not found'}),404
    d=json.loads(r['data']); d['status']='approved'; d['approved_by']=u['name']; c.execute('UPDATE applications SET data=? WHERE id=?',(json.dumps(d),aid)); c.commit(); c.close()
    audit_log(u,'APPLICATION_APPROVED','Application',aid)
    return jsonify({'ok':True,'application':d})

@app.post('/api/verification/schedule')
def schedule():
    u, err = require_role('officer','admin')
    if err: return err
    b=request.get_json(silent=True) or {}; aid=b.get('id'); c=conn(); r=c.execute('SELECT data FROM applications WHERE id=?',(aid,)).fetchone()
    if not r: c.close(); return jsonify({'error':'Application not found'}),404
    d=json.loads(r['data']); d['status']='inspection_scheduled'; d['schedule']={'date':b.get('date'), 'time':b.get('time')}; c.execute('UPDATE applications SET data=? WHERE id=?',(json.dumps(d),aid)); c.commit(); c.close()
    audit_log(u,'INSPECTION_SCHEDULED','Application',aid)
    return jsonify({'ok':True,'application':d})

@app.post('/api/applications/bulk')
def applications_bulk():
    u=current_user()
    if not u: return jsonify({'error':'Authentication required'}),401
    items=(request.get_json(silent=True) or {}).get('applications',[])
    c=conn()
    for d in items:
        if not d or not d.get('id'): continue
        c.execute('INSERT OR REPLACE INTO applications(id,data) VALUES (?,?)',(int(d['id']),json.dumps(d)))
    c.commit(); c.close(); return jsonify({'ok':True,'count':len(items)})

# ------------------------------------------------------------------
# Officer assignment (Admin assigns applications to Metrology Officers)
# ------------------------------------------------------------------
@app.get('/api/officers')
def list_officers():
    u, err = require_role('admin')
    if err: return err
    c=conn()
    out=[{'id':r['id'],'name':r['name'],'lmo_code':r['lmo_code'],'district':r['district'],'org':r['org']} for r in c.execute("SELECT id,name,lmo_code,district,org FROM users WHERE role='officer'")]
    c.close(); return jsonify({'officers':out})

@app.post('/api/applications/<int:aid>/assign')
def assign_officer(aid):
    u, err = require_role('admin')
    if err: return err
    b=request.get_json(silent=True) or {}
    officer_id=b.get('officer_id')
    c=conn()
    r=c.execute('SELECT data FROM applications WHERE id=?',(aid,)).fetchone()
    if not r: c.close(); return jsonify({'error':'Application not found'}),404
    d=json.loads(r['data'])
    if officer_id in (None,'','unassign'):
        d['officer_id']=None; d['assigned_officer']='Unassigned'; d['assignment_status']='unassigned'; d['assigned_on']=None
        action='APPLICATION_UNASSIGNED'
    else:
        o=c.execute("SELECT * FROM users WHERE id=? AND role='officer'",(officer_id,)).fetchone()
        if not o: c.close(); return jsonify({'error':'Selected officer not found'}),404
        d['officer_id']=o['id']
        d['assigned_officer']=f"{o['name']} ({o['lmo_code'] or 'LMO'})"
        d['assignment_status']='assigned'
        d['assigned_on']=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        d['assigned_by']=u['name']
        action='OFFICER_ASSIGNED'
    c.execute('UPDATE applications SET data=? WHERE id=?',(json.dumps(d),aid)); c.commit(); c.close()
    audit_log(u,action,'Application',aid,d.get('assigned_officer',''))
    return jsonify({'ok':True,'application':d})

# ------------------------------------------------------------------
# MO -> GATC requests (send / inbox / approve-reject with reason)
# ------------------------------------------------------------------
@app.get('/api/gatc-requests')
def gatc_requests_list():
    u, err = require_role('officer','gatc','admin')
    if err: return err
    items=rows('gatc_requests')
    if u['role']=='officer':
        items=[r for r in items if r.get('officer_id')==u['id']]
    elif u['role']=='gatc':
        gid=u.get('gatc_id') or u.get('id')
        items=[r for r in items if not r.get('gatc_id') or r.get('gatc_id')==gid or r.get('gatc_code')==(u.get('lmo_code') or '')]
    items.sort(key=lambda r: r.get('created_on',''), reverse=True)
    return jsonify({'requests':items})

@app.post('/api/gatc-requests')
def gatc_request_create():
    u, err = require_role('officer','admin')
    if err: return err
    b=request.get_json(silent=True) or {}
    application_id=b.get('application_id')
    instrument_id=b.get('instrument_id')
    message=(b.get('message') or '').strip()
    if not message:
        return jsonify({'error':'A request message is required'}),400
    c=conn()
    app_d=None; inst_d=None
    if application_id:
        r=c.execute('SELECT data FROM applications WHERE id=?',(application_id,)).fetchone()
        if r: app_d=json.loads(r['data'])
    if instrument_id:
        r=c.execute('SELECT data FROM instruments WHERE id=?',(instrument_id,)).fetchone()
        if r: inst_d=json.loads(r['data'])
    if not app_d and not inst_d:
        c.close(); return jsonify({'error':'Select an application or instrument for this request'}),400
    gatc_id=b.get('gatc_id')
    gatc_d=None
    if gatc_id:
        r=c.execute('SELECT data FROM gatcs WHERE id=?',(gatc_id,)).fetchone()
        if r: gatc_d=json.loads(r['data'])
    code,nid=next_code('GATC-REQ','gatc_requests',1000)
    req={
        "id":nid,"code":code,
        "officer_id":u['id'],"officer_name":u['name'],"officer_code":u.get('lmo_code') or 'LMO',
        "gatc_id":(gatc_d or {}).get('id'),"gatc_code":(gatc_d or {}).get('code'),
        "application_id":(app_d or {}).get('application_id') or (app_d or {}).get('id'),
        "public_id":(app_d or {}).get('public_id'),
        "instrument_id":(inst_d or app_d or {}).get('instrument_id'),
        "serial":(inst_d or app_d or {}).get('serial',''),
        "instrument_name":(inst_d or app_d or {}).get('instrument_name') or (inst_d or {}).get('name',''),
        "district":(app_d or inst_d or {}).get('district',''),
        "subject":b.get('subject') or 'GATC testing request',
        "message":message,
        "status":"pending","reason_code":None,"reason_note":"",
        "created_on":datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "decided_on":None,"decided_by":None
    }
    c.execute('INSERT INTO gatc_requests(id,data) VALUES (?,?)',(nid,json.dumps(req)))
    c.commit(); c.close()
    audit_log(u,'GATC_REQUEST_SENT',req['code'],nid)
    return jsonify({'ok':True,'request':req}),201

@app.post('/api/gatc-requests/<int:rid>/decision')
def gatc_request_decision(rid):
    u, err = require_role('gatc')
    if err: return err
    b=request.get_json(silent=True) or {}
    decision=(b.get('decision') or '').lower()
    if decision not in ('approved','rejected'):
        return jsonify({'error':"decision must be 'approved' or 'rejected'"}),400
    reason_code=b.get('reason_code'); reason_note=(b.get('reason_note') or '').strip()
    if decision=='rejected' and not reason_code:
        return jsonify({'error':'A rejection reason is required'}),400
    if reason_code and reason_code not in GATC_REJECTION_REASONS:
        return jsonify({'error':'Invalid rejection reason'}),400
    c=conn()
    r=c.execute('SELECT data FROM gatc_requests WHERE id=?',(rid,)).fetchone()
    if not r: c.close(); return jsonify({'error':'Request not found'}),404
    d=json.loads(r['data'])
    if d.get('status')!='pending':
        c.close(); return jsonify({'error':'This request has already been decided'}),409
    d['status']=decision
    d['reason_code']=reason_code if decision=='rejected' else None
    d['reason_label']=GATC_REJECTION_REASONS.get(reason_code) if decision=='rejected' else None
    d['reason_note']=reason_note
    d['decided_on']=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    d['decided_by']=f"{u.get('org') or 'GATC'} ({u.get('lmo_code') or 'GATC'})"
    # Approving a request links the application/instrument to this GATC for testing
    if decision=='approved' and d.get('gatc_id') is None:
        d['gatc_id']=u.get('gatc_id') or u.get('id')
        d['gatc_code']=u.get('lmo_code') or 'GATC'
    gatc_id=u.get('gatc_id') or u.get('id')
    if decision=='approved' and d.get('application_id'):
        ar=c.execute('SELECT data FROM applications WHERE id=?',(d['application_id'],)).fetchone()
        if ar:
            ad=json.loads(ar['data'])
            ad['gatc_id']=gatc_id
            ad['gatc_assigned_on']=datetime.date.today().isoformat()
            if ad.get('status') not in ('failed','rejected','payment_paid','payment_pending','gatc_assigned','inspection_completed','verified','completed'):
                ad['status']='gatc_assigned'
                ad['gatc_test_result']=None
            c.execute('UPDATE applications SET data=? WHERE id=?',(json.dumps(ad),d['application_id']))
    c.execute('UPDATE gatc_requests SET data=? WHERE id=?',(json.dumps(d),rid))
    c.commit(); c.close()
    audit_log(u,'GATC_REQUEST_'+decision.upper(),d['code'],rid,d.get('reason_label') or '')
    return jsonify({'ok':True,'request':d})

# ------------------------------------------------------------------
# Field inspections (measurements + photos + GPS)
# ------------------------------------------------------------------
@app.get('/api/inspections')
def inspections_list():
    u, err = require_role('officer','admin')
    if err: return err
    items=rows('inspections')
    if u['role']=='officer':
        items=[r for r in items if r.get('officer_id')==u['id']]
    items.sort(key=lambda r: r.get('inspected_on',''), reverse=True)
    return jsonify({'inspections':items})

@app.post('/api/inspections')
def inspection_create():
    u, err = require_role('officer')
    if err: return err
    f=request.form
    application_id=f.get('application_id'); instrument_id=f.get('instrument_id')
    verdict=(f.get('verdict') or '').lower()
    if verdict not in ('pass','fail'):
        return jsonify({'error':'verdict must be pass or fail'}),400
    failure_code=f.get('failure_reason_code') or None
    if verdict=='fail' and failure_code not in FAILURE_REASONS:
        return jsonify({'error':'A valid failure reason is required when the verdict is fail'}),400
    try:
        measurements=json.loads(f.get('measurements') or '[]')
        if not isinstance(measurements,list): measurements=[]
    except Exception:
        return jsonify({'error':'measurements must be valid JSON'}),400
    for m in measurements:
        try:
            m['load_kg']=float(m.get('load_kg') or 0); m['indicated_kg']=float(m.get('indicated_kg') or 0)
            m['error_kg']=round(m['indicated_kg']-m['load_kg'],4)
        except Exception:
            return jsonify({'error':'Invalid measurement values'}),400
    gps={}
    try:
        gps_raw=f.get('gps') or ''
        if gps_raw:
            gps=json.loads(gps_raw)
    except Exception:
        gps={}
    c=conn()
    app_d=None; inst_d=None
    if application_id:
        r=c.execute('SELECT data FROM applications WHERE id=?',(application_id,)).fetchone()
        if r: app_d=json.loads(r['data'])
    if instrument_id:
        r=c.execute('SELECT data FROM instruments WHERE id=?',(instrument_id,)).fetchone()
        if r: inst_d=json.loads(r['data'])
    code,nid=next_code('INS','inspections',9000)
    now=datetime.datetime.now()
    insp={
        "id":nid,"code":code,
        "application_id":int(application_id) if application_id else (app_d or {}).get('id'),
        "public_id":(app_d or {}).get('public_id'),
        "instrument_id":int(instrument_id) if instrument_id else (inst_d or app_d or {}).get('instrument_id'),
        "serial":(inst_d or app_d or {}).get('serial',''),
        "instrument_name":(inst_d or {}).get('name') or (app_d or {}).get('instrument_name',''),
        "district":(inst_d or app_d or u).get('district',''),
        "officer_id":u['id'],"officer_name":u['name'],"officer_code":u.get('lmo_code') or 'LMO',
        "inspected_on":now.strftime("%Y-%m-%d %H:%M"),
        "measurements":measurements,
        "seal_condition":f.get('seal_condition') or 'not_checked',
        "verdict":verdict,
        "failure_reason_code":failure_code if verdict=='fail' else None,
        "failure_reason_label":FAILURE_REASONS.get(failure_code) if verdict=='fail' else None,
        "failure_note":(f.get('failure_note') or '').strip(),
        "notes":(f.get('notes') or '').strip(),
        "photos":[],
        "gps":{"lat":gps.get('lat'),"lng":gps.get('lng'),"accuracy":gps.get('accuracy'),"captured_at":gps.get('captured_at') or now.isoformat()},
        "gps_permission":gps.get('granted', bool(gps.get('lat') is not None)),
        "status":"completed"
    }
    # save uploaded photos
    files=request.files.getlist('photos')
    saved=0
    folder=os.path.join(UPLOAD_DIR,f"insp_{nid}")
    for file in files[:6]:
        if not file or not file.filename: continue
        ext=os.path.splitext(file.filename)[1][:8] or '.jpg'
        os.makedirs(folder,exist_ok=True)
        fname=f"{int(time.time()*1000)}_{saved}{ext}"
        file.save(os.path.join(folder,fname))
        insp['photos'].append({"url":f"/uploads/insp_{nid}/{fname}","name":file.filename})
        saved+=1
    c.execute('INSERT INTO inspections(id,data) VALUES (?,?)',(nid,json.dumps(insp)))
    # side effects on application + instrument + high-risk flags
    if insp['application_id']:
        r=c.execute('SELECT data FROM applications WHERE id=?',(insp['application_id'],)).fetchone()
        if r:
            ad=json.loads(r['data'])
            ad['inspection_id']=nid
            ad['inspection_status']='completed'
            if verdict=='pass':
                ad['status']='inspection_completed'
                ad['failure_reason_code']=None
            else:
                ad['status']='failed'
                ad['failure_reason_code']=failure_code
                ad['failure_reason_label']=FAILURE_REASONS.get(failure_code)
                ad['high_risk']=failure_code in ('tampered_seal','third_party_issue')
            c.execute('UPDATE applications SET data=? WHERE id=?',(json.dumps(ad),ad['id']))
    if insp['instrument_id']:
        r=c.execute('SELECT data FROM instruments WHERE id=?',(insp['instrument_id'],)).fetchone()
        if r:
            idata=json.loads(r['data'])
            if verdict=='pass':
                idata['status']='verified'; idata['last_verified']=now.date().isoformat()
            else:
                idata['status']='failed'
                if failure_code=='tampered_seal': idata['status']='sealed_tampered'
                if failure_code=='third_party_issue': idata['oem_status']='third_party'
                idata['high_risk']=True
                idata['risk_reason']=FAILURE_REASONS.get(failure_code)
            c.execute('UPDATE instruments SET data=? WHERE id=?',(json.dumps(idata),idata['id']))
    c.commit(); c.close()
    audit_log(u,'INSPECTION_'+('PASS' if verdict=='pass' else 'FAIL'),code,nid,insp.get('failure_reason_label') or '')
    return jsonify({'ok':True,'inspection':insp}),201

# ------------------------------------------------------------------
# Outside jurisdiction -> authorization requests
# ------------------------------------------------------------------
@app.get('/api/authorizations')
def authorizations_list():
    u, err = require_role('officer','admin')
    if err: return err
    items=rows('authorizations')
    if u['role']=='officer':
        items=[r for r in items if r.get('officer_id')==u['id']]
    items.sort(key=lambda r: r.get('created_on',''), reverse=True)
    return jsonify({'authorizations':items})

@app.post('/api/authorizations')
def authorization_create():
    u, err = require_role('officer')
    if err: return err
    b=request.get_json(silent=True) or {}
    reason_code=b.get('reason_code')
    if reason_code not in AUTHORIZATION_REASONS:
        return jsonify({'error':'A valid authorization reason is required'}),400
    entity_type=b.get('entity_type') or 'application'
    entity_id=b.get('entity_id')
    if not entity_id:
        return jsonify({'error':'entity_id is required'}),400
    code,nid=next_code('AUTH','authorizations',500)
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    d={"id":nid,"code":code,
       "officer_id":u['id'],"officer_name":u['name'],"officer_code":u.get('lmo_code') or 'LMO',
       "entity_type":entity_type,"entity_id":entity_id,
       "user_id":b.get('user_id'),"user_label":b.get('user_label',''),
       "location":b.get('location',u.get('district','')),
       "district":b.get('district',''),
       "group_id":b.get('group_id',''),
       "reason_code":reason_code,"reason_label":AUTHORIZATION_REASONS[reason_code],
       "reason_note":(b.get('reason_note') or '').strip(),
       "status":"authorization_requested",
       "created_on":now,"decided_on":None,"decided_by":None,"decision_note":""}
    c=conn(); c.execute('INSERT INTO authorizations(id,data) VALUES (?,?)',(nid,json.dumps(d))); c.commit(); c.close()
    audit_log(u,'AUTHORIZATION_REQUESTED',code,nid)
    return jsonify({'ok':True,'authorization':d}),201

@app.post('/api/authorizations/<int:aid>/decision')
def authorization_decision(aid):
    u, err = require_role('admin')
    if err: return err
    b=request.get_json(silent=True) or {}
    decision=(b.get('decision') or '').lower()
    if decision not in ('authorized','denied'):
        return jsonify({'error':"decision must be 'authorized' or 'denied'"}),400
    c=conn()
    r=c.execute('SELECT data FROM authorizations WHERE id=?',(aid,)).fetchone()
    if not r: c.close(); return jsonify({'error':'Authorization request not found'}),404
    d=json.loads(r['data'])
    if d.get('status')!='authorization_requested':
        c.close(); return jsonify({'error':'This authorization request has already been decided'}),409
    d['status']='authorized' if decision=='authorized' else 'authorization_denied'
    d['decision_note']=(b.get('note') or '').strip()
    d['decided_on']=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    d['decided_by']=u['name']
    c.execute('UPDATE authorizations SET data=? WHERE id=?',(json.dumps(d),aid))
    c.commit(); c.close()
    audit_log(u,'AUTHORIZATION_'+decision.upper(),d['code'],aid)
    return jsonify({'ok':True,'authorization':d})

# ------------------------------------------------------------------
# Notifications (kept for backward compatibility)
# ------------------------------------------------------------------
@app.get('/api/notifications')
def notifications(): return jsonify({'notifications':rows('notifications')})

@app.post('/api/notifications')
def save_notifications():
    u=current_user()
    if not u: return jsonify({'error':'Authentication required'}),401
    items=(request.get_json(silent=True) or {}).get('notifications',[])
    c=conn()
    c.execute('DELETE FROM notifications')
    for n in items[:50]:
        c.execute('INSERT OR REPLACE INTO notifications(id,data) VALUES (?,?)',(int(float(n.get('id',0))),json.dumps(n)))
    c.commit(); c.close(); return jsonify({'ok':True,'count':len(items[:50])})

@app.get('/api/complaints')
def complaints(): return jsonify({'complaints':rows('complaints')})

@app.post('/api/complaints')
def create_complaint():
    u, err = require_role('user','officer','admin')
    if err: return err
    b=request.get_json(silent=True) or {}; c=conn(); nums=[]
    for r in c.execute('SELECT id FROM complaints').fetchall():
      try: nums.append(int(str(r['id']).replace('CMP-','')))
      except: pass
    cid=f"CMP-{(max(nums) if nums else 1025)+1}"; d={'id':cid,'instrument_id':b.get('instrument_id',2),'serial':b.get('serial',''),'type':b.get('type',''),'description':b.get('description',''),'district':u.get('district','Lucknow'),'date':datetime.date.today().isoformat(),'priority':'High','status':'New','assigned_officer':'Unassigned'}; c.execute('INSERT INTO complaints(id,data) VALUES (?,?)',(cid,json.dumps(d))); c.commit(); c.close(); return jsonify({'ok':True,'complaint':d}),201

@app.get('/api/certificates')
def certificates(): return jsonify({'certificates':rows('certificates')})

@app.post('/api/certificates/revoke')
def revoke_certificate():
    u, err = require_role('admin','user')
    if err: return err
    b=request.get_json(silent=True) or {}
    cert_no=b.get('cert_no'); instrument_id=b.get('instrument_id')
    reason_code=b.get('reason_code')
    if reason_code not in REVOKE_REASONS:
        return jsonify({'error':'A valid revocation reason is required'}),400
    c=conn()
    row=None
    if cert_no:
        for r in c.execute('SELECT id,data FROM certificates').fetchall():
            d=json.loads(r['data'])
            if d.get('cert_no')==cert_no: row=(r['id'],d); break
    elif instrument_id is not None:
        for r in c.execute('SELECT id,data FROM certificates').fetchall():
            d=json.loads(r['data'])
            if str(d.get('instrument_id'))==str(instrument_id): row=(r['id'],d); break
    if not row:
        c.close(); return jsonify({'error':'Certificate not found'}),404
    cid,d=row
    # traders may only revoke their own certificate
    if u['role']=='user':
        owner=d.get('owner') or ''
        inst=c.execute('SELECT data FROM instruments WHERE id=?',(d.get('instrument_id'),)).fetchone()
        inst_premises=json.loads(inst['data']).get('premises','') if inst else ''
        if owner.lower() not in ((u.get('org') or '').lower(), inst_premises.lower()):
            c.close(); return jsonify({'error':'You can only revoke your own certificate'}),403
    d['status']='Revoked'
    d['revoked_at']=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    d['revoked_by']=f"{u['name']} ({u['role']})"
    d['revoke_reason_code']=reason_code
    d['revoke_reason_label']=REVOKE_REASONS[reason_code]
    d['revoke_note']=(b.get('note') or '').strip()
    c.execute('UPDATE certificates SET data=? WHERE id=?',(json.dumps(d),cid))
    # keep the instrument registry consistent
    if d.get('instrument_id') is not None:
        ir=c.execute('SELECT data FROM instruments WHERE id=?',(d['instrument_id'],)).fetchone()
        if ir:
            idata=json.loads(ir['data']); idata['status']='revoked'; idata['certificate_status']='revoked'
            c.execute('UPDATE instruments SET data=? WHERE id=?',(json.dumps(idata),d['instrument_id']))
    c.commit(); c.close()
    audit_log(u,'CERTIFICATE_REVOKED',d.get('cert_no'),cid,d['revoke_reason_label'])
    return jsonify({'ok':True,'certificate':d})

def issue_certificate_for_instrument(inst_id):
    c=conn()
    for r in c.execute('SELECT id,data FROM certificates').fetchall():
        d=json.loads(r['data'])
        if str(d.get('instrument_id'))==str(inst_id):
            c.close(); return d
    ir=c.execute('SELECT data FROM instruments WHERE id=?',(inst_id,)).fetchone()
    if not ir: c.close(); return None
    idata=json.loads(ir['data'])
    n=c.execute('SELECT COALESCE(MAX(id),4400)+1 FROM certificates').fetchone()[0]
    today=datetime.date.today()
    d={"cert_no":f"CERT-UP-{today.year}-{4400+n}","instrument_id":idata.get('id'),"serial":idata.get('serial'),
       "owner":idata.get('premises',''),"issue_date":today.isoformat(),
       "expiry_date":(today+datetime.timedelta(days=365)).isoformat(),"status":"Valid","issued_via":"payment"}
    c.execute('INSERT INTO certificates(id,data) VALUES (?,?)',(n,json.dumps(d)))
    c.commit(); c.close()
    return d

@app.post('/api/payments')
def make_payment():
    u, err = require_role('user')
    if err: return err
    b=request.get_json(silent=True) or {}
    aid=b.get('application_id'); amount=b.get('amount')
    c=conn()
    r=c.execute('SELECT data FROM applications WHERE id=?',(aid,)).fetchone() if aid else None
    if not r: c.close(); return jsonify({'error':'Application not found'}),404
    ad=json.loads(r['data'])
    if (ad.get('owner_id') or ad.get('applicant_id')) not in (None,u['id']) and ad.get('owner_id')!=u['id']:
        c.close(); return jsonify({'error':'You can only pay for your own applications'}),403
    if ad.get('status') not in ('payment_pending','completed','gatc_tested'):
        c.close(); return jsonify({'error':'Payment is not due for this application yet'}),400
    try: amount=float(amount)
    except (TypeError,ValueError): c.close(); return jsonify({'error':'Invalid payment amount'}),400
    txn=f"PAY-{int(time.time()*1000)}"
    n=c.execute('SELECT COALESCE(MAX(id),0)+1 FROM payments').fetchone()[0]
    pdata={"application_id":ad['id'],"public_id":ad.get('public_id'),"serial":ad.get('serial'),
           "instrument_id":ad.get('instrument_id'),"owner_id":u['id'],"owner":u['name'],
           "amount":amount,"status":"paid","transaction_id":txn,
           "paid_on":datetime.datetime.now().isoformat()}
    c.execute('INSERT INTO payments(id,instrument_id,transaction_id,amount,status,data) VALUES (?,?,?,?,?,?)',
              (n,ad.get('instrument_id'),txn,amount,'paid',json.dumps(pdata)))
    ad['payment']={"status":"paid","amount":amount,"paid_on":pdata['paid_on'],"payment_id":txn}
    ad['status']='payment_paid'
    c.execute('UPDATE applications SET data=? WHERE id=?',(json.dumps(ad),ad['id']))
    c.commit(); c.close()
    cert=issue_certificate_for_instrument(ad.get('instrument_id')) if ad.get('instrument_id') else None
    audit_log(u,'PAYMENT_RECEIVED',ad.get('public_id'),aid,f"Rs {amount}")
    return jsonify({'ok':True,'payment':pdata,'application':ad,'certificate':cert}),201

@app.get('/api/payments')
def list_payments():
    u, err = require_role('user','admin')
    if err: return err
    items=rows('payments')
    if u['role']=='user':
        items=[p for p in items if p.get('owner_id')==u['id']]
    return jsonify({'payments':items})

@app.get('/api/public/verify')
def public_verify():
    q=request.args.get('q','').lower(); insts=rows('instruments'); inst=next((i for i in insts if i.get('serial','').lower()==q or q in i.get('name','').lower()),None)
    if not inst: return jsonify({'found':False,'note':'Not Found on Registry'})
    cert=next((c for c in rows('certificates') if c.get('instrument_id')==inst['id']),None); return jsonify({'found':True,**inst,'certificate':cert})

def _days_ago(n):
    return (datetime.date.today()-datetime.timedelta(days=n)).isoformat()

@app.get('/api/stats')
def stats():
    ins=rows('instruments'); apps=rows('applications'); cmps=rows('complaints'); insp=rows('inspections'); greq=rows('gatc_requests'); gatcs=rows('gatcs'); certs=rows('certificates')
    failed_cases=sum(1 for a in apps if a.get('status')=='failed')+sum(1 for i in insp if i.get('verdict')=='fail')
    return jsonify({
      'instruments':len(ins),'due_soon':sum(1 for i in ins if i.get('next_due')),
      'by_oem':{'third_party':sum(1 for i in ins if i.get('oem_status')=='third_party')},
      'audits':len(rows('audit')),'pending_complaints':len(cmps),
      'high_risk':sum(1 for i in ins if i.get('status')=='expired' or i.get('oem_status')=='third_party' or i.get('high_risk')),
      'applications_total':len(apps),
      'applications_pending':sum(1 for a in apps if a.get('status') in ('pending','submitted')),
      'applications_approved':sum(1 for a in apps if a.get('status') in ('approved','scheduled','gatc_assigned','inspection_completed','payment_pending','payment_paid','verified')),
      'applications_rejected':sum(1 for a in apps if a.get('status')=='rejected'),
      'applications_failed':sum(1 for a in apps if a.get('status')=='failed'),
      'applications_assigned':sum(1 for a in apps if a.get('assignment_status')=='assigned' or (a.get('assigned_officer') and a.get('assigned_officer')!='Unassigned')),
      'applications_unassigned':sum(1 for a in apps if not a.get('assigned_officer') or a.get('assigned_officer')=='Unassigned'),
      'gatcs_total':len(gatcs),'gatcs_active':sum(1 for g in gatcs if g.get('status')=='active'),
      'inspections_total':len(insp),
      'failed_cases':failed_cases,
      'gatc_requests_pending':sum(1 for r in greq if r.get('status')=='pending'),
      'gatc_requests_total':len(greq),
      'certificates_valid':sum(1 for c in certs if c.get('status')=='Valid'),
      'certificates_revoked':sum(1 for c in certs if c.get('status')=='Revoked'),
      'authorizations_pending':sum(1 for a in rows('authorizations') if a.get('status')=='authorization_requested')
    })

@app.get('/api/analytics')
def analytics():
    u, err = require_role('admin')
    if err: return err
    try: days=max(7,min(365,int(request.args.get('days',30))))
    except ValueError: days=30
    cutoff=_days_ago(days)
    apps=rows('applications'); insp=rows('inspections'); greq=rows('gatc_requests'); auths=rows('authorizations'); cmps=rows('complaints'); insts=rows('instruments'); certs=rows('certificates'); pays=rows('payments'); gatcs=rows('gatcs')

    def series(items, datekey):
        out={}
        for x in items:
            d=str(x.get(datekey,''))[:10]
            if d and d>=cutoff: out[d]=out.get(d,0)+1
        return [{"date":d,"count":out[d]} for d in sorted(out)]

    def by_key(items, key):
        out={}
        for x in items:
            k=x.get(key) or 'Unknown'
            out[k]=out.get(k,0)+1
        return out

    app_by_status={}
    for a in apps:
        s=a.get('status') or 'unknown'
        app_by_status[s]=app_by_status.get(s,0)+1
    greq_by_status={}
    for r in greq:
        s=r.get('status') or 'unknown'
        greq_by_status[s]=greq_by_status.get(s,0)+1
    insp_pass=sum(1 for i in insp if i.get('verdict')=='pass'); insp_fail=sum(1 for i in insp if i.get('verdict')=='fail')
    failed_reasons={}
    for i in insp:
        if i.get('verdict')=='fail':
            k=i.get('failure_reason_label') or i.get('failure_reason_code') or 'unknown'
            failed_reasons[k]=failed_reasons.get(k,0)+1
    for a in apps:
        if a.get('status')=='failed':
            k=a.get('failure_reason_label') or a.get('failure_reason_code') or 'unknown'
            failed_reasons[k]=failed_reasons.get(k,0)+1
    return jsonify({
      'days':days,
      'applications':{'total':len(apps),'by_status':app_by_status,'per_day':series(apps,'submitted_date')},
      'inspections':{'total':len(insp),'pass':insp_pass,'fail':insp_fail,'per_day':series(insp,'inspected_on')},
      'gatc_requests':{'total':len(greq),'by_status':greq_by_status},
      'authorizations':{'total':len(auths),'by_status':by_key(auths,'status')},
      'complaints':{'total':len(cmps),'by_type':by_key(cmps,'type')},
      'instruments':{'total':len(insts),'by_status':by_key(insts,'status'),'by_district':by_key(insts,'district'),
                     'high_risk':sum(1 for i in insts if i.get('status')=='expired' or i.get('oem_status')=='third_party' or i.get('high_risk'))},
      'certificates':{'total':len(certs),'by_status':by_key(certs,'status')},
      'payments':{'total':len(pays),'amount':sum(float(p.get('amount') or 0) for p in pays)},
      'gatcs':{'total':len(gatcs),'active':sum(1 for g in gatcs if g.get('status')=='active')},
      'failed_reasons':failed_reasons
    })

@app.get('/api/audit')
def audit(): return jsonify({'events':list(reversed(rows('audit')))})

@app.get('/api/guidelines')
def guidelines(): return jsonify({'guidelines':[{'id':'GL-01','jurisdiction':'India · Legal Metrology Act 2009','title':'Section 24 — Verification and Stamping','body':'Every weight or measure used in transaction of trade or commerce must be verified and stamped by a Legal Metrology Officer in prescribed intervals.','refs':['Act No. 1 of 2010','Rule 12']}], 'reverify_months':{'electronic_weighing':12,'platform_scale':12,'weighbridge':12,'fuel_dispenser':12,'counter_machine':24,'tape':60}})

@app.route('/api/analyze',methods=['POST'])
@app.route('/api/public/analyze',methods=['POST'])
def analyze(): return jsonify({'label':'GENUINE','headline':'Genuine OEM Instrument & Sealing Verified','confidence':96,'flags':['Nameplate typography matches registered mold','Lead wire seal imprint corresponds to registered LMO'],'parts':[],'compliance':{'verdict':'COMPLIANT','passed':['Model approval active'],'issues':[],'rules_applied':['Legal Metrology Act s.24']}})

if __name__=='__main__':
    init_db(); app.run(host='0.0.0.0',port=5000,debug=True)
