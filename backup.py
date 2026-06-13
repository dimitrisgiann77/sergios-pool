# -*- coding: utf-8 -*-
"""
Εστία — Module Αντιγράφων Ασφαλείας (Backups) — v12.31
======================================================
Plug-in (όπως faults.py/surveys.py/imports.py): import από το ΤΕΛΟΣ του app.py,
ΠΡΙΝ το init_db().

ΣΤΡΑΤΗΓΙΚΗ (Δρόμος Α — off-site, ανεξάρτητο από το Railway):
  Το schema της Εστίας το φτιάχνει ο ίδιος ο κώδικας σε κάθε boot
  (create_all + ensure_columns). Άρα το backup κρατά ΜΟΝΟ δεδομένα.
  Dump όλων των πινάκων -> συμπιεσμένο JSON (.json.gz) που πιάνει τα πάντα
  (μετρήσεις, βλάβες, ερωτηματολόγια ΚΑΙ τις base64 εικόνες/avatars/logos).
  Καθαρό Python (psycopg2 μέσω SQLAlchemy) — ΚΑΝΕΝΑ pg_dump binary, καμία
  εξάρτηση από έκδοση client/server.

ΠΡΟΟΡΙΣΜΟΣ: εταιρικό SharePoint μέσω Microsoft Graph, με τα ΙΔΙΑ app-only
  credentials που χρησιμοποιεί ήδη το email (GRAPH_TENANT_ID/CLIENT_ID/SECRET).
  Απαιτείται στο Azure app registration το permission **Sites.ReadWrite.All**
  (application) + admin consent.

RESTORE: fresh boot (φτιάχνει πίνακες) + φόρτωση του dump (masteradmin,
  με ρητή επιβεβαίωση). Βλ. /dashboard/backup.
"""
import os, io, gzip, json, base64, threading, time, datetime as _dt, urllib.request, urllib.parse
from decimal import Decimal
from flask import request, redirect, url_for, render_template, session, Response

from app import (app, db, current_user, is_admin, has_rank, ROLE_RANK, log_activity, Setting,
                 _graph_token, GRAPH_CLIENT_ID, _athens_now, APP_VERSION)


def is_master():
    return has_rank(ROLE_RANK['masteradmin'])

# ── Ρυθμίσεις (env) ───────────────────────────────────────────────────────────
BACKUP_ENABLED = os.environ.get('BACKUP_ENABLED', 'false').lower() in ('1', 'true', 'yes', 'on')
BACKUP_HOUR    = int(os.environ.get('BACKUP_HOUR', '3'))        # ώρα ημερήσιου backup (Europe/Athens)
BACKUP_KEEP    = int(os.environ.get('BACKUP_KEEP', '30'))       # πόσα αρχεία κρατάμε στο SharePoint

# SharePoint target (μέσω Graph)
SP_HOST       = os.environ.get('SP_HOST', '')                  # π.χ. condianhotels.sharepoint.com
SP_SITE_PATH  = os.environ.get('SP_SITE_PATH', '')             # π.χ. /sites/Estia
SP_FOLDER     = os.environ.get('SP_FOLDER', 'Estia-Backups')   # φάκελος στη βιβλιοθήκη εγγράφων

_SITE_ID_CACHE = {'v': None}


