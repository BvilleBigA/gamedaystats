"""GWT JSON API blueprint — serves /action/stats/*.json endpoints."""

import os
import json
import string
import random
from datetime import datetime
from flask import Blueprint, request, jsonify
from app import db
from app.models import (User, Season, Game, Team, Player,
                        InningScore, BattingStats, PitchingStats, FieldingStats,
                        GameVersion, Play)

gwtapi_bp = Blueprint('gwtapi', __name__)

LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'gwt_requests.log')

# GWT position index → string (mirrors BatSportPositions.POS_DESC in the GWT client).
# GWT saves numeric starterPosition/playedPosition but not always the pos string,
# so we derive the human-readable position from the index when pos is empty.
_GWT_POS_DESC = {
    1: 'p', 2: 'c', 3: '1b', 4: '2b', 5: '3b', 6: 'ss',
    7: 'lf', 8: 'cf', 9: 'rf',
    10: 'dh',   # baseball; softball uses 'dp' but same index
    11: 'dh',
    12: 'ph', 13: 'pr', 14: 'eh',
}

# Reverse map: position string → GWT numeric index (used when building blobs from DB).
# Build manually to control priority when multiple indices share the same label.
_GWT_POS_INDEX = {
    'p': 1, 'c': 2, '1b': 3, '2b': 4, '3b': 5, 'ss': 6,
    'lf': 7, 'cf': 8, 'rf': 9,
    'dh': 10, 'dp': 10,   # baseball=dh, softball=dp, same index
    'ph': 12, 'pr': 13, 'eh': 14,
    'of': 7,   # generic outfield → left field as fallback
}


def _log(endpoint, data):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, 'a') as f:
        f.write(f"--- {endpoint} ---\n{dict(data)}\n\n")


def _stub(endpoint):
    """Log request and return minimal OK response."""
    _log(endpoint, request.form)
    return jsonify({"ok": True})


def _rand_key(n=16):
    """Generate a random alphanumeric version key like PrestoSports uses."""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _save_version(game, created_by=''):
    """Snapshot current game state into a GameVersion record."""
    try:
        from app.routes import _boxscore_data
        data = _boxscore_data(game)
        label = _version_label(game, data)
        version = GameVersion(
            game_id       = game.id,
            version_key   = _rand_key(),
            label         = label,
            snapshot_json = json.dumps(data),
            created_at    = datetime.utcnow(),
            created_by    = created_by or 'system',
        )
        db.session.add(version)
        db.session.flush()
    except Exception:
        pass  # Never let snapshot failure break the save


def _version_label(game, data):
    """Build the dropdown label: 'Visitor X, Home Y, Status (Uploaded on ...) by user'"""
    vis  = data.get('visitor_name', 'Visitor')
    home = data.get('home_name', 'Home')
    vr   = data.get('visitor_runs', 0)
    hr   = data.get('home_runs', 0)
    status = data.get('status_label') or '1st inning'
    now_str = datetime.utcnow().strftime('%-m/%-d/%Y %-I:%M %p UTC')
    return f"{vis} {vr}, {home} {hr}, {status} (Uploaded on {now_str}) by {data.get('created_by', 'system')}"


def _sanitize_boxscore_batting_order(boxscore):
    """
    Trim each team's currentBattingOrder to at most visBatters/homeBatters.
    Prevents $onBack crashes when blobs have 10 entries (FLEX) with maxBatters=9.
    Modifies boxscore in place; returns None.
    """
    if not boxscore:
        return
    ei = boxscore.get("eventInfo") or {}
    vis_max = int(ei.get("visBatters") or 9)
    home_max = int(ei.get("homeBatters") or 9)
    for i, t in enumerate(boxscore.get("teams") or []):
        max_batters = vis_max if i == 0 else home_max
        bo = t.get("currentBattingOrder")
        if isinstance(bo, list) and len(bo) > max_batters:
            t["currentBattingOrder"] = bo[:max_batters]


def _pitch_count_from_sequence(raw):
    """Count pitches from a GWT pitch sequence string."""
    if not raw or not str(raw).strip():
        return 0
    raw = str(raw).strip()
    if raw and raw[0].isalpha():
        return sum(1 for c in raw if c.isalpha())
    return sum(1 for part in raw.split('/') if part.strip())


