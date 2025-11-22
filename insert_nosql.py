
from tinydb import TinyDB
from datetime import datetime, timezone
import bcrypt
from typing import Optional

DB_PATH = "tickets_nosql.json"

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def hash_pw_bcrypt(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_user_nosql(username: str, password: str, role: str = "user", db_path: str = DB_PATH) -> int:
    """
    Legt einen Benutzer in TinyDB an und gibt die doc_id zurück.
    """
    db = TinyDB(db_path)
    users = db.table("users")
    pw_hash = hash_pw_bcrypt(password)
    doc = {
        "username": username,
        "password_hash": pw_hash,
        "role": role,
        "active": 1,
        "created_at": _now_iso(),
        "deleted_at": None
    }
    doc_id = users.insert(doc)
    return doc_id

def create_ticket_nosql(title: str,
                        description: str,
                        category: str,
                        priority: str,
                        creator_doc_id: int,
                        assignee_doc_id: Optional[int] = None,
                        status: str = "Neu",
                        archived: int = 0,
                        db_path: str = DB_PATH) -> int:
    """
    Legt ein Ticket in TinyDB an und gibt die doc_id zurück.
    """
    db = TinyDB(db_path)
    tickets = db.table("tickets")
    now = _now_iso()
    doc = {
        "title": title,
        "description": description,
        "category": category,
        "status": status,
        "priority": priority,
        "creator_id": creator_doc_id,
        "assignee_id": assignee_doc_id,
        "created_at": now,
        "updated_at": now,
        "archived": archived
    }
    doc_id = tickets.insert(doc)
    return doc_id

# Beispielnutzung
if __name__ == "__main__":
    # 1) Benutzer anlegen
    user_id = create_user_nosql("neueruser", "Passwort123!", role="user")
    print("Neuer User doc_id:", user_id)

    # 2) Ticket für den neuen Benutzer anlegen
    ticket_id = create_ticket_nosql(
        title="Monitor-Anfrage",
        description="Bitte 27 Zoll bevorzugt, ergon. Standfuß.",
        category="Sonstiges",
        priority="Normal",
        creator_doc_id=user_id,
        assignee_doc_id=None,
        status="Neu",
        archived=0
    )
    print("Neues Ticket doc_id:", ticket_id)
