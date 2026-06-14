# -*- coding: utf-8 -*-
"""
Εστία — Module «Μισθοδοσία» (Payroll) — Φάση 1 (θεμέλιο & μητρώο)
================================================================
Plug-in: `import payroll` από το ΤΕΛΟΣ του app.py (αφού οριστούν app/db/helpers,
ΠΡΙΝ το init_db() ώστε το create_all να πιάσει τους νέους πίνακες).
Spec: 02_MODULES_ESTIA/ΜΙΣΘΟΔΟΣΙΑ/00_SPEC.md

Φ1: Company, Agreement, EmployeePII, PayrollRates (seed 2026) · Hotel.company_id ·
admin-only (P-08) · όψεις μητρώο/καρτέλα/εταιρείες/συντελεστές · διαβάζει schedule.py.

Αποφάσεις Giannis (14/06): Λογιστήριο όψη = Epsilon import (αλήθεια)· Management = τι
πληρώνεται· ωρομίσθιο = ημερομίσθιο÷8 (Α-02)· μενού νέα ομάδα «Οικονομικά» (Α-08).
ΔΕΝ αλλάζει layout (D-09). Μηχανή/Run/Line/Forecast/Outputs = Φ2+.
"""
import os, re, json, unicodedata
from datetime import datetime, date
from flask import request, redirect, url_for, render_template, session
from app import (app, db, current_user, is_admin, log_activity,
                 Hotel, User, Setting, role_rank, ROLE_RANK)

try:
    from schedule import EmploymentProfile, monthly_settlement  # L1/L2 source (S-13)
except Exception:
    EmploymentProfile = None
    monthly_settlement = None


# ── Χάρτης εταιρειών (SPEC §3) ────────────────────────────────────────────────
COMPANY_MAP = {
    'AST': ('Γ. ΓΙΑΝΝΟΥΛΑΚΗΣ – Α. ΓΙΑΝΝΟΥΛΑΚΗ Α.Ε.', '0002'),
    'CNT': ('Γ. ΓΙΑΝΝΟΥΛΑΚΗΣ – Α. ΓΙΑΝΝΟΥΛΑΚΗ Α.Ε.', None),
    'IRO': ('Γ. ΓΙΑΝΝΟΥΛΑΚΗΣ – Α. ΓΙΑΝΝΟΥΛΑΚΗ Α.Ε.', None),
    'SRG': ('ΑΦΟΙ ΣΕΡΓΙΟΥ Α.Ε.',                       None),
    'PSV': ('ΠΙΣΚΟΠΙΑΝΟ Α.Ε.',                         None),
    'PLM': ('ΦΥΤΩΡΙΑ ΚΡΗΤΗΣ Α.Ε.',                     None),
    'CND': ('CONDIAN HOTELS (HQ / Όμιλος)',            None),
}
COMPANY_CODE = {
    'AST': 'GIAN', 'CNT': 'GIAN', 'IRO': 'GIAN',
    'SRG': 'SERG', 'PSV': 'PISK', 'PLM': 'FYTO', 'CND': 'CND',
}
HOTEL_NAME_CODE = {
    'asterias': 'AST', 'central': 'CNT', 'iro': 'IRO', 'ηρω': 'IRO',
    'sergios': 'SRG', 'piskopiano': 'PSV', 'palmera': 'PLM', 'condian': 'CND',
}


def _acc(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s)) if unicodedata.category(c) != 'Mn')

def _norm(s):
    return re.sub(r'[^a-zα-ω0-9]', '', _acc(s).strip().lower()) if s else ''

def hotel_code(hotel):
    if not hotel:
        return None
    n = _norm(hotel.name)
    for key, code in HOTEL_NAME_CODE.items():
        if _norm(key) in n:
            return code
    return None


# ── ΜΟΝΤΕΛΑ ───────────────────────────────────────────────────────────────────
class Company(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    code         = db.Column(db.String(12), unique=True, index=True)
    legal_name   = db.Column(db.String(160), nullable=False)
    vat          = db.Column(db.String(20))
    subunit_code = db.Column(db.String(20))
    active       = db.Column(db.Boolean, default=True)


class Agreement(db.Model):
    """Συμφωνία με ιστορικό ισχύος (SPEC §4.2). Φ1: δομή + προαιρετική καταγραφή."""
    id                 = db.Column(db.Integer, primary_key=True)
    user_id            = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=False)
    effective_from     = db.Column(db.Date, default=date.today)
    effective_to       = db.Column(db.Date)
    agreement_type     = db.Column(db.String(20), default='Μηνιαίος')
    agreed_amount      = db.Column(db.Float)
    folder_fixed       = db.Column(db.Float, default=0.0)
    hour_wage_override = db.Column(db.Float)
    channels_json      = db.Column(db.Text)
    note               = db.Column(db.String(200))
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)
    created_by         = db.Column(db.Integer, db.ForeignKey('user.id'))


