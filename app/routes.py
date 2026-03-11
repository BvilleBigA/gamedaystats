"""Flask routes for the baseball stats app."""

import hashlib
from types import SimpleNamespace
import json
import os
import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, send_from_directory, current_app
from app import db
from app.models import (
    Season, Team, Player, Game, InningScore,
    BattingStats, PitchingStats, FieldingStats,
    User, UserPermission, UserSchoolPermission, School, GameVersion, Play,
)

main_bp = Blueprint("main", __name__)


# ── Helper functions ──────────────────────────────────────────────────────────


def _aggregate_batting(stats_query):
    """Aggregate batting stats from a list of BattingStats objects."""
    stats = stats_query
    if not stats:
        return None
    totals = {
        "gp": len(set(s.game_id for s in stats)),
        "ab": sum(s.ab for s in stats),
        "r": sum(s.r for s in stats),
        "h": sum(s.h for s in stats),
        "rbi": sum(s.rbi for s in stats),
        "doubles": sum(s.doubles for s in stats),
        "triples": sum(s.triples for s in stats),
        "hr": sum(s.hr for s in stats),
        "bb": sum(s.bb for s in stats),
        "so": sum(s.so for s in stats),
        "sb": sum(s.sb for s in stats),
        "cs": sum(s.cs for s in stats),
        "hbp": sum(s.hbp for s in stats),
        "sh": sum(s.sh for s in stats),
        "sf": sum(s.sf for s in stats),
        "gdp": sum(s.gdp for s in stats),
        "kl": sum(s.kl for s in stats),
    }
    ab = totals["ab"]
    h = totals["h"]
    bb = totals["bb"]
    hbp = totals["hbp"]
    sf = totals["sf"]
    singles = h - totals["doubles"] - totals["triples"] - totals["hr"]
    tb = singles + 2 * totals["doubles"] + 3 * totals["triples"] + 4 * totals["hr"]

    totals["avg"] = f"{h / ab:.3f}" if ab > 0 else ".000"
    denom = ab + bb + hbp + sf
    totals["obp"] = f"{(h + bb + hbp) / denom:.3f}" if denom > 0 else ".000"
    totals["slg"] = f"{tb / ab:.3f}" if ab > 0 else ".000"
    obp_val = (h + bb + hbp) / denom if denom > 0 else 0.0
    slg_val = tb / ab if ab > 0 else 0.0
    totals["ops"] = f"{obp_val + slg_val:.3f}"
    return totals


def _aggregate_pitching(stats_list):
    """Aggregate pitching stats from a list of PitchingStats objects."""
    if not stats_list:
        return None

    # IP is stored as e.g. 4.1 meaning 4 and 1/3
    total_thirds = 0
    for s in stats_list:
        ip_full = int(s.ip)
        ip_frac = round((s.ip - ip_full) * 10)
        total_thirds += ip_full * 3 + ip_frac

    ip_display_full = total_thirds // 3
    ip_display_frac = total_thirds % 3
    ip_display = f"{ip_display_full}.{ip_display_frac}" if ip_display_frac else str(ip_display_full)

    totals = {
        "gp": len(set(s.game_id for s in stats_list)),
        "gs": sum(s.gs for s in stats_list),
        "ip": ip_display,
        "h": sum(s.h for s in stats_list),
        "r": sum(s.r for s in stats_list),
        "er": sum(s.er for s in stats_list),
        "bb": sum(s.bb for s in stats_list),
        "so": sum(s.so for s in stats_list),
        "hr": sum(s.hr for s in stats_list),
        "hbp": sum(s.hbp for s in stats_list),
        "bf": sum(s.bf for s in stats_list),
        "wp": sum(s.wp for s in stats_list),
        "bk": sum(s.bk for s in stats_list),
        "pitches": sum(s.pitches for s in stats_list),
        "strikes": sum(s.strikes for s in stats_list),
        "cg": sum(s.cg for s in stats_list),
        "sho": sum(s.sho for s in stats_list),
        "w": sum(1 for s in stats_list if s.win),
        "l": sum(1 for s in stats_list if s.loss),
        "sv": sum(1 for s in stats_list if s.save),
    }

    er = totals["er"]
    # ERA based on scheduled innings (7 for softball default)
    totals["era"] = f"{(er * 7 * 3) / total_thirds:.2f}" if total_thirds > 0 else "0.00"
    totals["whip"] = f"{(totals['bb'] + totals['h']) / (total_thirds / 3):.2f}" if total_thirds > 0 else "0.00"
    return totals


def _aggregate_fielding(stats_list):
    """Aggregate fielding stats."""
    if not stats_list:
        return None
    totals = {
        "gp": len(set(s.game_id for s in stats_list)),
        "po": sum(s.po for s in stats_list),
        "a": sum(s.a for s in stats_list),
        "e": sum(s.e for s in stats_list),
        "pb": sum(s.pb for s in stats_list),
        "sba": sum(s.sba for s in stats_list),
    }
    tc = totals["po"] + totals["a"] + totals["e"]
    totals["tc"] = tc
    totals["fpct"] = f"{(totals['po'] + totals['a']) / tc:.3f}" if tc > 0 else "1.000"
    return totals


# ── Main routes ───────────────────────────────────────────────────────────────


@main_bp.route("/")
def index():
    return redirect(url_for('main.admin'))



# ── GWT / Gameday Stats frontend routes ─────────────────────────────────────


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '')
        password = request.form.get('password', '')
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        user = User.query.filter_by(username=email, password_sha256=pw_hash, is_active=True).first()
        if user:
            session['user_id'] = user.id
            next_url = request.args.get('next') or url_for('main.gameday')
            return redirect(next_url)
        flash('Invalid credentials')
    return render_template('login.html')


@main_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('main.login'))


@main_bp.route('/admin')
def admin():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('main.login'))
    return redirect(url_for('main.gameday'))


@main_bp.route('/admin/user', methods=['GET', 'POST'])
def account():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('main.login', next=request.url))
    current_user = User.query.get(user_id)
    if not current_user:
        session.pop('user_id', None)
        return redirect(url_for('main.login'))

    error = None
    success = None
    action = request.form.get('action') if request.method == 'POST' else None

    if action == 'update_profile':
        new_email = request.form.get('email', '').strip()
        if new_email:
            existing = User.query.filter_by(username=new_email).first()
            if existing and existing.id != current_user.id:
                error = 'That email is already in use.'
            else:
                current_user.username = new_email
        current_user.phone = request.form.get('phone', '').strip()
        if not error:
            db.session.commit()
            success = 'Profile updated.'

    elif action == 'change_password':
        current_pw = request.form.get('current_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')
        if hashlib.sha256(current_pw.encode()).hexdigest() != current_user.password_sha256:
            error = 'Current password is incorrect.'
        elif not new_pw:
            error = 'New password cannot be empty.'
        elif new_pw != confirm_pw:
            error = 'New passwords do not match.'
        else:
            current_user.password_sha256 = hashlib.sha256(new_pw.encode()).hexdigest()
            db.session.commit()
            success = 'Password changed.'

    return render_template('account.html',
                           current_user=current_user,
                           error=error, success=success)


def _user_management_assets():
    """Resolve built React asset paths for user management SPA."""
    import glob
    base = os.path.join(current_app.root_path, 'static', 'user-management', 'assets')
    if not os.path.isdir(base):
        return None, None
    js_files = glob.glob(os.path.join(base, 'index-*.js'))
    css_files = glob.glob(os.path.join(base, 'index-*.css'))
    js_path = ('/static/user-management/assets/' + os.path.basename(js_files[0])) if js_files else None
    css_path = ('/static/user-management/assets/' + os.path.basename(css_files[0])) if css_files else None
    return js_path, css_path


@main_bp.route('/admin/user/manage-users', methods=['GET'])
@main_bp.route('/admin/user/manage-users/permissions/<int:user_id>', methods=['GET'])
@main_bp.route('/admin/user/manage-database', methods=['GET'])
def manage_users(user_id=None):
    """Admin-only: Serve React user management SPA."""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('main.login', next=request.url))
    current_user = User.query.get(user_id)
    if not current_user:
        session.pop('user_id', None)
        return redirect(url_for('main.login'))
    if current_user.role != 'admin':
        return redirect(url_for('main.account'))

    asset_js, asset_css = _user_management_assets()
    if not asset_js:
        return render_template('manage_users_spa.html', asset_js=None, asset_css=None,
                               build_required=True)
    return render_template('manage_users_spa.html',
                           asset_js=asset_js, asset_css=asset_css,
                           build_required=False)




@main_bp.route('/action/stats/statsentry/statGame.jsp')
def statgame():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('main.login', next=request.url))
    current_user = User.query.get(user_id)
    if not current_user:
        session.pop('user_id', None)
        return redirect(url_for('main.login'))

    season_id = request.args.get('season_id')
    event_id = request.args.get('event_id')
    sport_code = request.args.get('sport_code', '1')

    if not season_id:
        first_season = Season.query.first()
        season_id = str(first_season.id) if first_season else '1'
    if not event_id:
        first_game = Game.query.first()
        event_id = str(first_game.id) if first_game else '1'

    game = Game.query.get(int(event_id)) if event_id.isdigit() else None

    # Convert YYYY-MM-DD → M/D/YYYY (required by isLoadingOneGame() for auto-auth)
    event_date = ''
    if game and game.date:
        parts = game.date.split('-')
        if len(parts) == 3:
            event_date = f"{int(parts[1])}/{int(parts[2])}/{parts[0]}"
    if not event_date:
        # Fallback so isLoadingOneGame() doesn't abort auto-auth
        from datetime import date
        today = date.today()
        event_date = f"{today.month}/{today.day}/{today.year}"

    return render_template('statgame.html',
                           current_user=current_user,
                           season_id=season_id,
                           event_id=event_id,
                           sport_code=sport_code,
                           event_date=event_date)


@main_bp.route('/action/stats/statsentry/<path:filename>')
def statsentry_static(filename):
    base = os.path.join(current_app.root_path, 'static', 'presto', 'statsentry')
    filepath = os.path.join(base, filename)
    # Fallback: serve the WebKit cache file for any unknown .cache.js request
    if 'statentry/' in filename and filename.endswith('.cache.js') and not os.path.exists(filepath):
        filename = 'statentry/9CF75CF4CE787752B1D6376959488943.cache.js'
    return send_from_directory(base, filename)


# ── Gameday admin page ────────────────────────────────────────────────────────

def _require_login():
    """Return (user, None) or (None, redirect_response)."""
    user_id = session.get('user_id')
    if not user_id:
        return None, redirect(url_for('main.login', next=request.url))
    user = User.query.get(user_id)
    if not user:
        session.pop('user_id', None)
        return None, redirect(url_for('main.login'))
    return user, None


def _require_admin_json():
    """Return (user, None) or (None, json_error_response). For API endpoints."""
    user_id = session.get('user_id')
    if not user_id:
        return None, (jsonify({"error": "Not authenticated"}), 401)
    user = User.query.get(user_id)
    if not user:
        session.pop('user_id', None)
        return None, (jsonify({"error": "Not authenticated"}), 401)
    if user.role != 'admin':
        return None, (jsonify({"error": "Admin only"}), 403)
    return user, None


def _user_to_json(u):
    """Convert User to dict for API responses."""
    parts = (u.display_name or '').strip().split(None, 1)
    first_name = parts[0] if parts else ''
    last_name = parts[1] if len(parts) > 1 else ''
    if not first_name and u.username:
        first_name = u.username.split('@')[0]
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or '',
        "first_name": first_name,
        "last_name": last_name,
        "phone": u.phone or '',
        "role": u.role,
        "is_active": u.is_active,
    }


