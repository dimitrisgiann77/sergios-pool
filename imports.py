# -*- coding: utf-8 -*-
"""
Εστία — Κέντρο Εισαγωγής Δεδομένων (v12.29)
===========================================
Plug-in (όπως faults.py/surveys.py): import από το ΤΕΛΟΣ του app.py, ΠΡΙΝ το init_db().

Στόχος: ένα hub με κάρτα ανά πηγή/module. Δύο τρόποι εισαγωγής:
  (α) bundled αρχεία (π.χ. ιστορικές βλάβες HotelToolbox — βλ. faults.py)
  (β) ανέβασμα Excel/CSV από τον χρήστη → αντιστοίχιση στηλών → προεπισκόπηση → εισαγωγή.

Πρώτος ενεργός στόχος upload: **Βλάβες**. Επόμενα: Ερωτηματολόγια, Παράπονα/Συμβάντα.
"""
import io, csv, hashlib
from datetime import datetime
from flask import request, redirect, url_for, render_template, session
from app import (app, db, current_user, is_admin, log_activity, Hotel, BASE_DIR)
import faults as F

# ── Μοντέλο: προσωρινό ανέβασμα αρχείου ──────────────────────────────────────
class ImportUpload(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    filename    = db.Column(db.String(200))
    target      = db.Column(db.String(30), default='faults')   # ποιο module
    status      = db.Column(db.String(16), default='uploaded') # uploaded|done
    n_rows      = db.Column(db.Integer, default=0)
    headers_json= db.Column(db.Text)                            # JSON λίστα επικεφαλίδων
    data        = db.Column(db.LargeBinary)                     # τα bytes του αρχείου
    is_csv      = db.Column(db.Boolean, default=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    result_json = db.Column(db.Text)

# ── Στόχοι εισαγωγής (επεκτάσιμο registry) ───────────────────────────────────
# κάθε field: (key, ετικέτα, required, [συνώνυμα για auto-guess])
FAULT_FIELDS = [
    ('hotel',        'Ξενοδοχείο',           True,  ['ξενοδοχειο', 'hotel', 'ξεν']),
    ('description',  'Περιγραφή',            True,  ['περιγραφη', 'description', 'desc', 'σχολια', 'θεμα']),
    ('submitted_at', 'Ημ/νία υποβολής',      False, ['υποβολης', 'υποβολη', 'submitted', 'ημ/νια υποβολης', 'ημερομηνια']),
    ('updated_at',   'Ημ/νία ενημέρωσης',    False, ['ενημερωσης', 'updated', 'τελευταιας']),
    ('category',     'Κατηγορία',            False, ['κατηγορια', 'category', 'ειδος']),
    ('priority',     'Προτεραιότητα',        False, ['προτεραιοτητα', 'priority']),
    ('status',       'Κατάσταση',            False, ['κατασταση', 'status']),
    ('location',     'Τοποθεσία',            False, ['τοποθεσια', 'location', 'χωρος']),
    ('room',         'Δωμάτιο',              False, ['δωματιο', 'room']),
    ('from',         'Από (υποβολή)',        False, ['απο', 'from', 'υπευθυνος']),
    ('assignee',     'Ανάθεση σε',           False, ['αναθεση', 'assignee', 'ανατεθηκε']),
    ('completed_by', 'Ολοκληρώθηκε από',     False, ['ολοκληρωθηκε', 'completed']),
]

# HT-style ελληνικές ετικέτες κατάστασης → enum (δέχεται και έτοιμο enum)
HT_STATUS_MAP = {
    'ολοκληρωθηκε': 'done', 'αυτοματη αναθεση': 'auto_assigned',
    'εχει υποβληθει ξανα': 'resubmitted', 'υποβληθηκε ξανα': 'resubmitted',
    'προς διεκπεραιωση': 'in_progress', 'σε εξελιξη': 'in_progress',
    'για χειμωνα': 'winter', 'δεν εγινε': 'not_done',
    'ανατεθηκε': 'assigned', 'σε παυση': 'paused', 'αναμενει αναθεση': 'pending_assign',
}

import unicodedata as _ud
def _norm(s):
    s = (s or '').lower()
    s = ''.join(c for c in _ud.normalize('NFD', s) if _ud.category(c) != 'Mn')
    return ''.join(s.split())

_STATUS_NORM = {_norm(k): v for k, v in HT_STATUS_MAP.items()}

# ── Parsing αρχείου ──────────────────────────────────────────────────────────
def _parse_upload(data_bytes, is_csv):
    """Επιστρέφει (headers:list, rows:list-of-list). Πρώτη μη-κενή γραμμή = headers."""
    if is_csv:
        text = None
        for enc in ('utf-8-sig', 'utf-8', 'cp1253', 'iso-8859-7'):
            try:
                text = data_bytes.decode(enc); break
            except Exception:
                continue
        if text is None:
            text = data_bytes.decode('utf-8', errors='replace')
        # sniff delimiter
        sample = text[:4096]
        delim = ';' if sample.count(';') > sample.count(',') else ','
        rdr = csv.reader(io.StringIO(text), delimiter=delim)
        allrows = [r for r in rdr]
    else:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data_bytes), read_only=True, data_only=True)
        ws = wb.active
        allrows = []
        for r in ws.iter_rows(values_only=True):
            allrows.append(['' if c is None else c for c in r])
        wb.close()
    # βρες την πρώτη γραμμή με ≥2 μη-κενά κελιά = headers
    hidx = 0
    for i, r in enumerate(allrows[:10]):
        nonempty = sum(1 for c in r if str(c).strip())
        if nonempty >= 2:
            hidx = i; break
    headers = [str(c).strip() for c in allrows[hidx]] if allrows else []
    rows = [r for r in allrows[hidx + 1:] if any(str(c).strip() for c in r)]
    return headers, rows

