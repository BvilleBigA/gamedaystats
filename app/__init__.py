from dotenv import load_dotenv
from flask import Flask
from flask.wrappers import Request
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

db = SQLAlchemy()


class LargeFormRequest(Request):
    """Allow large form fields (e.g. GWT boxscore blob ~300KB+) for saveboxscore.json."""
    max_form_memory_size = 50 * 1024 * 1024  # 50MB


def create_app(config_class=None):
    app = Flask(__name__)
    app.request_class = LargeFormRequest

    if config_class:
        app.config.from_object(config_class)
    else:
        from config import Config
        app.config.from_object(Config)

    db.init_app(app)

    from app.routes import main_bp
    app.register_blueprint(main_bp)

    from app.gwtapi import gwtapi_bp
    app.register_blueprint(gwtapi_bp, url_prefix='/action/stats')

    from app.xmlapi import xml_bp
    app.register_blueprint(xml_bp)

    # Map sport_code → default icon filename under /action/cdn/info/images/icons/
    SPORT_ICON_MAP = {
        'bsb': 'bsb.png', 'hsvarsitybsb': 'bsb.png', 'hsjvbsb': 'bsb.png',
        'sb':  'sball.png', 'sballhs': 'sball.png', 'hsvarsitysb': 'sball.png', 'hsjvsb': 'sball.png',
        'mbkb': 'mbkb.png', 'hsvarsitymbkb': 'mbkb.png', 'hsjvmbkb': 'mbkb.png',
        'wbkb': 'wbkb.png', 'hsvarsitywbkb': 'wbkb.png', 'hsjvwbkb': 'wbkb.png',
        'fb':  'fball.png', 'hsvarsityfb': 'fball.png', 'hsjvfb': 'fball.png',
    }

    @app.template_filter("sport_icon")
    def sport_icon_filter(sport_code):
        """Return the URL for the default sport icon given a sport_code string."""
        fname = SPORT_ICON_MAP.get(sport_code or '', 'bsb.png')
        return f'/action/cdn/info/images/icons/{fname}'

    @app.template_filter("team_logo")
    def team_logo_filter(team, sport_code=''):
        """Return logo URL for team: school logo if available, else sport icon."""
        if team and team.school and team.school.logo:
            return f'/action/cdn/schools/{team.school.logo}'
        fname = SPORT_ICON_MAP.get(sport_code or '', 'bsb.png')
        return f'/action/cdn/info/images/icons/{fname}'

    @app.template_global("sport_icon_url")
    def sport_icon_url(sport_code):
        fname = SPORT_ICON_MAP.get(sport_code or '', 'bsb.png')
        return f'/action/cdn/info/images/icons/{fname}'

    @app.template_filter("pretty_date")
    def pretty_date_filter(s):
        """Format mm/dd/yyyy or yyyy-mm-dd as 'Month Day, Year'."""
        if not s:
            return ''
        from datetime import datetime
        for fmt in ('%m/%d/%Y', '%Y-%m-%d', '%m-%d-%Y'):
            try:
                return datetime.strptime(s.strip(), fmt).strftime('%B %-d, %Y')
            except ValueError:
                continue
        return s  # fallback: return as-is

    @app.template_filter("from_json")
    def from_json_filter(s):
        """Parse a JSON string in a template: {{ json_str | from_json }}"""
        if not s:
            return {}
        try:
            import json as _json
            return _json.loads(s)
        except Exception:
            return {}

    @app.template_filter("numfmt")
    def numfmt_filter(s):
        """Strip leading zeros from a uniform number string (e.g. '07' -> '7')."""
        if not s:
            return s or ""
        try:
            return str(int(s))
        except (ValueError, TypeError):
            return s

    def _uniform_sort_key_player(p):
        u = (getattr(p, "uniform_number", None) or "").strip()
        if not u:
            return (2, 999999, "")
        try:
            return (0, int(u), "")
        except (ValueError, TypeError):
            return (1, 0, u.lower())

    @app.template_filter("sort_players_by_uniform")
    def sort_players_by_uniform_filter(players):
        """Roster order: numeric by uniform (2 before 11), not string order."""
        if not players:
            return []
        return sorted(players, key=_uniform_sort_key_player)

    def _player_display_name(player):
        """First Last; handles comma-form names and legacy name-only field."""
        if not player:
            return ""
        fn = (getattr(player, "first_name", None) or "").strip()
        ln = (getattr(player, "last_name", None) or "").strip()
        if fn and ln:
            return f"{fn} {ln}"
        n = (getattr(player, "name", None) or "").strip()
        if not n:
            return ""
        if ", " in n:
            parts = n.split(", ", 1)
            return f"{parts[1].strip()} {parts[0].strip()}"
        return n

    @app.template_filter("player_display_name")
    def player_display_name_filter(player):
        return _player_display_name(player)

    @app.template_filter("player_last_name")
    def player_last_name_filter(player):
        full = _player_display_name(player)
        parts = full.split()
        return parts[-1] if parts else ""

    @app.template_filter("event_date")
    def event_date_filter(date_str):
        """Convert YYYY-MM-DD to MM/DD/YYYY for statGame.jsp URLs."""
        if not date_str:
            return ''
        try:
            from datetime import datetime
            return datetime.strptime(date_str, '%Y-%m-%d').strftime('%m/%d/%Y')
        except (ValueError, AttributeError):
            return date_str

    import time

    @app.template_global("now_ms")
    def now_ms():
        """Current epoch milliseconds for the ?t= cache-buster parameter."""
        return int(time.time() * 1000)

    with app.app_context():
        from app import models  # noqa: F401
        db.create_all()
        _migrate_db()
        _seed_demo_data()

    @app.cli.command("make-admin")
    def make_admin_cmd():
        """Make user 'Anderson Long' an admin."""
        from app.models import User
        for u in User.query.all():
            dn = (u.display_name or "").lower()
            un = (u.username or "").lower()
            combined = set(dn.split()) | set(un.split())
            if "anderson" in combined and "long" in combined:
                u.role = "admin"
                db.session.commit()
                print(f"Updated {u.display_name or u.username} (id={u.id}) to admin.")
                return
        print("User 'Anderson Long' not found.")

    return app


