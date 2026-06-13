# -*- coding: utf-8 -*-
"""
Εστία — Module Αντιγράφων Ασφαλείας (Backups) — v12.33
======================================================
Plug-in (όπως faults.py/surveys.py/imports.py): import από το ΤΕΛΟΣ του app.py,
ΠΡΙΝ το init_db(). Μετά το init_db() καλείται το backup.ensure_backup_columns().

ΣΤΡΑΤΗΓΙΚΗ (Δρόμος Α — off-site, ανεξάρτητο από το Railway):
  Το schema το φτιάχνει ο κώδικας σε κάθε boot → το backup κρατά ΜΟΝΟ δεδομένα.
  Dump όλων των πινάκων -> συμπιεσμένο JSON (.json.gz) με τα πάντα (μετρήσεις,
  βλάβες, ερωτηματολόγια ΚΑΙ base64 εικόνες/avatars/logos). Καθαρό Python — χωρίς
  pg_dump binary. Προορισμός: εταιρικό SharePoint μέσω Microsoft Graph.

ΡΥΘΜΙΣΕΙΣ (v12.33): enabled / ώρες / διατήρηση αποθηκεύονται στη ΒΑΣΗ (Setting) και
  ρυθμίζονται από το UI — αλλάζουν ΧΩΡΙΣ redeploy. Τα env vars χρησιμεύουν μόνο ως
  αρχικές προεπιλογές (seed). Default: 2 φορές/μέρα (03:00 & 15:00), κράτα 30.
  Τα GRAPH_*/SP_* (secrets/προορισμός) παραμένουν env.
"""
import os, io, gzip, json, base64, threading, time, datetime as _dt, urllib.request, urllib.parse
from decimal import Decimal
from flask import request, redirect, url_for, render_template, session, Response

from app import (app, db, current_user, is_admin, has_rank, ROLE_RANK, log_activity, Setting,
                 _graph_token, GRAPH_CLIENT_ID, _athens_now, APP_VERSION, APP_BUILD, _add_col)


def is_master():
    return has_rank(ROLE_RANK['masteradmin'])

# ── Αρχικές προεπιλογές (env seed — μετά ρυθμίζονται από το UI/βάση) ───────────
ENV_ENABLED = os.environ.get('BACKUP_ENABLED', 'false').lower() in ('1', 'true', 'yes', 'on')
ENV_HOURS   = os.environ.get('BACKUP_HOURS', '') or os.environ.get('BACKUP_HOUR', '')  # συμβατότητα
ENV_KEEP    = os.environ.get('BACKUP_KEEP', '30')

# SharePoint target (env)
SP_HOST       = os.environ.get('SP_HOST', '')
SP_SITE_PATH  = os.environ.get('SP_SITE_PATH', '')
SP_FOLDER     = os.environ.get('SP_FOLDER', 'Estia-Backups')

_SITE_ID_CACHE = {'v': None}