# ── Admin REST API (for React user management SPA) ────────────────────────────


@main_bp.route('/api/admin/me', methods=['GET'])
def api_admin_me():
    """Current user for React SPA. 401 if not logged in, 403 if not admin."""
    user, err = _require_admin_json()
    if err:
        return err
    school = School.query.first()
    return jsonify({
        "user": _user_to_json(user),
        "account_name": school.name if school else "Gameday Stats",
    })


@main_bp.route('/api/admin/users', methods=['GET'])
def api_admin_users_list():
    """List all users. Admin only."""
    user, err = _require_admin_json()
    if err:
        return err
    school = School.query.first()
    account_name = school.name if school else "Gameday Stats"
    users_raw = User.query.order_by(User.username).all()
    users = [_user_to_json(u) for u in users_raw]
    return jsonify({"account_name": account_name, "users": users})


@main_bp.route('/api/admin/users', methods=['POST'])
def api_admin_users_create():
    """Add a new user. Admin only."""
    user, err = _require_admin_json()
    if err:
        return err
    data = request.get_json() or {}
    email = (data.get('email') or '').strip()
    password = (data.get('password') or '').strip()
    first_name = (data.get('first_name') or '').strip()
    last_name = (data.get('last_name') or '').strip()
    phone = (data.get('phone') or '').strip()
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400
    if User.query.filter_by(username=email).first():
        return jsonify({"error": f'Email "{email}" already exists.'}), 400
    display_name = f"{first_name} {last_name}".strip() or email
    new_user = User(
        username=email,
        password_sha256=hashlib.sha256(password.encode()).hexdigest(),
        display_name=display_name,
        phone=phone,
        role='scorer',
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"ok": True, "user": _user_to_json(new_user)}, 201)


@main_bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
def api_admin_users_delete(user_id):
    """Delete a user. Admin only. Cannot delete self."""
    user, err = _require_admin_json()
    if err:
        return err
    if user.id == user_id:
        return jsonify({"error": "Cannot delete yourself."}), 400
    target = User.query.get(user_id)
    if not target:
        return jsonify({"error": "User not found."}), 404
    UserPermission.query.filter_by(user_id=user_id).delete()
    UserSchoolPermission.query.filter_by(user_id=user_id).delete()
    db.session.delete(target)
    db.session.commit()
    return jsonify({"ok": True})


@main_bp.route('/api/admin/users/<int:user_id>/permissions', methods=['GET'])
def api_admin_user_permissions_list(user_id):
    """List school permissions for a user. Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    target = User.query.get(user_id)
    if not target:
        return jsonify({"error": "User not found."}), 404
    perms = UserSchoolPermission.query.filter_by(user_id=user_id).all()
    items = []
    for p in perms:
        items.append({
            "id": p.id,
            "school_id": p.school_id,
            "school_name": p.school.name if p.school else "",
        })
    return jsonify({"permissions": items, "user": _user_to_json(target)})


@main_bp.route('/api/admin/users/<int:user_id>/permissions', methods=['POST'])
def api_admin_user_permissions_add(user_id):
    """Add a school permission for a user. Grants access to all seasons for that school. Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    target = User.query.get(user_id)
    if not target:
        return jsonify({"error": "User not found."}), 404
    data = request.get_json() or {}
    school_id = data.get('school_id')
    if not school_id:
        return jsonify({"error": "school_id is required."}), 400
    school = School.query.get(int(school_id))
    if not school:
        return jsonify({"error": "School not found."}), 400
    existing = UserSchoolPermission.query.filter_by(
        user_id=user_id, school_id=school.id
    ).first()
    if existing:
        return jsonify({"error": "User already has access to this school."}), 400
    perm = UserSchoolPermission(user_id=user_id, school_id=school.id)
    db.session.add(perm)
    db.session.commit()
    return jsonify({
        "ok": True,
        "permission": {
            "id": perm.id,
            "school_id": perm.school_id,
            "school_name": perm.school.name,
        },
    }, 201)


@main_bp.route('/api/admin/users/<int:user_id>/permissions/<int:perm_id>', methods=['DELETE'])
def api_admin_user_permissions_remove(user_id, perm_id):
    """Remove a school permission. Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    perm = UserSchoolPermission.query.filter_by(id=perm_id, user_id=user_id).first()
    if not perm:
        return jsonify({"error": "Permission not found."}), 404
    db.session.delete(perm)
    db.session.commit()
    return jsonify({"ok": True})


@main_bp.route('/api/admin/schools', methods=['GET'])
def api_admin_schools_list():
    """List schools. Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    schools = School.query.order_by(School.name).all()
    items = []
    for s in schools:
        teams = [{"id": t.id, "season_id": t.season_id, "season_name": t.season.name if t.season else ""} for t in s.teams]
        items.append({
            "id": s.id, "name": s.name, "rpi": s.rpi or "", "code": s.code or "",
            "city": s.city or "", "state": s.state or "", "logo": s.logo or "",
            "teams": teams,
        })
    return jsonify({"schools": items})


@main_bp.route('/api/admin/schools', methods=['POST'])
def api_admin_schools_add():
    """Add a school. Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    data = request.get_json() or {}
    sname = (data.get('school_name') or data.get('name') or '').strip()
    if not sname:
        return jsonify({"error": "School name is required."}), 400
    school = School(
        name=sname,
        rpi=(data.get('rpi') or '').strip(),
        code=(data.get('code') or '').strip().upper(),
        city=(data.get('city') or '').strip(),
        state=(data.get('state') or '').strip(),
    )
    db.session.add(school)
    db.session.commit()
    return jsonify({"ok": True, "school": {"id": school.id, "name": school.name}}, 201)


@main_bp.route('/api/admin/schools/<int:school_id>', methods=['PATCH'])
def api_admin_schools_update(school_id):
    """Update a school. Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    school = School.query.get(school_id)
    if not school:
        return jsonify({"error": "School not found."}), 404
    data = request.get_json() or {}
    if 'school_name' in data or 'name' in data:
        sname = (data.get('school_name') or data.get('name') or '').strip()
        if sname:
            school.name = sname
    if 'rpi' in data:
        school.rpi = (data.get('rpi') or '').strip()
    if 'code' in data:
        school.code = (data.get('code') or '').strip().upper()
    if 'city' in data:
        school.city = (data.get('city') or '').strip()
    if 'state' in data:
        school.state = (data.get('state') or '').strip()
    db.session.commit()
    return jsonify({"ok": True, "school": {"id": school.id, "name": school.name}})


@main_bp.route('/api/admin/schools/<int:school_id>/logo', methods=['POST'])
def api_admin_schools_upload_logo(school_id):
    """Upload a logo for a school. Admin only. Accepts multipart form with 'logo' file."""
    user, err = _require_admin_json()
    if err:
        return err
    school = School.query.get(school_id)
    if not school:
        return jsonify({"error": "School not found."}), 404
    if 'logo' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400
    f = request.files['logo']
    if not f or not f.filename:
        return jsonify({"error": "No file selected."}), 400
    ext = os.path.splitext(f.filename)[1].lower() or '.png'
    if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'):
        return jsonify({"error": "Invalid file type. Use PNG, JPG, GIF, WebP or SVG."}), 400
    cdn_dir = os.path.join(current_app.root_path, 'static', 'cdn', 'schools')
    os.makedirs(cdn_dir, exist_ok=True)
    filename = f"school_{school_id}{ext}"
    filepath = os.path.join(cdn_dir, filename)
    f.save(filepath)
    school.logo = filename
    db.session.commit()
    return jsonify({"ok": True, "logo": filename, "url": f"/action/cdn/schools/{filename}"})


@main_bp.route('/api/admin/schools/<int:school_id>', methods=['DELETE'])
def api_admin_schools_delete(school_id):
    """Delete a school. Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    school = School.query.get(school_id)
    if not school:
        return jsonify({"error": "School not found."}), 404
    UserSchoolPermission.query.filter_by(school_id=school_id).delete()
    db.session.delete(school)
    db.session.commit()
    return jsonify({"ok": True})


@main_bp.route('/api/admin/database/seasons', methods=['GET'])
def api_admin_database_seasons():
    """List all seasons with sport info. Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    seasons = Season.query.order_by(Season.name).all()
    items = []
    for s in seasons:
        items.append({
            "id": s.id, "name": s.name, "sport_code": s.sport_code or "",
            "gender": s.gender or "", "start_date": s.start_date or "", "end_date": s.end_date or "",
        })
    return jsonify({"seasons": items, "sport_groups": SPORT_GROUPS, "sport_codes": {k: v[1] for k, v in SPORT_CODES.items()}})


@main_bp.route('/api/admin/seasons/<int:season_id>/teams', methods=['GET'])
def api_admin_season_teams(season_id):
    """List teams in a season. Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    season = Season.query.get(season_id)
    if not season:
        return jsonify({"error": "Season not found."}), 404
    teams = Team.query.filter_by(season_id=season_id).order_by(Team.name).all()
    items = [{"id": t.id, "name": t.name, "code": t.code or "", "school_name": t.school.name if t.school else ""} for t in teams]
    return jsonify({"season": {"id": season.id, "name": season.name}, "teams": items})


@main_bp.route('/api/admin/schools/<int:school_id>/add-to-season', methods=['POST'])
def api_admin_school_add_season(school_id):
    """Add school to a season (existing or new). Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    school = School.query.get(school_id)
    if not school:
        return jsonify({"error": "School not found."}), 404
    data = request.get_json() or {}
    existing_season_id = (data.get('existing_season_id') or '').strip()
    new_season_name = (data.get('new_season_name') or '').strip()
    sport_code = (data.get('sport_code') or 'bsb').strip()
    gender = (data.get('gender') or 'female').strip()

    if not existing_season_id and not new_season_name:
        return jsonify({"error": "Select an existing season or enter a new season name."}), 400

    if existing_season_id:
        season = Season.query.get(int(existing_season_id))
        if not season:
            return jsonify({"error": "Season not found."}), 400
    else:
        season = Season(
            name=new_season_name,
            sport_code=sport_code,
            sport_id=_sport_int(sport_code),
            gender=gender,
        )
        db.session.add(season)
        db.session.flush()

    base_code = (school.code or re.sub(r'[^A-Z0-9]', '', school.name.upper())[:6]) or 'TEAM'
    code = base_code
    suffix = 1
    while Team.query.filter_by(code=code, season_id=season.id).first():
        code = f"{base_code}{suffix}"
        suffix += 1
    team = Team(
        name=school.name,
        print_name=school.name,
        code=code,
        abbreviation=(school.code or school.name[:4].upper()),
        city=school.city,
        state=school.state,
        season_id=season.id,
        school_id=school.id,
    )
    db.session.add(team)
    db.session.commit()
    return jsonify({"ok": True, "message": f'Team "{school.name}" added to season "{season.name}".'}, 201)


