import os, sqlite3
from datetime import date, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-demo-secret-key')
app.config['DATABASE'] = os.path.join(app.instance_path, 'gym_slot_master.db')
os.makedirs(app.instance_path, exist_ok=True)

PLANS = [('Monthly', 30), ('Quarterly', 90), ('Half-Yearly', 180), ('Yearly', 365)]

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS slots (
      id INTEGER PRIMARY KEY AUTOINCREMENT, slot_date TEXT NOT NULL,
      slot_time TEXT NOT NULL, capacity INTEGER NOT NULL DEFAULT 10,
      UNIQUE(slot_date, slot_time)
    );
    CREATE TABLE IF NOT EXISTS bookings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      slot_id INTEGER NOT NULL, booked_at TEXT DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(user_id, slot_id),
      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
      FOREIGN KEY(slot_id) REFERENCES slots(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS membership_plans (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
      duration_days INTEGER NOT NULL, price REAL NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS subscriptions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      plan_id INTEGER NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
      amount REAL NOT NULL, payment_status TEXT NOT NULL DEFAULT 'Unpaid',
      payment_method TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(user_id) REFERENCES users(id),
      FOREIGN KEY(plan_id) REFERENCES membership_plans(id)
    );
    ''')
    # Migrate older database without deleting existing members/bookings.
    user_cols = {r['name'] for r in db.execute('PRAGMA table_info(users)')}
    if 'is_active' not in user_cols:
        db.execute('ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1')
    if 'must_change_password' not in user_cols:
        db.execute('ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0')
    # Remove obsolete QR-related columns only from application usage; SQLite keeps old columns harmlessly.
    defaults = {
      'admin_username': os.environ.get('ADMIN_EMAIL', 'admin@gym.local'),
      'admin_password_hash': generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'GymAdmin@123')),
      'contact_phone': '', 'contact_whatsapp': '', 'contact_email': ''
    }
    for k, v in defaults.items():
        db.execute('INSERT OR IGNORE INTO app_settings(key,value) VALUES(?,?)', (k,v))
    for name, days in PLANS:
        db.execute('INSERT OR IGNORE INTO membership_plans(name,duration_days,price) VALUES(?,?,0)', (name,days))
    schedule = ['Morning · 5:00–7:00 AM','Morning · 6:00–8:00 AM','Morning · 7:00–9:00 AM','Morning · 8:00–10:00 AM','Evening · 5:00–7:00 PM','Evening · 6:00–8:00 PM','Evening · 7:00–9:00 PM','Evening · 8:00–10:00 PM']
    for offset in range(7):
        day = (date.today()+timedelta(days=offset)).isoformat()
        for label in schedule:
            db.execute('INSERT OR IGNORE INTO slots(slot_date,slot_time,capacity) VALUES(?,?,10)', (day,label))
    db.execute("""
    DELETE FROM bookings
    WHERE slot_id IN (
        SELECT id FROM slots
        WHERE slot_date < ?
    )
""", (date.today().isoformat(),))
    db.commit()

@app.before_request
def prepare_db(): init_db()

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'info'); return redirect(url_for('login'))
        if session.get('role') == 'user':
            user = get_db().execute('SELECT is_active FROM users WHERE id=?', (session['user_id'],)).fetchone()
            if not user or not user['is_active']:
                session.clear()
                flash('Your account is inactive. Please contact the gym admin.', 'error')
                return redirect(url_for('login'))
        return fn(*a, **kw)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if session.get('role') != 'admin':
            flash('Admin access is required.', 'error'); return redirect(url_for('home'))
        return fn(*a, **kw)
    return wrapper

def setting(key):
    row = get_db().execute('SELECT value FROM app_settings WHERE key=?',(key,)).fetchone()
    return row['value'] if row else ''

@app.route('/')
def home():
    db=get_db(); today=date.today().isoformat()
    slots=db.execute('''SELECT s.*, s.capacity-COUNT(b.id) available FROM slots s LEFT JOIN bookings b ON b.slot_id=s.id WHERE s.slot_date=? GROUP BY s.id ORDER BY s.id''',(today,)).fetchall()
    return render_template('index.html', slots=slots, contact_phone=setting('contact_phone'), contact_whatsapp=setting('contact_whatsapp'), contact_email=setting('contact_email'))

@app.route('/register', methods=['GET','POST'])
def register():
    flash('Accounts are created by the gym admin. Please contact the gym.', 'info')
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        username=request.form.get('username','').strip()
        password=request.form.get('password','')
        if username == setting('admin_username') and check_password_hash(setting('admin_password_hash'), password):
            session.clear(); session.update(user_id=0,name='Administrator',role='admin'); return redirect(url_for('admin'))
        user=get_db().execute('SELECT * FROM users WHERE email=?',(username.lower(),)).fetchone()
        if user and user['is_active'] and check_password_hash(user['password_hash'],password):
            session.clear(); session.update(user_id=user['id'],name=user['name'],role='user',must_change_password=user['must_change_password'])
            return redirect(url_for('change_password') if user['must_change_password'] else url_for('dashboard'))
        flash('Username or password is incorrect, or the account is inactive.','error')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); flash('You have been logged out.','info'); return redirect(url_for('home'))

@app.route('/change-password',methods=['GET','POST'])
@login_required
def change_password():
    if session.get('role')=='admin': return redirect(url_for('admin_settings'))
    if request.method=='POST':
        old=request.form.get('current_password',''); new=request.form.get('new_password','')
        user=get_db().execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone()
        if not user or not check_password_hash(user['password_hash'],old): flash('Current password is incorrect.','error')
        elif len(new)<8: flash('New password must be at least 8 characters.','error')
        else:
            get_db().execute('UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?',(generate_password_hash(new),session['user_id'])); get_db().commit()
            session['must_change_password']=0; flash('Password changed successfully.','success'); return redirect(url_for('dashboard'))
    return render_template('change_password.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if session.get('role')=='admin': return redirect(url_for('admin'))
    db=get_db()
    bookings=db.execute('SELECT b.id booking_id,s.slot_date,s.slot_time FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE b.user_id=? ORDER BY s.slot_date,s.id',(session['user_id'],)).fetchall()
    sub=db.execute('''SELECT s.*,p.name plan_name FROM subscriptions s JOIN membership_plans p ON p.id=s.plan_id WHERE s.user_id=? ORDER BY s.id DESC LIMIT 1''',(session['user_id'],)).fetchone()
    return render_template('dashboard.html',bookings=bookings,subscription=sub)

@app.route('/book/<int:slot_id>',methods=['POST'])
@login_required
def book(slot_id):
    if session.get('role')!='user': return redirect(url_for('admin'))
    db=get_db(); today=date.today().isoformat()
    sub=db.execute('''SELECT * FROM subscriptions WHERE user_id=? AND payment_status='Paid' AND end_date>=? ORDER BY end_date DESC LIMIT 1''',(session['user_id'],today)).fetchone()
    if not sub: flash('An active, paid membership is required to book a slot. Please contact the gym admin.','error'); return redirect(url_for('dashboard'))
    slot=db.execute('SELECT * FROM slots WHERE id=?',(slot_id,)).fetchone()
    if not slot or slot['slot_date']<today: flash('That slot is unavailable.','error'); return redirect(url_for('home'))
    count=db.execute('SELECT COUNT(*) FROM bookings WHERE slot_id=?',(slot_id,)).fetchone()[0]
    if count>=slot['capacity']: flash('Sorry, this slot is full.','error')
    else:
        try: db.execute('INSERT INTO bookings(user_id,slot_id) VALUES(?,?)',(session['user_id'],slot_id)); db.commit(); flash('Your gym slot is booked!','success')
        except sqlite3.IntegrityError: flash('You have already booked this slot.','info')
    return redirect(url_for('dashboard'))

@app.route('/cancel/<int:booking_id>',methods=['POST'])
@login_required
def cancel(booking_id):
    if session.get('role')!='user': return redirect(url_for('admin'))
    db=get_db(); db.execute('DELETE FROM bookings WHERE id=? AND user_id=?',(booking_id,session['user_id'])); db.commit(); flash('Booking cancelled (if it belonged to your account).','info'); return redirect(url_for('dashboard'))

@app.route('/admin')
@login_required
@admin_required
def admin():
    db=get_db()
    rows=db.execute('SELECT u.name,u.email,s.slot_date,s.slot_time,b.booked_at FROM bookings b JOIN users u ON u.id=b.user_id JOIN slots s ON s.id=b.slot_id ORDER BY s.slot_date DESC,s.id').fetchall()
    members=db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    active=db.execute('SELECT COUNT(*) FROM users WHERE is_active=1').fetchone()[0]
    return render_template('admin.html',rows=rows,total_users=members,active_users=active,total_bookings=db.execute('SELECT COUNT(*) FROM bookings').fetchone()[0])

@app.route('/admin/members')
@login_required
@admin_required
def members():
    q=request.args.get('q','').strip(); db=get_db()
    members=db.execute('SELECT u.*, (SELECT p.name FROM subscriptions s JOIN membership_plans p ON p.id=s.plan_id WHERE s.user_id=u.id ORDER BY s.id DESC LIMIT 1) plan_name, (SELECT s.payment_status FROM subscriptions s WHERE s.user_id=u.id ORDER BY s.id DESC LIMIT 1) payment_status FROM users u WHERE u.name LIKE ? OR u.email LIKE ? ORDER BY u.created_at DESC', (f'%{q}%',f'%{q}%')).fetchall()
    return render_template('members.html',members=members,q=q)

@app.route('/admin/members/create',methods=['GET','POST'])
@login_required
@admin_required
def create_member():
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        if not name or not email or len(password)<8: flash('Enter name, valid email/username and a password of at least 8 characters.','error')
        else:
            try:
                get_db().execute('INSERT INTO users(name,email,password_hash,must_change_password) VALUES(?,?,?,1)',(name,email,generate_password_hash(password))); get_db().commit(); flash('Member account created. Ask the member to change the temporary password at first login.','success'); return redirect(url_for('members'))
            except sqlite3.IntegrityError: flash('That username/email already exists.','error')
    return render_template('member_form.html')

@app.route('/admin/members/<int:user_id>/status',methods=['POST'])
@login_required
@admin_required
def toggle_member(user_id):
    db=get_db(); user=db.execute('SELECT is_active FROM users WHERE id=?',(user_id,)).fetchone()
    if user:
        db.execute('UPDATE users SET is_active=? WHERE id=?',(0 if user['is_active'] else 1,user_id)); db.commit(); flash('Member status updated.','success')
    return redirect(url_for('members'))
@app.route('/admin/members/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_member(user_id):
    db = get_db()

    user = db.execute(
        'SELECT id FROM users WHERE id=?',
        (user_id,)
    ).fetchone()

    if user:
        db.execute(
            'DELETE FROM subscriptions WHERE user_id=?',
            (user_id,)
        )

        db.execute(
            'DELETE FROM users WHERE id=?',
            (user_id,)
        )

        db.commit()
        flash('Member and their bookings deleted successfully.', 'success')

    return redirect(url_for('members'))

@app.route('/admin/subscriptions')
@login_required
@admin_required
def subscriptions():
    db=get_db(); plans=db.execute('SELECT * FROM membership_plans ORDER BY id').fetchall()
    rows=db.execute('''SELECT s.*,u.name,u.email,p.name plan_name FROM subscriptions s JOIN users u ON u.id=s.user_id JOIN membership_plans p ON p.id=s.plan_id ORDER BY s.created_at DESC''').fetchall()
    member_list=db.execute('SELECT id,name,email FROM users WHERE is_active=1 ORDER BY name').fetchall()
    return render_template('subscriptions.html',plans=plans,rows=rows,members=member_list,today=date.today().isoformat())

@app.route('/admin/plans/<int:plan_id>',methods=['POST'])
@login_required
@admin_required
def update_plan(plan_id):
    try: price=float(request.form.get('price',''))
    except ValueError: price=-1
    if price<0: flash('Enter a valid non-negative price.','error')
    else: get_db().execute('UPDATE membership_plans SET price=? WHERE id=?',(price,plan_id)); get_db().commit(); flash('Plan price updated.','success')
    return redirect(url_for('subscriptions'))

@app.route('/admin/subscriptions/assign',methods=['POST'])
@login_required
@admin_required
def assign_subscription():
    db=get_db(); user_id=request.form.get('user_id',type=int); plan_id=request.form.get('plan_id',type=int); start=request.form.get('start_date') or date.today().isoformat()
    plan=db.execute('SELECT * FROM membership_plans WHERE id=?',(plan_id,)).fetchone()
    if not user_id or not plan or plan['price']<=0: flash('Select a member and a plan with a price set by admin.','error')
    else:
        end=(date.fromisoformat(start)+timedelta(days=plan['duration_days']-1)).isoformat()
        db.execute('INSERT INTO subscriptions(user_id,plan_id,start_date,end_date,amount,payment_status) VALUES(?,?,?,?,?,\'Unpaid\')',(user_id,plan_id,start,end,plan['price'])); db.commit(); flash('Membership assigned. Fees status is Unpaid until admin records payment.','success')
    return redirect(url_for('subscriptions'))

@app.route('/admin/subscriptions/<int:sub_id>/paid',methods=['POST'])
@login_required
@admin_required
def mark_paid(sub_id):
    method=request.form.get('payment_method','Cash')
    if method not in ('Cash','UPI'): method='Cash'
    get_db().execute("UPDATE subscriptions SET payment_status='Paid',payment_method=? WHERE id=?",(method,sub_id)); get_db().commit(); flash('Fees marked as Paid.','success'); return redirect(url_for('subscriptions'))

@app.route('/admin/settings',methods=['GET','POST'])
@login_required
@admin_required
def admin_settings():
    db=get_db()
    if request.method=='POST':
        if request.form.get('form_type')=='contact':
            for key, field in [('contact_phone','phone'),('contact_whatsapp','whatsapp'),('contact_email','email')]: db.execute('INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,request.form.get(field,'').strip()))
            db.commit(); flash('Contact details updated.','success')
        elif request.form.get('form_type')=='credentials':
            current=request.form.get('current_password',''); new_user=request.form.get('username','').strip(); new_pass=request.form.get('new_password','')
            if not check_password_hash(setting('admin_password_hash'),current): flash('Current admin password is incorrect.','error')
            elif not new_user or (new_pass and len(new_pass)<8): flash('Enter a username and a password of at least 8 characters.','error')
            else:
                db.execute('UPDATE app_settings SET value=? WHERE key=?',(new_user,'admin_username'))
                if new_pass: db.execute('UPDATE app_settings SET value=? WHERE key=?',(generate_password_hash(new_pass),'admin_password_hash'))
                db.commit(); session.clear(); flash('Admin login details updated. Please log in again.','success'); return redirect(url_for('login'))
    return render_template('admin_settings.html',phone=setting('contact_phone'),whatsapp=setting('contact_whatsapp'),email=setting('contact_email'),username=setting('admin_username'))

if __name__=='__main__': app.run(host='0.0.0.0',port=5000,debug=True)
