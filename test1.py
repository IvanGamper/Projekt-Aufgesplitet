
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import bcrypt
import pandas as pd
import pymysql
import streamlit as st

# --------------------
# Konfiguration (gleich wie vorher)
# --------------------
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "Xyz1343!!!"),
    "database": os.getenv("DB_NAME", "ticketsystemabkoo1"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}

STATI = ["Neu", "In Bearbeitung", "Warten auf Benutzer", "Gelöst", "Geschlossen"]
PRIO = ["Niedrig", "Normal", "Hoch", "Kritisch"]
CATS = ["Hardware", "Software", "Netzwerk", "Sonstiges"]

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

# --------------------
# Infrastruktur
# --------------------
class DBConnection:
    """Kontextmanager für DB-Verbindung (Commit/Rollback automatisch)."""

    def __init__(self, config: dict = DB_CONFIG):
        self.config = config
        self.conn = None

    def __enter__(self):
        self.conn = pymysql.connect(**self.config)
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()

# --------------------
# Hilfsfunktionen (als Modul-Utilities)
# --------------------
def hash_pw_bcrypt(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_pw_bcrypt(password: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except Exception:
        return False

def safe_index(options, value, default=0):
    try:
        return options.index(value)
    except Exception:
        return default

def next_status(s: str) -> str:
    try:
        i = STATI.index(s)
        return STATI[min(i + 1, len(STATI) - 1)]
    except ValueError:
        return s

def prev_status(s: str) -> str:
    try:
        i = STATI.index(s)
        return STATI[max(i - 1, 0)]
    except ValueError:
        return s

def format_datetime(dt_str):
    if not dt_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(dt_str).replace('Z', '+00:00'))
        return dt.strftime("%d.%m.%Y %H:%M")
    except:
        return str(dt_str)

# --------------------
# Repositories (Data Access)
# --------------------
class UserRepository:
    """DB-Zugriffe für users-Tabelle."""

    @staticmethod
    def get_by_username(username: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT id, username, role, password_hash, active FROM users WHERE username=%s"
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (username.strip(),))
                rows = cur.fetchall()
        if not rows or rows[0].get("active") != 1:
            return None
        return rows[0]

    @staticmethod
    def create(username: str, password_hash: str, role: str = "user") -> int:
        sql = "INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s)"
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (username, password_hash, role))
                return getattr(cur, "lastrowid", 0) or 0

    @staticmethod
    def list_active() -> List[Dict[str, Any]]:
        sql = "SELECT id, username, role FROM users WHERE active=1 ORDER BY username"
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchall()

    @staticmethod
    def deactivate(user_id: int):
        sql = "UPDATE users SET active=0, deleted_at=NOW() WHERE id=%s"
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id,))