# ── Μοντέλο ιστορικού ─────────────────────────────────────────────────────────
class BackupLog(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    filename    = db.Column(db.String(200))
    status      = db.Column(db.String(16), default='running')
    n_tables    = db.Column(db.Integer, default=0)
    n_rows      = db.Column(db.Integer, default=0)
    size_bytes  = db.Column(db.Integer, default=0)
    destination = db.Column(db.String(20), default='sharepoint')
    app_version = db.Column(db.String(10))
    app_build   = db.Column(db.String(10))
    sp_item_id  = db.Column(db.String(200))
    sp_url      = db.Column(db.Text)
    error       = db.Column(db.Text)
    by_user_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at  = db.Column(db.DateTime, default=_dt.datetime.utcnow)


def ensure_backup_columns():
    """Auto-migration νέων στηλών + seed προεπιλογών ρυθμίσεων (idempotent).
    Καλείται από το app.py ΜΕΤΑ το init_db()."""
    with app.app_context():
        try:
            _add_col('backup_log', 'app_version', 'app_version VARCHAR(10)')
            _add_col('backup_log', 'app_build', 'app_build VARCHAR(10)')
        except Exception as e:
            db.session.rollback(); print('[backup] ensure cols skipped:', e)
        # seed ρυθμίσεων αν λείπουν (πρώτη φορά)
        try:
            if Setting.query.get('backup_enabled') is None:
                _setput('enabled', '1' if ENV_ENABLED else '0')
            if Setting.query.get('backup_hours') is None:
                _setput('hours', ENV_HOURS or '3,15')   # default 2 φορές/μέρα
            if Setting.query.get('backup_keep') is None:
                _setput('keep', ENV_KEEP or '30')
            db.session.commit()
        except Exception as e:
            db.session.rollback(); print('[backup] seed settings skipped:', e)


# ── Ρυθμίσεις από τη βάση (Setting) ───────────────────────────────────────────
def _setget(key, default=''):
    s = Setting.query.get('backup_' + key)
    return s.value if (s and s.value is not None) else default

def _setput(key, val):
    s = Setting.query.get('backup_' + key)
    if s:
        s.value = str(val)
    else:
        db.session.add(Setting(key='backup_' + key, value=str(val)))

def get_enabled():
    v = _setget('enabled', '')
    if v == '':
        return ENV_ENABLED
    return v.lower() in ('1', 'true', 'yes', 'on')

def get_hours():
    v = _setget('hours', '') or ENV_HOURS or '3,15'
    hrs = []
    for p in v.replace(' ', '').split(','):
        if p.isdigit() and 0 <= int(p) <= 23:
            hrs.append(int(p))
    return sorted(set(hrs)) or [3]

def get_keep():
    v = _setget('keep', '') or ENV_KEEP
    try:
        return int(v)
    except Exception:
        return 30

def hours_str():
    return ', '.join('%02d:00' % h for h in get_hours())


# ── Serialization ─────────────────────────────────────────────────────────────
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
    tables = list(db.metadata.sorted_tables)
    out = {'estia_backup': 1,
           'created_utc': _dt.datetime.utcnow().isoformat(),
           'app_version': APP_VERSION, 'app_build': APP_BUILD,
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


def _backup_filename():
    ts = _athens_now().strftime('%Y%m%d-%H%M%S')
    return 'estia-backup-v%s-b%s-%s.json.gz' % (APP_VERSION, APP_BUILD, ts)


# ── Microsoft Graph (SharePoint) ──────────────────────────────────────────────
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
    keep = get_keep()
    if keep <= 0:
        return
    items = [x for x in sp_list() if (x.get('name') or '').startswith('estia-backup-')]
    items.sort(key=lambda x: x.get('createdDateTime', ''), reverse=True)
    for old in items[keep:]:
        try:
            sp_delete(old['id'])
        except Exception as e:
            print('[backup] retention delete skipped:', e)


# ── Orchestration ─────────────────────────────────────────────────────────────
def run_backup(by_user_id=None):
    fname = _backup_filename()
    rec = BackupLog(filename=fname, status='running', by_user_id=by_user_id,
                    app_version=APP_VERSION, app_build=APP_BUILD)
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


# ── Scheduler (πολλαπλές ώρες, lock ανά slot μέρα+ώρα) ─────────────────────────
def _backup_tick():
    with app.app_context():
        if not get_enabled():
            return
        now = _athens_now()
        if now.hour not in get_hours():
            return
        slot = now.strftime('%Y-%m-%d %H')
        s = Setting.query.get('backup_last_slot')
        if s and s.value == slot:
            return
        try:
            if s:
                s.value = slot
            else:
                db.session.add(Setting(key='backup_last_slot', value=slot))
            db.session.commit()
        except Exception:
            db.session.rollback(); return   # άλλος worker το ανέλαβε
        run_backup(by_user_id=None)

def _backup_loop():
    time.sleep(90)
    while True:
        try:
            _backup_tick()
        except Exception as e:
            print('[backup] loop error:', e)
        time.sleep(900)   # έλεγχος κάθε 15 λεπτά

def start_backup_scheduler():
    # ξεκινά πάντα· το enabled ελέγχεται δυναμικά (UI) σε κάθε tick
    threading.Thread(target=_backup_loop, daemon=True).start()
    print('[backup] scheduler thread started (έλεγχος δυναμικών ρυθμίσεων από βάση)')


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
                           enabled=get_enabled(), hours_str=hours_str(),
                           hours_raw=_setget('hours', '') or ENV_HOURS or '3,15',
                           keep=get_keep(), app_version=APP_VERSION, app_build=APP_BUILD,
                           is_master=is_master())


@app.route('/dashboard/backup/settings', methods=['POST'])
def backup_settings():
    if not is_admin():
        return redirect(url_for('login'))
    _setput('enabled', '1' if request.form.get('enabled') else '0')
    hrs = (request.form.get('hours') or '').strip()
    _setput('hours', hrs or '3,15')
    keep = (request.form.get('keep') or '').strip()
    _setput('keep', keep if keep.isdigit() else '30')
    db.session.commit()
    log_activity('backup_settings', 'ώρες=%s keep=%s on=%s' % (hrs, keep, bool(request.form.get('enabled'))))
    return redirect(url_for('backup_hub') + '?embed=1&msg=saved')


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
    if not is_admin():
        return redirect(url_for('login'))
    gz, _, _ = dump_bytes()
    log_activity('backup_download', _backup_filename())
    return Response(gz, mimetype='application/gzip',
                    headers={'Content-Disposition': 'attachment; filename=%s' % _backup_filename()})


@app.route('/dashboard/backup/restore', methods=['POST'])
def backup_restore():
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
