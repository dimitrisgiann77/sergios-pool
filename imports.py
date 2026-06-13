# -*- coding: utf-8 -*-
"""
Εστία — Κέντρο Εισαγωγής Δεδομένων (v12.29 / v12.30)
====================================================
Plug-in (όπως faults.py/surveys.py): import από το ΤΕΛΟΣ του app.py, ΠΡΙΝ το init_db().

Πίνακας ΤΟΜΕΙΣ × ΠΗΓΕΣ. Κάθε τομέας τροφοδοτείται από οποιαδήποτε πηγή
(HotelToolbox bundled, Excel/CSV upload, μελλοντικά API/connectors).
Ενεργοί targets upload: Βλάβες (faults), Ερωτηματολόγια (surveys).
"""
import io, csv, hashlib
import unicodedata as _ud
from datetime import datetime
from flask import request, redirect, url_for, render_template, session
from app import (app, db, current_user, is_admin, log_activity, Hotel, BASE_DIR)
import faults as F


class ImportUpload(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    filename     = db.Column(db.String(200))
    target       = db.Column(db.String(30), default='faults')
    status       = db.Column(db.String(16), default='uploaded')
    n_rows       = db.Column(db.Integer, default=0)
    headers_json = db.Column(db.Text)
    data         = db.Column(db.LargeBinary)
    is_csv       = db.Column(db.Boolean, default=False)
    uploaded_by  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    result_json  = db.Column(db.Text)


FAULT_FIELDS = [
    ('hotel',        'Ξενοδοχείο',        True,  ['ξενοδοχειο', 'hotel', 'ξεν']),
    ('description',  'Περιγραφή',         True,  ['περιγραφη', 'description', 'desc', 'σχολια', 'θεμα']),
    ('submitted_at', 'Ημ/νία υποβολής',   False, ['υποβολης', 'υποβολη', 'submitted', 'ημ/νια υποβολης', 'ημερομηνια']),
    ('updated_at',   'Ημ/νία ενημέρωσης', False, ['ενημερωσης', 'updated', 'τελευταιας']),
    ('category',     'Κατηγορία',         False, ['κατηγορια', 'category', 'ειδος']),
    ('priority',     'Προτεραιότητα',     False, ['προτεραιοτητα', 'priority']),
    ('status',       'Κατάσταση',         False, ['κατασταση', 'status']),
    ('location',     'Τοποθεσία',         False, ['τοποθεσια', 'location', 'χωρος']),
    ('room',         'Δωμάτιο',           False, ['δωματιο', 'room']),
    ('from',         'Από (υποβολή)',     False, ['απο', 'from', 'υπευθυνος']),
    ('assignee',     'Ανάθεση σε',        False, ['αναθεση', 'assignee', 'ανατεθηκε']),
    ('completed_by', 'Ολοκληρώθηκε από',  False, ['ολοκληρωθηκε', 'completed']),
]

HT_STATUS_MAP = {
    'ολοκληρωθηκε': 'done', 'αυτοματη αναθεση': 'auto_assigned',
    'εχει υποβληθει ξανα': 'resubmitted', 'υποβληθηκε ξανα': 'resubmitted',
    'προς διεκπεραιωση': 'in_progress', 'σε εξελιξη': 'in_progress',
    'για χειμωνα': 'winter', 'δεν εγινε': 'not_done',
    'ανατεθηκε': 'assigned', 'σε παυση': 'paused', 'αναμενει αναθεση': 'pending_assign',
}


def _norm(s):
    s = (s or '').lower()
    s = ''.join(c for c in _ud.normalize('NFD', s) if _ud.category(c) != 'Mn')
    return ''.join(s.split())


_STATUS_NORM = {_norm(k): v for k, v in HT_STATUS_MAP.items()}


def _parse_upload(data_bytes, is_csv):
    if is_csv:
        text = None
        for enc in ('utf-8-sig', 'utf-8', 'cp1253', 'iso-8859-7'):
            try:
                text = data_bytes.decode(enc); break
            except Exception:
                continue
        if text is None:
            text = data_bytes.decode('utf-8', errors='replace')
        sample = text[:4096]
        delim = ';' if sample.count(';') > sample.count(',') else ','
        allrows = [r for r in csv.reader(io.StringIO(text), delimiter=delim)]
    else:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data_bytes), read_only=True, data_only=True)
        ws = wb.active
        allrows = []
        for r in ws.iter_rows(values_only=True):
            allrows.append(['' if c is None else c for c in r])
        wb.close()
    hidx = 0
    for i, r in enumerate(allrows[:10]):
        if sum(1 for c in r if str(c).strip()) >= 2:
            hidx = i; break
    headers = [str(c).strip() for c in allrows[hidx]] if allrows else []
    rows = [r for r in allrows[hidx + 1:] if any(str(c).strip() for c in r)]
    return headers, rows