# ── Μοντέλο ιστορικού ─────────────────────────────────────────────────────────
class BackupLog(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    filename    = db.Column(db.String(200))
    status      = db.Column(db.String(16), default='running')   # running/done/error
    n_tables    = db.Column(db.Integer, default=0)
    n_rows      = db.Column(db.Integer, default=0)
    size_bytes  = db.Column(db.Integer, default=0)
    destination = db.Column(db.String(20), default='sharepoint') # sharepoint/local
    sp_item_id  = db.Column(db.String(200))
    sp_url      = db.Column(db.Text)
    error       = db.Column(db.Text)
    by_user_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at  = db.Column(db.DateTime, default=_dt.datetime.utcnow)


# ── Serialization (fidelity για datetime/bytes/Decimal) ───────────────────────
def _enc(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return {'__dt__': v.isoformat()}
    if isinstance(v, _dt.timedelta):
        return {'__td__': v.total_seconds()}
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {'__b64__': base64.b64encode(bytes(v)).decode()}
    if isinstance(v, Decimal):
        return {'__dec__': str(v)}
    return str(v)


def _dec(v):
    if isinstance(v, dict) and len(v) == 1:
        if '__dt__' in v:
            s = v['__dt__']
            for f in (_dt.datetime.fromisoformat, _dt.date.fromisoformat, _dt.time.fromisoformat):
                try:
                    return f(s)
                except Exception:
                    pass
            return s
        if '__td__' in v:
            return _dt.timedelta(seconds=v['__td__'])
        if '__b64__' in v:
            return base64.b64decode(v['__b64__'])
        if '__dec__' in v:
            return Decimal(v['__dec__'])
    return v


def dump_bytes():
    """Όλους τους πίνακες -> gzipped JSON bytes. Σειρά FK-safe (sorted_tables)."""
    tables = list(db.metadata.sorted_tables)   # parents πριν children
    out = {'estia_backup': 1,
           'created_utc': _dt.datetime.utcnow().isoformat(),
           'app_version': APP_VERSION,
           'dialect': (db.engine.dialect.name if db.engine is not None else ''),
           'tables': []}
    total_rows = 0
    for t in tables:
        cols = [c.name for c in t.columns]
        rows = []
        for r in db.session.execute(t.select()).mappings():
            rows.append([_enc(r[c]) for c in cols])
        total_rows += len(rows)
        out['tables'].append({'name': t.name, 'columns': cols, 'rows': rows})
    raw = json.dumps(out, ensure_ascii=False).encode('utf-8')
    gz = gzip.compress(raw, compresslevel=6)
    return gz, len(tables), total_rows


# ── Microsoft Graph (SharePoint upload/list/delete) ───────────────────────────
def _graph(method, url, data=None, token=None, ctype='application/json'):
    token = token or _graph_token()
    headers = {'Authorization': 'Bearer ' + token}
    if data is not None and ctype:
        headers['Content-Type'] = ctype
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
        return r.status, (json.loads(body.decode()) if body else {})


def _site_id(token):
    if _SITE_ID_CACHE['v']:
        return _SITE_ID_CACHE['v']
    if not (SP_HOST and SP_SITE_PATH):
        raise RuntimeError('Λείπουν SP_HOST / SP_SITE_PATH (env).')
    url = 'https://graph.microsoft.com/v1.0/sites/%s:%s' % (SP_HOST, SP_SITE_PATH)
    _, j = _graph('GET', url, token=token)
    _SITE_ID_CACHE['v'] = j['id']
    return j['id']


def sp_upload(filename, content):
    """Simple upload (<250MB) στον φάκελο SP_FOLDER της βιβλιοθήκης του site."""
    token = _graph_token()
    sid = _site_id(token)
    path = urllib.parse.quote('%s/%s' % (SP_FOLDER.strip('/'), filename))
    url = 'https://graph.microsoft.com/v1.0/sites/%s/drive/root:/%s:/content' % (sid, path)
    st, j = _graph('PUT', url, data=content, token=token, ctype='application/octet-stream')
    return j.get('id'), j.get('webUrl')


def sp_list(token=None):
    token = token or _graph_token()
    sid = _site_id(token)
    folder = urllib.parse.quote(SP_FOLDER.strip('/'))
    # ΣΗΜ.: το Graph ΔΕΝ δέχεται $orderby=createdDateTime στα drive children -> ταξινόμηση client-side
    url = ('https://graph.microsoft.com/v1.0/sites/%s/drive/root:/%s:/children'
           '?$select=name,id,size,createdDateTime&$top=200' % (sid, folder))
    try:
        _, j = _graph('GET', url, token=token)
        items = j.get('value', [])
        items.sort(key=lambda x: x.get('createdDateTime', ''), reverse=True)
        return items
    except Exception as e:
        print('[backup] sp_list error:', e)
        return []


def sp_delete(item_id, token=None):
    token = token or _graph_token()
    sid = _site_id(token)
    url = 'https://graph.microsoft.com/v1.0/sites/%s/drive/items/%s' % (sid, item_id)
    _graph('DELETE', url, token=token)


def _retention():
    """Κράτα μόνο τα BACKUP_KEEP πιο πρόσφατα αρχεία με πρόθεμα estia-backup-."""
    if BACKUP_KEEP <= 0:
        return
    items = [x for x in sp_list() if (x.get('name') or '').startswith('estia-backup-')]
    items.sort(key=lambda x: x.get('createdDateTime', ''), reverse=True)
    for old in items[BACKUP_KEEP:]:
        try:
            sp_delete(old['id'])
        except Exception as e:
            print('[backup] retention delete skipped:', e)


# ── Orchestration ─────────────────────────────────────────────────────────────
def run_backup(by_user_id=None):
    """Πλήρης ροή: dump -> upload SharePoint -> log -> retention. Επιστρέφει BackupLog."""
    ts = _athens_now().strftime('%Y%m%d-%H%M%S')
    fname = 'estia-backup-%s.json.gz' % ts
    rec = BackupLog(filename=fname, status='running', by_user_id=by_user_id)
    db.session.add(rec); db.session.commit()
    try:
        gz, n_tables, n_rows = dump_bytes()
        rec.n_tables = n_tables; rec.n_rows = n_rows; rec.size_bytes = len(gz)
        item_id, web_url = sp_upload(fname, gz)
        rec.sp_item_id = item_id; rec.sp_url = web_url
        rec.status = 'done'
        db.session.commit()
        try:
            _retention()
        except Exception as e:
            print('[backup] retention error:', e)
        print('[backup] OK %s (%d πίνακες, %d γραμμές, %.1f KB)' % (fname, n_tables, n_rows, len(gz) / 1024))
    except Exception as e:
        db.session.rollback()
        rec = db.session.get(BackupLog, rec.id)
        if rec:
            rec.status = 'error'; rec.error = str(e)[:500]; db.session.commit()
        print('[backup] ERROR:', e)
    return rec


# ── Scheduler (ημερήσιο, lock μέσω Setting για τους 2 workers) ────────────────
def _backup_tick():
    with app.app_context():
        now = _athens_now()
        if now.hour != BACKUP_HOUR:
            return
        day = now.strftime('%Y-%m-%d')
        key = 'backup_last_day'
        s = Setting.query.get(key)
        if s and s.value == day:
            return
        try:
            if s:
                s.value = day
            else:
                db.session.add(Setting(key=key, value=day))
            db.session.commit()
        except Exception:
            db.session.rollback(); return   # άλλος worker το ανέλαβε
        run_backup(by_user_id=None)


def _backup_loop():
    time.sleep(90)   # να προλάβει το init_db
    while True:
        try:
            _backup_tick()
        except Exception as e:
            print('[backup] loop error:', e)
        time.sleep(1800)   # κάθε 30 λεπτά ελέγχει την ώρα


def start_backup_scheduler():
    if BACKUP_ENABLED:
        threading.Thread(target=_backup_loop, daemon=True).start()
        print('[backup] scheduler started (ώρα %02d:00, keep %d)' % (BACKUP_HOUR, BACKUP_KEEP))
    else:
        print('[backup] scheduler off (BACKUP_ENABLED=false)')


# ── Routes (admin) ────────────────────────────────────────────────────────────
def _config_ok():
    return bool(GRAPH_CLIENT_ID and SP_HOST and SP_SITE_PATH)


@app.route('/dashboard/backup')
def backup_hub():
    if not is_admin():
        return redirect(url_for('login'))
    recent = BackupLog.query.order_by(BackupLog.id.desc()).limit(12).all()
    last_ok = BackupLog.query.filter_by(status='done').order_by(BackupLog.id.desc()).first()
    remote = sp_list() if _config_ok() else []
    return render_template('backup.html',
                           recent=recent, last_ok=last_ok, remote=remote,
                           cfg_ok=_config_ok(), graph_ok=bool(GRAPH_CLIENT_ID),
                           sp_host=SP_HOST, sp_site=SP_SITE_PATH, sp_folder=SP_FOLDER,
                           enabled=BACKUP_ENABLED, hour=BACKUP_HOUR, keep=BACKUP_KEEP,
                           is_master=is_master())


@app.route('/dashboard/backup/run', methods=['POST'])
def backup_run():
    if not is_admin():
        return redirect(url_for('login'))
    if not _config_ok():
        return redirect(url_for('backup_hub') + '?embed=1&err=cfg')
    u = current_user()
    rec = run_backup(by_user_id=u.id if u else None)
    log_activity('backup_run', rec.filename if rec else '—')
    return redirect(url_for('backup_hub') + '?embed=1&msg=' + ('ok' if rec and rec.status == 'done' else 'err'))


@app.route('/dashboard/backup/download', methods=['POST'])
def backup_download():
    """Κατέβασμα τοπικού αντιγράφου (δεν ανεβαίνει στο SharePoint) — χρήσιμο για χειροκίνητο off-site."""
    if not is_admin():
        return redirect(url_for('login'))
    gz, _, _ = dump_bytes()
    fname = 'estia-backup-%s.json.gz' % _athens_now().strftime('%Y%m%d-%H%M%S')
    log_activity('backup_download', fname)
    return Response(gz, mimetype='application/gzip',
                    headers={'Content-Disposition': 'attachment; filename=%s' % fname})


@app.route('/dashboard/backup/restore', methods=['POST'])
def backup_restore():
    """RESTORE από ανεβασμένο .json.gz. ΚΙΝΔΥΝΟΣ: αντικαθιστά δεδομένα.
    masteradmin + ρητή επιβεβαίωση ('ΕΠΑΝΑΦΟΡΑ')."""
    if not is_master():
        return redirect(url_for('login'))
    if (request.form.get('confirm') or '').strip().upper() != 'ΕΠΑΝΑΦΟΡΑ':
        return redirect(url_for('backup_hub') + '?embed=1&err=confirm')
    f = request.files.get('file')
    if not f or not f.filename:
        return redirect(url_for('backup_hub') + '?embed=1&err=nofile')
    try:
        data = json.loads(gzip.decompress(f.read()).decode('utf-8'))
        assert data.get('estia_backup') == 1
        order = list(db.metadata.sorted_tables)
        for t in reversed(order):
            db.session.execute(t.delete())
        loaded = {tb['name']: tb for tb in data.get('tables', [])}
        for t in order:
            tb = loaded.get(t.name)
            if not tb:
                continue
            cols = tb['columns']
            batch = [{c: _dec(v) for c, v in zip(cols, row)} for row in tb['rows']]
            if batch:
                db.session.execute(t.insert(), batch)
        db.session.commit()
        log_activity('backup_restore', f.filename)
        return redirect(url_for('backup_hub') + '?embed=1&msg=restored')
    except Exception as e:
        db.session.rollback()
        print('[backup] restore error:', e)
        return redirect(url_for('backup_hub') + '?embed=1&err=restore')