def _migrate_db():
    """Add any missing columns to existing tables without losing data."""
    new_columns = [
        ("game", "visitor_record", "VARCHAR(20) DEFAULT ''"),
        ("game", "visitor_conf", "VARCHAR(20) DEFAULT ''"),
        ("game", "home_record", "VARCHAR(20) DEFAULT ''"),
        ("game", "home_conf", "VARCHAR(20) DEFAULT ''"),
        ("game", "entry_mode", "VARCHAR(40) DEFAULT 'box_game_totals'"),
        ("play", "action_type", "VARCHAR(80)"),
        ("play", "rbi", "INTEGER DEFAULT 0"),
        ("play", "outs_on_play", "INTEGER DEFAULT 0"),
        ("play", "runs_scored", "INTEGER DEFAULT 0"),
        ("play", "earned_runs", "INTEGER"),
        ("play", "runners_after", "VARCHAR(3) DEFAULT '000'"),
        ("play", "sub_who",  "VARCHAR(200) DEFAULT ''"),
        ("play", "sub_for",  "VARCHAR(200) DEFAULT ''"),
        ("play", "sub_pos",  "VARCHAR(20)  DEFAULT ''"),
        ("play", "sub_spot", "INTEGER DEFAULT 0"),
        ("play", "sub_vh",   "VARCHAR(1)   DEFAULT ''"),
        ("play", "runner_first",  "VARCHAR(200) DEFAULT ''"),
        ("play", "runner_second", "VARCHAR(200) DEFAULT ''"),
        ("play", "runner_third",  "VARCHAR(200) DEFAULT ''"),
        ("play", "balls",    "INTEGER"),
        ("play", "strikes",  "INTEGER"),
        ("game", "gwt_bs_blob", "TEXT DEFAULT ''"),
        ("season", "sport_id", "INTEGER DEFAULT 1"),
        ("season", "sport_code", "VARCHAR(50) DEFAULT ''"),
        ("users", "email", "VARCHAR(200) DEFAULT ''"),
        ("users", "phone", "VARCHAR(30) DEFAULT ''"),
        ("season", "start_date", "VARCHAR(20) DEFAULT ''"),
        ("season", "end_date", "VARCHAR(20) DEFAULT ''"),
        ("team", "school_id", "INTEGER REFERENCES school(id)"),
        ("game", "has_lineup", "BOOLEAN DEFAULT 0"),
        ("school", "logo", "VARCHAR(200) DEFAULT ''"),
        ("fielding_stats", "indp", "INTEGER DEFAULT 0"),
        ("fielding_stats", "intp", "INTEGER DEFAULT 0"),
        ("fielding_stats", "csb", "INTEGER DEFAULT 0"),
        ("game_version", "id", None),  # sentinel — table created by create_all
    ]
    with db.engine.connect() as conn:
        for table, column, col_def in new_columns:
            try:
                conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
                conn.commit()
            except Exception:
                pass  # Column already exists

        # Clear false-finalized games: games marked complete but with no inning scores
        # (artifact of old reload bug where statsPerPeriod phantom innings were saved)
        try:
            conn.execute(db.text(
                "UPDATE game SET is_complete=0 WHERE is_complete=1 "
                "AND id NOT IN (SELECT DISTINCT game_id FROM inning_score)"
            ))
            conn.commit()
        except Exception:
            pass

        # Backfill sport_id from rules for any rows that still have the default
        try:
            conn.execute(db.text(
                "UPDATE season SET sport_id=11 WHERE sport_id=1 AND rules LIKE '%_sb'"
            ))
            conn.commit()
        except Exception:
            pass

        # Backfill sport_code from sport_id for existing rows missing it
        _sport_id_to_default_code = {
            0: 'fb', 1: 'bsb', 2: 'mbkb', 3: 'msoc', 4: 'vb',
            5: 'ih', 6: 'mlax', 7: 'ten', 9: 'fh', 10: 'wlax',
            11: 'sb', 12: 'wp',
        }
        for sport_int, default_code in _sport_id_to_default_code.items():
            try:
                conn.execute(db.text(
                    f"UPDATE season SET sport_code=:code WHERE sport_id=:sid AND (sport_code='' OR sport_code IS NULL)"
                ), {'code': default_code, 'sid': sport_int})
                conn.commit()
            except Exception:
                pass