def _auto_guess(headers):
    guess = {}
    norm_headers = [_norm(h) for h in headers]
    for key, label, req, syns in FAULT_FIELDS:
        found = None
        cands = [_norm(label)] + [_norm(x) for x in syns] + [_norm(key)]
        for i, nh in enumerate(norm_headers):
            if nh and any(c and (c in nh or nh in c) for c in cands):
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


_PREFIX_NORM = {F._norm_hotel(k): v for k, v in F.HOTEL_PREFIX.items()}


def _resolve_prefix(hotel_val, hid, hotels):
    p = F.HOTEL_PREFIX.get(hotel_val)
    if p:
        return p
    p = _PREFIX_NORM.get(F._norm_hotel(hotel_val))
    if p:
        return p
    hobj = next((h for h in hotels if h.id == hid), None)
    if hobj:
        p = F.HOTEL_PREFIX.get(hobj.name) or _PREFIX_NORM.get(F._norm_hotel(hobj.name))
        if p:
            return p
    return 'GEN'


def import_faults_from_upload(up, mapping):
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
        h8 = hashlib.md5(('|'.join([hotel_val, sub_raw, desc, cat])).encode('utf-8')).hexdigest()[:10].upper()
        prefix = _resolve_prefix(hotel_val, hid, hotels)
        code = 'UPL-%s-%s' % (prefix, h8)
        if code in existing:
            skipped += 1; continue
        st_raw = _cell(row, mapping.get('status'))
        st = st_raw if st_raw in F.STATUSES else _STATUS_NORM.get(_norm(st_raw), '')
        if not st:
            st = 'pending_assign'
        pr = _cell(row, mapping.get('priority'))
        if pr not in F.PRIORITIES:
            pr = 'Κανονική'
        sub = F._ht_parse_dt(sub_raw)
        upd = F._ht_parse_dt(upd_raw)
        completed_at = None
        resolution = None
        if st in F.TERMINAL:
            completed_at = upd or sub
            if sub and completed_at:
                try:
                    resolution = max(0, int((completed_at - sub).total_seconds()))
                except Exception:
                    resolution = None
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


SURVEY_META_FIELDS = [
    ('date',   'Ημερομηνία',      ['ημερομηνια', 'date', 'ημ/νια', 'ημ']),
    ('name',   'Όνομα / Πελάτης', ['πελατης', 'name', 'ονομα', 'email', 'guest']),
    ('room',   'Δωμάτιο',         ['δωματιο', 'room']),
    ('origin', 'Προέλευση',       ['origin', 'προελευση', 'source']),
]

S_QTYPE_LABELS = {'rating': 'Βαθμολογία 1–5', 'nps': 'NPS 0–10', 'choice': 'Επιλογή',
                  'yesno': 'Ναι/Όχι', 'text': 'Κείμενο'}

_GR_MONTHS = {'ιαν': 1, 'φεβ': 2, 'μαρ': 3, 'απρ': 4, 'μαι': 5, 'μαϊ': 5, 'ιουν': 6,
              'ιουλ': 7, 'αυγ': 8, 'σεπ': 9, 'οκτ': 10, 'νοε': 11, 'δεκ': 12}


def _auto_guess_meta(headers):
    guess = {}
    norm_headers = [_norm(h) for h in headers]
    for key, label, syns in SURVEY_META_FIELDS:
        found = None
        cands = [_norm(label)] + [_norm(x) for x in syns] + [_norm(key)]
        for i, nh in enumerate(norm_headers):
            if nh and any(c and (c == nh or c in nh) for c in cands):
                found = i; break
        guess[key] = found
    return guess


