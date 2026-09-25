import os

import requests
from db import (
    get_connection,
    get_games_missing_box_scores,
    get_games_missing_periods,
    insert_box_score,
    insert_game,
    insert_game_periods,
    insert_player,
    insert_team,
    upsert_box_score_player,
    upsert_opponent_team,
)
from dotenv import load_dotenv

# --- Load API key from .env ---
load_dotenv()
BALLDONTLIE_KEY = os.getenv("BALLDONTLIE_KEY")
headers = {"Authorization": BALLDONTLIE_KEY}

conn = get_connection()


def extract_espn_fields(a):
    """Pull the common enrichment fields out of an ESPN athlete dict."""
    college = a.get("college", {}).get("name")
    headshot_url = a.get("headshot", {}).get("href")
    shoots_catches = a.get("hand", {}).get("abbreviation")  # NEW

    contracts = a.get("contracts", [])
    if contracts:
        contracts_sorted = sorted(
            contracts, key=lambda c: c.get("season", {}).get("year", 0), reverse=True
        )
        most_recent = contracts_sorted[0]
        contract_salary = most_recent.get("salary")
        contract_season = most_recent.get("season", {}).get("year")
        contract_total_value = sum(c.get("salary", 0) for c in contracts)
        contract_years = len(contracts)
        contract_expires = (
            most_recent.get("season", {}).get("endDate", "").split("T")[0] or None
        )
    else:
        contract_salary = None
        contract_season = None
        contract_total_value = None
        contract_years = None
        contract_expires = None

    injuries = a.get("injuries", [])
    if injuries:
        injury_status = injuries[0].get("status")  # CHANGED
    else:
        injury_status = None

    return (
        college,
        headshot_url,
        shoots_catches,  # NEW
        contract_salary,
        contract_season,
        contract_total_value,
        contract_years,
        contract_expires,
        injury_status,
    )


def extract_team_venue_fields(team_data):
    """Pull venue name and city out of an ESPN team dict.
    Nesting may vary by sport - falls back to None instead of erroring
    if a level of the structure isn't present."""
    franchise = team_data.get("franchise", {})
    venue_info = franchise.get("venue", team_data.get("venue", {}))
    venue = venue_info.get("fullName")
    city = venue_info.get("address", {}).get("city")
    return venue, city


def map_espn_status(status_type):
    """Translate ESPN's game status into one of the values games.status allows
    ('scheduled', 'in_progress', 'final', 'postponed', 'canceled').
    ESPN has many specific names (STATUS_HALFTIME, STATUS_END_PERIOD, ...),
    but every one also carries a simple state: 'pre', 'in', or 'post'."""
    name = status_type.get("name", "")
    if name == "STATUS_POSTPONED":
        return "postponed"
    if name in ("STATUS_CANCELED", "STATUS_CANCELLED"):
        return "canceled"
    state = status_type.get("state")
    if state == "in":
        return "in_progress"
    if state == "post":
        return "final"
    return "scheduled"


def extract_score(competitor):
    """ESPN gives scores as {"value": 23.0, "displayValue": "23"},
    or leaves the key out entirely before a game starts."""
    score = competitor.get("score")
    if isinstance(score, dict) and score.get("value") is not None:
        return int(score["value"])
    return None


# ESPN's numeric season types -> the values games.season_type allows
ESPN_SEASON_TYPES = {1: "preseason", 2: "regular", 3: "postseason"}


def pull_games(conn, league, sport_path, espn_team_id, our_team_id):
    """Pull one tracked team's preseason, regular-season, and postseason
    schedules from ESPN and upsert every game into games. The opponent is
    upserted into teams first (as an untracked team), so both home_team_id
    and away_team_id have a row to point at. Returns the number of games upserted."""
    game_count = 0
    for espn_season_type, season_type in ESPN_SEASON_TYPES.items():
        response = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/teams/{espn_team_id}/schedule",
            params={"seasontype": espn_season_type},
        )
        events = response.json().get("events", [])

        for event in events:
            competition = event["competitions"][0]

            # Look up (or create) a team_id for both sides of the game
            team_ids = {}
            scores = {}
            for competitor in competition["competitors"]:
                side = competitor["homeAway"]  # "home" or "away"
                team = competitor["team"]
                if team["id"] == espn_team_id:
                    team_ids[side] = our_team_id
                else:
                    team_ids[side] = upsert_opponent_team(
                        conn, league, team["id"], team["displayName"]
                    )
                scores[side] = extract_score(competitor)

            insert_game(
                conn,
                league,
                event["id"],
                event["season"]["year"],
                season_type,
                team_ids["home"],
                team_ids["away"],
                event["date"],
                map_espn_status(competition["status"]["type"]),
                home_score=scores["home"],
                away_score=scores["away"],
                venue_name=competition.get("venue", {}).get("fullName"),
                is_neutral_site=competition.get("neutralSite", False),
            )

        game_count += len(events)

    return game_count