def _auto_guess(headers):
    """Πρόταση αντιστοίχισης: field_key -> column index (ή None)."""
    guess = {}
    norm_headers = [_norm(h) for h in headers]
    for key, label, req, syns in FAULT_FIELDS:
        found = None
        cands = [_norm(label)] + [_norm(x) for x in syns] + [_norm(key)]
        for i, nh in enumerate(norm_headers):
            if not nh:
                continue
            if any(c and (c in nh or nh in c) for c in cands):
                found = i; break
        guess[key] = found
    return guess

def _cell(row, idx):
    if idx is None or idx < 0 or idx >= len(row):
        return ''
    v = row[idx]
    if isinstance(v, datetime):
        return v.strftime('%Y-%m-%d %H:%M:%S')
    return str(v).strip()

# χάρτης normalized ονόματος → prefix (πιάνει «Piskopiano Village Resort» κ.λπ.)
_PREFIX_NORM = {F._norm_hotel(k): v for k, v in F.HOTEL_PREFIX.items()}

def _resolve_prefix(hotel_val, hid, hotels):
    p = F.HOTEL_PREFIX.get(hotel_val)
    if p: return p
    p = _PREFIX_NORM.get(F._norm_hotel(hotel_val))
    if p: return p
    hobj = next((h for h in hotels if h.id == hid), None)
    if hobj:
        p = F.HOTEL_PREFIX.get(hobj.name) or _PREFIX_NORM.get(F._norm_hotel(hobj.name))
        if p: return p
    return 'GEN'

# ── Εισαγωγή γραμμών → Fault (idempotent μέσω hash) ──────────────────────────
def import_faults_from_upload(up, mapping):
    """mapping: dict field_key -> column index. Επιστρέφει stats."""
    headers, rows = _parse_upload(up.data, up.is_csv)
    hotels = Hotel.query.all()
    hmap = {h.name: h.id for h in hotels}
    norm_map = {}
    for h in hotels:
        norm_map.setdefault(F._norm_hotel(h.name), h.id)
    existing = set(c[0] for c in db.session.query(F.Fault.code)
                   .filter(F.Fault.code.like('UPL-%')).all())
    ccache = {}
    added = skipped = nohotel = nodesc = 0
    for row in rows:
        hotel_val = _cell(row, mapping.get('hotel'))
        hid = F._resolve_hotel_id(hotel_val, hmap, norm_map)
        if not hid:
            nohotel += 1; continue
        desc = _cell(row, mapping.get('description'))
        if not desc:
            nodesc += 1; continue
        cat = _cell(row, mapping.get('category'))
        sub_raw = _cell(row, mapping.get('submitted_at'))
        upd_raw = _cell(row, mapping.get('updated_at'))
        # idempotent hash από βασικά πεδία
        h8 = hashlib.md5(('|'.join([hotel_val, sub_raw, desc, cat])).encode('utf-8')).hexdigest()[:10].upper()
        prefix = _resolve_prefix(hotel_val, hid, hotels)
        code = 'UPL-%s-%s' % (prefix, h8)
        if code in existing:
            skipped += 1; continue
        # status
        st_raw = _cell(row, mapping.get('status'))
        st = st_raw if st_raw in F.STATUSES else _STATUS_NORM.get(_norm(st_raw), '')
        if not st:
            st = 'pending_assign'
        # priority
        pr = _cell(row, mapping.get('priority'))
        if pr not in F.PRIORITIES:
            pr = 'Κανονική'
        sub = F._ht_parse_dt(sub_raw)
        upd = F._ht_parse_dt(upd_raw)
        completed_at = None; resolution = None
        if st in F.TERMINAL:
            completed_at = upd or sub
            if sub and completed_at:
                try: resolution = max(0, int((completed_at - sub).total_seconds()))
                except Exception: resolution = None
        cid = F._ht_resolve_category(cat, ccache)
        f = F.Fault(
            code=code, hotel_id=hid, category_id=cid,
            description=desc, priority=pr, status=st,
            source='Εισαγωγή αρχείου',
            submitted_at=sub or datetime.utcnow(), updated_at=upd,
            completed_at=completed_at, resolution_seconds=resolution,
            imported_from='upload',
            legacy_from=(_cell(row, mapping.get('from'))[:120] or None),
            legacy_assignee=(_cell(row, mapping.get('assignee'))[:120] or None),
            legacy_completed_by=(_cell(row, mapping.get('completed_by'))[:120] or None),
            legacy_category=(cat[:200] or None),
            legacy_location=(_cell(row, mapping.get('location'))[:200] or None),
            legacy_room=(_cell(row, mapping.get('room'))[:80] or None),
        )
        db.session.add(f); existing.add(code); added += 1
        if added % 500 == 0:
            db.session.commit()
    db.session.commit()
    return {'added': added, 'skipped': skipped, 'nohotel': nohotel, 'nodesc': nodesc,
            'total': len(rows)}