def _sync_live_count_in_boxscore(boxscore):
    """
    Preserve the live count GWT synced in eventInfo.

    Some scoring flows keep the current count only in eventInfo and do not create an
    in-progress raw play until the at-bat is committed. In those cases XML must follow
    eventInfo exactly as sent by GWT. We only backfill these values from raw plays when
    eventInfo is missing them entirely.
    """
    if not boxscore:
        return

    ei = boxscore.setdefault("eventInfo", {})
    if all(ei.get(k) not in (None, "") for k in (
        "ballOnCurrentPlay",
        "strikesOnCurrentPlay",
        "pitchesNumberOnCurrentPlay",
    )):
        return

    raw_plays = boxscore.get("plays") or boxscore.get("rawPlays") or {}
    if not raw_plays:
        return

    def _int_or_none(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def _is_truthy(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "y", "on")
        return bool(v)

    current_period = _int_or_none(ei.get("statusPeriod"))
    if current_period is None:
        return
    current_home_off = _is_truthy(ei.get("isHomeOffensive"))

    play_list = raw_plays.get(str(current_period))
    if not isinstance(play_list, list):
        play_list = raw_plays.get(current_period)
    if not isinstance(play_list, list):
        play_list = []

    last_live = None
    last_key = -1
    for p in play_list:
        if p.get("playtype") in ("TURNOVR", "SCOREADJ", "INNINGS_ADVANCE"):
            continue
        if _is_truthy(p.get("homeTeam")) != current_home_off:
            continue
        seq = _int_or_none(p.get("sequence")) or 0
        if seq >= last_key:
            last_key = seq
            last_live = p

    if not last_live:
        return

    props = last_live.get("props") or {}
    action = (props.get("RUNNER_ACTION0") or props.get("ACTION", "") or "").strip()
    if action:
        return

    pitch_seq = (props.get("PITCHER_ACTIONS_0") or props.get("PITCHER_ACTIONS", "") or "").strip()
    balls_val = props.get("CURRENT_BALLS") or props.get("BALLS")
    strikes_val = props.get("CURRENT_STRIKES") or props.get("STRIKES")
    if balls_val not in (None, "") and strikes_val not in (None, ""):
        try:
            b_int = int(balls_val)
            s_int = int(strikes_val)
        except (TypeError, ValueError):
            b_int, s_int = _derive_balls_strikes_from_sequence(pitch_seq)
    else:
        b_int, s_int = _derive_balls_strikes_from_sequence(pitch_seq)

    ei["ballOnCurrentPlay"] = int(b_int or 0)
    ei["strikesOnCurrentPlay"] = int(s_int or 0)
    ei["pitchesNumberOnCurrentPlay"] = _pitch_count_from_sequence(pitch_seq)


def _date_db_to_gwt(d):
    """Convert 'YYYY-MM-DD' → 'M/d/yyyy' as required by GWT date parser."""
    if not d:
        return None
    parts = d.split('-')
    if len(parts) == 3:
        return f"{int(parts[1])}/{int(parts[2])}/{parts[0]}"
    return None


def _derive_balls_strikes_from_sequence(raw):
    """Derive (balls, strikes) from GWT pitch sequence. Returns (balls, strikes) integers."""
    if not raw or not str(raw).strip():
        return (None, None)
    raw = str(raw).strip()
    b, s = 0, 0
    if raw and raw[0].isalpha():
        for c in raw.lower():
            if c in ('b', 'i'):
                b += 1
            elif c in ('k', 's', 'p'):
                s = min(s + 1, 2)
            elif c == 'f':
                if s < 2:
                    s += 1
            elif c in ('x', 'h'):
                break
        return (b, s)
    for part in raw.split('/'):
        part = part.strip()
        if len(part) < 2:
            continue
        pfx = part[:2]
        if pfx in ('01', '06'):
            b += 1
        elif pfx in ('02', '03', '08'):
            s = min(s + 1, 2)
        elif pfx == '04':
            if s < 2:
                s += 1
        elif pfx in ('05', '07'):
            break
    return (b, s)


def _date_gwt_to_db(d):
    """Convert 'M/d/yyyy' (GWT) → 'YYYY-MM-DD'."""
    if not d or not isinstance(d, str):
        return None
    parts = d.strip().split('/')
    if len(parts) != 3:
        return None
    try:
        m, day, year = int(parts[0]), int(parts[1]), int(parts[2])
        if 1 <= m <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100:
            return f"{year:04d}-{m:02d}-{day:02d}"
    except (ValueError, TypeError):
        pass
    return None


def _persist_setup_to_game(game, ei, bs_teams, _int):
    """Persist eventInfo and team setup fields from GWT payload to Game model."""
    # eventInfo → Game
    if 'date' in ei:
        gwt_date = (ei.get('date') or '').strip()
        game.date = _date_gwt_to_db(gwt_date) if gwt_date else None
    if 'timeStart' in ei:
        game.start_time = (ei.get('timeStart') or '').strip() or None
    if 'location' in ei:
        game.location = (ei.get('location') or '').strip() or None
    if 'stadium' in ei:
        game.stadium = (ei.get('stadium') or '').strip() or None
    if 'duration' in ei:
        v = (ei.get('duration') or '').strip()
        game.duration = v if v else None
    if 'attendance' in ei:
        game.attendance = _int(ei.get('attendance'))
    if 'weather' in ei:
        game.weather = (ei.get('weather') or '').strip() or None
    if 'notes' in ei:
        game.notes = (ei.get('notes') or '').strip() or None
    if 'delay' in ei or 'delayedTime' in ei:
        v = (ei.get('delay') or ei.get('delayedTime') or '').strip()
        game.delayed_time = v if v else None
    # scheduledInnings / gamePeriods / rulesPeriods
    for key in ('scheduledInnings', 'gamePeriods', 'rulesPeriods'):
        if key in ei:
            val = _int(ei.get(key))
            if val > 0:
                game.scheduled_innings = val
    # Booleans
    if 'dhRule' in ei:
        v = ei.get('dhRule')
        game.used_dh = 'yes' if v else 'no'
    if 'night' in ei:
        game.is_night = bool(ei.get('night'))
    if 'conference' in ei:
        game.is_league_game = bool(ei.get('conference'))
    if 'confDivision' in ei:
        game.is_conf_division = bool(ei.get('confDivision'))
    if 'exhibition' in ei:
        game.is_exhibition = bool(ei.get('exhibition'))
    if 'neutral' in ei:
        game.is_neutral = bool(ei.get('neutral'))
    # Referees
    if 'referees' in ei:
        refs = ei.get('referees') or []
        game.ump_hp = (str(refs[0] or '').strip() or None) if len(refs) >= 1 else None
        game.ump_1b = (str(refs[1] or '').strip() or None) if len(refs) >= 2 else None
        game.ump_2b = (str(refs[2] or '').strip() or None) if len(refs) >= 3 else None
        game.ump_3b = (str(refs[3] or '').strip() or None) if len(refs) >= 4 else None
    # Team IDs and records (bs_teams: [visitor, home])
    if bs_teams and len(bs_teams) >= 1:
        if 'psId' in bs_teams[0]:
            tid = _int(bs_teams[0].get('psId'))
            if tid and Team.query.get(tid):
                game.visitor_team_id = tid
        if 'record' in bs_teams[0]:
            game.visitor_record = (str(bs_teams[0].get('record') or '')).strip() or ''
        if 'record_conf' in bs_teams[0]:
            game.visitor_conf = (str(bs_teams[0].get('record_conf') or '')).strip() or ''
    if bs_teams and len(bs_teams) >= 2:
        if 'psId' in bs_teams[1]:
            tid = _int(bs_teams[1].get('psId'))
            if tid and Team.query.get(tid):
                game.home_team_id = tid
        if 'record' in bs_teams[1]:
            game.home_record = (str(bs_teams[1].get('record') or '')).strip() or ''
        if 'record_conf' in bs_teams[1]:
            game.home_conf = (str(bs_teams[1].get('record_conf') or '')).strip() or ''


def _parse_and_persist_plays(game, bs, _int):
    """Parse bs.plays and persist to Play table. Shared by saveGame, saveboxscore, processRawPlay."""
    raw_plays = bs.get('plays') or bs.get('rawPlays') or {}
    if not raw_plays:
        return
    vis_roster = {str(p.uniform_number): p for p in (game.visitor_team.players if game.visitor_team else [])}
    home_roster = {str(p.uniform_number): p for p in (game.home_team.players if game.home_team else [])}

    def _resolve_narrative(text):
        import re as _re
        def _repl(m):
            vh, uni = m.group(1), m.group(2)
            rstr = vis_roster if vh == 'V' else home_roster
            player = rstr.get(uni)
            if player:
                last = (player.last_name or '').strip()
                first = (player.first_name or '').strip()
                if last and first:
                    return f"{last}, {first[0]}."
                parts = (player.name or '').strip().split()
                if len(parts) >= 2:
                    return f"{parts[-1]}, {parts[0][0]}."
                return player.name or uni
            return uni
        return _re.sub(r'%p([VH]):(\w+)', _repl, text or '')

    def _short(player):
        last = (player.last_name or '').strip()
        first = (player.first_name or '').strip()
        if last and first:
            return f"{last}, {first[0]}."
        parts = (player.name or '').strip().split()
        if len(parts) >= 2:
            return f"{parts[-1]}, {parts[0][0]}."
        return player.name or ''

    Play.query.filter_by(game_id=game.id).delete()

    for inning_key, play_list in raw_plays.items():
        try:
            inning_num = int(inning_key)
        except (ValueError, TypeError):
            continue
        if not isinstance(play_list, list):
            continue

        current_half = None

        def _half_from_batter_uni(uni):
            if not uni:
                return None
            if str(uni) in home_roster:
                return 'bottom'
            if str(uni) in vis_roster:
                return 'top'
            return None

        def _next_non_sub_half(start_idx):
            for future in play_list[start_idx + 1:]:
                if future.get('playtype', '') == 'SUB':
                    continue
                return 'bottom' if future.get('homeTeam', False) else 'top'
            return None

        for idx, play_obj in enumerate(play_list):
            playtype = play_obj.get('playtype', '')
            if playtype in ('TURNOVR', 'SCOREADJ', 'INNINGS_ADVANCE'):
                continue

            if playtype == 'SUB':
                props = play_obj.get('props', {})
                sub_home_team = play_obj.get('homeTeam', False)
                sequence = play_obj.get('sequence', 0)
                outs_before = _int(props.get('CURRENT_OUTS', 0))
                # SPOT_OUT = spot of player leaving; SPOT_IN = spot incoming player takes (prefer OUT for "for" player)
                # GWT may use 0-based indexing (0=1st, 4=5th); convert to 1-based for XML
                raw_spot = _int(props.get('SPOT_OUT') or props.get('SPOT_IN') or 0)
                batting_spot = (raw_spot + 1) if 0 <= raw_spot <= 8 else raw_spot
                pos_in = (props.get('POS_IN_DESC') or '').strip().lower()
                in_uni = next(iter(play_obj.get('players', {}).get('IN_PLAYER', {}).keys()), None)
                out_uni = next(iter(play_obj.get('players', {}).get('OUT_PLAYER', {}).keys()), None)
                def_roster = home_roster if sub_home_team else vis_roster
                opp_roster = vis_roster if sub_home_team else home_roster

                def _name_from_uni(uni):
                    for r in (def_roster, opp_roster):
                        p = r.get(str(uni)) if uni else None
                        if p:
                            return _short(p)
                    return ''

                in_name = _name_from_uni(in_uni)
                out_name = _name_from_uni(out_uni)
                # Parse batter/pitcher from play context (GWT may include them for SUB)
                batter_uni = next(iter(play_obj.get('players', {}).get('BATTER', {}).keys()), None)
                batter_name = ''
                if batter_uni:
                    rstr = home_roster if sub_home_team else vis_roster
                    player = rstr.get(str(batter_uni))
                    if player:
                        batter_name = _short(player)
                pitcher_unis = play_obj.get('playersProp', {}).get('PITCHER', [])
                pitcher_uni = str(pitcher_unis[0]) if pitcher_unis else None
                pitcher_name = ''
                if pitcher_uni:
                    def_rstr = vis_roster if sub_home_team else home_roster
                    player = def_rstr.get(pitcher_uni)
                    if player:
                        pitcher_name = _short(player)

                # SUB half = when it happened, not which team was changed.
                # For defensive subs, batter_uni is unreliable (GWT may attach the opposing team's
                # next batter), so skip it and rely on current_half / look-ahead / fallback.
                _is_def_sub_pos = pos_in in frozenset({'p','c','1b','2b','3b','ss','lf','cf','rf'})
                if _is_def_sub_pos:
                    # Defensive: home on defense (sub_home_team=True) → visitor batting → top
                    _fallback_half = 'top' if sub_home_team else 'bottom'
                    sub_half = (
                        current_half
                        or _next_non_sub_half(idx)
                        or _fallback_half
                    )
                else:
                    # Offensive (ph/pr): batter context is reliable
                    _fallback_half = 'bottom' if sub_home_team else 'top'
                    sub_half = (
                        _half_from_batter_uni(batter_uni)
                        or current_half
                        or _next_non_sub_half(idx)
                        or _fallback_half
                    )
                narr_parts = [_resolve_narrative(props.get(f'NARRATIVE{i}', '')) for i in range(5)]
                narrative = ' '.join(n for n in narr_parts if n and n.strip()).strip()
                if not narrative:
                    pos_label = (pos_in or '').strip().lower() or 'sub'
                    if in_name and out_name and in_name != out_name:
                        narrative = f"{in_name} to {pos_label} for {out_name}."
                    elif in_name:
                        narrative = f"{in_name} to {pos_label}."
                    else:
                        narrative = ''

                db.session.add(Play(
                    game_id=game.id, inning=inning_num,
                    half=sub_half,
                    sequence=sequence, outs_before=outs_before,
                    action_type='SUB', narrative=narrative,
                    sub_who=in_name, sub_for=out_name, sub_pos=pos_in,
                    sub_spot=batting_spot, sub_vh='H' if sub_home_team else 'V',
                    batter_name=batter_name or None, pitcher_name=pitcher_name or None,
                ))
                continue

            props = play_obj.get('props', {})
            home_team_bat = play_obj.get('homeTeam', False)
            current_half = 'bottom' if home_team_bat else 'top'
            sequence = play_obj.get('sequence', 0)
            batter_uni = next(iter(play_obj.get('players', {}).get('BATTER', {}).keys()), None)
            batter_name = ''
            if batter_uni:
                rstr = home_roster if home_team_bat else vis_roster
                player = rstr.get(str(batter_uni))
                if player:
                    batter_name = _short(player)

            pitcher_unis = play_obj.get('playersProp', {}).get('PITCHER', [])
            pitcher_uni = str(pitcher_unis[0]) if pitcher_unis else None
            pitcher_name = ''
            if pitcher_uni:
                def_rstr = vis_roster if home_team_bat else home_roster
                player = def_rstr.get(pitcher_uni)
                if player:
                    pitcher_name = _short(player)

            narr_parts = [_resolve_narrative(props.get(f'NARRATIVE{i}', '')) for i in range(5)]
            narrative = ' '.join(n for n in narr_parts if n and n.strip()).strip()
            pitch_seq = (props.get('PITCHER_ACTIONS_0') or props.get('PITCHER_ACTIONS', '')).strip()
            balls_val = props.get('CURRENT_BALLS') or props.get('BALLS')
            strikes_val = props.get('CURRENT_STRIKES') or props.get('STRIKES')
            if balls_val not in (None, '') and strikes_val not in (None, ''):
                balls_int, strikes_int = _int(balls_val), _int(strikes_val)
            else:
                balls_int, strikes_int = _derive_balls_strikes_from_sequence(pitch_seq)

            action_type = (props.get('RUNNER_ACTION0') or props.get('ACTION', '') or '').strip()
            outs_before = _int(props.get('CURRENT_OUTS', 0))
            outs_on_play = sum(1 for i in range(4) if props.get(f'OUT{i}', 'false').lower() == 'true')
            runs_scored = sum(1 for i in range(4) if props.get(f'SCORE{i}', 'false').lower() == 'true')
            rbi = _int(props.get('RBI', 0))
            try:
                aft = json.loads(props.get('OFF_PLAYERS_AFT', '[-1,-1,-1,-1]'))
                runners_after = (
                    ('1' if len(aft) > 1 and aft[1] != -1 else '0') +
                    ('1' if len(aft) > 2 and aft[2] != -1 else '0') +
                    ('1' if len(aft) > 3 and aft[3] != -1 else '0')
                )
            except Exception:
                runners_after = '000'

            # OFF_PLAYERS_BEF: [1b_uni, 2b_uni, 3b_uni] — resolve to names
            off_roster = home_roster if home_team_bat else vis_roster
            runner_first = runner_second = runner_third = ''
            try:
                bef = json.loads(props.get('OFF_PLAYERS_BEF', '[-1,-1,-1,-1]'))
                for idx, uni in enumerate([bef[i] if len(bef) > i else -1 for i in (1, 2, 3)]):
                    if uni is not None and uni != -1:
                        pl = off_roster.get(str(uni)) or off_roster.get(int(uni))
                        name = _short(pl) if pl else ''
                        if idx == 0:
                            runner_first = name
                        elif idx == 1:
                            runner_second = name
                        else:
                            runner_third = name
            except Exception:
                pass

            db.session.add(Play(
                game_id=game.id, inning=inning_num,
                half='bottom' if home_team_bat else 'top',
                sequence=sequence, outs_before=outs_before,
                batter_name=batter_name, pitcher_name=pitcher_name,
                pitch_sequence=pitch_seq, balls=balls_int, strikes=strikes_int,
                narrative=narrative, action_type=action_type,
                rbi=rbi, outs_on_play=outs_on_play,
                runs_scored=runs_scored, runners_after=runners_after,
                runner_first=runner_first, runner_second=runner_second, runner_third=runner_third,
            ))

    # Renumber sequences consecutively (1,2,3...) game-wide — first play is 1, never reset
    db.session.flush()
    plays = Play.query.filter_by(game_id=game.id).all()
    half_ord = lambda h: 0 if (h or '').lower() == 'top' else 1
    plays.sort(key=lambda p: (p.inning, half_ord(p.half), p.sequence))
    for seq, p in enumerate(plays, start=1):
        p.sequence = seq


def _season_dates(season_obj):
    """
    Return (startDate, endDate) in M/d/yyyy format for a Season.
    Derived from the actual game dates in the season so the GWT week
    generator always covers every game.  Falls back to Jan 1 – Dec 31
    of the season year if no games exist.
    """
    games = (
        Game.query
        .join(Team, Game.visitor_team_id == Team.id)
        .filter(Team.season_id == season_obj.id)
        .with_entities(Game.date)
        .all()
    )
    dates = [g.date for g in games if g.date]
    if dates:
        raw_start = min(dates)
        raw_end   = max(dates)
    else:
        year = season_obj.name[:4] if season_obj.name[:4].isdigit() else "2025"
        raw_start = f"{year}-01-01"
        raw_end   = f"{year}-12-31"

    return _date_db_to_gwt(raw_start), _date_db_to_gwt(raw_end)


def _seasons_payload(seasons_qs):
    """
    Build the 'seasons' array that the GWT data manager expects.
    Each entry needs at minimum: id, startDate, endDate (M/d/yyyy).
    GWT's $loadStatGame matches season_id attribute against season['id'].
    """
    out = []
    for s in seasons_qs:
        start, end = _season_dates(s)
        out.append({
            "id":        str(s.id),
            "name":      s.name,
            "startDate": start or "1/1/2025",
            "endDate":   end   or "12/31/2025",
        })
    return out


def _build_player_obj(player, batting, pitching, fielding, participated, is_initial_roster=False):
    """Build the GWT player object for boxscore.teams[i].players.
    When is_initial_roster=True (app first starting, no saved state), only Name, number, b/t, class are sent."""
    uni = player.uniform_number or ""

    # "Last, First" format — fall back to full name if no last/first split
    if player.last_name:
        complete = f"{player.last_name}, {player.first_name or ''}".strip(', ')
    else:
        complete = player.name or ""

    if is_initial_roster:
        return {
            "uniform":              uni,
            "completeName":         complete,
            "batProfile":           player.bats or "",
            "pitcherThrowsProfile": player.throws or "",
            "class":                player.player_class or "",
            "pos":                  "",
            "starter":              False,
            "participated":         False,
            "readOrder":            0,
            "spot":                 0,
            "initialSpot":          0,
            "starterPosition":      0,
        }

    # Position: prefer game batting position, then player's default
    pos = ""
    if batting and batting.position:
        pos = batting.position
    elif fielding and fielding.position:
        pos = fielding.position
    elif player.position:
        pos = player.position

    order = (batting.batting_order or 0) if batting else 0
    # is_actual_starter: only players GWT flagged as starter=True get initialSpot set.
    # Pinch hitters/subs have is_starter=False in the DB; giving them initialSpot > 0
    # causes two players to share the same slot in GWT's currentBattingOrder, which
    # corrupts every subsequent batter assignment after the sub.
    is_actual_starter = bool(batting and batting.is_starter)
    on_field = participated or is_actual_starter or bool(batting and (batting.batting_order or batting.position))

    # starterPosition: the GWT numeric defensive-position index stored in the blob.
    # For regular batters (order 1-9) GWT sets this directly during lineup setup; we
    # preserve the blob value, so the DB-only fallback only needs to handle the FLEX
    # (order=10 / DH-fielder) whose index MUST come from their position string.
    # For all starters we map the position string to a GWT index so that $initBattingOrder
    # sets playedPosition correctly and the field/lineup-editor display is accurate.
    _pos_lower = pos.lower().strip() if pos else ''
    starter_pos_idx = _GWT_POS_INDEX.get(_pos_lower, 0)

    return {
        "uniform":              uni,
        "completeName":         complete,
        "lastName":             player.last_name or player.name or "",
        "firstName":            player.first_name or "",
        "pos":                  pos,
        "position":             "",
        "offPosition":          "",
        "defPosition":          pos,
        "starter":              is_actual_starter,
        "starterDef":           is_actual_starter,
        "starterOff":           False,
        "onField":              on_field,
        "participated":         participated,
        "inactive":             player.disabled or False,
        "readOrder":            order,
        "spot":                 order,
        "initialSpot":          order if (is_actual_starter and 1 <= order <= 10) else 0,
        # For batters (order 1-9) GWT will overwrite starterPosition from the blob on
        # the next save; passing order as a fallback is safe.  For the FLEX/DH-fielder
        # (order=10) we supply the mapped position index so $initBattingOrder sets
        # playedPosition correctly and the lineup-editor slot 10 shows the right position.
        "starterPosition":      starter_pos_idx if (is_actual_starter and order > 9 and starter_pos_idx) else (order if (is_actual_starter and 1 <= order <= 9) else 0),
        "goalie":               False,
        "goalieStarter":        False,
        # Bats / Throws
        "batProfile":           player.bats   or "",
        "pitcherThrowsProfile": player.throws or "",
        "year":                 0,
        # Batting stats
        "hittingAb":            (batting.ab       if batting else 0),
        "hittingR":             (batting.r        if batting else 0),
        "hittingH":             (batting.h        if batting else 0),
        "hittingRbi":           (batting.rbi      if batting else 0),
        "hittingDouble":        (batting.doubles  if batting else 0),
        "hittingTriple":        (batting.triples  if batting else 0),
        "hittingHr":            (batting.hr       if batting else 0),
        "hittingBb":            (batting.bb       if batting else 0),
        "hittingSb":            (batting.sb       if batting else 0),
        "hittingCs":            (batting.cs       if batting else 0),
        "hittingHbp":           (batting.hbp      if batting else 0),
        "hittingSh":            (batting.sh       if batting else 0),
        "hittingSf":            (batting.sf       if batting else 0),
        "hittingSo":            (batting.so       if batting else 0),
        "hittingGdp":           (batting.gdp      if batting else 0),
        "hittingIbb":           (batting.ibb      if batting else 0),
        "hittingGround":        (batting.ground   if batting else 0),
        "hittingFly":           (batting.fly      if batting else 0),
        "hittingKl":            (batting.kl       if batting else 0),
        "hittingHitdp":         0,
        "hittingPicked":        0,
        "hitSumLob":            0,
        "hitSumReachedErr":     0,
        "hitSumReachedFc":      0,
        "hitSum2OutsAb":        0,
        "hitSum2OutsH":         0,
        "hitSumWRunnersAb":     0,
        "hitSumWRunnersH":      0,
        "hitSumRbiOpsAb":       0,
        "hitSumRbiOpsH":        0,
        "hitSumVsLeftAb":       0,
        "hitSumVsLeftH":        0,
        "hitSumAdvOpsOps":      0,
        "hitSumAdvOpsNo":       0,
        "hitSumAdv":            0,
        "hitSumLeadoffOps":     0,
        "hitSumLeadoffNo":      0,
        "hitSumRbi2Out":        0,
        "hitSumLoadedAb":       0,
        "hitSumLoadedH":        0,
        "hitSumPinchHitAb":     0,
        "hitSumPinchHitH":      0,
        "hitSumRbi3rdNo":       0,
        "hitSumRbi3rdOps":      0,
        # Fielding stats
        "fieldingPo":           (fielding.po  if fielding else 0),
        "fieldingA":            (fielding.a   if fielding else 0),
        "fieldingE":            (fielding.e   if fielding else 0),
        "fieldingPb":           (fielding.pb  if fielding else 0),
        "fieldingIndp":         0,
        "fieldingIntp":         0,
        "fieldingCi":           (fielding.ci  if fielding else 0),
        "fieldingCsb":          0,
        "fieldingSba":          (fielding.sba if fielding else 0),
        # Pitching stats
        "pitchingIp":           round(pitching.ip, 1) if pitching else 0.0,
        "pitchingH":            (pitching.h   if pitching else 0),
        "pitchingR":            (pitching.r   if pitching else 0),
        "pitchingEr":           (pitching.er  if pitching else 0),
        "pitchingBb":           (pitching.bb  if pitching else 0),
        "pitchingSo":           (pitching.so  if pitching else 0),
        "pitchingBf":           (pitching.bf  if pitching else 0),
        "pitchingWp":           (pitching.wp  if pitching else 0),
        "pitchingBk":           (pitching.bk  if pitching else 0),
        "pitchingHbp":          (pitching.hbp if pitching else 0),
        "pitchingFly":          0,
        "pitchingHr":           (pitching.hr  if pitching else 0),
        "pitchingKl":           0,
        "pitchingGround":       0,
        "pitchingIbb":          0,
        "pitchingGdp":          0,
        "pitchingDouble":       0,
        "pitchingTriple":       0,
        "pitchingAb":           0,
        "pitchingPicked":       0,
        "pitchingSha":          0,
        "pitchingSfa":          0,
        "pitSumLeadoffOps":     0,
        "pitSumLeadoffNo":      0,
        "pitSumRunnersAb":      0,
        "pitSumRunnersH":       0,
        "pitSumVsLeftAb":       0,
        "pitSumVsLeftH":        0,
        "pitSum2OutsAb":        0,
        "pitSum2OutsH":         0,
        "pitSumTmUnearned":     0,
        "statsPerPeriod":       {},
    }


def _build_event_payload(game, sport_code="1"):
    """Build the GWT event.json array element for a single game.

    If a raw boxscore blob was saved by saveboxscore/saveGame, it is returned
    verbatim for the 'boxscore' key so GWT reloads exactly the state it last
    saved.  The wrapper fields (psId, teams, status) are always rebuilt from the
    DB so the gameday page stays in sync.
    """
    import json as json_mod
    vis  = game.visitor_team
    home = game.home_team

    game_date_gwt = _date_db_to_gwt(game.date) or "1/1/2025"
    time_str      = game.start_time or "TBA"
    scheduled     = game.scheduled_innings or 7
    location      = game.location or (home.stadium if home else "") or ""

    # ── Per-team player list ────────────────────────────────────────────────
    is_initial = not bool(game.gwt_bs_blob)

    def _players_for_team(team):
        if not team:
            return []
        batting_map  = {bs.player_id: bs for bs in game.batting_stats  if bs.team_id == team.id}
        pitching_map = {ps.player_id: ps for ps in game.pitching_stats if ps.team_id == team.id}
        fielding_map = {fs.player_id: fs for fs in game.fielding_stats if fs.team_id == team.id}

        # All players who appear in stats OR on the team roster
        stats_pids  = set(batting_map) | set(pitching_map) | set(fielding_map)
        roster_map  = {p.id: p for p in team.players if not p.disabled}
        all_pids    = stats_pids | set(roster_map.keys())

        result = []
        for pid in all_pids:
            player = roster_map.get(pid) or Player.query.get(pid)
            if not player:
                continue
            batting     = batting_map.get(pid)
            pitching    = pitching_map.get(pid)
            fielding    = fielding_map.get(pid)
            participated = bool(batting or pitching or fielding)
            result.append(_build_player_obj(
                player, batting, pitching, fielding, participated,
                is_initial_roster=is_initial
            ))

        # Sort: batting order (1-9) first, then bench (spot=0), then by uniform
        result.sort(key=lambda x: (
            0 if (x["readOrder"] and x["readOrder"] > 0) else 1,
            x["readOrder"] if x["readOrder"] else 999,
            x["uniform"] or "999",
        ))
        return result

    # ── Inning-by-inning line score ─────────────────────────────────────────
    inning_map     = {i.inning: i for i in game.innings}
    played_innings = len(inning_map)   # actual innings saved to DB

    # periodstats array length:
    #   not started (no lineup)  → 1 empty entry so GWT opens at inning 1
    #   lineup entered / started → full scheduled span so all innings show
    ps_count = scheduled if (played_innings or game.has_lineup) else 1

    def _periodstats(is_home):
        out = []
        for inn in range(1, ps_count + 1):
            row = inning_map.get(inn)
            if row:
                try:
                    score = int(row.home_score if is_home else row.visitor_score)
                except (TypeError, ValueError):
                    score = 0
            else:
                score = 0
            out.append({"score": score})
        return out

    # ── Boxscore teams ──────────────────────────────────────────────────────
    boxscore_teams = []
    for team, is_home in [(vis, False), (home, True)]:
        boxscore_teams.append({
            "psId":        str(team.id) if team else "0",
            "name":        team.name    if team else "",
            "abbr":        (team.abbreviation or team.code or "")[:10] if team else "",
            "record":      (game.home_record if is_home else game.visitor_record) or "",
            "record_conf": (game.home_conf   if is_home else game.visitor_conf)   or "",
            "players":     _players_for_team(team),
            "periodstats": _periodstats(is_home),
        })

    # ── Status ──────────────────────────────────────────────────────────────
    # Final: marked complete AND has inning data.
    # In Progress: has inning data, OR lineups have been entered (0-0 Top 1st).
    # Scheduled: nothing entered yet.
    if game.is_complete and played_innings > 0:
        statuscode = 0
        status_str = "Final"
    elif inning_map or game.has_lineup:
        statuscode = -1
        status_str = "In Progress"
    else:
        statuscode = -2
        status_str = "Scheduled"


    # Use the stored GWT boxscore blob if available; otherwise build from DB.
    # The blob is the raw 'bs' JSON GWT last saved via saveboxscore/saveGame —
    # returning it verbatim lets GWT restore state exactly as it left it.
    if game.gwt_bs_blob:
        try:
            boxscore = json_mod.loads(game.gwt_bs_blob)
        except (ValueError, TypeError):
            boxscore = None
    else:
        boxscore = None

    # NOTE: FLEX/DH-fielder players (initialSpot=10) are handled correctly by
    # patched GWT client code: $initBattingOrder now skips adding them to
    # currentBattingOrder when their spot exceeds team.maxBatters (9), and
    # $findPlayerBySpot has a fallback to find them by spot field.  No
    # server-side initialSpot sanitization is needed.
    #
    if boxscore:
        _sanitize_boxscore_batting_order(boxscore)
        # Merge game metadata into blob's eventInfo so persisted values show on reload
        ei = boxscore.setdefault("eventInfo", {})
        def _fill(key, val, fmt=str):
            if not (ei.get(key) or ""):
                ei[key] = fmt(val) if val is not None else ""
        _fill("date", _date_db_to_gwt(game.date))
        _fill("timeStart", game.start_time)
        _fill("location", game.location)
        _fill("stadium", game.stadium)
        _fill("duration", game.duration)
        _fill("weather", game.weather)
        _fill("notes", game.notes)
        _fill("delay", game.delayed_time)
        _fill("delayedTime", game.delayed_time)
        if game.attendance is not None and "attendance" not in ei:
            ei["attendance"] = game.attendance
        if game.scheduled_innings:
            if "scheduledInnings" not in ei:
                ei["scheduledInnings"] = game.scheduled_innings
            if "gamePeriods" not in ei:
                ei["gamePeriods"] = game.scheduled_innings
            if "rulesPeriods" not in ei:
                ei["rulesPeriods"] = game.scheduled_innings
        if "dhRule" not in ei and game.used_dh is not None:
            ei["dhRule"] = game.used_dh != "no"
        if "night" not in ei:
            ei["night"] = bool(game.is_night)
        if "conference" not in ei:
            ei["conference"] = bool(game.is_league_game)
        if "confDivision" not in ei:
            ei["confDivision"] = bool(game.is_conf_division)
        if "exhibition" not in ei:
            ei["exhibition"] = bool(game.is_exhibition)
        if "neutral" not in ei:
            ei["neutral"] = bool(game.is_neutral)
        refs = ei.get("referees") or []
        if not any((r or "").strip() for r in refs) and (game.ump_hp or game.ump_1b or game.ump_2b or game.ump_3b):
            ei["referees"] = [game.ump_hp or "", game.ump_1b or "", game.ump_2b or "", game.ump_3b or ""]
        # Team records
        teams = boxscore.get("teams") or []
        if len(teams) >= 1 and (game.visitor_record or game.visitor_conf):
            if not (teams[0].get("record") or ""):
                teams[0]["record"] = game.visitor_record or ""
            if not (teams[0].get("record_conf") or ""):
                teams[0]["record_conf"] = game.visitor_conf or ""
        if len(teams) >= 2 and (game.home_record or game.home_conf):
            if not (teams[1].get("record") or ""):
                teams[1]["record"] = game.home_record or ""
            if not (teams[1].get("record_conf") or ""):
                teams[1]["record_conf"] = game.home_conf or ""

    if boxscore is None:
        # First load (no blob yet) — build boxscore from DB so GWT can initialise
        # Determine current inning for GWT: same half-inning logic as status_label
        if inning_map:
            _last_num = max(inning_map.keys())
            _last = inning_map[_last_num]
            try:
                _lv = int(_last.visitor_score or 0)
                _lh = int(_last.home_score or 0)
            except (TypeError, ValueError):
                _lv, _lh = 0, 0
            current_period = _last_num if (_lv > 0 and _lh == 0) else _last_num + 1
        else:
            current_period = 1

        boxscore = {
            "countPeriods": played_innings if played_innings else 1,
            "gamePeriods":  scheduled,
            "eventInfo": {
                "date":              game_date_gwt,
                "timeStart":         time_str,
                "location":          location,
                "stadium":           game.stadium or "",
                "duration":          game.duration or "",
                "attendance":        game.attendance if game.attendance is not None else 0,
                "weather":           game.weather or "",
                "notes":             game.notes or "",
                "delay":             game.delayed_time or "",
                "statusPeriod":      current_period,
                "gamePeriods":       scheduled,
                "rulesPeriods":      scheduled,
                "scheduledInnings":  scheduled,
                "visBatters":        9,
                "homeBatters":       9,
                "dhRule":            (game.used_dh != "no") if game.used_dh else True,
                "useDp":             sport_code in ('sb', 'wsb', '11'),
                "dhGame":            0,
                "night":             game.is_night      or False,
                "isHomeOffensive":   False,
                "conference":        game.is_league_game or False,
                "confDivision":      game.is_conf_division or False,
                "exhibition":        game.is_exhibition  or False,
                "neutral":           game.is_neutral     or False,
                "postseason":        False,
                "referees":          [
                    game.ump_hp or "",
                    game.ump_1b or "",
                    game.ump_2b or "",
                    game.ump_3b or "",
                ],
                "pitcherRecordWinUni":  -1,
                "pitcherRecordWin":     "",
                "pitcherRecordLossUni": -1,
                "pitcherRecordLoss":    "",
                "pitcherSaveUni":       -1,
                "pitcherSave":          -1,
            },
            "teams": boxscore_teams,
            "plays": {},
        }

    return {
        "psId":                 str(game.id),
        "sportCode":            str(sport_code),
        "last_update_timestamp": 0,
        "primeTime":            False,
        "has_xml_stats":        False,

        # Top-level teams — always from DB so gameday page stays current
        "teams": [
            {
                "psId":        str(vis.id)  if vis  else "0",
                "name":        vis.name     if vis  else "Visitor",
                "custom_name": "",
                "result":      str(game.visitor_runs or 0),
            },
            {
                "psId":        str(home.id) if home else "0",
                "name":        home.name    if home else "Home",
                "custom_name": "",
                "result":      str(game.home_runs or 0),
            },
        ],

        "status": {
            "statuscode":  statuscode,
            "status":      status_str,
            "date":        f"{game_date_gwt} {time_str}",
            "away_score":  game.visitor_runs or 0,
            "home_score":  game.home_runs   or 0,
            "conference":  game.is_league_game or False,
            "division":    game.is_conf_division or False,
            "region":      game.is_region    or False,
            "exhibition":  game.is_exhibition or False,
            "neutral":     game.is_neutral   or False,
            "postseason":  False,
            "location":    location,
        },

        "boxscore":   boxscore,
        "seasonStats": {},
    }


# ── Real implementations ───────────────────────────────────────────────────────

@gwtapi_bp.route('/auth.json', methods=['POST'])
def auth():
    # GWT sends 'e' (login) and 'p' (SHA-256 password hash)
    login    = request.form.get('e', '')
    password = request.form.get('p', '')
    _log('auth.json', request.form)

    user = User.query.filter_by(username=login, is_active=True).first()
    if not (user and user.password_sha256 == password):
        return jsonify({"error": "Invalid credentials"}), 401

    # GWT $verifyResponse() checks auth=="yes" and reads seasons[] to populate
    # the local data manager.  Without seasons the GWT aborts in $loadStatGame.
    all_seasons = Season.query.all()
    return jsonify({
        "auth":    "yes",
        "access":  "STATSENTRY_LIVE",
        "id":      str(user.id),
        "login":   user.username,
        "name":    user.display_name or user.username,
        "role":    user.role,
        "seasons": _seasons_payload(all_seasons),
    })


@gwtapi_bp.route('/season.json', methods=['POST'])
def season():
    """
    Called right after auth with ev=<event_id>.
    $onSuccess_13 passes this response through $verifyResponse() again,
    so it also needs auth=="yes" and seasons[].
    """
    _log('season.json', request.form)
    all_seasons = Season.query.all()
    return jsonify({
        "auth":    "yes",
        "access":  "STATSENTRY_LIVE",
        "seasons": _seasons_payload(all_seasons),
    })


@gwtapi_bp.route('/seasons.json', methods=['POST'])
def seasons():
    _log('seasons.json', request.form)
    all_seasons = Season.query.all()
    return jsonify([
        {"id": str(s.id), "name": s.name, "year": s.name[:4] if len(s.name) >= 4 else s.name}
        for s in all_seasons
    ])


@gwtapi_bp.route('/events.json', methods=['POST'])
def events():
    _log('events.json', request.form)
    season_id = request.form.get('s')
    try:
        sid = int(season_id)
    except (TypeError, ValueError):
        return jsonify([])
    games = Game.query.filter(
        (Game.visitor_team.has(season_id=sid)) | (Game.home_team.has(season_id=sid))
    ).all()
    result = []
    for g in games:
        vis  = g.visitor_team
        home = g.home_team
        result.append({
            "id":      str(g.id),
            "name":    f"{vis.name if vis else 'Visitor'} at {home.name if home else 'Home'}",
            "date":    g.date or "",
            "visitor": vis.name  if vis  else "Visitor",
            "home":    home.name if home else "Home",
            "status":  "final" if g.is_complete else "scheduled",
        })
    return jsonify(result)


@gwtapi_bp.route('/event.json', methods=['POST'])
def event():
    _log('event.json', request.form)
    event_id   = request.form.get('evt')
    sport_code = request.form.get('sport_code', '1')
    try:
        eid = int(event_id)
    except (TypeError, ValueError):
        return jsonify([])
    game = Game.query.get(eid)
    if not game:
        return jsonify([])
    return jsonify([_build_event_payload(game, sport_code)])


@gwtapi_bp.route('/saveGame.json', methods=['POST'])
def save_game():
    import json as json_mod
    _log('saveGame.json', request.form)

    raw = request.form.get('jsonData') or request.get_data(as_text=True)
    if not raw:
        return jsonify({"ok": True})

    try:
        data = json_mod.loads(raw)
    except (ValueError, TypeError):
        return jsonify({"ok": True})

    if isinstance(data, list):
        data = data[0] if data else {}

    event_id = data.get('psId') or request.form.get('evt')
    try:
        eid = int(event_id)
    except (TypeError, ValueError):
        return jsonify({"ok": True})

    game = Game.query.get(eid)
    if not game:
        return jsonify({"ok": True})

    def _int(v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    def _float(v):
        try:
            return float(v or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # --- Store raw GWT boxscore blob ---
    # saveGame sends the full event object; extract the boxscore section and store
    # it so event.json can return it verbatim on reload.
    # Sanitize currentBattingOrder so we never persist 10-entry arrays (prevents
    # $onBack crashes when user backs out of pitch menu and re-enters).
    _bs_section = data.get('boxscore')
    if _bs_section:
        import json as _json_mod2
        _sanitize_boxscore_batting_order(_bs_section)
        _sync_live_count_in_boxscore(_bs_section)
        game.gwt_bs_blob = _json_mod2.dumps(_bs_section)

    # --- Status ---
    status_block = data.get('status', {})
    statuscode = _int(status_block.get('statuscode', -2))

    # --- Inning scores ---
    boxscore = data.get('boxscore', {})
    bs_teams = boxscore.get('teams', [])

    vis_periods  = bs_teams[0].get('periodstats', []) if len(bs_teams) > 0 else []
    home_periods = bs_teams[1].get('periodstats', []) if len(bs_teams) > 1 else []
    max_periods  = max(len(vis_periods), len(home_periods), 0)

    # --- Detect real stat save vs lineup sync (same logic as saveboxscore) ---
    any_participated = any(
        bool(pdata.get('participated'))
        for bs_team in bs_teams
        for pdata in bs_team.get('players', [])
    )
    total_ab = sum(
        _int(pdata.get('hittingAb', 0))
        for bs_team in bs_teams
        for pdata in bs_team.get('players', [])
    )
    real_stat_save = any_participated or total_ab > 0

    # Lineup detection (same as saveboxscore)
    any_ordered = any(
        _int(pdata.get('spot') or pdata.get('readOrder') or 0) > 0
        for bs_team in bs_teams
        for pdata in bs_team.get('players', [])
    )
    if any_ordered:
        game.has_lineup = True

    # Only trust game-complete status from real stat saves
    if real_stat_save:
        game.is_complete = (statuscode == 0)

    # Mark Final when pitching decisions (W/L) and total time have been entered
    ei = boxscore.get('eventInfo') or {}
    win_uni = _int(ei.get('pitcherRecordWinUni', -1))
    loss_uni = _int(ei.get('pitcherRecordLossUni', -1))
    duration = (ei.get('duration') or '').strip()
    if win_uni != -1 and loss_uni != -1 and duration:
        game.is_complete = True
        game.duration = duration

    _persist_setup_to_game(game, ei, bs_teams, _int)

    # Inning scores: trim trailing 0-0 innings so unstarted games don't create
    # phantom innings that push GWT to the last inning on reload
    innings_to_save = []
    for i in range(max_periods):
        vs = _int(vis_periods[i].get('score'))  if i < len(vis_periods)  else 0
        hs = _int(home_periods[i].get('score')) if i < len(home_periods) else 0
        innings_to_save.append((i + 1, vs, hs))
    while innings_to_save and innings_to_save[-1][1] == 0 and innings_to_save[-1][2] == 0:
        innings_to_save.pop()
    if innings_to_save:
        InningScore.query.filter_by(game_id=game.id).delete()
        for inning_num, v_score, h_score in innings_to_save:
            db.session.add(InningScore(game_id=game.id, inning=inning_num,
                                       visitor_score=str(v_score),
                                       home_score=str(h_score)))
        game.visitor_runs = sum(v for _, v, _ in innings_to_save)
        game.home_runs    = sum(h for _, _, h in innings_to_save)

    # --- Player stats ---
    for idx, bs_team in enumerate(bs_teams[:2]):
        is_home  = (idx == 1)
        team_obj = game.home_team if is_home else game.visitor_team
        if not team_obj:
            continue

        roster = {p.uniform_number: p for p in team_obj.players if p.uniform_number}

        if real_stat_save:
            # Preserve is_starter=True for any player already marked as a starter
            # before wiping stats.  GWT resets starter=False for the FLEX between
            # saves; this ensures their is_starter status survives a full stats rebuild.
            prev_starter_ids = {
                bs.player_id
                for bs in BattingStats.query.filter_by(
                    game_id=game.id, team_id=team_obj.id
                ).all()
                if bs.is_starter
            }
            BattingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).delete()
            PitchingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).delete()
            FieldingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).delete()
        else:
            prev_starter_ids = set()
            existing_batting = {
                bs.player_id: bs
                for bs in BattingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).all()
            }

        # Accumulate pitching/fielding per player — GWT can send same player multiple
        # times (e.g. starter + re-entry), causing duplicate PitchingStats and inflated IP.
        pit_accum = {}  # player_id -> {ip_thirds, h, r, er, bb, so, bf, ...}
        fld_accum = {}  # player_id -> {po, a, e, pb, ci, sba, position}

        for pdata in bs_team.get('players', []):
            participated = bool(pdata.get('participated'))
            on_field     = bool(pdata.get('onField'))
            starter      = bool(pdata.get('starter'))
            spot         = _int(pdata.get('spot') or pdata.get('readOrder') or 0)
            pos          = (pdata.get('pos') or pdata.get('defPosition') or '').strip()
            # GWT stores the defensive position as a numeric index but does not
            # always populate the pos string field.  Derive it when pos is empty.
            if not pos:
                _pidx = int(pdata.get('playedPosition') or 0)
                if _pidx <= 0:
                    _pidx = int(pdata.get('starterPosition') or 0)
                pos = _GWT_POS_DESC.get(_pidx, '')

            if not participated and not on_field and not starter and not spot and not pos:
                continue

            uni    = str(pdata.get('uniform', '')).strip()
            player = roster.get(uni)
            if not player:
                player = Player.query.filter_by(
                    team_id=team_obj.id,
                    last_name=pdata.get('lastName', ''),
                    first_name=pdata.get('firstName', ''),
                ).first()
            if not player:
                continue

            if not real_stat_save:
                existing = existing_batting.get(player.id)
                if existing:
                    if spot: existing.batting_order = spot
                    if pos:  existing.position      = pos
                    # Only GWT's starter=True promotes is_starter; onField alone
                    # means a sub/pinch-hitter came on and must NOT set is_starter.
                    if starter: existing.is_starter = True
                elif spot > 0 or (pos and (starter or on_field)):
                    db.session.add(BattingStats(
                        game_id=game.id, player_id=player.id, team_id=team_obj.id,
                        batting_order=spot, position=pos,
                        is_starter=starter,
                        is_sub=on_field and not starter,
                        ab=0, r=0, h=0, rbi=0, doubles=0, triples=0, hr=0,
                        bb=0, so=0, sb=0, cs=0, hbp=0, sh=0, sf=0,
                        gdp=0, ibb=0, ground=0, fly=0, kl=0,
                    ))
                continue

            # Preserve is_starter=True for players previously marked as starters
            is_starter_final = starter or (player.id in prev_starter_ids)
            db.session.add(BattingStats(
                game_id=game.id, player_id=player.id, team_id=team_obj.id,
                batting_order=spot,
                position=pos,
                is_starter=is_starter_final,
                is_sub=participated and not is_starter_final,
                ab=_int(pdata.get('hittingAb')),
                r=_int(pdata.get('hittingR')),
                h=_int(pdata.get('hittingH')),
                rbi=_int(pdata.get('hittingRbi')),
                doubles=_int(pdata.get('hittingDouble')),
                triples=_int(pdata.get('hittingTriple')),
                hr=_int(pdata.get('hittingHr')),
                bb=_int(pdata.get('hittingBb')),
                so=_int(pdata.get('hittingSo')),
                sb=_int(pdata.get('hittingSb')),
                cs=_int(pdata.get('hittingCs')),
                hbp=_int(pdata.get('hittingHbp')),
                sh=_int(pdata.get('hittingSh')),
                sf=_int(pdata.get('hittingSf')),
                gdp=_int(pdata.get('hittingGdp')),
                ibb=_int(pdata.get('hittingIbb')),
                ground=_int(pdata.get('hittingGround')),
                fly=_int(pdata.get('hittingFly')),
                kl=_int(pdata.get('hittingKl')),
            ))

            if not participated:
                continue

            ip = _float(pdata.get('pitchingIp'))
            if ip or _int(pdata.get('pitchingSo')) or _int(pdata.get('pitchingH')) or _int(pdata.get('pitchingR')):
                ip_full, ip_frac = int(ip), round((ip - int(ip)) * 10)
                thirds = ip_full * 3 + ip_frac
                cur = pit_accum.get(player.id, {'thirds': 0, 'h': 0, 'r': 0, 'er': 0, 'bb': 0, 'so': 0, 'bf': 0})
                cur['thirds'] += thirds
                cur['h']  += _int(pdata.get('pitchingH'))
                cur['r']  += _int(pdata.get('pitchingR'))
                cur['er'] += _int(pdata.get('pitchingEr'))
                cur['bb'] += _int(pdata.get('pitchingBb'))
                cur['so'] += _int(pdata.get('pitchingSo'))
                cur['bf'] += _int(pdata.get('pitchingBf'))
                pit_accum[player.id] = cur

            po = _int(pdata.get('fieldingPo'))
            a  = _int(pdata.get('fieldingA'))
            e  = _int(pdata.get('fieldingE'))
            if po or a or e:
                cur = fld_accum.get(player.id, {'po': 0, 'a': 0, 'e': 0, 'pb': 0, 'ci': 0, 'sba': 0, 'pos': pos})
                cur['po']  += po
                cur['a']   += a
                cur['e']   += e
                cur['pb']  += _int(pdata.get('fieldingPb'))
                cur['ci']  += _int(pdata.get('fieldingCi'))
                cur['sba'] += _int(pdata.get('fieldingSba'))
                cur['pos'] = pos or cur['pos']
                fld_accum[player.id] = cur

        for pid, acc in pit_accum.items():
            thirds = acc['thirds']
            ip_val = (thirds // 3) + (thirds % 3) / 10.0 if thirds % 3 else thirds // 3
            db.session.add(PitchingStats(
                game_id=game.id, player_id=pid, team_id=team_obj.id,
                ip=ip_val, h=acc['h'], r=acc['r'], er=acc['er'],
                bb=acc['bb'], so=acc['so'], bf=acc['bf'],
            ))
        for pid, acc in fld_accum.items():
            db.session.add(FieldingStats(
                game_id=game.id, player_id=pid, team_id=team_obj.id,
                position=acc['pos'], po=acc['po'], a=acc['a'], e=acc['e'],
                pb=acc['pb'], ci=acc['ci'], sba=acc['sba'],
            ))

    db.session.flush()

    # Recompute hits and errors from saved player stats
    for is_home, team_obj in [(False, game.visitor_team), (True, game.home_team)]:
        if not team_obj:
            continue
        bat = BattingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).all()
        fld = FieldingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).all()
        if is_home:
            game.home_hits   = sum(b.h for b in bat)
            game.home_errors = sum(f.e for f in fld)
        else:
            game.visitor_hits   = sum(b.h for b in bat)
            game.visitor_errors = sum(f.e for f in fld)

    # Parse and persist plays (same as reference stat entry — XML reflects plays on save)
    _parse_and_persist_plays(game, boxscore, _int)

    _save_version(game)
    db.session.commit()
    return jsonify({"ok": True, "saved": True})