@main_bp.route('/api/admin/teams/<int:team_id>', methods=['DELETE'])
def api_admin_teams_delete(team_id):
    """Remove team (school from season). Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    team = Team.query.get(team_id)
    if not team:
        return jsonify({"error": "Team not found."}), 404
    season_name = team.season.name if team.season else ''
    school_name = team.school.name if team.school else ''
    db.session.delete(team)
    db.session.commit()
    return jsonify({"ok": True, "message": f'Removed "{school_name}" from season "{season_name}".'})


@main_bp.route('/api/admin/seasons', methods=['POST'])
def api_admin_seasons_add():
    """Add a season. Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    data = request.get_json() or {}
    sname = (data.get('season_name') or data.get('name') or '').strip()
    if not sname:
        return jsonify({"error": "Season name is required."}), 400
    scode = data.get('sport_code', 'bsb')
    gender = data.get('gender', 'male')
    start_date = (data.get('start_date') or '').strip() or None
    end_date = (data.get('end_date') or '').strip() or None
    season = Season(
        name=sname,
        sport_code=scode,
        sport_id=_sport_int(scode),
        gender=gender,
        start_date=start_date,
        end_date=end_date,
    )
    db.session.add(season)
    db.session.commit()
    return jsonify({"ok": True, "season": {"id": season.id, "name": season.name}}, 201)


@main_bp.route('/api/admin/seasons/<int:season_id>', methods=['DELETE'])
def api_admin_seasons_delete(season_id):
    """Delete a season and all its data. Admin only."""
    _, err = _require_admin_json()
    if err:
        return err
    season = Season.query.get(season_id)
    if not season:
        return jsonify({"error": "Season not found."}), 404
    sname = season.name
    team_ids = [t.id for t in season.teams]
    games = Game.query.filter(
        (Game.home_team_id.in_(team_ids)) | (Game.visitor_team_id.in_(team_ids))
    ).all()
    for game in games:
        Play.query.filter_by(game_id=game.id).delete()
        GameVersion.query.filter_by(game_id=game.id).delete()
        InningScore.query.filter_by(game_id=game.id).delete()
        BattingStats.query.filter_by(game_id=game.id).delete()
        PitchingStats.query.filter_by(game_id=game.id).delete()
        FieldingStats.query.filter_by(game_id=game.id).delete()
        db.session.delete(game)
    for team in season.teams:
        for player in team.players:
            db.session.delete(player)
        db.session.delete(team)
    UserPermission.query.filter_by(season_id=season.id).delete()
    db.session.delete(season)
    db.session.commit()
    return jsonify({"ok": True, "message": f'Season "{sname}" and all its data deleted.'})


def _baseball_status_options():
    opts = ['Final']
    for i in range(1, 51):
        opts.append(f"Final - {i} inning{'s' if i > 1 else ''}")
    for i in range(1, 11):
        opts.append(f"Final - KO {i}")
    return opts


def _softball_status_options():
    return _baseball_status_options()


def _generic_status_options():
    opts = ['Final']
    for i in range(1, 18):
        opts.append(f"Final - {'OT' if i == 1 else str(i) + 'OT'}")
    return opts


STATUS_OPTIONS_BY_SPORT = {
    0:  _generic_status_options(),    # football
    1:  _baseball_status_options(),   # baseball
    2:  _generic_status_options(),    # basketball
    3:  _generic_status_options(),    # soccer
    4:  _generic_status_options(),    # volleyball
    5:  _generic_status_options(),    # ice hockey
    6:  _generic_status_options(),    # men's lacrosse
    7:  _generic_status_options(),    # tennis
    9:  _generic_status_options(),    # field hockey
    10: _generic_status_options(),    # women's lacrosse
    11: _softball_status_options(),   # softball
    12: _generic_status_options(),    # water polo
}


def _status_options(sport_id):
    return STATUS_OPTIONS_BY_SPORT.get(sport_id, _generic_status_options())


def _game_status_code(game):
    if game.is_complete:
        return 0
    if getattr(game, 'has_lineup', False) or getattr(game, 'batting_stats', None):
        return -1
    return -2


def _game_status_formatted(game):
    if game.is_complete:
        return 'Final'
    return 'Scheduled'


def _game_to_event(game, season_id, sport_id):
    """Build the event object the gameday controller.js expects."""
    vis  = game.visitor_team
    home = game.home_team

    # Date in MM/DD/YYYY for display; event_date in M/D/YYYY for GWT
    event_date_display = ''
    event_date_gwt = ''
    if game.date:
        parts = game.date.split('-')
        if len(parts) == 3:
            event_date_display = f"{parts[1]}/{parts[2]}/{parts[0]}"
            event_date_gwt     = f"{int(parts[1])}/{int(parts[2])}/{parts[0]}"

    status_code = _game_status_code(game)
    return {
        'id':              str(game.id),
        'date':            event_date_display or '',
        'awayTeam':        vis.name  if vis  else 'Visitor',
        'homeTeam':        home.name if home else 'Home',
        'awayResult':      str(game.visitor_runs or 0) if game.is_complete else '',
        'homeResult':      str(game.home_runs    or 0) if game.is_complete else '',
        'statusCode':      status_code,
        'statusFormatted': _game_status_formatted(game),
        'status':          game.state or '',
        'inProgress':      status_code == -1,
        'cancelled':       False,
        'postponed':       False,
        'conference':      game.is_league_game or False,
        'regional':        game.is_region or False,
        'division':        game.is_conf_division or False,
        'overall':         True,
        'primetime':       False,
        'tba':             not bool(game.start_time),
        'hasScorebug':     True,
        'scorebugJsonData': None,
        'neutralSite':     game.location if game.is_neutral else '',
        'statsApp':        'STATSENTRY_LIVE',
        # For stats entry link substitution
        'season_id':       str(season_id),
        'sport_code':      str(sport_id),
        'event_date':      event_date_gwt,
    }


@main_bp.route('/admin/team/checklist/')
@main_bp.route('/admin/team/checklist')
def checklist():
    user, err = _require_login()
    if err:
        return err

    from datetime import date, timedelta

    # Determine week start (Monday) from ?week=YYYY-MM-DD, default to current week
    week_param = request.args.get('week', '')
    try:
        anchor = date.fromisoformat(week_param)
    except ValueError:
        anchor = date.today()
    week_start = anchor - timedelta(days=anchor.weekday())  # Monday
    week_end   = week_start + timedelta(days=6)             # Sunday

    prev_week = (week_start - timedelta(days=7)).isoformat()
    next_week = (week_start + timedelta(days=7)).isoformat()

    # Format for display
    def fmt(d):
        return d.strftime('%b %-d, %Y')

    week_label = f"{fmt(week_start)} thru {fmt(week_end)}"

    # Fetch all games in this week range, grouped by season
    ws_str = week_start.isoformat()
    we_str = week_end.isoformat()

    seasons = Season.query.order_by(Season.name).all()
    season_rows = []
    for season in seasons:
        team_ids = [t.id for t in Team.query.filter_by(season_id=season.id).all()]
        if not team_ids:
            continue
        games = (Game.query
                 .filter(Game.visitor_team_id.in_(team_ids))
                 .filter(Game.date >= ws_str, Game.date <= we_str)
                 .order_by(Game.date, Game.start_time)
                 .all())
        season_rows.append({'season': season, 'games': games})

    return render_template('checklist.html',
                           current_user=user,
                           week_label=week_label,
                           week_start=week_start.isoformat(),
                           prev_week=prev_week,
                           next_week=next_week,
                           season_rows=season_rows)


# Each entry: 'url_code': (stats_engine_int, 'Display Name')
# Multiple codes can share the same int — they calculate stats identically
# but represent different sport variants (HS varsity vs JV, boys vs girls, etc.)
SPORT_CODES = {
    # Baseball (stats engine = 1)
    'bsb':              (1,  'Baseball'),
    'hsvarsitybsb':     (1,  'HS Varsity Baseball'),
    'hsjvbsb':          (1,  'HS JV Baseball'),
    # Softball (stats engine = 11)
    'sb':               (11, 'Softball'),
    'sballhs':          (11, 'Girls Softball'),
    'hsvarsitysb':      (11, 'HS Varsity Softball'),
    'hsjvsb':           (11, 'HS JV Softball'),
    # Boys Basketball (stats engine = 2)
    'mbkb':             (2,  'Boys Basketball'),
    'hsvarsitymbkb':    (2,  'HS Varsity Boys Basketball'),
    'hsjvmbkb':         (2,  'HS JV Boys Basketball'),
    # Girls Basketball (stats engine = 2)
    'wbkb':             (2,  'Girls Basketball'),
    'hsvarsitywbkb':    (2,  'HS Varsity Girls Basketball'),
    'hsjvwbkb':         (2,  'HS JV Girls Basketball'),
    # Football (stats engine = 0)
    'fb':               (0,  'Football'),
    'hsvarsityfb':      (0,  'HS Varsity Football'),
    'hsjvfb':           (0,  'HS JV Football'),
    # Boys Soccer (stats engine = 3)
    'msoc':             (3,  'Boys Soccer'),
    'hsvarsitymsoc':    (3,  'HS Varsity Boys Soccer'),
    'hsjvmsoc':         (3,  'HS JV Boys Soccer'),
    # Girls Soccer (stats engine = 3)
    'wsoc':             (3,  'Girls Soccer'),
    'hsvarsitywsoc':    (3,  'HS Varsity Girls Soccer'),
    'hsjvwsoc':         (3,  'HS JV Girls Soccer'),
    # Volleyball (stats engine = 4)
    'vb':               (4,  'Volleyball'),
    'hsvarsityvb':      (4,  'HS Varsity Volleyball'),
    'hsjvvb':           (4,  'HS JV Volleyball'),
    # Ice Hockey (stats engine = 5)
    'ih':               (5,  'Ice Hockey'),
    'mih':              (5,  "Men's Ice Hockey"),
    'wih':              (5,  "Women's Ice Hockey"),
    # Men's Lacrosse (stats engine = 6)
    'mlax':             (6,  "Men's Lacrosse"),
    'hsvarsitymlax':    (6,  'HS Varsity Boys Lacrosse'),
    # Women's Lacrosse (stats engine = 10)
    'wlax':             (10, "Women's Lacrosse"),
    'hsvarsitywlax':    (10, 'HS Varsity Girls Lacrosse'),
    # Tennis (stats engine = 7)
    'ten':              (7,  'Tennis'),
    'mten':             (7,  "Men's Tennis"),
    'wten':             (7,  "Women's Tennis"),
    # Field Hockey (stats engine = 9)
    'fh':               (9,  'Field Hockey'),
    'hsvarsityfh':      (9,  'HS Varsity Field Hockey'),
    # Water Polo (stats engine = 12)
    'wp':               (12, 'Water Polo'),
    'mwp':              (12, "Men's Water Polo"),
    'wwp':              (12, "Women's Water Polo"),
}

# Grouped for <optgroup> dropdowns in templates
SPORT_GROUPS = [
    ('Baseball',          ['bsb', 'hsvarsitybsb', 'hsjvbsb']),
    ('Softball',          ['sb', 'sballhs', 'hsvarsitysb', 'hsjvsb']),
    ('Boys Basketball',   ['mbkb', 'hsvarsitymbkb', 'hsjvmbkb']),
    ('Girls Basketball',  ['wbkb', 'hsvarsitywbkb', 'hsjvwbkb']),
    ('Football',          ['fb', 'hsvarsityfb', 'hsjvfb']),
    ('Boys Soccer',       ['msoc', 'hsvarsitymsoc', 'hsjvmsoc']),
    ('Girls Soccer',      ['wsoc', 'hsvarsitywsoc', 'hsjvwsoc']),
    ('Volleyball',        ['vb', 'hsvarsityvb', 'hsjvvb']),
    ('Ice Hockey',        ['ih', 'mih', 'wih']),
    ("Men's Lacrosse",    ['mlax', 'hsvarsitymlax']),
    ("Women's Lacrosse",  ['wlax', 'hsvarsitywlax']),
    ('Tennis',            ['ten', 'mten', 'wten']),
    ('Field Hockey',      ['fh', 'hsvarsityfh']),
    ('Water Polo',        ['wp', 'mwp', 'wwp']),
]


