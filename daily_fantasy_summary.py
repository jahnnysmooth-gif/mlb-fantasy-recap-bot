import os
import time
import random
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
NY_TZ = ZoneInfo("America/New_York")

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
TRANSACTIONS_URL = "https://statsapi.mlb.com/api/v1/transactions"


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


def get_transactions_for_date(date_str):
    try:
        r = requests.get(
            TRANSACTIONS_URL,
            params={"sportId": 1, "date": date_str},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("transactions", [])
    except Exception as e:
        print(f"Transactions fetch failed for {date_str}: {e}")
        return []


def safe_int(value):
    try:
        return int(value or 0)
    except Exception:
        return 0


def safe_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


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
    pitchers = []

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

        innings_pitched = pitching.get("inningsPitched")
        strikeouts = safe_int(pitching.get("strikeOuts"))
        earned_runs = safe_int(pitching.get("earnedRuns"))
        wins = safe_int(pitching.get("wins"))
        losses = safe_int(pitching.get("losses"))
        hits_allowed = safe_int(pitching.get("hits"))
        walks = safe_int(pitching.get("baseOnBalls"))

        if innings_pitched:
            pitcher_score = (
                safe_float(innings_pitched) * 3
                + strikeouts * 2
                - earned_runs * 3
                - walks
                - hits_allowed * 0.5
                + wins * 2
                - losses * 2
            )

            pitchers.append(
                {
                    "name": name,
                    "team": team,
                    "ip": innings_pitched,
                    "k": strikeouts,
                    "er": earned_runs,
                    "h": hits_allowed,
                    "bb": walks,
                    "score": pitcher_score,
                }
            )

    statcast_notes = collect_statcast_notes(feed)

    return {
        "hitters": hitters,
        "multi_hr": multi_hr,
        "multi_sb": multi_sb,
        "saves": saves,
        "blown_saves": blown_saves,
        "pitchers": pitchers,
        "longest_hr": statcast_notes["longest_hr"],
        "hardest_hit": statcast_notes["hardest_hit"],
    }


def collect_statcast_notes(feed):
    plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])

    longest_hr = None
    hardest_hit = None

    for play in plays:
        matchup = play.get("matchup", {})
        batter = matchup.get("batter", {})
        batter_name = batter.get("fullName", "Unknown Player")

        result = play.get("result", {})
        event = (result.get("event") or "").lower()
        description = result.get("description", "")

        hit_data = play.get("hitData", {}) or play.get("playEvents", [{}])[-1].get("hitData", {}) or {}

        launch_speed = safe_float(hit_data.get("launchSpeed"))
        total_distance = safe_float(hit_data.get("totalDistance"))
        launch_angle = safe_float(hit_data.get("launchAngle"))

        if launch_speed > 0:
            candidate = {
                "name": batter_name,
                "ev": launch_speed,
                "distance": total_distance,
                "angle": launch_angle,
                "description": description,
            }
            if hardest_hit is None or candidate["ev"] > hardest_hit["ev"]:
                hardest_hit = candidate

        if "home_run" in event or event == "home run":
            candidate = {
                "name": batter_name,
                "ev": launch_speed,
                "distance": total_distance,
                "angle": launch_angle,
                "description": description,
            }
            if longest_hr is None or candidate["distance"] > longest_hr["distance"]:
                longest_hr = candidate

    return {
        "longest_hr": longest_hr,
        "hardest_hit": hardest_hit,
    }


def summarize_transactions(transactions):
    injury_keywords = [
        "injured list",
        "7-day injured list",
        "10-day injured list",
        "15-day injured list",
        "60-day injured list",
        "placed on il",
        "placed on the il",
        "placed on injured list",
        "reinstated",
        "returned from",
        "returned to roster",
        "rehab assignment",
        "medical emergency",
        "bereavement",
        "paternity",
        "restricted list",
        "suspended list",
    ]

    injury_items = []

    for tx in transactions:
        person = tx.get("person", {})
        player_name = person.get("fullName", "Unknown Player")

        to_team = tx.get("toTeam", {}) or {}
        from_team = tx.get("fromTeam", {}) or {}
        team_name = to_team.get("name") or from_team.get("name") or "Unknown Team"

        type_desc = tx.get("typeDesc", "") or ""
        description = tx.get("description", "") or ""
        resolution = tx.get("resolutionDate", "") or ""
        text_blob = f"{type_desc} {description}".lower()

        if any(keyword in text_blob for keyword in injury_keywords):
            injury_items.append(
                {
                    "name": player_name,
                    "team": team_name,
                    "type": type_desc.strip() or "Transaction",
                    "desc": description.strip(),
                    "date": resolution,
                }
            )

    seen = set()
    unique_items = []
    for item in injury_items:
        key = (item["name"], item["team"], item["type"], item["desc"])
        if key not in seen:
            seen.add(key)
            unique_items.append(item)

    return unique_items[:8]