@gwtapi_bp.route('/networkEvent.json', methods=['POST'])
def network_event():
    return _stub('networkEvent.json')


@gwtapi_bp.route('/seasonrosters.json', methods=['POST'])
def season_rosters():
    # GWT expects an array (or empty array) — not a plain object
    _log('seasonrosters.json', request.form)
    return jsonify([])


@gwtapi_bp.route('/seasonTeams.json', methods=['GET', 'POST'])
def season_teams():
    _log('seasonTeams.json', request.args if request.method == 'GET' else request.form)
    season_id = request.args.get('s') or request.form.get('s')
    try:
        sid = int(season_id)
    except (TypeError, ValueError):
        return jsonify([])
    teams = Team.query.filter_by(season_id=sid).all()
    return jsonify([
        {"id": str(t.id), "name": t.name, "code": t.code, "abbreviation": t.abbreviation or t.code}
        for t in teams
    ])


def _persist_boxscore_full(game, bs, statuscode=-2, live_stats_raw=''):
    """
    Full boxscore persist: blob, setup, inning scores, batting/pitching/fielding stats, plays.
    Called by saveboxscore (explicit save) and processRawPlay (every data sync/change).
    When statuscode=-2 (default), is_complete is not changed from GWT statuscode.
    When live_stats_raw is empty, entry_mode is not changed.
    """
    def _int(v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    def _float(v):
        try:
            return float(v or 0.0)
        except (TypeError, ValueError):
            return 0.0

    _sanitize_boxscore_batting_order(bs)
    _sync_live_count_in_boxscore(bs)

    bs_teams = bs.get('teams', [])

    # --- Entry mode (only when explicitly provided, e.g. from saveboxscore) ---
    if live_stats_raw:
        lr = live_stats_raw.lower()
        if lr == 'true':
            game.entry_mode = 'pbp_simple'
        elif lr == 'false':
            game.entry_mode = 'box_game_totals'

    vis_periods  = bs_teams[0].get('periodstats', []) if len(bs_teams) > 0 else []
    home_periods = bs_teams[1].get('periodstats', []) if len(bs_teams) > 1 else []
    max_periods  = max(len(vis_periods), len(home_periods), 0)

    # --- Detect whether this is a real stat save vs a lineup/reload sync ---
    # GWT resets 'participated' to False at the start of each browser session even
    # for players who have historical stats, so we cannot rely on it alone.
    # A "real" save has participated=True OR has actual at-bat totals in the payload.
    any_participated = any(
        bool(pdata.get('participated'))
        for bs_team in bs_teams
        for pdata in bs_team.get('players', [])
    )
    total_ab = sum(
        _int(pdata.get('hittingAb', 0))
        for bs_team in bs_teams
        for pdata in bs_team.get('players', [])
    )
    real_stat_save = any_participated or total_ab > 0

    # --- Lineup detection ---
    # Mark the game as having lineups entered once any player has a batting order slot.
    any_ordered = any(
        _int(pdata.get('spot') or pdata.get('readOrder') or 0) > 0
        for bs_team in bs_teams
        for pdata in bs_team.get('players', [])
    )
    if any_ordered:
        game.has_lineup = True

    # --- Game completion status ---
    # Only trust GWT's statuscode during real stat saves.
    # On page reload GWT resets to statuscode=-2 (or 0 for finished games) before
    # the user has done anything — accepting that blindly would finalize or un-finalize
    # games incorrectly.
    if real_stat_save:
        game.is_complete = (statuscode == 0)

    # Mark Final when pitching decisions (W/L) and total time have been entered
    ei = bs.get('eventInfo') or {}
    win_uni = _int(ei.get('pitcherRecordWinUni', -1))
    loss_uni = _int(ei.get('pitcherRecordLossUni', -1))
    duration = (ei.get('duration') or '').strip()
    if win_uni != -1 and loss_uni != -1 and duration:
        game.is_complete = True
        game.duration = duration

    _persist_setup_to_game(game, ei, bs_teams, _int)

    # --- Inning scores ---
    # Build the inning list then TRIM trailing 0-0 entries.
    # GWT always sends the full scheduled span (e.g. 7 entries) even for games
    # that haven't started yet, so using statsPerPeriod keys or raw array length
    # to determine "innings played" creates phantom innings and pushes GWT to
    # the last inning / marks the game Final on every reload.
    innings_to_save = []
    for i in range(max_periods):
        vs = _int(vis_periods[i].get('score'))  if i < len(vis_periods)  else 0
        hs = _int(home_periods[i].get('score')) if i < len(home_periods) else 0
        innings_to_save.append((i + 1, vs, hs))

    # Remove trailing scoreless innings (those haven't actually been played yet)
    while innings_to_save and innings_to_save[-1][1] == 0 and innings_to_save[-1][2] == 0:
        innings_to_save.pop()

    if innings_to_save:
        InningScore.query.filter_by(game_id=game.id).delete()
        for inning_num, v_score, h_score in innings_to_save:
            db.session.add(InningScore(game_id=game.id, inning=inning_num,
                                       visitor_score=str(v_score),
                                       home_score=str(h_score)))
        game.visitor_runs = sum(v for _, v, _ in innings_to_save)
        game.home_runs    = sum(h for _, _, h in innings_to_save)
    # If innings_to_save is empty (game not started / no runs yet) leave the
    # existing DB innings untouched — a reload must never wipe real inning data.

    # --- Player stats ---
    for idx, bs_team in enumerate(bs_teams[:2]):
        is_home  = (idx == 1)
        team_obj = game.home_team if is_home else game.visitor_team
        if not team_obj:
            continue

        roster = {p.uniform_number: p for p in team_obj.players if p.uniform_number}

        if real_stat_save:
            # Preserve is_starter=True for any player already marked as a starter
            # before wiping stats.  GWT resets starter=False for the FLEX between
            # saves; this ensures their is_starter status survives a full stats rebuild.
            prev_starter_ids = {
                bs.player_id
                for bs in BattingStats.query.filter_by(
                    game_id=game.id, team_id=team_obj.id
                ).all()
                if bs.is_starter
            }
            # Full replace: delete old stats then reinsert from GWT payload
            BattingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).delete()
            PitchingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).delete()
            FieldingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).delete()
        else:
            prev_starter_ids = set()
            # Lineup-only sync (reload or pre-game setup): load existing records
            # so we can update lineup fields without touching stat columns.
            existing_batting = {
                bs.player_id: bs
                for bs in BattingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).all()
            }

        # Accumulate pitching/fielding per player — GWT can send same player multiple
        # times (e.g. starter + re-entry), causing duplicate PitchingStats and inflated IP.
        pit_accum = {}  # player_id -> {thirds, h, r, er, bb, so, bf, wp, bk, ...}
        fld_accum = {}  # player_id -> {po, a, e, pb, ci, sba, pos}

        for pdata in bs_team.get('players', []):
            participated = bool(pdata.get('participated'))
            on_field     = bool(pdata.get('onField'))
            starter      = bool(pdata.get('starter'))
            spot         = _int(pdata.get('spot') or pdata.get('readOrder') or 0)
            pos          = (pdata.get('pos') or pdata.get('defPosition') or '').strip()
            # GWT stores the defensive position as a numeric index (starterPosition /
            # playedPosition) but does not always populate the pos string field.
            # Derive the position string from the numeric field when pos is empty.
            if not pos:
                _pidx = int(pdata.get('playedPosition') or 0)
                if _pidx <= 0:
                    _pidx = int(pdata.get('starterPosition') or 0)
                pos = _GWT_POS_DESC.get(_pidx, '')

            # Skip players with no meaningful lineup or stat info
            if not participated and not on_field and not starter and not spot and not pos:
                continue

            uni    = str(pdata.get('uniform', '')).strip()
            player = roster.get(uni)
            if not player:
                player = Player.query.filter_by(
                    team_id=team_obj.id,
                    last_name=pdata.get('lastName', ''),
                    first_name=pdata.get('firstName', ''),
                ).first()
            if not player:
                continue

            if not real_stat_save:
                # Lineup sync: update existing batting record, or create a
                # lineup placeholder (spot > 0) without overwriting real stats.
                existing = existing_batting.get(player.id)
                if existing:
                    if spot:         existing.batting_order = spot
                    if pos:          existing.position      = pos
                    # Only GWT's starter=True promotes is_starter; onField alone
                    # means a sub/pinch-hitter came on and must NOT set is_starter.
                    if starter:
                        existing.is_starter = True
                elif spot > 0 or (pos and (starter or on_field)):
                    db.session.add(BattingStats(
                        game_id=game.id, player_id=player.id, team_id=team_obj.id,
                        batting_order=spot, position=pos,
                        is_starter=starter,
                        is_sub=on_field and not starter,
                        ab=0, r=0, h=0, rbi=0, doubles=0, triples=0, hr=0,
                        bb=0, so=0, sb=0, cs=0, hbp=0, sh=0, sf=0,
                        gdp=0, ibb=0, ground=0, fly=0, kl=0,
                    ))
                continue  # never touch pitching/fielding in lineup-sync mode

            # --- Full stat insert (real_stat_save path) ---
            # Preserve is_starter=True for any player previously flagged as a
            # starter. Safeguard against any edge-case where GWT sends starter=False
            # for the DH-fielder/FLEX (e.g. blobs saved under older server code).
            is_starter_final = starter or (player.id in prev_starter_ids)
            db.session.add(BattingStats(
                game_id=game.id, player_id=player.id, team_id=team_obj.id,
                batting_order=spot,
                position=pos,
                is_starter=is_starter_final,
                is_sub=participated and not is_starter_final,
                ab=_int(pdata.get('hittingAb')),
                r=_int(pdata.get('hittingR')),
                h=_int(pdata.get('hittingH')),
                rbi=_int(pdata.get('hittingRbi')),
                doubles=_int(pdata.get('hittingDouble')),
                triples=_int(pdata.get('hittingTriple')),
                hr=_int(pdata.get('hittingHr')),
                bb=_int(pdata.get('hittingBb')),
                so=_int(pdata.get('hittingSo')),
                sb=_int(pdata.get('hittingSb')),
                cs=_int(pdata.get('hittingCs')),
                hbp=_int(pdata.get('hittingHbp')),
                sh=_int(pdata.get('hittingSh')),
                sf=_int(pdata.get('hittingSf')),
                gdp=_int(pdata.get('hittingGdp')),
                ibb=_int(pdata.get('hittingIbb')),
                ground=_int(pdata.get('hittingGround')),
                fly=_int(pdata.get('hittingFly')),
                kl=_int(pdata.get('hittingKl')),
            ))

            if not participated:
                continue  # lineup-only player — no pitching/fielding stats

            # Accumulate pitching per player — GWT can send same player multiple times
            # (e.g. starter + re-entry), which would otherwise create duplicate records
            # and inflate IP when summed. Use thirds for IP (4.1 + 2.2 = 7.0, not 6.3).
            ip = _float(pdata.get('pitchingIp'))
            if ip or _int(pdata.get('pitchingSo')) or _int(pdata.get('pitchingH')) or _int(pdata.get('pitchingR')):
                ip_full, ip_frac = int(ip), round((ip - int(ip)) * 10)
                thirds = ip_full * 3 + ip_frac
                pid = player.id
                if pid not in pit_accum:
                    pit_accum[pid] = {
                        'thirds': 0, 'h': 0, 'r': 0, 'er': 0, 'bb': 0, 'so': 0, 'bf': 0,
                        'wp': 0, 'bk': 0, 'hbp': 0, 'fly': 0, 'hr': 0, 'kl': 0,
                        'ground': 0, 'ibb': 0, 'doubles': 0, 'triples': 0, 'pitches': 0,
                    }
                acc = pit_accum[pid]
                acc['thirds'] += thirds
                acc['h'] += _int(pdata.get('pitchingH'))
                acc['r'] += _int(pdata.get('pitchingR'))
                acc['er'] += _int(pdata.get('pitchingEr'))
                acc['bb'] += _int(pdata.get('pitchingBb'))
                acc['so'] += _int(pdata.get('pitchingSo'))
                acc['bf'] += _int(pdata.get('pitchingBf'))
                acc['wp'] += _int(pdata.get('pitchingWp'))
                acc['bk'] += _int(pdata.get('pitchingBk'))
                acc['hbp'] += _int(pdata.get('pitchingHbp'))
                acc['fly'] += _int(pdata.get('pitchingFly'))
                acc['hr'] += _int(pdata.get('pitchingHr'))
                acc['kl'] += _int(pdata.get('pitchingKl'))
                acc['ground'] += _int(pdata.get('pitchingGround'))
                acc['ibb'] += _int(pdata.get('pitchingIbb'))
                acc['doubles'] += _int(pdata.get('pitchingDouble'))
                acc['triples'] += _int(pdata.get('pitchingTriple'))
                acc['pitches'] += _int(pdata.get('pitchingPitches', 0))

            po = _int(pdata.get('fieldingPo'))
            a  = _int(pdata.get('fieldingA'))
            e  = _int(pdata.get('fieldingE'))
            if po or a or e:
                cur = fld_accum.get(player.id, {'po': 0, 'a': 0, 'e': 0, 'pb': 0, 'ci': 0, 'sba': 0, 'pos': pos})
                cur['po'] += po
                cur['a'] += a
                cur['e'] += e
                cur['pb'] += _int(pdata.get('fieldingPb'))
                cur['ci'] += _int(pdata.get('fieldingCi'))
                cur['sba'] += _int(pdata.get('fieldingSba'))
                cur['pos'] = pos or cur['pos']
                fld_accum[player.id] = cur

        for pid, acc in pit_accum.items():
            thirds = acc['thirds']
            ip_val = (thirds // 3) + (thirds % 3) / 10.0 if thirds % 3 else thirds // 3
            db.session.add(PitchingStats(
                game_id=game.id, player_id=pid, team_id=team_obj.id,
                ip=ip_val, h=acc['h'], r=acc['r'], er=acc['er'],
                bb=acc['bb'], so=acc['so'], bf=acc['bf'],
                wp=acc['wp'], bk=acc['bk'], hbp=acc['hbp'],
                fly=acc['fly'], hr=acc['hr'], kl=acc['kl'],
                ground=acc['ground'], ibb=acc['ibb'],
                doubles=acc['doubles'], triples=acc['triples'],
                pitches=acc['pitches'],
            ))
        for pid, acc in fld_accum.items():
            db.session.add(FieldingStats(
                game_id=game.id, player_id=pid, team_id=team_obj.id,
                position=acc['pos'], po=acc['po'], a=acc['a'], e=acc['e'],
                pb=acc['pb'], ci=acc['ci'], sba=acc['sba'],
            ))

    db.session.flush()

    # Recompute hits and errors from saved player stats
    for is_home, team_obj in [(False, game.visitor_team), (True, game.home_team)]:
        if not team_obj:
            continue
        bat = BattingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).all()
        fld = FieldingStats.query.filter_by(game_id=game.id, team_id=team_obj.id).all()
        if is_home:
            game.home_hits   = sum(b.h for b in bat)
            game.home_errors = sum(f.e for f in fld)
        else:
            game.visitor_hits   = sum(b.h for b in bat)
            game.visitor_errors = sum(f.e for f in fld)

    # Parse and persist plays (same as saveGame — reference stat entry saves XML data on both paths)
    _parse_and_persist_plays(game, bs, _int)

    _save_version(game)


