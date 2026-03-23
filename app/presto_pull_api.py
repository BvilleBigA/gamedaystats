"""
PrestoSync-compatible pull-only API for stats.bvillebiga.com.

PrestoSync is built with REACT_APP_GAMEDAY_API_ENDPOINT pointing at the /api prefix,
e.g. https://stats.bvillebiga.com/api

Implements:
  POST /api/auth/token          — JSON { username, password }
  POST /api/auth/token/refresh  — JSON { refreshToken }
  GET  /api/me/events           — query: startDate, endDate, eventType, eventStatus (optional)
  GET  /api/events/<id>/stats   — JSON { data: { xml: "..." } }

CORS is open (*); auth is Bearer idToken. Tokens are signed (itsdangerous), not JWTs.
"""

import hashlib
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.models import Game, Team, User
from app.routes import (
    _user_has_season_permission,
    _user_has_team_permission,
    _permitted_seasons,
)
from app.xmlapi import build_bsgame_xml

presto_pull_bp = Blueprint("presto_pull", __name__)

ACCESS_MAX_AGE = 86400 * 1  # 1 day
REFRESH_MAX_AGE = 86400 * 30  # 30 days


def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@presto_pull_bp.after_request
def _after(resp):
    return _cors(resp)


@presto_pull_bp.route("/auth/token", methods=["OPTIONS"])
def auth_token_options():
    return "", 204


@presto_pull_bp.route("/auth/token/refresh", methods=["OPTIONS"])
def auth_refresh_options():
    return "", 204


@presto_pull_bp.route("/me/events", methods=["OPTIONS"])
def me_events_options():
    return "", 204


@presto_pull_bp.route("/events/<int:event_id>/stats", methods=["OPTIONS"])
def event_stats_options(event_id):
    return "", 204


def _access_serializer():
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt="presto-pull-access-v1"
    )


def _refresh_serializer():
    return URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"], salt="presto-pull-refresh-v1"
    )


def _issue_tokens(user_id):
    uid = int(user_id)
    access = _access_serializer().dumps({"u": uid})
    refresh = _refresh_serializer().dumps({"u": uid})
    return {"idToken": access, "refreshToken": refresh}


def _user_from_access_token(token):
    if not token:
        return None
    try:
        data = _access_serializer().loads(token, max_age=ACCESS_MAX_AGE)
        return User.query.get(data.get("u"))
    except (BadSignature, SignatureExpired, TypeError, KeyError):
        return None


def _user_from_refresh_token(token):
    if not token:
        return None
    try:
        data = _refresh_serializer().loads(token, max_age=REFRESH_MAX_AGE)
        return User.query.get(data.get("u"))
    except (BadSignature, SignatureExpired, TypeError, KeyError):
        return None


def _require_user():
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return None
    return _user_from_access_token(auth[7:].strip())


def _abs_url(path):
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    root = request.url_root.rstrip("/")
    p = path if path.startswith("/") else f"/{path}"
    return f"{root}{p}"


def _team_logo_url(team):
    if not team or not team.school or not team.school.logo:
        return None
    logo = (team.school.logo or "").strip().lstrip("/")
    return _abs_url(f"/action/cdn/schools/{logo}")


def _team_payload(team):
    if not team:
        return None
    return {
        "teamName": team.name or "",
        "logo": _team_logo_url(team) or "",
    }


def _game_visible(user, game):
    if user.role == "admin":
        return True
    vis = game.visitor_team
    home = game.home_team
    if not vis or not vis.season_id:
        return False
    sid = vis.season_id
    if not _user_has_season_permission(user, sid):
        return False
    if not home:
        return _user_has_team_permission(user, sid, vis.id)
    return _user_has_team_permission(user, sid, vis.id) or _user_has_team_permission(
        user, sid, home.id
    )


def _parse_iso_date(s):
    if not s or not isinstance(s, str):
        return None
    s = s.strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.strptime(s, "%y-%m-%d").date()
        except ValueError:
            return None


