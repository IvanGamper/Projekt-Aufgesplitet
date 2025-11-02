from datetime import datetime, timezone
import bcrypt
from db import query_fetchall, query_execute

# --------- Konstanten / UI-Labels ----------
STATI = ["Neu", "In Bearbeitung", "Warten auf Benutzer", "Gelöst", "Geschlossen"]
PRIO  = ["Niedrig", "Normal", "Hoch", "Kritisch"]
CATS  = ["Hardware", "Software", "Netzwerk", "Sonstiges"]

STATUS_COLORS = {
    "Neu": "🔵",
    "In Bearbeitung": "🟡",
    "Warten auf Benutzer": "🟠",
    "Gelöst": "🟢",
    "Geschlossen": "⚫"
}

PRIO_COLORS = {
    "Niedrig": "🟢",
    "Normal": "🟡",
    "Hoch": "🟠",
    "Kritisch": "🔴"
}

# --------- Utils ----------
def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def format_datetime(dt_str):
    if not dt_str: return "—"
    try:
        dt = datetime.fromisoformat(str(dt_str).replace('Z', '+00:00'))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(dt_str)

def safe_index(options, value, default=0):
    return options.index(value) if value in options else default


def next_status(s):
    return STATI[min(STATI.index(s) + 1, len(STATI) - 1)] if s in STATI else s

def prev_status(s):
    return STATI[max(STATI.index(s) - 1, 0)] if s in STATI else s

# --------- Security ----------
def hash_pw_bcrypt(password: str) -> str:
    """Erzeugt bcrypt-Hash als UTF-8-String."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_pw_bcrypt(password: str, stored_hash: str) -> bool:
    """Prüft Passwort gegen gespeicherten bcrypt-Hash."""
    try:
        return bcrypt.checkpw(password.encode(), stored_hash.encode())
    except Exception:
        return False

# --------- User-Service ----------
def get_user_by_username(username: str):
    rows = query_fetchall(
        "SELECT id, username, role, password_hash, active FROM users WHERE username=%s",
        (username.strip(),)
    )
    return rows[0] if rows and rows[0]["active"] == 1 else None


def login_user(username: str, password: str):
    u = get_user_by_username(username.strip())
    if not u:
        return None
    if verify_pw_bcrypt(password, u["password_hash"]):
        return {"id": u["id"], "username": u["username"], "role": u["role"]}
    return None

def create_user(username: str, password: str, role: str = "user"):
    pw_hash = hash_pw_bcrypt(password)
    query_execute("INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s)",
                  (username, pw_hash, role))

def list_users():
    return query_fetchall("SELECT id, username, role FROM users WHERE active=1 ORDER BY username")

def deactivate_user(user_id: int):
    query_execute("UPDATE users SET active=0, deleted_at=NOW() WHERE id=%s", (user_id,))

# --------- Ticket-Service ----------
def create_ticket(title, description, category, priority, creator_id):
    now = now_utc_str()
    query_execute(
        """INSERT INTO tickets
           (title, description, category, status, priority, creator_id, created_at, updated_at, archived)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0)""",
        (title, description, category, "Neu", priority, creator_id, now, now)
    )

def fetch_tickets(creator_id=None, archived=False, search_term=None, category=None, priority=None):
    where, params = [], []
    if not archived:
        where.append("t.archived = 0")
    if creator_id:
        where.append("t.creator_id = %s")
        params.append(creator_id)
    if search_term:
        where.append("(t.title LIKE %s OR t.description LIKE %s)")
        params += [f"%{search_term}%", f"%{search_term}%"]
    if category and category != "Alle":
        where.append("t.category = %s")
        params.append(category)
    if priority and priority != "Alle":
        where.append("t.priority = %s")
        params.append(priority)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT t.*, u.username AS creator_name, a.username AS assignee_name
        FROM tickets t
        JOIN users u ON u.id = t.creator_id
        LEFT JOIN users a ON a.id = t.assignee_id
        {where_sql}
        ORDER BY t.updated_at DESC
    """
    return query_fetchall(sql, tuple(params))



def update_ticket(tid, **fields):
    if not fields: return
    fields["updated_at"] = now_utc_str()
    set_clause = ", ".join(f"{k}=%s" for k in fields)
    query_execute(f"UPDATE tickets SET {set_clause} WHERE id=%s", (*fields.values(), tid))


def get_ticket_stats():
    stats = query_fetchall("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'Neu' THEN 1 ELSE 0 END) as neue,
            SUM(CASE WHEN status = 'In Bearbeitung' THEN 1 ELSE 0 END) as in_bearbeitung,
            SUM(CASE WHEN status = 'Gelöst' THEN 1 ELSE 0 END) as geloest,
            SUM(CASE WHEN archived = 1 THEN 1 ELSE 0 END) as archiviert
        FROM tickets
    """)
    return stats[0] if stats else {}