def _seed_demo_data():
    """Create a Demo Season with sample teams, rosters, and games if it doesn't exist."""
    import hashlib
    from app.models import Season, Team, Player, Game, InningScore, BattingStats, PitchingStats, User

    # Seed admin user
    if not User.query.filter_by(username='admin@admin.com').first():
        # Migrate legacy 'admin' username to email format if it exists
        legacy = User.query.filter_by(username='admin').first()
        if legacy:
            legacy.username = 'admin@admin.com'
            db.session.commit()
        else:
            admin = User(
                username='admin@admin.com',
                password_sha256=hashlib.sha256(b'admin').hexdigest(),
                display_name='Administrator',
                role='admin',
            )
            db.session.add(admin)
            db.session.commit()

    if Season.query.filter_by(name="Demo Season").first():
        return
    # Do not seed demo data once real seasons exist (e.g. after user removed Demo Season).
    if Season.query.count() > 0:
        return

    season = Season(name="Demo Season", play_entry_mode="box_game_totals", rules="rules_hs_sb", gender="female")
    db.session.add(season)
    db.session.flush()

    # --- Teams ---
    teams_data = [
        {"code": "EAGLE", "name": "Eagles", "abbreviation": "EGL", "mascot": "Eagle", "city": "Springfield", "state": "IL", "stadium": "Eagle Field", "coach": "Coach Smith", "league": "Central", "division": "East", "conference": "Metro"},
        {"code": "TIGER", "name": "Tigers", "abbreviation": "TGR", "mascot": "Tiger", "city": "Riverside", "state": "CA", "stadium": "Tiger Park", "coach": "Coach Johnson", "league": "Central", "division": "East", "conference": "Metro"},
        {"code": "HAWK", "name": "Hawks", "abbreviation": "HWK", "mascot": "Hawk", "city": "Lakewood", "state": "OH", "stadium": "Hawk Stadium", "coach": "Coach Davis", "league": "Central", "division": "West", "conference": "Metro"},
        {"code": "BEAR", "name": "Bears", "abbreviation": "BRS", "mascot": "Bear", "city": "Fairview", "state": "TX", "stadium": "Bear Diamond", "coach": "Coach Wilson", "league": "Central", "division": "West", "conference": "Metro"},
    ]
    teams = []
    for td in teams_data:
        t = Team(season_id=season.id, print_name=td["name"], **td)
        db.session.add(t)
        teams.append(t)
    db.session.flush()

    # --- Rosters ---
    positions = ["P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DP", "EF", "P", "P"]
    first_names = [
        ["Emma", "Olivia", "Ava", "Sophia", "Isabella", "Mia", "Charlotte", "Amelia", "Harper", "Evelyn", "Abigail", "Lily", "Grace"],
        ["Madison", "Chloe", "Ella", "Riley", "Zoey", "Nora", "Hazel", "Layla", "Penelope", "Scarlett", "Aria", "Luna", "Stella"],
        ["Brooklyn", "Savannah", "Claire", "Skylar", "Paisley", "Audrey", "Bella", "Ellie", "Anna", "Natalie", "Caroline", "Quinn", "Ruby"],
        ["Addison", "Leah", "Aubrey", "Jade", "Vivian", "Willow", "Madelyn", "Eleanor", "Piper", "Rylee", "Mackenzie", "Faith", "Kinley"],
    ]
    last_names = [
        ["Anderson", "Baker", "Clark", "Davis", "Evans", "Foster", "Garcia", "Harris", "Irwin", "Jones", "Kelly", "Lopez", "Miller"],
        ["Nelson", "Owens", "Perez", "Quinn", "Roberts", "Scott", "Taylor", "Underwood", "Vasquez", "Walker", "Young", "Adams", "Brown"],
        ["Carter", "Dixon", "Edwards", "Fisher", "Grant", "Hayes", "Jackson", "King", "Lewis", "Morgan", "Nash", "Oliver", "Parker"],
        ["Reed", "Stone", "Thomas", "Upton", "Vega", "White", "Xiong", "York", "Zimmerman", "Allen", "Brooks", "Collins", "Drake"],
    ]

    all_players = {}
    for ti, team in enumerate(teams):
        team_players = []
        for pi in range(13):
            p = Player(
                name=f"{first_names[ti][pi]} {last_names[ti][pi]}",
                first_name=first_names[ti][pi],
                last_name=last_names[ti][pi],
                uniform_number=str(pi + 1),
                position=positions[pi],
                bats="Right" if pi % 3 == 0 else ("Left" if pi % 3 == 1 else "Switch"),
                throws="Right" if pi % 2 == 0 else "Left",
                year=["Fr", "So", "Jr", "Sr"][pi % 4],
                height=f"5'{4 + (pi % 8)}\"",
                weight=str(120 + pi * 5),
                hometown=team.city,
                team_id=team.id,
            )
            db.session.add(p)
            team_players.append(p)
        all_players[team.id] = team_players
    db.session.flush()

    # --- Games ---
    import itertools
    matchups = list(itertools.combinations(range(4), 2))
    game_dates = ["2025-03-01", "2025-03-08", "2025-03-15", "2025-03-22", "2025-03-29", "2025-04-05"]
    import random
    random.seed(42)

    for gi, (vi, hi) in enumerate(matchups):
        visitor = teams[vi]
        home = teams[hi]
        v_runs = random.randint(0, 8)
        h_runs = random.randint(0, 8)
        while v_runs == h_runs:
            h_runs = random.randint(0, 8)
        v_hits = v_runs + random.randint(1, 4)
        h_hits = h_runs + random.randint(1, 4)

        game = Game(
            date=game_dates[gi],
            location=home.city,
            stadium=home.stadium,
            start_time="4:00 PM",
            scheduled_innings=7,
            is_league_game=True,
            is_complete=True,
            visitor_team_id=visitor.id,
            home_team_id=home.id,
            visitor_runs=v_runs,
            visitor_hits=v_hits,
            visitor_errors=random.randint(0, 3),
            visitor_lob=random.randint(2, 8),
            home_runs=h_runs,
            home_hits=h_hits,
            home_errors=random.randint(0, 3),
            home_lob=random.randint(2, 8),
        )
        db.session.add(game)
        db.session.flush()

        # Inning scores
        v_inning_runs = _distribute_runs(v_runs, 7)
        h_inning_runs = _distribute_runs(h_runs, 7)
        for inning in range(1, 8):
            inn = InningScore(game_id=game.id, inning=inning,
                              visitor_score=str(v_inning_runs[inning - 1]),
                              home_score=str(h_inning_runs[inning - 1]))
            db.session.add(inn)

        # Batting stats for each team
        for side, team_obj, runs, hits in [
            ("visitor", visitor, v_runs, v_hits),
            ("home", home, h_runs, h_hits),
        ]:
            players = all_players[team_obj.id]
            hits_left = hits
            runs_left = runs
            for pi, player in enumerate(players[:9]):
                p_hits = min(hits_left, random.randint(0, 2))
                hits_left -= p_hits
                p_runs = min(runs_left, random.randint(0, 1)) if p_hits > 0 else 0
                runs_left -= p_runs
                ab = random.randint(max(p_hits, 1), 4)
                bs = BattingStats(
                    game_id=game.id, player_id=player.id, team_id=team_obj.id,
                    batting_order=pi + 1, position=player.position,
                    is_starter=True, ab=ab, r=p_runs, h=p_hits,
                    rbi=random.randint(0, p_hits),
                    bb=random.randint(0, 1), so=random.randint(0, 2),
                )
                db.session.add(bs)

        # Pitching stats
        for side, team_obj, opp_runs, opp_hits in [
            ("visitor", visitor, h_runs, h_hits),
            ("home", home, v_runs, v_hits),
        ]:
            pitcher = all_players[team_obj.id][0]  # first player is pitcher
            is_winner = (side == "visitor" and v_runs > h_runs) or (side == "home" and h_runs > v_runs)
            ps = PitchingStats(
                game_id=game.id, player_id=pitcher.id, team_id=team_obj.id,
                appear=1, gs=1, ip=7.0,
                h=opp_hits, r=opp_runs, er=max(0, opp_runs - random.randint(0, 1)),
                bb=random.randint(1, 4), so=random.randint(3, 10),
                bf=opp_hits + opp_runs + random.randint(20, 25),
                win=is_winner, loss=not is_winner,
            )
            db.session.add(ps)

    db.session.commit()


def _distribute_runs(total, innings):
    """Distribute runs randomly across innings."""
    import random
    result = [0] * innings
    for _ in range(total):
        result[random.randint(0, innings - 1)] += 1
    return result
