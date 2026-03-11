import os
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
NY_TZ = ZoneInfo("America/New_York")

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

# Discord embed limits
EMBED_FIELD_VALUE_LIMIT = 1024
DISCORD_EMBED_COLOR = 0x1D82B6  # blue-ish


def get_target_date():
    """
    Use New York time so the recap lines up with your expected baseball day.
    """
    now_ny = datetime.now(NY_TZ)
    target_date = (now_ny - timedelta(days=1)).date()
    return target_date.isoformat()


def get_schedule_for_date(date_str):
    params = {
        "sportId": 1,
        "date": date_str,
        "hydrate": "linescore",
    }
    r = requests.get(SCHEDULE_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    games = []
    for date_block in data.get("dates", []):
        games.extend(date_block.get("games", []))
    return games


def get_live_feed(game_pk):
    url = LIVE_FEED_URL.format(game_pk=game_pk)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def safe_int(value):
    if value is None:
        return 0
    try:
        return int(value)
    except Exception:
        return 0


def team_name_from_player(player_data):
    current_team = player_data.get("currentTeam", {})
    return current_team.get("name", "Unknown Team")


def collect_game_notes(feed):
    boxscore = feed.get("liveData", {}).get("boxscore", {})
    teams = boxscore.get("teams", {})
    away_players = teams.get("away", {}).get("players", {})
    home_players = teams.get("home", {}).get("players", {})

    all_players = []
    all_players.extend(away_players.values())
    all_players.extend(home_players.values())

    hitters = []
    multi_hr = []
    multi_sb = []
    saves = []
    blown_saves = []

    for player in all_players:
        person = player.get("person", {})
        full_name = person.get("fullName", "Unknown Player")
        team_name = team_name_from_player(player)
        stats = player.get("stats", {})
        batting = stats.get("batting", {})
        pitching = stats.get("pitching", {})

        # Batting stats
        hits = safe_int(batting.get("hits"))
        hr = safe_int(batting.get("homeRuns"))
        rbi = safe_int(batting.get("rbi"))
        runs = safe_int(batting.get("runs"))
        sb = safe_int(batting.get("stolenBases"))

        # Fantasy-ish hitter ranking score
        # Keeps your top hitters section useful without being overly fancy
        hitter_score = (
            hr * 10
            + rbi * 3
            + runs * 2
            + sb * 5
            + hits * 1
        )

        if hits > 0 or hr > 0 or rbi > 0 or runs > 0 or sb > 0:
            hitters.append({
                "name": full_name,
                "team": team_name,
                "hr": hr,
                "rbi": rbi,
                "runs": runs,
                "sb": sb,
                "hits": hits,
                "score": hitter_score,
            })

        # HR notes: only 2+ HR
        if hr >= 2:
            multi_hr.append({
                "name": full_name,
                "team": team_name,
                "hr": hr,
                "rbi": rbi,
                "runs": runs,
                "hits": hits,
            })

        # SB notes: only 2+ SB
        if sb >= 2:
            multi_sb.append({
                "name": full_name,
                "team": team_name,
                "sb": sb,
                "runs": runs,
                "hits": hits,
            })

        # Pitching notes
        save_total = safe_int(pitching.get("saves"))
        blown_total = safe_int(pitching.get("blownSaves"))

        if save_total >= 1:
            saves.append({
                "name": full_name,
                "team": team_name,
            })

        if blown_total >= 1:
            blown_saves.append({
                "name": full_name,
                "team": team_name,
            })

    return hitters, multi_hr, multi_sb, saves, blown_saves


def build_summary_data(date_str):
    games = get_schedule_for_date(date_str)

    all_hitters = []
    all_multi_hr = []
    all_multi_sb = []
    all_saves = []
    all_blown_saves = []

    for game in games:
        game_pk = game.get("gamePk")
        status = game.get("status", {}).get("detailedState", "")

        # Skip games that never completed
        if status not in {"Final", "Game Over", "Completed Early"}:
            continue

        try:
            feed = get_live_feed(game_pk)
            hitters, multi_hr, multi_sb, saves, blown_saves = collect_game_notes(feed)
            all_hitters.extend(hitters)
            all_multi_hr.extend(multi_hr)
            all_multi_sb.extend(multi_sb)
            all_saves.extend(saves)
            all_blown_saves.extend(blown_saves)
        except Exception as e:
            print(f"Error processing game {game_pk}: {e}")

    # Top hitters: keep 5
    all_hitters.sort(
        key=lambda x: (
            x["score"],
            x["hr"],
            x["rbi"],
            x["sb"],
            x["runs"],
            x["hits"],
        ),
        reverse=True,
    )
    top_hitters = all_hitters[:5]

    # Multi-HR notes sorted by HR, then RBI, then runs
    all_multi_hr.sort(
        key=lambda x: (x["hr"], x["rbi"], x["runs"], x["hits"]),
        reverse=True,
    )

    # Multi-SB notes sorted by SB, then runs, then hits
    all_multi_sb.sort(
        key=lambda x: (x["sb"], x["runs"], x["hits"]),
        reverse=True,
    )

    return {
        "date": date_str,
        "top_hitters": top_hitters,
        "multi_hr": all_multi_hr,
        "multi_sb": all_multi_sb,
        "saves": all_saves,
        "blown_saves": all_blown_saves,
    }


def format_top_hitters(items):
    if not items:
        return "No notable hitter lines found."

    lines = []
    for p in items:
        parts = []
        if p["hr"] > 0:
            parts.append(f"{p['hr']} HR")
        if p["rbi"] > 0:
            parts.append(f"{p['rbi']} RBI")
        if p["runs"] > 0:
            parts.append(f"{p['runs']} R")
        if p["sb"] > 0:
            parts.append(f"{p['sb']} SB")
        if p["hits"] > 0:
            parts.append(f"{p['hits']} H")

        stat_line = ", ".join(parts) if parts else "No stats"
        lines.append(f"• **{p['name']}** ({p['team']}): {stat_line}")
    return "\n".join(lines)


def format_multi_hr(items):
    if not items:
        return "No multi-HR games."

    lines = []
    for p in items:
        parts = [f"{p['hr']} HR"]
        if p["rbi"] > 0:
            parts.append(f"{p['rbi']} RBI")
        if p["runs"] > 0:
            parts.append(f"{p['runs']} R")
        if p["hits"] > 0:
            parts.append(f"{p['hits']} H")

        lines.append(f"• **{p['name']}** ({p['team']}): {', '.join(parts)}")
    return "\n".join(lines)


def format_multi_sb(items):
    if not items:
        return "No multi-steal games."

    lines = []
    for p in items:
        parts = [f"{p['sb']} SB"]
        if p["runs"] > 0:
            parts.append(f"{p['runs']} R")
        if p["hits"] > 0:
            parts.append(f"{p['hits']} H")

        lines.append(f"• **{p['name']}** ({p['team']}): {', '.join(parts)}")
    return "\n".join(lines)


def format_saves(items):
    if not items:
        return "No saves recorded."

    lines = [f"• **{p['name']}** ({p['team']})" for p in items]
    return "\n".join(lines)


def format_blown_saves(items):
    if not items:
        return "No blown saves recorded."

    lines = [f"• **{p['name']}** ({p['team']})" for p in items]
    return "\n".join(lines)


def truncate_field(text, limit=EMBED_FIELD_VALUE_LIMIT):
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def build_discord_payload(summary_data):
    date_obj = datetime.strptime(summary_data["date"], "%Y-%m-%d")
    pretty_date = date_obj.strftime("%A, %B %-d, %Y")

    # Windows-safe fallback if %-d is unsupported
    if "%-d" in pretty_date:
        pretty_date = date_obj.strftime("%A, %B %d, %Y").replace(" 0", " ")

    top_hitters_text = truncate_field(format_top_hitters(summary_data["top_hitters"]))
    multi_hr_text = truncate_field(format_multi_hr(summary_data["multi_hr"]))
    multi_sb_text = truncate_field(format_multi_sb(summary_data["multi_sb"]))
    saves_text = truncate_field(format_saves(summary_data["saves"]))
    blown_saves_text = truncate_field(format_blown_saves(summary_data["blown_saves"]))

    embed = {
        "title": f"📋 Fantasy Recap — {pretty_date}",
        "description": "Daily MLB fantasy roundup from yesterday's games.",
        "color": DISCORD_EMBED_COLOR,
        "fields": [
            {
                "name": "🔥 Top Hitters",
                "value": top_hitters_text,
                "inline": False,
            },
            {
                "name": "💣 Multi-HR Games",
                "value": multi_hr_text,
                "inline": False,
            },
            {
                "name": "💨 Multi-SB Games",
                "value": multi_sb_text,
                "inline": False,
            },
            {
                "name": "🔒 Saves",
                "value": saves_text,
                "inline": False,
            },
            {
                "name": "🚨 Blown Saves",
                "value": blown_saves_text,
                "inline": False,
            },
        ],
        "footer": {
            "text": f"Recap date: {summary_data['date']}"
        },
    }

    return {"embeds": [embed]}


def post_to_discord(payload, max_retries=5):
    for attempt in range(max_retries):
        r = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=30,
        )

        if r.status_code in (200, 204):
            print("✅ Posted recap to Discord successfully.")
            return

        if r.status_code == 429:
            retry_after = 2.0
            try:
                data = r.json()
                retry_after = float(data.get("retry_after", 2))
            except Exception:
                pass

            wait_time = retry_after + 0.5
            print(f"⚠️ Discord rate limited the webhook. Waiting {wait_time} seconds...")
            time.sleep(wait_time)
            continue

        print(f"❌ Discord post failed: {r.status_code} - {r.text}")
        r.raise_for_status()

    raise RuntimeError("Failed to post to Discord after multiple retries.")


def main():
    target_date = get_target_date()
    summary_data = build_summary_data(target_date)

    print(f"📋 Fantasy Recap for {target_date}")
    print("🔥 Top hitters")
    for p in summary_data["top_hitters"]:
        print(
            f"- {p['name']} ({p['team']}): "
            f"{p['hr']} HR, {p['rbi']} RBI, {p['runs']} R, {p['sb']} SB, {p['hits']} H"
        )

    print("💣 Multi-HR games")
    for p in summary_data["multi_hr"]:
        print(f"- {p['name']} ({p['team']}): {p['hr']} HR, {p['rbi']} RBI")

    print("💨 Multi-SB games")
    for p in summary_data["multi_sb"]:
        print(f"- {p['name']} ({p['team']}): {p['sb']} SB")

    print("🔒 Saves")
    for p in summary_data["saves"]:
        print(f"- {p['name']} ({p['team']}): save")

    print("🚨 Blown saves")
    for p in summary_data["blown_saves"]:
        print(f"- {p['name']} ({p['team']}): blown save")

    payload = build_discord_payload(summary_data)
    post_to_discord(payload)


if __name__ == "__main__":
    main()
