"""
SERGIOS HOTEL — Pool Management App
Backend: Flask + SQLite + Microsoft 365 SMTP
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date
import os, json, base64, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

app = Flask(__name__)

# Ρυθμίσεις
app.secret_key = os.environ.get('SECRET_KEY', 'sergios-pool-secret-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///pool.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

# Microsoft 365 SMTP ρυθμίσεις
SMTP_SERVER   = 'condian.gr'
SMTP_PORT     = 465
EMAIL_FROM    = os.environ.get('EMAIL_FROM', 'report@condian.gr')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_TO_LIST = [
    'dimitris@condianhotels.gr',
    'm.xypakis@condianhotels.gr',
    'g.giakoumakis@condianhotels.gr'
]
HOTEL_NAME = 'Sergios Hotel'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Μοντέλα
class User(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    username   = db.Column(db.String(50), unique=True, nullable=False)
    password   = db.Column(db.String(200), nullable=False)
    full_name  = db.Column(db.String(100), nullable=False)
    role       = db.Column(db.String(20), default='staff')
    language   = db.Column(db.String(5), default='el')
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DailyRecord(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    record_date    = db.Column(db.Date, default=date.today, nullable=False)
    recorded_at    = db.Column(db.DateTime, default=datetime.utcnow)
    ph             = db.Column(db.Float)
    alkalinity     = db.Column(db.Float)
    free_chlorine  = db.Column(db.Float)
    total_chlorine = db.Column(db.Float)
    cya            = db.Column(db.Float)
    water_temp     = db.Column(db.Float)
    swimmers       = db.Column(db.Integer)
    clarity        = db.Column(db.String(20))
    algicide_done  = db.Column(db.Boolean, default=False)
    recommendations = db.Column(db.Text)
    check_walls     = db.Column(db.Boolean, default=False)
    check_backwash  = db.Column(db.Boolean, default=False)
    check_pump      = db.Column(db.Boolean, default=False)
    check_skimmer   = db.Column(db.Boolean, default=False)
    check_waterline = db.Column(db.Boolean, default=False)
    check_prefilter = db.Column(db.Boolean, default=False)
    photo_filename  = db.Column(db.String(200))
    notes           = db.Column(db.Text)
    user = db.relationship('User', backref='records')

def calculate_chemicals(ph, alk, fc, tc, cya, water_temp, swimmers, clarity, algicide_done):
    VOL = 90
    AIR_TEMP = 26.0
    results = []
    high_temp   = (AIR_TEMP > 25) or (water_temp and water_temp > 28)
    high_load   = (swimmers and swimmers > 40) or high_temp
    combined    = max(0, (tc or 0) - (fc or 0)) if tc and fc else 0
    min_fc      = max(2.0, (cya or 0) * 0.075) if cya else 2.0
    needs_shock = combined > 0.5 or clarity in ['cloudy', 'green']

    if ph:
        if ph > 7.8:
            dose = round((ph - 7.4) * VOL * 0.18)
            results.append({'product': 'pH-', 'dose': f'{dose} g', 'note': f'Μειωσε pH {ph} -> 7.4. Βραδυ η πρωι (2h πριν ανοιξει).', 'type': 'success'})
        elif ph < 7.2:
            dose = round((7.4 - ph) * VOL * 0.14)
            results.append({'product': 'pH+', 'dose': f'{dose} g', 'note': f'Ανυψωσε pH {ph} -> 7.4.', 'type': 'info'})

    if cya:
        if cya > 70:
            results.append({'product': 'CYA - Αραιωση νερου', 'dose': '-', 'note': f'CYA {cya} mg/L - αδειασε μερος νερου και αναπληρωσε με φρεσκο.', 'type': 'danger'})
        elif cya < 30:
            results.append({'product': 'CYA χαμηλο', 'dose': '-', 'note': f'CYA {cya} mg/L - οι ταμπλετες θα το ανεβασουν σταδιακα.', 'type': 'warning'})

    if fc is not None:
        if needs_shock:
            dose = VOL * 10
            reasons = []
            if combined > 0.5: reasons.append(f'δεσμευμενο χλωριο {combined:.2f} mg/L')
            if clarity == 'cloudy': reasons.append('θολο νερο')
            if clarity == 'green': reasons.append('αλγη')
            results.append({'product': 'Astral Trichloro Powder - SHOCK', 'dose': f'{dose} g', 'note': f'Λογω: {", ".join(reasons)}. Διαλυσε σε νερο, ριξε στην πισινα. Βραδυ, χωρις κολυμβητες. Εισοδος μετα 12-14 ωρες.', 'type': 'danger'})
        else:
            tabs = 2 if (fc < min_fc or high_load) else 1
            reason = f'Free Chlorine {fc} mg/L' if fc < min_fc else ('υψηλο φορτιο/θερμοκρ.' if high_load else 'maintenance')
            results.append({'product': 'Aqua Clor Ταμπλετες 200g', 'dose': f'{tabs} τεμ.', 'note': f'{reason}. {"1 ταμπλετα σε καθε skimmer." if tabs==2 else "1 ταμπλετα σε εναν skimmer."}', 'type': 'info'})

    if alk:
        if alk < 80:
            dose = round((80 - alk) * VOL * 0.015)
            results.append({'product': 'Sodium Bicarbonate', 'dose': f'{dose} g', 'note': f'Alkalinity {alk} -> στοχος 80-120 mg/L.', 'type': 'warning'})
        elif alk > 150:
            results.append({'product': 'Alkalinity υψηλη', 'dose': '-', 'note': f'Alkalinity {alk} mg/L - μειωσε με pH-.', 'type': 'danger'})

    if not algicide_done:
        dose = round(375 * VOL / 50)
        results.append({'product': 'Aqua Clor Algicide Super', 'dose': f'{dose} ml', 'note': 'Εβδομαδιαια δοση. Τελος ημερησιας χρησης, κοντα στις εισοδους νερου.', 'type': 'success'})

    if not results:
        results.append({'product': 'Ολα εντος οριων!', 'dose': '-', 'note': 'Δεν απαιτειται καμια ενεργεια σημερα.', 'type': 'ok'})

    return results

def send_report_email(record, user, recommendations, photo_path=None):
    if not EMAIL_PASSWORD:
        print("Email password δεν εχει οριστει")
        return False

    checklist_items = {
        'Καθαρισμος τοιχιων/πυθμενα': record.check_walls,
        'Backwash φιλτρου': record.check_backwash,
        'Ελεγχος αντλιας': record.check_pump,
        'Ελεγχος skimmer': record.check_skimmer,
        'Καθαρισμος ισαλης γραμμης': record.check_waterline,
        'Καθαρισμος προφιλτρων': record.check_prefilter,
    }

    recs_html = ''.join([
        f'<tr style="border-bottom:1px solid #eee;">'
        f'<td style="padding:8px;font-weight:500;">{r["product"]}</td>'
        f'<td style="padding:8px;">{r["dose"]}</td>'
        f'<td style="padding:8px;color:#666;">{r["note"]}</td>'
        f'</tr>' for r in recommendations
    ])

    chk_html = ''.join([
        f'<tr><td style="padding:6px;">{"OK" if v else "X"} {k}</td></tr>'
        for k, v in checklist_items.items()
    ])

    combined = max(0, (record.total_chlorine or 0) - (record.free_chlorine or 0))

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
      <div style="background:#185FA5;color:white;padding:20px;border-radius:8px 8px 0 0;">
        <h1 style="margin:0;font-size:20px;">Sergios Hotel - Ημερησιο Report Πισινας</h1>
        <p style="margin:5px 0 0;opacity:0.8;">{record.record_date.strftime('%d/%m/%Y')} | Υπευθυνος: {user.full_name}</p>
      </div>
      <div style="background:#f9f9f9;padding:20px;border:1px solid #eee;">
        <h2 style="font-size:15px;color:#333;border-bottom:2px solid #185FA5;padding-bottom:6px;">Μετρησεις Pool Line</h2>
        <table style="width:100%;border-collapse:collapse;">
          <tr><td style="padding:8px;border:1px solid #eee;"><b>pH</b></td><td style="padding:8px;border:1px solid #eee;">{record.ph or '-'}</td><td style="padding:8px;border:1px solid #eee;color:#888;">Στοχος: 7.2-7.8</td></tr>
          <tr><td style="padding:8px;border:1px solid #eee;"><b>Free Chlorine</b></td><td style="padding:8px;border:1px solid #eee;">{record.free_chlorine or '-'} mg/L</td><td style="padding:8px;border:1px solid #eee;color:#888;">Στοχος: 2.0-3.0</td></tr>
          <tr><td style="padding:8px;border:1px solid #eee;"><b>Total Chlorine</b></td><td style="padding:8px;border:1px solid #eee;">{record.total_chlorine or '-'} mg/L</td><td style="padding:8px;border:1px solid #eee;color:#888;">>= Free Chlorine</td></tr>
          <tr><td style="padding:8px;border:1px solid #eee;"><b>Δεσμευμενο χλωριο</b></td><td style="padding:8px;border:1px solid #eee;">{combined:.2f} mg/L</td><td style="padding:8px;border:1px solid #eee;color:#888;">Πρεπει: &lt; 0.5</td></tr>
          <tr><td style="padding:8px;border:1px solid #eee;"><b>Alkalinity</b></td><td style="padding:8px;border:1px solid #eee;">{record.alkalinity or '-'} mg/L</td><td style="padding:8px;border:1px solid #eee;color:#888;">Στοχος: 80-120</td></tr>
          <tr><td style="padding:8px;border:1px solid #eee;"><b>CYA</b></td><td style="padding:8px;border:1px solid #eee;">{record.cya or '-'} mg/L</td><td style="padding:8px;border:1px solid #eee;color:#888;">Στοχος: 30-50</td></tr>
          <tr><td style="padding:8px;border:1px solid #eee;"><b>Θερμοκρ. νερου</b></td><td style="padding:8px;border:1px solid #eee;">{record.water_temp or '-'} C</td><td style="padding:8px;border:1px solid #eee;"></td></tr>
          <tr><td style="padding:8px;border:1px solid #eee;"><b>Κολυμβητες</b></td><td style="padding:8px;border:1px solid #eee;">{record.swimmers or '-'}</td><td style="padding:8px;border:1px solid #eee;"></td></tr>
        </table>
        <h2 style="font-size:15px;color:#333;border-bottom:2px solid #185FA5;padding-bottom:6px;margin-top:20px;">Συστασεις χημικων</h2>
        <table style="width:100%;border-collapse:collapse;">
          <tr style="background:#185FA5;color:white;"><th style="padding:8px;text-align:left;">Χημικο</th><th style="padding:8px;text-align:left;">Δοση</th><th style="padding:8px;text-align:left;">Σημειωση</th></tr>
          {recs_html}
        </table>
        <h2 style="font-size:15px;color:#333;border-bottom:2px solid #185FA5;padding-bottom:6px;margin-top:20px;">Checklist εργασιων</h2>
        <table style="width:100%;border-collapse:collapse;">{chk_html}</table>
        {"<h2 style='font-size:15px;color:#333;margin-top:20px;'>Παρατηρησεις</h2><p style='background:#fff;padding:12px;border:1px solid #eee;border-radius:4px;'>" + (record.notes or '-') + "</p>" if record.notes else ""}
      </div>
      <div style="background:#f0f0f0;padding:12px;text-align:center;font-size:12px;color:#888;border-radius:0 0 8px 8px;">
        Sergios Hotel - Διαχειριση Πισινας - {record.record_date.strftime('%d/%m/%Y')}
      </div>
    </div>
    """

    try:
        msg = MIMEMultipart()
        msg['From']    = EMAIL_FROM
        msg['To']      = ', '.join(EMAIL_TO_LIST)
        msg['Subject'] = f'Sergios Hotel - Report Πισινας {record.record_date.strftime("%d/%m/%Y")}'
        msg.attach(MIMEText(html, 'html', 'utf-8'))

        if photo_path and os.path.exists(photo_path):
            with open(photo_path, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename=pool_{record.record_date}.jpg')
                msg.attach(part)

        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO_LIST, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f'Email error: {e}')
        return False