def extract_linescores(competitor):
    """ESPN's per-period scores for one team, as a list of ints in order:
    regulation periods first, then any overtimes, then a shootout (NHL)."""
    return [
        int(float(line["displayValue"])) for line in competitor.get("linescores", [])
    ]


def build_periods(home_lines, away_lines, regulation_periods, is_shootout):
    """Turn two lists of per-period scores into game_periods rows of
    (period_number, period_type, home_score, away_score).
    Numbering restarts for each type: regulation 1..N, overtime 1..k,
    shootout 1 — so NBA double overtime is ('overtime', 1) and ('overtime', 2).
    ESPN doesn't label which entry is which, so it's worked out from the
    league's regulation period count (from sport_period_labels) and, for
    hockey, whether the game ended in a shootout (always the last entry)."""
    periods = []
    last_index = len(home_lines) - 1
    for index, (home, away) in enumerate(zip(home_lines, away_lines)):
        if index < regulation_periods:
            periods.append((index + 1, "regulation", home, away))
        elif is_shootout and index == last_index:
            periods.append((1, "shootout", home, away))
        else:
            periods.append((index - regulation_periods + 1, "overtime", home, away))
    return periods


def pull_game_periods(conn, sport_paths):
    """Fill in game_periods for every final game that doesn't have them yet.
    Uses ESPN's per-game summary endpoint (the schedule endpoint has no
    per-period scores) — one request per game, but only for games not
    already filled in, so a typical night is just the previous day's games.
    Returns the number of games filled in."""
    filled = 0
    for game_id, league, external_id, regulation_periods in get_games_missing_periods(
        conn
    ):
        response = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/{sport_paths[league]}/summary",
            params={"event": external_id},
        )
        competition = response.json()["header"]["competitions"][0]
        lines = {
            c["homeAway"]: extract_linescores(c) for c in competition["competitors"]
        }

        home_lines = lines.get("home", [])
        away_lines = lines.get("away", [])
        if not home_lines or len(home_lines) != len(away_lines):
            print(
                f"  No usable period scores for {league} game {external_id}, skipping"
            )
            continue

        is_shootout = "/SO" in competition["status"]["type"].get("detail", "")
        periods = build_periods(home_lines, away_lines, regulation_periods, is_shootout)
        insert_game_periods(conn, game_id, periods)
        filled += 1

    return filled


# Box score keys that hold playing time. They go into
# player_game_appearances.seconds_played rather than player_game_stats.
PLAYING_TIME_KEYS = {"minutes", "timeOnIce"}

# NFL box scores are split into stat categories (passing, rushing, defensive, ...)
# that reuse key names with different meanings — "interceptions" is thrown under
# passing but caught under defensive — so NFL stat names get the category as a
# prefix, e.g. "passing.interceptions". NHL groups are positions (forwards,
# goalies), and a player is only ever in one, so no prefix is needed there.
STAT_GROUP_PREFIX_LEAGUES = {"NFL"}


def parse_stat_value(raw):
    """Convert one box score value to a number.
    '14' -> 14.0, '+6' -> 6.0, '.923' -> 0.923, '12:50' -> 770 (seconds).
    Returns None for blanks like '--' or ''."""
    if ":" in raw:
        minutes, seconds = raw.split(":")
        return int(minutes) * 60 + int(seconds)
    try:
        return float(raw)
    except ValueError:
        return None


