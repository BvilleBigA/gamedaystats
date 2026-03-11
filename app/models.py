import re
from datetime import datetime
from app import db


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(200), unique=True, nullable=False)  # stores email
    password_sha256 = db.Column(db.String(64), nullable=False)
    display_name = db.Column(db.String(100))
    phone = db.Column(db.String(30), default='')

    @property
    def email(self):
        return self.username
    role = db.Column(db.String(20), default='scorer')  # 'admin' or 'scorer'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UserPermission(db.Model):
    """Grants a scorer user access to a specific season (and optionally a team)."""
    __tablename__ = 'user_permission'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)  # None = all teams in season

    user = db.relationship('User', backref='permissions')
    season = db.relationship('Season', backref='permissions')
    team = db.relationship('Team', backref='permissions')


class UserSchoolPermission(db.Model):
    """Grants a user access to all seasons (current and future) for a school."""
    __tablename__ = 'user_school_permission'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('school.id'), nullable=False)

    user = db.relationship('User', backref='school_permissions')
    school = db.relationship('School', backref='user_permissions')


class School(db.Model):
    __tablename__ = 'school'
    id    = db.Column(db.Integer, primary_key=True)
    name  = db.Column(db.String(200), nullable=False)
    rpi   = db.Column(db.String(50), default='')   # identifier used when selecting games
    code  = db.Column(db.String(50), default='')   # short code / abbreviation
    city  = db.Column(db.String(100), default='')
    state = db.Column(db.String(10), default='')
    logo  = db.Column(db.String(200), default='')   # filename under CDN schools/ e.g. "schools/123.png"
    teams = db.relationship('Team', backref='school', lazy=True)

    def __repr__(self):
        return f"<School {self.name}>"


class Season(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    play_entry_mode = db.Column(db.String(40), default="box_game_totals")  # box_game_totals, box_inning_by_inning, pbp_simple
    rules = db.Column(db.String(30), default="rules_hs_sb")  # rules_hs_ba, rules_hs_sb, rules_ncaa_ba, rules_ncaa_sb, rules_mlb
    gender = db.Column(db.String(20), default="female")  # male, female, coed
    sport_id = db.Column(db.Integer, default=1)  # stats-engine int: 0=Football,1=Baseball,2=Basketball,3=Soccer,4=Volleyball,5=IceHockey,6=LacrosseMen,7=Tennis,9=FieldHockey,10=LacrosseWomen,11=Softball,12=WaterPolo
    sport_code = db.Column(db.String(50), default='')  # URL string code, e.g. 'bsb', 'sballhs', 'hsvarsitymbkb'
    start_date = db.Column(db.String(20), default='')  # YYYY-MM-DD
    end_date = db.Column(db.String(20), default='')    # YYYY-MM-DD
    teams = db.relationship("Team", backref="season", lazy=True)

    @property
    def slug(self):
        """URL-friendly version of the season name, e.g. 'Demo Season' -> 'demo-season'."""
        s = self.name.lower().strip()
        s = re.sub(r'[^a-z0-9\s-]', '', s)
        s = re.sub(r'[\s]+', '-', s)
        return s

    def __repr__(self):
        return f"<Season {self.name}>"


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), nullable=False)
    team_id = db.Column(db.String(50))  # external ID like "STATS1"
    name = db.Column(db.String(200), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey("season.id"))
    school_id = db.Column(db.Integer, db.ForeignKey("school.id"), nullable=True)
    stadium = db.Column(db.String(200), default="")
    city = db.Column(db.String(100), default="")
    state = db.Column(db.String(50), default="")
    mascot = db.Column(db.String(100), default="")
    print_name = db.Column(db.String(200), default="")
    abbreviation = db.Column(db.String(20), default="")
    league = db.Column(db.String(100), default="")
    division = db.Column(db.String(100), default="")
    coach = db.Column(db.String(200), default="")
    conference = db.Column(db.String(100), default="")
    players = db.relationship("Player", backref="team", lazy=True)

    __table_args__ = (db.UniqueConstraint("code", "season_id", name="uq_team_code_season"),)

    def __repr__(self):
        return f"<Team {self.name}>"