@app.route('/')
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user and user.role == 'admin':
            return redirect(url_for('dashboard'))
        return redirect(url_for('pool_app'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, is_active=True).first()
        if user and check_password_hash(user.password, password):
            session['user_id']   = user.id
            session['user_name'] = user.full_name
            session['user_role'] = user.role
            session['language']  = user.language
            return redirect(url_for('dashboard') if user.role == 'admin' else url_for('pool_app'))
        error = 'Λαθος username η password'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/app')
def pool_app():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    today_record = DailyRecord.query.filter_by(user_id=user.id, record_date=date.today()).first()
    return render_template('app.html', user=user, today_record=today_record)

@app.route('/submit', methods=['POST'])
def submit():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Μη εξουσιοδοτημενο'}), 401

    user = User.query.get(session['user_id'])
    data = request.form

    photo_filename = None
    photo_path = None
    if 'photo' in request.files:
        photo = request.files['photo']
        if photo and photo.filename:
            ext = photo.filename.rsplit('.', 1)[-1].lower()
            if ext in ['jpg', 'jpeg', 'png', 'heic']:
                photo_filename = f"pool_{user.id}_{date.today()}_{int(datetime.utcnow().timestamp())}.{ext}"
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(photo_filename))
                photo.save(photo_path)

    def flt(key): return float(data[key]) if data.get(key) else None
    def nt(key):  return int(data[key]) if data.get(key) else None
    def bl(key):  return data.get(key) == 'true'

    ph   = flt('ph'); alk  = flt('alkalinity'); fc   = flt('free_chlorine')
    tc   = flt('total_chlorine'); cya  = flt('cya'); wt   = flt('water_temp')
    sw   = nt('swimmers'); cl   = data.get('clarity', ''); algd = bl('algicide_done')

    recommendations = calculate_chemicals(ph, alk, fc, tc, cya, wt, sw, cl, algd)

    record = DailyRecord(
        user_id=user.id, record_date=date.today(),
        ph=ph, alkalinity=alk, free_chlorine=fc, total_chlorine=tc,
        cya=cya, water_temp=wt, swimmers=sw, clarity=cl, algicide_done=algd,
        recommendations=json.dumps(recommendations, ensure_ascii=False),
        check_walls=bl('check_walls'), check_backwash=bl('check_backwash'),
        check_pump=bl('check_pump'), check_skimmer=bl('check_skimmer'),
        check_waterline=bl('check_waterline'), check_prefilter=bl('check_prefilter'),
        photo_filename=photo_filename, notes=data.get('notes', '')
    )
    db.session.add(record)
    db.session.commit()

    email_sent = send_report_email(record, user, recommendations, photo_path)

    return jsonify({
        'success': True,
        'message': 'Καταγραφη αποθηκευτηκε!' + (' Email απεσταλη.' if email_sent else ''),
        'recommendations': recommendations
    })

