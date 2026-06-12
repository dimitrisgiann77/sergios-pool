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
import os, smtplib, threading, json, time, urllib.request, urllib.error, urllib.parse
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
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024   # 2MB (avatar upload)

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

# Microsoft Graph (Office 365) — ενεργό αν οριστεί GRAPH_CLIENT_ID
GRAPH_TENANT_ID     = os.environ.get('GRAPH_TENANT_ID', '')
GRAPH_CLIENT_ID     = os.environ.get('GRAPH_CLIENT_ID', '')
GRAPH_CLIENT_SECRET = os.environ.get('GRAPH_CLIENT_SECRET', '')
GRAPH_SENDER        = os.environ.get('GRAPH_SENDER', EMAIL_FROM)

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

PARAM_LABELS = {
    'free_chlorine': 'Ελεύθερο χλώριο', 'combined_chlorine': 'Συνδεδεμένο χλώριο',
    'ph': 'pH', 'temp': 'Θερμοκρασία', 'turbidity': 'Θολότητα',
    'cyanuric_acid': 'Κυανουρικό οξύ', 'total_alkalinity': 'Ολική αλκαλικότητα', 'orp': 'ORP',
}

# Κανόνας ενεργειών όταν τιμή εκτός ορίων (low = κάτω από min, high = πάνω από max)
ACTION_RULES = {
    'free_chlorine':     {'low': 'Χαμηλό χλώριο — κάνε χλωρίωση και επανέλεγξε σε 30΄.',
                          'high': 'Υψηλό χλώριο — σταμάτα τη δοσομέτρηση/άσε να πέσει· απόφυγε χρήση μέχρι <1.5 mg/L.'},
    'combined_chlorine': {'high': 'Υψηλό δεσμευμένο χλώριο — υπερχλωρίωση (shock) + αερισμός· έλεγξε ανανέωση νερού.'},
    'ph':                {'low': 'Χαμηλό pH — πρόσθεσε pH plus (ανθρακική σόδα).',
                          'high': 'Υψηλό pH — πρόσθεσε pH minus (οξύ), σταδιακά.'},
    'temp':              {'high': 'Υψηλή θερμοκρασία — έλεγξε/μείωσε θέρμανση· παρακολούθησε χλώριο.'},
    'turbidity':         {'high': 'Θολό νερό — backwash φίλτρου, έλεγξε διήθηση/κυκλοφορία, εξέτασε κροκίδωση.'},
    'cyanuric_acid':     {'high': 'Υψηλό κυανουρικό οξύ — μερική ανανέωση νερού (αραίωση)· μείωσε σταθεροποιητή.'},
    'total_alkalinity':  {'low': 'Χαμηλή αλκαλικότητα — πρόσθεσε alkalinity up (ανθρακική σόδα).',
                          'high': 'Υψηλή αλκαλικότητα — πρόσθεσε οξύ σταδιακά.'},
    'orp':               {'low': 'Χαμηλό ORP — ανέβασε ελεύθερο χλώριο και ρύθμισε pH στο 7.2–7.6.'},
}
SAFETY_NOTE = 'Ποτέ μην αναμειγνύεις χημικά μεταξύ τους (ειδικά χλώριο με οξύ). Πρόσθεσε ένα-ένα, με την κυκλοφορία ανοιχτή.'

AREA_LABELS = {'pump': 'Αντλία', 'filter': 'Φίλτρο', 'chemicals': 'Χημικά / Δοσομέτρηση',
               'water': 'Νερό / Στάθμη', 'electrical': 'Ηλεκτρικό', 'app': 'Εφαρμογή', 'other': 'Άλλο'}

def _urgent(param, val):
    return ((param == 'free_chlorine' and val < 0.2) or
            (param == 'combined_chlorine' and val > 1.0) or
            (param == 'turbidity' and val > 2.0))

def compute_pool_actions(rec):
    out = []
    for key, rule in ACTION_RULES.items():
        val = getattr(rec, key, None)
        if val is None:
            continue
        mn, mx = POOL_LIMITS.get(key, (None, None))
        action = None
        if mn is not None and val < mn:
            action = rule.get('low')
        elif mx is not None and val > mx:
            action = rule.get('high')
        if action:
            out.append({'label': PARAM_LABELS.get(key, key), 'action': action, 'urgent': _urgent(key, val)})
    return out


def notify(user_id, text, link=None):
    if not user_id:
        return
    try:
        db.session.add(Notification(user_id=user_id, text=(text or '')[:300], link=link))
        db.session.commit()
    except Exception:
        db.session.rollback()

def notify_admins(text, link=None):
    for u in User.query.filter(User.is_active == True, User.role.in_(['admin', 'masteradmin'])).all():
        notify(u.id, text, link)

def send_fault_email(fr):
    if not EMAIL_PASSWORD and not GRAPH_CLIENT_ID:
        return False
    label = AREA_LABELS.get(fr.area, fr.area)
    who = fr.user.full_name if fr.user else '-'
    where = (fr.pool.hotel.name + ' / ' + fr.pool.name) if (fr.pool and fr.pool.hotel) else (fr.pool.name if fr.pool else '-')
    html = ('<div style="font-family:Arial,sans-serif;max-width:600px;">'
            '<div style="background:#b91c1c;color:white;padding:16px;border-radius:8px 8px 0 0;"><h2 style="margin:0;">Αναφορα βλαβης</h2></div>'
            '<div style="background:#f9f9f9;padding:16px;border:1px solid #eee;">'
            + '<p><b>Τομεας:</b> ' + label + '</p><p><b>Σημειο:</b> ' + where + '</p><p><b>Απο:</b> ' + who + '</p>'
            + '<p><b>Περιγραφη:</b><br>' + (fr.message or '') + '</p></div></div>')
    return send_email('Αναφορα βλαβης - ' + label, html, EMAIL_TO_LIST)


# ── ROLES & PERMISSIONS ──
ROLE_RANK = {'viewer': 0, 'staff': 1, 'manager': 2, 'admin': 3, 'masteradmin': 4}
ROLE_LABELS = {'staff': 'Staff (καταγραφή)', 'manager': 'Manager (επόπτης)', 'admin': 'Admin', 'masteradmin': 'Master Admin'}

def role_rank(role):
    return ROLE_RANK.get(role, 0)

def current_user():
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None

@app.context_processor
def inject_nav():
    uid = session.get('user_id')
    unread = Notification.query.filter_by(user_id=uid, is_read=False).count() if uid else 0
    return {'nav_unread': unread}

@app.context_processor
def inject_theme():
    return {'theme': get_theme()}

def has_rank(min_rank):
    u = current_user()
    return u is not None and role_rank(u.role) >= min_rank

def is_admin():
    return has_rank(ROLE_RANK['admin'])      # admin ή masteradmin

def can_log():
    return has_rank(ROLE_RANK['staff'])      # ό,τι πάνω από viewer

def allowed_hotels(u):
    if u is None:
        return []
    if role_rank(u.role) >= ROLE_RANK['admin']:
        return Hotel.query.filter_by(is_active=True).order_by(Hotel.name).all()
    assigned = [h for h in u.hotels if h.is_active]
    if assigned:
        return sorted(assigned, key=lambda h: h.name)
    return Hotel.query.filter_by(is_active=True).order_by(Hotel.name).all()   # χωρίς ανάθεση = όλα

