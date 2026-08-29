import os

import requests
from db import get_connection, insert_player, insert_team
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

conn.close()
