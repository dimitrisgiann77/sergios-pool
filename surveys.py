# -*- coding: utf-8 -*-
"""
Εστία — Module Ερωτηματολόγια (v12.23)
======================================
Plug-in: γίνεται `import surveys` από το ΤΕΛΟΣ του app.py (πριν το init_db()).
Πλήρης builder + δημόσιος σύνδεσμος (/s/<token>) + εσωτερικά + αποτελέσματα.
Τύποι ερωτήσεων: rating(1-5), nps(0-10), choice, yesno, text.
"""
import os, csv, uuid, json
from datetime import datetime, timedelta
from flask import request, redirect, url_for, render_template, session, Response, abort
from app import (app, db, current_user, is_admin, allowed_hotels, log_activity,
                 Hotel, User, Setting, active_hotel_id)

QTYPES = ('rating', 'nps', 'choice', 'yesno', 'text')
QTYPE_LABELS = {
    'rating': 'Βαθμολογία 1–5', 'nps': 'NPS (0–10)', 'choice': 'Πολλαπλή επιλογή',
    'yesno': 'Ναι / Όχι', 'text': 'Ελεύθερο κείμενο',
}
AUDIENCES = ('πελάτες', 'προσωπικό')

# ── Μοντέλα ──────────────────────────────────────────────────────────────────
class Survey(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    title        = db.Column(db.String(160), nullable=False)
    description  = db.Column(db.Text)
    audience     = db.Column(db.String(16), default='πελάτες')
    hotel_id     = db.Column(db.Integer, db.ForeignKey('hotel.id'), nullable=True)   # None = όλα
    token        = db.Column(db.String(36), unique=True, index=True)
    is_active    = db.Column(db.Boolean, default=True)
    thank_you    = db.Column(db.String(300), default='Ευχαριστούμε για τον χρόνο σας!')
    created_by   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    hotel        = db.relationship('Hotel')
    questions    = db.relationship('SurveyQuestion', backref='survey',
                                   order_by='SurveyQuestion.sort', cascade='all, delete-orphan')

class SurveyQuestion(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
    text      = db.Column(db.String(300), nullable=False)
    qtype     = db.Column(db.String(10), default='rating')
    options   = db.Column(db.Text)            # γραμμές (για choice)
    required  = db.Column(db.Boolean, default=True)
    sort      = db.Column(db.Integer, default=0)

class SurveyResponse(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    survey_id    = db.Column(db.Integer, db.ForeignKey('survey.id'), nullable=False)
    hotel_id     = db.Column(db.Integer, db.ForeignKey('hotel.id'), nullable=True)
    source       = db.Column(db.String(10), default='public')   # public | internal
    respondent_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name         = db.Column(db.String(120))
    room         = db.Column(db.String(60))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    hotel        = db.relationship('Hotel')
    answers      = db.relationship('SurveyAnswer', backref='response', cascade='all, delete-orphan')

class SurveyAnswer(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey('survey_response.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('survey_question.id'), nullable=False)
    value_num   = db.Column(db.Float, nullable=True)
    value_text  = db.Column(db.Text, nullable=True)
    question    = db.relationship('SurveyQuestion')

# ── Helpers ──────────────────────────────────────────────────────────────────
def _token():
    return uuid.uuid4().hex

def opts_of(q):
    if q.qtype == 'yesno':
        return ['Ναι', 'Όχι']
    return [o.strip() for o in (q.options or '').splitlines() if o.strip()]

def _scoped_surveys():
    q = Survey.query
    aid = active_hotel_id()
    if aid:
        q = q.filter((Survey.hotel_id == aid) | (Survey.hotel_id.is_(None)))
    return q

def response_count(s):
    return SurveyResponse.query.filter_by(survey_id=s.id).count()

def survey_nps(s):
    """NPS από όλες τις nps ερωτήσεις του survey (−100..100) ή None."""
    qids = [q.id for q in s.questions if q.qtype == 'nps']
    if not qids:
        return None
    vals = [a.value_num for a in SurveyAnswer.query.filter(SurveyAnswer.question_id.in_(qids)).all() if a.value_num is not None]
    if not vals:
        return None
    promoters = sum(1 for v in vals if v >= 9)
    detractors = sum(1 for v in vals if v <= 6)
    return round(100.0 * (promoters - detractors) / len(vals))

def survey_avg_rating(s):
    qids = [q.id for q in s.questions if q.qtype == 'rating']
    if not qids:
        return None
    vals = [a.value_num for a in SurveyAnswer.query.filter(SurveyAnswer.question_id.in_(qids)).all() if a.value_num is not None]
    return round(sum(vals) / len(vals), 1) if vals else None

# ── Seed (idempotent) ────────────────────────────────────────────────────────
def seed_surveys():
    with app.app_context():
        try:
            if Setting.query.get('seeded_surveys_v1'):
                return
            if Survey.query.count() == 0:
                s = Survey(title='Ικανοποίηση Πελατών', audience='πελάτες', token=_token(),
                           description='Η γνώμη σας μάς βοηθά να γινόμαστε καλύτεροι. Σας ευχαριστούμε!',
                           thank_you='Ευχαριστούμε θερμά για τον χρόνο και τα σχόλιά σας!')
                db.session.add(s); db.session.flush()
                qs = [
                    ('Πώς θα βαθμολογούσατε τη συνολική σας εμπειρία;', 'rating', None),
                    ('Καθαριότητα δωματίου & χώρων', 'rating', None),
                    ('Εξυπηρέτηση προσωπικού', 'rating', None),
                    ('Πόσο πιθανό είναι να μας συστήσετε σε φίλο/συνάδελφο;', 'nps', None),
                    ('Ποιον χώρο επισκεφθήκατε περισσότερο;', 'choice', 'Πισίνα\nΕστιατόριο\nBar\nΔωμάτιο\nSpa'),
                    ('Θα μας επισκεπτόσασταν ξανά;', 'yesno', None),
                    ('Σχόλια / προτάσεις', 'text', None),
                ]
                for i, (t, qt, op) in enumerate(qs):
                    db.session.add(SurveyQuestion(survey_id=s.id, text=t, qtype=qt, options=op,
                                                  required=(qt != 'text'), sort=i))
                db.session.commit()
            db.session.add(Setting(key='seeded_surveys_v1', value='1'))
            db.session.commit()
            print('[surveys] seeded sample questionnaire')
        except Exception as e:
            db.session.rollback(); print('[surveys] seed skipped:', e)

# ── Admin: λίστα/board ───────────────────────────────────────────────────────
@app.route('/dashboard/surveys')
def surveys_list():
    if not is_admin():
        return redirect(url_for('login'))
    user = current_user()
    surveys = _scoped_surveys().order_by(Survey.is_active.desc(), Survey.id.desc()).all()
    rows = []
    total_resp = 0
    for s in surveys:
        rc = response_count(s)
        total_resp += rc
        rows.append({'s': s, 'responses': rc, 'questions': len(s.questions),
                     'nps': survey_nps(s), 'avg': survey_avg_rating(s)})
    kpi = {
        'active':  sum(1 for r in rows if r['s'].is_active),
        'total':   len(rows),
        'responses': total_resp,
        'today':   SurveyResponse.query.filter(SurveyResponse.submitted_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)).count(),
    }
    return render_template('surveys_list.html', rows=rows, kpi=kpi, user=user,
                           QTYPE_LABELS=QTYPE_LABELS)

@app.route('/dashboard/surveys/new', methods=['POST'])
def survey_new():
    if not is_admin():
        return redirect(url_for('login'))
    title = (request.form.get('title') or '').strip() or 'Νέο ερωτηματολόγιο'
    hid = request.form.get('hotel_id', type=int)
    s = Survey(title=title, audience=request.form.get('audience', 'πελάτες'),
               hotel_id=hid or None, token=_token(), created_by=session.get('user_id'),
               description=(request.form.get('description') or '').strip())
    db.session.add(s); db.session.commit()
    log_activity('survey_create', title, hotel_id=hid or None)
    return redirect(url_for('survey_edit', sid=s.id) + '?embed=1')

@app.route('/dashboard/survey/<int:sid>/edit', methods=['GET', 'POST'])
def survey_edit(sid):
    if not is_admin():
        return redirect(url_for('login'))
    s = Survey.query.get_or_404(sid)
    if request.method == 'POST':
        s.title = (request.form.get('title') or s.title).strip()
        s.description = (request.form.get('description') or '').strip()
        s.audience = request.form.get('audience', s.audience)
        s.thank_you = (request.form.get('thank_you') or s.thank_you).strip()
        hid = request.form.get('hotel_id', type=int)
        s.hotel_id = hid or None
        db.session.commit()
        log_activity('survey_edit', s.title, hotel_id=s.hotel_id)
        return redirect(url_for('survey_edit', sid=s.id) + '?embed=1&saved=1')
    return render_template('survey_edit.html', s=s, hotels=allowed_hotels(current_user()),
                           QTYPES=QTYPES, QTYPE_LABELS=QTYPE_LABELS, AUDIENCES=AUDIENCES,
                           opts_of=opts_of, app_url=_app_url())

@app.route('/dashboard/survey/<int:sid>/question', methods=['POST'])
def survey_question_add(sid):
    if not is_admin():
        return redirect(url_for('login'))
    s = Survey.query.get_or_404(sid)
    text = (request.form.get('text') or '').strip()
    qt = request.form.get('qtype', 'rating')
    if qt not in QTYPES:
        qt = 'rating'
    if text:
        nxt = (max([q.sort for q in s.questions]) + 1) if s.questions else 0
        db.session.add(SurveyQuestion(survey_id=s.id, text=text, qtype=qt,
                                      options=(request.form.get('options') or '').strip() or None,
                                      required=bool(request.form.get('required')), sort=nxt))
        db.session.commit()
    return redirect(url_for('survey_edit', sid=sid) + '?embed=1')

@app.route('/dashboard/survey/<int:sid>/question/<int:qid>/del', methods=['POST'])
def survey_question_del(sid, qid):
    if not is_admin():
        return redirect(url_for('login'))
    q = SurveyQuestion.query.get(qid)
    if q and q.survey_id == sid:
        db.session.delete(q); db.session.commit()
    return redirect(url_for('survey_edit', sid=sid) + '?embed=1')

@app.route('/dashboard/survey/<int:sid>/question/<int:qid>/move', methods=['POST'])
def survey_question_move(sid, qid):
    if not is_admin():
        return redirect(url_for('login'))
    s = Survey.query.get_or_404(sid)
    qlist = list(s.questions)
    idx = next((i for i, q in enumerate(qlist) if q.id == qid), None)
    d = request.form.get('dir')
    if idx is not None:
        j = idx - 1 if d == 'up' else idx + 1
        if 0 <= j < len(qlist):
            qlist[idx].sort, qlist[j].sort = qlist[j].sort, qlist[idx].sort
            db.session.commit()
    return redirect(url_for('survey_edit', sid=sid) + '?embed=1')

@app.route('/dashboard/survey/<int:sid>/toggle', methods=['POST'])
def survey_toggle(sid):
    if not is_admin():
        return redirect(url_for('login'))
    s = Survey.query.get_or_404(sid)
    s.is_active = not s.is_active; db.session.commit()
    return redirect(url_for('surveys_list') + '?embed=1')

@app.route('/dashboard/survey/<int:sid>/delete', methods=['POST'])
def survey_delete(sid):
    if not is_admin():
        return redirect(url_for('login'))
    s = Survey.query.get_or_404(sid)
    SurveyResponse.query.filter_by(survey_id=sid).delete()
    db.session.delete(s); db.session.commit()
    log_activity('survey_delete', s.title)
    return redirect(url_for('surveys_list') + '?embed=1')

# ── Αποτελέσματα ─────────────────────────────────────────────────────────────
@app.route('/dashboard/survey/<int:sid>/results')
def survey_results(sid):
    if not is_admin():
        return redirect(url_for('login'))
    s = Survey.query.get_or_404(sid)
    resp_ids = [r.id for r in SurveyResponse.query.filter_by(survey_id=sid).all()]
    n = len(resp_ids)
    blocks = []
    for q in s.questions:
        ans = SurveyAnswer.query.filter_by(question_id=q.id).all()
        b = {'q': q, 'count': len(ans), 'type': q.qtype}
        if q.qtype == 'rating':
            vals = [a.value_num for a in ans if a.value_num is not None]
            b['avg'] = round(sum(vals) / len(vals), 1) if vals else None
            b['dist'] = [sum(1 for v in vals if round(v) == k) for k in range(1, 6)]
            b['max'] = max(b['dist']) if b['dist'] else 0
        elif q.qtype == 'nps':
            vals = [a.value_num for a in ans if a.value_num is not None]
            if vals:
                pro = sum(1 for v in vals if v >= 9); det = sum(1 for v in vals if v <= 6)
                b['nps'] = round(100.0 * (pro - det) / len(vals))
                b['pro'] = pro; b['pas'] = len(vals) - pro - det; b['det'] = det; b['n'] = len(vals)
            else:
                b['nps'] = None
        elif q.qtype in ('choice', 'yesno'):
            opts = opts_of(q)
            counts = {o: 0 for o in opts}
            for a in ans:
                if a.value_text in counts:
                    counts[a.value_text] += 1
                elif a.value_text:
                    counts[a.value_text] = counts.get(a.value_text, 0) + 1
            b['counts'] = counts
            b['max'] = max(counts.values()) if counts else 0
        else:  # text
            b['texts'] = [a.value_text for a in ans if a.value_text][:50]
        blocks.append(b)
    return render_template('survey_results.html', s=s, blocks=blocks, n=n,
                           nps=survey_nps(s), avg=survey_avg_rating(s), app_url=_app_url(),
                           QTYPE_LABELS=QTYPE_LABELS)

@app.route('/dashboard/survey/<int:sid>/export.csv')
def survey_export_csv(sid):
    if not is_admin():
        return redirect(url_for('login'))
    s = Survey.query.get_or_404(sid)
    qs = list(s.questions)
    import io
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(['Ημ/νία', 'Πηγή', 'Όνομα', 'Δωμάτιο'] + [q.text for q in qs])
    for r in SurveyResponse.query.filter_by(survey_id=sid).order_by(SurveyResponse.submitted_at.desc()).all():
        amap = {a.question_id: a for a in r.answers}
        row = [r.submitted_at.strftime('%d/%m/%Y %H:%M') if r.submitted_at else '', r.source, r.name or '', r.room or '']
        for q in qs:
            a = amap.get(q.id)
            row.append((a.value_text if a and a.value_text is not None else (a.value_num if a and a.value_num is not None else '')))
        w.writerow(row)
    fname = 'survey-%d-%s.csv' % (sid, datetime.utcnow().strftime('%Y%m%d'))
    return Response('﻿' + buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=%s' % fname})

# ── Δημόσια φόρμα ────────────────────────────────────────────────────────────
def _app_url():
    try:
        return (Setting.query.get('app_url').value if Setting.query.get('app_url') else '') or request.host_url.rstrip('/')
    except Exception:
        return ''

@app.route('/s/<token>', methods=['GET', 'POST'])
def survey_public(token):
    s = Survey.query.filter_by(token=token).first()
    if not s or not s.is_active:
        return render_template('survey_public.html', s=None, done=False)
    if request.method == 'POST':
        resp = SurveyResponse(survey_id=s.id, hotel_id=s.hotel_id, source='public',
                              name=(request.form.get('_name') or '').strip()[:120] or None,
                              room=(request.form.get('_room') or '').strip()[:60] or None)
        db.session.add(resp); db.session.flush()
        for q in s.questions:
            raw = (request.form.get('q_%d' % q.id) or '').strip()
            if raw == '':
                continue
            a = SurveyAnswer(response_id=resp.id, question_id=q.id)
            if q.qtype in ('rating', 'nps'):
                try: a.value_num = float(raw)
                except Exception: a.value_num = None
            else:
                a.value_text = raw[:2000]
            db.session.add(a)
        db.session.commit()
        log_activity('survey_response', s.title, hotel_id=s.hotel_id)
        return render_template('survey_public.html', s=s, done=True, opts_of=opts_of)
    return render_template('survey_public.html', s=s, done=False, opts_of=opts_of)

print('[surveys] module loaded')