@gwtapi_bp.route('/saveboxscore.json', methods=['POST'])
def save_boxscore():
    import json as json_mod
    _log('saveboxscore.json', request.form)

    event_id = request.form.get('id')
    try:
        eid = int(event_id)
    except (TypeError, ValueError):
        return jsonify({"ok": True})

    game = Game.query.get(eid)
    if not game:
        return jsonify({"ok": True})

    # --- Store raw GWT boxscore blob ---
    raw_bs = request.form.get('bs', '')
    if raw_bs:
        try:
            _bs = json_mod.loads(raw_bs)
            _sanitize_boxscore_batting_order(_bs)
            _sync_live_count_in_boxscore(_bs)
            game.gwt_bs_blob = json_mod.dumps(_bs)
        except (ValueError, TypeError):
            game.gwt_bs_blob = raw_bs

    try:
        es = json_mod.loads(request.form.get('es') or '{}')
    except (ValueError, TypeError):
        es = {}
    statuscode = int(es.get('statuscode', -2) or -2)
    try:
        statuscode = int(statuscode)
    except (TypeError, ValueError):
        statuscode = -2

    live_stats_raw = request.form.get('liveStats', '')

    try:
        bs = json_mod.loads(request.form.get('bs') or '{}')
    except (ValueError, TypeError):
        return jsonify({"ok": True})

    _persist_boxscore_full(game, bs, statuscode=statuscode, live_stats_raw=live_stats_raw)
    db.session.commit()
    return jsonify({"ok": True, "saved": True})