def _sport_int(code):
    """Return the stats-engine integer for a sport code string."""
    return SPORT_CODES.get(code, (1, ''))[0]


def _sport_name(code):
    """Return the display name for a sport code string."""
    return SPORT_CODES.get(code, (1, code))[1]


def _season_task_list(season, teams, games):
    """Return list of (task_name, notes) tuples for incomplete setup tasks."""
    tasks = []
    if not season.sport_code:
        tasks.append(('Sport', 'Sport type not configured.'))
    if len(teams) == 0:
        tasks.append(('Teams', 'No teams added to this season.'))
    elif len(teams) < 2:
        tasks.append(('Teams', 'At least two teams are required to schedule games.'))
    if len(games) == 0:
        tasks.append(('Schedule', 'No games scheduled.'))
    return tasks


def _season_tasks(season, teams, games):
    """Return count of incomplete setup tasks."""
    return len(_season_task_list(season, teams, games))


def _user_permitted_school_ids(user):
    """Return set of school IDs the user has school-level access to."""
    perms = UserSchoolPermission.query.filter_by(user_id=user.id).all()
    return {p.school_id for p in perms}


def _user_has_season_via_school(user, season_id):
    """True if user has school permission for a school that has a team in this season."""
    school_ids = _user_permitted_school_ids(user)
    if not school_ids:
        return False
    return Team.query.filter(
        Team.season_id == season_id,
        Team.school_id.in_(school_ids)
    ).first() is not None


def _user_has_season_permission(user, season_id):
    """True if user may access this season (via UserPermission or UserSchoolPermission)."""
    if user.role == 'admin':
        return True
    if UserPermission.query.filter_by(user_id=user.id, season_id=season_id).first():
        return True
    return _user_has_season_via_school(user, season_id)


def _user_has_team_permission(user, season_id, team_id):
    """True if user may access this team in this season."""
    if user.role == 'admin':
        return True
    perms = UserPermission.query.filter_by(user_id=user.id, season_id=season_id).all()
    if perms:
        if any(p.team_id is None for p in perms):
            return True
        if team_id in {p.team_id for p in perms}:
            return True
    team = Team.query.get(team_id)
    if team and team.season_id == season_id and team.school_id:
        return team.school_id in _user_permitted_school_ids(user)
    return False


def _permitted_seasons(user):
    """Return the list of Season objects this user may access.
    Admins see everything; scorers see seasons from UserPermission or UserSchoolPermission."""
    if user.role == 'admin':
        return Season.query.order_by(Season.name).all()
    season_ids = set()
    for p in UserPermission.query.filter_by(user_id=user.id).all():
        season_ids.add(p.season_id)
    school_ids = _user_permitted_school_ids(user)
    if school_ids:
        teams = Team.query.filter(Team.school_id.in_(school_ids)).all()
        for t in teams:
            if t.season_id:
                season_ids.add(t.season_id)
    if not season_ids:
        return []
    return Season.query.filter(Season.id.in_(season_ids)).order_by(Season.name).all()


@main_bp.route('/admin/team/season/')
@main_bp.route('/admin/team/season')
def seasons_list():
    user, err = _require_login()
    if err:
        return err
    all_seasons = _permitted_seasons(user)
    # Build sorted unique sport codes from seasons in use
    seen = set()
    sports = []
    for s in all_seasons:
        code = s.sport_code or ''
        if code and code not in seen:
            seen.add(code)
            sports.append((code, _sport_name(code)))
    sports.sort(key=lambda x: x[1])
    return render_template('seasons.html',
                           current_user=user,
                           seasons=all_seasons,
                           sports=sports)


@main_bp.route('/admin/team/season/sport.jsp')
def season_sport():
    user, err = _require_login()
    if err:
        return err
    sport_code = request.args.get('sport_id', '')
    sport_name = _sport_name(sport_code) if sport_code else ''
    permitted = _permitted_seasons(user)
    seasons = [s for s in permitted if s.sport_code == sport_code] if sport_code else []
    # Sports sidebar: only sports the user can access
    seen = set()
    sports = []
    for s in permitted:
        code = s.sport_code or ''
        if code and code not in seen:
            seen.add(code)
            sports.append((code, _sport_name(code)))
    sports.sort(key=lambda x: x[1])
    return render_template('season_sport.html',
                           current_user=user,
                           sport_name=sport_name,
                           sport_code=sport_code,
                           seasons=seasons,
                           sports=sports)


@main_bp.route('/admin/team/season/season.jsp', methods=['GET', 'POST'])
def season_detail():
    user, err = _require_login()
    if err:
        return err
    season_id = request.args.get('season_id', type=int)
    if not season_id:
        return redirect(url_for('main.seasons_list'))
    season = Season.query.get_or_404(season_id)

    # Non-admins may only access seasons they have a permission record for
    if user.role != 'admin':
        if not _user_has_season_permission(user, season_id):
            return redirect(url_for('main.seasons_list'))

    error = None
    success = None
    action = request.form.get('action') if request.method == 'POST' else None

    if action == 'update_season':
        season.name = request.form.get('name', season.name).strip()
        scode = request.form.get('sport_code', season.sport_code or 'bsb')
        season.sport_code = scode
        season.sport_id = _sport_int(scode)
        season.rules = request.form.get('rules', season.rules)
        season.gender = request.form.get('gender', season.gender)
        season.play_entry_mode = request.form.get('play_entry_mode', season.play_entry_mode)
        season.start_date = request.form.get('start_date', season.start_date or '').strip() or None
        season.end_date = request.form.get('end_date', season.end_date or '').strip() or None
        db.session.commit()
        success = 'Season settings saved.'

    elif action == 'add_team' and user.role == 'admin':
        tname = request.form.get('name', '').strip()
        tcode = request.form.get('code', '').strip().upper()
        if not tname or not tcode:
            error = 'Team name and code are required.'
        elif Team.query.filter_by(code=tcode, season_id=season_id).first():
            error = f'Team code "{tcode}" already exists in this season.'
        else:
            team = Team(
                name=tname,
                print_name=tname,
                code=tcode,
                abbreviation=request.form.get('abbreviation', tcode[:3]).strip().upper(),
                city=request.form.get('city', '').strip(),
                state=request.form.get('state', '').strip(),
                coach=request.form.get('coach', '').strip(),
                season_id=season_id,
            )
            db.session.add(team)
            db.session.commit()
            success = f'Team "{tname}" added.'

    elif action == 'delete_team' and user.role == 'admin':
        team_id = int(request.form.get('team_id', 0))
        team = Team.query.get(team_id)
        if team and team.season_id == season_id:
            db.session.delete(team)
            db.session.commit()
            success = f'Team "{team.name}" removed.'

    elif action == 'add_game':
        vis_id  = request.form.get('visitor_team_id')
        home_id = request.form.get('home_team_id')
        gdate   = request.form.get('date', '').strip()
        if not vis_id or not home_id or not gdate:
            error = 'Date, visitor team, and home team are required.'
        elif vis_id == home_id:
            error = 'Visitor and home team cannot be the same.'
        else:
            game = Game(
                date=gdate,
                start_time=request.form.get('start_time', '').strip() or None,
                location=request.form.get('location', '').strip() or None,
                scheduled_innings=int(request.form.get('scheduled_innings', 7)),
                is_league_game=bool(request.form.get('is_league_game')),
                visitor_team_id=int(vis_id),
                home_team_id=int(home_id),
            )
            try:
                db.session.add(game)
                db.session.commit()
                success = 'Game added.'
            except Exception:
                db.session.rollback()
                error = 'Game already exists for that date/matchup.'

    elif action == 'delete_game':
        game_id = int(request.form.get('game_id', 0))
        game = Game.query.get(game_id)
        if game:
            team_ids = [t.id for t in season.teams]
            if game.visitor_team_id in team_ids or game.home_team_id in team_ids:
                has_stats = (
                    BattingStats.query.filter_by(game_id=game_id).first() is not None or
                    PitchingStats.query.filter_by(game_id=game_id).first() is not None or
                    InningScore.query.filter_by(game_id=game_id).first() is not None
                )
                if has_stats:
                    error = 'Cannot delete a game that has stats entered. Remove the box score first.'
                else:
                    Play.query.filter_by(game_id=game_id).delete()
                    GameVersion.query.filter_by(game_id=game_id).delete()
                    db.session.delete(game)
                    db.session.commit()
                    success = 'Game deleted.'

    elif action == 'toggle_complete':
        game_id = int(request.form.get('game_id', 0))
        game = Game.query.get(game_id)
        if game:
            game.is_complete = not game.is_complete
            db.session.commit()
            success = 'Game status updated.'

    elif action == 'add_player':
        team_id = request.form.get('team_id', type=int)
        team = Team.query.get(team_id) if team_id else None
        if not team or team.season_id != season_id:
            error = 'Invalid team.'
        else:
            first = request.form.get('first_name', '').strip()
            last  = request.form.get('last_name', '').strip()
            uni   = request.form.get('uniform_number', '').strip()
            if not first and not last:
                error = 'First or last name is required.'
            else:
                full_name = f"{first} {last}".strip()
                player = Player(
                    name=full_name,
                    first_name=first,
                    last_name=last,
                    uniform_number=uni or None,
                    position=request.form.get('position', '').strip(),
                    bats=request.form.get('bats', '').strip(),
                    throws=request.form.get('throws', '').strip(),
                    player_class=request.form.get('player_class', '').strip(),
                    team_id=team_id,
                )
                db.session.add(player)
                try:
                    db.session.commit()
                    success = f'Player "{full_name}" added to {team.name}.'
                except Exception:
                    db.session.rollback()
                    error = f'Could not add player "{full_name}" — may already exist.'

    elif action == 'delete_player':
        player_id = request.form.get('player_id', type=int)
        player = Player.query.get(player_id) if player_id else None
        if player and player.team and player.team.season_id == season_id:
            if player.batting_stats or player.pitching_stats or player.fielding_stats:
                error = f'Cannot remove "{player.name}" — stats have been recorded for this player.'
            else:
                pname = player.name
                db.session.delete(player)
                db.session.commit()
                success = f'Player "{pname}" removed.'

    teams = Team.query.filter_by(season_id=season_id).order_by(Team.name).all()
    team_ids = [t.id for t in teams]
    games = (Game.query
             .filter(Game.visitor_team_id.in_(team_ids))
             .order_by(Game.date, Game.start_time)
             .all()) if team_ids else []

    from datetime import date, timedelta
    today_str = date.today().strftime('%Y-%m-%d')
    week_ago_str = (date.today() - timedelta(days=7)).strftime('%Y-%m-%d')
    recent_games = [g for g in games if g.date and week_ago_str <= g.date <= today_str]

    tasks_left = _season_tasks(season, teams, games)

    # Determine which teams this user can see and whether to show the Teams tab
    if user.role == 'admin':
        visible_teams = teams
        show_teams_tab = True
    else:
        visible_teams = [t for t in teams if _user_has_team_permission(user, season_id, t.id)]
        show_teams_tab = len(visible_teams) > 1

    # If a non-admin has exactly one team and arrives without a tab param,
    # jump them straight to that team's roster.
    if (request.method == 'GET'
            and user.role != 'admin'
            and len(visible_teams) == 1
            and not request.args.get('tab')):
        return redirect(url_for('main.season_detail',
                                season_id=season_id,
                                tab='roster',
                                team_id=visible_teams[0].id))

    total_players = sum(len(t.players) for t in visible_teams)

    return render_template('season_detail.html',
                           current_user=user,
                           season=season,
                           teams=teams,
                           visible_teams=visible_teams,
                           show_teams_tab=show_teams_tab,
                           games=games,
                           recent_games=recent_games,
                           sport_name=_sport_name(season.sport_code or ''),
                           sport_groups=SPORT_GROUPS,
                           sport_codes=SPORT_CODES,
                           tasks_left=tasks_left,
                           total_players=total_players,
                           error=error,
                           success=success)