def parse_box_score(team_box, league):
    """Flatten one team's ESPN box score into
    {espn_athlete_id: {"name", "did_play", "seconds_played", "stats"}}.
    A player can appear in several stat groups (an NFL running back is under
    both rushing and receiving), so their stats are merged into one entry."""
    players = {}
    for group in team_box.get("statistics", []):
        prefix = f"{group['name']}." if league in STAT_GROUP_PREFIX_LEAGUES else ""
        for entry in group.get("athletes", []):
            athlete = entry["athlete"]
            player = players.setdefault(
                athlete["id"],
                {
                    "name": athlete["displayName"],
                    # Only basketball marks DNPs; for other sports everyone listed played
                    "did_play": not entry.get("didNotPlay"),
                    "seconds_played": None,
                    "stats": {},
                },
            )
            for key, raw in zip(group["keys"], entry.get("stats", [])):
                if key in PLAYING_TIME_KEYS:
                    value = parse_stat_value(raw)
                    if value is not None:
                        # Basketball gives whole minutes; hockey's MM:SS is already seconds
                        seconds = value * 60 if key == "minutes" else value
                        player["seconds_played"] = int(seconds)
                    continue
                if key.startswith("ytd"):  # season-to-date totals, not this game
                    continue

                # Paired stats like "fieldGoalsMade-fieldGoalsAttempted": "6-10"
                # or "completions/passingAttempts": "19/31" become two stats.
                names, values = [key], [raw]
                for separator in ("/", "-"):
                    if separator in key:
                        names, values = key.split(separator), raw.split(separator)
                        break
                if len(names) != len(values):
                    continue
                for name, value in zip(names, values):
                    number = parse_stat_value(value)
                    if number is not None:
                        player["stats"][prefix + name] = number
    return players


def pull_box_scores(conn, sport_paths):
    """Fill in player_game_appearances and player_game_stats for our team in
    every final game that doesn't have a box score yet, from ESPN's per-game
    summary endpoint. Only the tracked team's players are stored — opponents'
    players aren't in the players table. Returns the number of games filled in."""
    filled = 0
    for (
        game_id,
        league,
        external_id,
        our_team_id,
        our_espn_id,
    ) in get_games_missing_box_scores(conn):
        response = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/{sport_paths[league]}/summary",
            params={"event": external_id},
        )
        team_boxes = response.json().get("boxscore", {}).get("players", [])
        team_box = next((t for t in team_boxes if t["team"]["id"] == our_espn_id), None)
        parsed = parse_box_score(team_box, league) if team_box else {}
        if not parsed:
            print(f"  No box score for {league} game {external_id}, skipping")
            continue

        box_score = []
        for espn_athlete_id, player in parsed.items():
            player_id = upsert_box_score_player(
                conn, our_team_id, league, espn_athlete_id, player["name"]
            )
            box_score.append(
                (
                    player_id,
                    player["did_play"],
                    player["seconds_played"],
                    player["stats"],
                )
            )
        insert_box_score(conn, game_id, box_score)
        filled += 1

    return filled


# --- Pacers (NBA) ---
response = requests.get("https://api.balldontlie.io/nba/v1/teams", headers=headers)
teams = response.json()["data"]
pacers = [t for t in teams if t["full_name"] == "Indiana Pacers"][0]

# Extra ESPN call just for venue/city enrichment
response = requests.get(
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/11"
)
pacers_team_data = response.json()["team"]
pacers_venue, pacers_city = extract_team_venue_fields(pacers_team_data)

pacers_id = insert_team(
    conn,
    "NBA",
    str(pacers["id"]),
    pacers["full_name"],
    espn_id="11",
    venue=pacers_venue,
    city=pacers_city,
    founded_year=1967,
)
print(
    "Pacers inserted, team_id:",
    pacers_id,
    "| venue:",
    pacers_venue,
    "| city:",
    pacers_city,
)

# --- Pacers players (ESPN) ---
response = requests.get(
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/11/roster"
)
roster_data = response.json()
athletes = roster_data["athletes"]
print("Pacers roster size:", len(athletes))