@gwtapi_bp.route('/processRawPlay.json', methods=['POST'])
def process_raw_play():
    """Full boxscore persist on every data sync/change (pitch, play, lineup, etc.)."""
    import json as _json
    _log('processRawPlay.json', request.form)

    event_id = request.form.get('id') or request.form.get('evt') or request.form.get('eventId')
    try:
        eid = int(event_id)
    except (TypeError, ValueError):
        return jsonify({"ok": True})

    game = Game.query.get(eid)
    if not game:
        return jsonify({"ok": True})

    raw_bs = request.form.get('bs') or request.form.get('boxscore', '') or request.form.get('raw_play', '')
    if not raw_bs:
        return jsonify({"ok": True})

    try:
        bs = _json.loads(raw_bs)
    except (ValueError, TypeError):
        return jsonify({"ok": True})

    # Store blob and run full saveboxscore persist (inning scores, stats, plays)
    _sanitize_boxscore_batting_order(bs)
    _sync_live_count_in_boxscore(bs)
    game.gwt_bs_blob = _json.dumps(bs)

    # statuscode=-2: don't change is_complete from GWT; live_stats_raw='': don't change entry_mode
    _persist_boxscore_full(game, bs, statuscode=-2, live_stats_raw='')

    db.session.commit()
    return jsonify({"ok": True})


