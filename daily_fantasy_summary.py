import os
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
NY_TZ = ZoneInfo("America/New_York")

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"


def get_target_date():
    now_ny = datetime.now(NY_TZ)
    return (now_ny - timedelta(days=1)).date().isoformat()


def get_schedule_for_date(date_str):
    r = requests.get(
        SCHEDULE_URL,
        params={"sportId": 1, "date": date_str},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()

    games = []
    for date_block in data.get("dates", []):
        games.extend(date_block.get("games", []))
    return games


def get_live_feed(game_pk):
    r = requests.get(LIVE_FEED_URL.format(game_pk=game_pk), timeout=30)
    r.raise_for_status()
    return r.json()


def safe_int(value):
    try:
        return int(value or 0)
    except Exception:
        return 0


def collect_game_notes(feed):
    boxscore = feed.get("liveData", {}).get("boxscore", {})
    teams = boxscore.get("teams", {})

    away_team_name = teams.get("away", {}).get("team", {}).get("name", "Away Team")
    home_team_name = teams.get("home", {}).get("team", {}).get("name", "Home Team")

    away_players = teams.get("away", {}).get("players", {})
    home_players = teams.get("home", {}).get("players", {})

    hitters = []
    multi_hr = []
    multi_sb = []
    saves = []
    blown_saves = []

    all_players = []

    for player in away_players.values():
        all_players.append((player, away_team_name))

    for player in home_players.values():
        all_players.append((player, home_team_name))

    for player, team in all_players:
        person = player.get("person", {})
        name = person.get("fullName", "Unknown Player")

        stats = player.get("stats", {})
        batting = stats.get("batting", {})
        pitching = stats.get("pitching", {})

        hits = safe_int(batting.get("hits"))
        hr = safe_int(batting.get("homeRuns"))
        rbi = safe_int(batting.get("rbi"))
        runs = safe_int(batting.get("runs"))
        sb = safe_int(batting.get("stolenBases"))

        score = (hr * 10) + (rbi * 3) + (runs * 2) + (sb * 5) + hits

        if hits > 0 or hr > 0 or rbi > 0 or runs > 0 or sb > 0:
            hitters.append(
                {
                    "name": name,
                    "team": team,
                    "hr": hr,
                    "rbi": rbi,
                    "runs": runs,
                    "sb": sb,
                    "hits": hits,
                    "score": score,
                }
            )

        if hr >= 2:
            multi_hr.append(
                {
                    "name": name,
                    "team": team,
                    "hr": hr,
                    "rbi": rbi,
                    "runs": runs,
                    "hits": hits,
                }
            )

        if sb >= 2:
            multi_sb.append(
                {
                    "name": name,
                    "team": team,
                    "sb": sb,
                    "runs": runs,
                    "hits": hits,
                }
            )

        if safe_int(pitching.get("saves")) >= 1:
            saves.append({"name": name, "team": team})

        if safe_int(pitching.get("blownSaves")) >= 1:
            blown_saves.append({"name": name, "team": team})

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

    all_hitters.sort(
        key=lambda x: (x["score"], x["hr"], x["rbi"], x["sb"], x["runs"], x["hits"]),
        reverse=True,
    )

    all_multi_hr.sort(
        key=lambda x: (x["hr"], x["rbi"], x["runs"], x["hits"]),
        reverse=True,
    )

    all_multi_sb.sort(
        key=lambda x: (x["sb"], x["runs"], x["hits"]),
        reverse=True,
    )

    return {
        "date": date_str,
        "top_hitters": all_hitters[:5],
        "multi_hr": all_multi_hr,
        "multi_sb": all_multi_sb,
        "saves": all_saves,
        "blown_saves": all_blown_saves,
    }


def fmt_top_hitters(items):
    if not items:
        return "No notable hitter lines found."

    lines = []
    for p in items:
        parts = []
        if p["hr"] > 0:
            parts.append(f'{p["hr"]} HR')
        if p["rbi"] > 0:
            parts.append(f'{p["rbi"]} RBI')
        if p["runs"] > 0:
            parts.append(f'{p["runs"]} R')
        if p["sb"] > 0:
            parts.append(f'{p["sb"]} SB')
        if p["hits"] > 0:
            parts.append(f'{p["hits"]} H')

        lines.append(f'• **{p["name"]}** ({p["team"]}): {", ".join(parts)}')

    return "\n".join(lines)


def fmt_multi_hr(items):
    if not items:
        return "No multi-HR games."

    lines = []
    for p in items:
        parts = [f'{p["hr"]} HR']
        if p["rbi"] > 0:
            parts.append(f'{p["rbi"]} RBI')
        if p["runs"] > 0:
            parts.append(f'{p["runs"]} R')
        if p["hits"] > 0:
            parts.append(f'{p["hits"]} H')

        lines.append(f'• **{p["name"]}** ({p["team"]}): {", ".join(parts)}')

    return "\n".join(lines)


def fmt_multi_sb(items):
    if not items:
        return "No multi-SB games."

    lines = []
    for p in items:
        parts = [f'{p["sb"]} SB']
        if p["runs"] > 0:
            parts.append(f'{p["runs"]} R')
        if p["hits"] > 0:
            parts.append(f'{p["hits"]} H')

        lines.append(f'• **{p["name"]}** ({p["team"]}): {", ".join(parts)}')

    return "\n".join(lines)


def fmt_simple_list(items, empty_text):
    if not items:
        return empty_text

    return "\n".join([f'• **{p["name"]}** ({p["team"]})' for p in items])


def build_message_text(summary_data):
    date_obj = datetime.strptime(summary_data["date"], "%Y-%m-%d")
    pretty_date = date_obj.strftime("%A, %B %d, %Y").replace(" 0", " ")

    lines = [
        "━━━━━━━━━━━━━━━━━━",
        f"📋 **FANTASY RECAP — {pretty_date}**",
        "━━━━━━━━━━━━━━━━━━",
        "",
        "🔥 **Top Hitters**",
        fmt_top_hitters(summary_data["top_hitters"]),
        "",
        "💣 **Multi-HR Games**",
        fmt_multi_hr(summary_data["multi_hr"]),
        "",
        "💨 **Multi-SB Games**",
        fmt_multi_sb(summary_data["multi_sb"]),
        "",
        "🔒 **Saves**",
        fmt_simple_list(summary_data["saves"], "No saves recorded."),
        "",
        "🚨 **Blown Saves**",
        fmt_simple_list(summary_data["blown_saves"], "No blown saves recorded."),
    ]

    return "\n".join(lines)


def split_message(text, limit=1900):
    chunks = []
    current = ""

    for line in text.splitlines():
        addition = line if not current else "\n" + line
        if len(current) + len(addition) > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current += addition

    if current:
        chunks.append(current)

    return chunks


def post_to_discord(text, max_retries=8):
    chunks = split_message(text)

    for chunk_index, chunk in enumerate(chunks, start=1):
        posted = False

        for attempt in range(max_retries):
            r = requests.post(
                DISCORD_WEBHOOK_URL,
                json={"content": chunk},
                timeout=30,
            )

            if r.status_code in (200, 204):
                print(f"Posted chunk {chunk_index}/{len(chunks)} successfully.")
                posted = True
                break

            if r.status_code == 429:
                retry_after = 2.0
                body = {}

                try:
                    body = r.json()
                    retry_after = float(body.get("retry_after", 2))
                except Exception:
                    pass

                print("429 body:", body if body else r.text)
                print(
                    "429 headers:",
                    {
                        "Retry-After": r.headers.get("Retry-After"),
                        "X-RateLimit-Scope": r.headers.get("X-RateLimit-Scope"),
                        "X-RateLimit-Global": r.headers.get("X-RateLimit-Global"),
                        "X-RateLimit-Bucket": r.headers.get("X-RateLimit-Bucket"),
                        "X-RateLimit-Remaining": r.headers.get("X-RateLimit-Remaining"),
                        "X-RateLimit-Reset-After": r.headers.get("X-RateLimit-Reset-After"),
                    },
                )

                wait_time = retry_after + 1.0
                print(
                    f"Rate limited by Discord. Waiting {wait_time} seconds... "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
                continue

            print(f"Discord post failed: {r.status_code} - {r.text}")
            return False

        if not posted:
            print("Discord webhook stayed rate limited after all retries. Skipping remaining chunks.")
            return False

        if chunk_index < len(chunks):
            time.sleep(1.25)

    return True


def main():
    target_date = get_target_date()
    summary_data = build_summary_data(target_date)

    print(f"Fantasy recap date: {target_date}")
    print(f"Top hitters found: {len(summary_data['top_hitters'])}")
    print(f"Multi-HR games found: {len(summary_data['multi_hr'])}")
    print(f"Multi-SB games found: {len(summary_data['multi_sb'])}")

    message_text = build_message_text(summary_data)
    post_to_discord(message_text)


if __name__ == "__main__":
    main()
