# -*- coding: utf-8 -*-
"""
Εστία — extras.py (v12.43): per-role μενού + Feedback χρηστών.
Plug-in: import από το ΤΕΛΟΣ του app.py (πριν το init_db ώστε το create_all να πιάσει το Feedback).
"""
import json
from datetime import datetime
from flask import request, redirect, url_for, render_template, session, jsonify
from app import (app, db, current_user, is_admin, ROLE_RANK, role_rank, log_activity, notify_admins)

# ── MENU ανά ρόλο ─────────────────────────────────────────────────────────────
# Κλειδιά λειτουργικών items (admin workspace μένει πάντα admin-only).
MENU_ITEMS = [
    ('pools',        'Πισίνες'),
    ('water',        'Νερά Χρήσης'),
    ('pools_dash',   'Πίνακας Πισινών'),
    ('records',      'Records'),
    ('coverage',     'Εβδομαδιαία κάλυψη'),
    ('faults_board', 'Πίνακας Βλαβών'),
    ('fault_submit', 'Δήλωση βλάβης'),
    ('areas',        'Καταγραφή τομέων'),
    ('areas_dash',   'Πίνακας τομέων'),
    ('surveys',      'Ερωτηματολόγια'),
    ('schedule',     'Πρόγραμμα Εργασίας'),
    ('whatsnew',     'Τι νέο'),
]
ROLES_CFG = ['manager', 'staff']   # admin/masteradmin = πάντα όλα· viewer = ελάχιστα
# Προεπιλογές ορατότητας ανά ρόλο (manager = υποδοχή: πρόγραμμα/βλάβες/records/τι νέο)
DEFAULT_VIS = {
    'manager': {'records', 'faults_board', 'fault_submit', 'schedule', 'whatsnew', 'pools_dash'},
    'staff':   {'pools', 'water', 'pools_dash', 'records', 'coverage', 'faults_board',
                'fault_submit', 'areas', 'areas_dash', 'whatsnew'},
}

def get_menu_vis():
    from app import Setting
    row = Setting.query.get('menu_vis')
    if row and row.value:
        try:
            return json.loads(row.value)
        except Exception:
            pass
    return {r: sorted(DEFAULT_VIS.get(r, set())) for r in ROLES_CFG}

def _vis_for_role(role):
    cfg = get_menu_vis()
    return set(cfg.get(role, DEFAULT_VIS.get(role, set())))

@app.context_processor
def _inject_menu_show():
    u = current_user()
    role = u.role if u else None
    rank = role_rank(role) if role else -1
    if rank >= ROLE_RANK['admin']:
        allowed = {k for k, _ in MENU_ITEMS}          # admin: όλα
    elif role in ROLES_CFG:
        allowed = _vis_for_role(role)
    elif rank >= ROLE_RANK['staff']:
        allowed = _vis_for_role('staff')
    else:
        allowed = {'whatsnew'}                          # viewer
    return {'menu_show': (lambda key: key in allowed)}

@app.route('/dashboard/menu-roles', methods=['GET', 'POST'])
def menu_roles():
    if not is_admin():
        return redirect(url_for('login'))
    from app import Setting
    if request.method == 'POST':
        cfg = {}
        for r in ROLES_CFG:
            cfg[r] = [k for k, _ in MENU_ITEMS if request.form.get(f'{r}__{k}')]
        row = Setting.query.get('menu_vis')
        if not row:
            row = Setting(key='menu_vis'); db.session.add(row)
        row.value = json.dumps(cfg, ensure_ascii=False)
        db.session.commit()
        log_activity('menu_roles_save')
        return redirect('/dashboard/menu-roles?embed=1&ok=1')
    return render_template('menu_roles.html', items=MENU_ITEMS, roles=ROLES_CFG,
                           vis={r: _vis_for_role(r) for r in ROLES_CFG},
                           role_labels={'manager': 'Manager (υποδοχή)', 'staff': 'Staff'})


# ── FEEDBACK χρηστών ──────────────────────────────────────────────────────────
class Feedback(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'))
    kind       = db.Column(db.String(12), default='idea')   # bug | idea | other
    text       = db.Column(db.Text)
    page       = db.Column(db.String(200))
    status     = db.Column(db.String(10), default='new')    # new | seen | done
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

KIND_LABEL = {'bug': '🐞 Bug', 'idea': '💡 Ιδέα', 'other': '💬 Άλλο'}

@app.route('/feedback', methods=['GET', 'POST'])
def feedback_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    sent = False
    if request.method == 'POST':
        txt = (request.form.get('text') or '').strip()
        if txt:
            fb = Feedback(user_id=session['user_id'], kind=request.form.get('kind', 'idea'),
                          text=txt[:4000], page=(request.form.get('page') or '')[:200])
            db.session.add(fb); db.session.commit()
            try:
                u = current_user()
                notify_admins(f'Νέο feedback ({KIND_LABEL.get(fb.kind, fb.kind)}) από {u.full_name if u else "?"}',
                              '/dashboard/feedback?embed=1')
            except Exception:
                pass
            log_activity('feedback_submit', fb.kind)
            sent = True
    return render_template('feedback_form.html', sent=sent, kinds=KIND_LABEL)

@app.route('/dashboard/feedback', methods=['GET', 'POST'])
def feedback_admin():
    if not is_admin():
        return redirect(url_for('login'))
    from app import User
    if request.method == 'POST':
        fb = Feedback.query.get(request.form.get('id', type=int))
        if fb:
            fb.status = request.form.get('status', fb.status)
            db.session.commit()
        return redirect('/dashboard/feedback?embed=1')
    items = Feedback.query.order_by(Feedback.created_at.desc()).limit(400).all()
    umap = {u.id: u.full_name for u in User.query.all()}
    counts = {'new': Feedback.query.filter_by(status='new').count(),
              'total': Feedback.query.count()}
    return render_template('feedback_admin.html', items=items, umap=umap,
                           kinds=KIND_LABEL, counts=counts)
