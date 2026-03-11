"""Parser for Gameday Stats XML game files."""

from lxml import etree
from app import db
from app.models import (
    Team, Player, Game, InningScore,
    BattingStats, PitchingStats, FieldingStats, Play,
)


def _int(val, default=0):
    """Safely parse int from XML attribute."""
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        return default


def _float(val, default=0.0):
    """Safely parse float from XML attribute."""
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def _bool_yn(val):
    """Parse Y/N boolean."""
    return val and val.upper() == "Y"


def parse_game_xml(xml_content, league):
    """
    Parse a Gameday Stats XML game file and insert data into the database.

    Args:
        xml_content: XML string or bytes
        league: League model instance to associate teams with

    Returns:
        The created Game object, or None on error
    """
    if isinstance(xml_content, str):
        xml_content = xml_content.encode("utf-8")

    root = etree.fromstring(xml_content)
    venue = root.find("venue")
    if venue is None:
        raise ValueError("No <venue> element found in XML")

    # --- Parse venue / game info ---
    game_date = venue.get("date", "")
    location = venue.get("location", "")
    stadium = venue.get("stadium", "")
    start_time = venue.get("start", "")
    duration = venue.get("duration", "")
    attendance = _int(venue.get("attend"))
    scheduled_innings = _int(venue.get("schedinn"), 7)
    weather = venue.get("weather", "")
    is_league = _bool_yn(venue.get("leaguegame"))
    rules = venue.find("rules")
    used_dh = rules.get("usedh", "N") if rules is not None else "N"

    is_complete = False
    status = root.find("status")
    if status is not None:
        is_complete = _bool_yn(status.get("complete"))

    # --- Parse teams ---
    teams_xml = root.findall("team")
    visitor_team = None
    home_team = None
    team_map = {}  # vh -> (team_obj, team_xml)

    for team_xml in teams_xml:
        vh = team_xml.get("vh")
        code = team_xml.get("code", "")
        ext_id = team_xml.get("id", "")
        name = team_xml.get("name", "")

        team = Team.query.filter_by(code=code, league_id=league.id).first()
        if not team:
            team = Team(code=code, team_id=ext_id, name=name, league_id=league.id)
            db.session.add(team)
            db.session.flush()

        team_map[vh] = (team, team_xml)
        if vh == "V":
            visitor_team = team
        else:
            home_team = team

    if not visitor_team or not home_team:
        raise ValueError("Could not find both visitor and home teams in XML")

    # --- Check for duplicate game ---
    existing = Game.query.filter_by(
        date=game_date,
        visitor_team_id=visitor_team.id,
        home_team_id=home_team.id,
        start_time=start_time,
    ).first()
    if existing:
        return existing  # Already imported

    # --- Create Game ---
    game = Game(
        date=game_date,
        location=location,
        stadium=stadium,
        start_time=start_time,
        duration=duration,
        attendance=attendance,
        scheduled_innings=scheduled_innings,
        weather=weather,
        is_league_game=is_league,
        is_complete=is_complete,
        used_dh=used_dh,
        visitor_team_id=visitor_team.id,
        home_team_id=home_team.id,
    )
    db.session.add(game)
    db.session.flush()

    # --- Parse line scores and team totals ---
    for vh, (team, team_xml) in team_map.items():
        linescore = team_xml.find("linescore")
        if linescore is not None:
            runs = _int(linescore.get("runs"))
            hits = _int(linescore.get("hits"))
            errs = _int(linescore.get("errs"))
            lob = _int(linescore.get("lob"))

            if vh == "V":
                game.visitor_runs = runs
                game.visitor_hits = hits
                game.visitor_errors = errs
                game.visitor_lob = lob
            else:
                game.home_runs = runs
                game.home_hits = hits
                game.home_errors = errs
                game.home_lob = lob

            for lineinn in linescore.findall("lineinn"):
                inn_num = _int(lineinn.get("inn"))
                score = lineinn.get("score", "0")

                existing_inn = InningScore.query.filter_by(
                    game_id=game.id, inning=inn_num
                ).first()
                if existing_inn:
                    if vh == "V":
                        existing_inn.visitor_score = score
                    else:
                        existing_inn.home_score = score
                else:
                    inn_score = InningScore(
                        game_id=game.id,
                        inning=inn_num,
                        visitor_score=score if vh == "V" else "0",
                        home_score=score if vh == "H" else "0",
                    )
                    db.session.add(inn_score)
                    db.session.flush()

        # --- Parse players ---
        for player_xml in team_xml.findall("player"):
            player_name = player_xml.get("name", "")
            uni = player_xml.get("uni", "")
            gp = _int(player_xml.get("gp"))
            gs = _int(player_xml.get("gs"))
            ext_player_id = player_xml.get("playerId", "")
            bats = player_xml.get("bats", "")
            throws = player_xml.get("throws", "")
            player_class = player_xml.get("class", "")
            spot = _int(player_xml.get("spot"))
            pos = player_xml.get("pos", "")
            is_sub = _bool_yn(player_xml.get("sub")) or _int(player_xml.get("sub")) == 1

            # Find or create player
            player = Player.query.filter_by(
                name=player_name, uniform_number=uni, team_id=team.id
            ).first()
            if not player:
                player = Player(
                    external_id=ext_player_id,
                    name=player_name,
                    short_name=player_xml.get("shortname", player_name),
                    uniform_number=uni,
                    bats=bats,
                    throws=throws,
                    player_class=player_class,
                    team_id=team.id,
                )
                db.session.add(player)
                db.session.flush()
            elif ext_player_id and not player.external_id:
                player.external_id = ext_player_id

            if gp == 0:
                continue  # Player didn't play in this game

            # --- Batting stats ---
            hitting = player_xml.find("hitting")
            if hitting is not None:
                batting = BattingStats(
                    game_id=game.id,
                    player_id=player.id,
                    team_id=team.id,
                    batting_order=spot,
                    position=pos,
                    is_starter=gs == 1,
                    is_sub=is_sub,
                    ab=_int(hitting.get("ab")),
                    r=_int(hitting.get("r")),
                    h=_int(hitting.get("h")),
                    rbi=_int(hitting.get("rbi")),
                    doubles=_int(hitting.get("double")),
                    triples=_int(hitting.get("triple")),
                    hr=_int(hitting.get("hr")),
                    bb=_int(hitting.get("bb")),
                    so=_int(hitting.get("so")),
                    sb=_int(hitting.get("sb")),
                    cs=_int(hitting.get("cs")),
                    hbp=_int(hitting.get("hbp")),
                    sh=_int(hitting.get("sh")),
                    sf=_int(hitting.get("sf")),
                    gdp=_int(hitting.get("gdp")),
                    ibb=_int(hitting.get("ibb")),
                    ground=_int(hitting.get("ground")),
                    fly=_int(hitting.get("fly")),
                    kl=_int(hitting.get("kl")),
                )
                db.session.add(batting)

            # --- Fielding stats ---
            fielding = player_xml.find("fielding")
            if fielding is not None:
                fstats = FieldingStats(
                    game_id=game.id,
                    player_id=player.id,
                    team_id=team.id,
                    position=pos,
                    po=_int(fielding.get("po")),
                    a=_int(fielding.get("a")),
                    e=_int(fielding.get("e")),
                    pb=_int(fielding.get("pb")),
                    ci=_int(fielding.get("ci")),
                    sba=_int(fielding.get("sba")),
                )
                db.session.add(fstats)

            # --- Pitching stats ---
            pitching = player_xml.find("pitching")
            if pitching is not None:
                win_str = pitching.get("win", "")
                loss_str = pitching.get("loss", "")
                save_str = pitching.get("save", "")

                pstats = PitchingStats(
                    game_id=game.id,
                    player_id=player.id,
                    team_id=team.id,
                    appear=_int(pitching.get("appear")),
                    gs=_int(pitching.get("gs")),
                    ip=_float(pitching.get("ip")),
                    ab=_int(pitching.get("ab")),
                    h=_int(pitching.get("h")),
                    r=_int(pitching.get("r")),
                    er=_int(pitching.get("er")),
                    bb=_int(pitching.get("bb")),
                    so=_int(pitching.get("so")),
                    hr=_int(pitching.get("hr")),
                    doubles=_int(pitching.get("double")),
                    triples=_int(pitching.get("triple")),
                    hbp=_int(pitching.get("hbp")),
                    bf=_int(pitching.get("bf")),
                    wp=_int(pitching.get("wp")),
                    bk=_int(pitching.get("bk")),
                    ibb=_int(pitching.get("ibb")),
                    fly=_int(pitching.get("fly")),
                    ground=_int(pitching.get("ground")),
                    kl=_int(pitching.get("kl")),
                    pitches=_int(pitching.get("pitches")),
                    strikes=_int(pitching.get("strikes")),
                    cg=_int(pitching.get("cg")),
                    sho=_int(pitching.get("sho")),
                    win=bool(win_str),
                    loss=bool(loss_str),
                    save=bool(save_str),
                )
                db.session.add(pstats)

    # --- Parse play-by-play ---
    plays_xml = root.find("plays")
    if plays_xml is not None:
        for inning_xml in plays_xml.findall("inning"):
            inn_num = _int(inning_xml.get("number"))

            for batting_xml in inning_xml.findall("batting"):
                vh = batting_xml.get("vh")
                half = "top" if vh == "V" else "bottom"

                for play_xml in batting_xml.findall("play"):
                    seq = _int(play_xml.get("seq"))
                    outs = _int(play_xml.get("outs"))
                    batter = play_xml.get("batter", "")
                    pitcher = play_xml.get("pitcher", "")

                    narrative_el = play_xml.find("narrative")
                    narrative = narrative_el.get("text", "") if narrative_el is not None else ""

                    # Check for substitution narrative
                    sub_el = play_xml.find("sub")
                    if sub_el is not None and not narrative:
                        narrative = f"{sub_el.get('who', '')} to {sub_el.get('pos', '')} for {sub_el.get('for', '')}."

                    pitches_el = play_xml.find("pitches")
                    pitch_seq = pitches_el.get("text", "") if pitches_el is not None else ""

                    if narrative or batter:
                        play = Play(
                            game_id=game.id,
                            inning=inn_num,
                            half=half,
                            sequence=seq,
                            outs_before=outs,
                            batter_name=batter,
                            pitcher_name=pitcher,
                            pitch_sequence=pitch_seq,
                            narrative=narrative,
                        )
                        db.session.add(play)

    db.session.commit()
    return game