@main_bp.route('/admin/team/season/setup.jsp')
def season_setup():
    user, err = _require_login()
    if err:
        return err
    season_id = request.args.get('season_id', type=int)
    if not season_id:
        return redirect(url_for('main.seasons_list'))
    season = Season.query.get_or_404(season_id)
    teams = Team.query.filter_by(season_id=season_id).all()
    team_ids = [t.id for t in teams]
    games = (Game.query
             .filter(Game.visitor_team_id.in_(team_ids))
             .all()) if team_ids else []
    tasks = _season_task_list(season, teams, games)
    return render_template('season_setup.html',
                           current_user=user,
                           season=season,
                           sport_name=_sport_name(season.sport_code or ''),
                           tasks=tasks)


@main_bp.route('/admin/team/event/view.jsp', methods=['GET', 'POST'])
def event_detail():
    user, err = _require_login()
    if err:
        return err
    game_id = request.args.get('event_id', type=int)
    if not game_id:
        return redirect(url_for('main.gameday'))
    game = Game.query.get_or_404(game_id)

    # Derive season from one of the game's teams
    season = None
    if game.visitor_team and game.visitor_team.season_id:
        season = Season.query.get(game.visitor_team.season_id)
    if not season and game.home_team and game.home_team.season_id:
        season = Season.query.get(game.home_team.season_id)

    error = None
    success = None

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'toggle_complete':
            game.is_complete = not game.is_complete
            db.session.commit()
            success = 'Game status updated.'
        elif action == 'remove_boxscore':
            InningScore.query.filter_by(game_id=game_id).delete()
            BattingStats.query.filter_by(game_id=game_id).delete()
            PitchingStats.query.filter_by(game_id=game_id).delete()
            FieldingStats.query.filter_by(game_id=game_id).delete()
            game.visitor_runs = 0
            game.visitor_hits = 0
            game.visitor_errors = 0
            game.home_runs = 0
            game.home_hits = 0
            game.home_errors = 0
            game.is_complete = False
            game.has_lineup = False
            game.gwt_bs_blob = ''
            db.session.commit()
            success = 'Box score removed and stats reset.'

    # Build ordered list of all games in this season for prev/next navigation
    prev_game = None
    next_game = None
    if season:
        team_ids = [t.id for t in Team.query.filter_by(season_id=season.id).all()]
        all_games = (Game.query
                     .filter(Game.visitor_team_id.in_(team_ids))
                     .order_by(Game.date, Game.start_time)
                     .all()) if team_ids else []
        for i, g in enumerate(all_games):
            if g.id == game_id:
                if i > 0:
                    prev_game = all_games[i - 1]
                if i < len(all_games) - 1:
                    next_game = all_games[i + 1]
                break

    innings = game.innings if game.innings else []
    has_boxscore = game.is_complete or bool(innings) or bool(game.batting_stats)

    def _batting_totals(team_id):
        stats = [s for s in game.batting_stats if s.team_id == team_id]
        return {
            'ab':      sum(s.ab      for s in stats),
            'r':       sum(s.r       for s in stats),
            'h':       sum(s.h       for s in stats),
            'doubles': sum(s.doubles for s in stats),
            'triples': sum(s.triples for s in stats),
            'hr':      sum(s.hr      for s in stats),
            'rbi':     sum(s.rbi     for s in stats),
            'bb':      sum(s.bb      for s in stats),
            'so':      sum(s.so      for s in stats),
            'sb':      sum(s.sb      for s in stats),
            'cs':      sum(s.cs      for s in stats),
        }

    visitor_stats = _batting_totals(game.visitor_team_id) if has_boxscore else None
    home_stats    = _batting_totals(game.home_team_id)    if has_boxscore else None

    sport_id    = season.sport_id if season else 1
    status_opts = _status_options(sport_id)
    current_sc  = _game_status_code(game)

    return render_template('event_detail.html',
                           current_user=user,
                           game=game,
                           season=season,
                           sport_name=_sport_name(season.sport_code or '') if season else '',
                           innings=innings,
                           has_boxscore=has_boxscore,
                           has_lineup=game.has_lineup,
                           visitor_stats=visitor_stats,
                           home_stats=home_stats,
                           prev_game=prev_game,
                           next_game=next_game,
                           status_options=status_opts,
                           current_status_code=current_sc,
                           error=error,
                           success=success)


def _date_db_to_display(date_str):
    """Convert YYYY-MM-DD to MM/DD/YYYY."""
    if not date_str:
        return ''
    try:
        parts = date_str.split('-')
        if len(parts) == 3:
            return f"{parts[1]}/{parts[2]}/{parts[0]}"
    except Exception:
        pass
    return date_str


def _date_display_to_db(date_str):
    """Convert MM/DD/YYYY to YYYY-MM-DD."""
    if not date_str:
        return ''
    try:
        parts = date_str.strip().split('/')
        if len(parts) == 3:
            return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
    except Exception:
        pass
    return date_str


def _save_game_from_form(game, form):
    """Apply form fields to a Game object (new or existing). Does not commit."""
    date_str = _date_display_to_db(form.get('date', '').strip())
    if date_str:
        game.date = date_str
    time_str = form.get('time', '').strip() or None
    game.start_time = time_str

    vis_id = form.get('visitor_team_id')
    home_id = form.get('home_team_id')
    if vis_id:
        game.visitor_team_id = int(vis_id)
    if home_id:
        game.home_team_id = int(home_id)

    vis_result = form.get('team_0_result', '').strip()
    home_result = form.get('team_1_result', '').strip()
    if vis_result.isdigit():
        game.visitor_runs = int(vis_result)
    if home_result.isdigit():
        game.home_runs = int(home_result)

    status_code = int(form.get('status_code', '-2'))
    game.is_complete = (status_code >= 0)
    game.state = form.get('status', '').strip() or None

    game.location = form.get('location', '').strip() or None
    game.stadium = form.get('venue', '').strip() or None
    game.notes = form.get('notesShared', '').strip() or None
    game.is_neutral = bool(form.get('neutralSite', '').strip())

    event_type = form.get('eventType', 'regular')
    game.is_exhibition = (event_type == 'exhibition')
    game.is_league_game = bool(form.get('conference'))
    game.is_region = bool(form.get('regional'))
    game.is_conf_division = bool(form.get('division'))

    return date_str


@main_bp.route('/admin/team/roster/addPlayer.jsp', methods=['GET', 'POST'])
def add_player_page():
    user, err = _require_login()
    if err:
        return err

    season_id = request.args.get('season_id', type=int) or request.form.get('season_id', type=int)
    team_id   = request.args.get('team_id',   type=int) or request.form.get('team_id',   type=int)
    player_id = request.args.get('player_id', type=int) or request.form.get('player_id', type=int)

    if not season_id or not team_id:
        return redirect(url_for('main.seasons_list'))

    season  = Season.query.get_or_404(season_id)
    team    = Team.query.get_or_404(team_id)

    # Non-admins may only access teams they have an explicit permission for
    if user.role != 'admin':
        if not _user_has_team_permission(user, season_id, team_id):
            if _user_has_season_permission(user, season_id):
                return redirect(url_for('main.season_detail', season_id=season_id, tab='roster'))
            return redirect(url_for('main.seasons_list'))

    player  = Player.query.get(player_id) if player_id else None
    is_edit = player is not None

    roster_url = url_for('main.season_detail', season_id=season_id, tab='roster', team_id=team_id)
    error = None
    success = None

    # Pre-fill form values from existing player (edit) or blank (add)
    form = {
        'attr_number':     player.uniform_number or '' if player else '',
        'attr_first_name': player.first_name     or '' if player else '',
        'attr_last_name':  player.last_name      or '' if player else '',
        'attr_year':       player.player_class   or '' if player else '',
        'attr_position':   player.position       or '' if player else '',
        'bats':            player.bats           or '' if player else '',
        'throws':          player.throws         or '' if player else '',
        'stat_category':   'h',
    }

    if request.method == 'POST':
        submit_action = request.form.get('submit_action', '')

        if submit_action == 'Cancel':
            return redirect(roster_url)

        first = request.form.get('attr_first_name', '').strip()
        last  = request.form.get('attr_last_name',  '').strip()
        form  = request.form

        if not first and not last:
            error = 'First or last name is required.'
        else:
            if is_edit:
                player.first_name     = first
                player.last_name      = last
                player.name           = f"{first} {last}".strip()
                player.uniform_number = request.form.get('attr_number', '').strip() or None
                player.position       = request.form.get('attr_position', '').strip() or None
                player.bats           = request.form.get('bats', '').strip() or None
                player.throws         = request.form.get('throws', '').strip() or None
                player.player_class   = request.form.get('attr_year', '').strip() or None
            else:
                player = Player(
                    name=f"{first} {last}".strip(),
                    first_name=first,
                    last_name=last,
                    uniform_number=request.form.get('attr_number', '').strip() or None,
                    position=request.form.get('attr_position', '').strip() or None,
                    bats=request.form.get('bats', '').strip() or None,
                    throws=request.form.get('throws', '').strip() or None,
                    player_class=request.form.get('attr_year', '').strip() or None,
                    team_id=team_id,
                )
                db.session.add(player)
            try:
                db.session.commit()
                if not is_edit and submit_action == 'Save and add another':
                    return redirect(url_for('main.add_player_page',
                                            season_id=season_id, team_id=team_id))
                return redirect(roster_url)
            except Exception:
                db.session.rollback()
                error = f'Could not save player "{first} {last}".'

    return render_template('add_player.html',
                           current_user=user,
                           season=season,
                           team=team,
                           player=player,
                           is_edit=is_edit,
                           sport_name=_sport_name(season.sport_code or ''),
                           form=form,
                           error=error,
                           success=success)