@gwtapi_bp.route('/checkVersion.json', methods=['POST'])
def check_version():
    _log('checkVersion.json', request.form)
    return jsonify({"status": "OK", "version": "1.0"})


@gwtapi_bp.route('/event-status.json', methods=['POST'])
def event_status():
    return _stub('event-status.json')


@gwtapi_bp.route('/webRoster.json', methods=['POST'])
def web_roster():
    return _stub('webRoster.json')


@gwtapi_bp.route('/opponentrosters.json', methods=['POST'])
def opponent_rosters():
    # GWT expects an array — not a plain object
    _log('opponentrosters.json', request.form)
    return jsonify([])


@gwtapi_bp.route('/download.jspd', methods=['GET'])
def download_pdf():
    from flask import redirect
    event_id = request.args.get('evt', request.args.get('event_id', ''))
    if event_id and str(event_id).isdigit():
        # Redirect to XML URL — opens in browser (inline); user can right-click to save
        return redirect(f'/game/{event_id}/boxscore.xml')
    return redirect(f'/action/stats/downloadXML.jsp?evt={event_id}')


@gwtapi_bp.route('/downloadXML.jsp', methods=['GET'])
def download_xml():
    from flask import Response, redirect
    from app.models import Game
    from app.xmlapi import build_bsgame_xml
    evt = (request.args.get('evt') or request.args.get('event_id') or request.args.get('id', '')).strip()
    # Presto/GWT may use ?t= as cache buster; some links pass event as id. Accept t if it looks like game id (small int)
    if not evt and request.args.get('t'):
        tv = request.args.get('t', '')
        if str(tv).isdigit() and 0 < int(tv) < 10000000:
            evt = tv
    if evt and str(evt).isdigit():
        game = Game.query.get(int(evt))
        if game:
            xml_str = build_bsgame_xml(game)
            fname = f"boxscore_{(game.date or 'nodate').replace('-', '')}_{evt}"
            # inline = open in browser; user can right-click to save
            # no-cache so reload picks up GWT edits without reclicking
            return Response(
                xml_str,
                mimetype='application/xml',
                headers={
                    'Content-Disposition': f'inline; filename="{fname}.xml"',
                    'Cache-Control':      'no-cache, no-store, must-revalidate',
                    'Pragma':             'no-cache',
                    'Expires':            '0',
                }
            )
    _log('downloadXML.jsp', request.args)
    return jsonify({"ok": True, "message": "Event not found"})


