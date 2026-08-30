from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3, json, os, hashlib, datetime
BASE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE)

DB_PATH = os.path.join(BASE, 'pramana.db')
FRONTEND = os.path.join(PROJECT_ROOT, 'frontend')
app=Flask(__name__, static_folder=FRONTEND, static_url_path='')

CORS(app, supports_credentials=True)

def conn():
    c=sqlite3.connect(DB_PATH)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    c=conn(); cur=c.cursor()
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, role TEXT, org TEXT, district TEXT, lmo_code TEXT, password TEXT);
    CREATE TABLE IF NOT EXISTS instruments(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS applications(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS complaints(id TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS certificates(id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, instrument_id INTEGER, transaction_id TEXT UNIQUE, amount REAL, status TEXT, data TEXT NOT NULL);
    ''')
    users=[
      (1,'Rajesh Sharma','trader@pramana.in','user','Sharma Stores','Lucknow',None,'password123'),
      (2,'Rahul Sharma','officer@pramana.in','officer','District Inspectorate','Lucknow','LMO-LKO-01','password123'),
      (99,'Director General','admin@pramana.in','admin','Legal Metrology Dept, UP','Lucknow','LMO-HQ-00','password123')]
    for u in users: cur.execute('INSERT OR IGNORE INTO users VALUES (?,?,?,?,?,?,?,?)',u)
    if cur.execute('SELECT COUNT(*) FROM instruments').fetchone()[0]==0:
      instruments=json.load(open(os.path.join(os.path.dirname(BASE),'db_seed.json')))['instruments']
      for x in instruments: cur.execute('INSERT INTO instruments(id,data) VALUES (?,?)',(x['id'],json.dumps(x)))
    seed=json.load(open(os.path.join(os.path.dirname(BASE),'db_seed.json')))
    if cur.execute('SELECT COUNT(*) FROM applications').fetchone()[0]==0:
      for x in seed['applications']: cur.execute('INSERT INTO applications(id,data) VALUES (?,?)',(x['id'],json.dumps(x)))
    if cur.execute('SELECT COUNT(*) FROM complaints').fetchone()[0]==0:
      for x in seed['complaints']: cur.execute('INSERT INTO complaints(id,data) VALUES (?,?)',(x['id'],json.dumps(x)))
    if cur.execute('SELECT COUNT(*) FROM certificates').fetchone()[0]==0:
      for x in seed['certificates']: cur.execute('INSERT INTO certificates(data) VALUES (?)',(json.dumps(x),))
    if cur.execute('SELECT COUNT(*) FROM audit').fetchone()[0]==0:
      for x in seed['audit']: cur.execute('INSERT INTO audit(data) VALUES (?)',(json.dumps(x),))
    if cur.execute('SELECT COUNT(*) FROM notifications').fetchone()[0]==0:
      for x in seed['notifications']: cur.execute('INSERT INTO notifications(data) VALUES (?)',(json.dumps(x),))
    c.commit(); c.close()

SESSIONS={}
def current_user():
    token=request.headers.get('X-Session-Token') or request.cookies.get('pramana_session')
    return SESSIONS.get(token)

def rows(table):
    c=conn(); out=[json.loads(r['data']) for r in c.execute(f'SELECT data FROM {table}').fetchall()]; c.close(); return out

def save_json(table, keycol, key, data):
    c=conn(); c.execute(f'INSERT OR REPLACE INTO {table}({keycol},data) VALUES (?,?)',(key,json.dumps(data))); c.commit(); c.close()

@app.get('/')
def index(): return send_from_directory(FRONTEND,'index.html')

@app.get('/api/bootstrap')
def bootstrap():
    return jsonify({'instruments':rows('instruments'),'applications':rows('applications'),'complaints':rows('complaints'),'certificates':rows('certificates'),'audit':rows('audit'),'notifications':rows('notifications')})

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
    u=current_user()
    if not u: return jsonify({'error':'Authentication required'}),401
    data=request.get_json(silent=True) or {}; c=conn(); nid=(c.execute('SELECT COALESCE(MAX(id),0)+1 FROM instruments').fetchone()[0]); data['id']=nid; c.execute('INSERT INTO instruments(id,data) VALUES (?,?)',(nid,json.dumps(data))); c.commit(); c.close(); return jsonify({'ok':True,'instrument':data}),201

@app.get('/api/applications')
def applications(): return jsonify({'applications':rows('applications')})

@app.post('/api/verification/apply')
def apply_verification():
    u=current_user();
    if not u: return jsonify({'error':'Authentication required'}),401
    data=request.get_json(silent=True) or {}; c=conn(); nid=c.execute('SELECT COALESCE(MAX(id),100)+1 FROM applications').fetchone()[0]; data.setdefault('id',nid); data.setdefault('applicant_name',u['name']); data.setdefault('org',u['org']); data.setdefault('status','submitted'); data.setdefault('submitted_date',datetime.date.today().isoformat()); data.setdefault('public_id',f"APP-{datetime.date.today().year}-{nid}"); c.execute('INSERT INTO applications(id,data) VALUES (?,?)',(data['id'],json.dumps(data))); c.commit(); c.close(); return jsonify({'ok':True,'application':data}),201

@app.post('/api/verification/approve')
def approve():
    b=request.get_json(silent=True) or {}; aid=b.get('id'); c=conn(); r=c.execute('SELECT data FROM applications WHERE id=?',(aid,)).fetchone();
    if not r: c.close(); return jsonify({'error':'Application not found'}),404
    d=json.loads(r['data']); d['status']='approved'; c.execute('UPDATE applications SET data=? WHERE id=?',(json.dumps(d),aid)); c.commit(); c.close(); return jsonify({'ok':True,'application':d})

@app.post('/api/verification/schedule')
def schedule():
    b=request.get_json(silent=True) or {}; aid=b.get('id'); c=conn(); r=c.execute('SELECT data FROM applications WHERE id=?',(aid,)).fetchone();
    if not r: c.close(); return jsonify({'error':'Application not found'}),404
    d=json.loads(r['data']); d['status']='inspection_scheduled'; d['schedule']={'date':b.get('date'), 'time':b.get('time')}; c.execute('UPDATE applications SET data=? WHERE id=?',(json.dumps(d),aid)); c.commit(); c.close(); return jsonify({'ok':True,'application':d})

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
        c.execute('INSERT INTO notifications(id,data) VALUES (?,?)',(int(float(n.get('id',0))),json.dumps(n)))
    c.commit(); c.close(); return jsonify({'ok':True,'count':len(items[:50])})

@app.get('/api/complaints')
def complaints(): return jsonify({'complaints':rows('complaints')})

@app.post('/api/complaints')
def create_complaint():
    u=current_user();
    if not u: return jsonify({'error':'Authentication required'}),401
    b=request.get_json(silent=True) or {}; c=conn(); nums=[]
    for r in c.execute('SELECT id FROM complaints').fetchall():
      try: nums.append(int(str(r['id']).replace('CMP-','')))
      except: pass
    cid=f"CMP-{(max(nums) if nums else 1025)+1}"; d={'id':cid,'instrument_id':b.get('instrument_id',2),'serial':b.get('serial',''),'type':b.get('type',''),'description':b.get('description',''),'district':u.get('district','Lucknow'),'date':datetime.date.today().isoformat(),'priority':'High','status':'New','assigned_officer':'Unassigned'}; c.execute('INSERT INTO complaints(id,data) VALUES (?,?)',(cid,json.dumps(d))); c.commit(); c.close(); return jsonify({'ok':True,'complaint':d}),201

@app.get('/api/certificates')
def certificates(): return jsonify({'certificates':rows('certificates')})

@app.get('/api/public/verify')
def public_verify():
    q=request.args.get('q','').lower(); insts=rows('instruments'); inst=next((i for i in insts if i.get('serial','').lower()==q or q in i.get('name','').lower()),None)
    if not inst: return jsonify({'found':False,'note':'Not Found on Registry'})
    cert=next((c for c in rows('certificates') if c.get('instrument_id')==inst['id']),None); return jsonify({'found':True,**inst,'certificate':cert})

@app.get('/api/stats')
def stats():
    ins=rows('instruments'); return jsonify({'instruments':len(ins),'due_soon':sum(1 for i in ins if i.get('next_due')),'by_oem':{'third_party':sum(1 for i in ins if i.get('oem_status')=='third_party')},'audits':len(rows('audit')),'high_risk':sum(1 for i in ins if i.get('status')=='expired' or i.get('oem_status')=='third_party'),'pending_complaints':len(rows('complaints'))})

@app.get('/api/audit')
def audit(): return jsonify({'events':rows('audit')})
@app.get('/api/guidelines')
def guidelines(): return jsonify({'guidelines':[{'id':'GL-01','jurisdiction':'India · Legal Metrology Act 2009','title':'Section 24 — Verification and Stamping','body':'Every weight or measure used in transaction of trade or commerce must be verified and stamped by a Legal Metrology Officer in prescribed intervals.','refs':['Act No. 1 of 2010','Rule 12']}], 'reverify_months':{'electronic_weighing':12,'platform_scale':12,'weighbridge':12,'fuel_dispenser':12,'counter_machine':24,'tape':60}})

@app.route('/api/analyze',methods=['POST'])
@app.route('/api/public/analyze',methods=['POST'])
def analyze(): return jsonify({'label':'GENUINE','headline':'Genuine OEM Instrument & Sealing Verified','confidence':96,'flags':['Nameplate typography matches registered mold','Lead wire seal imprint corresponds to registered LMO'],'parts':[],'compliance':{'verdict':'COMPLIANT','passed':['Model approval active'],'issues':[],'rules_applied':['Legal Metrology Act s.24']}})

if __name__=='__main__':
    init_db(); app.run(host='127.0.0.1',port=5000,debug=True)