def _parse_date_any(s):
    s = (s or '').strip()
    if not s:
        return None
    d = F._ht_parse_dt(s)
    if d:
        return d
    import re as _re
    m = _re.match(r'([Α-Ωα-ωΆ-ώϊΐ]+)\s+(\d{1,2}),?\s+(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?', s)
    if m:
        mon = _GR_MONTHS.get(_norm(m.group(1))[:3])
        if mon:
            try:
                return datetime(int(m.group(3)), mon, int(m.group(2)),
                                int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0))
            except Exception:
                return None
    for fmt in ('%d/%m/%Y %H:%M', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def _detect_qtype(values):
    vals = [str(v).strip() for v in values if str(v).strip() != '']
    if not vals:
        return ('text', None)
    low = {v.lower() for v in vals}
    if low <= {'yes', 'no', 'ναι', 'οχι', 'όχι', 'y', 'n'}:
        return ('yesno', None)
    nums = []
    for v in vals:
        try:
            nums.append(float(v.replace(',', '.')))
        except Exception:
            pass
    if len(nums) >= 0.7 * len(vals):
        mx = max(nums) if nums else 0
        mn = min(nums) if nums else 0
        if mn >= 0 and mx <= 5:
            return ('rating', None)
        if mn >= 0 and mx <= 10:
            return ('nps', None)
        return ('text', None)
    distinct = sorted({v for v in vals})
    if len(distinct) <= 8 and all(len(d) <= 40 for d in distinct):
        return ('choice', '\n'.join(distinct))
    return ('text', None)


def _survey_qcols(headers, meta_map):
    meta_cols = set(v for v in meta_map.values() if v is not None)
    return [(i, str(h).strip()) for i, h in enumerate(headers)
            if str(h).strip() and i not in meta_cols]


def import_surveys_from_upload(up, title, hotel_id, meta_map):
    import surveys as S
    import uuid
    headers, rows = _parse_upload(up.data, up.is_csv)
    qcols = _survey_qcols(headers, meta_map)
    if not qcols:
        return {'error': 'Δεν εντοπίστηκαν στήλες-ερωτήσεις (όλες ορίστηκαν ως μετα-δεδομένα;).'}
    sv = S.Survey.query.filter_by(title=title[:160], hotel_id=hotel_id).first()
    created_survey = False
    if not sv:
        sv = S.Survey(title=title[:160], audience='πελάτες', hotel_id=hotel_id,
                      token=uuid.uuid4().hex, is_active=False,
                      description='Εισαγωγή από αρχείο',
                      created_by=(current_user().id if current_user() else None))
        db.session.add(sv)
        db.session.flush()
        created_survey = True
    existing_q = {q.text.strip(): q for q in sv.questions}
    qmap = {}
    for sort, (idx, htext) in enumerate(qcols):
        htext = htext[:300]
        q = existing_q.get(htext)
        if not q:
            vals = [row[idx] for row in rows if idx < len(row)]
            qtype, opts = _detect_qtype(vals)
            q = S.SurveyQuestion(survey_id=sv.id, text=htext, qtype=qtype, options=opts,
                                 required=False, sort=sort)
            db.session.add(q)
            db.session.flush()
            existing_q[htext] = q
        qmap[idx] = q
    db.session.commit()
    existing_h = set(x[0] for x in db.session.query(S.SurveyResponse.import_hash)
                     .filter(S.SurveyResponse.survey_id == sv.id,
                             S.SurveyResponse.import_hash.isnot(None)).all())
    added = skipped = 0
    for _ridx, row in enumerate(rows):
        dval = _cell(row, meta_map.get('date'))
        nval = _cell(row, meta_map.get('name'))
        rval = _cell(row, meta_map.get('room'))
        joined = '|'.join(_cell(row, i) for i, _ in qcols)
        h40 = hashlib.md5(('%d|%d|%s|%s|%s' % (sv.id, _ridx, dval, nval, joined)).encode('utf-8')).hexdigest()[:40]
        if h40 in existing_h:
            skipped += 1
            continue
        resp = S.SurveyResponse(survey_id=sv.id, hotel_id=hotel_id, source='import',
                                name=(nval[:120] or None), room=(rval[:60] or None),
                                submitted_at=_parse_date_any(dval) or datetime.utcnow(),
                                import_hash=h40)
        db.session.add(resp)
        db.session.flush()
        for idx, q in qmap.items():
            raw = _cell(row, idx)
            if raw == '':
                continue
            num = None
            try:
                num = float(raw.replace(',', '.'))
            except Exception:
                num = None
            if q.qtype in ('rating', 'nps') and num is not None:
                db.session.add(S.SurveyAnswer(response_id=resp.id, question_id=q.id, value_num=num))
            elif q.qtype == 'yesno':
                yes = raw.strip().lower() in ('yes', 'ναι', 'y', '1', 'true')
                db.session.add(S.SurveyAnswer(response_id=resp.id, question_id=q.id,
                                              value_num=(1 if yes else 0), value_text=raw[:500]))
            else:
                db.session.add(S.SurveyAnswer(response_id=resp.id, question_id=q.id,
                                              value_num=num, value_text=raw[:1000]))
        existing_h.add(h40)
        added += 1
        if added % 300 == 0:
            db.session.commit()
    db.session.commit()
    return {'added': added, 'skipped': skipped, 'survey_id': sv.id, 'survey_title': sv.title,
            'questions': len(qmap), 'total': len(rows), 'created_survey': created_survey}


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
    try:
        import surveys as S
        surv_imported = S.SurveyResponse.query.filter_by(source='import').count()
    except Exception:
        surv_imported = 0
    recent = ImportUpload.query.order_by(ImportUpload.id.desc()).limit(8).all()
    return render_template('imports_hub.html', ht_avail=ht_avail, ht_done=ht_done,
                           upl_done=upl_done, surv_imported=surv_imported, recent=recent)


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
    except Exception:
        return redirect(url_for('imports_hub') + '?embed=1&err=parse')
    import json
    up = ImportUpload(filename=name[:200], target=target, is_csv=is_csv, data=raw,
                      n_rows=len(rows), headers_json=json.dumps(headers, ensure_ascii=False),
                      uploaded_by=(current_user().id if current_user() else None))
    db.session.add(up)
    db.session.commit()
    log_activity('import_upload', '%s (%d γραμμές)' % (name, len(rows)))
    return redirect(url_for('imports_map', uid=up.id) + '?embed=1')


@app.route('/dashboard/imports/<int:uid>/map')
def imports_map(uid):
    if not is_admin():
        return redirect(url_for('login'))
    up = ImportUpload.query.get_or_404(uid)
    headers, rows = _parse_upload(up.data, up.is_csv)
    preview = rows[:5]
    if up.target == 'surveys':
        meta_guess = _auto_guess_meta(headers)
        qcols = _survey_qcols(headers, meta_guess)
        qinfo = []
        for idx, htext in qcols:
            qtype, opts = _detect_qtype([row[idx] for row in rows if idx < len(row)])
            qinfo.append({'text': htext, 'type': qtype, 'label': S_QTYPE_LABELS.get(qtype, qtype)})
        hotels = Hotel.query.filter_by(is_active=True).order_by(Hotel.name).all()
        return render_template('imports_map_survey.html', up=up, headers=headers,
                               meta_fields=SURVEY_META_FIELDS, meta_guess=meta_guess,
                               qinfo=qinfo, preview=preview, n_rows=len(rows),
                               default_title=up.filename.rsplit('.', 1)[0], hotels=hotels)
    guess = _auto_guess(headers)
    return render_template('imports_map.html', up=up, headers=headers, fields=FAULT_FIELDS,
                           guess=guess, preview=preview, n_rows=len(rows))


@app.route('/dashboard/imports/<int:uid>/commit', methods=['POST'])
def imports_commit(uid):
    if not is_admin():
        return redirect(url_for('login'))
    up = ImportUpload.query.get_or_404(uid)
    import json

    if up.target == 'surveys':
        title = (request.form.get('title') or up.filename.rsplit('.', 1)[0]).strip()
        hid = request.form.get('hotel_id', type=int) or None
        meta_map = {}
        for key, label, syns in SURVEY_META_FIELDS:
            v = request.form.get('meta_' + key, '')
            meta_map[key] = int(v) if (v not in ('', '-1', None)) else None
        res = import_surveys_from_upload(up, title, hid, meta_map)
        if res.get('error'):
            headers, rows = _parse_upload(up.data, up.is_csv)
            meta_guess = _auto_guess_meta(headers)
            qcols = _survey_qcols(headers, meta_guess)
            qinfo = [{'text': h, 'type': _detect_qtype([r[i] for r in rows if i < len(r)])[0],
                      'label': ''} for i, h in qcols]
            return render_template('imports_map_survey.html', up=up, headers=headers,
                                   meta_fields=SURVEY_META_FIELDS, meta_guess=meta_guess,
                                   qinfo=qinfo, preview=rows[:5], n_rows=len(rows),
                                   default_title=title,
                                   hotels=Hotel.query.filter_by(is_active=True).all(),
                                   error=res['error'])
        up.status = 'done'
        up.result_json = json.dumps(res, ensure_ascii=False)
        db.session.commit()
        log_activity('import_commit', 'surveys "%s" +%s' % (res.get('survey_title'), res.get('added')))
        return render_template('imports_done.html', up=up, res=res, is_survey=True)

    mapping = {}
    for key, label, req, syns in FAULT_FIELDS:
        v = request.form.get('map_' + key, '')
        mapping[key] = int(v) if (v not in ('', '-1', None)) else None
    missing = [label for key, label, req, syns in FAULT_FIELDS if req and mapping.get(key) is None]
    if missing:
        headers, rows = _parse_upload(up.data, up.is_csv)
        return render_template('imports_map.html', up=up, headers=headers, fields=FAULT_FIELDS,
                               guess=mapping, preview=rows[:5], n_rows=len(rows),
                               error='Αντιστοίχισε τα υποχρεωτικά: ' + ', '.join(missing))
    res = import_faults_from_upload(up, mapping)
    up.status = 'done'
    up.result_json = json.dumps(res, ensure_ascii=False)
    db.session.commit()
    log_activity('import_commit', 'faults +%s (skip %s)' % (res.get('added'), res.get('skipped')))
    return render_template('imports_done.html', up=up, res=res)


@app.route('/dashboard/imports/<int:uid>/delete', methods=['POST'])
def imports_delete(uid):
    if not is_admin():
        return redirect(url_for('login'))
    up = ImportUpload.query.get(uid)
    if up:
        db.session.delete(up)
        db.session.commit()
    return redirect(url_for('imports_hub') + '?embed=1')


print('[imports] module loaded')
