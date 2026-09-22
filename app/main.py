import io
import json
import math
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import qrcode
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("QUEST_DB_PATH", "/tmp/quest.db" if os.getenv("VERCEL") else BASE_DIR.parent / "quest.db"))
ADMIN_KEY = os.getenv("ADMIN_KEY")
GPS_RADIUS_M = 5
GPS_MAX_ACCURACY_M = 10
GPS_VERIFY_TTL_SECONDS = 180
MAX_LOGO_BYTES = 2 * 1024 * 1024

app = FastAPI(title="Sofia City Quest")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

MISSION_SET = [
    {
        "id": "crystal", "title": "1. Главата в Кристал", "place": "Градина „Кристал“ — паметникът на Стефан Стамболов",
        "lat": 42.69566, "lon": 23.32778, "radius": GPS_RADIUS_M, "difficulty": 1,
        "prompt": "Намерете модерния паметник с голяма бронзова глава. Въведете ФАМИЛИЯТА на човека, изписана върху паметника.",
        "hint": "Потърсете паметника на държавника, убит в София през XIX век. Името му започва със „С“.",
        "answers": ["СТАМБОЛОВ", "STAMBOLOV"],
    },
    {
        "id": "russian_church", "title": "2. Златните куполи", "place": "Руска църква „Св. Николай Мирликийски“",
        "lat": 42.69543, "lon": 23.32949, "radius": GPS_RADIUS_M, "difficulty": 2,
        "prompt": "Огледайте табелата/надписа с името на храма. Въведете само собственото име на светеца, на когото е посветен храмът.",
        "hint": "Името е същото като на един от най-популярните зимни светци в България.",
        "answers": ["НИКОЛАЙ", "NIKOLAI", "NICHOLAS"],
    },
    {
        "id": "alexander_nevsky", "title": "3. Храмът символ", "place": "Храм-паметник „Св. Александър Невски“",
        "lat": 42.69583, "lon": 23.33291, "radius": GPS_RADIUS_M, "difficulty": 3,
        "prompt": "Намерете името на храма на място. Въведете фамилното/второто име на светеца от надписа.",
        "hint": "Думата започва с „Н“ и е изписана в самото име на катедралата.",
        "answers": ["НЕВСКИ", "NEVSKI", "NEVSKY"],
    },
    {
        "id": "university", "title": "4. Патронът на университета", "place": "Софийски университет „Св. Климент Охридски“",
        "lat": 42.69355, "lon": 23.33553, "radius": GPS_RADIUS_M, "difficulty": 4,
        "prompt": "Погледнете името на университета върху/около сградата. Въведете само прозвището на св. Климент — една дума.",
        "hint": "То идва от името на град край Охридското езеро.",
        "answers": ["ОХРИДСКИ", "OHRIDSKI"],
    },
    {
        "id": "assembly", "title": "5. Признателна България", "place": "Паметник на Цар Освободител",
        "lat": 42.69453, "lon": 23.33151, "radius": GPS_RADIUS_M, "difficulty": 5,
        "prompt": "Прочетете големия надпис върху паметника. Въведете ПОСЛЕДНАТА дума от изречението „Царю Освободителю ...“.",
        "hint": "Това е името на държавата, от чието име е благодарността.",
        "answers": ["БЪЛГАРИЯ", "BULGARIA"],
    },
    {
        "id": "theatre", "title": "6. Кодът на театъра", "place": "Народен театър „Иван Вазов“",
        "lat": 42.69428, "lon": 23.32604, "radius": GPS_RADIUS_M, "difficulty": 6,
        "prompt": "На фасадата намерете името „ИВАН ВАЗОВ“. Кодът е броят на буквите в двете имена ОБЩО, без интервала. Въведете числото.",
        "hint": "Бройте буквите в „ИВАН“ и в „ВАЗОВ“, после ги съберете.",
        "answers": ["9", "ДЕВЕТ", "NINE"],
    },
    {
        "id": "archaeology", "title": "7. Музеят в старата джамия", "place": "Национален археологически институт с музей",
        "lat": 42.69655, "lon": 23.32462, "radius": GPS_RADIUS_M, "difficulty": 7,
        "prompt": "Открийте името/табелата на музея. Въведете думата, която описва вида на музея и започва с „А“.",
        "hint": "Там се пазят находки от минали епохи — търсената дума е „археологически“ тип, но въведете формата от името на институцията.",
        "answers": ["АРХЕОЛОГИЧЕСКИ", "АРХЕОЛОГИЧЕСКИМУЗЕЙ", "ARCHAEOLOGICAL"],
    },
    {
        "id": "rotunda", "title": "8. Сърцето на Константиновия квартал", "place": "Ротонда „Св. Георги“",
        "lat": 42.69642, "lon": 23.32294, "radius": GPS_RADIUS_M, "difficulty": 8,
        "prompt": "Намерете табелата/информацията за ротондата. Тя датира от края на III – началото на кой РИМСКИ век? Въведете само римската цифра.",
        "hint": "След III идва следващата римска цифра. Отговорът е две букви.",
        "answers": ["IV", "4", "ЧЕТВЪРТИ"],
    },
    {
        "id": "serdica", "title": "9. Град под града", "place": "Античен комплекс „Сердика“ — Ларгото",
        "lat": 42.69788, "lon": 23.32222, "radius": GPS_RADIUS_M, "difficulty": 9,
        "prompt": "Слезте/погледнете към археологическия комплекс. Открийте името на античния град. Въведете латинската му форма със 7 букви.",
        "hint": "Името е същото като на комплекса, но на латиница.",
        "answers": ["SERDICA", "СЕРДИКА"],
    },
    {
        "id": "mineral_baths", "title": "10. Финалният код на минералната баня", "place": "Централна минерална баня / Регионален исторически музей – София",
        "lat": 42.69949, "lon": 23.32218, "radius": GPS_RADIUS_M, "difficulty": 10,
        "prompt": "Намерете годината, свързана с откриването/завършването на Централната минерална баня на място. Финалният код е СБОРЪТ на четирите цифри на годината. Въведете само числото.",
        "hint": "Годината е 19_3. Открийте липсващата цифра на място и после съберете всички четири цифри.",
        "answers": ["14", "ЧЕТИРИНАДЕСЕТ", "FOURTEEN"],
    },
]