# ── Routes ───────────────────────────────────────────────────────────────────
def _ht_stats():
    try:
        avail = F.ht_available_count()
        done = F.Fault.query.filter_by(imported_from='hoteltoolbox').count()
    except Exception:
        avail, done = 0, 0
    return avail, done

@app.route('/dashboard/imports')
def imports_hub():
    if not is_admin():
        return redirect(url_for('login'))
    ht_avail, ht_done = _ht_stats()
    upl_done = F.Fault.query.filter_by(imported_from='upload').count()
    recent = ImportUpload.query.order_by(ImportUpload.id.desc()).limit(8).all()
    return render_template('imports_hub.html', ht_avail=ht_avail, ht_done=ht_done,
                           upl_done=upl_done, recent=recent)

@app.route('/dashboard/imports/upload', methods=['POST'])
def imports_upload():
    if not is_admin():
        return redirect(url_for('login'))
    target = request.form.get('target', 'faults')
    file = request.files.get('file')
    if not file or not file.filename:
        return redirect(url_for('imports_hub') + '?embed=1&err=nofile')
    name = file.filename
    is_csv = name.lower().endswith('.csv') or name.lower().endswith('.tsv')
    raw = file.read()
    try:
        headers, rows = _parse_upload(raw, is_csv)
    except Exception as e:
        return redirect(url_for('imports_hub') + '?embed=1&err=parse')
    import json
    up = ImportUpload(filename=name[:200], target=target, is_csv=is_csv, data=raw,
                      n_rows=len(rows), headers_json=json.dumps(headers, ensure_ascii=False),
                      uploaded_by=(current_user().id if current_user() else None))
    db.session.add(up); db.session.commit()
    log_activity('import_upload', '%s (%d γραμμές)' % (name, len(rows)))
    return redirect(url_for('imports_map', uid=up.id) + '?embed=1')

@app.route('/dashboard/imports/<int:uid>/map')
def imports_map(uid):
    if not is_admin():
        return redirect(url_for('login'))
    up = ImportUpload.query.get_or_404(uid)
    import json
    headers = json.loads(up.headers_json or '[]')
    headers, rows = _parse_upload(up.data, up.is_csv)
    guess = _auto_guess(headers)
    preview = rows[:5]
    return render_template('imports_map.html', up=up, headers=headers, fields=FAULT_FIELDS,
                           guess=guess, preview=preview, n_rows=len(rows))

@app.route('/dashboard/imports/<int:uid>/commit', methods=['POST'])
def imports_commit(uid):
    if not is_admin():
        return redirect(url_for('login'))
    up = ImportUpload.query.get_or_404(uid)
    mapping = {}
    for key, label, req, syns in FAULT_FIELDS:
        v = request.form.get('map_' + key, '')
        mapping[key] = int(v) if (v not in ('', '-1', None)) else None
    # required check
    missing = [label for key, label, req, syns in FAULT_FIELDS if req and mapping.get(key) is None]
    if missing:
        import json
        headers, rows = _parse_upload(up.data, up.is_csv)
        return render_template('imports_map.html', up=up, headers=headers, fields=FAULT_FIELDS,
                               guess=mapping, preview=rows[:5], n_rows=len(rows),
                               error='Αντιστοίχισε τα υποχρεωτικά: ' + ', '.join(missing))
    res = import_faults_from_upload(up, mapping)
    import json
    up.status = 'done'; up.result_json = json.dumps(res, ensure_ascii=False)
    db.session.commit()
    log_activity('import_commit', 'faults +%s (skip %s)' % (res.get('added'), res.get('skipped')))
    return render_template('imports_done.html', up=up, res=res)

@app.route('/dashboard/imports/<int:uid>/delete', methods=['POST'])
def imports_delete(uid):
    if not is_admin():
        return redirect(url_for('login'))
    up = ImportUpload.query.get(uid)
    if up:
        db.session.delete(up); db.session.commit()
    return redirect(url_for('imports_hub') + '?embed=1')

print('[imports] module loaded')
