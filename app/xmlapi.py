"""
XML export blueprint — generates PrestoSports bsgame XML for completed/in-progress games.

Route:  GET /game/<event_id>/boxscore.xml
        GET /game/<event_id>/boxscore.xml?download=1   (force file download)
"""

import json as json_mod
import hashlib
import re
from datetime import date as date_cls
from flask import Blueprint, Response, request
import xml.etree.ElementTree as ET

from app.models import Game, Play, InningScore, BattingStats, PitchingStats

xml_bp = Blueprint('xml', __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _venue_date(date_str):
    """YYYY-MM-DD → M/D/YYYY"""
    if not date_str:
        return ''
    try:
        parts = date_str.split('-')
        return f"{int(parts[1])}/{int(parts[2])}/{parts[0]}"
    except Exception:
        return date_str


def _short_name(player):
    """Return 'Last, F.' format short name, falling back to player.short_name."""
    if player.short_name:
        return player.short_name
    last = (player.last_name or '').strip()
    first = (player.first_name or '').strip()
    if last and first:
        return f"{last}, {first[0]}."
    # Fallback: split full name
    parts = (player.name or '').strip().split()
    if len(parts) >= 2:
        return f"{parts[-1]}, {parts[0][0]}."
    return player.name or ''


def _player_id(player):
    """Return stable unique playerId for PrestoSports XML. Uses external_id when set, else derives from player.id."""
    if player.external_id and str(player.external_id).strip():
        return str(player.external_id).strip()
    h = hashlib.sha256(f"player_{player.id}".encode()).hexdigest()
    return h[:17]


def _rev_name(player):
    """Return 'Last, First' format (revname) for XML schema."""
    last = (player.last_name or '').strip()
    first = (player.first_name or '').strip()
    if last and first:
        return f"{last}, {first}"
    parts = (player.name or '').strip().split()
    if len(parts) >= 2:
        return f"{parts[-1]}, {' '.join(parts[:-1])}"
    return player.name or ''


def _presto_name(player):
    """Return 'First Last' format for starters/batords (Presto format)."""
    first = (player.first_name or '').strip()
    last = (player.last_name or '').strip()
    if first and last:
        return f"{first} {last}"
    # Parse from "Last, First" or "Last First"
    n = (player.name or '').strip()
    if ', ' in n:
        parts = n.split(', ', 1)
        return f"{parts[1].strip()} {parts[0].strip()}" if len(parts) == 2 else n
    parts = n.split()
    if len(parts) >= 2:
        return f"{parts[0]} {' '.join(parts[1:])}"  # assume "First Last"
    return n


def _fmt_ip(ip_val):
    """Format innings-pitched float: 7.0 stays '7.0', 4.1 stays '4.1'."""
    if ip_val is None:
        return '0.0'
    return f"{float(ip_val):.1f}"


def _fmt_pct3(x):
    """Format 3-decimal percentage: Presto uses .000 not 0.000 for zero."""
    if x is None or (isinstance(x, (int, float)) and x == 0):
        return '.000'
    return f"{float(x):.3f}"


# Presto blob numeric position -> XML pos string (1-9 standard, 10/11 DH/FLEX)
_BLOB_POS_MAP = {
    1: 'p', 2: 'c', 3: '1b', 4: '2b', 5: '3b', 6: 'ss',
    7: 'lf', 8: 'cf', 9: 'rf', 10: 'dh', 11: 'dh', 0: 'dh',
}

def _presto_action(play):
    """
    Normalize play.action_type to Presto/Scoremaster format for XML export.
    Supports: K WP/PB/E#, E5T/E5F, 1B+8, HR+LC+RBI3, E3 A6, etc.
    Returns string suitable for <batter action="...">.
    """
    raw = (play.action_type or '').strip()
    if not raw:
        return ''
    upper = raw.upper()
    narr = (play.narrative or '').lower()
    rbi = play.rbi if play.rbi is not None else 0

    # K + reached: K WP, K PB, K E2 — pass through as-is (Presto uses spaces)
    if upper.startswith('K '):
        rest = upper[2:].strip()
        if rest == 'WP':
            return 'K WP'
        if rest == 'PB':
            return 'K PB'
        if rest.startswith('E') and len(rest) >= 2 and rest[1].isdigit():
            return 'K ' + rest

    # Error: E5 → E5T (throwing) or E5F (fielding) based on narrative
    # E3 A6 = muffed throw (fielding error by receiving fielder)
    if upper.startswith('E') and len(upper) >= 2 and upper[1].isdigit():
        if re.search(r'E\d[TF]\b', upper):
            return raw  # already has T or F (e.g. E5T, E6F)
        if ' E' in upper or ' A' in upper:
            return raw  # E3 A6 (assist notation) — pass through
        if 'fielding' in narr or 'fielding error' in narr or 'muffed' in narr:
            pos = upper[1] if len(upper) >= 2 else '5'
            return f'E{pos}F'
        if 'throwing' in narr or 'throwing error' in narr:
            pos = upper[1] if len(upper) >= 2 else '5'
            return f'E{pos}T'
        # E5 DF (dropped foul)
        if ' DF' in upper or 'DF' in upper:
            return raw
        # default: keep as-is (E5, E6) — Presto accepts both

    # Hits with position/location: 1B+8, 2B+9, 3B+RL+RBI3, HR+LC+RBI3
    # Position numbers: 1=p, 2=c, 3=1b, 4=2b, 5=3b, 6=ss, 7=lf, 8=cf, 9=rf
    # Location codes: LC/RC (left/right center), LL/RL (left/right line),
    #   LS/RS/MI (thru left/right side, middle), IP (inside park)
    _pos_num = {'P': '1', 'C': '2', '1B': '3', '2B': '4', '3B': '5', 'SS': '6',
                'LF': '7', 'CF': '8', 'RF': '9'}
    _loc_codes = ('LC', 'RC', 'RL', 'LL', 'LS', 'RS', 'MI', 'IP')
    parts = raw.split()
    if len(parts) >= 1:
        base = parts[0].upper()
        if base in ('1B', '2B', '3B', 'HR'):
            suffix = []
            has_rbi = False
            for p in parts[1:]:
                p_upper = p.upper()
                if p_upper.isdigit() and 1 <= int(p_upper) <= 9:
                    suffix.append(p_upper)
                elif p_upper in _pos_num:
                    suffix.append(_pos_num[p_upper])
                elif p_upper in _loc_codes:
                    suffix.append(p_upper)
                elif p_upper.startswith('RBI') and len(p_upper) > 3 and p_upper[3:].isdigit():
                    suffix.append(p_upper)
                    has_rbi = True
            if rbi and not has_rbi and base in ('3B', 'HR'):
                suffix.append(f'RBI{rbi}')
            if suffix:
                return base + ' ' + ' '.join(suffix)

    return raw


def _xml_team_id(team):
    """Return team ID for XML export. Prefers actual team_id/code over generic STATS1/STATS2."""
    if not team:
        return ''
    tid = (team.team_id or '').strip().upper()
    if tid in ('STATS1', 'STATS2'):
        return team.code or str(team.id)
    return team.team_id or team.code or str(team.id)


def _indent(elem, level=0):
    """In-place pretty-print indentation for ElementTree (Python < 3.9 compat)."""
    pad = '\n' + '  ' * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + '  '
        if not elem.tail or not elem.tail.strip():
            elem.tail = pad
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = pad
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = pad
    if not level:
        elem.tail = '\n'


# PrestoSports GWT pitch codes (first 2 digits of 4-digit codes like 0422/0222/0122)
# → letter codes: B=ball, F=foul, K=called/looking strike, S=swinging strike,
#   P=in play, I=intentional ball, H=hit by pitch
_GWT_PITCH_CODE = {
    '01': 'B',   # ball
    '02': 'K',   # strike looking / called strike
    '03': 'S',   # strike swinging
    '04': 'F',   # foul
    '05': 'P',   # in play
    '06': 'I',   # intentional ball
    '07': 'H',   # hit by pitch
    '08': 'K',   # called strike (same as looking)
}


def _pitch_count_from_sequence(raw):
    """Count total pitches in GWT pitch sequence (for np = number of pitches)."""
    if not raw or not str(raw).strip():
        return 0
    raw = str(raw).strip()
    if raw[0].isalpha():
        return len([c for c in raw.lower() if c in ('b', 'k', 's', 'p', 'f', 'x', 'h', 'i')])
    return len([p for p in raw.split('/') if p.strip() and len(p.strip()) >= 2])


def _live_count_from_blob(game, expected_inn=None, expected_half_ord=None):
    """
    Extract live pitch count (balls, strikes, np) from gwt_bs_blob when the in-progress
    at-bat isn't yet in the Play table. Presto stores live count in eventInfo during
    an at-bat (ballOnCurrentPlay, strikesOnCurrentPlay, pitchesNumberOnCurrentPlay).
    Also checks plays/rawPlays for the last incomplete play.

    expected_inn / expected_half_ord (0=top, 1=bottom): when provided, the blob data is
    only returned if the raw_plays last play belongs to that inning/half.  This prevents
    stale blob data from an old at-bat being used for a new half.
    Returns (b, s, np) or None if not found.
    """
    if not game.gwt_bs_blob:
        return None
    try:
        bs = json_mod.loads(game.gwt_bs_blob)
    except (json_mod.JSONDecodeError, TypeError):
        return None

    raw_plays = bs.get('plays') or bs.get('rawPlays') or {}
    # Find the last play across all innings (most recent = current at-bat)
    last_play = None
    last_key = (-1, -1, -1)  # (inning, half_ord, seq)
    if raw_plays:
        for inn_k, play_list in raw_plays.items():
            try:
                inn_num = int(inn_k)
            except (ValueError, TypeError):
                continue
            if not isinstance(play_list, list):
                continue
            for p in play_list:
                if p.get('playtype') in ('TURNOVR', 'SCOREADJ', 'INNINGS_ADVANCE'):
                    continue
                half_ord = 1 if p.get('homeTeam') else 0
                seq = int(p.get('sequence') or 0)
                key = (inn_num, half_ord, seq)
                if key > last_key:
                    last_key = key
                    last_play = p

    # When an expected half is given, verify the blob's last play is for that half.
    # If it isn't, the blob is stale (left over from a previous at-bat) — ignore it.
    if expected_inn is not None and expected_half_ord is not None:
        if last_play is None:
            return None
        blob_inn = last_key[0]
        blob_half_ord = last_key[1]
        if blob_inn != expected_inn or blob_half_ord != expected_half_ord:
            return None

    # eventInfo can be stale after inning changes. If raw plays exist, only trust a
    # real in-progress raw play for the live count. Fall back to eventInfo only when
    # there are no raw plays to inspect.
    if expected_inn is None and not last_play:
        ei = bs.get('eventInfo') or {}
        balls_ei = ei.get('ballOnCurrentPlay')
        strikes_ei = ei.get('strikesOnCurrentPlay')
        np_ei = ei.get('pitchesNumberOnCurrentPlay')
        if balls_ei is not None and strikes_ei is not None:
            try:
                b_int = int(balls_ei)
                s_int = int(strikes_ei)
                np_int = int(np_ei) if np_ei is not None and np_ei != '' else (b_int + s_int)
                return (b_int, s_int, np_int)
            except (TypeError, ValueError):
                pass

    if not last_play:
        return None
    props = last_play.get('props') or {}
    action = (props.get('RUNNER_ACTION0') or props.get('ACTION', '') or '').strip()
    if action:
        return None  # Completed at-bat; Play table should have it
    pitch_seq = (props.get('PITCHER_ACTIONS_0') or props.get('PITCHER_ACTIONS', '') or '').strip()
    balls_val = props.get('CURRENT_BALLS') or props.get('BALLS')
    strikes_val = props.get('CURRENT_STRIKES') or props.get('STRIKES')
    if balls_val is not None and balls_val != '' and strikes_val is not None and strikes_val != '':
        try:
            b_int = int(balls_val)
            s_int = int(strikes_val)
        except (TypeError, ValueError):
            b_int, s_int = _balls_strikes_from_pitch_sequence(pitch_seq)
    else:
        b_int, s_int = _balls_strikes_from_pitch_sequence(pitch_seq)
    np_val = _pitch_count_from_sequence(pitch_seq) if pitch_seq else 0
    return (b_int, s_int, np_val)


def _live_status_from_blob(game):
    """Return current live status fields from synced GWT blob, if available."""
    if not game.gwt_bs_blob:
        return None
    try:
        bs = json_mod.loads(game.gwt_bs_blob)
    except (json_mod.JSONDecodeError, TypeError):
        return None
    ei = bs.get('eventInfo') or {}
    try:
        inning = int(ei.get('statusPeriod'))
    except (TypeError, ValueError):
        return None

    is_home_off = ei.get('isHomeOffensive')
    if isinstance(is_home_off, str):
        is_home_off = is_home_off.strip().lower() in ('1', 'true', 'yes', 'y', 'on')
    else:
        is_home_off = bool(is_home_off)

    def _to_int(v, default=0):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    return {
        'inning': inning,
        'vh': 'H' if is_home_off else 'V',
        'outs': _to_int(ei.get('currentCountOuts'), 0),
        'b': _to_int(ei.get('ballOnCurrentPlay'), 0),
        's': _to_int(ei.get('strikesOnCurrentPlay'), 0),
        'np': _to_int(ei.get('pitchesNumberOnCurrentPlay'), 0),
    }


def _balls_strikes_from_pitch_sequence(raw):
    """Derive (balls, strikes) from GWT pitch sequence. Used for status and pitches b/s attributes."""
    if not raw or not str(raw).strip():
        return (0, 0)
    raw = str(raw).strip()
    b, s = 0, 0
    # Letter format: b=ball, k/s=strike (K=called/looking, S=swinging), f=foul, p/x=in play, h=HBP
    if raw[0].isalpha():
        letters = raw.lower()
        for i, c in enumerate(letters):
            if c in ('b', 'i'):
                b += 1
            elif c in ('k', 's'):
                s = min(s + 1, 2)
            elif c == 'p':
                if i == len(letters) - 1:
                    break  # in play (P) at end ends AB
                s = min(s + 1, 2)  # legacy: p as called strike in middle
            elif c == 'f':
                if s < 2:
                    s += 1
            elif c in ('x', 'h'):
                break  # in play (legacy x) / HBP ends AB
        return (b, s)
    # GWT numeric format: 4-digit codes, first 2 chars = type
    for part in raw.split('/'):
        part = part.strip()
        if len(part) < 2:
            continue
        pfx = part[:2]
        if pfx == '01' or pfx == '06':
            b += 1
        elif pfx in ('02', '03', '08'):
            s = min(s + 1, 2)
        elif pfx == '04':
            if s < 2:
                s += 1
        elif pfx in ('05', '07'):
            break
    return (b, s)


def _decode_pitch_sequence(raw):
    """Convert GWT numeric pitch sequence (0422/0222/0122/...) to PrestoSports letter format (BBSFKP)."""
    if not raw or not raw.strip():
        return ''
    raw = raw.strip()
    # Already letter format — normalize x→P for in play, output uppercase; H=HBP, I=intentional
    if raw and raw[0].isalpha():
        normalized = raw.replace('x', 'P').replace('X', 'P')
        return normalized.upper()
    # GWT format: 4-digit codes separated by /
    result = []
    for part in raw.split('/'):
        part = part.strip()
        if len(part) >= 2:
            prefix = part[:2]
            letter = _GWT_PITCH_CODE.get(prefix)
            if letter:
                result.append(letter)
    return ''.join(result)


# ── Team XML builder ──────────────────────────────────────────────────────────

def _build_team(parent, team, game, vh, is_initial=False, bs_team=None, ip_from_plays=None, all_plays=None):
    is_vis = (vh == 'V')
    # Build sub_order: player_id -> 1, 2, ... by order of SUB plays for this team
    sub_order_map = {}
    if all_plays and team:
        name_to_player = {p.name: p for p in team.players if p.name}
        name_to_player.update({_short_name(p): p for p in team.players})
        sub_num = 0
        for p in all_plays:
            if (p.action_type or '').upper() != 'SUB':
                continue
            half = (p.half or '').lower()
            team_batting = (half == 'top' and is_vis) or (half == 'bottom' and not is_vis)
            if not team_batting:
                continue
            who = (p.sub_who or '').strip()
            if not who:
                continue
            # Match who to player
            for name, pl in name_to_player.items():
                if name and (who == name or who in name or (name and name in who)):
                    if pl.id not in sub_order_map:
                        sub_num += 1
                        sub_order_map[pl.id] = sub_num
                    break
    runs   = (game.visitor_runs   if is_vis else game.home_runs)   or 0
    hits   = (game.visitor_hits   if is_vis else game.home_hits)   or 0
    errs   = (game.visitor_errors if is_vis else game.home_errors) or 0
    lob    = (game.visitor_lob    if is_vis else game.home_lob)    or 0
    record = (game.visitor_record if is_vis else game.home_record) or ''

    team_id_val = _xml_team_id(team)
    # Use school RPI as the PrestoSports team code if available
    code_val    = (team.school.rpi if team.school and team.school.rpi else None) or team.code or ''

    t_elem = ET.SubElement(parent, 'team')
    confrecord = (game.visitor_conf if is_vis else game.home_conf) or ''
    t_elem.set('vh',     vh)
    if confrecord:
        t_elem.set('confrecord', confrecord)
    t_elem.set('code',   code_val)
    t_elem.set('id',     team_id_val)
    t_elem.set('name',   team.name or '')
    t_elem.set('record', record)

    # ── Linescore ──────────────────────────────────────────────────────────
    if is_initial:
        # Initial/pre-edit state: single inning, all zeros (livescoring just selected)
        line_str = '0'
        num_inns = 1
        x_inn = None
    else:
        inn_map  = {i.inning: i for i in game.innings}
        max_inn  = max(inn_map.keys()) if inn_map else 0
        sched    = game.scheduled_innings or 7
        num_inns = max(max_inn, sched if not game.is_complete else max_inn if max_inn else sched)

        # "X" = home team did not bat in that inning (game ended after visitor's at-bat)
        last_inn = max(inn_map.keys()) if inn_map else 0
        prev_home = inn_map[last_inn - 1].home_score if (last_inn - 1) in inn_map else 0
        curr_home = inn_map[last_inn].home_score if last_inn in inn_map else 0
        home_did_not_bat = (
            game.is_complete
            and not is_vis
            and last_inn > 0
            and (game.home_runs or 0) > (game.visitor_runs or 0)
            and (curr_home or 0) == (prev_home or 0)
        )
        x_inn = last_inn if home_did_not_bat else None

        line_parts = []
        for n in range(1, num_inns + 1):
            if n in inn_map:
                score = inn_map[n].visitor_score if is_vis else inn_map[n].home_score
                val = score or 0
            else:
                val = 0
            if n == x_inn and not is_vis:
                line_parts.append('X')
            else:
                line_parts.append(str(val))
        line_str = ','.join(line_parts)

    ls = ET.SubElement(t_elem, 'linescore')
    ls.set('line', line_str)
    ls.set('runs', str(runs))
    ls.set('hits', str(hits))
    ls.set('errs', str(errs))
    ls.set('lob',  str(lob))

    inn_map = {i.inning: i for i in game.innings} if not is_initial else {}
    for n in range(1, num_inns + 1):
        li = ET.SubElement(ls, 'lineinn')
        li.text = ''  # Presto format: <lineinn ...></lineinn> not self-closing
        li.set('inn', str(n))
        if is_initial:
            li.set('score', '0')
        elif n == x_inn and not is_vis:
            li.set('score', 'X')
        elif n in inn_map:
            score = inn_map[n].visitor_score if is_vis else inn_map[n].home_score
            li.set('score', str(score or 0))
        else:
            li.set('score', '0')

    # Collect this team's stats for the game
    bat_stats = sorted(
        [s for s in game.batting_stats  if s.team_id == team.id],
        key=lambda s: (s.batting_order or 99, s.id)
    )
    pit_stats = [s for s in game.pitching_stats if s.team_id == team.id]
    ip_from_plays = ip_from_plays or {}
    fld_map   = {s.player_id: s for s in game.fielding_stats if s.team_id == team.id}
    # Multiple fsituation per player when they play multiple positions
    fld_list_by_player = {}
    for s in game.fielding_stats:
        if s.team_id != team.id:
            continue
        if s.player_id not in fld_list_by_player:
            fld_list_by_player[s.player_id] = []
        fld_list_by_player[s.player_id].append(s)
    hitter_splits, pitcher_splits = _build_situation_splits_from_plays(
        all_plays or [], game, team, is_vis, game.home_team, game.visitor_team
    ) if all_plays and game.home_team and game.visitor_team else ({}, {})

    # ── Starters (schema: spots 1–9 + 10 for DH/FLEX) ─────────────────────────
    starters_elem = ET.SubElement(t_elem, 'starters')
    batords_elem  = ET.SubElement(t_elem, 'batords')

    # Batords: prefer currentBattingOrder from GWT blob when available (reflects subs)
    cbo = bs_team.get('currentBattingOrder') if bs_team else None
    if cbo:
        players_by_uni = {}
        for pl in bs_team.get('players', []):
            u = pl.get('uniform')
            if u is not None:
                players_by_uni[str(u)] = pl
                players_by_uni[int(u)] = pl
        # Batords = current batting order (includes subs)
        for spot_idx, uni in enumerate(cbo[:10], 1):
            pl = players_by_uni.get(uni) or players_by_uni.get(str(uni))
            name = (pl.get('completeName') or '').strip() if pl else ''
            uni_str = str(uni) if uni is not None else ''
            pos_num = (pl.get('playedPosition') or pl.get('starterPosition') or pl.get('defPosition')) if pl else None
            pos = _BLOB_POS_MAP.get(pos_num, '') if pos_num is not None else ''
            bo = ET.SubElement(batords_elem, 'batord')
            bo.set('spot', str(spot_idx))
            bo.set('name', name)
            bo.set('uni', uni_str)
            bo.set('pos', pos)
        # Starters = original lineup (starter=True, ordered by initialSpot)
        blob_starters = sorted(
            [p for p in bs_team.get('players', []) if p.get('starter')],
            key=lambda p: (p.get('initialSpot') or 99, str(p.get('uniform') or ''))
        )
        for pl in blob_starters[:10]:
            spot = pl.get('initialSpot') or pl.get('spot')
            if spot is None:
                continue
            name = (pl.get('completeName') or '').strip()
            uni_str = str(pl.get('uniform') or '')
            pos_num = pl.get('starterPosition') or pl.get('playedPosition') or pl.get('defPosition')
            pos = _BLOB_POS_MAP.get(pos_num, '') if pos_num is not None else ''
            st = ET.SubElement(starters_elem, 'starter')
            st.set('spot', str(spot))
            st.set('name', name)
            st.set('uni', uni_str)
            st.set('pos', pos)
    else:
        # Fallback: derive from DB starters
        batters = [s for s in bat_stats if s.is_starter and (s.batting_order or 0) in range(1, 11)]
        for bs in batters:
            p = bs.player
            if not p:
                continue
            spot = str(bs.batting_order)
            pos = (bs.position or p.position or '').lower()
            st = ET.SubElement(starters_elem, 'starter')
            st.set('spot', spot)
            st.set('name', _presto_name(p) or '')
            st.set('uni',  p.uniform_number or '')
            st.set('pos',  pos)
            bo = ET.SubElement(batords_elem, 'batord')
            bo.set('spot', spot)
            bo.set('name', _presto_name(p) or '')
            bo.set('uni',  p.uniform_number or '')
            bo.set('pos',  pos)

    # ── Totals ─────────────────────────────────────────────────────────────
    totals = ET.SubElement(t_elem, 'totals')

    # Hitting totals
    ht = ET.SubElement(totals, 'hitting')
    _hitting_totals(ht, bat_stats, all_plays=all_plays)

    # Fielding totals
    ft = ET.SubElement(totals, 'fielding')
    fld_list = [s for s in game.fielding_stats if s.team_id == team.id]
    _fielding_totals(ft, fld_list)

    # Hitting situational summary — use aggregated stats where available
    hsi = ET.SubElement(totals, 'hsitsummary')
    h_fly = str(sum(getattr(b, 'fly', 0) or 0 for b in bat_stats))
    h_ground = str(sum(getattr(b, 'ground', 0) or 0 for b in bat_stats))
    h_lob = str(lob)  # game.visitor_lob or home_lob
    for k, v in [
        ('adv', '0'), ('fly', h_fly), ('ground', h_ground), ('lob', h_lob),
        ('rcherr', '0'), ('rchfc', '0'), ('vsleft', '0,0'), ('advops', '0,0'),
        ('leadoff', '0,0'), ('pinchhit', '0,0'), ('w2outs', '0,0'),
        ('wloaded', '0,0'), ('wrbiops', '0,0'), ('wrunners', '0,0'), ('rbi3rd', '0,0'),
    ]:
        hsi.set(k, v)

    # Pitching totals (use play-derived IP when available to fix inflated GWT accumulation)
    pt = ET.SubElement(totals, 'pitching')
    _pitching_totals(pt, pit_stats, ip_from_plays=ip_from_plays)

    # Pitching situational summary — use aggregated stats where available
    psi = ET.SubElement(totals, 'psitsummary')
    p_fly = str(sum(getattr(p, 'fly', 0) or 0 for p in pit_stats))
    p_ground = str(sum(getattr(p, 'ground', 0) or 0 for p in pit_stats))
    p_pitches = str(sum(getattr(p, 'pitches', 0) or 0 for p in pit_stats))
    p_strikes = str(sum(getattr(p, 'strikes', 0) or 0 for p in pit_stats))
    for k, v in [
        ('fly', p_fly), ('ground', p_ground), ('picked', '0'),
        ('leadoff', '0,0'), ('wrunners', '0,0'), ('vsleft', '0,0'), ('w2outs', '0,0'),
        ('pitches', p_pitches), ('strikes', p_strikes),
    ]:
        psi.set(k, v)

    # ── Roster players (exact PrestoSports schema) ───────────────────────────
    # Only count as "played" (gp=1) players who actually participated: starters,
    # subs, or pitchers. Lineup placeholders (BattingStats with is_starter=False,
    # is_sub=False) should get gp=0.
    def _actually_played(pid):
        bs = next((s for s in bat_stats if s.player_id == pid), None)
        ps = next((s for s in pit_stats if s.player_id == pid), None)
        return (bs and (bs.is_starter or bs.is_sub)) or bool(ps)

    played_player_ids = {p.id for p in team.players if _actually_played(p.id)}
    ps_map = {ps.player_id: ps for ps in pit_stats}

    # Game IDs for this team in same season (for hitseason/pchseason)
    game_ids = [g.id for g in Game.query.filter(
        (Game.visitor_team_id == team.id) | (Game.home_team_id == team.id)
    ).all()]

    def _roster_sort_key(p):
        """Players who played (gp=1) first by batting order; didn't play (gp=0) at bottom."""
        has_stats = p.id in played_player_ids
        bs = next((s for s in bat_stats if s.player_id == p.id), None)
        spot = (bs.batting_order or 99) if bs else 99
        uni = int(p.uniform_number) if (p.uniform_number or '').isdigit() else 999
        return (0 if has_stats else 1, spot if has_stats else uni, p.name or '')

    for player in sorted(team.players, key=_roster_sort_key):
        if player.disabled:
            continue
        has_stats = player.id in played_player_ids
        bs = next((s for s in bat_stats if s.player_id == player.id), None)
        ps = ps_map.get(player.id)
        # Only use batting_order if it's a valid spot (1-10); -1/0 = didn't bat. 10 = FLEX.
        spot = str(bs.batting_order) if bs and bs.batting_order and 1 <= bs.batting_order <= 10 else '0'
        pos = (((bs.position if bs else None) or player.position or '') if has_stats else '').lower()
        code = spot if has_stats and bs and bs.batting_order and 1 <= bs.batting_order <= 10 else ''
        is_pitcher = ps or (pos == 'p')
        # Compound pos for two-way players (e.g. p/rf when they pitch and also play RF)
        if has_stats and is_pitcher and pos and pos not in ('p', 'ph', 'pr') and '/' not in pos:
            pos = f"p/{pos}"
        elif has_stats and is_pitcher and not pos:
            pos = 'p'
        # atpos = actual batting position (Presto format): p, ph, dh, rf, cf, etc.
        if not has_stats:
            atpos = ''
        elif pos in ('ph', 'pr'):
            atpos = pos
        elif '/' in pos:
            parts = [p.strip().lower() for p in pos.split('/')]
            non_p = [p for p in parts if p and p != 'p']
            atpos = non_p[0] if non_p else (parts[0] if parts else '')
        else:
            atpos = pos if pos else ('p' if is_pitcher else '')

        # Attribute order matches PrestoSports exactly:
        # gp=1: name, shortname, revname, uni, gp, gs, spot, code, bats, throws, [class], pos, playerId, atpos
        # gp=0: name, shortname, revname, uni, gp, pos, spot, code, bats, throws, [class]
        p_elem = ET.SubElement(t_elem, 'player')
        p_elem.set('name',      player.name or '')
        p_elem.set('shortname', player.name or '')
        p_elem.set('revname',   _rev_name(player))
        p_elem.set('uni',       player.uniform_number or '')
        p_elem.set('gp',        '1' if has_stats else '0')
        if has_stats:
            p_elem.set('gs',    '1' if (bs and bs.is_starter) else '0')
            if bs and bs.is_sub:
                p_elem.set('sub', str(sub_order_map.get(player.id, 1)))
            p_elem.set('spot',  spot)
            p_elem.set('code',  code)
            p_elem.set('bats',  player.bats or 'R')
            p_elem.set('throws', player.throws or 'R')
            if player.player_class and str(player.player_class).strip():
                p_elem.set('class', str(player.player_class).strip())
            p_elem.set('pos',   pos)
            p_elem.set('playerId', _player_id(player))
            p_elem.set('atpos', atpos)
        else:
            p_elem.set('pos',   pos)
            p_elem.set('spot',  spot)
            p_elem.set('code',  code)
            p_elem.set('bats',  player.bats or 'R')
            p_elem.set('throws', player.throws or 'R')
            if player.player_class and str(player.player_class).strip():
                p_elem.set('class', str(player.player_class).strip())

        if has_stats:
            _player_hitting_schema(p_elem, bs)
            fld_agg = fld_list_by_player.get(player.id)
            if fld_agg:
                class _AggFld:
                    pass
                a = _AggFld()
                a.po = sum(getattr(f, 'po', 0) or 0 for f in fld_agg)
                a.a = sum(getattr(f, 'a', 0) or 0 for f in fld_agg)
                a.e = sum(getattr(f, 'e', 0) or 0 for f in fld_agg)
                a.pb = sum(getattr(f, 'pb', 0) or 0 for f in fld_agg)
                a.ci = sum(getattr(f, 'ci', 0) or 0 for f in fld_agg)
                a.sba = sum(getattr(f, 'sba', 0) or 0 for f in fld_agg)
                a.indp = sum(getattr(f, 'indp', 0) or 0 for f in fld_agg)
                a.intp = sum(getattr(f, 'intp', 0) or 0 for f in fld_agg)
                a.csb = sum(getattr(f, 'csb', 0) or 0 for f in fld_agg)
                _player_fielding_schema(p_elem, a)
            else:
                _player_fielding_schema(p_elem, fld_map.get(player.id))
            hsi_p = ET.SubElement(p_elem, 'hsitsummary')
            hsi_p.text = ''
            gnd = str(getattr(bs, 'ground', 0) or 0) if bs else '0'
            fly_val = str(getattr(bs, 'fly', 0) or 0) if bs else '0'
            for k, v in [
                ('ground', gnd), ('fly', fly_val),
                ('advops', '0,0'), ('leadoff', '0,0'), ('wrunners', '0,0'),
                ('w2outs', '0,0'), ('pinchhit', '0,0'), ('wrbiops', '0,0'),
                ('rbi3rd', '0,0'), ('wloaded', '0,0'), ('lob', '0'),
                ('adv', '0'), ('rcherr', '0'), ('rchfc', '0'), ('vsleft', '0,0'),
            ]:
                hsi_p.set(k, v)
            bat_agg = _agg_batting(player.id, game_ids)
            _add_hitseason(p_elem, bat_agg)
            if is_pitcher:
                if ps:
                    _player_pitching_schema(p_elem, ps, ip_override=ip_from_plays.get(ps.player_id))
                    pit_agg = _agg_pitching(player.id, game_ids)
                    _add_pchseason(p_elem, pit_agg)
                    psi = ET.SubElement(p_elem, 'psitsummary')
                    psi.set('fly',     str(ps.fly or 0))
                    psi.set('ground',  str(ps.ground or 0))
                    psi.set('picked',  '0')
                    psi.set('leadoff', '0,0')
                    psi.set('wrunners', '0,0')
                    psi.set('w2outs',  '0,0')
                    psi.set('vsleft',  '0,0')
                    psi.set('pitches', str(ps.pitches or 0))
                    psi.set('strikes', str(ps.strikes or 0))
                else:
                    # Pitcher starter with no PitchingStats yet — add default elements like reference
                    p = ET.SubElement(p_elem, 'pitching')
                    p.set('appear', '1')
                    p.set('ip',     '0.0')
                    p.set('gs',     '1')
                    p.set('ab',     '0')
                    p.set('bb',     '0')
                    p.set('bf',     '0')
                    p.set('er',     '0')
                    p.set('h',      '0')
                    p.set('r',      '0')
                    p.set('so',     '0')
                    p.set('whip',   '.00')
                    _add_pchseason(p_elem, {})  # empty agg → empty pchseason format
                    psi = ET.SubElement(p_elem, 'psitsummary')
                    psi.set('fly',     '0')
                    psi.set('ground',  '0')
                    psi.set('picked',  '0')
                    psi.set('leadoff', '0,0')
                    psi.set('wrunners', '0,0')
                    psi.set('w2outs',  '0,0')
                    psi.set('vsleft',  '0,0')
                    psi.set('pitches', '0')
                    psi.set('strikes', '0')

            # hsituation, fsituation, psituation — from play-by-play splits when available
            _add_situation_placeholders(
                p_elem, bs, fld_list_by_player.get(player.id, []), ps, spot, pos,
                hitter_splits.get(player.id), pitcher_splits.get(player.id)
            )


# ── Situation splits from play-by-play ─────────────────────────────────────────

def _build_situation_splits_from_plays(all_plays, game, team, is_vis, home, vis):
    """Build per-player situational splits from plays. Returns (hitter_splits, pitcher_splits)."""
    hitter_splits = {}   # player_id -> {context: {ab, r, h, rbi, so, ...}}
    pitcher_splits = {}  # player_id -> {context: {bb, ab, bf, ip, h, er, ...}}

    bat_team = vis if is_vis else home
    pit_team = home if is_vis else vis
    bat_stats = [s for s in game.batting_stats if s.team_id == bat_team.id]
    pit_stats = [s for s in game.pitching_stats if s.team_id == pit_team.id]

    def _name_matches(play_name, player):
        if not play_name or not player:
            return False
        pn = (play_name or '').strip()
        full = (player.name or '').strip()
        short = (_short_name(player) or '').strip()
        presto = (_presto_name(player) or '').strip()
        return pn in (full, short, presto) or (full and pn in full) or (short and pn in short)

    bat_name_to_player = {}
    for bs in bat_stats:
        if bs.player:
            for n in [bs.player.name, _short_name(bs.player), _presto_name(bs.player)]:
                if n:
                    bat_name_to_player[n.strip()] = (bs.player_id, bs.batting_order, bs.position or bs.player.position or '')

    pit_name_to_player = {}
    for ps in pit_stats:
        if ps.player:
            for n in [ps.player.name, _short_name(ps.player), _presto_name(ps.player)]:
                if n:
                    pit_name_to_player[n.strip()] = ps.player_id

    def _get_batter(play):
        bn = (play.batter_name or '').strip()
        for name, (pid, spot, pos) in bat_name_to_player.items():
            if name and (bn == name or bn in name or (name and name in bn)):
                return pid, str(spot or ''), (pos or '').lower()
        return None, '', ''

    def _get_pitcher(play):
        pn = (play.pitcher_name or '').strip()
        for name, pid in pit_name_to_player.items():
            if name and (pn == name or pn in name or (name and name in pn)):
                return pid
        return None

    def _classify_hitter_context(play):
        r1 = bool((play.runner_first or '').strip())
        r2 = bool((play.runner_second or '').strip())
        r3 = bool((play.runner_third or '').strip())
        outs = play.outs_before or 0
        ctxs = []
        if outs == 0:
            ctxs.append('leadoff')
        if not r1 and not r2 and not r3:
            ctxs.append('empty')
        if r1 or r2 or r3:
            ctxs.append('runners')
        if (r1 and r2) or (r1 and r3) or (r2 and r3):
            ctxs.append('runners2')
        if r1 and r2 and r3:
            ctxs.append('loaded')
        if r2 or r3:
            ctxs.append('scorepos')
        if r2 and r3:
            ctxs.append('scorepos2')
        return ctxs

    def _classify_pitcher_context(play):
        ctxs = _classify_hitter_context(play)
        ctxs.append(('byinn', str(play.inning or 1)))
        return ctxs

    def _parse_hitter_outcome(play):
        raw = (play.action_type or '').upper()
        base = raw.split()[0] if raw else ''
        parts = raw.split() if raw else []
        is_df = bool(base.startswith('E') and 'DF' in parts)
        is_sac = bool('SAC' in parts or base == 'SAC')
        is_sf = bool('SF' in parts or base == 'SF')
        is_ab = not is_df and not is_sac and not is_sf and (
            base in ('K', 'KS', 'KL') or base in ('1B', '2B', '3B', 'HR') or
            (len(base) == 1 and base.isdigit()) or (len(base) >= 2 and base[0] in 'FP' and base[-1].isdigit()) or
            base.startswith('E') or 'DP' in raw or 'TP' in raw or 'GDP' in raw or base == 'FC'
        )
        ab = 1 if is_ab else 0
        h = 1 if base in ('1B', '2B', '3B', 'HR') and 'DP' not in raw and 'TP' not in raw else 0
        rbi = play.rbi or 0
        so = 1 if base in ('K', 'KS', 'KL') else 0
        kl = 1 if base == 'KL' else 0
        gdp = 1 if 'GDP' in raw or ('DP' in raw and base in ('1B', '2B', '3B', 'HR')) else 0
        ground = 1 if 'GO' in raw or (base and base[0] == 'G') or 'ground' in (play.narrative or '').lower() else 0
        fly = 1 if base and base[0] in ('F', 'P', 'L') and len(base) >= 2 and base[-1].isdigit() else 0
        bb = 1 if base in ('BB', 'IBB') else 0
        hbp = 1 if base in ('HBP', 'HP') else 0
        sb = 1 if 'stole' in (play.narrative or '').lower() and not raw else 0
        cs = 1 if 'caught stealing' in (play.narrative or '').lower() and not raw else 0
        out = 1 if (base in ('K', 'KS', 'KL') or (len(base) >= 1 and base[0].isdigit()) or
                    (len(base) >= 2 and base[0] in 'FP' and base[-1].isdigit()) or 'DP' in raw or 'TP' in raw) else 0
        dp = 1 if 'DP' in raw or 'TP' in raw else 0
        return dict(ab=ab, r=0, h=h, rbi=rbi, so=so, kl=kl, gdp=gdp, ground=ground, fly=fly, bb=bb, hbp=hbp, sb=sb, cs=cs, out=out, dp=dp)

    def _parse_pitcher_outcome(play):
        raw = (play.action_type or '').upper()
        base = raw.split()[0] if raw else ''
        parts = raw.split() if raw else []
        is_df = bool(base.startswith('E') and 'DF' in parts)
        is_sac = bool('SAC' in parts or base == 'SAC')
        is_sf = bool('SF' in parts or base == 'SF')
        is_ab = not is_df and not is_sac and not is_sf
        ab = 1 if is_ab and (base in ('1B', '2B', '3B', 'HR') or base in ('K', 'KS', 'KL') or
                            (len(base) >= 1 and base[0].isdigit()) or (len(base) >= 2 and base[0] in 'FP')) else 0
        bb = 1 if base in ('BB', 'IBB') else 0
        h = 1 if base in ('1B', '2B', '3B', 'HR') and 'DP' not in raw and 'TP' not in raw else 0
        er = play.runs_scored or 0
        so = 1 if base in ('K', 'KS', 'KL') else 0
        fly = 1 if base and base[0] in ('F', 'P', 'L') and len(base) >= 2 and base[-1].isdigit() else 0
        ground = 1 if 'GO' in raw or (base and base[0] == 'G') or 'ground' in (play.narrative or '').lower() else 0
        ip = (play.outs_on_play or 1) / 3.0 if play.outs_on_play else (1/3 if ab or bb else 0)
        hr = 1 if base == 'HR' else 0
        double = 1 if base == '2B' else 0
        triple = 1 if base == '3B' else 0
        return dict(bb=bb, ab=ab, bf=1, ip=ip, h=h, er=er, so=so, fly=fly, ground=ground, hr=hr, double=double, triple=triple)

    for play in all_plays:
        if (play.action_type or '').upper() == 'SUB':
            continue
        half = (play.half or '').lower()
        bat_this_half = (half == 'top' and is_vis) or (half == 'bottom' and not is_vis)
        if not bat_this_half:
            continue
        if not play.batter_name and not play.pitcher_name:
            continue

        bid, bspot, bpos = _get_batter(play)
        pid = _get_pitcher(play)
        pit_name = (play.pitcher_name or '').strip()

        if bid:
            ctxs = _classify_hitter_context(play)
            outcome = _parse_hitter_outcome(play)
            # Add byspot, bypos, vspitcher (Presto contexts)
            if bspot:
                ctxs.append('byspot')
            if bpos:
                ctxs.append('bypos')
            if pit_name:
                ctxs.append('vspitcher')
            for ctx in ctxs:
                key = ctx if isinstance(ctx, str) else ctx[0]
                extra = {'spot': bspot} if key == 'byspot' and bspot else {}
                extra.update({'pos': bpos} if key == 'bypos' and bpos else {})
                if key == 'byinn':
                    extra['inn'] = ctx[1]
                if pit_name and key == 'vspitcher':
                    extra['pitcher'] = pit_name
                skey = (key, tuple(sorted(extra.items())))
                if bid not in hitter_splits:
                    hitter_splits[bid] = {}
                if skey not in hitter_splits[bid]:
                    hitter_splits[bid][skey] = dict(ab=0, r=0, h=0, rbi=0, so=0, kl=0, gdp=0, ground=0, fly=0, bb=0, hbp=0, sb=0, cs=0, out=0, dp=0, **_dict(extra))
                for k, v in outcome.items():
                    hitter_splits[bid][skey][k] = hitter_splits[bid][skey].get(k, 0) + v

        if pid:
            ctxs = _classify_pitcher_context(play)
            outcome = _parse_pitcher_outcome(play)
            for ctx in ctxs:
                key = ctx if isinstance(ctx, str) else ctx[0]
                extra = {'inn': ctx[1]} if key == 'byinn' else {}
                skey = (key, tuple(sorted(extra.items())))
                if pid not in pitcher_splits:
                    pitcher_splits[pid] = {}
                if skey not in pitcher_splits[pid]:
                    pitcher_splits[pid][skey] = dict(bb=0, ab=0, bf=0, ip=0.0, h=0, er=0, so=0, fly=0, ground=0, hr=0, double=0, triple=0, **_dict(extra))
                for k, v in outcome.items():
                    if k in pitcher_splits[pid][skey]:
                        if k == 'ip':
                            pitcher_splits[pid][skey][k] += v
                        else:
                            pitcher_splits[pid][skey][k] += v

    # Convert to list of (context, extra_attrs, stats) per player for emission
    def _to_emit_list(d):
        out = {}
        for pid, ctxs in d.items():
            items = []
            for (ctx, extra_tup), vals in ctxs.items():
                extra = dict(extra_tup) if extra_tup else {}
                stats = {k: v for k, v in vals.items() if k not in ('spot', 'pos', 'pitcher', 'inn')}
                items.append((ctx, extra, stats))
            out[pid] = items
        return out
    hitter_splits = _to_emit_list(hitter_splits)
    pitcher_splits = _to_emit_list(pitcher_splits)

    return hitter_splits, pitcher_splits


def _dict(extra):
    return dict(extra) if isinstance(extra, dict) else dict(extra) if isinstance(extra, (list, tuple)) else {}


# ── Stat fill helpers ─────────────────────────────────────────────────────────

def _add_situation_placeholders(p_elem, bs, fld_list, ps, spot, pos, hitter_splits=None, pitcher_splits=None):
    """Add hsituation, fsituation, psituation from play-by-play splits (Presto format)."""
    hitter_splits = hitter_splits or {}
    pitcher_splits = pitcher_splits or {}
    def v(attr, default=0): return str(getattr(bs, attr, default) or default) if bs else str(default)
    def pv(attr): return str(getattr(ps, attr, 0) or 0) if ps else '0'

    # hsituation: from play splits when available, else minimal placeholders
    if bs and (int(v('ab')) > 0 or int(v('bb')) > 0 or int(v('hbp')) > 0):
        h_items = hitter_splits if isinstance(hitter_splits, list) else []
        if not h_items:
            pos_attr = (pos.split('/')[-1] if pos and '/' in pos else pos) or ''
            base_vals = dict(ab=v('ab'), r=v('r'), h=v('h'), rbi=v('rbi'), so=v('so'), out='0', kl=v('kl'), gdp=v('gdp'), ground=v('ground'), fly=v('fly'), bb=v('bb'), hbp=v('hbp'))
            base_vals = {k: v for k, v in base_vals.items() if v is not None}
            h_items = [
                ('leadoff', {}, base_vals),
                ('empty', {}, base_vals),
                ('runners', {}, base_vals),
                ('scorepos', {}, base_vals),
            ]
            if spot and spot != '0':
                h_items.append(('byspot', {'spot': spot}, base_vals))
            if pos_attr:
                h_items.append(('bypos', {'pos': pos_attr}, base_vals))
            h_items.append(('vsright', {}, base_vals))
        for ctx, extra, vals in h_items:
            if ctx == 'byspot' and (not extra.get('spot') or extra.get('spot') == '0'):
                continue
            if ctx == 'bypos' and not extra.get('pos'):
                continue
            h = ET.SubElement(p_elem, 'hsituation')
            h.set('context', ctx)
            for k, ev in extra.items():
                if ev:
                    h.set(k, str(ev))
            for k in ['ab', 'r', 'h', 'rbi', 'so', 'kl', 'gdp', 'ground', 'fly', 'bb', 'hbp', 'sb', 'cs', 'out', 'dp']:
                if k in vals and vals[k] is not None:
                    h.set(k, str(vals[k]))

    # fsituation: one per position (Presto: multiple when player plays multiple positions)
    for fld in (fld_list or []):
        po_a, a_a, e_a = int(getattr(fld, 'po', 0) or 0), int(getattr(fld, 'a', 0) or 0), int(getattr(fld, 'e', 0) or 0)
        if not fld or (po_a == 0 and a_a == 0 and e_a == 0):
            continue
        fpos = (fld.position or pos or '').split('/')[0].lower() or 'unknown'
        fs = ET.SubElement(p_elem, 'fsituation')
        fs.set('context', 'bypos')
        fs.set('pos', fpos)
        for attr in ['a', 'e', 'po', 'indp', 'pb', 'csb', 'sba']:
            val = getattr(fld, attr, 0) or 0
            fs.set(attr, str(val))

    # psituation: from play splits when available
    if ps:
        p_items = pitcher_splits if isinstance(pitcher_splits, list) else []
        if not p_items:
            base_p = dict(bb=pv('bb'), ab=pv('ab'), bf=pv('bf'), ip=pv('ip'), h=pv('h'), er=pv('er'), so=pv('so'), fly=pv('fly'), ground=pv('ground'))
            p_items = [
                ('leadoff', {}, base_p),
                ('empty', {}, base_p),
                ('runners', {}, base_p),
                ('runners2', {}, base_p),
                ('scorepos', {}, base_p),
                ('scorepos2', {}, base_p),
            ]
        for ctx, extra, vals in p_items:
            p = ET.SubElement(p_elem, 'psituation')
            p.set('context', ctx)
            for k, ev in extra.items():
                if ev:
                    p.set(k, str(ev))
            for k in ['bb', 'ab', 'bf', 'ip', 'h', 'er', 'so', 'fly', 'ground', 'hr', 'double', 'triple']:
                if k in vals and vals[k] is not None:
                    p.set(k, str(vals[k]) if k != 'ip' else f'{vals[k]:.1f}' if isinstance(vals[k], (int, float)) else str(vals[k]))


def _fill_hitting(parent, bs):
    h = ET.SubElement(parent, 'hitting')
    def v(attr): return str(getattr(bs, attr, 0) or 0) if bs else '0'
    h.set('ab',     v('ab'))
    h.set('r',      v('r'))
    h.set('h',      v('h'))
    h.set('rbi',    v('rbi'))
    h.set('double', v('doubles'))
    h.set('triple', v('triples'))
    h.set('hr',     v('hr'))
    h.set('bb',     v('bb'))
    h.set('sb',     v('sb'))
    h.set('cs',     v('cs'))
    h.set('hbp',    v('hbp'))
    h.set('sh',     v('sh'))
    h.set('sf',     v('sf'))
    h.set('so',     v('so'))
    h.set('gdp',    v('gdp'))
    h.set('ibb',    v('ibb'))
    h.set('picked', '0')
    h.set('ground', v('ground'))
    h.set('fly',    v('fly'))
    h.set('kl',     v('kl'))
    h.set('hitdp',  v('gdp'))
    h.set('hittp',  v('hittp') if hasattr(bs, 'hittp') else '0')


def _fill_fielding(parent, fld):
    f = ET.SubElement(parent, 'fielding')
    def v(attr): return str(getattr(fld, attr, 0) or 0) if fld else '0'
    f.set('po', v('po'))
    f.set('a',  v('a'))
    f.set('e',  v('e'))
    f.set('pb', v('pb'))
    f.set('ci', v('ci'))


def _fill_pitching_stat(parent, ps):
    p = ET.SubElement(parent, 'pitching')
    def v(attr): return str(getattr(ps, attr, 0) or 0)
    p.set('ip',      _fmt_ip(ps.ip))
    p.set('ab',      v('ab'))
    p.set('bb',      v('bb'))
    p.set('bf',      v('bf'))
    p.set('bk',      v('bk'))
    p.set('double',  v('doubles'))
    p.set('er',      v('er'))
    p.set('fly',     v('fly'))
    p.set('ground',  v('ground'))
    p.set('h',       v('h'))
    p.set('hbp',     v('hbp'))
    p.set('hr',      v('hr'))
    p.set('ibb',     v('ibb'))
    p.set('kl',      v('kl'))
    p.set('r',       v('r'))
    p.set('so',      v('so'))
    p.set('triple',  v('triples'))
    p.set('wp',      v('wp'))
    p.set('picked',  '0')
    p.set('sha',     '0')
    p.set('sfa',     '0')
    p.set('gdp',     v('gdp') if hasattr(ps, 'gdp') else '0')
    p.set('pitches', v('pitches'))
    p.set('strikes', v('strikes'))
    p.set('gs',      v('gs'))
    p.set('cg',      v('cg'))
    p.set('sho',     v('sho'))
    p.set('win',     '1' if ps.win  else '0')
    p.set('loss',    '1' if ps.loss else '0')
    p.set('save',    '1' if ps.save else '0')


def _hitting_totals(elem, bat_stats, all_plays=None):
    def s(attr): return str(sum(getattr(b, attr, 0) or 0 for b in bat_stats))
    # hitdp = GDP count; hittp = triple play count (from plays if available)
    hitdp_val = s('gdp')
    hittp_val = '0'
    if all_plays:
        hittp_val = str(sum(1 for p in all_plays if (p.action_type or '').upper().startswith('TP') or 'TP' in (p.action_type or '')))
    elem.set('ab',     s('ab'))
    elem.set('r',      s('r'))
    elem.set('h',      s('h'))
    elem.set('rbi',    s('rbi'))
    elem.set('double', s('doubles'))
    elem.set('triple', s('triples'))
    elem.set('hr',     s('hr'))
    elem.set('bb',     s('bb'))
    elem.set('sb',     s('sb'))
    elem.set('cs',     s('cs'))
    elem.set('hbp',    s('hbp'))
    elem.set('sh',     s('sh'))
    elem.set('sf',     s('sf'))
    elem.set('so',     s('so'))
    elem.set('gdp',    s('gdp'))
    elem.set('ibb',    s('ibb'))
    elem.set('picked', '0')
    elem.set('ground', s('ground'))
    elem.set('fly',    s('fly'))
    elem.set('kl',     s('kl'))
    elem.set('hitdp',  hitdp_val)
    elem.set('hittp',  hittp_val)


def _fielding_totals(elem, fld_list):
    def s(attr): return str(sum(getattr(f, attr, 0) or 0 for f in fld_list))
    elem.set('po', s('po'))
    elem.set('a',  s('a'))
    elem.set('e',  s('e'))
    elem.set('pb', s('pb'))
    elem.set('ci', s('ci'))
    elem.set('indp', s('indp'))
    elem.set('intp', s('intp'))
    elem.set('csb', s('csb'))
    elem.set('sba', s('sba'))


def _pitching_totals(elem, pit_stats, ip_from_plays=None):
    ip_from_plays = ip_from_plays or {}
    def s(attr): return str(sum(getattr(p, attr, 0) or 0 for p in pit_stats))
    # Sum IP properly (each .1 = 1/3 inning); use play-derived IP when available
    total_thirds = 0
    for ps in pit_stats:
        ip = ip_from_plays.get(ps.player_id) if ps.player_id in ip_from_plays else (ps.ip or 0.0)
        full = int(ip)
        frac = round((ip - full) * 10)
        total_thirds += full * 3 + frac
    ip_full = total_thirds // 3
    ip_frac = total_thirds % 3
    ip_str  = f"{ip_full}.{ip_frac}"

    sho_val = '1' if not pit_stats else ('1' if all((p.sho or 0) for p in pit_stats) else '0')

    elem.set('ip',      ip_str)
    elem.set('ab',      s('ab'))
    elem.set('bb',      s('bb'))
    elem.set('bf',      s('bf'))
    elem.set('bk',      s('bk'))
    elem.set('double',  s('doubles'))
    elem.set('er',      s('er'))
    elem.set('fly',     s('fly'))
    elem.set('ground',  s('ground'))
    elem.set('h',       s('h'))
    elem.set('hbp',     s('hbp'))
    elem.set('hr',      s('hr'))
    elem.set('ibb',     s('ibb'))
    elem.set('kl',      s('kl'))
    elem.set('r',       s('r'))
    elem.set('so',      s('so'))
    elem.set('triple',  s('triples'))
    elem.set('wp',      s('wp'))
    elem.set('picked',  '0')
    elem.set('sha',     '0')
    elem.set('sfa',     '0')
    elem.set('gdp',     '0')
    elem.set('pitches', s('pitches'))
    elem.set('strikes', s('strikes'))
    elem.set('sho',     sho_val)


# ── Season aggregation ───────────────────────────────────────────────────────

def _agg_batting(player_id, game_ids):
    """Aggregate batting stats for player across games. Returns dict for hitseason."""
    if not game_ids:
        return {}
    stats = BattingStats.query.filter(
        BattingStats.player_id == player_id,
        BattingStats.game_id.in_(game_ids)
    ).all()
    if not stats:
        return {}
    agg = {}
    for attr in ('ab', 'r', 'h', 'rbi', 'bb', 'so', 'sb', 'cs', 'hbp', 'sh', 'sf', 'gdp', 'ibb',
                 'doubles', 'triples', 'hr', 'ground', 'fly', 'kl'):
        db_attr = 'doubles' if attr == 'doubles' else attr
        agg[attr] = sum(getattr(s, db_attr, 0) or 0 for s in stats)
    agg['tb'] = agg.get('h', 0) + agg.get('doubles', 0) + 2 * agg.get('triples', 0) + 3 * agg.get('hr', 0)
    agg['hittp'] = agg.get('hittp', 0)
    agg['hitdp'] = agg.get('hitdp', 0)
    agg['picked'] = agg.get('picked', 0)
    return agg


def _agg_pitching(player_id, game_ids):
    """Aggregate pitching stats for player across games. Returns dict for pchseason."""
    if not game_ids:
        return {}
    stats = PitchingStats.query.filter(
        PitchingStats.player_id == player_id,
        PitchingStats.game_id.in_(game_ids)
    ).all()
    if not stats:
        return {}
    agg = {}
    for attr in ('ab', 'bb', 'bf', 'bk', 'hr', 'h', 'r', 'er', 'ibb', 'so', 'wp', 'gs', 'cg', 'sho',
                 'doubles', 'triples', 'hbp', 'appear'):
        db_attr = 'doubles' if attr == 'doubles' else attr
        agg[attr] = sum(getattr(s, db_attr, 0) or 0 for s in stats)
    agg['win'] = sum(1 for s in stats if s.win)
    agg['loss'] = sum(1 for s in stats if s.loss)
    total_ip = sum(s.ip or 0 for s in stats)
    agg['ip'] = total_ip
    agg['sha'] = agg.get('sha', 0)
    agg['sfa'] = agg.get('sfa', 0)
    return agg


# ── Player-level schema (exact PrestoSports format) ───────────────────────────

def _player_hitting_schema(parent, bs):
    """Player hitting: r, h, ab, rbi, so, gdp, ground, kl, hitdp, slg, obp, ops (Presto order)."""
    h = ET.SubElement(parent, 'hitting')
    if bs:
        def v(a): return str(getattr(bs, a, 0) or 0)
        ab = int(v('ab'))
        r = int(v('r'))
        hits = int(v('h'))
        rbi = int(v('rbi'))
        so = v('so')
        gdp = v('gdp')
        ground = v('ground')
        kl = v('kl')
        hitdp = v('gdp')  # hit into double play = gdp
        slg = _fmt_pct3(bs.slg()) if ab > 0 else '.000'
        obp = _fmt_pct3(bs.obp()) if (ab + (bs.bb or 0) + (bs.hbp or 0) + (bs.sf or 0)) > 0 else '.000'
        ops = _fmt_pct3(bs.ops()) if ab > 0 else '.000'
    else:
        r, hits, ab, rbi, so, gdp, ground, kl, hitdp = '0', '0', '0', '0', '0', '0', '0', '0', '0'
        slg, obp, ops = '.000', '.000', '.000'
    h.set('r', str(r))
    h.set('h', str(hits))
    h.set('ab', str(ab))
    h.set('rbi', str(rbi))
    h.set('so', so)
    h.set('gdp', gdp)
    h.set('ground', ground)
    h.set('kl', kl)
    h.set('hitdp', hitdp)
    h.set('slg', slg if isinstance(slg, str) else f"{slg:.3f}")
    h.set('obp', obp if isinstance(obp, str) else f"{obp:.3f}")
    h.set('ops', ops if isinstance(ops, str) else f"{ops:.3f}")


def _player_fielding_schema(parent, fld):
    """Player fielding: po, a, e, pb, ci, sba, indp, intp, csb (Presto format)."""
    f = ET.SubElement(parent, 'fielding')
    def v(attr): return str(getattr(fld, attr, 0) or 0) if fld else '0'
    f.set('po', v('po'))
    f.set('a',  v('a'))
    f.set('e',  v('e'))
    f.set('pb', v('pb'))
    f.set('ci', v('ci'))
    f.set('sba', v('sba'))
    f.set('indp', v('indp'))
    f.set('intp', v('intp'))
    f.set('csb', v('csb'))


def _player_pitching_schema(parent, ps, ip_override=None):
    """Player pitching: appear, ip, gs, ab, bb, bf, er, h, r, so, whip (reference order)."""
    p = ET.SubElement(parent, 'pitching')
    def v(attr): return str(getattr(ps, attr, 0) or 0)
    ip_val = ip_override if ip_override is not None else ps.ip
    p.set('appear', v('appear') if hasattr(ps, 'appear') else '1')
    p.set('ip',     _fmt_ip(ip_val))
    p.set('gs',     v('gs'))
    p.set('ab',     v('ab'))
    p.set('bb',     v('bb'))
    p.set('bf',     v('bf'))
    p.set('er',     v('er'))
    p.set('h',      v('h'))
    p.set('r',      v('r'))
    p.set('so',     v('so'))
    p.set('whip',   f"{(ps.whip()):.2f}" if ip_val and ip_val > 0 else '.00')


def _add_hitseason(parent, agg):
    """Add hitseason element with aggregated season stats (attribute order matches reference)."""
    h = ET.SubElement(parent, 'hitseason')
    def v(a): return str(agg.get(a, 0) or 0)
    def pct(val, denom): return _fmt_pct3(val / denom) if denom > 0 else '.000'
    ab = int(v('ab'))
    if ab == 0:
        # Minimal format: ab, r, h, rbi, double, triple, hr, bb, so, ibb, hbp, kl, sb, cs, sh, sf, rchci, gdp, picked, hitdp, hittp, bavg, avg, slugpct, obpct
        for attr, val in [
            ('ab', v('ab')), ('r', v('r')), ('h', v('h')), ('rbi', v('rbi')),
            ('double', v('doubles')), ('triple', v('triples')), ('hr', v('hr')),
            ('bb', v('bb')), ('so', v('so')), ('ibb', v('ibb')), ('hbp', v('hbp')),
            ('kl', v('kl')), ('sb', v('sb')), ('cs', v('cs')), ('sh', v('sh')),
            ('sf', v('sf')), ('rchci', '0'), ('gdp', v('gdp')), ('picked', v('picked')),
            ('hitdp', v('hitdp')), ('hittp', v('hittp')), ('bavg', '.000'),
            ('avg', '.000'), ('slugpct', '0'), ('obpct', '0'),
        ]:
            h.set(attr, val)
    else:
        # Full format: bb, ab, kl, hittp, obpct, double, h, ibb, rchci, hr, sb, slugpct, cs, r, gdp, sf, triple, hitdp, sh, picked, hbp, rbi, so, bavg
        _h, _d, _t, _hr = int(v('h')), int(v('doubles')), int(v('triples')), int(v('hr'))
        _tb = _h + _d + 2 * _t + 3 * _hr
        denom_obp = ab + int(v('bb')) + int(v('hbp')) + int(v('sf'))
        for attr, val in [
            ('bb', v('bb')), ('ab', v('ab')), ('kl', v('kl')), ('hittp', v('hittp')),
            ('obpct', pct(int(v('h')) + int(v('bb')) + int(v('hbp')), denom_obp) if denom_obp > 0 else '.000'),
            ('double', v('doubles')), ('h', v('h')), ('ibb', v('ibb')), ('rchci', '0'),
            ('hr', v('hr')), ('sb', v('sb')), ('slugpct', pct(_tb, ab)),
            ('cs', v('cs')), ('r', v('r')), ('gdp', v('gdp')), ('sf', v('sf')),
            ('triple', v('triples')), ('hitdp', v('hitdp')), ('sh', v('sh')),
            ('picked', v('picked')), ('hbp', v('hbp')), ('rbi', v('rbi')), ('so', v('so')),
            ('bavg', pct(int(v('h')), ab)),
        ]:
            h.set(attr, val)


def _add_pchseason(parent, agg):
    """Add pchseason element with aggregated season stats (attribute order matches reference)."""
    p = ET.SubElement(parent, 'pchseason')
    def v(a): return str(agg.get(a, 0) or 0)
    def pct(val, denom): return _fmt_pct3(val / denom) if denom > 0 else '.000'
    ab = int(v('ab'))
    ip = float(v('ip') or 0)
    er = int(v('er'))
    if ab == 0 and ip == 0:
        # Empty format: gs, cg, sho, cbo, h, r, er, bb, k, so, double, triple, hr, ab, bf, wp, hbp, bk, sfa, sha, cia, kl, ibb, appear, bavg, avg
        for attr, val in [
            ('gs', v('gs')), ('cg', v('cg')), ('sho', v('sho')), ('cbo', '0'),
            ('h', v('h')), ('r', v('r')), ('er', v('er')), ('bb', v('bb')),
            ('k', v('so')), ('so', v('so')), ('double', v('doubles')), ('triple', v('triples')),
            ('hr', v('hr')), ('ab', v('ab')), ('bf', v('bf')), ('wp', v('wp')),
            ('hbp', v('hbp')), ('bk', v('bk')), ('sfa', v('sfa')), ('sha', v('sha')),
            ('cia', '0'), ('kl', v('kl')), ('ibb', v('ibb')), ('appear', v('appear')),
            ('bavg', '.000'), ('avg', '.000'),
        ]:
            p.set(attr, val)
    else:
        # Full format: bb, bf, bk, hr, era, wp, bavg, ab, kl, cg, double, ip, h, ibb, k, gs, er, sha, sfa, cbo, appear, r, triple, hbp, cia, sho
        era_val = f"{(er * 7 / (ip if ip > 0 else 1)):.2f}" if ip > 0 else '0.00'
        for attr, val in [
            ('bb', v('bb')), ('bf', v('bf')), ('bk', v('bk')), ('hr', v('hr')),
            ('era', era_val), ('wp', v('wp')), ('bavg', pct(int(v('h')), ab) if ab > 0 else '.000'),
            ('ab', v('ab')), ('kl', v('kl')), ('cg', v('cg')), ('double', v('doubles')),
            ('ip', f"{ip:.1f}"), ('h', v('h')), ('ibb', v('ibb')), ('k', v('so')),
            ('gs', v('gs')), ('er', v('er')), ('sha', v('sha')), ('sfa', v('sfa')),
            ('cbo', '0'), ('appear', v('appear')), ('r', v('r')),
            ('triple', v('triples')), ('hbp', v('hbp')), ('cia', '0'), ('sho', v('sho')),
        ]:
            p.set(attr, val)


# ── Main builder ──────────────────────────────────────────────────────────────

def build_bsgame_xml(game):
    """Return a UTF-8 XML string in PrestoSports bsgame format for the given game."""
    from datetime import date as date_cls
    d = date_cls.today()
    generated = f"{d.month:02d}/{d.day}/{d.year}"

    # Detect initial/pre-edit state: no plays recorded (livescoring just selected)
    play_count = Play.query.filter_by(game_id=game.id).count()
    is_initial = play_count == 0

    root = ET.Element('bsgame')
    root.set('source',    'PrestoSports')
    root.set('version',   '7.13.1')
    root.set('generated', generated)

    vis  = game.visitor_team
    home = game.home_team

    vis_id  = _xml_team_id(vis)  if vis  else ''
    home_id = _xml_team_id(home) if home else ''

    # ── Venue ────────────────────────────────────────────────────────────────
    venue = ET.SubElement(root, 'venue')
    venue.set('visid',    vis_id)
    venue.set('homeid',   home_id)
    venue.set('visname',  vis.name  if vis  else '')
    venue.set('homename', home.name if home else '')
    venue.set('date',     _venue_date(game.date))
    venue.set('location', game.location  or '')
    venue.set('stadium',  game.stadium   or '')
    venue.set('duration', game.duration  or '')
    venue.set('delay',    game.delayed_time or '')
    venue.set('attend',   str(game.attendance or 0))
    venue.set('leaguegame', 'Y' if game.is_league_game else 'N')
    _start = (game.start_time or '').strip()
    if _start and re.match(r'^0\d:', _start):
        _start = re.sub(r'^0(\d):', r'\1:', _start)
    venue.set('start', _start)
    venue.set('schedinn', str(game.scheduled_innings or 9))
    venue.set('weather',  game.weather or '')

    umps = ET.SubElement(venue, 'umpires')
    umps.text = ''  # Presto format: <umpires></umpires> not self-closing
    for attr, val in [('hp', game.ump_hp), ('first', game.ump_1b), ('second', game.ump_2b), ('third', game.ump_3b)]:
        if val:
            umps.set(attr, val)

    notes_elem = ET.SubElement(venue, 'notes')
    note = ET.SubElement(notes_elem, 'note')
    note.set('text', game.notes or '')
    note.text = ''

    rules = ET.SubElement(venue, 'rules')
    rules.text = ''
    rules.set('batters', '9,9')
    udh = (game.used_dh or 'N')
    rules.set('usedh', 'Y' if str(udh).upper() in ('Y', 'YES', '1', 'TRUE') else 'N')

    # ── Teams ────────────────────────────────────────────────────────────────
    bs_teams = []
    if game.gwt_bs_blob:
        try:
            boxscore = json_mod.loads(game.gwt_bs_blob)
            bs_teams = boxscore.get('teams', [])
        except (json_mod.JSONDecodeError, TypeError):
            pass
    all_plays = Play.query.filter_by(game_id=game.id).order_by(
        Play.inning, Play.half.desc(), Play.sequence
    ).all()
    # Derive IP from plays (1 out = 1/3 inning) per team — overrides inflated GWT accumulation
    def _ip_from_plays_for_team(team_id):
        out_map = {}
        for ps in (game.pitching_stats or []):
            if not ps.player or ps.team_id != team_id:
                continue
            short = _short_name(ps.player)
            full = ps.player.name or ''
            outs = 0
            for p in all_plays:
                if not p.outs_on_play:
                    continue
                # Home team pitches in top, visitor in bottom
                pitch_home = (p.half or '').lower() == 'top'
                if (team_id == home.id and not pitch_home) or (team_id == vis.id and pitch_home):
                    continue
                pname = (p.pitcher_name or '').strip()
                if pname in (short, full) or (short and short in pname) or (full and full in pname):
                    outs += p.outs_on_play
            if outs > 0:
                out_map[ps.player_id] = outs / 3.0
        return out_map
    if vis:
        _build_team(root, vis,  game, 'V', is_initial, bs_team=bs_teams[0] if len(bs_teams) > 0 else None, ip_from_plays=_ip_from_plays_for_team(vis.id) if vis else {}, all_plays=all_plays)
    if home:
        _build_team(root, home, game, 'H', is_initial, bs_team=bs_teams[1] if len(bs_teams) > 1 else None, ip_from_plays=_ip_from_plays_for_team(home.id) if home else {}, all_plays=all_plays)

    # ── Plays ────────────────────────────────────────────────────────────────
    plays_elem = ET.SubElement(root, 'plays')
    plays_elem.set('format', 'summary')

    if not all_plays and game.has_lineup:
        # Starters entered, no plays yet — add empty inning 1
        inn_el = ET.SubElement(plays_elem, 'inning')
        inn_el.set('number', '1')
    elif all_plays:
        from collections import defaultdict

        def _inning_runs_from_plays(plays):
            """Runs scored in half-inning from plays (live)."""
            return sum(p.runs_scored or 0 for p in plays)

        # Build name -> bats/throws for batprof/pchprof lookup (index by both full and short name)
        # Build short->full name map so we always output full name (player.name) not shortname
        bat_profs = {}
        pit_profs = {}
        name_to_full = {}
        for bs in game.batting_stats:
            if bs.player:
                v = (bs.player.bats or 'R').upper()[:1]
                full = bs.player.name or ''
                short = _short_name(bs.player)
                bat_profs[full] = bat_profs[short] = v
                name_to_full[short] = name_to_full[full] = full
        for ps in game.pitching_stats:
            if ps.player:
                v = (ps.player.throws or 'R').upper()[:1]
                full = ps.player.name or ''
                short = _short_name(ps.player)
                pit_profs[full] = pit_profs[short] = v
                name_to_full[short] = name_to_full[full] = full

        def _batprof(name):
            return bat_profs.get(name or '') or bat_profs.get((name or '').upper()) or 'R'
        def _pchprof(name):
            return pit_profs.get(name or '') or pit_profs.get((name or '').upper()) or 'R'
        def _fullname(name):
            return name_to_full.get(name or '') or name_to_full.get((name or '').strip()) or (name or '')

        _BASE_NAMES = {'0': 'first', '1': 'second', '2': 'third', '3': 'home'}

        def _narrative_full_names(text):
            """Replace short names (Last, F.) in narrative with full names."""
            if not text or not name_to_full:
                return text or ''
            out = text
            for short, full in sorted(name_to_full.items(), key=lambda x: -len(x[0])):
                if short and full and short != full and short in out:
                    out = out.replace(short, full)
            return out

        def _resolve_narrative_placeholders(text):
            """Resolve %b:N (base) placeholders: %b:0=first, %b:1=second, %b:2=third."""
            if not text:
                return text or ''
            out = text
            for num, name in _BASE_NAMES.items():
                out = out.replace(f'%b:{num}', name)
            return out

        def _normalize_narrative(text):
            """Format narrative: semicolons between clauses, period at end."""
            if not text or not isinstance(text, str):
                return text or ''
            t = text.strip()
            if not t:
                return t
            # Resolve %b:N placeholders
            t = _resolve_narrative_placeholders(t)
            # Insert "; " between ") " and following clause
            t = re.sub(r'\)\s+([A-Za-z])', r'); \1', t)
            # Insert "; " before runner clause (after "2b ", "3b ", "cf ", "second ", "third ")
            t = re.sub(r'(second|third|2b|3b|cf|1b)\s+([A-Z])', r'\1; \2', t)
            # "passed ball Name" / "wild pitch Name" -> semicolon before runner name
            t = re.sub(r'(passed ball|wild pitch)\s+([A-Z])', r'\1; \2', t)
            # "error by c Name" / "error by 2b Name" -> semicolon before runner name
            t = re.sub(r'(error by \w+)\s+([A-Z])', r'\1; \2', t)
            # "3 RBI Name" / "2 RBI Name" -> semicolon before scorer name
            t = re.sub(r'(\d+ RBI)\s+([A-Z])', r'\1; \2', t)
            # "unearned Name" -> semicolon before runner name
            t = re.sub(r'(unearned)\s+([A-Z])', r'\1; \2', t)
            # "Name scored Name" -> "Name scored; Name" (semicolon between multiple scorers)
            t = re.sub(r' scored (?=[A-Z])', r' scored; ', t)
            # Ensure period at end
            if t and not t.endswith('.'):
                t = t + '.'
            return t

        def _sub_narrative(play):
            who = _fullname(play.sub_who) or (play.sub_who or '').strip()
            sub_for = _fullname(play.sub_for) or (play.sub_for or '').strip()
            pos = (play.sub_pos or '').strip().lower() or 'sub'
            if not who:
                return _normalize_narrative(_narrative_full_names(play.narrative or ''))
            if sub_for and sub_for != who:
                if pos == 'ph':
                    return f"{who} pinch hit for {sub_for}."
                if pos == 'pr':
                    return f"{who} pinch ran for {sub_for}."
                return f"{who} to {pos} for {sub_for}."
            return f"{who} to {pos}."

        # Build inning -> {top: [plays], bottom: [plays]} (one inning elem per inn, two batting children)
        _DEF_POS = frozenset({'p', 'c', '1b', '2b', '3b', 'ss', 'lf', 'cf', 'rf'})
        plays_by_inn = defaultdict(lambda: {'top': [], 'bottom': []})
        for p in all_plays:
            half = (p.half or '').lower()
            key = half if half in ('top', 'bottom') else (half or 'top')
            plays_by_inn[p.inning][key].append(p)
        for plist in plays_by_inn.values():
            plist['top'].sort(key=lambda x: x.sequence)
            plist['bottom'].sort(key=lambda x: x.sequence)

        for inning_num in sorted(plays_by_inn.keys()):
            inn_data = plays_by_inn[inning_num]
            inn_elem = ET.SubElement(plays_elem, 'inning')
            inn_elem.set('number', str(inning_num))

            for half, vh, team_obj in [('top', 'V', vis), ('bottom', 'H', home)]:
                half_plays = inn_data[half]
                if not half_plays:
                    continue  # Don't show batting section if team hasn't batted this inning
                team_id_str = _xml_team_id(team_obj)

                batting_elem = ET.SubElement(inn_elem, 'batting')
                batting_elem.set('vh', vh)
                batting_elem.set('id', team_id_str)

                _OUT_ACTIONS = {'KS', 'KL', 'FO', 'GO', 'LO', 'SF', 'SAC', 'DP', 'GDP', 'E', 'BI'}
                _POS_ALIAS = {'c': 'c', '1b': '1b', '2b': '2b', '3b': '3b', 'ss': 'ss',
                              'lf': 'lf', 'cf': 'cf', 'rf': 'rf', 'p': 'p',
                              'center': 'cf', 'left': 'lf', 'right': 'rf', 'short': 'ss',
                              'first': '1b', 'second': '2b', 'third': '3b', 'home': 'home'}
                _POS_NUM = {'p': 1, 'c': 2, '1b': 3, '2b': 4, '3b': 5, 'ss': 6, 'lf': 7, 'cf': 8, 'rf': 9}

                prev_batter = prev_pitcher = None
                # V batting → H pitches; H batting → V pitches. Pitcher is from the team NOT batting.
                bat_team = team_obj
                def_team = home if bat_team.id == vis.id else vis
                _def_team_ps = next((s for s in game.pitching_stats if s.team_id == def_team.id and ((s.gs or 0) > 0 or (s.ip or 0) > 0)), None)
                _def_team_pitcher = (_def_team_ps.player.name if (_def_team_ps and _def_team_ps.player) else '') or ''
                def _pitcher_on_def_team(name):
                    if not name:
                        return None
                    for s in (game.pitching_stats or []):
                        if s.team_id != def_team.id or s.team_id == bat_team.id or not s.player:
                            continue
                        pn = (s.player.name or '').strip()
                        sn = _short_name(s.player) or ''
                        if pn and (name in pn or pn in name) or sn and (name in sn or sn in name):
                            return pn or sn
                    return None
                for idx, play in enumerate(half_plays):
                    is_sub = (play.action_type or '').upper() == 'SUB'
                    sub_pos = ((play.sub_pos or '').strip().lower() if is_sub else '')
                    is_def_sub = is_sub and sub_pos in _DEF_POS

                    if is_sub:
                        # Find the last non-SUB play before this sub
                        prev_play = None
                        for p in reversed(half_plays[:idx]):
                            if (p.action_type or '').upper() != 'SUB':
                                prev_play = p
                                break
                        # Did an out occur before this sub? Compare outs_before values.
                        out_was_made = (prev_play is not None and
                                        (play.outs_before or 0) > (prev_play.outs_before or 0))

                        near_batter = None
                        if out_was_made:
                            # Sub after an out: batter is the NEXT one in the lineup.
                            # Look forward for the next at-bat.
                            for p in half_plays[idx + 1:]:
                                if (p.action_type or '').upper() != 'SUB' and p.batter_name:
                                    near_batter = p.batter_name
                                    break
                            # Derive from batting order: find who comes after the batter who made the out
                            if not near_batter and prev_play and prev_play.batter_name:
                                out_batter = (prev_play.batter_name or '').strip()
                                orders = sorted([s.batting_order for s in game.batting_stats
                                                 if s.team_id == team_obj.id and s.batting_order
                                                 and 1 <= s.batting_order <= 10])
                                batter_spot = None
                                for s in game.batting_stats:
                                    if s.team_id != team_obj.id or not s.player or not s.batting_order:
                                        continue
                                    pn = (s.player.name or '').strip()
                                    sn = _short_name(s.player) or ''
                                    if out_batter in (pn, sn) or (sn and sn == out_batter):
                                        batter_spot = s.batting_order
                                        break
                                if batter_spot and orders:
                                    try:
                                        cur_i = orders.index(batter_spot)
                                        next_spot = orders[(cur_i + 1) % len(orders)]
                                    except ValueError:
                                        next_spot = orders[0]
                                    nbs = next((s for s in game.batting_stats
                                                if s.team_id == team_obj.id
                                                and s.batting_order == next_spot and s.player), None)
                                    if nbs and nbs.player:
                                        near_batter = nbs.player.name or _short_name(nbs.player)
                        else:
                            # Sub during/before at-bat: batter is the current at-bat batter.
                            # Look backward, then forward.
                            for p in reversed(half_plays[:idx]):
                                if (p.action_type or '').upper() != 'SUB' and p.batter_name:
                                    near_batter = p.batter_name
                                    break
                            if not near_batter:
                                for p in half_plays[idx + 1:]:
                                    if (p.action_type or '').upper() != 'SUB' and p.batter_name:
                                        near_batter = p.batter_name
                                        break
                        # Final fallback: leadoff batter
                        if not near_batter:
                            nbs = next((s for s in game.batting_stats
                                        if s.team_id == team_obj.id and s.batting_order == 1 and s.player), None)
                            if nbs and nbs.player:
                                near_batter = nbs.player.name or _short_name(nbs.player)
                        bat_name = near_batter or play.batter_name or prev_batter
                    else:
                        bat_name = play.batter_name or prev_batter
                    # Pitcher: V batting → H pitches; H batting → V pitches. sub_vh = who was batting: H→visitor pitches, V→home pitches
                    if is_def_sub:
                        sub_vh_u = (play.sub_vh or '').upper()
                        _pdef = home if sub_vh_u == 'V' else vis
                        ps = next((s for s in game.pitching_stats if s.team_id == _pdef.id and ((s.gs or 0) > 0 or (s.ip or 0) > 0)), None)
                        pch_name = (ps.player.name if (ps and ps.player) else '') or _def_team_pitcher
                    else:
                        cand = play.pitcher_name or (prev_pitcher if is_sub else None)
                        pch_name = _pitcher_on_def_team(cand) or _def_team_pitcher
                    play_elem = ET.SubElement(batting_elem, 'play')
                    play_elem.set('seq',     str(play.sequence))
                    play_elem.set('outs',    str(play.outs_before or 0))
                    play_elem.set('batter',  _fullname(bat_name) or '')
                    play_elem.set('batprof', _batprof(bat_name))
                    play_elem.set('pchprof', _pchprof(pch_name))
                    play_elem.set('pitcher', _fullname(pch_name) or '')

                    if play.runner_first:
                        play_elem.set('first', _fullname(play.runner_first))
                    if play.runner_second:
                        play_elem.set('second', _fullname(play.runner_second))
                    if play.runner_third:
                        play_elem.set('third', _fullname(play.runner_third))

                    action_raw = (play.action_type or '').upper()
                    narr_lower = (play.narrative or '').lower()
                    action_has_wp = 'WP' in action_raw or 'wild pitch' in narr_lower
                    action_has_pb = 'PB' in action_raw or 'passed ball' in narr_lower
                    _err_pos_match = re.search(r'E(\d)', action_raw)
                    action_has_error = bool(_err_pos_match)

                    # ── Substitution play ──────────────────────────────────────────
                    if action_raw == 'SUB':
                        sub_spot = play.sub_spot if (play.sub_spot and 1 <= play.sub_spot <= 10) else None
                        if not sub_spot and play.sub_for:
                            # Derive spot from sub_for (player being replaced) batting order
                            sub_for_norm = (play.sub_for or '').strip()
                            sub_for_full = _fullname(play.sub_for) or sub_for_norm
                            for bs in game.batting_stats:
                                if bs.team_id != team_obj.id or not bs.player or not (1 <= (bs.batting_order or 0) <= 10):
                                    continue
                                pname = (bs.player.name or '').strip()
                                pshort = _short_name(bs.player)
                                if sub_for_norm in (pname, pshort) or sub_for_full == pname or (pshort and pshort in (sub_for_norm, sub_for_full)):
                                    sub_spot = bs.batting_order
                                    break
                        sub_el = ET.SubElement(play_elem, 'sub')
                        sub_el.set('vh',   play.sub_vh   or vh)
                        sub_el.set('spot', str(sub_spot or 0))
                        sub_el.set('who',  _fullname(play.sub_who) or '')
                        sub_el.set('for',  _fullname(play.sub_for) or '')
                        sub_el.set('pos',  play.sub_pos  or '')

                        narr_el = ET.SubElement(play_elem, 'narrative')
                        narr_el.set('text', _sub_narrative(play))
                        continue   # skip normal batter/pitcher sub-elements

                    # ── Normal at-bat play ─────────────────────────────────────────
                    action_base = (action_raw or '').split()[0] if action_raw else ''
                    action_parts = action_raw.split() if action_raw else []
                    # Normalize "8-3" / "8–3" to "83" for throw-code parsing; FC 46 uses second part as throw code
                    action_for_throw = action_base
                    if action_base and len(action_base) == 3 and action_base[1] in '-–' and action_base[0].isdigit() and action_base[2].isdigit():
                        action_for_throw = action_base[0] + action_base[2]
                    if action_base == 'FC' and len(action_parts) >= 2 and action_parts[1].isdigit() and len(action_parts[1]) == 2:
                        action_for_throw = action_parts[1]
                    # Throw code (84, 43, 63, 83...) = batter ground out; always treat as throw out
                    is_throw_out = (len(action_for_throw) == 2 and action_for_throw.isdigit())
                    # Unassisted out: single digit 1-9, F/P/L+digit (F8, P3, L6, FF9 foul fly to rf), XUA (3UA, 6UA...), or FO/LO/PU
                    is_unassisted_code = (action_base and
                        ((len(action_base) == 1 and action_base.isdigit() and 1 <= int(action_base) <= 9)
                         or (len(action_base) >= 2 and action_base[0].upper() in ('F', 'P', 'L')
                             and action_base[-1].isdigit() and 1 <= int(action_base[-1]) <= 9)
                         or (len(action_base) == 3 and action_base[0].isdigit() and 1 <= int(action_base[0]) <= 9 and action_base[1:].upper() == 'UA')
                         or action_base in ('FO', 'LO', 'PU')))
                    # Special play type flags
                    is_df  = bool(action_base.startswith('E') and 'DF' in action_parts)  # E9 DF dropped foul
                    is_sac = bool('SAC' in action_parts or action_base == 'SAC')           # 14 SAC / SAC bunt
                    is_sf  = bool('SF' in action_parts or action_base == 'SF')             # F9 SF / SF
                    is_fc  = (action_base == 'FC')                                         # fielder's choice batter reaches
                    is_sb  = (not action_raw) and ('stole' in narr_lower)                  # stolen base runner play
                    is_cs  = (not action_raw) and ('caught stealing' in narr_lower)        # caught stealing runner play
                    is_dp_tp = bool(('DP' in action_raw or 'TP' in action_raw or 'GDP' in action_raw)
                                    and action_base and re.match(r'\d{2,3}', action_base))
                    is_strikeout = action_base in ('K', 'KS', 'KL') or action_raw in ('KS', 'KL')
                    is_k_cs_dp = is_strikeout and 'DP' in (action_raw or '') and 'caught stealing' in narr_lower
                    batter_out = 1 if (action_base in _OUT_ACTIONS or is_throw_out or is_unassisted_code or is_dp_tp or is_strikeout) else 0
                    is_unassisted_out = batter_out and is_unassisted_code
                    # Error: E5, E5T, E6 — batter reached; E9 DF = dropped foul, NOT a reached-base error
                    is_error = (not is_df and action_base and action_base[0].upper() == 'E'
                        and ((len(action_base) >= 2 and action_base[1].isdigit() and 1 <= int(action_base[1]) <= 9)
                             or (action_base.upper() == 'E' and play.narrative and re.search(r'error\s+by\s+\w+|(?:throwing|fielding)\s+error', (play.narrative or ''), re.I))))
                    is_ci      = (action_raw or '').upper() == 'CI' or (action_base or '').upper() == 'CI'
                    is_admin_play = bool(action_base and (str(action_base).startswith('R:') or str(action_base).startswith('B:')))
                    adv_map    = {'1B': 1, '2B': 2, '3B': 3, 'HR': 4, 'BB': 1, 'IBB': 1, 'HBP': 1, 'HP': 1, 'FC': 1, 'CI': 1}
                    batter_reached = is_error or action_has_wp or action_has_pb or action_has_error or is_ci
                    adv        = 0 if (batter_out or is_df) else (1 if batter_reached else adv_map.get(action_base, adv_map.get(action_raw, 0)))
                    # SAC/SF/DF/CI/R:/B: are not at-bats; walks and HBP are not at-bats
                    is_ab      = not is_df and not is_sac and not is_sf and not is_ci and not is_admin_play and (batter_out or action_raw not in ('BB', 'IBB', 'HBP', 'HP', 'CI'))
                    is_hit     = action_base in ('1B', '2B', '3B', 'HR') and not batter_out

                    # Runner-only "advanced on error": no batter involvement — no <batter> element
                    is_runner_only_advance_on_error = (
                        (not action_raw or not action_raw.strip()) and
                        'error' in narr_lower and 'advanced' in narr_lower and
                        (play.runner_first or play.runner_second or play.runner_third) and
                        not batter_out and adv == 0
                    )

                    # ── SB / CS: runner-only play — no <batter> element ─────────────
                    if is_sb or is_cs:
                        for run_base, run_name in ((1, play.runner_first), (2, play.runner_second), (3, play.runner_third)):
                            if not run_name:
                                continue
                            run_el = ET.SubElement(play_elem, 'runner')
                            if is_sb:
                                # "stole second, advanced to third on error by c" → SB E2, adv=2, tobase=3
                                sb_err = re.search(r'advanced\s+to\s+third\s+on\s+(?:an\s+)?error\s+by\s+(\w+)', narr_lower)
                                if sb_err:
                                    err_pos = _POS_ALIAS.get(sb_err.group(1).lower(), sb_err.group(1).lower())
                                    if err_pos in _POS_NUM:
                                        sb_action = f'SB E{_POS_NUM[err_pos]}'
                                        next_b, sb_adv = 3, '2'
                                    else:
                                        sb_action, next_b, sb_adv = 'SB', min(run_base + 1, 4), '1'
                                else:
                                    sb_action, next_b, sb_adv = 'SB', min(run_base + 1, 4), '1'
                                for k, v in [('base', str(run_base)), ('name', _fullname(run_name)),
                                             ('action', sb_action), ('out', '0'), ('adv', sb_adv),
                                             ('tobase', str(next_b)), ('sb', '1')]:
                                    run_el.set(k, v)
                            else:
                                cs_throw = ''
                                tm = re.search(r'\b(\w+)\s+to\s+(\w+)\b', narr_lower)
                                if tm:
                                    a_pos = _POS_ALIAS.get(tm.group(1), tm.group(1))
                                    p_pos = _POS_ALIAS.get(tm.group(2), tm.group(2))
                                    if a_pos in _POS_NUM and p_pos in _POS_NUM:
                                        cs_throw = f'{_POS_NUM[a_pos]}{_POS_NUM[p_pos]} '
                                for k, v in [('base', str(run_base)), ('name', _fullname(run_name)),
                                             ('action', f'{cs_throw}CS'), ('out', '1'), ('adv', '0'),
                                             ('tobase', str(run_base)), ('cs', '1')]:
                                    run_el.set(k, v)
                            break
                        pit_el = ET.SubElement(play_elem, 'pitcher')
                        pit_el.set('name', _fullname(pch_name) or '')
                        if is_sb:
                            pit_el.set('sba', '1')
                            def_team_sb = home if vh == 'V' else vis
                            sb_err_by_c = bool(re.search(r'advanced\s+to\s+third\s+on\s+(?:an\s+)?error\s+by\s+(?:c|catcher)\b', narr_lower))
                            for fpos in ('p', 'c'):
                                fld_el = ET.SubElement(play_elem, 'fielder')
                                fld_el.set('pos', fpos)
                                _fbs = next((s for s in game.batting_stats
                                             if s.team_id == def_team_sb.id
                                             and (s.position or '').lower().startswith(fpos)), None)
                                fld_el.set('name', _fbs.player.name if _fbs and _fbs.player else '')
                                fld_el.set('sba', '1')
                                if fpos == 'c' and sb_err_by_c:
                                    fld_el.set('e', '1')
                        else:
                            pit_el.set('bf', '1')
                            pit_el.set('ip', '1')
                            pit_el.set('ab', '1')
                            pit_el.set('csb', '1')
                            def_team_cs = home if vh == 'V' else vis
                            _NUM_TO_POS_CS = {1:'p', 2:'c', 3:'1b', 4:'2b', 5:'3b', 6:'ss', 7:'lf', 8:'cf', 9:'rf'}
                            pos_assist, pos_putout = 'c', None
                            tm = re.search(r'\b(\w+)\s+to\s+(\w+)\b', narr_lower)
                            if tm:
                                a_pos = _POS_ALIAS.get(tm.group(1), tm.group(1))
                                p_pos = _POS_ALIAS.get(tm.group(2), tm.group(2))
                                if a_pos in _POS_NUM and p_pos in _POS_NUM:
                                    a_num, p_num = int(_POS_NUM[a_pos]), int(_POS_NUM[p_pos])
                                    pos_assist = _NUM_TO_POS_CS.get(a_num, 'c')
                                    pos_putout = _NUM_TO_POS_CS.get(p_num)
                            _stat_sources = list(getattr(game, 'fielding_stats', []) or []) + list(game.batting_stats or [])
                            for fpos in ('p', pos_assist):
                                fld_el = ET.SubElement(play_elem, 'fielder')
                                fld_el.set('pos', fpos)
                                _fbs = next((s for s in _stat_sources
                                             if s.team_id == def_team_cs.id
                                             and (s.position or '').lower().startswith(fpos)), None)
                                fld_name = (_fbs.player.name if _fbs and _fbs.player else '') or (_fullname(pch_name) if fpos == 'p' else '')
                                fld_el.set('name', fld_name)
                                if fpos == 'p':
                                    fld_el.set('csb', '1')
                                else:
                                    fld_el.set('po', '0')
                                    fld_el.set('a', '1')
                                    fld_el.set('csb', '1')
                            if pos_putout and pos_putout != pos_assist:
                                fld_el = ET.SubElement(play_elem, 'fielder')
                                fld_el.set('pos', pos_putout)
                                _fbs = next((s for s in _stat_sources
                                             if s.team_id == def_team_cs.id
                                             and (s.position or '').lower().startswith(pos_putout)), None)
                                fld_el.set('name', _fbs.player.name if _fbs and _fbs.player else '')
                                fld_el.set('po', '1')
                        narr_el = ET.SubElement(play_elem, 'narrative')
                        narr_el.set('text', _resolve_narrative_placeholders(_narrative_full_names(play.narrative or '')))
                        continue  # skip standard batter/pitcher/fielder/narrative block

                    # Skip batter when unneeded (runner-only advance on error, or no meaningful batter stats)
                    # Dropped foul (E9 DF): batter stays at plate — Presto shows batter with action
                    # R:/B: admin plays (runner placed, batter set): show batter with action, no ab
                    batter_needed = batter_out or adv > 0 or is_ab or is_df or is_admin_play
                    if not is_runner_only_advance_on_error and batter_needed:
                        bat_el = ET.SubElement(play_elem, 'batter')
                        presto_action = _presto_action(play) or (play.action_type or '')
                        bat_attrs = [
                            ('name', _fullname(play.batter_name) or ''),
                            ('action', presto_action),
                            ('out', str(batter_out)),
                            ('adv', str(adv)),
                            ('tobase', str(adv)),
                        ]
                        if action_base == 'HR':
                            bat_attrs.append(('por', _fullname(pch_name) or ''))
                        if is_ab:
                            bat_attrs.append(('ab', '1'))
                        if action_raw in ('BB', 'IBB'):
                            bat_attrs.append(('bb', '1'))
                        if action_raw == 'IBB':
                            bat_attrs.append(('ibb', '1'))
                        if action_raw in ('HBP', 'HP'):
                            bat_attrs.append(('hbp', '1'))
                        if is_hit:
                            bat_attrs.append(('h', '1'))
                        if action_base == '2B':
                            bat_attrs.append(('double', '1'))
                        if action_base == '3B':
                            bat_attrs.append(('triple', '1'))
                        if action_base == 'HR':
                            bat_attrs.extend([('hr', '1'), ('scored', '1')])
                        if is_strikeout:
                            bat_attrs.append(('so', '1'))
                        if action_raw == 'KL' or action_base == 'KL':
                            bat_attrs.append(('kl', '1'))
                        if batter_out and (action_base == 'GO' or is_throw_out or is_dp_tp or (is_unassisted_out and 'ground' in narr_lower)):
                            bat_attrs.append(('gndout', '1'))
                        if is_sac:
                            bat_attrs.append(('sh', '1'))
                            bat_attrs.append(('gndout', '1'))
                        if is_sf:
                            bat_attrs.append(('sf', '1'))
                            bat_attrs.append(('ab', '1'))
                            bat_attrs.append(('flyout', '1'))
                        is_flyout = (batter_out and action_base and action_base[0].upper() in ('F', 'P')
                                     and len(action_base) >= 2 and action_base[-1].isdigit())
                        if is_flyout:
                            bat_attrs.append(('flyout', '1'))
                        if is_fc:
                            bat_attrs.append(('rchfc', '1'))
                            bat_attrs.append(('gndout', '1'))
                        rbi_val = play.rbi
                        if rbi_val is None or rbi_val == 0:
                            _rbi_m = re.search(r'RBI\s*(\d+)', action_raw, re.I)
                            if _rbi_m:
                                rbi_val = int(_rbi_m.group(1))
                        if rbi_val or action_base == 'HR':
                            bat_attrs.append(('rbi', str(rbi_val or 0)))
                        # K E2: batter reaches on dropped third strike; Presto does not put rcherr on batter
                        if (is_error or action_has_error) and not is_df and not (is_strikeout and 'E2' in (action_raw or '')):
                            bat_attrs.append(('rcherr', '1'))
                        for k, v in bat_attrs:
                            bat_el.set(k, v)

                    # <runner> sub-elements — attr order: base, name, action, out, adv, tobase, scored, ue
                    def _runner_attrs(base, name, action, out, adv, tobase, scored=None, ue=None):
                        a = [('base', str(base)), ('name', name), ('action', action), ('out', out), ('adv', adv), ('tobase', str(tobase))]
                        if scored:
                            a.append(('scored', '1'))
                        if ue:
                            a.append(('ue', '1'))
                        return a
                    if adv >= 1 and action_raw in ('BB', 'IBB', 'HBP', 'HP'):
                        if play.runner_first:
                            run_el = ET.SubElement(play_elem, 'runner')
                            for k, v in _runner_attrs(1, _fullname(play.runner_first), '+', '0', '1', '2'):
                                run_el.set(k, v)
                        if play.runner_second and play.runner_first:
                            run_el = ET.SubElement(play_elem, 'runner')
                            for k, v in _runner_attrs(2, _fullname(play.runner_second), '+', '0', '1', '3'):
                                run_el.set(k, v)
                        if play.runner_third and play.runner_first and play.runner_second:
                            run_el = ET.SubElement(play_elem, 'runner')
                            for k, v in _runner_attrs(3, _fullname(play.runner_third), '+', '0', '1', '4', scored=True):
                                run_el.set(k, v)
                    elif is_dp_tp and (play.runner_first or play.runner_second or play.runner_third):
                        # DP/TP: only runners who are actually out get action="X" out="1" (Presto format)
                        # DP: 1 runner out (forced at 2b); TP: 2 runners out
                        runners_out = max(0, (play.outs_on_play or 2) - 1)
                        runners_list = [(1, play.runner_first), (2, play.runner_second), (3, play.runner_third)]
                        for i, (base, run_name) in enumerate(runners_list):
                            if not run_name or i >= runners_out:
                                break
                            run_el = ET.SubElement(play_elem, 'runner')
                            for k, v in _runner_attrs(base, _fullname(run_name), 'X', '1', '0', str(base)):
                                run_el.set(k, v)
                    elif is_k_cs_dp and (play.runner_first or play.runner_second or play.runner_third):
                        # K + CS double play: batter K, runner caught stealing — runner gets "X CS" or "24 CS"
                        cs_throw = ''
                        for part in (action_parts or []):
                            if len(part) == 2 and part.isdigit():
                                cs_throw = part + ' '
                                break
                        if not cs_throw:
                            tm = re.search(r'\b(\w+)\s+to\s+(\w+)\b', narr_lower)
                            if tm:
                                a_pos = _POS_ALIAS.get(tm.group(1), tm.group(1))
                                p_pos = _POS_ALIAS.get(tm.group(2), tm.group(2))
                                if a_pos in _POS_NUM and p_pos in _POS_NUM:
                                    cs_throw = f'{_POS_NUM[a_pos]}{_POS_NUM[p_pos]} '
                        cs_action = 'X CS'  # Presto uses "X CS" for K+CS DP
                        cs_name = None
                        for m in re.finditer(r'([A-Za-z][A-Za-z\s\'-]+)\s+caught\s+stealing', narr_lower, re.I):
                            cs_name = m.group(1).strip()
                            break
                        for base, run_name in [(1, play.runner_first), (2, play.runner_second), (3, play.runner_third)]:
                            if not run_name:
                                continue
                            name_full = _fullname(run_name) or run_name
                            if cs_name and (cs_name.lower() in name_full.lower() or name_full.lower() in cs_name.lower() or
                                            any(cs_name.lower() in (p or '').lower() for p in re.split(r'[\s,]+', name_full))):
                                run_el = ET.SubElement(play_elem, 'runner')
                                tobase = base
                                if cs_throw and len(cs_throw.strip()) >= 2 and cs_throw.strip()[-1].isdigit():
                                    putout_pos = int(cs_throw.strip()[-1])
                                    tobase = {3: 1, 4: 2, 5: 3}.get(putout_pos, base)
                                for k, v in _runner_attrs(base, name_full, cs_action, '1', '0', str(tobase), ue=None):
                                    run_el.set(k, v)
                                run_el.set('cs', '1')
                                break
                        else:
                            run_base, run_name = next(((b, r) for b, r in [(1, play.runner_first), (2, play.runner_second), (3, play.runner_third)] if r), (1, play.runner_first))
                            if run_name:
                                run_el = ET.SubElement(play_elem, 'runner')
                                for k, v in _runner_attrs(run_base, _fullname(run_name), cs_action, '1', '0', str(run_base)):
                                    run_el.set(k, v)
                                run_el.set('cs', '1')
                    elif is_fc and play.runner_first:
                        # FC: runner on 1st gets out; derive throw code from action_type ("FC 46") or narrative
                        fc_throw = ''
                        if len(action_parts) >= 2 and action_parts[1].isdigit():
                            fc_throw = action_parts[1]
                        if not fc_throw:
                            tm = re.search(r'\b(\w+)\s+to\s+(\w+)\b', narr_lower)
                            if tm:
                                a_pos = _POS_ALIAS.get(tm.group(1), tm.group(1))
                                p_pos = _POS_ALIAS.get(tm.group(2), tm.group(2))
                                if a_pos in _POS_NUM and p_pos in _POS_NUM:
                                    fc_throw = f'{_POS_NUM[a_pos]}{_POS_NUM[p_pos]}'
                        run_el = ET.SubElement(play_elem, 'runner')
                        for k, v in _runner_attrs(1, _fullname(play.runner_first), fc_throw, '1', '0', '1'):
                            run_el.set(k, v)
                    elif is_sf:
                        # SF: runner from 3rd scores and/or runner from 2nd advances to third
                        if play.runner_third and (play.runs_scored or 'scored' in narr_lower or 'scoring' in narr_lower):
                            run_el = ET.SubElement(play_elem, 'runner')
                            for k, v in _runner_attrs(3, _fullname(play.runner_third), '+', '0', '1', '4', scored=True):
                                run_el.set(k, v)
                        if play.runner_second and ('advanced' in narr_lower or 'to third' in narr_lower or (play.runners_after or '000')[2:3] == '1'):
                            run_el = ET.SubElement(play_elem, 'runner')
                            for k, v in _runner_attrs(2, _fullname(play.runner_second), '+', '0', '1', '3'):
                                run_el.set(k, v)
                    elif is_sac and play.runner_first:
                        # SAC: runners advance — only emit when they actually advance (Presto omits non-advancers)
                        run_el = ET.SubElement(play_elem, 'runner')
                        for k, v in _runner_attrs(1, _fullname(play.runner_first), '+', '0', '1', '2'):
                            run_el.set(k, v)
                        if play.runner_second and ('advanced' in narr_lower or 'to third' in narr_lower or (play.runners_after or '000')[2:3] == '1'):
                            run_el = ET.SubElement(play_elem, 'runner')
                            for k, v in _runner_attrs(2, _fullname(play.runner_second), '+', '0', '1', '3'):
                                run_el.set(k, v)
                        if play.runner_third and (play.runs_scored or 'scored' in narr_lower or 'scoring' in narr_lower):
                            run_el = ET.SubElement(play_elem, 'runner')
                            for k, v in _runner_attrs(3, _fullname(play.runner_third), '+', '0', '1', '4', scored=True):
                                run_el.set(k, v)
                    elif (is_hit or is_throw_out or is_error or action_has_wp or action_has_pb or action_has_error or ('error' in narr_lower and 'advanced' in narr_lower)) and (play.runner_first or play.runner_second or play.runner_third or (play.narrative and ('advanced' in narr_lower or 'out at' in narr_lower or 'scored' in narr_lower or 'scoring' in narr_lower or play.outs_on_play))):
                        narr = _resolve_narrative_placeholders(_narrative_full_names(play.narrative or ''))
                        runners_to_check = [(play.runner_first, 1), (play.runner_second, 2), (play.runner_third, 3)]
                        if not any(r[0] for r in runners_to_check) and play.narrative:
                            runners_to_check = []
                            for out_m in re.finditer(r'([A-Za-z][A-Za-z\s\'-]+)\s+out\s+at\s+(\w+)', narr):
                                name, dest = out_m.group(1).strip(), out_m.group(2).lower()
                                start_base = {'second': 1, 'third': 2, 'home': 3}.get(dest, 1)
                                if not any(r[0] == name for r in runners_to_check):
                                    runners_to_check.append((name, start_base))
                            for adv_m in re.finditer(r'([A-Za-z][A-Za-z\s\'-]+)\s+advanced\s+to\s+(\w+)', narr):
                                name, dest = adv_m.group(1).strip(), adv_m.group(2).lower()
                                start_base = {'second': 1, 'third': 2, 'home': 3}.get(dest, 2)
                                if not any(r[0] == name for r in runners_to_check):
                                    runners_to_check.append((name, start_base))
                            # Match "Name scored" or "scoring Name" (user-typed narrative)
                            for scored_m in re.finditer(r'([A-Za-z][A-Za-z\s\'-]+)\s+scored', narr, re.I):
                                name = scored_m.group(1).strip()
                                if not any(r[0] == name for r in runners_to_check):
                                    runners_to_check.append((name, 3))  # from 3B (home)
                            for scoring_m in re.finditer(r'scoring\s+([A-Za-z][A-Za-z\s\',\-]+?)(?:\.|,|$|\band\b)', narr, re.I):
                                names_str = scoring_m.group(1).strip()
                                for name in re.split(r',\s*|\s+and\s+', names_str):
                                    name = name.strip()
                                    if name and not any(r[0] == name for r in runners_to_check):
                                        runners_to_check.append((name, 3))
                            runners_to_check.sort(key=lambda x: x[1])
                        for rf, base in runners_to_check:
                            if not rf:
                                continue
                            name_full = _fullname(rf) or rf
                            name_pat = re.escape(name_full) if name_full else ''
                            if not name_pat:
                                name_pat = re.escape(str(rf))
                            out_match = re.search(name_pat + r'\s+out\s+at\s+(\w+)', narr, re.I)
                            adv_match = re.search(name_pat + r'\s+advanced\s+to\s+(\w+)', narr, re.I)
                            scored_match = re.search(name_pat + r'\s+scored', narr, re.I) or re.search(
                                r'scoring[^.]*' + name_pat, narr, re.I)
                            if not scored_match and name_full:
                                # Try matching by first or last name (e.g. "Nico scored" vs "Smith, Nico")
                                for part in re.split(r'[\s,]+', name_full):
                                    if len(part) > 1:
                                        p_esc = re.escape(part)
                                        scored_match = scored_match or re.search(p_esc + r'\s+scored', narr, re.I) or re.search(
                                            r'scoring[^.]*' + p_esc, narr, re.I)
                                        if scored_match:
                                            break
                            tobase_map = {'first': 1, 'second': 2, 'third': 3, 'home': 4}
                            # Presto: only emit runner when they advance, get out, or score — omit if no advancement
                            if out_match:
                                run_el = ET.SubElement(play_elem, 'runner')
                                throw_m = re.search(r'(\w+)\s+to\s+(\w+)\b', narr, re.I)
                                run_action = '84'
                                if throw_m:
                                    a, b = throw_m.group(1).lower(), throw_m.group(2).lower()
                                    a, b = _POS_ALIAS.get(a, a), _POS_ALIAS.get(b, b)
                                    if a in _POS_NUM and b in _POS_NUM:
                                        run_action = f'{_POS_NUM[a]}{_POS_NUM[b]}'
                                # 1B +T: runner advanced then thrown out — use "+ " + throw code (e.g. "+ 72")
                                if adv_match:
                                    run_action = '+ ' + run_action
                                for k, v in _runner_attrs(base, name_full, run_action, '1', '0', '1'):
                                    run_el.set(k, v)
                            elif adv_match or scored_match:
                                run_el = ET.SubElement(play_elem, 'runner')
                                if adv_match:
                                    dest_key = adv_match.group(1).lower()
                                    tobase = tobase_map.get(dest_key, 4 if dest_key == 'home' else 3)
                                else:
                                    tobase = 4  # "scored" or "scoring Name" = home
                                if base == 1 and tobase == 4:
                                    action, adv = '+++', '3'
                                elif base == 2 and tobase == 4:
                                    action, adv = '++', '2'
                                else:
                                    action, adv = '+', '1'
                                # Presto: "advanced on error by X, assist by Y" → runner action "E4 A1 NA"
                                err_m = re.search(r'error\s+by\s+(\w+)', narr, re.I)
                                ast_m = re.search(r'assist\s+by\s+(\w+)', narr, re.I)
                                if err_m and ast_m and adv_match:
                                    err_pos = _POS_ALIAS.get((err_m.group(1) or '').lower(), (err_m.group(1) or '').lower())
                                    ast_pos = _POS_ALIAS.get((ast_m.group(1) or '').lower(), (ast_m.group(1) or '').lower())
                                    if err_pos in _POS_NUM and ast_pos in _POS_NUM:
                                        action = f'E{_POS_NUM[err_pos]} A{_POS_NUM[ast_pos]} NA'
                                        # Presto uses tobase=1 for "advanced to second" in error+assist plays
                                        if tobase == 2:
                                            tobase = 1
                                # Only the runner who scored unearned gets ue="1" — match "Name scored, unearned"
                                is_unearned = tobase == 4 and name_full and re.search(
                                    rf'{re.escape(name_full)}\s+scored\s*,\s*unearned\b',
                                    narr, re.I)
                                for k, v in _runner_attrs(base, name_full, action, '0', adv, tobase, scored=(tobase == 4), ue=is_unearned):
                                    run_el.set(k, v)
                            elif play.runners_after:
                                # Infer advancement from runners_after when narrative is minimal (e.g. "singled")
                                ra = (play.runners_after or '000')[:3]
                                if base == 1 and ra[1] == '1':
                                    run_el = ET.SubElement(play_elem, 'runner')
                                    for k, v in _runner_attrs(base, name_full, '+', '0', '1', '2'):
                                        run_el.set(k, v)
                                elif base == 2 and ra[2] == '1':
                                    run_el = ET.SubElement(play_elem, 'runner')
                                    for k, v in _runner_attrs(base, name_full, '+', '0', '1', '3'):
                                        run_el.set(k, v)
                                elif base == 3 and play.runs_scored:
                                    run_el = ET.SubElement(play_elem, 'runner')
                                    for k, v in _runner_attrs(base, name_full, '+', '0', '1', '4', scored=True):
                                        run_el.set(k, v)

                    # <pitcher> sub-element — attribute order: name, bf, ip, ab, bb, hbp, h, er, r, hr, so, kl
                    pit_el = ET.SubElement(play_elem, 'pitcher')
                    pit_attrs = [('name', _fullname(pch_name) or '')]
                    if not is_runner_only_advance_on_error and not is_admin_play:
                        if not is_df:
                            pit_attrs.append(('bf', '1'))
                        if batter_out or (is_fc and (play.outs_on_play or 0) >= 1) or is_hit:
                            ip_val = str(play.outs_on_play or 1) if is_dp_tp and (play.outs_on_play or 0) > 1 else '1'
                            pit_attrs.append(('ip', ip_val))
                        if is_ab:
                            pit_attrs.append(('ab', '1'))
                    if action_raw in ('BB', 'IBB'):
                        pit_attrs.append(('bb', '1'))
                    if action_raw in ('HBP', 'HP'):
                        pit_attrs.append(('hbp', '1'))
                    if is_ci:
                        pit_attrs.append(('cia', '1'))
                    if is_k_cs_dp:
                        pit_attrs.append(('csb', '1'))
                    if is_hit:
                        pit_attrs.append(('h', '1'))
                    if action_base == '2B':
                        pit_attrs.append(('double', '1'))
                    if action_base == '3B':
                        pit_attrs.append(('triple', '1'))
                    runs_allowed = play.runs_scored or 0
                    if runs_allowed:
                        pit_attrs.extend([('er', str(runs_allowed)), ('r', str(runs_allowed))])
                    if action_base == 'HR':
                        pit_attrs.append(('hr', '1'))
                    if is_strikeout:
                        pit_attrs.append(('so', '1'))
                    if action_raw == 'KL' or action_base == 'KL':
                        pit_attrs.append(('kl', '1'))
                    if action_has_wp:
                        pit_attrs.append(('wp', '1'))
                    if (batter_out or (is_fc and (play.outs_on_play or 0) >= 1)) and (action_base == 'GO' or is_throw_out or is_sac or is_dp_tp or is_fc or (is_unassisted_out and 'ground' in narr_lower)):
                        pit_attrs.append(('gndout', '1'))
                    if is_sac:
                        pit_attrs.append(('sha', '1'))
                    if is_sf:
                        pit_attrs.append(('sfa', '1'))
                        pit_attrs.append(('ab', '1'))
                        pit_attrs.append(('flyout', '1'))
                    if is_flyout:
                        pit_attrs.append(('flyout', '1'))
                    for k, v in pit_attrs:
                        pit_el.set(k, v)

                    # <pitches> sub-element — only include when pitches were thrown
                    if play.pitch_sequence and str(play.pitch_sequence).strip():
                        pit_seq_el = ET.SubElement(play_elem, 'pitches')
                        pit_seq_el.set('name', _fullname(pch_name) or '')
                        pitch_text = _decode_pitch_sequence(play.pitch_sequence)
                        if action_raw in ('HBP', 'HP') and pitch_text and pitch_text[-1] == 'I':
                            pitch_text = pitch_text[:-1] + 'H'
                        pit_seq_el.set('text', pitch_text)
                        import re as _re
                        if play.balls is not None and play.strikes is not None:
                            pit_seq_el.set('b', str(play.balls))
                            pit_seq_el.set('s', str(play.strikes))
                        else:
                            m = _re.search(r'\((\d+)-(\d+)\s', play.narrative or '')
                            if m:
                                pit_seq_el.set('b', m.group(1))
                                pit_seq_el.set('s', m.group(2))
                            else:
                                pb, ps = _balls_strikes_from_pitch_sequence(play.pitch_sequence)
                                pit_seq_el.set('b', str(pb))
                                pit_seq_el.set('s', str(ps))

                    # <fielder> sub-element
                    def_team = home if vh == 'V' else vis
                    if is_k_cs_dp:
                        # K + CS DP: p csb, c po/a/indp/csb, 2b po/indp (from throw code 24 = c to 2b)
                        cs_throw_code = ''
                        for part in (action_parts or []):
                            if len(part) == 2 and part.isdigit():
                                cs_throw_code = part
                                break
                        if not cs_throw_code:
                            tm = re.search(r'\b(\w+)\s+to\s+(\w+)\b', narr_lower)
                            if tm:
                                a_pos = _POS_ALIAS.get(tm.group(1), tm.group(1))
                                p_pos = _POS_ALIAS.get(tm.group(2), tm.group(2))
                                if a_pos in _POS_NUM and p_pos in _POS_NUM:
                                    cs_throw_code = f'{_POS_NUM[a_pos]}{_POS_NUM[p_pos]}'
                        _NUM_TO_POS = {1:'p',2:'c',3:'1b',4:'2b',5:'3b',6:'ss',7:'lf',8:'cf',9:'rf'}
                        _stat_sources = list(getattr(game, 'fielding_stats', []) or []) + list(game.batting_stats or [])
                        assist_pos = _NUM_TO_POS.get(int(cs_throw_code[0]), 'c') if cs_throw_code and cs_throw_code[0].isdigit() else 'c'
                        putout_pos = _NUM_TO_POS.get(int(cs_throw_code[1]), '2b') if cs_throw_code and len(cs_throw_code) >= 2 and cs_throw_code[1].isdigit() else '2b'
                        for fpos in ('p', assist_pos, putout_pos):
                            if fpos == putout_pos and putout_pos == assist_pos:
                                continue
                            fld_el = ET.SubElement(play_elem, 'fielder')
                            _fbs = next((s for s in _stat_sources if s.team_id == def_team.id
                                         and (s.position or '').lower().startswith(fpos)), None)
                            fld_el.set('pos', fpos)
                            fld_el.set('name', (_fbs.player.name if _fbs and _fbs.player else '') or (_fullname(pch_name) if fpos == 'p' else ''))
                            if fpos == 'p':
                                fld_el.set('csb', '1')
                            elif fpos == assist_pos:
                                fld_el.set('po', '1')
                                fld_el.set('indp', '1')
                                fld_el.set('a', '1')
                                fld_el.set('csb', '1')
                            else:
                                fld_el.set('po', '1')
                                fld_el.set('indp', '1')
                    elif is_strikeout and batter_out:
                        cat_bs = next((s for s in game.batting_stats if s.team_id == def_team.id
                                       and (s.position or '').lower().startswith('c')), None)
                        if cat_bs and cat_bs.player:
                            fld_el = ET.SubElement(play_elem, 'fielder')
                            fld_el.set('pos', 'c')
                            fld_el.set('name', cat_bs.player.name or '')
                            fld_el.set('po', '1')
                    elif is_strikeout and (action_has_wp or action_has_pb):
                        # K WP / K PB: catcher involved, no putout; K PB gets pb="1"
                        cat_bs = next((s for s in game.batting_stats if s.team_id == def_team.id
                                       and (s.position or '').lower().startswith('c')), None)
                        if cat_bs and cat_bs.player:
                            fld_el = ET.SubElement(play_elem, 'fielder')
                            fld_el.set('pos', 'c')
                            fld_el.set('name', cat_bs.player.name or '')
                            if action_has_pb:
                                fld_el.set('pb', '1')
                    elif (action_raw or '').upper() == 'BI' or (action_base or '').upper() == 'BI':
                        # Batter's interference — catcher gets putout
                        _stat_sources = list(getattr(game, 'fielding_stats', []) or []) + list(game.batting_stats or [])
                        cat_bs = next((s for s in _stat_sources if s.team_id == def_team.id
                                       and (s.position or '').lower().startswith('c')), None)
                        if cat_bs and cat_bs.player:
                            fld_el = ET.SubElement(play_elem, 'fielder')
                            fld_el.set('pos', 'c')
                            fld_el.set('name', cat_bs.player.name or '')
                            fld_el.set('po', '1')
                        else:
                            fld_el = ET.SubElement(play_elem, 'fielder')
                            fld_el.set('pos', 'c')
                            fld_el.set('name', '')
                            fld_el.set('po', '1')
                    elif is_ci:
                        # Catcher's interference — catcher gets ci="1" e="1"
                        _stat_sources = list(getattr(game, 'fielding_stats', []) or []) + list(game.batting_stats or [])
                        cat_bs = next((s for s in _stat_sources if s.team_id == def_team.id
                                       and (s.position or '').lower().startswith('c')), None)
                        if cat_bs and cat_bs.player:
                            fld_el = ET.SubElement(play_elem, 'fielder')
                            fld_el.set('pos', 'c')
                            fld_el.set('name', cat_bs.player.name or '')
                            fld_el.set('ci', '1')
                            fld_el.set('e', '1')
                        else:
                            fld_el = ET.SubElement(play_elem, 'fielder')
                            fld_el.set('pos', 'c')
                            fld_el.set('name', '')
                            fld_el.set('ci', '1')
                            fld_el.set('e', '1')
                    elif is_df and _err_pos_match:
                        # E9 DF: dropped foul — fielder who dropped it gets e="1"
                        _NUM_TO_POS = {1:'p',2:'c',3:'1b',4:'2b',5:'3b',6:'ss',7:'lf',8:'cf',9:'rf'}
                        pos_digit = int(_err_pos_match.group(1))
                        pos_norm = _NUM_TO_POS.get(pos_digit, '')
                        if pos_norm:
                            _pos_variants = {'2b': ('2b', '4', 'second'), 'cf': ('cf', '8', 'center'), '1b': ('1b', '3', 'first'),
                                             '3b': ('3b', '5', 'third'), 'ss': ('ss', '6', 'short'), 'c': ('c', '2', 'catcher'),
                                             'p': ('p', '1', 'pitcher'), 'lf': ('lf', '7', 'left'), 'rf': ('rf', '9', 'right')}
                            def _pos_matches(pos_lower, pnorm):
                                if not pos_lower or not pnorm: return False
                                for v in _pos_variants.get(pnorm, (pnorm,)):
                                    if pos_lower == str(v).lower(): return True
                                return pnorm == 'cf' and 'center' in (pos_lower or '') or pnorm == '2b' and 'second' in (pos_lower or '')
                            for stat in list(getattr(game, 'fielding_stats', []) or []) + list(game.batting_stats or []):
                                if stat.team_id != def_team.id or not getattr(stat, 'player', None): continue
                                if _pos_matches((stat.position or '').lower(), pos_norm):
                                    fld_el = ET.SubElement(play_elem, 'fielder')
                                    fld_el.set('pos', pos_norm)
                                    fld_el.set('name', stat.player.name or '')
                                    fld_el.set('e', '1')
                                    break
                            else:
                                fld_el = ET.SubElement(play_elem, 'fielder')
                                fld_el.set('pos', pos_norm)
                                fld_el.set('name', '')
                                fld_el.set('e', '1')
                    elif is_strikeout and action_has_error and _err_pos_match:
                        # K E2, K E5, etc.: fielder who made the error
                        _NUM_TO_POS = {1:'p',2:'c',3:'1b',4:'2b',5:'3b',6:'ss',7:'lf',8:'cf',9:'rf'}
                        pos_digit = int(_err_pos_match.group(1))
                        pos_norm = _NUM_TO_POS.get(pos_digit, '')
                        if pos_norm:
                            _pos_variants = {'2b': ('2b', '4', 'second'), 'cf': ('cf', '8', 'center'), '1b': ('1b', '3', 'first'),
                                             '3b': ('3b', '5', 'third'), 'ss': ('ss', '6', 'short'), 'c': ('c', '2', 'catcher'),
                                             'p': ('p', '1', 'pitcher'), 'lf': ('lf', '7', 'left'), 'rf': ('rf', '9', 'right')}
                            def _pos_matches(pos_lower, pnorm):
                                if not pos_lower or not pnorm: return False
                                for v in _pos_variants.get(pnorm, (pnorm,)):
                                    if pos_lower == str(v).lower(): return True
                                return pnorm == 'cf' and 'center' in (pos_lower or '') or pnorm == '2b' and 'second' in (pos_lower or '')
                            for stat in list(getattr(game, 'fielding_stats', []) or []) + list(game.batting_stats or []):
                                if stat.team_id != def_team.id or not getattr(stat, 'player', None): continue
                                if _pos_matches((stat.position or '').lower(), pos_norm):
                                    fld_el = ET.SubElement(play_elem, 'fielder')
                                    fld_el.set('pos', pos_norm)
                                    fld_el.set('name', stat.player.name or '')
                                    fld_el.set('e', '1')
                                    break
                            else:
                                fld_el = ET.SubElement(play_elem, 'fielder')
                                fld_el.set('pos', pos_norm)
                                fld_el.set('name', '')
                                fld_el.set('e', '1')
                    elif ('error' in narr_lower and 'assist' in narr_lower and
                          re.search(r'error\s+by\s+(\w+)', narr, re.I) and re.search(r'assist\s+by\s+(\w+)', narr, re.I)):
                        # Presto: "advanced on error by X, assist by Y" — emit assist fielder (a=1) then error fielder (e=1)
                        _POS_ALIAS_ERR = {'3b':'3b','third':'3b','1b':'1b','first':'1b','2b':'2b','second':'2b','ss':'ss','short':'ss','cf':'cf','center':'cf','lf':'lf','left':'lf','rf':'rf','right':'rf','c':'c','catcher':'c','p':'p','pitcher':'p'}
                        _pos_variants = {'2b': ('2b', '4', 'second'), 'cf': ('cf', '8', 'center'), '1b': ('1b', '3', 'first'),
                                         '3b': ('3b', '5', 'third'), 'ss': ('ss', '6', 'short'), 'c': ('c', '2', 'catcher'),
                                         'p': ('p', '1', 'pitcher'), 'lf': ('lf', '7', 'left'), 'rf': ('rf', '9', 'right')}
                        def _pos_matches(pos_lower, pnorm):
                            if not pos_lower or not pnorm:
                                return False
                            for v in _pos_variants.get(pnorm, (pnorm,)):
                                if pos_lower == str(v).lower():
                                    return True
                            return pnorm == 'cf' and 'center' in (pos_lower or '') or pnorm == '2b' and 'second' in (pos_lower or '')
                        ast_m = re.search(r'assist\s+by\s+(\w+)', narr, re.I)
                        err_m = re.search(r'error\s+by\s+(\w+)|(?:throwing|fielding)\s+error\s+by\s+(\w+)', narr, re.I)
                        if ast_m and err_m:
                            ast_pos = _POS_ALIAS_ERR.get((ast_m.group(1) or '').lower(), (ast_m.group(1) or '').lower())
                            err_pos_raw = (err_m.group(1) or err_m.group(2) or '').lower()
                            err_pos = _POS_ALIAS_ERR.get(err_pos_raw, err_pos_raw)
                            _VALID_POS = {'p','c','1b','2b','3b','ss','lf','cf','rf'}
                            for pos_norm, attr, val in [(ast_pos, 'a', '1'), (err_pos, 'e', '1')]:
                                if pos_norm and pos_norm in _VALID_POS:
                                    for stat in list(getattr(game, 'fielding_stats', []) or []) + list(game.batting_stats or []):
                                        if stat.team_id != def_team.id or not getattr(stat, 'player', None):
                                            continue
                                        if _pos_matches((stat.position or '').lower(), pos_norm):
                                            fld_el = ET.SubElement(play_elem, 'fielder')
                                            fld_el.set('pos', pos_norm)
                                            fld_el.set('name', stat.player.name or '')
                                            fld_el.set(attr, val)
                                            break
                                    else:
                                        fld_el = ET.SubElement(play_elem, 'fielder')
                                        fld_el.set('pos', pos_norm)
                                        fld_el.set('name', '')
                                        fld_el.set(attr, val)
                    elif is_error:
                        # Error play: E5, E5T, E6 — fielder who made the error; add assist fielder if narrative has "assist by"
                        _NUM_TO_POS = {1:'p',2:'c',3:'1b',4:'2b',5:'3b',6:'ss',7:'lf',8:'cf',9:'rf'}
                        _POS_ALIAS_ERR = {'3b':'3b','third':'3b','1b':'1b','first':'1b','2b':'2b','second':'2b','ss':'ss','short':'ss','cf':'cf','center':'cf','lf':'lf','left':'lf','rf':'rf','right':'rf','c':'c','catcher':'c','p':'p','pitcher':'p'}
                        pos_norm = _NUM_TO_POS.get(int(action_base[1]), '') if len(action_base) >= 2 and action_base[1].isdigit() else ''
                        if not pos_norm and play.narrative:
                            err_m = re.search(r'error\s+by\s+(\w+)|(?:throwing|fielding)\s+error\s+by\s+(\w+)', (play.narrative or '').lower())
                            if err_m:
                                pos_raw = (err_m.group(1) or err_m.group(2) or '').lower()
                                pos_norm = _POS_ALIAS_ERR.get(pos_raw, pos_raw)
                        _VALID_POS = {'p','c','1b','2b','3b','ss','lf','cf','rf'}
                        if pos_norm and pos_norm in _VALID_POS:
                            _pos_variants = {'2b': ('2b', '4', 'second'), 'cf': ('cf', '8', 'center'), '1b': ('1b', '3', 'first'),
                                             '3b': ('3b', '5', 'third'), 'ss': ('ss', '6', 'short'), 'c': ('c', '2', 'catcher'),
                                             'p': ('p', '1', 'pitcher'), 'lf': ('lf', '7', 'left'), 'rf': ('rf', '9', 'right')}
                            def _pos_matches(pos_lower, pnorm):
                                if not pos_lower or not pnorm:
                                    return False
                                for v in _pos_variants.get(pnorm, (pnorm,)):
                                    if pos_lower == str(v).lower():
                                        return True
                                return pnorm == 'cf' and 'center' in (pos_lower or '') or pnorm == '2b' and 'second' in (pos_lower or '')
                            # Presto: emit assist fielder first when narrative has "assist by Y"
                            ast_m = re.search(r'assist\s+by\s+(\w+)', (play.narrative or ''), re.I)
                            if ast_m:
                                ast_pos = _POS_ALIAS_ERR.get((ast_m.group(1) or '').lower(), (ast_m.group(1) or '').lower())
                                if ast_pos and ast_pos in _VALID_POS:
                                    for stat in list(getattr(game, 'fielding_stats', []) or []) + list(game.batting_stats or []):
                                        if stat.team_id != def_team.id or not getattr(stat, 'player', None):
                                            continue
                                        if _pos_matches((stat.position or '').lower(), ast_pos):
                                            fld_el = ET.SubElement(play_elem, 'fielder')
                                            fld_el.set('pos', ast_pos)
                                            fld_el.set('name', stat.player.name or '')
                                            fld_el.set('a', '1')
                                            break
                                    else:
                                        fld_el = ET.SubElement(play_elem, 'fielder')
                                        fld_el.set('pos', ast_pos)
                                        fld_el.set('name', '')
                                        fld_el.set('a', '1')
                            for stat in list(getattr(game, 'fielding_stats', []) or []) + list(game.batting_stats or []):
                                if stat.team_id != def_team.id or not getattr(stat, 'player', None):
                                    continue
                                if _pos_matches((stat.position or '').lower(), pos_norm):
                                    fld_el = ET.SubElement(play_elem, 'fielder')
                                    fld_el.set('pos', pos_norm)
                                    fld_el.set('name', stat.player.name or '')
                                    fld_el.set('e', '1')
                                    break
                            else:
                                fld_el = ET.SubElement(play_elem, 'fielder')
                                fld_el.set('pos', pos_norm)
                                fld_el.set('name', '')
                                fld_el.set('e', '1')
                    elif ('DP' in action_raw or 'TP' in action_raw or 'GDP' in action_raw) and re.match(r'\d{2,3}', action_base or ''):
                        # Double play / triple play: derive fielders from numeric code (e.g. 643, 543)
                        # Standard position numbers: 1=P, 2=C, 3=1B, 4=2B, 5=3B, 6=SS, 7=LF, 8=CF, 9=RF
                        seq_m = re.match(r'(\d{2,3})', action_base or '')
                        if seq_m:
                            seq = seq_m.group(1)
                            _NUM_TO_POS = {1:'p', 2:'c', 3:'1b', 4:'2b', 5:'3b', 6:'ss', 7:'lf', 8:'cf', 9:'rf'}
                            outs = play.outs_on_play or (3 if 'TP' in action_raw else 2)
                            # Presto lists fielders in reverse order (1b, 2b, 3b for 543); each putout gets po, all but last get a
                            rev_seq = list(seq)[::-1]
                            for i, ch in enumerate(rev_seq):
                                try:
                                    d = int(ch)
                                except ValueError:
                                    continue
                                pos = _NUM_TO_POS.get(d)
                                if not pos:
                                    continue
                                fld_el = ET.SubElement(play_elem, 'fielder')
                                fld_el.set('pos', pos)
                                stat_match = next((s for s in list(getattr(game, 'fielding_stats', []) or []) + list(game.batting_stats or [])
                                                   if s.team_id == def_team.id and (s.position or '').lower().startswith(pos) and getattr(s, 'player', None)), None)
                                fld_el.set('name', stat_match.player.name if stat_match and stat_match.player else '')
                                if i < outs:
                                    fld_el.set('po', '1')
                                else:
                                    fld_el.set('po', '0')
                                if i > 0:
                                    fld_el.set('a', '1')
                                fld_el.set('indp', '1')
                    elif (is_hit or is_throw_out or is_unassisted_out or is_fc) and (play.narrative or is_throw_out or is_unassisted_out) and (play.outs_on_play or 'out at' in (play.narrative or '').lower() or is_throw_out or is_unassisted_out or is_fc):
                        narr = (play.narrative or '').lower()
                        pos_throw, pos_catch = None, None
                        from_action_code = False
                        _VALID_FLD_POS = frozenset({'p', 'c', '1b', '2b', '3b', 'ss', 'lf', 'cf', 'rf'})
                        _NUM_TO_POS = {1:'p',2:'c',3:'1b',4:'2b',5:'3b',6:'ss',7:'lf',8:'cf',9:'rf'}
                        # Unassisted out: single digit, F/P/L+digit (F8, P3, L6, FF9 foul fly to rf), or XUA (3UA, 6UA) — putout only
                        if is_unassisted_out and action_base:
                            pos_digit = None
                            if len(action_base) == 1 and action_base.isdigit() and 1 <= int(action_base) <= 9:
                                pos_digit = int(action_base)
                            elif len(action_base) >= 2 and action_base[0].upper() in ('F', 'P', 'L') and action_base[-1].isdigit():
                                d = int(action_base[-1])
                                if 1 <= d <= 9:
                                    pos_digit = d
                            elif len(action_base) == 3 and action_base[0].isdigit() and 1 <= int(action_base[0]) <= 9 and action_base[1:].upper() == 'UA':
                                pos_digit = int(action_base[0])
                            pos_catch = _NUM_TO_POS.get(pos_digit, '') if pos_digit else ''
                            from_action_code = bool(pos_catch and pos_catch in _VALID_FLD_POS)
                        # Action code (83, 84, 82...) — 2-digit throw, assist + putout (skip if unassisted)
                        elif not is_unassisted_out and len(action_for_throw) == 2 and action_for_throw.isdigit():
                            a_num, p_num = int(action_for_throw[0]), int(action_for_throw[1])
                            pos_throw = _NUM_TO_POS.get(a_num, '')
                            pos_catch = _NUM_TO_POS.get(p_num, '')
                            from_action_code = True
                        if (not pos_throw or not pos_catch) and not (is_unassisted_out and pos_catch):
                            # Narrative fallback for unassisted: "flied out to center", "lined to short"
                            if is_unassisted_out and not pos_catch:
                                to_match = re.search(r'(?:flied|flew|lined|popped|grounded?)\s+(?:out\s+)?to\s+(\w+)', narr, re.I)
                                if to_match:
                                    pos_catch = _POS_ALIAS.get(to_match.group(1).lower(), to_match.group(1).lower())
                                    if pos_catch not in _VALID_FLD_POS:
                                        pos_catch = None
                            throw_match = re.search(
                                r'\b(cf|lf|rf|1b|2b|3b|ss|p|c|center|left|right|first|second|third|short|catcher|pitcher|[1-9])\s+to\s+(cf|lf|rf|1b|2b|3b|ss|p|c|center|left|right|first|second|third|short|catcher|pitcher|[1-9])\b',
                                narr, re.I)
                            if throw_match:
                                a_raw, p_raw = throw_match.group(1).lower(), throw_match.group(2).lower()
                                pos_throw = _NUM_TO_POS.get(int(a_raw), _POS_ALIAS.get(a_raw, a_raw)) if a_raw.isdigit() else _POS_ALIAS.get(a_raw, a_raw)
                                pos_catch = _NUM_TO_POS.get(int(p_raw), _POS_ALIAS.get(p_raw, p_raw)) if p_raw.isdigit() else _POS_ALIAS.get(p_raw, p_raw)
                                if pos_throw not in _VALID_FLD_POS or pos_catch not in _VALID_FLD_POS:
                                    pos_throw, pos_catch = None, None
                        if not pos_throw or not pos_catch:
                            # Skip num_match when we already have pos_catch from action/narrative (e.g. F9, "flied out to rf")
                            # — num_match would incorrectly match ball-strike counts like "(2-2 BBKK)" as 2-2 (c to c)
                            use_num_match = not (is_unassisted_out and pos_catch)
                            if use_num_match:
                                num_match = re.search(r'(\d)\s*[-–]\s*(\d)\b|(?:^|[\s,;])(\d)(\d)(?:[\s,;]|$)', narr)
                                if num_match:
                                    g = num_match.groups()
                                    a_num = int(g[0]) if g[0] is not None else int(g[3])
                                    p_num = int(g[1]) if g[0] is not None else int(g[4])
                                    # Only use when both are valid positions (1-9); "0-2" is a count, not 0 to 2b
                                    if 1 <= a_num <= 9 and 1 <= p_num <= 9:
                                        pos_throw = _NUM_TO_POS.get(a_num, '')
                                        pos_catch = _NUM_TO_POS.get(p_num, '')

                        if pos_catch and (pos_throw or is_unassisted_out):
                            # Only use narrative "out at X" when positions came from narrative, not action code.
                            # Action code (82, 83, 84...) is source of truth; narrative may be stale after edits.
                            out_at_m = re.search(r'out\s+at\s+(\w+)', narr) if not from_action_code else None
                            if out_at_m:
                                dest = _POS_ALIAS.get(out_at_m.group(1).lower(), out_at_m.group(1).lower())
                                if dest in ('1b', '2b', '3b', 'c', 'ss', 'lf', 'cf', 'rf', 'p'):
                                    pos_catch, pos_throw = dest, (pos_throw if pos_catch == dest else pos_catch)
                                    if pos_throw == pos_catch:
                                        throw_match = re.search(r'\b(\w+)\s+to\s+(\w+)\b', narr, re.I)
                                        if throw_match:
                                            orig = throw_match.group(1).lower()
                                            pos_throw = _POS_ALIAS.get(orig, orig)
                                            if pos_throw not in _VALID_FLD_POS:
                                                pos_throw = pos_catch
                            pos_b, pos_a = pos_catch, pos_throw
                            _pos_variants = {'2b': ('2b', '4', 'second', 'second base'),
                                             'cf': ('cf', '8', 'center', 'center field', 'centerfield'),
                                             '1b': ('1b', '3', 'first', 'first base'),
                                             '3b': ('3b', '5', 'third', 'third base'),
                                             'ss': ('ss', '6', 'short', 'shortstop'),
                                             'c': ('c', '2', 'catcher'),
                                             'p': ('p', '1', 'pitcher'),
                                             'lf': ('lf', '7', 'left', 'left field'),
                                             'rf': ('rf', '9', 'right', 'right field')}

                            def _pos_matches(pos_lower, pnorm):
                                if not pos_lower or not pnorm:
                                    return False
                                variants = _pos_variants.get(pnorm, (pnorm,))
                                for v in variants:
                                    if pos_lower == str(v).lower():
                                        return True
                                if pnorm == 'cf' and ('center' in pos_lower or pos_lower == '8'):
                                    return True
                                if pnorm == '2b' and ('second' in pos_lower or pos_lower == '4'):
                                    return True
                                return False

                            def _find_player_at_pos(team_id, pnorm):
                                if not pnorm:
                                    return None
                                # Prefer fielding_stats (defensive roster); fall back to batting_stats
                                for stat in list(getattr(game, 'fielding_stats', []) or []) + list(game.batting_stats or []):
                                    if stat.team_id != team_id or not getattr(stat, 'player', None):
                                        continue
                                    pos_lower = (stat.position or '').lower().strip()
                                    if _pos_matches(pos_lower, pnorm):
                                        return stat
                                return None

                            fld_attrs = {}  # pnorm -> {bs or None, po, a}
                            # Presto order: assist first, then putout
                            for pos, attrs in [(pos_a, {'po': '0', 'a': '1'}), (pos_b, {'po': '1'})]:
                                pnorm = (_POS_ALIAS.get(pos, pos) if pos else None)
                                if not pnorm or pnorm not in _VALID_FLD_POS:
                                    continue
                                bs = _find_player_at_pos(def_team.id, pnorm)
                                if pnorm not in fld_attrs:
                                    fld_attrs[pnorm] = {'bs': bs, 'po': 0, 'a': 0}
                                fld_attrs[pnorm]['po'] += int(attrs.get('po', 0))
                                fld_attrs[pnorm]['a'] += int(attrs.get('a', 0))
                            _POS_NUM_ORD = {'p': 1, 'c': 2, '1b': 3, '2b': 4, '3b': 5, 'ss': 6, 'lf': 7, 'cf': 8, 'rf': 9}
                            for pnorm, data in sorted(fld_attrs.items(), key=lambda x: _POS_NUM_ORD.get(x[0], 99)):
                                if pnorm not in _VALID_FLD_POS:
                                    continue
                                bs, po, a = data['bs'], data['po'], data['a']
                                if not (po or a):
                                    continue
                                fld_el = ET.SubElement(play_elem, 'fielder')
                                fld_el.set('pos', pnorm)
                                fld_el.set('name', (bs.player.name if bs and bs.player else '') or '')
                                fld_el.set('po', str(po))
                                if a:
                                    fld_el.set('a', str(a))

                    # <narrative> sub-element
                    if play.narrative:
                        narr_el = ET.SubElement(play_elem, 'narrative')
                        narr_el.set('text', _normalize_narrative(_narrative_full_names(play.narrative)))

                    if (play.action_type or '').upper() != 'SUB':
                        prev_batter, prev_pitcher = play.batter_name, pch_name or play.pitcher_name

                # <innsummary> live from plays: r, h, e, lob
                inn_r = _inning_runs_from_plays(half_plays)
                _act = lambda p: (p.action_type or '').upper()
                inn_h = sum(1 for p in half_plays if _act(p) in ('1B', '2B', '3B', 'HR') or
                            any(_act(p).startswith(x) for x in ('1B', '2B', '3B', 'HR')))
                inn_e = sum(1 for p in half_plays if _act(p).startswith('E'))
                last_play = half_plays[-1] if half_plays else None
                inn_lob = (last_play.runners_after or '000').count('1') if last_play else 0
                innsummary_el = ET.SubElement(batting_elem, 'innsummary')
                innsummary_el.set('r',   str(inn_r))
                innsummary_el.set('h',   str(inn_h))
                innsummary_el.set('e',   str(inn_e))
                innsummary_el.set('lob', str(inn_lob))

        # Empty inning elements (Presto format)
        max_inn = max((p.inning for p in all_plays), default=0)
        sched = game.scheduled_innings or 9
        if game.is_complete and max_inn > 0 and max_inn < sched:
            for n in range(max_inn + 1, sched + 1):
                empty_inn = ET.SubElement(plays_elem, 'inning')
                empty_inn.set('number', str(n))
        elif max_inn > 0 and not game.is_complete and all_plays:
            # In progress: show next inning only when current inning finished (3 outs in bottom half)
            last = max(all_plays, key=lambda p: (p.inning, 0 if p.half == 'top' else 1, p.sequence))
            cur_outs = (last.outs_before or 0) + (last.outs_on_play or 0)
            inn_finished = (last.half or '').lower() == 'bottom' and cur_outs >= 3
            if inn_finished:
                next_inn = ET.SubElement(plays_elem, 'inning')
                next_inn.set('number', str(max_inn + 1))

    # ── Status ──────────────────────────────────────────────────────────────────
    if game.is_complete:
        status = ET.SubElement(root, 'status')
        status.set('complete', 'Y')
    elif play_count > 0 and not game.is_complete and all_plays and vis and home:
        # In progress: plays exist — status with live count from last play
        last = max(all_plays, key=lambda p: (p.inning, 0 if p.half == 'top' else 1, p.sequence))
        cur_outs = (last.outs_before or 0) + (last.outs_on_play or 0)
        inn_done = cur_outs >= 3
        blob_live = _live_status_from_blob(game)
        # Status count should reflect the CURRENT at-bat only.
        # If the last saved play is in-progress, use it. Otherwise, look for a live
        # in-progress at-bat in the blob for the current/next half. If none exists,
        # the count is 0-0 with 0 pitches.
        if blob_live:
            b_str, s_str, np_val = str(blob_live['b']), str(blob_live['s']), blob_live['np']
        elif inn_done:
            # Half just ended — check blob for pitches already thrown to first batter of next half.
            # Pass the expected next inning/half so stale blob data from old at-bats is ignored.
            b_str, s_str, np_val = '0', '0', 0
            if (last.half or '').lower() == 'bottom':
                _next_inn, _next_half_ord = last.inning + 1, 0
            else:
                _next_inn, _next_half_ord = last.inning, 1
            live = _live_count_from_blob(game, expected_inn=_next_inn, expected_half_ord=_next_half_ord)
            if live:
                b_int, s_int, np_val = live
                b_str, s_str = str(b_int), str(s_int)
        elif last.pitch_sequence and not (last.action_type or '').strip():
            if last.balls is not None and last.strikes is not None:
                b_int, s_int = last.balls, last.strikes
            else:
                b_int, s_int = _balls_strikes_from_pitch_sequence(last.pitch_sequence)
            b_str, s_str = str(b_int), str(s_int)
            np_val = _pitch_count_from_sequence(last.pitch_sequence)  # total pitches in at-bat
        else:
            b_str, s_str, np_val = '0', '0', 0
            # Last play completed: only use blob if a NEW in-progress at-bat exists
            # in the same half. Never reuse the finished batter's terminal count.
            _cur_half_ord = 0 if (last.half or '').lower() == 'top' else 1
            live = _live_count_from_blob(game, expected_inn=last.inning, expected_half_ord=_cur_half_ord)
            if live:
                b_int, s_int, np_val = live
                b_str, s_str = str(b_int), str(s_int)
        # When blob live status exists, prefer the scorer's current synced inning/half.
        # Otherwise infer from the last saved play.
        inn_done = cur_outs >= 3
        if blob_live:
            vh = blob_live['vh']
            bat_id = vis_id if vh == 'V' else home_id
            status_inning = blob_live['inning']
            status_outs = blob_live['outs']
        elif inn_done:
            if (last.half or '').lower() == 'bottom':
                # Bottom ended -> top of next inning, visitor bats first
                vh, bat_id = 'V', vis_id
                status_inning = last.inning + 1
            else:
                # Top ended -> bottom of same inning, home bats
                vh, bat_id = 'H', home_id
                status_inning = last.inning
            status_outs = 0
        else:
            vh = 'V' if (last.half or '').lower() == 'top' else 'H'
            bat_id = vis_id if vh == 'V' else home_id
            status_inning = last.inning
            status_outs = cur_outs
        # vup/hup and current batter: derive from plays (game state), not PA count.
        # Dropped foul (E* DF) does not advance the batter; walk through plays to get current spot.
        def _eff_half(p):
            return (p.half or '').lower()

        def _current_batter_and_spot_from_plays(team_id, half_key):
            """Walk plays for this half; return (batter_name, spot 1-9) from game state."""
            bat_stats = [s for s in game.batting_stats if s.team_id == team_id and s.batting_order and 1 <= s.batting_order <= 10]
            if not bat_stats:
                return '', 1
            orders = sorted(set(s.batting_order for s in bat_stats))
            # spot -> current player (updated by SUB); init from starters
            spot_to_player = {}
            for s in bat_stats:
                if s.player and s.is_starter:
                    spot_to_player[s.batting_order] = s.player
            for s in bat_stats:
                if s.player and not s.is_starter and s.batting_order not in spot_to_player:
                    spot_to_player[s.batting_order] = s.player
            # name -> spot (for matching batter_name to order)
            name_to_spot = {}
            for s in bat_stats:
                if s.player:
                    for n in [s.player.name, _short_name(s.player), _presto_name(s.player)]:
                        if n:
                            name_to_spot[(n or '').strip()] = s.batting_order
            cur_spot = orders[0] if orders else 1
            for p in all_plays:
                if _eff_half(p) != half_key:
                    continue
                if (p.action_type or '').upper() == 'SUB':
                    # Update lineup: sub_who replaces sub_for at sub_spot
                    spot = getattr(p, 'sub_spot', None) or 0
                    if not (1 <= spot <= 10) and (p.sub_for or '').strip():
                        # Infer spot from sub_for
                        for_name = (p.sub_for or '').strip()
                        spot = name_to_spot.get(for_name, 0)
                    if 1 <= spot <= 10:
                        who = (p.sub_who or '').strip()
                        for s in bat_stats:
                            if s.player and (who == (s.player.name or '') or who == _short_name(s.player) or who in (s.player.name or '')):
                                spot_to_player[spot] = s.player
                                break
                    continue
                if 'DF' in (p.action_type or '').upper():
                    continue  # Dropped foul — same batter stays up
                # Real PA: advance to next batter
                bn = (p.batter_name or '').strip()
                if bn and bn in name_to_spot:
                    cur_spot = name_to_spot[bn]
                idx = orders.index(cur_spot) if cur_spot in orders else 0
                cur_spot = orders[(idx + 1) % len(orders)] if orders else cur_spot
            player = spot_to_player.get(cur_spot)
            return (player.name or _short_name(player) or '') if player else '', cur_spot

        cur_vis_batter, vup_val = _current_batter_and_spot_from_plays(vis.id, 'top')
        cur_home_batter, hup_val = _current_batter_and_spot_from_plays(home.id, 'bottom')

        # batter = current batter at plate (from game state)
        if last.pitch_sequence and not (last.action_type or '').strip():
            status_batter = last.batter_name or ''
        else:
            bat_team = vis if vh == 'V' else home
            status_batter = cur_vis_batter if vh == 'V' else cur_home_batter
            if not status_batter:
                status_batter = last.batter_name or ''
        # Runners on base: empty when inning ended (3 outs), else from runners_after
        ra = (last.runners_after or '000').ljust(3, '0') if status_outs < 3 else '000'
        adv_map = {'1B': 1, '2B': 2, '3B': 3, 'HR': 4, 'BB': 1, 'IBB': 1, 'HBP': 1, 'HP': 1, 'FC': 1}
        last_adv = 0 if (last.outs_on_play and last.outs_on_play > 0) or (last.action_type or '').upper() in _OUT_ACTIONS else adv_map.get((last.action_type or '').upper(), 0)
        # Batter on 1st when they reached (adv>=1); else runner_first was on 1st before
        st_first = (_fullname(last.batter_name) if last_adv >= 1 else _fullname(last.runner_first)) if ra[0] == '1' else ''
        st_second = _fullname(last.runner_first) if ra[1] == '1' else ''
        st_third = _fullname(last.runner_second) if ra[2] == '1' else ''

        status = ET.SubElement(root, 'status')
        status.set('complete', 'N')
        status.set('inning', str(status_inning))
        # endinn='Y' only when both halves of the inning are complete (bottom half ended).
        # If blob live status exists, we are looking at the current active half, so endinn=N.
        both_halves_done = (not blob_live) and inn_done and (last.half or '').lower() == 'bottom'
        status.set('endinn', 'Y' if both_halves_done else 'N')
        status.set('vh', vh)
        status.set('batting', bat_id)
        status.set('outs', str(status_outs))
        # Pitcher: defending team (opposite of batting). When vh='V' visitor bats, home pitches; vh='H' home bats, visitor pitches
        def_team = home if vh == 'V' else vis
        def _pitcher_on_status_def_team(name):
            if not name or not def_team:
                return ''
            for s in (game.pitching_stats or []):
                if s.team_id != def_team.id or not s.player:
                    continue
                full = (s.player.name or '').strip()
                short = (_short_name(s.player) or '').strip()
                cand = (name or '').strip()
                if full and (cand == full or cand in full or full in cand):
                    return full
                if short and (cand == short or cand in short or short in cand):
                    return full or short
            return ''
        status_pitcher = ''
        if not inn_done:
            status_pitcher = _pitcher_on_status_def_team(last.pitcher_name)
        if not status_pitcher:
            needed_half = 'top' if vh == 'V' else 'bottom'
            for p in reversed(all_plays):
                p_half = _eff_half(p)
                if p.pitcher_name and p_half == needed_half:
                    status_pitcher = _pitcher_on_status_def_team(p.pitcher_name)
                    if status_pitcher:
                        break
        if not status_pitcher:
            ps = next((s for s in game.pitching_stats if s.team_id == def_team.id and ((s.gs or 0) > 0 or (s.ip or 0) > 0)), None)
            if ps and ps.player:
                status_pitcher = ps.player.name or ''
        status.set('pitcher', status_pitcher)
        status.set('batter', _fullname(status_batter) or status_batter)
        status.set('first', st_first or '')
        status.set('second', st_second or '')
        status.set('third', st_third or '')
        status.set('vup', str(vup_val))
        status.set('hup', str(hup_val))
        status.set('b', b_str)
        status.set('s', s_str)
        status.set('np', str(np_val))
    elif (play_count == 0 or not all_plays) and game.has_lineup and vis and home:
        # Starters entered, no plays in DB (or empty) — status for top 1st
        # Check blob for in-progress pitch (e.g. Ball clicked before any completed AB)
        live = _live_count_from_blob(game)
        if live:
            b_int, s_int, np_val = live
            b_str, s_str = str(b_int), str(s_int)
            np_str = str(np_val)
        else:
            b_str, s_str, np_str = '0', '0', '0'

        status = ET.SubElement(root, 'status')
        status.set('complete', 'N')
        status.set('inning', '1')
        status.set('endinn', 'N')
        status.set('vh', 'V')
        status.set('batting', vis_id)
        status.set('outs', '0')
        # Home starting pitcher (pitcher with gs>0, or lineup player at position p)
        home_ps = next((s for s in game.pitching_stats if s.team_id == home.id and (s.gs or 0) > 0), None)
        if not home_ps:
            home_sp = next((s for s in game.batting_stats if s.team_id == home.id and s.is_starter and (s.position or '').lower() == 'p'), None)
            pitcher_name = home_sp.player.name if (home_sp and home_sp.player) else ''
        else:
            pitcher_name = home_ps.player.name if home_ps.player else ''
        status.set('pitcher', pitcher_name)
        # Visitor leadoff batter (batting_order=1)
        vis_bs = next((s for s in game.batting_stats if s.team_id == vis.id and s.batting_order == 1 and s.is_starter), None)
        batter_name = vis_bs.player.name if (vis_bs and vis_bs.player) else ''
        status.set('batter', batter_name)
        status.set('first', '')
        status.set('second', '')
        status.set('third', '')
        status.set('vup', '1')
        status.set('hup', '1')
        status.set('b', b_str)
        status.set('s', s_str)
        status.set('np', np_str)

    _indent(root)
    xml_bytes = ET.tostring(root, encoding='unicode', xml_declaration=False)
    # Presto format: use paired tags <tag></tag> instead of self-closing <tag/>
    xml_bytes = re.sub(r'<(umpires|lineinn|note|rules)([^>]*)\s*/>', r'<\1\2></\1>', xml_bytes)
    return '<?xml version="1.0" encoding="UTF-8"?>\n\n' + xml_bytes


# ── Route ─────────────────────────────────────────────────────────────────────

@xml_bp.route('/game/<int:event_id>/boxscore.xml')
def game_boxscore_xml(event_id):
    game = Game.query.get_or_404(event_id)

    xml_str  = build_bsgame_xml(game)
    filename = f"boxscore_{(game.date or 'nodate').replace('-', '')}_{event_id}.xml"

    force_dl = request.args.get('download', '0') == '1'
    disposition = f'attachment; filename="{filename}"' if force_dl else f'inline; filename="{filename}"'

    headers = {
        'Content-Disposition': disposition,
        'Cache-Control':       'no-cache, no-store, must-revalidate',
        'Pragma':              'no-cache',
        'Expires':             '0',
    }
    return Response(xml_str, mimetype='application/xml', headers=headers)