class EmployeePII(db.Model):
    """Ευαίσθητα στοιχεία — ξεχωριστός πίνακας, admin-gated (P-07/GDPR)."""
    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    afm              = db.Column(db.String(12))
    amka             = db.Column(db.String(12))
    ika_am           = db.Column(db.String(15))
    father_name      = db.Column(db.String(80))
    ergani_specialty = db.Column(db.String(120))
    contract_type    = db.Column(db.String(40))
    employment_kind  = db.Column(db.String(40))
    bank_name        = db.Column(db.String(60))
    bank_iban        = db.Column(db.String(34))
    hired_at         = db.Column(db.Date)
    left_at          = db.Column(db.Date)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by       = db.Column(db.Integer, db.ForeignKey('user.id'))


class PayrollRates(db.Model):
    """Συντελεστές ανά έτος (admin-editable). Seed 2026 ΓΙΑ ΕΚΤΙΜΗΣΗ/ΠΡΟΒΛΕΨΗ.
       Η αλήθεια των νόμιμων καθαρών έρχεται από Epsilon import."""
    id                    = db.Column(db.Integer, primary_key=True)
    year                  = db.Column(db.Integer, unique=True, index=True, nullable=False)
    efka_employee_pct     = db.Column(db.Float, default=13.87)
    efka_employer_pct     = db.Column(db.Float, default=22.29)
    efka_aux_employee_pct = db.Column(db.Float, default=3.25)
    efka_aux_employer_pct = db.Column(db.Float, default=3.25)
    tax_free_threshold    = db.Column(db.Float, default=8636.0)
    tax_brackets_json     = db.Column(db.Text)
    digital_fee           = db.Column(db.Float, default=0.0)
    note                  = db.Column(db.String(200))
    valid_from            = db.Column(db.Date)
    valid_to              = db.Column(db.Date)


TAX_BRACKETS_2026 = [[10000, 9], [20000, 22], [30000, 28], [40000, 36], [None, 44]]


# ── AUTH (admin-only — P-08) ──────────────────────────────────────────────────
def _padmin():
    return ('user_id' in session) and is_admin()


# ── MIGRATION (μη καταστροφικό) ───────────────────────────────────────────────
def ensure_payroll_columns():
    with app.app_context():
        try:
            from app import _add_col
            _add_col('hotel', 'company_id', 'company_id INTEGER')
        except Exception as e:
            print('ensure_payroll_columns skipped:', e)


# ── SEED (idempotent) ─────────────────────────────────────────────────────────
def seed_payroll():
    with app.app_context():
        try:
            seen = {}
            for hcode, ccode in COMPANY_CODE.items():
                if ccode in seen:
                    continue
                legal, sub = COMPANY_MAP[hcode]
                if not Company.query.filter_by(code=ccode).first():
                    db.session.add(Company(code=ccode, legal_name=legal, subunit_code=sub))
                seen[ccode] = True
            db.session.commit()

            comp_by_code = {c.code: c for c in Company.query.all()}
            for h in Hotel.query.all():
                if getattr(h, 'company_id', None):
                    continue
                hc = hotel_code(h)
                cc = COMPANY_CODE.get(hc)
                if cc and cc in comp_by_code:
                    h.company_id = comp_by_code[cc].id
            db.session.commit()

            if not PayrollRates.query.filter_by(year=2026).first():
                db.session.add(PayrollRates(
                    year=2026,
                    tax_brackets_json=json.dumps(TAX_BRACKETS_2026, ensure_ascii=False),
                    note='Seed εκτίμησης (η αλήθεια από Epsilon import). Admin-editable.',
                    valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31)))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print('seed_payroll skipped:', e)


# ── HELPERS ───────────────────────────────────────────────────────────────────
def _company_for_hotel(hotel_id):
    h = Hotel.query.get(hotel_id) if hotel_id else None
    if h and getattr(h, 'company_id', None):
        return Company.query.get(h.company_id)
    return None

def _employees():
    users = (User.query
             .filter((User.employment_active == True) | (User.employment_active.is_(None)))
             .all())
    out = []
    for u in users:
        prof = EmploymentProfile.query.filter_by(user_id=u.id).first() if EmploymentProfile else None
        pii = EmployeePII.query.filter_by(user_id=u.id).first()
        has_hr = bool(prof or pii or getattr(u, 'home_hotel_id', None) or getattr(u, 'department_id', None))
        if not has_hr:
            continue
        hid = getattr(u, 'home_hotel_id', None)
        comp = _company_for_hotel(hid)
        hotel = Hotel.query.get(hid) if hid else None
        out.append({'user': u, 'profile': prof, 'pii': pii, 'company': comp,
                    'hotel_name': (hotel.name if hotel else '')})
    out.sort(key=lambda r: (r['company'].legal_name if r['company'] else 'ω', r['user'].full_name or ''))
    return out


# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.route('/dashboard/payroll')
def payroll_home():
    if not _padmin():
        return redirect(url_for('login'))
    rows = _employees()
    companies = Company.query.filter_by(active=True).order_by(Company.legal_name).all()
    n_emp = len(rows)
    n_agree = sum(1 for r in rows if r['profile'] and r['profile'].agreement_amount)
    n_pii = sum(1 for r in rows if r['pii'] and r['pii'].afm)
    rates = PayrollRates.query.filter_by(year=2026).first()
    log_activity('payroll_view', 'μητρώο')
    return render_template('payroll_home.html',
        rows=rows, companies=companies, n_emp=n_emp, n_agree=n_agree, n_pii=n_pii,
        rates=rates, is_admin=is_admin())