for a in athletes:
    birth_place = a.get("birthPlace", {})
    (
        college,
        headshot_url,
        shoots_catches,
        contract_salary,
        contract_season,
        contract_total_value,
        contract_years,
        contract_expires,
        injury_status,
    ) = extract_espn_fields(a)
    player_id = insert_player(
        conn,
        pacers_id,
        "NBA",
        a["id"],
        a["fullName"],
        a["position"]["abbreviation"],
        height_inches=a.get("height"),
        weight_lbs=a.get("weight"),
        jersey_number=a.get("jersey"),
        birth_date=a.get("dateOfBirth", "").split("T")[0] or None,
        birth_city=birth_place.get("city"),
        birth_state=birth_place.get("state"),
        birth_country=birth_place.get("country"),
        experience_years=a.get("experience", {}).get("years"),
        status=a.get("status", {}).get("name"),
        college=college,
        headshot_url=headshot_url,
        shoots_catches=shoots_catches,
        contract_salary=contract_salary,
        contract_season=contract_season,
        contract_total_value=contract_total_value,
        contract_years=contract_years,
        contract_expires=contract_expires,
        injury_status=injury_status,
    )
    print(
        f"Inserted player_id {player_id}: {a['fullName']} ({a.get('status', {}).get('name')})"
    )

# --- Purdue (NCAAB) ---
response = requests.get("https://api.balldontlie.io/ncaab/v1/teams", headers=headers)
teams = response.json()["data"]
purdue = [t for t in teams if t["college"] == "Purdue"][0]

# ESPN's college basketball team endpoint doesn't return venue data,
# unlike NBA/NHL/NFL - hardcoded instead, same as founded_year
purdue_id = insert_team(
    conn,
    "NCAAB",
    str(purdue["id"]),
    purdue["full_name"],
    espn_id="2509",
    venue="Mackey Arena",
    city="West Lafayette",
    founded_year=1896,  # first season of Purdue men's basketball
)
print(
    "Purdue inserted, team_id:",
    purdue_id,
    "| venue: Mackey Arena",
    "| city: West Lafayette",
)

# --- Purdue players (ESPN) ---
response = requests.get(
    "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/2509/roster"
)
roster_data = response.json()
athletes = roster_data["athletes"]
print("Purdue roster size:", len(athletes))

for a in athletes:
    birth_place = a.get("birthPlace", {})
    (
        college,
        headshot_url,
        shoots_catches,
        contract_salary,
        contract_season,
        contract_total_value,
        contract_years,
        contract_expires,
        injury_status,
    ) = extract_espn_fields(a)
    player_id = insert_player(
        conn,
        purdue_id,
        "NCAAB",
        a["id"],
        a["fullName"],
        a["position"]["abbreviation"],
        height_inches=a.get("height"),
        weight_lbs=a.get("weight"),
        jersey_number=a.get("jersey"),
        birth_date=a.get("dateOfBirth", "").split("T")[0] or None,
        birth_city=birth_place.get("city"),
        birth_state=birth_place.get("state"),
        birth_country=birth_place.get("country"),
        experience_years=a.get("experience", {}).get("years"),
        status=a.get("status", {}).get("name"),
        college=college,
        headshot_url=headshot_url,
        shoots_catches=shoots_catches,
        contract_salary=contract_salary,
        contract_season=contract_season,
        contract_total_value=contract_total_value,
        contract_years=contract_years,
        contract_expires=contract_expires,
        injury_status=injury_status,
    )
    print(f"Inserted player_id {player_id}: {a['fullName']}")

# --- Red Wings (NHL) ---
response = requests.get("https://api-web.nhle.com/v1/club-schedule/DET/week/now")
red_wings_data = response.json()

# Extra ESPN call just for venue/city enrichment
response = requests.get(
    "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams/5"
)
red_wings_team_data = response.json()["team"]
red_wings_venue, red_wings_city = extract_team_venue_fields(red_wings_team_data)

red_wings_id = insert_team(
    conn,
    "NHL",
    "DET",
    "Detroit Red Wings",
    espn_id="5",
    venue=red_wings_venue,
    city=red_wings_city,
    founded_year=1926,
)
print(
    "Red Wings inserted, team_id:",
    red_wings_id,
    "| venue:",
    red_wings_venue,
    "| city:",
    red_wings_city,
)

# --- Red Wings players (ESPN) ---
response = requests.get(
    "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams/5/roster"
)
roster_data = response.json()
groups = roster_data["athletes"]
print("Number of position groups:", len(groups))

