"""
CONDIAN HOTELS - Water & Pool Log App v4
Backend: Flask + PostgreSQL + SMTP + AI Assistant

Modules:
  - Water Log (νερά χρήσης) — single hotel (Sergios)
  - Pool Log (πισίνες) — multi-hotel / multi-pool
  - AI Pool Assistant (Βοηθός Πισίνας) — provider-agnostic (Anthropic/OpenAI)
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text
from datetime import datetime, date, timedelta
import os, smtplib, threading, json, time, urllib.request, urllib.error
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'sergios-water-secret-2024')

# Railway/Heroku δίνουν 'postgres://' — η SQLAlchemy 2.x θέλει 'postgresql://'
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///water.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

SMTP_SERVER    = 'condian.gr'
SMTP_PORT      = 465
EMAIL_FROM     = os.environ.get('EMAIL_FROM', 'report@condian.gr')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_TO_LIST  = ['dimitris@condianhotels.gr', 'm.xypakis@condianhotels.gr', 'g.giakoumakis@condianhotels.gr']
HOTEL_NAME     = 'Sergios Hotel'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REG_CODE = os.environ.get('REG_CODE', 'condian2026')          # κωδικός εγγραφής προσωπικού
ENABLE_SCHEDULER = os.environ.get('ENABLE_SCHEDULER', 'true').lower() in ('1','true','yes','on')
REMINDER_HOUR = int(os.environ.get('REMINDER_HOUR', '18'))    # ώρα υπενθύμισης (Europe/Athens)

# ── AI Assistant config (provider-agnostic) ──
AI_PROVIDER       = os.environ.get('AI_PROVIDER', 'auto')   # auto | anthropic | openai
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
OPENAI_API_KEY    = os.environ.get('OPENAI_API_KEY', '')
AI_MODEL          = os.environ.get('AI_MODEL', '')          # override; αλλιώς default ανά πάροχο

POOL_ASSISTANT_PROMPT = """Είσαι ο «Βοηθός Πισίνας», ψηφιακός βοηθός στην εφαρμογή διαχείρισης του ξενοδοχείου.
Βοηθάς το προσωπικό συντήρησης και τους υπεύθυνους βάρδιας στην ασφαλή, καθαρή και
νόμιμη καθημερινή λειτουργία των πισινών.
# ΑΡΜΟΔΙΟΤΗΤΕΣ
- Χημεία νερού: ερμηνεία μετρήσεων (pH, ελεύθερο/ολικό χλώριο, αλκαλικότητα,
  κυανουρικό οξύ, σκληρότητα ασβεστίου, θερμοκρασία) και προτάσεις διόρθωσης.
- Δοσολογία χημικών: υπολογισμός ποσότητας με βάση τον όγκο κάθε πισίνας και την
  απόκλιση από τις επιθυμητές τιμές.
- Πρόγραμμα καθαρισμού: skimming, βούρτσισμα, σκούπισμα πυθμένα, καθαρισμός
  καλαθιών skimmer/προφίλτρου, backwash φίλτρων.
- Έλεγχοι εξοπλισμού: αντλίες, κυκλοφορία, στάθμη νερού, πίεση φίλτρων, διαρροές.
- Ασφάλεια & συμμόρφωση: διαύγεια νερού, σήμανση, βάθη, ναυαγοσώστης, τήρηση
  αρχείου μετρήσεων.
- Ημερολόγιο: καταγραφή μετρήσεων και ενεργειών ανά βάρδια και ανά πισίνα.
# ΛΕΙΤΟΥΡΓΙΑ
1. Ρώτα πρώτα ποια πισίνα αφορά και ζήτα τις τρέχουσες μετρήσεις αν δεν τις έχεις.
2. Δίνε σαφή, πρακτικά βήματα — «τι να κάνω τώρα», όχι θεωρία.
3. Στη δοσολογία δείξε όγκο, απόκλιση και τελική ποσότητα προϊόντος. Πάντα
   επιβεβαίωνε τον όγκο της πισίνας.
4. Σήμανε ως ΕΠΕΙΓΟΝ ό,τι είναι εκτός ορίων (χλώριο, θολό νερό, βλάβη αντλίας).
5. Αν μια τιμή ήταν προβληματική νωρίτερα, υπενθύμισε επανέλεγχο.
# ΟΡΙΑ ΑΣΦΑΛΕΙΑΣ
- Δεν αντικαθιστάς πιστοποιημένο τεχνικό ή τη νομοθεσία· τα όρια τιμών διαφέρουν
  ανά περιοχή — σύστησε επαλήθευση με τους τοπικούς υγειονομικούς κανονισμούς.
- Σε σοβαρά περιστατικά (υπερδοσολογία, ηλεκτρικό πρόβλημα, ατύχημα) δώσε άμεση
  οδηγία ασφαλείας, σύστησε κλείσιμο πισίνας και ειδοποίηση υπευθύνου.