@app.route('/set-language/<lang>')
def set_language(lang):
    if lang in ['el', 'en'] and 'user_id' in session:
        session['language'] = lang
        user = User.query.get(session['user_id'])
        if user:
            user.language = lang
            db.session.commit()
    return redirect(request.referrer or url_for('pool_app'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session or session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    records = DailyRecord.query.order_by(DailyRecord.record_date.desc()).limit(30).all()
    users   = User.query.filter_by(is_active=True).all()
    today   = DailyRecord.query.filter_by(record_date=date.today()).first()
    return render_template('dashboard.html', records=records, users=users, today=today)

@app.route('/dashboard/add-user', methods=['POST'])
def add_user():
    if session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    data = request.form
    existing = User.query.filter_by(username=data['username']).first()
    if existing:
        return redirect(url_for('dashboard') + '?error=exists')
    user = User(
        username=data['username'],
        password=generate_password_hash(data['password']),
        full_name=data['full_name'],
        role=data.get('role', 'staff'),
        language=data.get('language', 'el')
    )
    db.session.add(user)
    db.session.commit()
    return redirect(url_for('dashboard') + '?success=user_added')

@app.route('/dashboard/delete-user/<int:user_id>')
def delete_user(user_id):
    if session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    user = User.query.get(user_id)
    if user and user.role != 'admin':
        user.is_active = False
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/api/history')
def api_history():
    if 'user_id' not in session:
        return jsonify([])
    records = DailyRecord.query.order_by(DailyRecord.record_date.desc()).limit(14).all()
    return jsonify([{
        'date': r.record_date.strftime('%d/%m'),
        'ph': r.ph, 'fc': r.free_chlorine,
        'alk': r.alkalinity, 'cya': r.cya
    } for r in records if r.ph or r.free_chlorine])

def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(username='admin', password=generate_password_hash('sergios2024'), full_name='Δημητρης Γιαννουλακης', role='admin', language='el'))
            db.session.add(User(username='giannhs', password=generate_password_hash('pool2024'), full_name='Γιαννης Γιακουμακης', role='admin', language='el'))
            db.session.commit()
            print('Βαση δεδομενων και χρηστες δημιουργηθηκαν')

if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