@main_bp.route('/admin/team/schedule/editEvent.jsp', methods=['GET', 'POST'])
def edit_event():
    user, err = _require_login()
    if err:
        return err

    event_id  = request.args.get('event_id',  type=int)
    season_id = request.args.get('season_id', type=int)

    def _school_team_lookup(season_id):
        """Return list of dicts: {team_id, school_id, name, rpi, code, city, state}
        for every team in the season, using the linked school's info where available,
        falling back to the team's own name/code."""
        teams = Team.query.filter_by(season_id=season_id).order_by(Team.name).all()
        rows = []
        for t in teams:
            s = t.school
            rows.append({
                'team_id':  t.id,
                'name':     (s.name  if s else t.name)  or t.name,
                'rpi':      (s.rpi   if s else t.code)  or '',
                'code':     (s.code  if s else t.code)  or '',
                'city':     (s.city  if s else '')       or '',
                'state':    (s.state if s else '')       or '',
            })
        return rows

    # ── Edit mode ──────────────────────────────────────────────────────────
    if event_id:
        game = Game.query.get_or_404(event_id)

        season = None
        if game.visitor_team and game.visitor_team.season_id:
            season = Season.query.get(game.visitor_team.season_id)
        if not season and game.home_team and game.home_team.season_id:
            season = Season.query.get(game.home_team.season_id)

        season_teams = Team.query.filter_by(season_id=season.id).order_by(Team.name).all() if season else []
        teams        = season_teams
        school_teams = _school_team_lookup(season.id) if season else []
        error        = None

        if request.method == 'POST':
            if request.form.get('submit_action') == 'Cancel':
                return redirect(url_for('main.event_detail', event_id=event_id))
            _save_game_from_form(game, request.form)
            try:
                db.session.commit()
                return redirect(url_for('main.event_detail', event_id=event_id))
            except Exception:
                db.session.rollback()
                error = 'Could not save game (date/teams conflict).'

        if game.is_complete:
            current_status_code = 0
        elif game.innings or game.has_lineup or (game.state and game.state.lower() not in ('', 'scheduled')):
            current_status_code = -1
        else:
            current_status_code = -2

        status_options = _status_options(season.sport_id if season else 1)
        date_display = _date_db_to_display(game.date)
        form_action = url_for('main.edit_event', event_id=event_id)

        return render_template('game_edit.html',
                               current_user=user,
                               game=game,
                               season=season,
                               sport_name=_sport_name(season.sport_code or '') if season else '',
                               teams=season_teams,
                               school_teams=school_teams,
                               status_options=status_options,
                               current_status_code=current_status_code,
                               date_display=date_display,
                               form_action=form_action,
                               is_add=False,
                               error=error, success=None)

    # ── Add mode ───────────────────────────────────────────────────────────
    if not season_id:
        return redirect(url_for('main.seasons_list'))
    season       = Season.query.get_or_404(season_id)
    teams        = Team.query.filter_by(season_id=season_id).order_by(Team.name).all()
    school_teams = _school_team_lookup(season_id)
    error        = None

    if request.method == 'POST':
        if request.form.get('submit_action') == 'Cancel':
            return redirect(url_for('main.season_detail', season_id=season_id, tab='schedule'))

        vis_id   = request.form.get('visitor_team_id')
        home_id  = request.form.get('home_team_id')
        date_raw = request.form.get('date', '').strip()

        if not date_raw or not vis_id or not home_id:
            error = 'Date, visitor team, and home team are required.'
        elif vis_id == home_id:
            error = 'Visitor and home team cannot be the same.'
        else:
            game = Game()
            _save_game_from_form(game, request.form)
            try:
                db.session.add(game)
                db.session.commit()
                return redirect(url_for('main.event_detail', event_id=game.id))
            except Exception:
                db.session.rollback()
                error = 'Could not add game (duplicate date/teams).'

    status_options = _status_options(season.sport_id)
    form_action = url_for('main.edit_event', season_id=season_id)

    return render_template('game_edit.html',
                           current_user=user,
                           game=None,
                           season=season,
                           sport_name=_sport_name(season.sport_code or ''),
                           teams=teams,
                           school_teams=school_teams,
                           status_options=status_options,
                           current_status_code=-2,
                           date_display='',
                           form_action=form_action,
                           is_add=True,
                           error=error, success=None)


@main_bp.route('/admin/team/gameday3/')
@main_bp.route('/admin/team/gameday3')
def gameday():
    user, err = _require_login()
    if err:
        return err
    return render_template('gameday.html', current_user=user)


@main_bp.route('/admin/team/gameday3/<path:filename>')
def gameday_static(filename):
    base = os.path.join(current_app.root_path, 'static', 'gameday3')
    return send_from_directory(base, filename)


@main_bp.route('/action/cdn/info/images/icons/<path:filename>')
def cdn_icons(filename):
    base = os.path.join(current_app.root_path, 'static', 'cdn', 'info', 'images', 'icons')
    return send_from_directory(base, filename)


@main_bp.route('/action/cdn/schools/<path:filename>')
def cdn_school_logos(filename):
    """Serve uploaded school logos from CDN."""
    base = os.path.join(current_app.root_path, 'static', 'cdn', 'schools')
    return send_from_directory(base, filename)


@main_bp.route('/admin/team/gameday/seasonListByDate.json')
def gameday_season_list():
    user, err = _require_login()
    if err:
        return jsonify([]), 401

    date_str    = request.args.get('date', '')   # MM/DD/YYYY
    all_seasons = request.args.get('allSeasons', 'false').lower() == 'true'

    # Parse date to YYYY-MM-DD for DB comparison
    db_date = None
    if date_str:
        try:
            parts   = date_str.split('/')
            db_date = f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
        except (IndexError, ValueError):
            db_date = None

    seasons = _permitted_seasons(user)
    result  = []
    for s in seasons:
        teams    = Team.query.filter_by(season_id=s.id).all()
        team_ids = [t.id for t in teams]
        sport_id = s.sport_id

        if db_date and not all_seasons:
            count = Game.query.filter(
                Game.date == db_date,
                (Game.visitor_team_id.in_(team_ids)) | (Game.home_team_id.in_(team_ids))
            ).count()
            # Skip seasons with no games on this date
            if count == 0:
                continue
        else:
            count = Game.query.filter(
                (Game.visitor_team_id.in_(team_ids)) | (Game.home_team_id.in_(team_ids))
            ).count()

        result.append({
            'id':                  str(s.id),
            'name':                s.name,
            'seasonSportSharingId': 0,
            'statcrewSportId':     sport_id,
            'hidden':              False,
            'statusOptions':       _status_options(sport_id),
            'prefs':               {'bb_period_rules': 'HALVES'},
            'eventsCount':         count,
        })
    return jsonify(result)


@main_bp.route('/admin/team/gameday/seasonEvents.json')
def gameday_season_events():
    user, err = _require_login()
    if err:
        return jsonify([]), 401

    season_id_str = request.args.get('seasonId', '')
    date_str      = request.args.get('date', '')   # MM/DD/YYYY

    try:
        sid = int(season_id_str)
    except (TypeError, ValueError):
        return jsonify([])

    season = Season.query.get(sid)
    if not season:
        return jsonify([])

    # Enforce season-level permission for non-admins
    if user.role != 'admin':
        if not _user_has_season_permission(user, sid):
            return jsonify([]), 403

    all_teams = Team.query.filter_by(season_id=sid).all()
    if user.role != 'admin':
        all_teams = [t for t in all_teams if _user_has_team_permission(user, sid, t.id)]
    teams    = all_teams
    team_ids = [t.id for t in teams]
    sport_id = season.sport_id

    db_date = None
    if date_str:
        try:
            parts   = date_str.split('/')
            db_date = f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
        except (IndexError, ValueError):
            pass

    query = Game.query.filter(
        (Game.visitor_team_id.in_(team_ids)) | (Game.home_team_id.in_(team_ids))
    )
    if db_date:
        query = query.filter(Game.date == db_date)

    games = query.order_by(Game.date).all()
    return jsonify([_game_to_event(g, sid, sport_id) for g in games])


@main_bp.route('/admin/team/gameday/setScore.jsp', methods=['POST'])
def gameday_set_score():
    user, err = _require_login()
    if err:
        return jsonify({'ok': False}), 401

    raw = request.form.get('gamedayEvent', '')
    if not raw:
        return jsonify({'ok': False, 'error': 'no gamedayEvent'})

    try:
        evt = json.loads(raw)
    except Exception:
        return jsonify({'ok': False, 'error': 'invalid JSON'})

    try:
        game = Game.query.get(int(evt['id']))
    except (KeyError, TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'unknown event'})

    if not game:
        return jsonify({'ok': False, 'error': 'game not found'})

    status_code = int(evt.get('statusCode', -2))
    game.is_complete = (status_code >= 0)
    game.state       = evt.get('status', '') or None

    away_result = evt.get('awayResult', '')
    home_result = evt.get('homeResult', '')
    if away_result != '':
        try:
            game.visitor_runs = int(away_result)
        except ValueError:
            pass
    if home_result != '':
        try:
            game.home_runs = int(home_result)
        except ValueError:
            pass

    db.session.commit()
    return jsonify({'ok': True})


# ── Live boxscore page ────────────────────────────────────────────────────────

def _fmt_ip(ip_val):
    """Format innings-pitched float for display: 7.0 → '7.0', 4.1 → '4.1'."""
    if ip_val is None:
        return '0.0'
    return f"{float(ip_val):.1f}"