@app.route('/dashboard/payroll/companies', methods=['GET', 'POST'])
def payroll_companies():
    if not _padmin():
        return redirect(url_for('login'))
    if request.method == 'POST':
        cid = request.form.get('id', type=int)
        c = Company.query.get(cid) if cid else None
        if c:
            c.legal_name   = (request.form.get('legal_name') or c.legal_name).strip()
            c.vat          = (request.form.get('vat') or '').strip() or None
            c.subunit_code = (request.form.get('subunit_code') or '').strip() or None
            c.active       = request.form.get('active') == '1'
            db.session.commit()
            log_activity('payroll_company_edit', c.legal_name)
        return redirect(url_for('payroll_companies'))
    companies = Company.query.order_by(Company.legal_name).all()
    hcount = {}
    for h in Hotel.query.all():
        cid = getattr(h, 'company_id', None)
        if cid:
            hcount.setdefault(cid, []).append(h.name)
    return render_template('payroll_companies.html', companies=companies, hcount=hcount, is_admin=is_admin())


@app.route('/dashboard/payroll/rates', methods=['GET', 'POST'])
def payroll_rates():
    if not _padmin():
        return redirect(url_for('login'))
    r = PayrollRates.query.filter_by(year=2026).first()
    if not r:
        r = PayrollRates(year=2026, tax_brackets_json=json.dumps(TAX_BRACKETS_2026, ensure_ascii=False))
        db.session.add(r); db.session.commit()
    if request.method == 'POST':
        def _f(name, cur):
            v = request.form.get(name)
            try:
                return float(v) if v not in (None, '') else cur
            except Exception:
                return cur
        r.efka_employee_pct     = _f('efka_employee_pct', r.efka_employee_pct)
        r.efka_employer_pct     = _f('efka_employer_pct', r.efka_employer_pct)
        r.efka_aux_employee_pct = _f('efka_aux_employee_pct', r.efka_aux_employee_pct)
        r.efka_aux_employer_pct = _f('efka_aux_employer_pct', r.efka_aux_employer_pct)
        r.tax_free_threshold    = _f('tax_free_threshold', r.tax_free_threshold)
        r.digital_fee           = _f('digital_fee', r.digital_fee)
        r.note                  = (request.form.get('note') or '').strip() or r.note
        db.session.commit()
        log_activity('payroll_rates_edit', '2026')
        return redirect(url_for('payroll_rates'))
    try:
        brackets = json.loads(r.tax_brackets_json or '[]')
    except Exception:
        brackets = []
    return render_template('payroll_rates.html', r=r, brackets=brackets, is_admin=is_admin())


@app.route('/dashboard/payroll/employee/<int:uid>', methods=['GET', 'POST'])
def payroll_employee(uid):
    if not _padmin():
        return redirect(url_for('login'))
    u = User.query.get_or_404(uid)
    prof = EmploymentProfile.query.filter_by(user_id=uid).first() if EmploymentProfile else None
    pii = EmployeePII.query.filter_by(user_id=uid).first()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'pii':
            if not pii:
                pii = EmployeePII(user_id=uid); db.session.add(pii)
            for f in ('afm', 'amka', 'ika_am', 'father_name', 'ergani_specialty',
                      'contract_type', 'employment_kind', 'bank_name', 'bank_iban'):
                setattr(pii, f, (request.form.get(f) or '').strip() or None)
            for f in ('hired_at', 'left_at'):
                v = request.form.get(f)
                try:
                    setattr(pii, f, datetime.strptime(v, '%Y-%m-%d').date() if v else None)
                except Exception:
                    pass
            cu = current_user()
            pii.updated_by = cu.id if cu else None
            db.session.commit()
            log_activity('payroll_pii_edit', u.full_name or u.username)
        elif action == 'agreement' and prof is not None:
            amt = request.form.get('agreement_amount')
            try:
                prof.agreement_amount = float(amt) if amt not in (None, '') else prof.agreement_amount
            except Exception:
                pass
            prof.agreement_type = request.form.get('agreement_type') or prof.agreement_type
            db.session.commit()
            log_activity('payroll_agreement_edit', u.full_name or u.username)
        return redirect(url_for('payroll_employee', uid=uid))
    comp = _company_for_hotel(getattr(u, 'home_hotel_id', None))
    hotel = Hotel.query.get(u.home_hotel_id) if getattr(u, 'home_hotel_id', None) else None
    agreements = (Agreement.query.filter_by(user_id=uid)
                  .order_by(Agreement.effective_from.desc()).all())
    return render_template('payroll_employee.html',
        u=u, prof=prof, pii=pii, comp=comp, hotel=hotel, agreements=agreements, is_admin=is_admin())


print('payroll module loaded (Φ1)')