def can_access_pool(u, pool):
    if u is None or pool is None:
        return False
    if role_rank(u.role) >= ROLE_RANK['admin']:
        return True
    assigned = {h.id for h in u.hotels if h.is_active}
    if not assigned:
        return True   # χωρίς ανάθεση = όλα
    return pool.hotel_id in assigned

def log_activity(action, detail=''):
    try:
        db.session.add(ActivityLog(user_id=session.get('user_id'),
                                   action=(action or '')[:60], detail=(detail or '')[:300]))
        db.session.commit()
    except Exception:
        db.session.rollback()

# ──────────────────────────────────────────────────────────────────────────
#  MODELS
# ──────────────────────────────────────────────────────────────────────────
user_hotels = db.Table('user_hotels',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('hotel_id', db.Integer, db.ForeignKey('hotel.id'), primary_key=True),
)

class ActivityLog(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action     = db.Column(db.String(60))
    detail     = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user       = db.relationship('User')

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
    avatar     = db.Column(db.Text)                       # data URL (base64) εικόνας προφίλ
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    hotels     = db.relationship('Hotel', secondary=user_hotels, backref='members')

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

class FaultReport(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    hotel_id    = db.Column(db.Integer, db.ForeignKey('hotel.id'), nullable=True)
    pool_id     = db.Column(db.Integer, db.ForeignKey('pool.id'), nullable=True)
    area        = db.Column(db.String(20))
    message     = db.Column(db.Text)
    status      = db.Column(db.String(12), default='open')   # open / resolved
    answer      = db.Column(db.Text)
    answered_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    user = db.relationship('User', foreign_keys=[user_id])
    pool = db.relationship('Pool')

class Notification(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text       = db.Column(db.String(300))
    link       = db.Column(db.String(120))
    is_read    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class EmailLog(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    subject    = db.Column(db.String(200))
    recipients = db.Column(db.String(300))
    ok         = db.Column(db.Boolean, default=False)
    via        = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Setting(db.Model):
    key   = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.Text)

# ── Generic monitoring engine (Πλατφόρμα Συντήρησης) ──
class MonitorTemplate(db.Model):
    key       = db.Column(db.String(30), primary_key=True)   # 'tank','energy',...
    name      = db.Column(db.String(80))
    icon      = db.Column(db.String(30), default='ti-checklist')
    frequency = db.Column(db.String(10), default='daily')    # twice|daily|weekly|monthly
    sort      = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    params    = db.relationship('MonitorParam', backref='template', order_by='MonitorParam.sort',
                                cascade='all, delete-orphan')

class MonitorParam(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    template_key = db.Column(db.String(30), db.ForeignKey('monitor_template.key'))
    pkey         = db.Column(db.String(40))      # κλειδί τιμής
    label        = db.Column(db.String(80))
    unit         = db.Column(db.String(20), default='')
    min_v        = db.Column(db.Float)
    max_v        = db.Column(db.Float)
    action_low   = db.Column(db.String(200))
    action_high  = db.Column(db.String(200))
    periodic     = db.Column(db.Boolean, default=False)   # μόνο πρωί/πρώτη βάρδια
    sort         = db.Column(db.Integer, default=0)

class Area(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    hotel_id     = db.Column(db.Integer, db.ForeignKey('hotel.id'), nullable=False)
    template_key = db.Column(db.String(30), db.ForeignKey('monitor_template.key'), nullable=False)
    name         = db.Column(db.String(120))
    location     = db.Column(db.String(120))
    is_active    = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    hotel        = db.relationship('Hotel')
    template     = db.relationship('MonitorTemplate')

class Reading(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    area_id     = db.Column(db.Integer, db.ForeignKey('area.id'), nullable=False)
    template_key= db.Column(db.String(30))
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'))
    record_date = db.Column(db.Date, default=date.today)
    period      = db.Column(db.String(10), default='day')
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime)
    updated_by  = db.Column(db.Integer, db.ForeignKey('user.id'))
    values      = db.Column(db.Text)     # JSON {pkey: value}
    notes       = db.Column(db.Text)
    area        = db.relationship('Area')
    user        = db.relationship('User', foreign_keys=[user_id])

FREQ_PERIODS = {'twice': ['morning', 'afternoon'], 'daily': ['day'], 'weekly': ['day'], 'monthly': ['day']}
FREQ_LABEL   = {'twice': '2×/ημέρα (πρωί/απόγευμα)', 'daily': 'Καθημερινά', 'weekly': 'Εβδομαδιαία', 'monthly': 'Μηνιαία'}

def periods_for(freq):
    return FREQ_PERIODS.get(freq, ['day'])

def area_actions(reading):
    """Generic έλεγχος ορίων -> ενέργειες, με βάση τις παραμέτρους του template."""
    out = []
    try:
        vals = json.loads(reading.values or '{}')
    except Exception:
        vals = {}
    tpl = MonitorTemplate.query.get(reading.template_key)
    if not tpl:
        return out
    for p in tpl.params:
        v = vals.get(p.pkey)
        if v is None:
            continue
        try:
            v = float(v)
        except (ValueError, TypeError):
            continue
        act = None
        if p.min_v is not None and v < p.min_v:
            act = p.action_low or ('Χαμηλό: ' + p.label)
        elif p.max_v is not None and v > p.max_v:
            act = p.action_high or ('Υψηλό: ' + p.label)
        if act:
            out.append({'label': p.label, 'value': v, 'unit': p.unit, 'action': act})
    return out


def flt(data, key):
    try:
        return float(data[key]) if data.get(key) not in (None, '') else None
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────────────────────────────────
#  EMAIL (Microsoft Graph ή SMTP) + log
# ──────────────────────────────────────────────────────────────────────────
def _graph_token():
    data = urllib.parse.urlencode({
        'client_id': GRAPH_CLIENT_ID, 'client_secret': GRAPH_CLIENT_SECRET,
        'scope': 'https://graph.microsoft.com/.default', 'grant_type': 'client_credentials',
    }).encode()
    req = urllib.request.Request('https://login.microsoftonline.com/' + GRAPH_TENANT_ID + '/oauth2/v2.0/token', data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())['access_token']

def _send_graph(subject, html, recips):
    token = _graph_token()
    payload = {'message': {'subject': subject, 'body': {'contentType': 'HTML', 'content': html},
               'toRecipients': [{'emailAddress': {'address': a}} for a in recips]}, 'saveToSentItems': True}
    req = urllib.request.Request('https://graph.microsoft.com/v1.0/users/' + GRAPH_SENDER + '/sendMail',
        data=json.dumps(payload).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status in (200, 202)

def _send_smtp(subject, html, recips):
    msg = MIMEMultipart(); msg['From'] = EMAIL_FROM; msg['To'] = ', '.join(recips); msg['Subject'] = subject
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    sv = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT); sv.login(EMAIL_FROM, EMAIL_PASSWORD)
    sv.sendmail(EMAIL_FROM, recips, msg.as_string()); sv.quit()
    return True

def send_email(subject, html, recips=None):
    recips = recips or EMAIL_TO_LIST
    via = 'graph' if GRAPH_CLIENT_ID else ('smtp' if EMAIL_PASSWORD else 'none')
    ok = False
    if via != 'none':
        try:
            ok = _send_graph(subject, html, recips) if via == 'graph' else _send_smtp(subject, html, recips)
        except Exception as e:
            print('email error (' + via + '):', e); ok = False
    try:
        db.session.add(EmailLog(subject=(subject or '')[:200], recipients=', '.join(recips)[:300], ok=ok, via=via))
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    return ok


THEME_DEFAULTS = {'primary': '#193847', 'accent': '#BB9549', 'app_title': 'CONDIAN HOTELS', 'logo': ''}

def get_theme():
    t = dict(THEME_DEFAULTS)
    try:
        for row in Setting.query.filter(Setting.key.like('theme_%')).all():
            k = row.key[6:]
            if k in t and row.value is not None:
                t[k] = row.value
    except Exception:
        pass
    return t

def get_ai_config():
    cfg = {'provider': AI_PROVIDER, 'anthropic': ANTHROPIC_API_KEY, 'openai': OPENAI_API_KEY, 'model': AI_MODEL}
    try:
        for row in Setting.query.filter(Setting.key.like('ai_%')).all():
            k = row.key[3:]
            if k in cfg and row.value:
                cfg[k] = row.value
    except Exception:
        pass
    return cfg


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
    if not EMAIL_PASSWORD and not GRAPH_CLIENT_ID:
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
    return send_email(f'Sergios Hotel - Water Log {period_gr} {record.record_date.strftime("%d/%m/%Y")}', html, EMAIL_TO_LIST)


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
    if not EMAIL_PASSWORD and not GRAPH_CLIENT_ID:
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
    _acts = compute_pool_actions(record)
    if _acts:
        _li = ''.join('<li style="margin-bottom:4px;' + ('color:#b91c1c;font-weight:600;' if a['urgent'] else '') + '">' + ('ΕΠΕΙΓΟΝ — ' if a['urgent'] else '') + a['label'] + ': ' + a['action'] + '</li>' for a in _acts)
        actions_html = '<h2 style="font-size:15px;color:#b45309;margin-top:18px;">Προτεινομενες ενεργειες</h2><ul style="background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:12px 12px 12px 28px;color:#333;">' + _li + '</ul><p style="font-size:11px;color:#888;">' + SAFETY_NOTE + '</p>'
    else:
        actions_html = ''
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
        {actions_html}
        {f'<h2 style="font-size:15px;color:#333;margin-top:16px;">Παρατηρησεις</h2><p style="background:#fff;padding:10px;border:1px solid #eee;">{record.notes}</p>' if record.notes else ''}
      </div>
      <div style="background:#f0f0f0;padding:12px;text-align:center;font-size:12px;color:#888;border-radius:0 0 8px 8px;">
        {hotel} - Πισινα {pool.name if pool else ''} - {record.record_date.strftime('%d/%m/%Y')} - {period_gr}
      </div>
    </div>"""
    return send_email(f'{hotel} - Πισινα {pool.name if pool else ""} {period_gr} {record.record_date.strftime("%d/%m/%Y")}', html, EMAIL_TO_LIST)


# ──────────────────────────────────────────────────────────────────────────
#  AI ASSISTANT helpers
# ──────────────────────────────────────────────────────────────────────────
def resolve_provider():
    c = get_ai_config()
    if c['provider'] == 'anthropic' and c['anthropic']:
        return 'anthropic'
    if c['provider'] == 'openai' and c['openai']:
        return 'openai'
    if c['provider'] == 'auto':
        if c['anthropic']:
            return 'anthropic'
        if c['openai']:
            return 'openai'
    return None

def call_llm(system_prompt, messages):
    """messages: list of {'role':'user'|'assistant','content':str}. Returns (reply, error)."""
    provider = resolve_provider()
    if not provider:
        return None, 'not_configured'
    c = get_ai_config()
    try:
        if provider == 'anthropic':
            model = c['model'] or 'claude-sonnet-4-6'
            payload = {'model': model, 'max_tokens': 1024,
                       'system': system_prompt, 'messages': messages}
            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=json.dumps(payload).encode('utf-8'),
                headers={'content-type': 'application/json',
                         'x-api-key': c['anthropic'],
                         'anthropic-version': '2023-06-01'})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode('utf-8'))
            return data['content'][0]['text'], None
        else:  # openai
            model = c['model'] or 'gpt-4o-mini'
            msgs = [{'role': 'system', 'content': system_prompt}] + messages
            payload = {'model': model, 'max_tokens': 1024, 'messages': msgs}
            req = urllib.request.Request(
                'https://api.openai.com/v1/chat/completions',
                data=json.dumps(payload).encode('utf-8'),
                headers={'content-type': 'application/json',
                         'authorization': 'Bearer ' + c['openai']})
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
            pdf.set_x(pdf.l_margin); pdf.set_font('dv', '', 9); pdf.set_text_color(*GREY)
            pdf.multi_cell(pdf.epw, 5, '   Σημ: ' + r.notes)
        _acts = compute_pool_actions(r)
        if _acts:
            pdf.set_x(pdf.l_margin); pdf.set_font('dv', 'B', 9); pdf.set_text_color(180, 83, 9)
            pdf.multi_cell(pdf.epw, 5, 'Προτεινόμενες ενέργειες:')
            for a in _acts:
                pdf.set_x(pdf.l_margin); pdf.set_font('dv', '', 9)
                pdf.set_text_color(185, 28, 28) if a['urgent'] else pdf.set_text_color(80, 80, 80)
                pdf.multi_cell(pdf.epw, 4.6, ('• ΕΠΕΙΓΟΝ — ' if a['urgent'] else '• ') + a['label'] + ': ' + a['action'])
    return bytes(pdf.output())


# ── Background email senders (τρέχουν σε thread, με app context) ──
def _bg_send_water(rid, uid):
    with app.app_context():
        r = WaterRecord.query.get(rid); u = User.query.get(uid)
        if r and u:
            send_report_email(r, u)

def _bg_send_pool(rid, uid):
    with app.app_context():
        r = PoolRecord.query.get(rid); u = User.query.get(uid)
        if r and u:
            send_pool_report_email(r, u)

def _bg_send_fault(fid):
    with app.app_context():
        fr = FaultReport.query.get(fid)
        if fr:
            send_fault_email(fr)


# ──────────────────────────────────────────────────────────────────────────
#  AUTH
# ──────────────────────────────────────────────────────────────────────────
def landing_for(user):
    r = role_rank(user.role)
    if r >= ROLE_RANK['admin']:
        return url_for('dashboard')
    if r >= ROLE_RANK['viewer'] and r != ROLE_RANK['staff']:
        return url_for('pools_dashboard')   # manager / viewer
    return url_for('pools_app')             # staff
@app.route('/')
def index():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            return render_template('shell.html', user=user, is_admin=is_admin(),
                                   is_master=(user.role == 'masteradmin'), can_log=can_log(),
                                   rank=role_rank(user.role), RANK=ROLE_RANK)
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
            log_activity('login')
            return redirect(url_for('index'))
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
        photo = request.files.get('photo')
        if photo and photo.filename and photo.mimetype and photo.mimetype.startswith('image/'):
            raw = photo.read()
            if 0 < len(raw) <= 800 * 1024:
                import base64
                user.avatar = 'data:' + photo.mimetype + ';base64,' + base64.b64encode(raw).decode()
        db.session.commit()
        log_activity('profile_update')
        saved = True
    return render_template('profile.html', user=user, saved=saved)


# ──────────────────────────────────────────────────────────────────────────
#  WATER LOG ROUTES
# ──────────────────────────────────────────────────────────────────────────
@app.route('/app')
def water_app():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if not can_log():
        return redirect(url_for('pools_dashboard'))
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
    threading.Thread(target=_bg_send_water, args=(record.id, user.id), daemon=True).start()
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
def hotels_payload(user=None):
    if user is not None and role_rank(user.role) < ROLE_RANK['admin']:
        hotels = allowed_hotels(user)
    else:
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
    if not can_log():
        return redirect(url_for('pools_dashboard'))
    user = User.query.get(session['user_id'])
    hotels, hotels_json = hotels_payload(user)
    todays = PoolRecord.query.filter_by(record_date=date.today()).all()
    done = {}
    for r in todays:
        done.setdefault(str(r.pool_id), []).append(r.period)
    return render_template('pools.html', user=user, hotels=hotels,
                           hotels_json=hotels_json, done=done, limits=POOL_LIMITS,
                           action_rules=ACTION_RULES, param_labels=PARAM_LABELS, safety_note=SAFETY_NOTE)

@app.route('/submit-pool', methods=['POST'])
def submit_pool():
    if 'user_id' not in session or not can_log():
        return jsonify({'success': False, 'message': 'Μη εξουσιοδοτημενο'}), 401
    user   = User.query.get(session['user_id'])
    data   = request.form
    period = data.get('period', 'morning')
    pool_id = data.get('pool_id')
    pool = Pool.query.filter_by(id=pool_id, is_active=True).first() if pool_id else None
    if not pool:
        return jsonify({'success': False, 'message': 'Επιλεξτε πισινα'}), 400
    if not can_access_pool(user, pool):
        return jsonify({'success': False, 'message': 'Δεν εχεις προσβαση σε αυτη την πισινα'}), 403
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
    log_activity('pool_submit', f'{pool.name} ({period})')
    _a = compute_pool_actions(record)
    if _a:
        notify_admins((('ΕΠΕΙΓΟΝ — ' if any(x['urgent'] for x in _a) else '') + 'Μέτρηση εκτός ορίων: ' + pool.name), '/pools/dashboard')
    threading.Thread(target=_bg_send_pool, args=(record.id, user.id), daemon=True).start()
    period_gr = 'Πρωι' if period == 'morning' else 'Απογευμα'
    return jsonify({'success': True, 'message': f'Καταγραφη {pool.name} ({period_gr}) αποθηκευτηκε!'})

@app.route('/pools/edit/<int:record_id>', methods=['GET', 'POST'])
def edit_pool_record(record_id):
    if 'user_id' not in session or not can_log():
        return redirect(url_for('login'))
    user   = current_user()
    record = PoolRecord.query.get_or_404(record_id)
    if not can_access_pool(user, record.pool):
        return redirect(url_for('pools_app'))
    if not is_admin() and record.record_date != date.today():
        return redirect(url_for('pools_app'))
    if request.method == 'POST':
        apply_pool_record(record, request.form, record.period)
        record.updated_at = datetime.utcnow()
        record.updated_by = user.id
        db.session.commit()
        log_activity('pool_edit', record.pool.name if record.pool else '')
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
    hotels, hotels_json = hotels_payload(current_user())
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
    if not is_admin():
        return redirect(url_for('login'))
    records = WaterRecord.query.order_by(WaterRecord.record_date.desc(), WaterRecord.period).limit(60).all()
    users   = User.query.filter_by(is_active=True, approved=True).all()
    pending = User.query.filter_by(is_active=True, approved=False).all()
    today_m = WaterRecord.query.filter_by(record_date=date.today(), period='morning').first()
    today_a = WaterRecord.query.filter_by(record_date=date.today(), period='afternoon').first()
    return render_template('dashboard.html', records=records, users=users, pending=pending,
                           today_morning=today_m, today_afternoon=today_a,
                           all_hotels=Hotel.query.filter_by(is_active=True).order_by(Hotel.name).all(),
                           role_labels=ROLE_LABELS, me=current_user())

@app.route('/pools/dashboard')
def pools_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = current_user()
    hotels = allowed_hotels(user)
    hids = {h.id for h in hotels}
    pools = [p for p in Pool.query.filter_by(is_active=True).all() if p.hotel_id in hids]
    pids = {p.id for p in pools}
    q = PoolRecord.query
    if role_rank(user.role) < ROLE_RANK['admin']:
        q = q.filter(PoolRecord.pool_id.in_(pids if pids else [-1]))
    records = q.order_by(PoolRecord.record_date.desc(), PoolRecord.recorded_at.desc()).limit(80).all()
    return render_template('pools_dashboard.html', hotels=hotels, pools=pools,
                           records=records, limits=POOL_LIMITS,
                           is_admin=is_admin(), user=user)

@app.route('/dashboard/add-user', methods=['POST'])
def add_user():
    if not is_admin():
        return redirect(url_for('login'))
    data = request.form
    if not User.query.filter_by(username=data['username']).first():
        db.session.add(User(
            username=data['username'],
            password=generate_password_hash(data['password']),
            full_name=data['full_name'],
            email=data.get('email', '').strip(),
            phone=data.get('phone', '').strip(),
            role=data.get('role', 'staff'),
            language=data.get('language', 'el')
        ))
        db.session.commit()
        log_activity('user_add', data.get('username', ''))
    return redirect(url_for('dashboard') + '?success=user_added')

@app.route('/dashboard/delete-user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if not is_admin():
        return redirect(url_for('login'))
    user = User.query.get(user_id)
    if user and role_rank(user.role) < ROLE_RANK['admin']:
        user.is_active = False
        db.session.commit()
        log_activity('user_delete', user.username)
    return redirect(url_for('dashboard'))

@app.route('/dashboard/approve-user/<int:user_id>', methods=['POST'])
def approve_user(user_id):
    if not is_admin():
        return redirect(url_for('login'))
    u = User.query.get(user_id)
    if u:
        u.approved = True; u.is_active = True
        db.session.commit()
        log_activity('user_approve', u.username)
        notify(u.id, 'Ο λογαριασμός σου εγκρίθηκε. Καλώς ήρθες!', '/pools')
    return redirect(url_for('dashboard') + '?success=user_approved')

def _protected(actor, target):
    # δεν επιτρέπεται σε χαμηλότερο ρόλο να πειράξει masteradmin
    return role_rank(target.role) >= ROLE_RANK['masteradmin'] and role_rank(actor.role) < ROLE_RANK['masteradmin']

@app.route('/dashboard/edit-user/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    if not is_admin():
        return redirect(url_for('login'))
    actor = current_user(); u = User.query.get(user_id)
    if not u or _protected(actor, u):
        return redirect(url_for('dashboard'))
    fm = request.form
    u.full_name = (fm.get('full_name') or u.full_name).strip() or u.full_name
    u.email = fm.get('email', '').strip()
    u.phone = fm.get('phone', '').strip()
    new_role = fm.get('role', u.role)
    if new_role in ROLE_RANK and role_rank(new_role) <= role_rank(actor.role):
        u.role = new_role
    hids = [int(x) for x in fm.getlist('hotel_ids') if x.isdigit()]
    u.hotels = Hotel.query.filter(Hotel.id.in_(hids)).all() if hids else []
    db.session.commit()
    log_activity('user_edit', u.username)
    return redirect(url_for('dashboard') + '?success=user_edited')

@app.route('/dashboard/reset-password/<int:user_id>', methods=['POST'])
def reset_password(user_id):
    if not is_admin():
        return redirect(url_for('login'))
    actor = current_user(); u = User.query.get(user_id)
    if u and not _protected(actor, u):
        newpw = request.form.get('password', '').strip()
        if newpw:
            u.password = generate_password_hash(newpw); db.session.commit()
            log_activity('user_reset_password', u.username)
    return redirect(url_for('dashboard') + '?success=password_reset')

@app.route('/dashboard/toggle-user/<int:user_id>', methods=['POST'])
def toggle_user(user_id):
    if not is_admin():
        return redirect(url_for('login'))
    actor = current_user(); u = User.query.get(user_id)
    if u and u.id != actor.id and not _protected(actor, u):
        u.is_active = not u.is_active; db.session.commit()
        log_activity('user_toggle', u.username + (' -> active' if u.is_active else ' -> inactive'))
    return redirect(url_for('dashboard'))

@app.route('/dashboard/activity')
def activity_log_view():
    if not is_admin():
        return redirect(url_for('login'))
    logs = ActivityLog.query.order_by(ActivityLog.id.desc()).limit(200).all()
    return render_template('activity.html', logs=logs)

# ── Εβδομαδιαία κάλυψη ──
@app.route('/pools/coverage')
def pools_coverage():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = current_user()
    hids = {h.id for h in allowed_hotels(user)}
    pools = [p for p in Pool.query.filter_by(is_active=True).order_by(Pool.hotel_id, Pool.name).all() if p.hotel_id in hids]
    days = [date.today() - timedelta(days=i) for i in range(6, -1, -1)]
    recs = PoolRecord.query.filter(
        PoolRecord.pool_id.in_([p.id for p in pools] or [-1]),
        PoolRecord.record_date.in_(days)).all()
    cov = {}
    for r in recs:
        cov.setdefault((r.pool_id, r.record_date), set()).add(r.period)
    grid = []
    for p in pools:
        cells = []
        for d in days:
            sset = cov.get((p.id, d), set())
            cells.append({'m': 'morning' in sset, 'a': 'afternoon' in sset})
        grid.append({'pool': p, 'cells': cells})
    return render_template('coverage.html', grid=grid, days=days)

# ── Αναφορά βλάβης ──
@app.route('/fault', methods=['GET', 'POST'])
def fault_report():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = current_user()
    hids = {h.id for h in allowed_hotels(user)}
    pools = [p for p in Pool.query.filter_by(is_active=True).all() if p.hotel_id in hids]
    if request.method == 'POST':
        area = request.form.get('area', 'other')
        msg = request.form.get('message', '').strip()
        pid = request.form.get('pool_id', '')
        pool = Pool.query.get(int(pid)) if pid.isdigit() else None
        if msg:
            fr = FaultReport(user_id=user.id, area=area, message=msg,
                             pool_id=pool.id if pool else None,
                             hotel_id=pool.hotel_id if pool else None, status='open')
            db.session.add(fr); db.session.commit()
            log_activity('fault_report', area)
            where = (' / ' + pool.name) if pool else ''
            notify_admins('Νέα αναφορά βλάβης: ' + AREA_LABELS.get(area, area) + where, '/dashboard/faults')
            threading.Thread(target=_bg_send_fault, args=(fr.id,), daemon=True).start()
            return render_template('fault.html', areas=AREA_LABELS, pools=pools, done=True)
    return render_template('fault.html', areas=AREA_LABELS, pools=pools, done=False)

# ── In-app ειδοποιήσεις ──
@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    items = Notification.query.filter_by(user_id=session['user_id']).order_by(Notification.id.desc()).limit(100).all()
    return render_template('notifications.html', items=items)

@app.route('/notifications/read', methods=['POST'])
def notifications_read():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    Notification.query.filter_by(user_id=session['user_id'], is_read=False).update({'is_read': True})
    db.session.commit()
    return redirect(url_for('notifications'))

# ── Admin inbox βλαβών ──
@app.route('/dashboard/faults')
def faults_inbox():
    if not is_admin():
        return redirect(url_for('login'))
    open_faults = FaultReport.query.filter_by(status='open').order_by(FaultReport.id.desc()).all()
    done_faults = FaultReport.query.filter_by(status='resolved').order_by(FaultReport.id.desc()).limit(50).all()
    return render_template('faults_inbox.html', open_faults=open_faults, done_faults=done_faults, areas=AREA_LABELS)

@app.route('/dashboard/fault/<int:fid>/answer', methods=['POST'])
def fault_answer(fid):
    if not is_admin():
        return redirect(url_for('login'))
    fr = FaultReport.query.get(fid)
    if fr:
        fr.answer = request.form.get('answer', '').strip()
        fr.answered_by = session.get('user_id')
        db.session.commit()
        notify(fr.user_id, 'Απάντηση στην αναφορά σου: ' + (fr.answer or '')[:80], '/notifications')
        log_activity('fault_answer', str(fid))
    return redirect(url_for('faults_inbox'))

@app.route('/dashboard/fault/<int:fid>/resolve', methods=['POST'])
def fault_resolve(fid):
    if not is_admin():
        return redirect(url_for('login'))
    fr = FaultReport.query.get(fid)
    if fr:
        fr.status = 'resolved'; fr.resolved_at = datetime.utcnow(); db.session.commit()
        notify(fr.user_id, 'Η αναφορά βλάβης σου επιλύθηκε.', '/notifications')
        log_activity('fault_resolve', str(fid))
    return redirect(url_for('faults_inbox'))

@app.route('/dashboard/fault/<int:fid>/reopen', methods=['POST'])
def fault_reopen(fid):
    if not is_admin():
        return redirect(url_for('login'))
    fr = FaultReport.query.get(fid)
    if fr:
        fr.status = 'open'; fr.resolved_at = None; db.session.commit()
    return redirect(url_for('faults_inbox'))

# ── Email admin (Graph/SMTP, test, manual, log) ──
@app.route('/dashboard/email')
def email_admin():
    if not is_admin():
        return redirect(url_for('login'))
    logs = EmailLog.query.order_by(EmailLog.id.desc()).limit(50).all()
    mode = 'Microsoft Graph (365)' if GRAPH_CLIENT_ID else ('SMTP (' + SMTP_SERVER + ')' if EMAIL_PASSWORD else 'Δεν έχει ρυθμιστεί')
    return render_template('email_admin.html', logs=logs, mode=mode)

@app.route('/dashboard/email/test', methods=['POST'])
def email_test():
    if not is_admin():
        return redirect(url_for('login'))
    to = request.form.get('to', '').strip()
    recips = [to] if to else EMAIL_TO_LIST
    send_email('CONDIAN - Δοκιμαστικο email', '<p>Δοκιμαστικο email απο την εφαρμογη CONDIAN. Αν το βλεπεις, η αποστολη λειτουργει.</p>', recips)
    log_activity('email_test', ', '.join(recips))
    return redirect(url_for('email_admin'))

@app.route('/dashboard/email/reminder', methods=['POST'])
def email_reminder_now():
    if not is_admin():
        return redirect(url_for('login'))
    miss = missing_today()
    if miss:
        send_reminder_email(miss)
    log_activity('email_reminder_manual', str(len(miss)))
    return redirect(url_for('email_admin'))

# ── Theming (admin) ──
@app.route('/dashboard/theme', methods=['GET', 'POST'])
def theme_admin():
    if not is_admin():
        return redirect(url_for('login'))
    import re as _re
    if request.method == 'POST':
        def setk(k, v):
            row = Setting.query.get('theme_' + k)
            if row:
                row.value = v
            else:
                db.session.add(Setting(key='theme_' + k, value=v))
        for k in ['primary', 'accent']:
            v = request.form.get(k, '')
            if _re.match(r'^#[0-9a-fA-F]{6}$', v):
                setk(k, v)
        setk('app_title', (request.form.get('app_title', 'CONDIAN HOTELS') or 'CONDIAN HOTELS')[:60])
        if request.form.get('reset_logo'):
            setk('logo', '')
        else:
            logo = request.files.get('logo')
            if logo and logo.filename and logo.mimetype and logo.mimetype.startswith('image/'):
                raw = logo.read()
                if 0 < len(raw) <= 400 * 1024:
                    import base64
                    setk('logo', 'data:' + logo.mimetype + ';base64,' + base64.b64encode(raw).decode())
        db.session.commit(); log_activity('theme_update')
        return redirect(url_for('theme_admin') + '?saved=1')
    return render_template('theme_admin.html', theme=get_theme())

# ── AI σύνδεση (masteradmin) ──
@app.route('/dashboard/ai', methods=['GET', 'POST'])
def ai_admin():
    u = current_user()
    if u is None or u.role != 'masteradmin':
        return redirect(url_for('login'))
    def setk(k, v):
        row = Setting.query.get('ai_' + k)
        if row:
            row.value = v
        else:
            db.session.add(Setting(key='ai_' + k, value=v))
    if request.method == 'POST':
        setk('provider', request.form.get('provider', 'auto'))
        setk('model', request.form.get('model', '').strip())
        if request.form.get('clear_keys'):
            setk('anthropic', ''); setk('openai', '')
        else:
            ak = request.form.get('anthropic', '').strip()
            if ak and not ak.startswith('*'):
                setk('anthropic', ak)
            ok = request.form.get('openai', '').strip()
            if ok and not ok.startswith('*'):
                setk('openai', ok)
        db.session.commit(); log_activity('ai_config')
        return redirect(url_for('ai_admin') + '?saved=1')
    c = get_ai_config()
    masked = {'anthropic': ('*' * 8 + c['anthropic'][-4:]) if c['anthropic'] else '',
              'openai': ('*' * 8 + c['openai'][-4:]) if c['openai'] else ''}
    return render_template('ai_admin.html', cfg=c, masked=masked, configured=(resolve_provider() is not None))

# ── GENERIC AREAS (Πλατφόρμα Συντήρησης) ──
def can_access_area(u, area):
    if u is None or area is None:
        return False
    if role_rank(u.role) >= ROLE_RANK['admin']:
        return True
    assigned = {h.id for h in u.hotels if h.is_active}
    if not assigned:
        return True
    return area.hotel_id in assigned

def _templates_json():
    out = {}
    for t in MonitorTemplate.query.filter_by(is_active=True).order_by(MonitorTemplate.sort).all():
        out[t.key] = {'name': t.name, 'icon': t.icon, 'frequency': t.frequency,
                      'params': [{'pkey': p.pkey, 'label': p.label, 'unit': p.unit,
                                  'min': p.min_v, 'max': p.max_v, 'periodic': p.periodic} for p in t.params]}
    return out

def reading_cells(r):
    try:
        vals = json.loads(r.values or '{}')
    except Exception:
        vals = {}
    tpl = MonitorTemplate.query.get(r.template_key); cells = []
    if tpl:
        for p in tpl.params:
            v = vals.get(p.pkey); ok = True
            if v is not None:
                try:
                    fv = float(v); ok = (p.min_v is None or fv >= p.min_v) and (p.max_v is None or fv <= p.max_v)
                except Exception:
                    pass
            cells.append({'label': p.label, 'value': v, 'unit': p.unit, 'ok': ok})
    return cells

@app.route('/areas')
def areas_app():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if not can_log():
        return redirect(url_for('areas_dashboard'))
    user = current_user()
    hids = {h.id for h in allowed_hotels(user)}
    areas = [a for a in Area.query.filter_by(is_active=True).order_by(Area.template_key, Area.name).all() if a.hotel_id in hids]
    areas_json = [{'id': a.id, 'name': a.name, 'location': a.location or '',
                   'hotel': a.hotel.name if a.hotel else '', 'template': a.template_key} for a in areas]
    todays = Reading.query.filter_by(record_date=date.today()).all()
    done = {}
    for r in todays:
        done.setdefault(str(r.area_id), []).append(r.period)
    return render_template('areas.html', user=user, areas_json=areas_json,
                           templates=_templates_json(), done=done, freq_periods=FREQ_PERIODS)

@app.route('/areas/submit', methods=['POST'])
def areas_submit():
    if 'user_id' not in session or not can_log():
        return jsonify({'success': False, 'message': 'Μη εξουσιοδοτημενο'}), 401
    user = current_user(); data = request.form
    area = Area.query.filter_by(id=data.get('area_id'), is_active=True).first() if data.get('area_id') else None
    if not area:
        return jsonify({'success': False, 'message': 'Επιλεξτε τομεα'}), 400
    if not can_access_area(user, area):
        return jsonify({'success': False, 'message': 'Δεν εχεις προσβαση'}), 403
    period = data.get('period', 'day')
    tpl = MonitorTemplate.query.get(area.template_key)
    vals = {}
    for p in (tpl.params if tpl else []):
        v = data.get(p.pkey, '')
        if v not in (None, ''):
            try:
                vals[p.pkey] = float(v)
            except (ValueError, TypeError):
                pass
    rec = Reading.query.filter_by(area_id=area.id, record_date=date.today(), period=period).first()
    if rec:
        rec.values = json.dumps(vals); rec.notes = data.get('notes', '')
        rec.updated_at = datetime.utcnow(); rec.updated_by = user.id
    else:
        rec = Reading(area_id=area.id, template_key=area.template_key, user_id=user.id,
                      record_date=date.today(), period=period, values=json.dumps(vals), notes=data.get('notes', ''))
        db.session.add(rec)
    db.session.commit()
    log_activity('area_submit', area.name)
    acts = area_actions(rec)
    if acts:
        notify_admins('Εκτός ορίων: ' + area.name + ' (' + str(len(acts)) + ')', '/areas/dashboard')
    return jsonify({'success': True, 'message': 'Καταγραφη ' + area.name + ' αποθηκευτηκε!'})

@app.route('/areas/dashboard')
def areas_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = current_user()
    hids = {h.id for h in allowed_hotels(user)}
    areas = [a for a in Area.query.filter_by(is_active=True).all() if a.hotel_id in hids]
    aids = {a.id for a in areas}
    q = Reading.query
    if role_rank(user.role) < ROLE_RANK['admin']:
        q = q.filter(Reading.area_id.in_(aids if aids else [-1]))
    recs = q.order_by(Reading.record_date.desc(), Reading.recorded_at.desc()).limit(120).all()
    rows = [(r, reading_cells(r)) for r in recs]
    return render_template('areas_dashboard.html', areas=areas, rows=rows,
                           is_admin=is_admin(), templates=MonitorTemplate.query.order_by(MonitorTemplate.sort).all())

@app.route('/overview')
def overview():
    if not is_admin():
        return redirect(url_for('login'))
    today = date.today()
    hotels = Hotel.query.filter_by(is_active=True).order_by(Hotel.name).all()
    cov = []
    total_exp = total_done = 0
    for h in hotels:
        exp = done = 0
        for p in [p for p in h.pools if p.is_active]:
            exp += 2
            done += min(2, PoolRecord.query.filter_by(pool_id=p.id, record_date=today).count())
        for a in Area.query.filter_by(hotel_id=h.id, is_active=True).all():
            tpl = MonitorTemplate.query.get(a.template_key)
            n = len(periods_for(tpl.frequency)) if tpl else 1
            exp += n
            done += min(n, Reading.query.filter_by(area_id=a.id, record_date=today).count())
        pct = int(100 * done / exp) if exp else 100
        cov.append({'hotel': h.name, 'exp': exp, 'done': done, 'pct': pct})
        total_exp += exp; total_done += done
    rec_dates = [today, today - timedelta(days=1)]
    alerts = []
    for r in PoolRecord.query.filter(PoolRecord.record_date.in_(rec_dates)).order_by(PoolRecord.recorded_at.desc()).limit(80).all():
        for a in compute_pool_actions(r):
            alerts.append({'where': (r.pool.hotel.name + ' / ' + r.pool.name) if (r.pool and r.pool.hotel) else (r.pool.name if r.pool else '—'),
                           'label': a['label'], 'urgent': a['urgent'], 'date': r.record_date})
    for r in Reading.query.filter(Reading.record_date.in_(rec_dates)).order_by(Reading.recorded_at.desc()).limit(80).all():
        for a in area_actions(r):
            alerts.append({'where': (r.area.hotel.name + ' / ' + r.area.name) if (r.area and r.area.hotel) else '—',
                           'label': a['label'], 'urgent': False, 'date': r.record_date})
    alerts = sorted(alerts, key=lambda x: (not x['urgent'], x['date']), reverse=False)[:15]
    faults = FaultReport.query.filter_by(status='open').order_by(FaultReport.id.desc()).limit(10).all()
    pending = User.query.filter_by(is_active=True, approved=False).all()
    kpis = {'hotels': len(hotels),
            'pools': Pool.query.filter_by(is_active=True).count(),
            'areas': Area.query.filter_by(is_active=True).count(),
            'users': User.query.filter_by(is_active=True, approved=True).count(),
            'compliance': int(100 * total_done / total_exp) if total_exp else 100,
            'open_faults': FaultReport.query.filter_by(status='open').count(),
            'pending': len(pending), 'alerts': len(alerts)}
    return render_template('overview.html', cov=cov, alerts=alerts, faults=faults,
                           pending=pending, kpis=kpis, areas_labels=AREA_LABELS)

# admin: areas management
@app.route('/dashboard/areas', methods=['GET', 'POST'])
def areas_admin():
    if not is_admin():
        return redirect(url_for('login'))
    if request.method == 'POST':
        hid = request.form.get('hotel_id'); tk = request.form.get('template_key'); nm = request.form.get('name', '').strip()
        if hid and tk and nm:
            db.session.add(Area(hotel_id=int(hid), template_key=tk, name=nm, location=request.form.get('location', '').strip()))
            db.session.commit(); log_activity('area_add', nm)
        return redirect(url_for('areas_admin') + '?saved=1')
    return render_template('areas_admin.html',
                           hotels=Hotel.query.filter_by(is_active=True).order_by(Hotel.name).all(),
                           templates=MonitorTemplate.query.filter_by(is_active=True).order_by(MonitorTemplate.sort).all(),
                           areas=Area.query.filter_by(is_active=True).all())

@app.route('/dashboard/area/<int:area_id>/delete', methods=['POST'])
def area_delete(area_id):
    if not is_admin():
        return redirect(url_for('login'))
    a = Area.query.get(area_id)
    if a:
        a.is_active = False; db.session.commit()
    return redirect(url_for('areas_admin'))

# admin: template editor (hybrid)
@app.route('/dashboard/templates')
def templates_admin():
    if not is_admin():
        return redirect(url_for('login'))
    return render_template('templates_admin.html',
                           templates=MonitorTemplate.query.order_by(MonitorTemplate.sort).all(),
                           freq_label=FREQ_LABEL)

@app.route('/dashboard/template/new', methods=['POST'])
def template_new():
    if not is_admin():
        return redirect(url_for('login'))
    key = (request.form.get('key', '').strip().lower() or '')
    key = ''.join(ch for ch in key if ch.isalnum() or ch == '_')[:30]
    if key and not MonitorTemplate.query.get(key):
        db.session.add(MonitorTemplate(key=key, name=request.form.get('name', key).strip(),
                       icon=request.form.get('icon', 'ti-checklist').strip() or 'ti-checklist',
                       frequency=request.form.get('frequency', 'daily'), sort=99))
        db.session.commit(); log_activity('template_new', key)
    return redirect(url_for('template_edit', key=key) if key else url_for('templates_admin'))

@app.route('/dashboard/template/<key>', methods=['GET', 'POST'])
def template_edit(key):
    if not is_admin():
        return redirect(url_for('login'))
    tpl = MonitorTemplate.query.get(key)
    if not tpl:
        return redirect(url_for('templates_admin'))
    if request.method == 'POST':
        tpl.name = request.form.get('name', tpl.name).strip()
        tpl.icon = request.form.get('icon', tpl.icon).strip() or tpl.icon
        tpl.frequency = request.form.get('frequency', tpl.frequency)
        def fnum(v):
            try:
                return float(v) if v not in (None, '') else None
            except (ValueError, TypeError):
                return None
        # update existing params
        for p in list(tpl.params):
            if request.form.get('del_%d' % p.id):
                db.session.delete(p); continue
            p.label = request.form.get('label_%d' % p.id, p.label).strip()
            p.unit = request.form.get('unit_%d' % p.id, p.unit).strip()
            p.min_v = fnum(request.form.get('min_%d' % p.id))
            p.max_v = fnum(request.form.get('max_%d' % p.id))
            p.action_low = request.form.get('alow_%d' % p.id, '').strip()
            p.action_high = request.form.get('ahigh_%d' % p.id, '').strip()
            p.periodic = bool(request.form.get('per_%d' % p.id))
        # new param
        npk = request.form.get('new_pkey', '').strip().lower()
        npk = ''.join(ch for ch in npk if ch.isalnum() or ch == '_')[:40]
        if npk and request.form.get('new_label', '').strip():
            db.session.add(MonitorParam(template_key=tpl.key, pkey=npk,
                           label=request.form.get('new_label').strip(),
                           unit=request.form.get('new_unit', '').strip(),
                           min_v=fnum(request.form.get('new_min')), max_v=fnum(request.form.get('new_max')),
                           action_low=request.form.get('new_alow', '').strip(),
                           action_high=request.form.get('new_ahigh', '').strip(),
                           periodic=bool(request.form.get('new_per')), sort=len(tpl.params) + 1))
        db.session.commit(); log_activity('template_edit', key)
        return redirect(url_for('template_edit', key=key) + '?saved=1')
    return render_template('template_edit.html', tpl=tpl, freq_label=FREQ_LABEL)

# ── Demo data seeder (admin) — τυχαίες καταγραφές 1-31/5 ──
@app.route('/admin/seed-demo')
def seed_demo():
    if not is_admin():
        return redirect(url_for('login'))
    import random
    user = current_user()
    pools = Pool.query.filter_by(is_active=True).all()
    if not pools:
        return 'Δεν υπάρχουν πισίνες. <a href="/pools/dashboard">Πίσω</a>'
    yr = int(request.args.get('year', date.today().year))
    created = 0
    for p in pools:
        d = date(yr, 5, 1)
        while d <= date(yr, 5, 31):
            for period in ('morning', 'afternoon'):
                if PoolRecord.query.filter_by(pool_id=p.id, record_date=d, period=period).first():
                    continue
                r = PoolRecord(pool_id=p.id, user_id=user.id, record_date=d, period=period)
                r.free_chlorine     = round(random.uniform(0.5, 1.3), 2) if random.random() > 0.10 else round(random.uniform(0.1, 0.39), 2)
                r.combined_chlorine = round(random.uniform(0.0, 0.4), 2) if random.random() > 0.10 else round(random.uniform(0.55, 0.9), 2)
                r.ph                = round(random.uniform(7.2, 7.8), 1) if random.random() > 0.10 else round(random.uniform(7.9, 8.3), 1)
                r.temp              = round(random.uniform(24, 30), 1)
                r.turbidity         = round(random.uniform(0.1, 0.8), 1) if random.random() > 0.10 else round(random.uniform(1.1, 1.8), 1)
                if period == 'morning':
                    r.cyanuric_acid    = round(random.uniform(20, 60))
                    r.total_alkalinity = round(random.uniform(80, 120)) if random.random() > 0.10 else round(random.uniform(60, 79))
                    r.orp              = round(random.uniform(650, 760)) if random.random() > 0.10 else round(random.uniform(580, 640))
                r.backwash_done = random.random() > 0.85
                r.recorded_at = datetime(yr, 5, d.day, 8 if period == 'morning' else 17, random.randint(0, 59))
                db.session.add(r); created += 1
            d += timedelta(days=1)
    db.session.commit()
    log_activity('seed_demo', f'{created} records {yr}-05')
    return ('<div style="font-family:Arial;padding:40px;text-align:center;">'
            '<h2 style="color:#193847;">Δημιουργήθηκαν ' + str(created) + ' demo καταγραφές (1-31/5/' + str(yr) + ')</h2>'
            '<p><a href="/pools/dashboard" style="color:#193847;">→ Pool dashboard</a> &nbsp; '
            '<a href="/pools/coverage" style="color:#193847;">→ Κάλυψη</a></p></div>')

@app.route('/dashboard/add-hotel', methods=['POST'])
def add_hotel():
    if not is_admin():
        return redirect(url_for('login'))
    name = request.form.get('name', '').strip()
    if name and not Hotel.query.filter_by(name=name).first():
        db.session.add(Hotel(name=name))
        db.session.commit()
    return redirect(url_for('pools_dashboard') + '?success=hotel_added')

@app.route('/dashboard/delete-hotel/<int:hotel_id>', methods=['POST'])
def delete_hotel(hotel_id):
    if not is_admin():
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
    if not is_admin():
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
    if not is_admin():
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
        _add_col('user', 'avatar', 'avatar TEXT')
    except Exception as e:
        db.session.rollback()
        print(f'ensure_columns skipped: {e}')

def init_db():
    with app.app_context():
        db.create_all()
        ensure_columns()
        try:
            if not User.query.filter_by(username='admin').first():
                db.session.add(User(username='admin', password=generate_password_hash('sergios2024'), full_name='Δημητρης Γιαννουλακης', role='masteradmin', language='el'))
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

            if not MonitorTemplate.query.first():
                tank = MonitorTemplate(key='tank', name='Στάθμες & Δεξαμενές', icon='ti-stack-2', frequency='daily', sort=10)
                db.session.add(tank); db.session.flush()
                db.session.add_all([
                    MonitorParam(template_key='tank', pkey='level_pct', label='Στάθμη', unit='%', min_v=20, max_v=100, action_low='Χαμηλή στάθμη — έλεγξε πλήρωση/διαρροή.', sort=1),
                    MonitorParam(template_key='tank', pkey='pressure', label='Πίεση', unit='bar', sort=2),
                    MonitorParam(template_key='tank', pkey='temp', label='Θερμοκρασία', unit='C', sort=3),
                ])
                energy = MonitorTemplate(key='energy', name='Ενέργεια & Μετρητές', icon='ti-bolt', frequency='daily', sort=20)
                db.session.add(energy); db.session.flush()
                db.session.add_all([
                    MonitorParam(template_key='energy', pkey='electricity_kwh', label='Ρεύμα (ένδειξη)', unit='kWh', sort=1),
                    MonitorParam(template_key='energy', pkey='water_m3', label='Νερό (ένδειξη)', unit='m3', sort=2),
                    MonitorParam(template_key='energy', pkey='gas_m3', label='Φυσικό αέριο (ένδειξη)', unit='m3', sort=3),
                ])
                db.session.commit()
                print('Δημιουργηθηκαν generic templates')

            if not Area.query.first():
                _h = Hotel.query.first()
                if _h:
                    db.session.add(Area(hotel_id=_h.id, template_key='tank', name='Κεντρική Δεξαμενή', location='Μηχανοστάσιο'))
                    db.session.add(Area(hotel_id=_h.id, template_key='energy', name='Γενικός Μετρητής', location='Πίνακας ΔΕΗ'))
                    db.session.commit()
                    print('Δημιουργηθηκαν δειγματικα areas')
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
    if (not EMAIL_PASSWORD and not GRAPH_CLIENT_ID) or not miss:
        return False
    recips = list(EMAIL_TO_LIST)
    for u in User.query.filter_by(is_active=True, approved=True).all():
        if u.email and u.email not in recips:
            recips.append(u.email)
    items = ''.join(f'<li>{m}</li>' for m in miss)
    html = f'<div style="font-family:Arial,sans-serif"><h3 style="color:#193847">Εκκρεμείς καταγραφές σήμερα</h3><ul>{items}</ul><p style="color:#888;font-size:12px">CONDIAN Hotels — αυτόματη υπενθύμιση</p></div>'
    return send_email('Υπενθυμιση καταγραφων - ' + date.today().strftime('%d/%m/%Y'), html, recips)

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