def _boxscore_data(game):
    """Build a dict with all live boxscore data for a game."""
    from app.models import BattingStats, PitchingStats

    vis  = game.visitor_team
    home = game.home_team

    inn_map = {i.inning: i for i in game.innings}
    sched   = game.scheduled_innings or 7
    max_inn = max(inn_map.keys()) if inn_map else 0
    num_inn = max(max_inn, sched)

    innings_data = []
    for n in range(1, num_inn + 1):
        row = inn_map.get(n)
        innings_data.append({
            'num': n,
            'v': str(row.visitor_score or 0) if row else '0',
            'h': str(row.home_score  or 0) if row else '0',
        })

    def _bat_rows(team_id):
        rows = []
        stats = sorted(
            [s for s in game.batting_stats if s.team_id == team_id],
            key=lambda s: (s.batting_order or 99, s.id)
        )
        for s in stats:
            p = s.player
            rows.append({
                'name':  p.name if p else '—',
                'pos':   (s.position or (p.position if p else '') or '').lower(),
                'order': s.batting_order or 0,
                'ab':    s.ab or 0,
                'r':     s.r  or 0,
                'h':     s.h  or 0,
                'rbi':   s.rbi or 0,
                'bb':    s.bb  or 0,
                'so':    s.so  or 0,
                '2b':    s.doubles or 0,
                '3b':    s.triples or 0,
                'hr':    s.hr  or 0,
                'sb':    s.sb  or 0,
                'hbp':   s.hbp or 0,
                'sh':    s.sh  or 0,
                'sf':    s.sf  or 0,
            })
        return rows

    def _bat_totals(team_id):
        stats = [s for s in game.batting_stats if s.team_id == team_id]
        def t(a): return sum(getattr(s, a, 0) or 0 for s in stats)
        return {'ab': t('ab'), 'r': t('r'), 'h': t('h'), 'rbi': t('rbi'),
                'bb': t('bb'), 'so': t('so'), '2b': t('doubles'), '3b': t('triples'),
                'hr': t('hr'), 'sb': t('sb')}

    def _pit_rows(team_id):
        rows = []
        stats = [s for s in game.pitching_stats if s.team_id == team_id]
        for s in stats:
            p = s.player
            dec = ''
            if s.win:  dec = 'W'
            elif s.loss: dec = 'L'
            elif s.save: dec = 'S'
            rows.append({
                'name':    p.name if p else '—',
                'dec':     dec,
                'ip':      _fmt_ip(s.ip),
                'h':       s.h  or 0,
                'r':       s.r  or 0,
                'er':      s.er or 0,
                'bb':      s.bb or 0,
                'so':      s.so or 0,
                'hr':      s.hr or 0,
                'bf':      s.bf or 0,
                'pitches': s.pitches or 0,
                'strikes': s.strikes or 0,
                'hbp':     s.hbp or 0,
                'wp':      s.wp  or 0,
            })
        return rows

    def _pit_totals(team_id):
        stats = [s for s in game.pitching_stats if s.team_id == team_id]
        def t(a): return sum(getattr(s, a, 0) or 0 for s in stats)
        # Sum IP in thirds
        thirds = 0
        for s in stats:
            ip = s.ip or 0.0
            thirds += int(ip) * 3 + round((ip - int(ip)) * 10)
        ip_str = f"{thirds // 3}.{thirds % 3}"
        return {'ip': ip_str, 'h': t('h'), 'r': t('r'), 'er': t('er'),
                'bb': t('bb'), 'so': t('so'), 'hr': t('hr'), 'bf': t('bf')}

    def _bat_summary(team_id):
        stats = [s for s in game.batting_stats if s.team_id == team_id]
        def names_with_count(attr, threshold=1):
            out = []
            for s in stats:
                val = getattr(s, attr, 0) or 0
                if val >= threshold:
                    p = s.player
                    nm = p.name if p else '?'
                    out.append(f"{nm} ({val})" if val > 1 else nm)
            return out
        return {
            '2B':  names_with_count('doubles'),
            '3B':  names_with_count('triples'),
            'HR':  names_with_count('hr'),
            'RBI': names_with_count('rbi'),
            'SB':  names_with_count('sb'),
            'HBP': names_with_count('hbp'),
            'SH':  names_with_count('sh'),
            'SF':  names_with_count('sf'),
        }

    def _pit_summary(team_id):
        stats = [s for s in game.pitching_stats if s.team_id == team_id]
        lines = []
        bf_parts = [f"{s.player.name if s.player else '?'} ({s.bf or 0})" for s in stats if s.bf]
        if bf_parts:
            lines.append({'label': 'Batters faced', 'value': ', '.join(bf_parts)})
        wp = [s.player.name if s.player else '?' for s in stats if s.wp]
        if wp:
            lines.append({'label': 'WP', 'value': ', '.join(wp)})
        hbp = [s.player.name if s.player else '?' for s in stats if s.hbp]
        if hbp:
            lines.append({'label': 'HBP', 'value': ', '.join(hbp)})
        ps_parts = [f"{s.player.name if s.player else '?'} ({s.pitches or 0}-{s.strikes or 0})"
                    for s in stats if (s.pitches or s.strikes)]
        if ps_parts:
            lines.append({'label': 'Pitches-Strikes', 'value': ', '.join(ps_parts)})
        return lines

    # Plays: scoring summary + full play-by-play grouped by inning/half
    scoring = []
    pbp_innings = []   # [{inning, half, label, plays:[{seq,outs,batter,pitcher,narrative,action}]}]
    v_running = 0
    h_running = 0
    _sorted_plays = sorted(game.plays, key=lambda p: (p.inning, _play_sort_half(p), p.sequence))
    from itertools import groupby as _groupby
    for (inn, half_ord), half_plays in _groupby(_sorted_plays, key=lambda p: (p.inning, _play_sort_half(p))):
        half = 'top' if half_ord == 0 else 'bottom'
        half_plays = list(half_plays)
        suffix = {1:'st', 2:'nd', 3:'rd'}.get(inn, 'th')
        label  = f"{'Top' if half == 'top' else 'Bot'} {inn}{suffix}"
        pbp_innings.append({
            'inning': inn,
            'half':   half,
            'label':  label,
            'plays':  [{
                'seq':       p.sequence,
                'outs':      p.outs_before or 0,
                'batter':    p.batter_name or '',
                'pitcher':   p.pitcher_name or '',
                'narrative': p.narrative or '',
                'action':    p.action_type or '',
                'rbi':       p.rbi or 0,
                'runs':      p.runs_scored or 0,
            } for p in half_plays],
        })
        for p in half_plays:
            if not p.runs_scored:
                continue
            v_running += p.runs_scored if half == 'top' else 0
            h_running += p.runs_scored if half == 'bottom' else 0
            scoring.append({
                'inning':  p.inning,
                'half':    half,
                'batter':  p.batter_name or '',
                'desc':    p.narrative or '',
                'rbi':     p.rbi or 0,
                'runs':    p.runs_scored or 0,
                'v_score': v_running,
                'h_score': h_running,
            })

    vid = game.visitor_team_id
    hid = game.home_team_id

    return {
        'game_id':       game.id,
        'status_label':  game.status_label,
        'is_complete':   game.is_complete,
        'has_lineup':    game.has_lineup,
        'date':          _date_db_to_display(game.date) if game.date else '',
        'start_time':    game.start_time or '',
        'visitor_name':  vis.name  if vis  else '',
        'visitor_code':  vis.code  if vis  else '',
        'home_name':     home.name if home else '',
        'home_code':     home.code if home else '',
        'visitor_runs':  game.visitor_runs  or 0,
        'visitor_hits':  game.visitor_hits  or 0,
        'visitor_errors':game.visitor_errors or 0,
        'visitor_lob':   game.visitor_lob   or 0,
        'home_runs':     game.home_runs     or 0,
        'home_hits':     game.home_hits     or 0,
        'home_errors':   game.home_errors   or 0,
        'home_lob':      game.home_lob      or 0,
        'innings':       innings_data,
        'visitor_batting':  _bat_rows(vid),
        'home_batting':     _bat_rows(hid),
        'visitor_bat_totals': _bat_totals(vid),
        'home_bat_totals':   _bat_totals(hid),
        'visitor_pitching':  _pit_rows(vid),
        'home_pitching':     _pit_rows(hid),
        'visitor_pit_totals': _pit_totals(vid),
        'home_pit_totals':   _pit_totals(hid),
        'visitor_bat_summary': _bat_summary(vid),
        'home_bat_summary':   _bat_summary(hid),
        'visitor_pit_summary': _pit_summary(vid),
        'home_pit_summary':   _pit_summary(hid),
        'scoring':       scoring,
        'pbp_innings':   pbp_innings,
    }


@main_bp.route('/game/<int:event_id>/statboxscore')
def stat_boxscore(event_id):
    user, err = _require_login()
    if err:
        return redirect(url_for('main.login'))
    game = Game.query.get_or_404(event_id)
    season = None
    if game.visitor_team:
        season = Season.query.get(game.visitor_team.season_id)
    data = _boxscore_data(game)
    return render_template('statboxscore.html',
                           current_user=user,
                           game=game,
                           season=season,
                           data=data)


@main_bp.route('/game/<int:event_id>/statboxscore.json')
def stat_boxscore_json(event_id):
    user, err = _require_login()
    if err:
        return jsonify({'ok': False}), 401
    game = Game.query.get_or_404(event_id)
    return jsonify(_boxscore_data(game))


# ── Game detail (Add Play UI) and API ───────────────────────────────────────

def _play_sort_half(p):
    """Order plays by the half they were recorded in: top before bottom."""
    return 0 if (p.half or '').lower() == 'top' else 1

@main_bp.route('/game/<int:game_id>')
def game_detail(game_id):
    """Render the Add Play scoring UI (game_detail.html)."""
    user, err = _require_login()
    if err:
        return err
    game = Game.query.get_or_404(game_id)
    season = None
    if game.visitor_team and game.visitor_team.season_id:
        season = Season.query.get(game.visitor_team.season_id)
    if not season and game.home_team and game.home_team.season_id:
        season = Season.query.get(game.home_team.season_id)

    innings = list(game.innings) if game.innings else []
    plays = sorted(game.plays, key=lambda p: (p.inning, _play_sort_half(p), p.sequence))
    v_batting = [s for s in game.batting_stats if s.team_id == game.visitor_team_id]
    h_batting = [s for s in game.batting_stats if s.team_id == game.home_team_id]
    v_pitching = [s for s in game.pitching_stats if s.team_id == game.visitor_team_id]
    h_pitching = [s for s in game.pitching_stats if s.team_id == game.home_team_id]

    def _defense_from_stats(stats):
        out = {}
        for s in stats:
            if s.position and s.player:
                pos = (s.position or '').upper().replace(' ', '')
                if pos and pos in ('P', 'C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'):
                    out[pos] = s.player.name or ''
        return out

    defense = _defense_from_stats(h_batting) if game.home_team_id else {}
    vis_defense = _defense_from_stats(v_batting) if game.visitor_team_id else {}
    is_new_game = not (game.batting_stats or game.plays)

    return render_template('game_detail.html',
                           current_user=user,
                           game=game,
                           season=season,
                           innings=innings,
                           plays=plays,
                           defense=defense,
                           vis_defense=vis_defense,
                           v_batting=v_batting,
                           h_batting=h_batting,
                           v_pitching=v_pitching,
                           h_pitching=h_pitching,
                           is_new_game=is_new_game)