for group in groups:
    print(f"Group: {group['position']} ({len(group['items'])} players)")
    for a in group["items"]:
        birth_place = a.get("birthPlace", {})
        (
            college,
            headshot_url,
            shoots_catches,
            contract_salary,
            contract_season,
            contract_total_value,
            contract_years,
            contract_expires,
            injury_status,
        ) = extract_espn_fields(a)
        player_id = insert_player(
            conn,
            red_wings_id,
            "NHL",
            a["id"],
            a["fullName"],
            a["position"]["abbreviation"],
            height_inches=a.get("height"),
            weight_lbs=a.get("weight"),
            jersey_number=a.get("jersey"),
            birth_date=a.get("dateOfBirth", "").split("T")[0] or None,
            birth_city=birth_place.get("city"),
            birth_state=birth_place.get("state"),
            birth_country=birth_place.get("country"),
            experience_years=a.get("experience", {}).get("years"),
            status=a.get("status", {}).get("name"),
            college=college,
            headshot_url=headshot_url,
            shoots_catches=shoots_catches,
            contract_salary=contract_salary,
            contract_season=contract_season,
            contract_total_value=contract_total_value,
            contract_years=contract_years,
            contract_expires=contract_expires,
            injury_status=injury_status,
        )
        print(f"  Inserted player_id {player_id}: {a['fullName']}")

# --- Colts (NFL) ---
response = requests.get(
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/ind"
)
team_data = response.json()["team"]
colts_venue, colts_city = extract_team_venue_fields(team_data)

colts_id = insert_team(
    conn,
    "NFL",
    team_data["id"],
    team_data["displayName"],
    espn_id=team_data["id"],
    venue=colts_venue,
    city=colts_city,
    founded_year=1984,
)
print(
    "Colts inserted, team_id:", colts_id, "| venue:", colts_venue, "| city:", colts_city
)

# --- Colts players (ESPN) ---
response = requests.get(
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/ind/roster"
)
roster_data = response.json()
groups = roster_data["athletes"]
print("Number of position groups:", len(groups))

for group in groups:
    print(f"Group: {group['position']} ({len(group['items'])} players)")
    for a in group["items"]:
        birth_place = a.get("birthPlace", {})
        (
            college,
            headshot_url,
            shoots_catches,
            contract_salary,
            contract_season,
            contract_total_value,
            contract_years,
            contract_expires,
            injury_status,
        ) = extract_espn_fields(a)
        player_id = insert_player(
            conn,
            colts_id,
            "NFL",
            a["id"],
            a["fullName"],
            a["position"]["abbreviation"],
            height_inches=a.get("height"),
            weight_lbs=a.get("weight"),
            jersey_number=a.get("jersey"),
            birth_date=a.get("dateOfBirth", "").split("T")[0] or None,
            birth_city=birth_place.get("city"),
            birth_state=birth_place.get("state"),
            birth_country=birth_place.get("country"),
            experience_years=a.get("experience", {}).get("years"),
            status=a.get("status", {}).get("name"),
            college=college,
            headshot_url=headshot_url,
            shoots_catches=shoots_catches,
            contract_salary=contract_salary,
            contract_season=contract_season,
            contract_total_value=contract_total_value,
            contract_years=contract_years,
            contract_expires=contract_expires,
            injury_status=injury_status,
        )
        print(f"  Inserted player_id {player_id}: {a['fullName']}")

# --- Games (ESPN schedules) ---
# Runs after all four teams are inserted, since each game needs our team's team_id.
tracked_teams = [
    ("Pacers", "NBA", "basketball/nba", "11", pacers_id),
    ("Purdue", "NCAAB", "basketball/mens-college-basketball", "2509", purdue_id),
    ("Red Wings", "NHL", "hockey/nhl", "5", red_wings_id),
    ("Colts", "NFL", "football/nfl", "11", colts_id),
]
for label, league, sport_path, espn_team_id, our_team_id in tracked_teams:
    game_count = pull_games(conn, league, sport_path, espn_team_id, our_team_id)
    print(f"{label} games upserted: {game_count}")

# --- Game periods (ESPN per-game summaries) ---
# Runs after the games pull, so games that just went final get their periods.
sport_paths = {league: sport_path for _, league, sport_path, _, _ in tracked_teams}
periods_filled = pull_game_periods(conn, sport_paths)
print(f"Games with periods filled in: {periods_filled}")

# --- Player box scores (ESPN per-game summaries) ---
box_scores_filled = pull_box_scores(conn, sport_paths)
print(f"Games with box scores filled in: {box_scores_filled}")

conn.close()