# ── Reports tab / partner / misc stubs ────────────────────────────────────────

@gwtapi_bp.route('/getStatTeamPartners.json', methods=['GET', 'POST'])
def get_stat_team_partners():
    # Returns list of stat distribution partners — empty on self-hosted
    return jsonify([])


@gwtapi_bp.route('/statsPartnerAccountStatusByEvent.json', methods=['GET', 'POST'])
def stats_partner_account_status():
    return jsonify({})


@gwtapi_bp.route('/generalData.json', methods=['GET', 'POST'])
def general_data():
    return jsonify({})


@gwtapi_bp.route('/timezones.json', methods=['GET', 'POST'])
def timezones():
    return jsonify([
        "America/New_York", "America/Montreal", "America/Chicago",
        "America/Winnipeg", "America/Regina", "America/Denver",
        "America/Phoenix", "America/Edmonton", "America/Los_Angeles",
        "America/Vancouver", "America/Anchorage", "Pacific/Honolulu",
        "CET", "GMT", "Asia/Dubai", "America/St_Johns", "America/Halifax",
    ])


@gwtapi_bp.route('/networkEventHistory.json', methods=['GET', 'POST'])
def network_event_history():
    return jsonify([])


@gwtapi_bp.route('/localStorage.json', methods=['GET', 'POST'])
def local_storage():
    return jsonify({})