# Разместването е ограничено до близки точки, за да останат маршрутите приблизително равни.
ROUTE_VARIANTS = [
    ["crystal", "russian_church", "alexander_nevsky", "university", "assembly", "theatre", "archaeology", "rotunda", "serdica", "mineral_baths"],
    ["crystal", "russian_church", "assembly", "alexander_nevsky", "university", "theatre", "rotunda", "archaeology", "serdica", "mineral_baths"],
    ["crystal", "russian_church", "alexander_nevsky", "assembly", "university", "theatre", "archaeology", "rotunda", "mineral_baths", "serdica"],
    ["crystal", "russian_church", "assembly", "university", "alexander_nevsky", "theatre", "rotunda", "archaeology", "mineral_baths", "serdica"],
]
MISSION_BY_ID = {m["id"]: m for m in MISSION_SET}


def now_dt():
    return datetime.now(timezone.utc)


def now_iso():
    return now_dt().isoformat()


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def table_columns(con, table):
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}


def add_column_if_missing(con, table, column, sql_type):
    if column not in table_columns(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = db()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS competitions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS teams(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          competition_id INTEGER,
          name TEXT NOT NULL,
          token TEXT UNIQUE NOT NULL,
          join_code TEXT UNIQUE NOT NULL,
          route_variant INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(competition_id) REFERENCES competitions(id)
        );
        CREATE TABLE IF NOT EXISTS players(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          team_id INTEGER NOT NULL,
          name TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS games(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          team_id INTEGER UNIQUE NOT NULL,
          started_at TEXT,
          finished_at TEXT,
          current_index INTEGER NOT NULL DEFAULT 0,
          penalty_seconds INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'ready',
          FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS mission_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          team_id INTEGER NOT NULL,
          mission_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          value TEXT,
          lat REAL,
          lon REAL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_mission_events_team ON mission_events(team_id, mission_id);
        CREATE INDEX IF NOT EXISTS idx_mission_events_created ON mission_events(team_id, created_at);
        """
    )
    add_column_if_missing(con, "competitions", "organizer_token", "TEXT")
    add_column_if_missing(con, "competitions", "status", "TEXT DEFAULT 'lobby'")
    add_column_if_missing(con, "competitions", "started_at", "TEXT")
    add_column_if_missing(con, "teams", "logo_blob", "BLOB")
    add_column_if_missing(con, "teams", "logo_mime", "TEXT")
    add_column_if_missing(con, "mission_events", "accuracy_m", "REAL")
    add_column_if_missing(con, "mission_events", "flagged", "INTEGER DEFAULT 0")
    con.execute("UPDATE competitions SET status='lobby' WHERE status IS NULL OR status='' ")
    con.commit()
    con.close()


init_db()


class CreateTeam(BaseModel):
    team_name: str = Field(min_length=2, max_length=60)
    players: List[str] = Field(default_factory=list)
    mode: str = "fun"
    competition_code: Optional[str] = None
    competition_name: Optional[str] = None


class TokenBody(BaseModel):
    token: str


class OrganizerBody(BaseModel):
    organizer_token: str


class LocationBody(BaseModel):
    token: str
    lat: float
    lon: float
    accuracy_m: Optional[float] = None


class AnswerBody(BaseModel):
    token: str
    answer: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    accuracy_m: Optional[float] = None


def make_code(n=6):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def normalize(s: str):
    s = s.upper().strip()
    return re.sub(r"[^A-ZА-Я0-9]+", "", s)


def haversine(lat1, lon1, lat2, lon2):
    radius = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def team_from_token(con, token):
    row = con.execute("SELECT * FROM teams WHERE token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(401, "Невалиден отборен токен.")
    return row


def competition_from_organizer(con, token):
    row = con.execute("SELECT * FROM competitions WHERE organizer_token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(401, "Невалиден организаторски токен.")
    return row


def route_for(team):
    return ROUTE_VARIANTS[team["route_variant"] % len(ROUTE_VARIANTS)]


def current_mission(team, game):
    route = route_for(team)
    idx = min(game["current_index"], len(route) - 1)
    return MISSION_BY_ID[route[idx]]


def elapsed_seconds(game):
    if not game["started_at"]:
        return 0
    start = datetime.fromisoformat(game["started_at"])
    end = datetime.fromisoformat(game["finished_at"]) if game["finished_at"] else now_dt()
    return max(0, int((end - start).total_seconds())) + int(game["penalty_seconds"] or 0)


def add_event(con, team_id, mission_id, event_type, value=None, lat=None, lon=None, accuracy_m=None, flagged=0):
    con.execute(
        "INSERT INTO mission_events(team_id,mission_id,event_type,value,lat,lon,accuracy_m,flagged,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (team_id, mission_id, event_type, value, lat, lon, accuracy_m, flagged, now_iso()),
    )


def validate_live_location(con, team, mission, lat, lon, accuracy_m, event_prefix="location"):
    if lat is None or lon is None:
        return {"ok": False, "reason": "missing", "distance_m": None, "accuracy_m": accuracy_m}

    accuracy = float(accuracy_m) if accuracy_m is not None else 9999.0
    distance = haversine(lat, lon, mission["lat"], mission["lon"])
    event_type = f"{event_prefix}_far"
    flagged = 0
    reason = "far"

    if accuracy > GPS_MAX_ACCURACY_M:
        event_type = f"{event_prefix}_low_accuracy"
        reason = "accuracy"
    else:
        previous = con.execute(
            "SELECT lat,lon,created_at FROM mission_events WHERE team_id=? AND lat IS NOT NULL AND lon IS NOT NULL ORDER BY id DESC LIMIT 1",
            (team["id"],),
        ).fetchone()
        if previous:
            try:
                dt = max(0.1, (now_dt() - datetime.fromisoformat(previous["created_at"])).total_seconds())
                moved = haversine(previous["lat"], previous["lon"], lat, lon)
                speed = moved / dt
                if moved > 80 and speed > 15:
                    event_type = f"{event_prefix}_suspicious_speed"
                    reason = "speed"
                    flagged = 1
                elif distance <= mission["radius"]:
                    event_type = f"{event_prefix}_ok"
                    reason = "ok"
            except Exception:
                if distance <= mission["radius"]:
                    event_type = f"{event_prefix}_ok"
                    reason = "ok"
        elif distance <= mission["radius"]:
            event_type = f"{event_prefix}_ok"
            reason = "ok"

    add_event(
        con, team["id"], mission["id"], event_type,
        value=json.dumps({"distance_m": round(distance, 1), "radius_m": mission["radius"]}, ensure_ascii=False),
        lat=lat, lon=lon, accuracy_m=accuracy, flagged=flagged,
    )
    return {
        "ok": event_type.endswith("_ok"),
        "reason": reason,
        "distance_m": round(distance, 1),
        "required_m": mission["radius"],
        "accuracy_m": round(accuracy, 1),
        "max_accuracy_m": GPS_MAX_ACCURACY_M,
    }


def recent_location_verified(con, team_id, mission_id):
    row = con.execute(
        "SELECT created_at FROM mission_events WHERE team_id=? AND mission_id=? AND event_type IN ('location_ok','answer_location_ok') ORDER BY id DESC LIMIT 1",
        (team_id, mission_id),
    ).fetchone()
    if not row:
        return False
    try:
        return now_dt() - datetime.fromisoformat(row["created_at"]) <= timedelta(seconds=GPS_VERIFY_TTL_SECONDS)
    except Exception:
        return False


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/play", response_class=HTMLResponse)
def play(request: Request):
    return templates.TemplateResponse("play.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
def leaderboard_page(request: Request):
    return templates.TemplateResponse("leaderboard.html", {"request": request})


@app.get("/organizer", response_class=HTMLResponse)
def organizer_page(request: Request):
    return templates.TemplateResponse("organizer.html", {"request": request})


@app.post("/api/teams")
def create_team(payload: CreateTeam):
    con = db()
    try:
        competition_id = None
        competition_code = None
        organizer_token = None
        if payload.mode == "race":
            if payload.competition_code:
                c = con.execute("SELECT * FROM competitions WHERE code=?", (payload.competition_code.upper().strip(),)).fetchone()
                if not c:
                    raise HTTPException(404, "Няма състезание с този код.")
                if c["status"] != "lobby":
                    raise HTTPException(409, "Това състезание вече е стартирало и не приема нови отбори.")
                competition_id = c["id"]
                competition_code = c["code"]
            else:
                competition_code = make_code(6)
                organizer_token = secrets.token_urlsafe(32)
                cname = (payload.competition_name or "City Quest Race").strip()[:80]
                cur = con.execute(
                    "INSERT INTO competitions(code,name,organizer_token,status,created_at) VALUES (?,?,?,?,?)",
                    (competition_code, cname, organizer_token, "lobby", now_iso()),
                )
                competition_id = cur.lastrowid

        token = secrets.token_urlsafe(24)
        join_code = make_code(6)
        if competition_id:
            existing = con.execute("SELECT COUNT(*) c FROM teams WHERE competition_id=?", (competition_id,)).fetchone()["c"]
        else:
            existing = con.execute("SELECT COUNT(*) c FROM teams WHERE competition_id IS NULL").fetchone()["c"]
        route_variant = existing % len(ROUTE_VARIANTS)
        cur = con.execute(
            "INSERT INTO teams(competition_id,name,token,join_code,route_variant,created_at) VALUES (?,?,?,?,?,?)",
            (competition_id, payload.team_name.strip(), token, join_code, route_variant, now_iso()),
        )
        team_id = cur.lastrowid
        clean_players = [p.strip() for p in payload.players if p.strip()][:20]
        for p in clean_players:
            con.execute("INSERT INTO players(team_id,name,created_at) VALUES (?,?,?)", (team_id, p[:60], now_iso()))
        con.execute("INSERT INTO games(team_id,status) VALUES (?,?)", (team_id, "ready"))
        con.commit()
        return {
            "token": token,
            "team_id": team_id,
            "join_code": join_code,
            "competition_code": competition_code,
            "route_variant": route_variant + 1,
            "organizer_token": organizer_token,
        }
    finally:
        con.close()


@app.post("/api/team-logo")
async def upload_team_logo(token: str, file: UploadFile = File(...)):
    con = db()
    try:
        team = team_from_token(con, token)
        data = await file.read(MAX_LOGO_BYTES + 1)
        if len(data) > MAX_LOGO_BYTES:
            raise HTTPException(413, "Снимката трябва да е до 2 MB.")
        content_type = (file.content_type or "").lower()
        allowed = {"image/jpeg", "image/png", "image/webp"}
        if content_type not in allowed:
            raise HTTPException(400, "Разрешени са JPG, PNG и WEBP снимки.")
        signatures_ok = (
            (content_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
            or (content_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
            or (content_type == "image/webp" and len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        )
        if not signatures_ok:
            raise HTTPException(400, "Файлът не изглежда като валидно изображение.")
        con.execute("UPDATE teams SET logo_blob=?, logo_mime=? WHERE id=?", (data, content_type, team["id"]))
        con.commit()
        return {"ok": True, "logo_url": f"/api/team-logo/{team['id']}"}
    finally:
        con.close()


@app.get("/api/team-logo/{team_id}")
def team_logo(team_id: int):
    con = db()
    try:
        row = con.execute("SELECT logo_blob,logo_mime FROM teams WHERE id=?", (team_id,)).fetchone()
        if not row or not row["logo_blob"]:
            raise HTTPException(404, "Няма снимка.")
        return Response(content=row["logo_blob"], media_type=row["logo_mime"], headers={"Cache-Control": "public, max-age=3600"})
    finally:
        con.close()


@app.post("/api/start")
def start_game(payload: TokenBody):
    con = db()
    try:
        team = team_from_token(con, payload.token)
        game = con.execute("SELECT * FROM games WHERE team_id=?", (team["id"],)).fetchone()
        if team["competition_id"]:
            comp = con.execute("SELECT * FROM competitions WHERE id=?", (team["competition_id"],)).fetchone()
            if comp["status"] != "running":
                raise HTTPException(409, "Изчакайте организаторът да стартира състезанието.")
            if not game["started_at"]:
                con.execute("UPDATE games SET started_at=?, status='running' WHERE team_id=?", (comp["started_at"], team["id"]))
                con.commit()
        elif not game["started_at"]:
            con.execute("UPDATE games SET started_at=?, status='running' WHERE team_id=?", (now_iso(), team["id"]))
            con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/competition/start")
def start_competition(payload: OrganizerBody):
    con = db()
    try:
        comp = competition_from_organizer(con, payload.organizer_token)
        if comp["status"] == "running":
            return {"ok": True, "started_at": comp["started_at"], "already_started": True}
        stamp = now_iso()
        con.execute("UPDATE competitions SET status='running', started_at=? WHERE id=?", (stamp, comp["id"]))
        con.execute(
            "UPDATE games SET started_at=?, status='running' WHERE team_id IN (SELECT id FROM teams WHERE competition_id=?) AND started_at IS NULL",
            (stamp, comp["id"]),
        )
        con.commit()
        return {"ok": True, "started_at": stamp, "already_started": False}
    finally:
        con.close()


@app.get("/api/state")
def state(token: str):
    con = db()
    try:
        team = team_from_token(con, token)
        game = con.execute("SELECT * FROM games WHERE team_id=?", (team["id"],)).fetchone()
        players = [r["name"] for r in con.execute("SELECT name FROM players WHERE team_id=? ORDER BY id", (team["id"],))]
        comp = None
        if team["competition_id"]:
            comp = con.execute("SELECT * FROM competitions WHERE id=?", (team["competition_id"],)).fetchone()
        mission = None
        hint_used = False
        loc_verified = False
        if game["status"] != "finished":
            mission = current_mission(team, game)
            hint_used = bool(
                con.execute(
                    "SELECT 1 FROM mission_events WHERE team_id=? AND mission_id=? AND event_type='hint' LIMIT 1",
                    (team["id"], mission["id"]),
                ).fetchone()
            )
            loc_verified = recent_location_verified(con, team["id"], mission["id"])
        return {
            "team": {
                "id": team["id"],
                "name": team["name"],
                "join_code": team["join_code"],
                "players": players,
                "logo_url": f"/api/team-logo/{team['id']}" if team["logo_blob"] else None,
                "competition_code": comp["code"] if comp else None,
                "competition_name": comp["name"] if comp else None,
                "competition_status": comp["status"] if comp else None,
            },
            "game": {
                "status": game["status"],
                "started_at": game["started_at"],
                "finished_at": game["finished_at"],
                "current_index": game["current_index"],
                "total": 10,
                "penalty_seconds": game["penalty_seconds"],
                "elapsed_seconds": elapsed_seconds(game),
            },
            "mission": None if not mission else {k: v for k, v in mission.items() if k not in ("answers", "hint")},
            "hint_used": hint_used,
            "location_verified": loc_verified,
            "gps": {"radius_m": GPS_RADIUS_M, "max_accuracy_m": GPS_MAX_ACCURACY_M, "verification_ttl_seconds": GPS_VERIFY_TTL_SECONDS},
        }
    finally:
        con.close()


@app.post("/api/location/ping")
def location_ping(payload: LocationBody):
    con = db()
    try:
        team = team_from_token(con, payload.token)
        game = con.execute("SELECT * FROM games WHERE team_id=?", (team["id"],)).fetchone()
        if game["status"] != "running":
            raise HTTPException(400, "Играта не е активна.")
        accuracy = float(payload.accuracy_m) if payload.accuracy_m is not None else 9999.0
        flagged = 0
        event_type = "location_ping"
        previous = con.execute(
            "SELECT lat,lon,accuracy_m,created_at FROM mission_events WHERE team_id=? AND lat IS NOT NULL AND lon IS NOT NULL ORDER BY id DESC LIMIT 1",
            (team["id"],),
        ).fetchone()
        if previous and accuracy <= GPS_MAX_ACCURACY_M and (previous["accuracy_m"] is None or previous["accuracy_m"] <= GPS_MAX_ACCURACY_M):
            try:
                dt = max(0.1, (now_dt() - datetime.fromisoformat(previous["created_at"])).total_seconds())
                moved = haversine(previous["lat"], previous["lon"], payload.lat, payload.lon)
                if moved > 80 and moved / dt > 15:
                    flagged = 1
                    event_type = "location_ping_suspicious_speed"
            except Exception:
                pass
        mission = current_mission(team, game)
        add_event(con, team["id"], mission["id"], event_type, lat=payload.lat, lon=payload.lon, accuracy_m=accuracy, flagged=flagged)
        con.commit()
        return {"ok": True, "flagged": bool(flagged)}
    finally:
        con.close()


@app.post("/api/location")
def check_location(payload: LocationBody):
    con = db()
    try:
        team = team_from_token(con, payload.token)
        game = con.execute("SELECT * FROM games WHERE team_id=?", (team["id"],)).fetchone()
        if game["status"] != "running":
            raise HTTPException(400, "Играта не е активна.")
        mission = current_mission(team, game)
        result = validate_live_location(con, team, mission, payload.lat, payload.lon, payload.accuracy_m, "location")
        con.commit()
        return result
    finally:
        con.close()


@app.post("/api/hint")
def hint(payload: TokenBody):
    con = db()
    try:
        team = team_from_token(con, payload.token)
        game = con.execute("SELECT * FROM games WHERE team_id=?", (team["id"],)).fetchone()
        if game["status"] != "running":
            raise HTTPException(400, "Играта не е активна.")
        mission = current_mission(team, game)
        used = con.execute(
            "SELECT 1 FROM mission_events WHERE team_id=? AND mission_id=? AND event_type='hint' LIMIT 1",
            (team["id"], mission["id"]),
        ).fetchone()
        if not used:
            con.execute("UPDATE games SET penalty_seconds=penalty_seconds+300 WHERE team_id=?", (team["id"],))
            add_event(con, team["id"], mission["id"], "hint", "+300")
            con.commit()
        return {"hint": mission["hint"], "penalty_added": 0 if used else 300}
    finally:
        con.close()


@app.post("/api/answer")
def answer(payload: AnswerBody):
    con = db()
    try:
        team = team_from_token(con, payload.token)
        game = con.execute("SELECT * FROM games WHERE team_id=?", (team["id"],)).fetchone()
        if game["status"] != "running":
            raise HTTPException(400, "Играта не е активна.")
        mission = current_mission(team, game)

        # При подаване на отговор се прави нова GPS проверка. Старо location_ok не е достатъчно.
        loc = validate_live_location(con, team, mission, payload.lat, payload.lon, payload.accuracy_m, "answer_location")
        if not loc["ok"]:
            con.commit()
            if loc["reason"] == "accuracy":
                raise HTTPException(403, f"GPS точността е {loc['accuracy_m']} м. Изчакайте да стане ≤ {GPS_MAX_ACCURACY_M} м.")
            if loc["reason"] == "speed":
                raise HTTPException(403, "GPS движението изглежда неестествено. Изчакайте няколко секунди и проверете отново.")
            raise HTTPException(403, f"Трябва да сте в радиус {GPS_RADIUS_M} м от точката. В момента сте на около {loc['distance_m']} м.")

        good = normalize(payload.answer) in {normalize(x) for x in mission["answers"]}
        add_event(
            con, team["id"], mission["id"], "answer_ok" if good else "answer_wrong",
            payload.answer[:120], payload.lat, payload.lon, payload.accuracy_m,
        )
        if good:
            next_index = game["current_index"] + 1
            if next_index >= 10:
                con.execute("UPDATE games SET current_index=10, finished_at=?, status='finished' WHERE team_id=?", (now_iso(), team["id"]))
            else:
                con.execute("UPDATE games SET current_index=? WHERE team_id=?", (next_index, team["id"]))
        con.commit()
        return {"ok": good, "finished": good and game["current_index"] + 1 >= 10}
    finally:
        con.close()


@app.get("/api/leaderboard")
def leaderboard(competition_code: Optional[str] = None):
    con = db()
    try:
        params = []
        where = ""
        if competition_code:
            where = "WHERE c.code=?"
            params = [competition_code.upper().strip()]
        rows = con.execute(
            f"""
            SELECT t.id team_id,t.name team_name,t.logo_blob IS NOT NULL has_logo,c.code competition_code,
                   g.status,g.started_at,g.finished_at,g.current_index,g.penalty_seconds
            FROM teams t JOIN games g ON g.team_id=t.id
            LEFT JOIN competitions c ON c.id=t.competition_id
            {where}
            """,
            params,
        ).fetchall()
        out = []
        for r in rows:
            e = elapsed_seconds(r)
            out.append(
                {
                    "team_id": r["team_id"],
                    "team_name": r["team_name"],
                    "logo_url": f"/api/team-logo/{r['team_id']}" if r["has_logo"] else None,
                    "competition_code": r["competition_code"],
                    "status": r["status"],
                    "completed": r["current_index"],
                    "penalty_seconds": r["penalty_seconds"],
                    "elapsed_seconds": e,
                }
            )
        out.sort(key=lambda x: (0 if x["status"] == "finished" else 1, x["elapsed_seconds"] if x["status"] == "finished" else -x["completed"], x["penalty_seconds"]))
        return out
    finally:
        con.close()


@app.get("/api/organizer/state")
def organizer_state(token: str):
    con = db()
    try:
        comp = competition_from_organizer(con, token)
        teams = con.execute(
            """
            SELECT t.id,t.name,t.route_variant,t.logo_blob IS NOT NULL has_logo,g.status,g.current_index,g.started_at,g.finished_at,g.penalty_seconds
            FROM teams t JOIN games g ON g.team_id=t.id
            WHERE t.competition_id=? ORDER BY t.id
            """,
            (comp["id"],),
        ).fetchall()
        result = []
        for t in teams:
            latest = con.execute(
                "SELECT lat,lon,accuracy_m,created_at,flagged FROM mission_events WHERE team_id=? AND lat IS NOT NULL AND lon IS NOT NULL ORDER BY id DESC LIMIT 1",
                (t["id"],),
            ).fetchone()
            flags = con.execute("SELECT COUNT(*) c FROM mission_events WHERE team_id=? AND flagged=1", (t["id"],)).fetchone()["c"]
            result.append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "logo_url": f"/api/team-logo/{t['id']}" if t["has_logo"] else None,
                    "route_variant": t["route_variant"] + 1,
                    "status": t["status"],
                    "completed": t["current_index"],
                    "penalty_seconds": t["penalty_seconds"],
                    "elapsed_seconds": elapsed_seconds(t),
                    "anti_cheat_flags": flags,
                    "last_location": None if not latest else {
                        "lat": latest["lat"], "lon": latest["lon"], "accuracy_m": latest["accuracy_m"],
                        "created_at": latest["created_at"], "flagged": bool(latest["flagged"]),
                    },
                }
            )
        return {
            "competition": {"name": comp["name"], "code": comp["code"], "status": comp["status"], "started_at": comp["started_at"]},
            "teams": result,
        }
    finally:
        con.close()


@app.get("/api/competition/qr")
def competition_qr(request: Request, token: str):
    con = db()
    try:
        comp = competition_from_organizer(con, token)
        base = str(request.base_url).rstrip("/")
        url = f"{base}/?competition={comp['code']}"
        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png", headers={"Cache-Control": "no-store"})
    finally:
        con.close()


@app.get("/api/admin")
def admin(request: Request):
    supplied = request.headers.get("X-Admin-Key", "")
    if not ADMIN_KEY or not secrets.compare_digest(supplied, ADMIN_KEY):
        raise HTTPException(404, "Not found")
    con = db()
    try:
        teams = [dict(r) for r in con.execute("SELECT id,competition_id,name,join_code,route_variant,logo_mime,created_at FROM teams ORDER BY id DESC")]
        players = [dict(r) for r in con.execute("SELECT id,team_id,name,created_at FROM players ORDER BY id DESC")]
        games = [dict(r) for r in con.execute("SELECT * FROM games ORDER BY id DESC")]
        competitions = [dict(r) for r in con.execute("SELECT id,code,name,status,started_at,created_at FROM competitions ORDER BY id DESC")]
        flags = [dict(r) for r in con.execute("SELECT id,team_id,mission_id,event_type,value,lat,lon,accuracy_m,created_at FROM mission_events WHERE flagged=1 ORDER BY id DESC LIMIT 200")]
        return {"competitions": competitions, "teams": teams, "players": players, "games": games, "anti_cheat_flags": flags}
    finally:
        con.close()