- ΠΟΤΕ μην προτείνεις ανάμειξη χλωρίου με οξέα ή χημικών μεταξύ τους.
# ΥΦΟΣ
- Σύντομος, πρακτικός, απλή γλώσσα για προσωπικό βάρδιας.
- Checklists για ελέγχους και προγράμματα.
- Στο τέλος κάθε αναφοράς, πρότεινε τι να καταγραφεί στο log."""

db = SQLAlchemy(app)

# ──────────────────────────────────────────────────────────────────────────
#  POOL LIMITS  (min, max) — None means no limit on that side.
# ──────────────────────────────────────────────────────────────────────────
POOL_LIMITS = {
    'free_chlorine':     (0.4, 1.5),
    'combined_chlorine': (None, 0.5),
    'ph':                (7.2, 7.8),
    'temp':              (None, 32.0),
    'turbidity':         (None, 1.0),
    'cyanuric_acid':     (None, 75.0),
    'total_alkalinity':  (80.0, 120.0),
    'orp':               (650.0, None),
}

# ──────────────────────────────────────────────────────────────────────────
#  MODELS
# ──────────────────────────────────────────────────────────────────────────
class User(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    username   = db.Column(db.String(50), unique=True, nullable=False)
    password   = db.Column(db.String(200), nullable=False)
    full_name  = db.Column(db.String(100), nullable=False)
    role       = db.Column(db.String(20), default='staff')
    language   = db.Column(db.String(5), default='el')
    email      = db.Column(db.String(120))
    phone      = db.Column(db.String(40))
    approved   = db.Column(db.Boolean, default=True)
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class WaterRecord(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    record_date = db.Column(db.Date, default=date.today, nullable=False)
    period      = db.Column(db.String(10), nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, nullable=True)
    updated_by  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    clo2_tank        = db.Column(db.Float)
    clo2_kitchen     = db.Column(db.Float)
    clo2_remote      = db.Column(db.Float)
    clo2_dhw_out     = db.Column(db.Float)
    clo2_dhw_return  = db.Column(db.Float)
    clo2_ro          = db.Column(db.Float)
    location_kitchen = db.Column(db.String(100))
    location_remote  = db.Column(db.String(100))
    temp_tank         = db.Column(db.Float)
    temp_dhw_out      = db.Column(db.Float)
    temp_dhw_return   = db.Column(db.Float)
    temp_ro           = db.Column(db.Float)
    temp_kitchen_cold = db.Column(db.Float)
    temp_kitchen_hot  = db.Column(db.Float)
    temp_remote_cold  = db.Column(db.Float)
    temp_remote_hot   = db.Column(db.Float)
    ph_tank = db.Column(db.Float)
    notes   = db.Column(db.Text)
    user         = db.relationship('User', foreign_keys=[user_id], backref='water_records')
    updated_user = db.relationship('User', foreign_keys=[updated_by])

class Hotel(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), unique=True, nullable=False)
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    pools = db.relationship('Pool', backref='hotel', order_by='Pool.name')

class Pool(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    hotel_id   = db.Column(db.Integer, db.ForeignKey('hotel.id'), nullable=False)
    name       = db.Column(db.String(120), nullable=False)
    location   = db.Column(db.String(120))
    pool_type  = db.Column(db.String(20), default='pool')
    volume_m3  = db.Column(db.Float)          # όγκος σε m³ (για δοσολογία)
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PoolRecord(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    pool_id     = db.Column(db.Integer, db.ForeignKey('pool.id'), nullable=False)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    record_date = db.Column(db.Date, default=date.today, nullable=False)
    period      = db.Column(db.String(10), nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, nullable=True)
    updated_by  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    free_chlorine     = db.Column(db.Float)
    combined_chlorine = db.Column(db.Float)
    ph                = db.Column(db.Float)
    temp              = db.Column(db.Float)
    turbidity         = db.Column(db.Float)
    cyanuric_acid     = db.Column(db.Float)
    total_alkalinity  = db.Column(db.Float)
    orp               = db.Column(db.Float)
    backwash_done     = db.Column(db.Boolean, default=False)
    notes             = db.Column(db.Text)
    pool         = db.relationship('Pool')
    user         = db.relationship('User', foreign_keys=[user_id])
    updated_user = db.relationship('User', foreign_keys=[updated_by])


class ReminderSent(db.Model):
    day = db.Column(db.String(10), primary_key=True)        # 'YYYY-MM-DD' lock ανά ημέρα
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)


def flt(data, key):
    try:
        return float(data[key]) if data.get(key) not in (None, '') else None
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────────────────────────────────
#  WATER LOG
# ──────────────────────────────────────────────────────────────────────────
def apply_record(record, data, period):
    record.clo2_tank        = flt(data, 'clo2_tank')
    record.clo2_kitchen     = flt(data, 'clo2_kitchen')
    record.clo2_remote      = flt(data, 'clo2_remote')
    record.location_kitchen = data.get('location_kitchen', '')
    record.location_remote  = data.get('location_remote', '')
    record.temp_tank        = flt(data, 'temp_tank')
    record.temp_dhw_out     = flt(data, 'temp_dhw_out')
    record.temp_dhw_return  = flt(data, 'temp_dhw_return')
    record.temp_ro          = flt(data, 'temp_ro')
    record.temp_kitchen_cold = flt(data, 'temp_kitchen_cold')
    record.temp_kitchen_hot  = flt(data, 'temp_kitchen_hot')
    record.temp_remote_cold  = flt(data, 'temp_remote_cold')
    record.temp_remote_hot   = flt(data, 'temp_remote_hot')
    record.notes = data.get('notes', '')
    if period == 'morning':
        record.clo2_dhw_out    = flt(data, 'clo2_dhw_out')
        record.clo2_dhw_return = flt(data, 'clo2_dhw_return')
        record.clo2_ro         = flt(data, 'clo2_ro')
        record.ph_tank         = flt(data, 'ph_tank')

def send_report_email(record, user):
    if not EMAIL_PASSWORD:
        return False
    period_gr = 'Πρωι' if record.period == 'morning' else 'Απογευμα'
    def row(label, val, unit='', min_v=None, max_v=None):
        if val is None:
            return f'<tr><td style="padding:7px 8px;border:1px solid #eee;">{label}</td><td style="padding:7px 8px;border:1px solid #eee;">-</td><td style="padding:7px 8px;border:1px solid #eee;color:#888;">{unit}</td></tr>'
        ok = (min_v is None or val >= min_v) and (max_v is None or val <= max_v)
        color = '#16a34a' if ok else '#dc2626'
        icon  = 'OK' if ok else 'ΠΡΟΣΟΧΗ'
        limit = f'min {min_v}{unit}' if min_v else (f'max {max_v}{unit}' if max_v else '')
        return f'<tr><td style="padding:7px 8px;border:1px solid #eee;">{label}</td><td style="padding:7px 8px;border:1px solid #eee;color:{color};font-weight:500;">{icon}: {val} {unit}</td><td style="padding:7px 8px;border:1px solid #eee;color:#888;">{limit}</td></tr>'
    loc_kit = f' ({record.location_kitchen})' if record.location_kitchen else ''
    loc_rem = f' ({record.location_remote})' if record.location_remote else ''
    clo2_rows  = row('Δεξαμενη', record.clo2_tank, 'ppm', 1.0, 2.0)
    clo2_rows += row(f'Κουζινα{loc_kit}', record.clo2_kitchen, 'ppm', 1.0, 2.0)
    clo2_rows += row(f'Απομακρυσμενο{loc_rem}', record.clo2_remote, 'ppm', 1.0, 2.0)
    if record.period == 'morning':
        clo2_rows += row('Αναχωρηση ΖΝΧ', record.clo2_dhw_out, 'ppm', 1.0, 2.0)
        clo2_rows += row('Επιστροφη ΖΝΧ', record.clo2_dhw_return, 'ppm', 1.0, 2.0)
        clo2_rows += row('Αντ. Οσμωση', record.clo2_ro, 'ppm', 1.0, 2.0)
    temp_rows  = row('Δεξαμενη', record.temp_tank, 'C', None, 20.0)
    temp_rows += row('Κολεκτερ ΖΝΧ (Αναχ.)', record.temp_dhw_out, 'C', 60.0, None)
    temp_rows += row('Κολεκτερ Ανακυκλ. (Επιστρ.)', record.temp_dhw_return, 'C', 50.0, None)
    temp_rows += row('Αντ. Οσμωση', record.temp_ro, 'C')
    temp_rows += row(f'Κουζινα Κρυο{loc_kit}', record.temp_kitchen_cold, 'C')
    temp_rows += row(f'Κουζινα Ζεστο{loc_kit}', record.temp_kitchen_hot, 'C', 50.0, None)
    temp_rows += row(f'Απομακρυσμενο Κρυο{loc_rem}', record.temp_remote_cold, 'C')
    temp_rows += row(f'Απομακρυσμενο Ζεστο{loc_rem}', record.temp_remote_hot, 'C', 50.0, None)
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;">
      <div style="background:#0369a1;color:white;padding:20px;border-radius:8px 8px 0 0;">
        <h1 style="margin:0;font-size:20px;">Sergios Hotel - Water Log {period_gr}</h1>
        <p style="margin:5px 0 0;opacity:0.8;">{record.record_date.strftime('%d/%m/%Y')} | Υπευθυνος: {user.full_name}</p>
      </div>
      <div style="background:#f9f9f9;padding:20px;border:1px solid #eee;">
        <h2 style="font-size:15px;color:#333;border-bottom:2px solid #0369a1;padding-bottom:6px;">CLO2 (ppm) - Στοχος: 1.0-2.0 ppm</h2>
        <table style="width:100%;border-collapse:collapse;">
          <tr style="background:#0369a1;color:white;"><th style="padding:8px;text-align:left;">Σημειο</th><th style="padding:8px;text-align:left;">Μετρηση</th><th style="padding:8px;text-align:left;">Ορια</th></tr>
          {clo2_rows}
        </table>
        <h2 style="font-size:15px;color:#333;border-bottom:2px solid #0369a1;padding-bottom:6px;margin-top:20px;">Θερμοκρασια (C)</h2>
        <table style="width:100%;border-collapse:collapse;">
          <tr style="background:#0369a1;color:white;"><th style="padding:8px;text-align:left;">Σημειο</th><th style="padding:8px;text-align:left;">Μετρηση</th><th style="padding:8px;text-align:left;">Ορια</th></tr>
          {temp_rows}
        </table>
        {f'<h2 style="font-size:15px;color:#333;margin-top:20px;">pH</h2><p style="background:#fff;padding:10px;border:1px solid #eee;">Δεξαμενη: {record.ph_tank}</p>' if record.period == 'morning' and record.ph_tank else ''}
        {f'<h2 style="font-size:15px;color:#333;margin-top:20px;">Παρατηρησεις</h2><p style="background:#fff;padding:10px;border:1px solid #eee;">{record.notes}</p>' if record.notes else ''}
      </div>
      <div style="background:#f0f0f0;padding:12px;text-align:center;font-size:12px;color:#888;border-radius:0 0 8px 8px;">
        Sergios Hotel - Water Log - {record.record_date.strftime('%d/%m/%Y')} - {period_gr}
      </div>
    </div>"""
    try:
        msg = MIMEMultipart()
        msg['From']    = EMAIL_FROM
        msg['To']      = ', '.join(EMAIL_TO_LIST)
        msg['Subject'] = f'Sergios Hotel - Water Log {period_gr} {record.record_date.strftime("%d/%m/%Y")}'
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        s = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        s.login(EMAIL_FROM, EMAIL_PASSWORD)
        s.sendmail(EMAIL_FROM, EMAIL_TO_LIST, msg.as_string())
        s.quit()
        return True
    except Exception as e:
        print(f'Email error: {e}')
        return False