def _game_start_datetime_iso(game):
    """ISO-8601 UTC for PrestoSync EventDisplay (moment.parseZone)."""
    d = (game.date or "1970-01-01").strip()[:10]
    raw_t = (game.start_time or "12:00 PM").strip()
    h, m = 12, 0
    for fmt in ("%I:%M %p", "%H:%M"):
        try:
            tt = datetime.strptime(raw_t, fmt)
            h, m = tt.hour, tt.minute
            break
        except ValueError:
            continue
    try:
        y, mo, da = int(d[0:4]), int(d[5:7]), int(d[8:10])
        dt = datetime(y, mo, da, h, m, tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except Exception:
        return f"{d}T12:00:00.000Z"


def _game_in_date_range(game, start_d, end_d):
    gd = _parse_iso_date(game.date or "")
    if not gd:
        return False
    if start_d and gd < start_d:
        return False
    if end_d and gd > end_d:
        return False
    return True


@presto_pull_bp.route("/auth/token", methods=["POST"])
def auth_token():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or body.get("email") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return jsonify({"message": "Invalid credentials"}), 401

    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    user = User.query.filter_by(
        username=username, password_sha256=pw_hash, is_active=True
    ).first()
    if not user:
        return jsonify({"message": "Invalid credentials"}), 401

    return jsonify(_issue_tokens(user.id))


@presto_pull_bp.route("/auth/token/refresh", methods=["POST"])
def auth_token_refresh():
    body = request.get_json(silent=True) or {}
    rt = body.get("refreshToken")
    user = _user_from_refresh_token(rt)
    if not user or not user.is_active:
        return jsonify({"message": "Unauthorized"}), 401
    return jsonify(_issue_tokens(user.id))


@presto_pull_bp.route("/me/events", methods=["GET"])
def me_events():
    user = _require_user()
    if not user:
        return jsonify({"message": "Unauthorized"}), 401

    start_raw = request.args.get("startDate") or request.args.get("start_date")
    end_raw = request.args.get("endDate") or request.args.get("end_date")
    start_d = _parse_iso_date(start_raw) if start_raw else None
    end_d = _parse_iso_date(end_raw) if end_raw else None

    seasons = _permitted_seasons(user)
    season_ids = {s.id for s in seasons}
    if not season_ids:
        return jsonify({"data": []})

    team_ids = [
        t.id
        for t in Team.query.filter(Team.season_id.in_(season_ids)).all()
    ]
    if not team_ids:
        return jsonify({"data": []})

    games = (
        Game.query.filter(Game.visitor_team_id.in_(team_ids))
        .order_by(Game.date, Game.start_time)
        .all()
    )

    out = []
    for g in games:
        if not _game_visible(user, g):
            continue
        if not _game_in_date_range(g, start_d, end_d):
            continue
        away = _team_payload(g.visitor_team)
        home = _team_payload(g.home_team)
        if not away or not home:
            continue
        out.append(
            {
                "id": str(g.id),
                "startDateTime": _game_start_datetime_iso(g),
                "teams": {
                    "awayTeam": away,
                    "homeTeam": home,
                },
            }
        )

    return jsonify({"data": out})


@presto_pull_bp.route("/events/<int:event_id>/stats", methods=["GET"])
def event_stats(event_id):
    user = _require_user()
    if not user:
        return jsonify({"message": "Unauthorized"}), 401

    game = Game.query.get(event_id)
    if not game:
        return jsonify({"message": "Not found"}), 404
    if not _game_visible(user, game):
        return jsonify({"message": "Forbidden"}), 403

    try:
        xml_str = build_bsgame_xml(game)
    except Exception as e:
        current_app.logger.exception("presto_pull build_bsgame_xml failed")
        return jsonify({"message": "XML build failed", "detail": str(e)}), 500

    return jsonify({"data": {"xml": xml_str or ""}})