class TicketRepository:
    """DB-Zugriffe für tickets-Tabelle."""

    @staticmethod
    def create(title: str, description: str, category: str, priority: str, creator_id: int) -> int:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        sql = (
            "INSERT INTO tickets"
            " (title, description, category, status, priority, creator_id, created_at, updated_at, archived)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0)"
        )
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (title, description, category, "Neu", priority, creator_id, now, now))
                return getattr(cur, "lastrowid", 0) or 0

    @staticmethod
    def fetch(creator_id: Optional[int] = None, archived: bool = False,
              search_term: Optional[str] = None, category: Optional[str] = None,
              priority: Optional[str] = None) -> List[Dict[str, Any]]:
        params: List[Any] = []
        where: List[str] = []

        if not archived:
            where.append("t.archived = 0")
        if creator_id is not None:
            where.append("t.creator_id = %s")
            params.append(creator_id)
        if search_term:
            where.append("(t.title LIKE %s OR t.description LIKE %s)")
            params.extend([f"%{search_term}%", f"%{search_term}%"])
        if category and category != "Alle":
            where.append("t.category = %s")
            params.append(category)
        if priority and priority != "Alle":
            where.append("t.priority = %s")
            params.append(priority)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"""
            SELECT t.*, u.username AS creator_name, a.username AS assignee_name
            FROM tickets t
            JOIN users u ON u.id = t.creator_id
            LEFT JOIN users a ON a.id = t.assignee_id
            {where_sql}
            ORDER BY t.updated_at DESC
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                return cur.fetchall()

    @staticmethod
    def update(ticket_id: int, fields: Dict[str, Any]):
        if not fields:
            return
        fields["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        set_clause = ", ".join(f"{k}=%s" for k in fields.keys())
        params = list(fields.values()) + [ticket_id]
        sql = f"UPDATE tickets SET {set_clause} WHERE id=%s"
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))

    @staticmethod
    def fetch_all_raw(archived: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM tickets " + ("WHERE archived=1 " if archived else "") + "ORDER BY updated_at DESC"
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchall()

    @staticmethod
    def stats() -> Dict[str, int]:
        sql = """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'Neu' THEN 1 ELSE 0 END) as neue,
                SUM(CASE WHEN status = 'In Bearbeitung' THEN 1 ELSE 0 END) as in_bearbeitung,
                SUM(CASE WHEN status = 'Gelöst' THEN 1 ELSE 0 END) as geloest,
                SUM(CASE WHEN archived = 1 THEN 1 ELSE 0 END) as archiviert
            FROM tickets
        """
        with DBConnection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                return rows[0] if rows else {}

# --------------------
# Services (Business Logic)
# --------------------
class AuthService:
    """Kapselt Login/Benutzererstellung."""

    @staticmethod
    def login(username: str, password: str) -> Optional[Dict[str, Any]]:
        u = UserRepository.get_by_username(username.strip())
        if not u:
            return None
        if verify_pw_bcrypt(password, u.get("password_hash", "")):
            return {"id": u["id"], "username": u["username"], "role": u["role"]}
        return None

    @staticmethod
    def create_user(username: str, password: str, role: str = "user") -> int:
        pw_hash = hash_pw_bcrypt(password)
        return UserRepository.create(username, pw_hash, role)

class TicketService:
    """Ticket-bezogene Geschäftslogik (Erstellen, Listen, Updaten)."""

    @staticmethod
    def create_ticket(title: str, description: str, category: str, priority: str, creator_id: int) -> int:
        return TicketRepository.create(title, description, category, priority, creator_id)

    @staticmethod
    def list_tickets(creator_id: Optional[int] = None, archived: bool = False,
                     search_term: Optional[str] = None, category: Optional[str] = None,
                     priority: Optional[str] = None) -> List[Dict[str, Any]]:
        return TicketRepository.fetch(creator_id, archived, search_term, category, priority)

    @staticmethod
    def update_ticket(ticket_id: int, **fields):
        TicketRepository.update(ticket_id, fields)

    @staticmethod
    def stats() -> Dict[str, int]:
        return TicketRepository.stats()

# --------------------
# App UI (Streamlit) - kapselt Seiten als Methoden
# --------------------
class AppUI:
    """Präsentationsschicht: alle page_*-Funktionen als Methoden."""

    def __init__(self):
        st.set_page_config(page_title="Ticketsystem", layout="wide", page_icon="🎫", initial_sidebar_state="expanded")
        # kleine CSS-Politur
        st.markdown("""
            <style>
            .stButton button { border-radius: 5px; }
            div[data-testid="stExpander"] { border: 1px solid #ddd; border-radius: 5px; }
            </style>
        """, unsafe_allow_html=True)

    # ---- UI-Helfer ----
    def show_stats(self):
        stats = TicketService.stats()
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Gesamt", stats.get('total', 0))
        col2.metric("🔵 Neu", stats.get('neue', 0))
        col3.metric("🟡 In Bearbeitung", stats.get('in_bearbeitung', 0))
        col4.metric("🟢 Gelöst", stats.get('geloest', 0))
        col5.metric("📦 Archiviert", stats.get('archiviert', 0))
        st.divider()

    def kanban_card(self, t: Dict[str, Any]):
        status_icon = STATUS_COLORS.get(t.get('status', ''), '⚪')
        prio_icon = PRIO_COLORS.get(t.get('priority', ''), '⚪')
        st.markdown(f"{status_icon} {prio_icon} **#{t['id']} — {t['title']}**")
        st.caption(f"📁 {t.get('category','-')} • ⏰ {format_datetime(t.get('updated_at'))}")
        desc = t.get('description') or ''
        st.write(desc[:150] + ("…" if len(desc) > 150 else ""))
        st.caption(f"👤 {t.get('creator_name','?')} → 👨‍💼 {t.get('assignee_name','—') or 'Nicht zugewiesen'}")

    # ---- Pages ----
    def page_login(self):
        st.title("🎫 Ticketsystem Login")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                st.subheader("Anmelden")
                u = st.text_input("Benutzername")
                p = st.text_input("Passwort", type="password")
                if st.form_submit_button("🔐 Anmelden", use_container_width=True):
                    user = AuthService.login(u, p)
                    if user:
                        st.session_state.update({
                            "user_id": user["id"],
                            "role": user["role"],
                            "username": user["username"]
                        })
                        st.success("✅ Erfolgreich angemeldet!")
                        st.rerun()
                    else:
                        st.error("❌ Ungültige Zugangsdaten")

    def page_create_ticket(self):
        st.header("➕ Neues Ticket erstellen")
        with st.form("create_ticket_form"):
            title = st.text_input("📝 Titel")
            desc = st.text_area("📄 Beschreibung", height=200)
            col1, col2 = st.columns(2)
            cat = col1.selectbox("📁 Kategorie", CATS)
            prio = col2.selectbox("⚠️ Priorität", PRIO, index=1)

            if st.form_submit_button("✅ Ticket anlegen", use_container_width=True):
                if not title or not desc:
                    st.error("❌ Titel und Beschreibung dürfen nicht leer sein.")
                else:
                    TicketService.create_ticket(title.strip(), desc.strip(), cat, prio, st.session_state.user_id)
                    st.success("✅ Ticket angelegt!")
                    st.balloons()
                    st.rerun()

    def page_kanban(self):
        st.header("🎫 Ticket Kanban-Board")
        self.show_stats()

        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
        search = col1.text_input("🔍 Suche", placeholder="Ticket durchsuchen...")
        filter_cat = col2.selectbox("📁 Kategorie", ["Alle"] + CATS)
        filter_prio = col3.selectbox("⚠️ Priorität", ["Alle"] + PRIO)
        show_arch = col4.checkbox("📦 Archiv")

        is_admin = (st.session_state.get("role") == "admin")
        tickets = TicketService.list_tickets(
            archived=show_arch,
            search_term=search or None,
            category=(None if filter_cat == "Alle" else filter_cat),
            priority=(None if filter_prio == "Alle" else filter_prio),
        )
        if not tickets:
            st.info("ℹ️ Keine Tickets gefunden.")
            return

        users = UserRepository.list_active()
        user_map = {u["id"]: u["username"] for u in users}
        user_ids = [None] + [u["id"] for u in users]

        cols = st.columns(len(STATI))
        for idx, status_name in enumerate(STATI):
            with cols[idx]:
                status_icon = STATUS_COLORS.get(status_name, '⚪')
                col_tickets = [t for t in tickets if t.get("status") == status_name]
                st.subheader(f"{status_icon} {status_name} ({len(col_tickets)})")

                if not col_tickets:
                    st.caption("—")

                for t in col_tickets:
                    with st.container():
                        self.kanban_card(t)
                        c1, c2, c3 = st.columns([1, 1, 2])

                        with c1:
                            if st.button("⬅️", key=f"left_{t['id']}", help="Vorheriger Status"):
                                TicketService.update_ticket(t["id"], status=prev_status(t["status"]))
                                st.rerun()
                        with c2:
                            if st.button("➡️", key=f"right_{t['id']}", help="Nächster Status"):
                                TicketService.update_ticket(t["id"], status=next_status(t["status"]))
                                st.rerun()

                        cur = t.get("assignee_id")
                        a_index = 0 if cur in (None, 0) else (user_ids.index(cur) if cur in user_ids else 0)
                        assignee = c3.selectbox(
                            "Bearbeiter",
                            user_ids, index=a_index,
                            format_func=lambda v: "—" if v is None else user_map.get(v, "?"),
                            key=f"as_{t['id']}",
                            label_visibility="collapsed"
                        )

                        if is_admin:
                            arch = st.checkbox("📦 Archivieren", value=bool(t.get("archived", 0)), key=f"arch_{t['id']}")
                        else:
                            arch = bool(t.get("archived", 0))

                        if st.button("💾 Speichern", key=f"save_{t['id']}", use_container_width=True):
                            fields = {"assignee_id": assignee}
                            if is_admin:
                                fields["archived"] = int(arch)
                            TicketService.update_ticket(t["id"], **fields)
                            st.success("✅ Gespeichert")
                            st.rerun()

    def page_admin(self):
        """Admin: Tickets verwalten (wie ursprünglich)."""
        st.header("🔧 Admin: Tickets verwalten")

        show_arch = st.checkbox("📦 Archivierte anzeigen")
        tickets = TicketService.list_tickets(archived=show_arch)

        if not tickets:
            st.info("ℹ️ Keine Tickets vorhanden")
            return

        users = UserRepository.list_active()
        user_map = {u["id"]: u["username"] for u in users}
        user_ids = [None] + [u["id"] for u in users]

        for t in tickets:
            with st.expander(f"#{t['id']} — {t['title']}", expanded=False):
                status_icon = STATUS_COLORS.get(t.get('status', ''), '⚪')
                prio_icon = PRIO_COLORS.get(t.get('priority', ''), '⚪')

                st.markdown(f"{status_icon} {prio_icon} **Ticket #{t['id']}**")
                st.caption(f"Erstellt: {format_datetime(t.get('created_at'))} | "
                           f"Aktualisiert: {format_datetime(t.get('updated_at'))}")
                st.write(t.get("description", ""))
                st.caption(f"Von: {t.get('creator_name','?')} → Bearbeiter: {t.get('assignee_name','-') or '-'}")

                st.divider()

                c1, c2, c3, c4 = st.columns(4)
                status = c1.selectbox("Status", STATI, index=safe_index(STATI, t.get("status")), key=f"st_{t['id']}")
                prio = c2.selectbox("Priorität", PRIO, index=safe_index(PRIO, t.get("priority"), 1), key=f"pr_{t['id']}")
                cat = c3.selectbox("Kategorie", CATS, index=safe_index(CATS, t.get("category")), key=f"ct_{t['id']}")

                current_assignee = t.get("assignee_id")
                assignee_index = 0 if current_assignee in (None, 0) else (user_ids.index(current_assignee) if current_assignee in user_ids else 0)
                assignee = c4.selectbox("Bearbeiter", user_ids, index=assignee_index,
                                        format_func=lambda v: "—" if v is None else user_map.get(v, "?"),
                                        key=f"as_adm_{t['id']}")

                arch = st.checkbox(f"📦 Archivieren", value=bool(t.get("archived", 0)), key=f"arch_adm_{t['id']}")

                if st.button(f"💾 Speichern", key=f"save_adm_{t['id']}", use_container_width=True):
                    TicketService.update_ticket(t["id"], status=status, priority=prio, category=cat,
                                                assignee_id=assignee, archived=int(arch))
                    st.success("✅ Gespeichert")
                    st.rerun()

    def page_database(self):
        """DB-Verwaltung / Benutzer (wie zuvor)."""
        st.header("🗄️ Datenbank (Admin)")
        tab1, tab2 = st.tabs(["👥 Benutzer", "🎫 Tickets"])

        with tab1:
            st.subheader("Aktive Benutzer")
            users = UserRepository.list_active()
            if users:
                df = pd.DataFrame(users)
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("Keine Benutzer vorhanden")

            st.divider()

            with st.form("new_user"):
                st.subheader("➕ Neuen Benutzer anlegen")
                col1, col2, col3 = st.columns(3)
                u = col1.text_input("Username")
                p = col2.text_input("Passwort", type="password")
                r = col3.selectbox("Rolle", ["user", "admin"])

                if st.form_submit_button("✅ Anlegen", use_container_width=True):
                    if u and p:
                        AuthService.create_user(u, p, r)
                        st.success("✅ Benutzer angelegt.")
                        st.rerun()
                    else:
                        st.error("❌ Username und Passwort erforderlich.")

            st.divider()

            st.subheader("🗑️ Benutzer deaktivieren")
            if not users:
                st.info("Keine aktiven Benutzer vorhanden.")
            else:
                victim = st.selectbox("Benutzer auswählen", users, format_func=lambda x: x["username"])
                confirm = st.text_input("Zur Bestätigung Benutzernamen erneut eingeben")
                sure = st.checkbox("Ich bin sicher")
                is_self = ("user_id" in st.session_state) and (victim["id"] == st.session_state["user_id"])
                if is_self:
                    st.warning("⚠️ Du kannst dich nicht selbst deaktivieren.")
                if st.button("🗑️ Benutzer deaktivieren",
                             disabled=is_self or not sure or confirm != victim["username"],
                             type="primary"):
                    UserRepository.deactivate(victim["id"])
                    st.success(f"✅ Benutzer '{victim['username']}' wurde deaktiviert.")
                    st.rerun()

    def page_profile(self):
        st.header("👤 Profil")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown(f"""
            ### Angemeldet als

            **Benutzername:** {st.session_state.username}  
            **Rolle:** {st.session_state.role}
            """)
            if st.button("🚪 Logout", use_container_width=True, type="primary"):
                for k in ["user_id", "role", "username"]:
                    st.session_state.pop(k, None)
                st.success("✅ Erfolgreich abgemeldet!")
                st.rerun()

# --------------------
# Main: Navigation (Sidebar with 3 items)
# --------------------
def main():
    ui = AppUI()

    # Login-Check
    if "user_id" not in st.session_state:
        ui.page_login()
        return

    # Sidebar Navigation (wie gewünscht: seitlich)
    st.sidebar.title("🎫 Ticketsystem")
    st.sidebar.markdown(f"**👤 Benutzer:**  {st.session_state.get('username','-')}")
    st.sidebar.markdown(f"**🛡️ Rolle:**  {st.session_state.get('role','-')}")
    st.sidebar.divider()

    menu = ["📋 Kanban-Board", "➕ Ticket erstellen"]
    if st.session_state.get("role") == "admin":
        menu.append("🛠️ Verwaltung")

    choice = st.sidebar.radio("Navigation", menu, label_visibility="collapsed")
    st.sidebar.divider()
    if st.sidebar.button("🚪 Logout"):
        for k in ["user_id", "role", "username"]:
            st.session_state.pop(k, None)
        st.rerun()

    # Render pages
    if choice == "📋 Kanban-Board":
        ui.page_kanban()
    elif choice == "➕ Ticket erstellen":
        ui.page_create_ticket()
    elif choice == "🛠️ Verwaltung":
        # Verwaltung mit zwei Subtabs (Tickets, Benutzer) wie zuvor
        sub = st.radio("Verwaltungsbereich", ["🎫 Tickets", "👥 Benutzer"], horizontal=True)
        if sub == "🎫 Tickets":
            ui.page_admin()
        else:
            ui.page_database()

if __name__ == "__main__":
    main()