class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    external_id = db.Column(db.String(50))  # playerId from XML
    name = db.Column(db.String(200), nullable=False)
    first_name = db.Column(db.String(100), default="")
    last_name = db.Column(db.String(100), default="")
    short_name = db.Column(db.String(100))
    uniform_number = db.Column(db.String(10))
    position = db.Column(db.String(30), default="")
    bats = db.Column(db.String(10), default="")
    throws = db.Column(db.String(10), default="")
    player_class = db.Column(db.String(10))  # class year
    year = db.Column(db.String(10), default="")
    height = db.Column(db.String(10), default="")
    weight = db.Column(db.String(10), default="")
    hometown = db.Column(db.String(200), default="")
    disabled = db.Column(db.Boolean, default=False)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"))
    batting_stats = db.relationship("BattingStats", backref="player", lazy=True)
    pitching_stats = db.relationship("PitchingStats", backref="player", lazy=True)
    fielding_stats = db.relationship("FieldingStats", backref="player", lazy=True)

    __table_args__ = (db.UniqueConstraint("name", "uniform_number", "team_id", name="uq_player_team"),)

    def __repr__(self):
        return f"<Player {self.name} #{self.uniform_number}>"


class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    location = db.Column(db.String(200))
    stadium = db.Column(db.String(200))
    start_time = db.Column(db.String(20))
    duration = db.Column(db.String(20))
    attendance = db.Column(db.Integer, default=0)
    scheduled_innings = db.Column(db.Integer, default=7)
    weather = db.Column(db.String(200))
    is_league_game = db.Column(db.Boolean, default=True)
    is_complete = db.Column(db.Boolean, default=False)
    has_lineup  = db.Column(db.Boolean, default=False)  # True once batting orders entered in GWT
    doubleheader = db.Column(db.Integer, default=0)  # 0 = not a doubleheader, 1 = game 1, 2 = game 2
    used_dh = db.Column(db.String(5))
    state = db.Column(db.String(100))
    delayed_time = db.Column(db.String(20))
    scorer = db.Column(db.String(200))
    ump_hp = db.Column(db.String(200))
    ump_1b = db.Column(db.String(200))
    ump_2b = db.Column(db.String(200))
    ump_3b = db.Column(db.String(200))
    notes = db.Column(db.Text)
    is_neutral = db.Column(db.Boolean, default=False)
    is_exhibition = db.Column(db.Boolean, default=False)
    is_region = db.Column(db.Boolean, default=False)
    is_conf_division = db.Column(db.Boolean, default=False)
    is_night = db.Column(db.Boolean, default=False)
    visitor_record = db.Column(db.String(20), default="")
    visitor_conf = db.Column(db.String(20), default="")
    home_record = db.Column(db.String(20), default="")
    home_conf = db.Column(db.String(20), default="")
    entry_mode = db.Column(db.String(40), default="box_game_totals")
    gwt_bs_blob = db.Column(db.Text, default='')   # raw GWT boxscore JSON — returned verbatim by event.json

    visitor_team_id = db.Column(db.Integer, db.ForeignKey("team.id"))
    home_team_id = db.Column(db.Integer, db.ForeignKey("team.id"))

    visitor_team = db.relationship("Team", foreign_keys=[visitor_team_id])
    home_team = db.relationship("Team", foreign_keys=[home_team_id])

    # Line score totals
    visitor_runs = db.Column(db.Integer, default=0)
    visitor_hits = db.Column(db.Integer, default=0)
    visitor_errors = db.Column(db.Integer, default=0)
    visitor_lob = db.Column(db.Integer, default=0)
    home_runs = db.Column(db.Integer, default=0)
    home_hits = db.Column(db.Integer, default=0)
    home_errors = db.Column(db.Integer, default=0)
    home_lob = db.Column(db.Integer, default=0)

    innings = db.relationship("InningScore", backref="game", lazy=True, order_by="InningScore.inning")
    batting_stats = db.relationship("BattingStats", backref="game", lazy=True)
    pitching_stats = db.relationship("PitchingStats", backref="game", lazy=True)
    fielding_stats = db.relationship("FieldingStats", backref="game", lazy=True)
    plays = db.relationship("Play", backref="game", lazy=True, order_by="Play.sequence")

    # Unique constraint: one game per date/visitor/home combo
    __table_args__ = (
        db.UniqueConstraint("date", "visitor_team_id", "home_team_id", "start_time", name="uq_game"),
    )

    @property
    def slug(self):
        """URL slug: MMDDYYYY_VisAbbrev_HomeAbbrev_DoubleheaderNum."""
        # date is stored as 'YYYY-MM-DD'
        if self.date and len(self.date) >= 10:
            parts = self.date.split('-')
            date_str = parts[1] + parts[2] + parts[0]  # MMDDYYYY
        else:
            date_str = '00000000'
        vis_abbr = (self.visitor_team.abbreviation if self.visitor_team and self.visitor_team.abbreviation else 'VIS')
        home_abbr = (self.home_team.abbreviation if self.home_team and self.home_team.abbreviation else 'HOM')
        dh = self.doubleheader or 0
        return f"{date_str}_{vis_abbr}_{home_abbr}_{dh}"

    @property
    def has_boxscore(self):
        return self.is_complete or bool(self.innings) or bool(self.batting_stats)

    @property
    def status_label(self):
        """Human-readable game status: score + inning/half or Final."""
        def _ord(n):
            if 11 <= (n % 100) <= 13:
                return f"{n}th"
            return f"{n}" + {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')

        if self.is_complete:
            return f"{self.visitor_runs}-{self.home_runs} Final"

        if self.innings:
            inning_map = {i.inning: i for i in self.innings}
            last_num = max(inning_map.keys())
            last = inning_map[last_num]
            try:
                v = int(last.visitor_score or 0)
                h = int(last.home_score or 0)
            except (TypeError, ValueError):
                v, h = 0, 0
            vr = self.visitor_runs or 0
            hr = self.home_runs or 0
            # Visitor scored but home hasn't batted yet in that inning → bottom half
            if v > 0 and h == 0:
                return f"{vr}-{hr} Bot of {_ord(last_num)}"
            # Both halves complete → top of next inning
            return f"{vr}-{hr} Top of {_ord(last_num + 1)}"

        if self.batting_stats:
            return f"{self.visitor_runs or 0}-{self.home_runs or 0} In Progress"

        if self.has_lineup:
            return "0-0 Top of 1st"

        return None  # not started

    def __repr__(self):
        return f"<Game {self.date}: {self.visitor_team_id} @ {self.home_team_id}>"


class InningScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False)
    inning = db.Column(db.Integer, nullable=False)
    visitor_score = db.Column(db.String(5), default="0")
    home_score = db.Column(db.String(5), default="0")


class BattingStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)

    # Game context
    batting_order = db.Column(db.Integer)
    position = db.Column(db.String(10))
    is_starter = db.Column(db.Boolean, default=False)
    is_sub = db.Column(db.Boolean, default=False)

    # Core batting stats
    ab = db.Column(db.Integer, default=0)
    r = db.Column(db.Integer, default=0)
    h = db.Column(db.Integer, default=0)
    rbi = db.Column(db.Integer, default=0)
    doubles = db.Column(db.Integer, default=0)
    triples = db.Column(db.Integer, default=0)
    hr = db.Column(db.Integer, default=0)
    bb = db.Column(db.Integer, default=0)
    so = db.Column(db.Integer, default=0)
    sb = db.Column(db.Integer, default=0)
    cs = db.Column(db.Integer, default=0)
    hbp = db.Column(db.Integer, default=0)
    sh = db.Column(db.Integer, default=0)
    sf = db.Column(db.Integer, default=0)
    gdp = db.Column(db.Integer, default=0)
    ibb = db.Column(db.Integer, default=0)
    ground = db.Column(db.Integer, default=0)
    fly = db.Column(db.Integer, default=0)
    kl = db.Column(db.Integer, default=0)  # called strikeouts (looking)

    def avg(self):
        return self.h / self.ab if self.ab > 0 else 0.0

    def obp(self):
        denom = self.ab + self.bb + self.hbp + self.sf
        return (self.h + self.bb + self.hbp) / denom if denom > 0 else 0.0

    def slg(self):
        if self.ab == 0:
            return 0.0
        singles = self.h - self.doubles - self.triples - self.hr
        total_bases = singles + (2 * self.doubles) + (3 * self.triples) + (4 * self.hr)
        return total_bases / self.ab

    def ops(self):
        return self.obp() + self.slg()


class PitchingStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)

    appear = db.Column(db.Integer, default=0)
    gs = db.Column(db.Integer, default=0)  # game started
    ip = db.Column(db.Float, default=0.0)  # innings pitched (e.g., 4.1 = 4 and 1/3)
    ab = db.Column(db.Integer, default=0)
    h = db.Column(db.Integer, default=0)
    r = db.Column(db.Integer, default=0)
    er = db.Column(db.Integer, default=0)
    bb = db.Column(db.Integer, default=0)
    so = db.Column(db.Integer, default=0)
    hr = db.Column(db.Integer, default=0)
    doubles = db.Column(db.Integer, default=0)
    triples = db.Column(db.Integer, default=0)
    hbp = db.Column(db.Integer, default=0)
    bf = db.Column(db.Integer, default=0)  # batters faced
    wp = db.Column(db.Integer, default=0)
    bk = db.Column(db.Integer, default=0)
    ibb = db.Column(db.Integer, default=0)
    fly = db.Column(db.Integer, default=0)
    ground = db.Column(db.Integer, default=0)
    kl = db.Column(db.Integer, default=0)
    pitches = db.Column(db.Integer, default=0)
    strikes = db.Column(db.Integer, default=0)
    cg = db.Column(db.Integer, default=0)  # complete game
    sho = db.Column(db.Integer, default=0)  # shutout
    win = db.Column(db.Boolean, default=False)
    loss = db.Column(db.Boolean, default=False)
    save = db.Column(db.Boolean, default=False)

    def era(self):
        """Calculate ERA. IP is stored as e.g. 4.1 meaning 4 and 1/3 innings."""
        ip_full = int(self.ip)
        ip_frac = round((self.ip - ip_full) * 10)
        total_thirds = ip_full * 3 + ip_frac
        if total_thirds == 0:
            return float("inf") if self.er > 0 else 0.0
        return (self.er * 7 * 3) / total_thirds  # 7-inning game default for softball

    def whip(self):
        ip_full = int(self.ip)
        ip_frac = round((self.ip - ip_full) * 10)
        total_thirds = ip_full * 3 + ip_frac
        if total_thirds == 0:
            return 0.0
        ip_decimal = total_thirds / 3
        return (self.bb + self.h) / ip_decimal


class FieldingStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    position = db.Column(db.String(10))

    po = db.Column(db.Integer, default=0)
    a = db.Column(db.Integer, default=0)
    e = db.Column(db.Integer, default=0)
    pb = db.Column(db.Integer, default=0)  # passed balls
    ci = db.Column(db.Integer, default=0)  # catcher interference
    sba = db.Column(db.Integer, default=0)  # stolen bases allowed
    indp = db.Column(db.Integer, default=0)  # induced double play
    intp = db.Column(db.Integer, default=0)  # induced triple play
    csb = db.Column(db.Integer, default=0)  # caught stealing


class GameRosterEntry(db.Model):
    """Per-game player info override — used for XML/reports without altering the team roster."""
    __tablename__ = 'game_roster_entry'
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    uniform_number = db.Column(db.String(10), default='')
    display_name = db.Column(db.String(100), default='')
    position = db.Column(db.String(10), default='')
    bats = db.Column(db.String(10), default='Right')
    throws = db.Column(db.String(10), default='Right')
    is_removed = db.Column(db.Boolean, default=False)

    player = db.relationship('Player', backref='game_roster_entries')


class GameVersion(db.Model):
    """Snapshot of the boxscore state saved after every GWT input."""
    __tablename__ = 'game_version'
    id            = db.Column(db.Integer, primary_key=True)
    game_id       = db.Column(db.Integer, db.ForeignKey('game.id'), nullable=False)
    version_key   = db.Column(db.String(20), unique=True, nullable=False)  # hash used in URL #fragment
    label         = db.Column(db.String(400), default='')   # display label in dropdown
    snapshot_json = db.Column(db.Text, default='')           # full _boxscore_data() JSON
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    created_by    = db.Column(db.String(200), default='')

    game = db.relationship('Game', backref=db.backref('versions', order_by='GameVersion.id.desc()', lazy=True))

    def __repr__(self):
        return f"<GameVersion {self.version_key} game={self.game_id}>"


class Play(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False)
    inning = db.Column(db.Integer, nullable=False)
    half = db.Column(db.String(10))  # "top" or "bottom"
    sequence = db.Column(db.Integer, nullable=False)
    outs_before = db.Column(db.Integer, default=0)
    batter_name = db.Column(db.String(200))
    pitcher_name = db.Column(db.String(200))
    pitch_sequence = db.Column(db.String(50))
    balls = db.Column(db.Integer)    # current count when in-progress; from GWT CURRENT_BALLS
    strikes = db.Column(db.Integer)  # current count when in-progress; from GWT CURRENT_STRIKES
    narrative = db.Column(db.Text)
    action_type = db.Column(db.String(80))       # e.g. "KS", "3B RL RBI3", "HR", "SUB"
    rbi = db.Column(db.Integer, default=0)
    outs_on_play = db.Column(db.Integer, default=0)
    runs_scored = db.Column(db.Integer, default=0)
    runners_after = db.Column(db.String(3), default='000')  # bitmask: '111' = bases loaded
    # Substitution-specific fields (only populated when action_type == 'SUB')
    sub_who = db.Column(db.String(200), default='')  # player coming in
    sub_for = db.Column(db.String(200), default='')  # player going out
    sub_pos = db.Column(db.String(20),  default='')  # position code: ph, pr, p, …
    sub_spot = db.Column(db.Integer,    default=0)   # batting order spot
    sub_vh = db.Column(db.String(1),    default='')  # V or H
    # Runners on base before play (from OFF_PLAYERS_BEF)
    runner_first = db.Column(db.String(200), default='')
    runner_second = db.Column(db.String(200), default='')
    runner_third = db.Column(db.String(200), default='')
