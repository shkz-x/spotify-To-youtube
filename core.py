import csv
import json
import time
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from ytmusicapi import YTMusic

# --- Config ---
HEADERS = "browser.json"
STATE_FILE = "added.json"

LIKE_SONGS = True
SLEEP = 1.2

MIN_SCORE = 0.62
SEARCH_LIMIT = 8

RETRIES = 3
RETRY_DELAY = 3.0

AUTO_REUSE_BY_NAME = True  # avoid duplicates


# --- Text normalize ---
def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = s.replace("&", "and")
    s = re.sub(
        r"\b(original mix|extended mix|radio edit|club mix|edit|mix|remix)\b",
        "",
        s,
    )
    s = re.sub(r"[^\w\s\-']", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _tokens(s: str) -> set:
    return set(_norm(s).split())


def _overlap(a: str, b: str) -> float:
    A, B = _tokens(a), _tokens(b)
    if not A or not B:
        return 0.0
    return len(A & B) / max(len(A), len(B))


def _split_artists(s: str) -> List[str]:
    return [x.strip() for x in re.split(r",|&|and", (s or "").lower()) if x.strip()]


def _candidate_artist(cand: Dict[str, Any]) -> str:
    artists = cand.get("artists")
    if isinstance(artists, list) and artists and isinstance(artists[0], dict):
        return artists[0].get("name", "") or ""
    return cand.get("author", "") or ""


def _candidate_album(cand: Dict[str, Any]) -> str:
    alb = cand.get("album")
    if isinstance(alb, dict):
        return alb.get("name", "") or ""
    return alb if isinstance(alb, str) else ""


def score(title: str, artist: str, album: str, cand: Dict[str, Any]) -> float:
    c_title = cand.get("title", "") or ""
    c_artist = _candidate_artist(cand)
    c_album = _candidate_album(cand)

    t = _overlap(title, c_title)
    al = _overlap(album, c_album) if album and c_album else 0.0
    parts = _split_artists(artist)
    a = max((_overlap(p, c_artist) for p in parts), default=0.0)

    # strong electronic match
    if t >= 0.9 and (al >= 0.9 or a >= 0.5):
        return 1.0

    return (0.55 * t) + (0.40 * a) + (0.05 * al)


# --- Helpers ---
def retry(fn):
    last = None
    for _ in range(RETRIES):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(RETRY_DELAY)
    raise last


def load_state() -> Dict[str, Any]:
    p = Path(STATE_FILE)
    if not p.exists():
        return {"version": 1, "playlist_id": None, "playlist_name": None, "added": {}}
    with p.open("r", encoding="utf-8") as f:
        state = json.load(f)
    state.setdefault("version", 1)
    state.setdefault("playlist_id", None)
    state.setdefault("playlist_name", None)
    state.setdefault("added", {})
    return state


def save_state(state: Dict[str, Any]):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def read_csv(path: str) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_queries(track: Dict[str, str]) -> List[str]:
    q = []
    if track.get("ISRC"):
        q.append(track["ISRC"])

    song = track.get("Song", "") or ""
    artist = track.get("Artist", "") or ""
    album = track.get("Album", "") or ""

    if song and artist:
        q.append(f"{song} {artist}")
        q.append(f"{song} - {artist}")
    if song and artist and album:
        q.append(f"{song} {artist} {album}")
    if song:
        q.append(song)
    return q


def best_from_results(track: Dict[str, str], results: List[Dict[str, Any]]) -> Tuple[Optional[str], float]:
    best_vid, best_score = None, -1.0
    for c in results or []:
        vid = c.get("videoId")
        if not vid:
            continue
        s = score(
            track.get("Song", "") or "",
            track.get("Artist", "") or "",
            track.get("Album", "") or "",
            c,
        )
        if s > best_score:
            best_vid, best_score = vid, s
    return best_vid, best_score


def find_best_video(yt: YTMusic, track: Dict[str, str]) -> Optional[str]:
    # songs first
    best_vid, best_score = None, -1.0
    for q in build_queries(track):
        res = retry(lambda: yt.search(q, filter="songs", limit=SEARCH_LIMIT)) or []
        vid, sc = best_from_results(track, res)
        if vid and sc > best_score:
            best_vid, best_score = vid, sc
        if best_score >= 0.9:
            return best_vid
    if best_score >= MIN_SCORE:
        return best_vid

    # video fallback
    best_vid, best_score = None, -1.0
    for q in build_queries(track):
        res = retry(lambda: yt.search(q, filter="videos", limit=SEARCH_LIMIT)) or []
        vid, sc = best_from_results(track, res)
        if vid and sc > best_score:
            best_vid, best_score = vid, sc
    return best_vid if best_score >= MIN_SCORE else None


def pick_or_create_playlist(yt: YTMusic, state: Dict[str, Any], desired_name: str, dry_run: bool) -> Optional[str]:
    if dry_run:
        return None

    # use saved id
    pid = state.get("playlist_id")
    if pid:
        return pid

    # reuse by name
    if AUTO_REUSE_BY_NAME:
        pls = retry(lambda: yt.get_library_playlists(limit=200)) or []
        same = [p for p in pls if (p.get("title") or "").strip().lower() == desired_name.strip().lower()]
        if same:
            def _cnt(p):
                try:
                    return int(p.get("count", 0))
                except Exception:
                    return 0
            same.sort(key=_cnt, reverse=True)
            pid = same[0].get("playlistId")
            if pid:
                state["playlist_id"] = pid
                state["playlist_name"] = desired_name
                save_state(state)
                return pid

    # create playlist
    pid = retry(lambda: yt.create_playlist(desired_name, "My Playlist Name!"))
    state["playlist_id"] = pid
    state["playlist_name"] = desired_name
    save_state(state)
    return pid


# --- Main ---
def run_import(csv_path: str, dry_run: bool = False):
    yt = YTMusic(HEADERS)
    state = load_state()

    playlist_name = Path(csv_path).stem
    playlist_id = pick_or_create_playlist(yt, state, playlist_name, dry_run)

    tracks = read_csv(csv_path)
    total = len(tracks)

    added_state = state["added"]

    cnt_added = cnt_skipped = cnt_no_match = 0
    no_matches: List[str] = []

    for i, t in enumerate(tracks, start=1):
        song = t.get("Song")
        artist = t.get("Artist")
        print(f"[{i}/{total}] {song} - {artist}")

        key = t.get("Spotify Track Id") or t.get("ISRC") or f"{song}|{artist}"

        if key in added_state:
            print("  ↳ skipped (already added)")
            cnt_skipped += 1
            continue

        vid = find_best_video(yt, t)
        if not vid:
            print("  ↳ no match")
            cnt_no_match += 1
            no_matches.append(f"{song} - {artist}")
            continue

        if dry_run:
            print("  ↳ would add")
            continue

        # add to playlist
        retry(lambda: yt.add_playlist_items(playlist_id, [vid]))

        if LIKE_SONGS:
            try:
                retry(lambda: yt.rate_song(vid, "LIKE"))
            except Exception:
                pass

        added_state[key] = {"videoId": vid}
        save_state(state)

        print("  ↳ added")
        cnt_added += 1
        time.sleep(SLEEP)

    print("\n=== Summary ===")
    print(f"Added now: {cnt_added}")
    print(f"Skipped (state): {cnt_skipped}")
    print(f"No match: {cnt_no_match}")

    if no_matches:
        print("\n=== Songs NOT added (no match) ===")
        for s in no_matches:
            print(f"- {s}")
        print(f"\nTotal not added: {len(no_matches)}")