# ──────────────────────────────────────────────────────────────────────────
#  POOL LOG
# ──────────────────────────────────────────────────────────────────────────
def apply_pool_record(record, data, period):
    record.free_chlorine     = flt(data, 'free_chlorine')
    record.combined_chlorine = flt(data, 'combined_chlorine')
    record.ph                = flt(data, 'ph')
    record.temp              = flt(data, 'temp')
    record.turbidity         = flt(data, 'turbidity')
    record.backwash_done     = data.get('backwash_done') in ('1', 'on', 'true', 'True')
    record.notes             = data.get('notes', '')
    if period == 'morning':
        record.cyanuric_acid    = flt(data, 'cyanuric_acid')
        record.total_alkalinity = flt(data, 'total_alkalinity')
        record.orp              = flt(data, 'orp')

def send_pool_report_email(record, user):
    if not EMAIL_PASSWORD:
        return False
    period_gr = 'Πρωι' if record.period == 'morning' else 'Απογευμα'
    pool   = record.pool
    hotel  = pool.hotel.name if pool and pool.hotel else ''
    point  = f' — {pool.location}' if pool and pool.location else ''
    def row(label, val, unit, key):
        min_v, max_v = POOL_LIMITS.get(key, (None, None))
        if val is None:
            return f'<tr><td style="padding:7px 8px;border:1px solid #eee;">{label}</td><td style="padding:7px 8px;border:1px solid #eee;">-</td><td style="padding:7px 8px;border:1px solid #eee;color:#888;">{unit}</td></tr>'
        ok = (min_v is None or val >= min_v) and (max_v is None or val <= max_v)
        color = '#16a34a' if ok else '#dc2626'
        icon  = 'OK' if ok else 'ΠΡΟΣΟΧΗ'
        if min_v is not None and max_v is not None:
            limit = f'{min_v}-{max_v} {unit}'
        elif min_v is not None:
            limit = f'min {min_v} {unit}'
        elif max_v is not None:
            limit = f'max {max_v} {unit}'
        else:
            limit = unit
        return f'<tr><td style="padding:7px 8px;border:1px solid #eee;">{label}</td><td style="padding:7px 8px;border:1px solid #eee;color:{color};font-weight:500;">{icon}: {val} {unit}</td><td style="padding:7px 8px;border:1px solid #eee;color:#888;">{limit}</td></tr>'
    rows  = row('Ελευθερο χλωριο', record.free_chlorine, 'mg/L', 'free_chlorine')
    rows += row('Συνδεδεμενο χλωριο', record.combined_chlorine, 'mg/L', 'combined_chlorine')
    rows += row('pH', record.ph, '', 'ph')
    rows += row('Θερμοκρασια', record.temp, 'C', 'temp')
    rows += row('Θολοτητα', record.turbidity, 'NTU', 'turbidity')
    if record.period == 'morning':
        rows += row('Κυανουρικο οξυ', record.cyanuric_acid, 'mg/L', 'cyanuric_acid')
        rows += row('Ολικη αλκαλικοτητα', record.total_alkalinity, 'mg/L', 'total_alkalinity')
        rows += row('ORP (Redox)', record.orp, 'mV', 'orp')
    backwash = 'Ναι' if record.backwash_done else 'Οχι'
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:0 auto;">
      <div style="background:#0e7490;color:white;padding:20px;border-radius:8px 8px 0 0;">
        <h1 style="margin:0;font-size:20px;">{hotel} - Πισινα {period_gr}</h1>
        <p style="margin:5px 0 0;opacity:0.85;">{pool.name if pool else ''}{point}</p>
        <p style="margin:5px 0 0;opacity:0.8;">{record.record_date.strftime('%d/%m/%Y')} | Υπευθυνος: {user.full_name}</p>
      </div>
      <div style="background:#f9f9f9;padding:20px;border:1px solid #eee;">
        <table style="width:100%;border-collapse:collapse;">
          <tr style="background:#0e7490;color:white;"><th style="padding:8px;text-align:left;">Παραμετρος</th><th style="padding:8px;text-align:left;">Μετρηση</th><th style="padding:8px;text-align:left;">Ορια</th></tr>
          {rows}
        </table>
        <p style="margin-top:14px;font-size:13px;color:#555;">Ανταποπλυση φιλτρου (backwash): <b>{backwash}</b></p>
        {f'<h2 style="font-size:15px;color:#333;margin-top:16px;">Παρατηρησεις</h2><p style="background:#fff;padding:10px;border:1px solid #eee;">{record.notes}</p>' if record.notes else ''}
      </div>
      <div style="background:#f0f0f0;padding:12px;text-align:center;font-size:12px;color:#888;border-radius:0 0 8px 8px;">
        {hotel} - Πισινα {pool.name if pool else ''} - {record.record_date.strftime('%d/%m/%Y')} - {period_gr}
      </div>
    </div>"""
    try:
        msg = MIMEMultipart()
        msg['From']    = EMAIL_FROM
        msg['To']      = ', '.join(EMAIL_TO_LIST)
        msg['Subject'] = f'{hotel} - Πισινα {pool.name if pool else ""} {period_gr} {record.record_date.strftime("%d/%m/%Y")}'
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        s = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        s.login(EMAIL_FROM, EMAIL_PASSWORD)
        s.sendmail(EMAIL_FROM, EMAIL_TO_LIST, msg.as_string())
        s.quit()
        return True
    except Exception as e:
        print(f'Pool email error: {e}')
        return False


# ──────────────────────────────────────────────────────────────────────────
#  AI ASSISTANT helpers
# ──────────────────────────────────────────────────────────────────────────
def resolve_provider():
    if AI_PROVIDER == 'anthropic' and ANTHROPIC_API_KEY:
        return 'anthropic'
    if AI_PROVIDER == 'openai' and OPENAI_API_KEY:
        return 'openai'
    if AI_PROVIDER == 'auto':
        if ANTHROPIC_API_KEY:
            return 'anthropic'
        if OPENAI_API_KEY:
            return 'openai'
    return None

def call_llm(system_prompt, messages):
    """messages: list of {'role':'user'|'assistant','content':str}. Returns (reply, error)."""
    provider = resolve_provider()
    if not provider:
        return None, 'not_configured'
    try:
        if provider == 'anthropic':
            model = AI_MODEL or 'claude-sonnet-4-6'
            payload = {'model': model, 'max_tokens': 1024,
                       'system': system_prompt, 'messages': messages}
            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=json.dumps(payload).encode('utf-8'),
                headers={'content-type': 'application/json',
                         'x-api-key': ANTHROPIC_API_KEY,
                         'anthropic-version': '2023-06-01'})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode('utf-8'))
            return data['content'][0]['text'], None
        else:  # openai
            model = AI_MODEL or 'gpt-4o-mini'
            msgs = [{'role': 'system', 'content': system_prompt}] + messages
            payload = {'model': model, 'max_tokens': 1024, 'messages': msgs}
            req = urllib.request.Request(
                'https://api.openai.com/v1/chat/completions',
                data=json.dumps(payload).encode('utf-8'),
                headers={'content-type': 'application/json',
                         'authorization': f'Bearer {OPENAI_API_KEY}'})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode('utf-8'))
            return data['choices'][0]['message']['content'], None
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8')[:300]
        except Exception:
            pass
        return None, f'http_{e.code}: {body}'
    except Exception as e:
        return None, str(e)

def build_pool_context(pool):
    if not pool:
        return 'Δεν έχει επιλεγεί συγκεκριμένη πισίνα — ρώτα τον χρήστη ποια πισίνα αφορά.'
    lines = [
        f'Ξενοδοχείο: {pool.hotel.name if pool.hotel else "-"}',
        f'Πισίνα: {pool.name}' + (f' ({pool.location})' if pool.location else ''),
        f'Τύπος: {pool.pool_type}',
        f'Όγκος: {(str(pool.volume_m3) + " m3") if pool.volume_m3 else "ΑΓΝΩΣΤΟΣ — ζήτησε να τον επιβεβαιώσει ο χρήστης"}',
    ]
    recs = (PoolRecord.query.filter_by(pool_id=pool.id)
            .order_by(PoolRecord.record_date.desc(), PoolRecord.recorded_at.desc())
            .limit(2).all())
    if recs:
        lines.append('Τελευταίες μετρήσεις:')
        for r in recs:
            per = 'Πρωί' if r.period == 'morning' else 'Απόγευμα'
            parts = []
            def add(lbl, val, key, unit=''):
                if val is None:
                    return
                mn, mx = POOL_LIMITS.get(key, (None, None))
                ok = (mn is None or val >= mn) and (mx is None or val <= mx)
                parts.append(f'{lbl}={val}{unit}' + ('' if ok else ' [ΕΚΤΟΣ ΟΡΙΩΝ]'))
            add('ελ.χλώριο', r.free_chlorine, 'free_chlorine', ' mg/L')
            add('συνδ.χλώριο', r.combined_chlorine, 'combined_chlorine', ' mg/L')
            add('pH', r.ph, 'ph')
            add('θερμ', r.temp, 'temp', ' C')
            add('θολότητα', r.turbidity, 'turbidity', ' NTU')
            add('κυανουρικό', r.cyanuric_acid, 'cyanuric_acid', ' mg/L')
            add('αλκαλικότητα', r.total_alkalinity, 'total_alkalinity', ' mg/L')
            add('ORP', r.orp, 'orp', ' mV')
            lines.append(f'  {r.record_date.strftime("%d/%m")} {per}: ' + (', '.join(parts) if parts else '—'))
    else:
        lines.append('Δεν υπάρχουν καταγεγραμμένες μετρήσεις για αυτή την πισίνα ακόμα.')
    lines.append('Επιθυμητά όρια: ελ.χλώριο 0.4-1.5 mg/L, συνδ.χλώριο <=0.5, pH 7.2-7.8, θερμ <=32C, θολότητα <=1 NTU, κυανουρικό <=75, αλκαλικότητα 80-120, ORP >=650 mV.')
    return '\n'.join(lines)


def build_pool_report_pdf(rep_date, records):
    """Branded PDF αναφορά πισινών για μια ημέρα (fpdf2 + DejaVuSans)."""
    from fpdf import FPDF
    NAVY=(25,56,71); GOLD=(187,149,73); GREY=(120,120,120); RED=(200,30,30); GREEN=(20,140,60)
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_font('dv', '', os.path.join(BASE_DIR, 'assets', 'fonts', 'DejaVuSans.ttf'))
    pdf.add_font('dv', 'B', os.path.join(BASE_DIR, 'assets', 'fonts', 'DejaVuSans-Bold.ttf'))
    pdf.add_page()
    try:
        pdf.image(os.path.join(BASE_DIR, 'static', 'img', 'logo.png'), x=12, y=10, h=14)
    except Exception:
        pass
    pdf.set_xy(32, 11); pdf.set_font('dv', 'B', 16); pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, 'CONDIAN Hotels — Αναφορά Πισινών', ln=1)
    pdf.set_x(32); pdf.set_font('dv', '', 11); pdf.set_text_color(*GREY)
    pdf.cell(0, 6, 'Ημερομηνία: ' + rep_date.strftime('%d/%m/%Y'), ln=1)
    pdf.ln(8)
    if not records:
        pdf.set_font('dv', '', 12); pdf.set_text_color(*GREY)
        pdf.cell(0, 8, 'Δεν υπάρχουν καταγραφές για αυτή την ημέρα.', ln=1)
    cur = None
    for r in records:
        pname = (r.pool.hotel.name + ' — ' + r.pool.name) if (r.pool and r.pool.hotel) else (r.pool.name if r.pool else '—')
        if pname != cur:
            cur = pname
            pdf.ln(2); pdf.set_font('dv', 'B', 12); pdf.set_text_color(*NAVY); pdf.set_fill_color(240,243,245)
            pdf.cell(0, 8, '  ' + pname, ln=1, fill=True)
        per = 'Πρωί' if r.period == 'morning' else 'Απόγευμα'
        pdf.set_font('dv', 'B', 10); pdf.set_text_color(*GOLD)
        pdf.cell(0, 6, per + ' — ' + (r.user.full_name if r.user else ''), ln=1)
        def line(lbl, val, key, unit=''):
            if val is None: return
            mn, mx = POOL_LIMITS.get(key, (None, None))
            ok = (mn is None or val >= mn) and (mx is None or val <= mx)
            pdf.set_font('dv', '', 10); pdf.set_text_color(40,40,40); pdf.cell(62, 5, '   ' + lbl)
            pdf.set_text_color(*(GREEN if ok else RED))
            pdf.cell(0, 5, str(val) + unit + ('' if ok else '  (εκτός ορίων)'), ln=1)
        line('Ελεύθερο χλώριο', r.free_chlorine, 'free_chlorine', ' mg/L')
        line('Συνδεδεμένο χλώριο', r.combined_chlorine, 'combined_chlorine', ' mg/L')
        line('pH', r.ph, 'ph')
        line('Θερμοκρασία', r.temp, 'temp', ' C')
        line('Θολότητα', r.turbidity, 'turbidity', ' NTU')
        line('Κυανουρικό', r.cyanuric_acid, 'cyanuric_acid', ' mg/L')
        line('Αλκαλικότητα', r.total_alkalinity, 'total_alkalinity', ' mg/L')
        line('ORP', r.orp, 'orp', ' mV')
        if r.notes:
            pdf.set_font('dv', '', 9); pdf.set_text_color(*GREY); pdf.multi_cell(0, 5, '   Σημ: ' + r.notes)
    return bytes(pdf.output())


# ──────────────────────────────────────────────────────────────────────────
#  AUTH
# ──────────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user and user.role == 'admin':
            return redirect(url_for('dashboard'))
        return redirect(url_for('water_app'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.approved and check_password_hash(user.password, password):
            session['user_id']   = user.id
            session['user_name'] = user.full_name
            session['user_role'] = user.role
            session['language']  = user.language
            return redirect(url_for('dashboard') if user.role == 'admin' else url_for('water_app'))
        error = 'Λαθος username η password'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if not REG_CODE:
        return render_template('register.html', enabled=False, error=None, done=False)
    error = None
    if request.method == 'POST':
        fm = request.form
        if fm.get('reg_code', '').strip() != REG_CODE:
            error = 'Λάθος κωδικός εγγραφής'
        elif not (fm.get('username') and fm.get('password') and fm.get('full_name')):
            error = 'Συμπλήρωσε ονοματεπώνυμο, username και κωδικό'
        elif User.query.filter_by(username=fm['username'].strip()).first():
            error = 'Το username υπάρχει ήδη'
        else:
            db.session.add(User(
                username=fm['username'].strip(),
                password=generate_password_hash(fm['password']),
                full_name=fm['full_name'].strip(),
                email=fm.get('email', '').strip(),
                phone=fm.get('phone', '').strip(),
                role='staff', language=fm.get('language', 'el'),
                approved=False, is_active=True))
            db.session.commit()
            return render_template('register.html', enabled=True, error=None, done=True)
    return render_template('register.html', enabled=True, error=error, done=False)

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    saved = False
    if request.method == 'POST':
        fm = request.form
        user.email = fm.get('email', '').strip()
        user.phone = fm.get('phone', '').strip()
        if fm.get('language') in ('el', 'en'):
            user.language = fm['language']; session['language'] = fm['language']
        if fm.get('password'):
            user.password = generate_password_hash(fm['password'])
        db.session.commit()
        saved = True
    return render_template('profile.html', user=user, saved=saved)


# ──────────────────────────────────────────────────────────────────────────
#  WATER LOG ROUTES
# ──────────────────────────────────────────────────────────────────────────
@app.route('/app')
def water_app():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    today_morning   = WaterRecord.query.filter_by(record_date=date.today(), period='morning').first()
    today_afternoon = WaterRecord.query.filter_by(record_date=date.today(), period='afternoon').first()
    return render_template('app.html', user=user,
                           today_morning=today_morning,
                           today_afternoon=today_afternoon)

@app.route('/submit', methods=['POST'])
def submit():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Μη εξουσιοδοτημενο'}), 401
    user   = User.query.get(session['user_id'])
    data   = request.form
    period = data.get('period', 'morning')
    record = WaterRecord.query.filter_by(record_date=date.today(), period=period).first()
    if record:
        apply_record(record, data, period)
        record.updated_at = datetime.utcnow()
        record.updated_by = user.id
    else:
        record = WaterRecord(user_id=user.id, record_date=date.today(), period=period)
        apply_record(record, data, period)
        db.session.add(record)
    db.session.commit()
    t = threading.Thread(target=send_report_email, args=(record, user))
    t.daemon = True
    t.start()
    period_gr = 'Πρωι' if period == 'morning' else 'Απογευμα'
    return jsonify({'success': True, 'message': f'Καταγραφη {period_gr} αποθηκευτηκε!'})

@app.route('/edit/<int:record_id>', methods=['GET', 'POST'])
def edit_record(record_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user   = User.query.get(session['user_id'])
    record = WaterRecord.query.get_or_404(record_id)
    if user.role != 'admin' and record.record_date != date.today():
        return redirect(url_for('water_app'))
    if request.method == 'POST':
        apply_record(record, request.form, record.period)
        record.updated_at = datetime.utcnow()
        record.updated_by = user.id
        db.session.commit()
        if user.role == 'admin':
            return redirect(url_for('dashboard') + '?success=updated')
        return redirect(url_for('water_app'))
    return render_template('edit.html', user=user, record=record)

@app.route('/api/record/<int:record_id>')
def api_record(record_id):
    if 'user_id' not in session:
        return jsonify({}), 401
    r = WaterRecord.query.get_or_404(record_id)
    return jsonify({
        'id': r.id, 'period': r.period,
        'record_date': r.record_date.strftime('%d/%m/%Y'),
        'clo2_tank': r.clo2_tank, 'clo2_kitchen': r.clo2_kitchen,
        'clo2_remote': r.clo2_remote, 'clo2_dhw_out': r.clo2_dhw_out,
        'clo2_dhw_return': r.clo2_dhw_return, 'clo2_ro': r.clo2_ro,
        'location_kitchen': r.location_kitchen, 'location_remote': r.location_remote,
        'temp_tank': r.temp_tank, 'temp_dhw_out': r.temp_dhw_out,
        'temp_dhw_return': r.temp_dhw_return, 'temp_ro': r.temp_ro,
        'temp_kitchen_cold': r.temp_kitchen_cold, 'temp_kitchen_hot': r.temp_kitchen_hot,
        'temp_remote_cold': r.temp_remote_cold, 'temp_remote_hot': r.temp_remote_hot,
        'ph_tank': r.ph_tank, 'notes': r.notes or ''
    })

@app.route('/set-language/<lang>')
def set_language(lang):
    if lang in ['el', 'en'] and 'user_id' in session:
        session['language'] = lang
        user = User.query.get(session['user_id'])
        if user:
            user.language = lang
            db.session.commit()
    return redirect(request.referrer or url_for('water_app'))


# ──────────────────────────────────────────────────────────────────────────
#  POOL LOG ROUTES
# ──────────────────────────────────────────────────────────────────────────
def hotels_payload():
    hotels = Hotel.query.filter_by(is_active=True).order_by(Hotel.name).all()
    payload = [{
        'id': h.id, 'name': h.name,
        'pools': [{'id': p.id, 'name': p.name, 'location': p.location or '',
                   'type': p.pool_type, 'volume_m3': p.volume_m3}
                  for p in h.pools if p.is_active]
    } for h in hotels]
    return hotels, payload

@app.route('/pools')
def pools_app():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    hotels, hotels_json = hotels_payload()
    todays = PoolRecord.query.filter_by(record_date=date.today()).all()
    done = {}
    for r in todays:
        done.setdefault(str(r.pool_id), []).append(r.period)
    return render_template('pools.html', user=user, hotels=hotels,
                           hotels_json=hotels_json, done=done, limits=POOL_LIMITS)

@app.route('/submit-pool', methods=['POST'])
def submit_pool():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Μη εξουσιοδοτημενο'}), 401
    user   = User.query.get(session['user_id'])
    data   = request.form
    period = data.get('period', 'morning')
    pool_id = data.get('pool_id')
    pool = Pool.query.filter_by(id=pool_id, is_active=True).first() if pool_id else None
    if not pool:
        return jsonify({'success': False, 'message': 'Επιλεξτε πισινα'}), 400
    record = PoolRecord.query.filter_by(pool_id=pool.id, record_date=date.today(), period=period).first()
    if record:
        apply_pool_record(record, data, period)
        record.updated_at = datetime.utcnow()
        record.updated_by = user.id
    else:
        record = PoolRecord(pool_id=pool.id, user_id=user.id, record_date=date.today(), period=period)
        apply_pool_record(record, data, period)
        db.session.add(record)
    db.session.commit()
    t = threading.Thread(target=send_pool_report_email, args=(record, user))
    t.daemon = True
    t.start()
    period_gr = 'Πρωι' if period == 'morning' else 'Απογευμα'
    return jsonify({'success': True, 'message': f'Καταγραφη {pool.name} ({period_gr}) αποθηκευτηκε!'})

@app.route('/pools/edit/<int:record_id>', methods=['GET', 'POST'])
def edit_pool_record(record_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user   = User.query.get(session['user_id'])
    record = PoolRecord.query.get_or_404(record_id)
    if user.role != 'admin' and record.record_date != date.today():
        return redirect(url_for('pools_app'))
    if request.method == 'POST':
        apply_pool_record(record, request.form, record.period)
        record.updated_at = datetime.utcnow()
        record.updated_by = user.id
        db.session.commit()
        if user.role == 'admin':
            return redirect(url_for('pools_dashboard') + '?success=updated')
        return redirect(url_for('pools_app'))
    return render_template('pool_edit.html', user=user, record=record, limits=POOL_LIMITS)

@app.route('/api/pool-record/<int:record_id>')
def api_pool_record(record_id):
    if 'user_id' not in session:
        return jsonify({}), 401
    r = PoolRecord.query.get_or_404(record_id)
    return jsonify({
        'id': r.id, 'period': r.period, 'pool_id': r.pool_id,
        'record_date': r.record_date.strftime('%d/%m/%Y'),
        'free_chlorine': r.free_chlorine, 'combined_chlorine': r.combined_chlorine,
        'ph': r.ph, 'temp': r.temp, 'turbidity': r.turbidity,
        'cyanuric_acid': r.cyanuric_acid, 'total_alkalinity': r.total_alkalinity,
        'orp': r.orp, 'backwash_done': r.backwash_done, 'notes': r.notes or ''
    })

@app.route('/pools/report.pdf')
def pool_report_pdf():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    ds = request.args.get('date')
    try:
        rep_date = datetime.strptime(ds, '%Y-%m-%d').date() if ds else date.today()
    except ValueError:
        rep_date = date.today()
    records = (PoolRecord.query.filter_by(record_date=rep_date)
               .order_by(PoolRecord.pool_id, PoolRecord.period).all())
    pdf_bytes = build_pool_report_pdf(rep_date, records)
    fname = 'pool-report-' + rep_date.strftime('%Y-%m-%d') + '.pdf'
    return Response(pdf_bytes, mimetype='application/pdf',
                    headers={'Content-Disposition': 'attachment; filename=' + fname})


# ──────────────────────────────────────────────────────────────────────────
#  AI ASSISTANT ROUTES
# ──────────────────────────────────────────────────────────────────────────
@app.route('/assistant')
def assistant_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    hotels, hotels_json = hotels_payload()
    return render_template('assistant.html', user=user,
                           hotels_json=hotels_json,
                           configured=(resolve_provider() is not None))

@app.route('/api/assistant', methods=['POST'])
def api_assistant():
    if 'user_id' not in session:
        return jsonify({'reply': '', 'error': 'auth'}), 401
    data = request.get_json(force=True, silent=True) or {}
    raw  = data.get('messages', [])
    pool_id = data.get('pool_id')
    messages = []
    for m in raw[-12:]:
        role = m.get('role')
        content = (m.get('content') or '').strip()
        if role in ('user', 'assistant') and content:
            messages.append({'role': role, 'content': content[:4000]})
    if not messages:
        return jsonify({'reply': '', 'error': 'empty'}), 400
    pool = Pool.query.filter_by(id=pool_id, is_active=True).first() if pool_id else None
    context = build_pool_context(pool)
    system = POOL_ASSISTANT_PROMPT + '\n\n# ΔΕΔΟΜΕΝΑ ΕΦΑΡΜΟΓΗΣ (τρέχουσα κατάσταση)\n' + context
    reply, err = call_llm(system, messages)
    if err == 'not_configured':
        return jsonify({'reply': '', 'error': 'not_configured'})
    if err:
        return jsonify({'reply': '', 'error': err}), 502
    return jsonify({'reply': reply, 'error': None})


# ──────────────────────────────────────────────────────────────────────────
#  ADMIN DASHBOARDS
# ──────────────────────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session or session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    records = WaterRecord.query.order_by(WaterRecord.record_date.desc(), WaterRecord.period).limit(60).all()
    users   = User.query.filter_by(is_active=True, approved=True).all()
    pending = User.query.filter_by(is_active=True, approved=False).all()
    today_m = WaterRecord.query.filter_by(record_date=date.today(), period='morning').first()
    today_a = WaterRecord.query.filter_by(record_date=date.today(), period='afternoon').first()
    return render_template('dashboard.html', records=records, users=users, pending=pending,
                           today_morning=today_m, today_afternoon=today_a)

@app.route('/pools/dashboard')
def pools_dashboard():
    if 'user_id' not in session or session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    hotels  = Hotel.query.filter_by(is_active=True).order_by(Hotel.name).all()
    pools   = Pool.query.filter_by(is_active=True).all()
    records = (PoolRecord.query
               .order_by(PoolRecord.record_date.desc(), PoolRecord.recorded_at.desc())
               .limit(80).all())
    return render_template('pools_dashboard.html', hotels=hotels, pools=pools,
                           records=records, limits=POOL_LIMITS)

@app.route('/dashboard/add-user', methods=['POST'])
def add_user():
    if session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    data = request.form
    if not User.query.filter_by(username=data['username']).first():
        db.session.add(User(
            username=data['username'],
            password=generate_password_hash(data['password']),
            full_name=data['full_name'],
            role=data.get('role', 'staff'),
            language=data.get('language', 'el')
        ))
        db.session.commit()
    return redirect(url_for('dashboard') + '?success=user_added')

@app.route('/dashboard/delete-user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    user = User.query.get(user_id)
    if user and user.role != 'admin':
        user.is_active = False
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/dashboard/approve-user/<int:user_id>', methods=['POST'])
def approve_user(user_id):
    if session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    u = User.query.get(user_id)
    if u:
        u.approved = True; u.is_active = True
        db.session.commit()
    return redirect(url_for('dashboard') + '?success=user_approved')

@app.route('/dashboard/add-hotel', methods=['POST'])
def add_hotel():
    if session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    name = request.form.get('name', '').strip()
    if name and not Hotel.query.filter_by(name=name).first():
        db.session.add(Hotel(name=name))
        db.session.commit()
    return redirect(url_for('pools_dashboard') + '?success=hotel_added')

@app.route('/dashboard/delete-hotel/<int:hotel_id>', methods=['POST'])
def delete_hotel(hotel_id):
    if session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    hotel = Hotel.query.get(hotel_id)
    if hotel:
        hotel.is_active = False
        for p in hotel.pools:
            p.is_active = False
        db.session.commit()
    return redirect(url_for('pools_dashboard'))

@app.route('/dashboard/add-pool', methods=['POST'])
def add_pool():
    if session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    data = request.form
    hotel_id = data.get('hotel_id')
    name = data.get('name', '').strip()
    if hotel_id and name:
        db.session.add(Pool(
            hotel_id=int(hotel_id),
            name=name,
            location=data.get('location', '').strip(),
            pool_type=data.get('pool_type', 'pool'),
            volume_m3=flt(data, 'volume_m3')
        ))
        db.session.commit()
    return redirect(url_for('pools_dashboard') + '?success=pool_added')

@app.route('/dashboard/delete-pool/<int:pool_id>', methods=['POST'])
def delete_pool(pool_id):
    if session.get('user_role') != 'admin':
        return redirect(url_for('login'))
    pool = Pool.query.get(pool_id)
    if pool:
        pool.is_active = False
        db.session.commit()
    return redirect(url_for('pools_dashboard'))


# ──────────────────────────────────────────────────────────────────────────
#  CHART APIs
# ──────────────────────────────────────────────────────────────────────────
@app.route('/api/history')
def api_history():
    if 'user_id' not in session:
        return jsonify([])
    records = WaterRecord.query.filter_by(period='morning').order_by(WaterRecord.record_date.desc()).limit(14).all()
    return jsonify([{
        'date': r.record_date.strftime('%d/%m'),
        'clo2_tank': r.clo2_tank,
        'temp_dhw_out': r.temp_dhw_out,
        'temp_dhw_return': r.temp_dhw_return,
        'temp_tank': r.temp_tank,
    } for r in records])

@app.route('/api/pool-history/<int:pool_id>')
def api_pool_history(pool_id):
    if 'user_id' not in session:
        return jsonify([])
    records = (PoolRecord.query.filter_by(pool_id=pool_id, period='morning')
               .order_by(PoolRecord.record_date.desc()).limit(14).all())
    return jsonify([{
        'date': r.record_date.strftime('%d/%m'),
        'free_chlorine': r.free_chlorine,
        'ph': r.ph,
        'temp': r.temp,
    } for r in records])


# ──────────────────────────────────────────────────────────────────────────
#  INIT  (τρέχει και κάτω από gunicorn)
# ──────────────────────────────────────────────────────────────────────────
def _add_col(table, col, ddl):
    insp = db.inspect(db.engine)
    if table in insp.get_table_names():
        cols = [c['name'] for c in insp.get_columns(table)]
        if col not in cols:
            db.session.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {ddl}'))
            db.session.commit()
            print(f'Migration: {table}.{col} added')

def ensure_columns():
    """Ελαφρύ migration: πρόσθεσε νέες στήλες σε ήδη υπάρχουσα βάση."""
    try:
        truth = 'true' if db.engine.dialect.name == 'postgresql' else '1'
        _add_col('pool', 'volume_m3', 'volume_m3 FLOAT')
        _add_col('user', 'email', 'email VARCHAR(120)')
        _add_col('user', 'phone', 'phone VARCHAR(40)')
        _add_col('user', 'approved', f'approved BOOLEAN DEFAULT {truth}')
    except Exception as e:
        db.session.rollback()
        print(f'ensure_columns skipped: {e}')

def init_db():
    with app.app_context():
        db.create_all()
        ensure_columns()
        try:
            if not User.query.filter_by(username='admin').first():
                db.session.add(User(username='admin', password=generate_password_hash('sergios2024'), full_name='Δημητρης Γιαννουλακης', role='admin', language='el'))
                db.session.add(User(username='giannhs', password=generate_password_hash('pool2024'), full_name='Γιαννης Γιακουμακης', role='admin', language='el'))
                db.session.add(User(username='xypakis', password=generate_password_hash('water2024'), full_name='Μανος Χυπακης', role='staff', language='el'))
                db.session.commit()
                print('Βαση δεδομενων και χρηστες δημιουργηθηκαν')
            if not Hotel.query.first():
                sergios = Hotel(name='Sergios Hotel')
                db.session.add(sergios)
                db.session.flush()
                db.session.add(Pool(hotel_id=sergios.id, name='Κύρια Πισίνα', location='Pool bar', pool_type='pool', volume_m3=200))
                db.session.add(Pool(hotel_id=sergios.id, name='Παιδική Πισίνα', location='Pool bar', pool_type='kids', volume_m3=20))
                db.session.commit()
                print('Δημιουργηθηκε δειγμα ξενοδοχειου & πισινων')
        except Exception as e:
            db.session.rollback()
            print(f'init_db seed skipped: {e}')


def _athens_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('Europe/Athens'))
    except Exception:
        return datetime.utcnow() + timedelta(hours=3)

def missing_today():
    today = date.today()
    miss = []
    for p in Pool.query.filter_by(is_active=True).all():
        recs = {r.period for r in PoolRecord.query.filter_by(pool_id=p.id, record_date=today).all()}
        gaps = [per for per in ('morning', 'afternoon') if per not in recs]
        if gaps:
            hotel = p.hotel.name if p.hotel else ''
            miss.append(f"{hotel} — {p.name}: " + ', '.join('Πρωί' if g == 'morning' else 'Απόγευμα' for g in gaps))
    for per, label in (('morning', 'Πρωί'), ('afternoon', 'Απόγευμα')):
        if not WaterRecord.query.filter_by(record_date=today, period=per).first():
            miss.append('Νερά Χρήσης (Sergios): ' + label)
    return miss

def send_reminder_email(miss):
    if not EMAIL_PASSWORD or not miss:
        return False
    recips = list(EMAIL_TO_LIST)
    for u in User.query.filter_by(is_active=True, approved=True).all():
        if u.email and u.email not in recips:
            recips.append(u.email)
    items = ''.join(f'<li>{m}</li>' for m in miss)
    html = f'<div style="font-family:Arial,sans-serif"><h3 style="color:#193847">Εκκρεμείς καταγραφές σήμερα</h3><ul>{items}</ul><p style="color:#888;font-size:12px">CONDIAN Hotels — αυτόματη υπενθύμιση</p></div>'
    try:
        msg = MIMEMultipart(); msg['From'] = EMAIL_FROM; msg['To'] = ', '.join(recips)
        msg['Subject'] = 'Υπενθυμιση καταγραφων - ' + date.today().strftime('%d/%m/%Y')
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        sv = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT); sv.login(EMAIL_FROM, EMAIL_PASSWORD)
        sv.sendmail(EMAIL_FROM, recips, msg.as_string()); sv.quit()
        return True
    except Exception as e:
        print('reminder email error:', e); return False

def reminder_tick():
    with app.app_context():
        now = _athens_now()
        if now.hour != REMINDER_HOUR:
            return
        today = now.strftime('%Y-%m-%d')
        if ReminderSent.query.get(today):
            return
        try:
            db.session.add(ReminderSent(day=today)); db.session.commit()
        except Exception:
            db.session.rollback(); return   # άλλος worker το ανέλαβε
        miss = missing_today()
        if miss:
            send_reminder_email(miss)
            print(f'[reminder] {today}: {len(miss)} εκκρεμή')

def reminder_loop():
    while True:
        try:
            reminder_tick()
        except Exception as e:
            print('[reminder] loop error:', e)
        time.sleep(1800)   # κάθε 30 λεπτά

def start_scheduler():
    if ENABLE_SCHEDULER:
        threading.Thread(target=reminder_loop, daemon=True).start()
        print('[scheduler] reminder loop started')


init_db()
start_scheduler()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