@main_bp.route('/api/games/<int:game_id>/action', methods=['POST'])
def api_games_action(game_id):
    """Persist a play from the Add Play UI. Updates Play, InningScore, BattingStats, PitchingStats."""
    user_id = session.get('user_id')
    if not user_id or not User.query.get(user_id):
        return jsonify({'ok': False, 'error': 'Login required'}), 401
    data = request.get_json() or {}
    game = Game.query.get_or_404(game_id)

    action_type_map = {
        'single': '1B', 'double': '2B', 'triple': '3B', 'hr': 'HR', 'itp': 'HR',
        'grd': '2B', 'bb': 'BB', 'ibb': 'IBB', 'hbp': 'HBP', 'ci': 'CI',
        'so': 'KS', 'k': 'KS', 'kl': 'KL', 'go': 'GO', 'fo': 'FO', 'lo': 'LO',
        'pu': 'PU', 'foul': 'FO', 'fc': 'FC', 'dp': 'DP', 'gdp': 'GDP',
        'sac': 'SAC', 'sf': 'SF', 'e': 'E', 'cs': 'CS', 'po': 'PO', 'sb': 'SB',
    }
    t = (data.get('type') or '').strip().lower()
    # Use user-typed action when provided; otherwise map from type
    action_typed = (data.get('action') or '').strip()
    action_type = action_typed if action_typed else action_type_map.get(t, t.upper()[:4] if t else '')
    # Dropped foul (E* DF) — does not change batter, no AB/BF
    is_dropped_foul = 'DF' in (action_type or '').upper()

    inning = int(data.get('inning', 1))
    half = (data.get('half') or 'top').lower()
    if half not in ('top', 'bottom'):
        half = 'top'
    # Always compute next sequence server-side; ignore client value for correctness
    existing = [p.sequence for p in game.plays]
    sequence = (max(existing) + 1) if existing else 1
    outs_before = int(data.get('outs_before', 0))
    outs_on_play = int(data.get('outs_on_play', 0))
    rbi = int(data.get('rbi', 0))
    runs_scored = int(data.get('runs_scored', 0))
    narrative = (data.get('narrative') or '').strip()
    batter_name = (data.get('batter_name') or '').strip()
    pitcher_name = (data.get('pitcher_name') or '').strip()
    batter_id = data.get('batter_id')
    pitcher_id = data.get('pitcher_id')
    runners_after = (data.get('runners_after') or '000')[:3]
    runner_first = (data.get('runner_first') or '').strip() or None
    runner_second = (data.get('runner_second') or '').strip() or None
    runner_third = (data.get('runner_third') or '').strip() or None

    play = Play(
        game_id=game.id, inning=inning, half=half, sequence=sequence,
        outs_before=outs_before, outs_on_play=outs_on_play,
        batter_name=batter_name or None, pitcher_name=pitcher_name or None,
        narrative=narrative or None, action_type=action_type or None,
        rbi=rbi, runs_scored=runs_scored, runners_after=runners_after,
        runner_first=runner_first, runner_second=runner_second, runner_third=runner_third,
    )
    db.session.add(play)
    db.session.flush()

    if runs_scored > 0:
        inn = InningScore.query.filter_by(game_id=game.id, inning=inning).first()
        if not inn:
            inn = InningScore(game_id=game.id, inning=inning, visitor_score='0', home_score='0')
            db.session.add(inn)
        try:
            if half == 'top':
                v = int(inn.visitor_score or 0) + runs_scored
                inn.visitor_score = str(v)
                game.visitor_runs = (game.visitor_runs or 0) + runs_scored
            else:
                h = int(inn.home_score or 0) + runs_scored
                inn.home_score = str(h)
                game.home_runs = (game.home_runs or 0) + runs_scored
        except (TypeError, ValueError):
            pass

    if batter_id and not is_dropped_foul:
        bat = BattingStats.query.filter_by(game_id=game.id, player_id=batter_id).first()
        if not bat:
            team_id = game.home_team_id if half == 'bottom' else game.visitor_team_id
            bat = BattingStats(game_id=game.id, player_id=batter_id, team_id=team_id, ab=0, r=0, h=0, rbi=0, bb=0, so=0)
            db.session.add(bat)
        if t in ('single', 'double', 'triple', 'hr', 'itp', 'grd'):
            bat.ab = (bat.ab or 0) + 1
            bat.h = (bat.h or 0) + 1
            bat.rbi = (bat.rbi or 0) + rbi
        elif t in ('bb', 'ibb', 'hbp', 'ci'):
            bat.rbi = (bat.rbi or 0) + rbi
        elif t in ('so', 'k', 'kl'):
            bat.ab = (bat.ab or 0) + 1
            bat.so = (bat.so or 0) + 1
        elif t in ('go', 'fo', 'lo', 'pu', 'fc', 'dp', 'gdp', 'e'):
            bat.ab = (bat.ab or 0) + 1
        elif t in ('sac', 'sf'):
            bat.rbi = (bat.rbi or 0) + rbi

    if pitcher_id and not is_dropped_foul:
        pit = PitchingStats.query.filter_by(game_id=game.id, player_id=pitcher_id).first()
        if not pit:
            team_id = game.visitor_team_id if half == 'bottom' else game.home_team_id
            pit = PitchingStats(game_id=game.id, player_id=pitcher_id, team_id=team_id, ip=0, h=0, r=0, er=0, bb=0, so=0, bf=0)
            db.session.add(pit)
        pit.bf = (pit.bf or 0) + 1
        if t in ('so', 'k', 'kl'):
            pit.so = (pit.so or 0) + 1
        elif t in ('bb', 'ibb', 'hbp', 'ci'):
            pit.bb = (pit.bb or 0) + 1
        if runs_scored > 0:
            pit.r = (pit.r or 0) + runs_scored

    game.has_lineup = True
    # Renumber sequences consecutively (1,2,3...) game-wide by chronological order
    plays_list = Play.query.filter_by(game_id=game.id).all()
    plays_sorted = sorted(plays_list, key=lambda p: (p.inning, _play_sort_half(p), p.sequence))
    for seq, p in enumerate(plays_sorted, start=1):
        p.sequence = seq
    db.session.commit()
    return jsonify({'ok': True, 'saved': True})


@main_bp.route('/api/games/<int:game_id>/lineups', methods=['POST'])
def api_games_lineups(game_id):
    """Save starting lineups. Creates BattingStats and PitchingStats."""
    user_id = session.get('user_id')
    if not user_id or not User.query.get(user_id):
        return jsonify({'ok': False, 'error': 'Login required'}), 401
    data = request.get_json() or {}
    game = Game.query.get_or_404(game_id)

    vis = data.get('visitor', [])
    home = data.get('home', [])

    def _save_team_lineup(team_id, entries, is_home):
        BattingStats.query.filter_by(game_id=game_id, team_id=team_id).delete()
        for e in entries:
            pid = e.get('player_id')
            if not pid:
                continue
            player = Player.query.get(pid)
            if not player or player.team_id != team_id:
                continue
            order = int(e.get('order', 0))
            pos = (e.get('position') or player.position or '').upper()[:5]
            bat = BattingStats(
                game_id=game_id, player_id=pid, team_id=team_id,
                batting_order=order, position=pos, is_starter=True,
                ab=0, r=0, h=0, rbi=0, bb=0, so=0,
            )
            db.session.add(bat)
            if order == 1 and pos in ('P', 'DP', ''):
                pit = PitchingStats(
                    game_id=game_id, player_id=pid, team_id=team_id,
                    appear=1, ip=0, h=0, r=0, er=0, bb=0, so=0, bf=0,
                )
                db.session.add(pit)

    if game.visitor_team_id:
        _save_team_lineup(game.visitor_team_id, vis, False)
    if game.home_team_id:
        _save_team_lineup(game.home_team_id, home, True)

    game.has_lineup = True
    db.session.commit()
    return jsonify({'ok': True})


@main_bp.route('/game/<int:event_id>/boxscore.pdf')
def stat_boxscore_pdf(event_id):
    """Render a print-friendly boxscore page (user can Print → Save as PDF)."""
    user, err = _require_login()
    if err:
        return redirect(url_for('main.login'))
    game   = Game.query.get_or_404(event_id)
    season = None
    if game.visitor_team:
        season = Season.query.get(game.visitor_team.season_id)
    data = _boxscore_data(game)
    return render_template('boxscore_print.html', game=game, season=season, data=data)


# ── Stat History (PrestoSports viewStatHistory.jsp) ──────────────────────────

@main_bp.route('/admin/team/event/viewStatHistory.jsp')
def view_stat_history():
    user, err = _require_login()
    if err:
        return redirect(url_for('main.login'))
    event_id = request.args.get('event_id', type=int)
    if not event_id:
        return redirect(url_for('main.seasons_list'))
    game = Game.query.get_or_404(event_id)
    season = None
    if game.visitor_team:
        season = Season.query.get(game.visitor_team.season_id)
    live_data = _boxscore_data(game)
    return render_template('stat_history.html',
                           current_user=user,
                           game=game,
                           season=season,
                           live_data=live_data)


@main_bp.route('/admin/team/event/viewBoxScore.jspd', methods=['POST'])
def view_boxscore_fragment():
    user, err = _require_login()
    if err:
        return ('', 401)
    version_key = request.form.get('id', '').strip()
    event_id    = request.form.get('event_id', type=int)
    highlight   = request.form.get('highlight', '')

    # Load the version snapshot
    version = GameVersion.query.filter_by(version_key=version_key).first()
    if version:
        try:
            data = json.loads(version.snapshot_json)
        except Exception:
            data = {}
    elif event_id:
        # Fall back to live data
        game = Game.query.get_or_404(event_id)
        data = _boxscore_data(game)
        version = None
    else:
        return ('', 404)

    game = Game.query.get(event_id or (version.game_id if version else 0))
    return render_template('_boxscore_fragment.html',
                           data=data,
                           version=version,
                           game=game,
                           highlight=highlight)


@main_bp.route('/admin/team/event/reviewStats.jsp', methods=['POST', 'GET'])
def revert_to_version():
    """Revert a game to an older version snapshot."""
    user, err = _require_login()
    if err:
        return redirect(url_for('main.login'))
    if user.role != 'admin':
        return redirect(url_for('main.seasons_list'))

    event_id  = request.args.get('event_id', type=int) or request.form.get('event_id', type=int)
    change_id = request.args.get('change_id') or request.form.get('change_id', '')

    version = GameVersion.query.filter_by(version_key=change_id).first()
    if not version or version.game_id != event_id:
        return redirect(url_for('main.view_stat_history', event_id=event_id))

    if request.method == 'GET':
        game   = Game.query.get_or_404(event_id)
        season = None
        if game.visitor_team:
            season = Season.query.get(game.visitor_team.season_id)
        versions = GameVersion.query.filter_by(game_id=event_id).order_by(GameVersion.id.desc()).all()
        return render_template('stat_history.html',
                               current_user=user, game=game, season=season,
                               versions=versions, revert_key=change_id)

    # POST — actually perform the revert
    try:
        data = json.loads(version.snapshot_json)
    except Exception:
        return redirect(url_for('main.view_stat_history', event_id=event_id))

    game = Game.query.get_or_404(event_id)
    game.visitor_runs   = data.get('visitor_runs', 0)
    game.home_runs      = data.get('home_runs', 0)
    game.visitor_hits   = data.get('visitor_hits', 0)
    game.home_hits      = data.get('home_hits', 0)
    game.visitor_errors = data.get('visitor_errors', 0)
    game.home_errors    = data.get('home_errors', 0)
    # Remove this version and all newer versions, then commit
    GameVersion.query.filter(
        GameVersion.game_id == event_id,
        GameVersion.id > version.id
    ).delete()
    db.session.commit()
    return redirect(url_for('main.view_stat_history', event_id=event_id))


@main_bp.route('/admin/team/stats/downloadVersion')
def download_version():
    user, err = _require_login()
    if err:
        return redirect(url_for('main.login'))
    version_key = request.args.get('id', '').strip()
    fmt         = request.args.get('f', 'json').lower()

    version = GameVersion.query.filter_by(version_key=version_key).first_or_404()
    game    = Game.query.get_or_404(version.game_id)
    fname   = f"boxscore_{(game.date or 'nodate').replace('-','')}_{version_key}"

    if fmt == 'xml':
        from app.xmlapi import build_bsgame_xml
        xml_str = build_bsgame_xml(game)
        from flask import Response
        return Response(xml_str, mimetype='application/xml',
                        headers={'Content-Disposition': f'attachment; filename="{fname}.xml"'})
    else:
        from flask import Response
        return Response(version.snapshot_json, mimetype='application/json',
                        headers={'Content-Disposition': f'attachment; filename="{fname}.json"'})


# ── Configure season API (used by system_preferences.html) ───────────────────

@main_bp.route('/configure/season', methods=['POST'])
def configure_season_add():
    user, err = _require_login()
    if err or user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Admin only'}), 403

    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'Season name is required.'})

    gender = request.form.get('gender', 'female').strip()
    start_date = request.form.get('start_date', '').strip() or None
    end_date = request.form.get('end_date', '').strip() or None

    new_season = Season(
        name=name,
        gender=gender,
        start_date=start_date,
        end_date=end_date,
    )
    db.session.add(new_season)
    db.session.commit()
    return jsonify({'ok': True, 'id': new_season.id})


@main_bp.route('/configure/season/<int:season_id>/edit', methods=['POST'])
def configure_season_edit(season_id):
    user, err = _require_login()
    if err or user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Admin only'}), 403

    season = Season.query.get(season_id)
    if not season:
        return jsonify({'ok': False, 'error': 'Season not found.'})

    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'Season name is required.'})

    season.name = name
    season.rules = request.form.get('rules', season.rules)
    season.gender = request.form.get('gender', season.gender)
    season.start_date = request.form.get('start_date', '').strip() or None
    season.end_date = request.form.get('end_date', '').strip() or None
    db.session.commit()
    return jsonify({'ok': True})


@main_bp.route('/configure/season/<int:season_id>/delete', methods=['POST'])
def configure_season_delete(season_id):
    user, err = _require_login()
    if err or user.role != 'admin':
        return jsonify({'ok': False, 'error': 'Admin only'}), 403

    season = Season.query.get(season_id)
    if not season:
        return jsonify({'ok': False, 'error': 'Season not found.'})

    db.session.delete(season)
    db.session.commit()
    return jsonify({'ok': True})