def build_summary_data(date_str):
    games = get_schedule_for_date(date_str)
    transactions = get_transactions_for_date(date_str)

    all_hitters = []
    all_multi_hr = []
    all_multi_sb = []
    all_saves = []
    all_blown_saves = []
    all_pitchers = []
    longest_hr_candidates = []
    hardest_hit_candidates = []

    for game in games:
        game_pk = game.get("gamePk")
        status = game.get("status", {}).get("detailedState", "")

        if status not in {"Final", "Game Over", "Completed Early"}:
            continue

        try:
            feed = get_live_feed(game_pk)
            notes = collect_game_notes(feed)

            all_hitters.extend(notes["hitters"])
            all_multi_hr.extend(notes["multi_hr"])
            all_multi_sb.extend(notes["multi_sb"])
            all_saves.extend(notes["saves"])
            all_blown_saves.extend(notes["blown_saves"])
            all_pitchers.extend(notes["pitchers"])

            if notes["longest_hr"] is not None:
                longest_hr_candidates.append(notes["longest_hr"])

            if notes["hardest_hit"] is not None:
                hardest_hit_candidates.append(notes["hardest_hit"])

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

    all_pitchers.sort(
        key=lambda x: (x["score"], safe_float(x["ip"]), x["k"], -x["er"]),
        reverse=True,
    )

    longest_hr = None
    if longest_hr_candidates:
        longest_hr = max(longest_hr_candidates, key=lambda x: x["distance"])

    hardest_hit = None
    if hardest_hit_candidates:
        hardest_hit = max(hardest_hit_candidates, key=lambda x: x["ev"])

    injuries = summarize_transactions(transactions)

    return {
        "date": date_str,
        "top_hitters": all_hitters[:5],
        "multi_hr": all_multi_hr,
        "multi_sb": all_multi_sb,
        "saves": all_saves,
        "blown_saves": all_blown_saves,
        "best_pitchers": all_pitchers[:3],
        "longest_hr": longest_hr,
        "hardest_hit": hardest_hit,
        "injuries": injuries,
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


def fmt_best_pitchers(items):
    if not items:
        return "No notable pitching lines."

    lines = []
    for p in items:
        lines.append(
            f'• **{p["name"]}** ({p["team"]}): '
            f'{p["ip"]} IP, {p["k"]} K, {p["er"]} ER, {p["h"]} H, {p["bb"]} BB'
        )
    return "\n".join(lines)


def fmt_longest_hr(item):
    if not item:
        return "No home run distance data found."

    parts = [f'• **{item["name"]}**']
    if item["distance"] > 0:
        parts.append(f'{item["distance"]:.0f} ft')
    if item["ev"] > 0:
        parts.append(f'{item["ev"]:.1f} mph EV')
    if item["angle"] > 0:
        parts.append(f'{item["angle"]:.0f}° LA')

    return " — ".join(parts)


def fmt_hardest_hit(item):
    if not item:
        return "No hard-hit ball data found."

    parts = [f'• **{item["name"]}**']
    if item["ev"] > 0:
        parts.append(f'{item["ev"]:.1f} mph EV')
    if item["distance"] > 0:
        parts.append(f'{item["distance"]:.0f} ft')
    if item["angle"] > 0:
        parts.append(f'{item["angle"]:.0f}° LA')

    return " — ".join(parts)


def fmt_injuries(items):
    if not items:
        return "No notable injury-related transactions found."

    lines = []
    for item in items:
        detail = item["desc"] if item["desc"] else item["type"]
        lines.append(f'• **{item["name"]}** ({item["team"]}): {detail}')
    return "\n".join(lines)


def build_message_text(summary_data):
    date_obj = datetime.strptime(summary_data["date"], "%Y-%m-%d")
    pretty_date = date_obj.strftime("%A, %B %d, %Y").replace(" 0", " ")

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📋 **FANTASY RECAP — {pretty_date}**",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
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
        "⚾ **Longest HR of the Day**",
        fmt_longest_hr(summary_data["longest_hr"]),
        "",
        "💨 **Hardest Hit Ball**",
        fmt_hardest_hit(summary_data["hardest_hit"]),
        "",
        "🔥 **Best Pitching Lines**",
        fmt_best_pitchers(summary_data["best_pitchers"]),
        "",
        "🔒 **Saves**",
        fmt_simple_list(summary_data["saves"], "No saves recorded."),
        "",
        "🚨 **Blown Saves**",
        fmt_simple_list(summary_data["blown_saves"], "No blown saves recorded."),
        "",
        "🚑 **Injury / Transaction Notes**",
        fmt_injuries(summary_data["injuries"]),
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


def get_retry_after_seconds(response):
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except Exception:
            pass

    try:
        data = response.json()
        return float(data.get("retry_after", 60))
    except Exception:
        return 60.0


def post_to_discord(text, max_retries=6):
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
                retry_after = get_retry_after_seconds(r)
                buffer_seconds = 10 + (attempt * 15)
                jitter = random.randint(0, 10)
                wait_time = retry_after + buffer_seconds + jitter

                print("429 raw Retry-After header:", r.headers.get("Retry-After"))
                print("429 body preview:", r.text[:300])
                print(
                    f"Rate limited by Discord/Cloudflare. Waiting {wait_time:.1f} seconds "
                    f"(attempt {attempt + 1}/{max_retries})"
                )

                time.sleep(wait_time)
                continue

            print(f"Discord post failed: {r.status_code} - {r.text[:500]}")
            return False

        if not posted:
            print("Webhook stayed unavailable after all retries. Skipping remaining chunks.")
            return False

        if chunk_index < len(chunks):
            time.sleep(5)

    return True


def main():
    time.sleep(random.randint(5, 30))

    target_date = get_target_date()
    summary_data = build_summary_data(target_date)

    print(f"Fantasy recap date: {target_date}")
    print(f"Top hitters found: {len(summary_data['top_hitters'])}")
    print(f"Multi-HR games found: {len(summary_data['multi_hr'])}")
    print(f"Multi-SB games found: {len(summary_data['multi_sb'])}")
    print(f"Pitching lines found: {len(summary_data['best_pitchers'])}")
    print(f"Injury notes found: {len(summary_data['injuries'])}")

    message_text = build_message_text(summary_data)
    post_to_discord(message_text)


if __name__ == "__main__":
    main()
