import os
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ET = ZoneInfo("America/New_York")


def get_target_date():
    now_et = datetime.now(ET)
    target = now_et.date() - timedelta(days=1)
    return target.strftime("%Y-%m-%d")


def get_schedule(date_str):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


def get_boxscore(game_id):
    url = f"https://statsapi.mlb.com/api/v1/game/{game_id}/boxscore"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


def to_int(value):
    try:
        return int(value)
    except Exception:
        return 0


def to_float(value):
    try:
        return float(value)
    except Exception:
        return 0.0


def collect_hitters(players, team_name):
    rows = []

    for _, pdata in players.items():
        person = pdata.get("person", {})
        stats = pdata.get("stats", {}).get("batting", {})
        if not stats:
            continue

        ab = to_int(stats.get("atBats"))
        h = to_int(stats.get("hits"))
        hr = to_int(stats.get("homeRuns"))
        rbi = to_int(stats.get("rbi"))
        sb = to_int(stats.get("stolenBases"))
        runs = to_int(stats.get("runs"))

        if ab == 0 and h == 0 and hr == 0 and rbi == 0 and sb == 0 and runs == 0:
            continue

        score = hr * 6 + sb * 5 + rbi * 2 + runs + h

        rows.append({
            "name": person.get("fullName", "Unknown"),
            "team": team_name,
            "h": h,
            "hr": hr,
            "rbi": rbi,
            "sb": sb,
            "runs": runs,
            "score": score,
        })

    return rows


def collect_pitchers(players, team_name):
    starters = []
    relievers = []

    for _, pdata in players.items():
        person = pdata.get("person", {})
        stats = pdata.get("stats", {}).get("pitching", {})
        if not stats:
            continue

        ip = stats.get("inningsPitched", "0.0")
        so = to_int(stats.get("strikeOuts"))
        er = to_int(stats.get("earnedRuns"))
        wins = to_int(stats.get("wins"))
        saves = to_int(stats.get("saves"))
        blown = to_int(stats.get("blownSaves"))
        holds = to_int(stats.get("holds"))

        ip_f = to_float(ip)
        starter_score = ip_f * 2 + so * 1.5 - er * 2 + wins * 4

        if ip_f >= 5.0:
            starters.append({
                "name": person.get("fullName", "Unknown"),
                "team": team_name,
                "ip": ip,
                "so": so,
                "er": er,
                "wins": wins,
                "score": starter_score,
            })

        if saves > 0 or blown > 0 or holds > 0:
            relievers.append({
                "name": person.get("fullName", "Unknown"),
                "team": team_name,
                "saves": saves,
                "blown": blown,
                "holds": holds,
            })

    return starters, relievers


def build_summary(date_str):
    schedule = get_schedule(date_str)
    games = []

    for date_block in schedule.get("dates", []):
        games.extend(date_block.get("games", []))

    final_games = [
        g for g in games
        if g.get("status", {}).get("detailedState") in {"Final", "Game Over", "Completed Early"}
    ]

    if not final_games:
        return f"📋 **Fantasy Recap for {date_str}**\nNo final MLB games found."

    all_hitters = []
    all_starters = []
    all_relievers = []

    for game in final_games:
        game_id = game["gamePk"]
        box = get_boxscore(game_id)

        away = box.get("teams", {}).get("away", {})
        home = box.get("teams", {}).get("home", {})

        away_name = away.get("team", {}).get("name", "Away")
        home_name = home.get("team", {}).get("name", "Home")

        away_players = away.get("players", {})
        home_players = home.get("players", {})

        all_hitters.extend(collect_hitters(away_players, away_name))
        all_hitters.extend(collect_hitters(home_players, home_name))

        away_starters, away_relievers = collect_pitchers(away_players, away_name)
        home_starters, home_relievers = collect_pitchers(home_players, home_name)

        all_starters.extend(away_starters)
        all_starters.extend(home_starters)
        all_relievers.extend(away_relievers)
        all_relievers.extend(home_relievers)

    top_hitters = sorted(all_hitters, key=lambda x: x["score"], reverse=True)[:5]
    top_starters = sorted(all_starters, key=lambda x: x["score"], reverse=True)[:4]
    top_hr = [p for p in sorted(all_hitters, key=lambda x: x["hr"], reverse=True) if p["hr"] > 0][:5]
    top_sb = [p for p in sorted(all_hitters, key=lambda x: x["sb"], reverse=True) if p["sb"] > 0][:3]
    saves = [p for p in all_relievers if p["saves"] > 0][:6]
    blown = [p for p in all_relievers if p["blown"] > 0][:4]

    lines = [f"📋 **Fantasy Recap for {date_str}**", ""]

    if top_hitters:
        lines.append("🔥 **Top hitters**")
        for p in top_hitters:
            parts = []
            if p["hr"]:
                parts.append(f'{p["hr"]} HR')
            if p["rbi"]:
                parts.append(f'{p["rbi"]} RBI')
            if p["runs"]:
                parts.append(f'{p["runs"]} R')
            if p["sb"]:
                parts.append(f'{p["sb"]} SB')
            if p["h"]:
                parts.append(f'{p["h"]} H')
            lines.append(f'- {p["name"]} ({p["team"]}): ' + ", ".join(parts))
        lines.append("")

    if top_starters:
        lines.append("🎯 **Standout starters**")
        for p in top_starters:
            win_text = " W" if p["wins"] else ""
            lines.append(f'- {p["name"]} ({p["team"]}): {p["ip"]} IP, {p["so"]} K, {p["er"]} ER{win_text}')
        lines.append("")

    if top_hr:
        lines.append("💣 **Home run notes**")
        for p in top_hr:
            lines.append(f'- {p["name"]} ({p["team"]}): {p["hr"]} HR, {p["rbi"]} RBI')
        lines.append("")

    if top_sb:
        lines.append("💨 **Stolen base notes**")
        for p in top_sb:
            lines.append(f'- {p["name"]} ({p["team"]}): {p["sb"]} SB')
        lines.append("")

    if saves:
        lines.append("🔒 **Saves**")
        for p in saves:
            lines.append(f'- {p["name"]} ({p["team"]}): save')
        lines.append("")

    if blown:
        lines.append("🚨 **Blown saves**")
        for p in blown:
            lines.append(f'- {p["name"]} ({p["team"]}): blown save')
        lines.append("")

    message = "\n".join(lines).strip()
    if len(message) > 1900:
        message = message[:1900] + "\n\n...truncated"
    return message


def post_to_discord(content):
    r = requests.post(WEBHOOK_URL, json={"content": content}, timeout=20)
    r.raise_for_status()


def main():
    date_str = get_target_date()
    summary = build_summary(date_str)
    print(summary)
    post_to_discord(summary)


if __name__ == "__main__":
    main()