@gwtapi_bp.route('/removeGame.json', methods=['GET', 'POST'])
def remove_game():
    return _stub('removeGame.json')


@gwtapi_bp.route('/sendEmail.jsp', methods=['GET', 'POST'])
def send_email():
    return jsonify({"ok": True})


@gwtapi_bp.route('/sendGenEmail.json', methods=['GET', 'POST'])
def send_gen_email():
    return jsonify({"ok": True})


@gwtapi_bp.route('/sendStatsToNCAA.json', methods=['GET', 'POST'])
def send_stats_ncaa():
    return jsonify({"ok": True})


@gwtapi_bp.route('/sendStatsToNCAAFootball.json', methods=['GET', 'POST'])
def send_stats_ncaa_football():
    return jsonify({"ok": True})


@gwtapi_bp.route('/sendStatsToRecipient.jspd', methods=['GET', 'POST'])
def send_stats_recipient():
    return jsonify({"ok": True})


@gwtapi_bp.route('/errorData.json', methods=['GET', 'POST'])
def error_data():
    return jsonify({})


@gwtapi_bp.route('/mailDebug.json', methods=['GET', 'POST'])
def mail_debug():
    return jsonify({})


@gwtapi_bp.route('/debug.json', methods=['GET', 'POST'])
def debug_endpoint():
    _log('debug.json', request.form)
    # Also log any JSON body
    if request.is_json:
        try:
            import json as _j
            body = _j.dumps(request.get_json(), indent=2)
            _log('debug.json [body]', {'json': body[:4000]})
        except Exception:
            pass
    return jsonify({})
