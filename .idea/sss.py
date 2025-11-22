import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import bcrypt
import pandas as pd
import pymysql
import streamlit as st


# Konfiguration

DB_KONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "Xyz1343!!!"),
    "database": os.getenv("DB_NAME", "ticketsystemabkoo"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}

PRIO_WERTE = ["niedrig", "mittel", "hoch"]


# Infrastruktur: DB-Kontextmanager

class DBVerbindung:
    """Kontextmanager für DB-Verbindung (Commit / Rollback automatisch)."""

    def __init__(self, konfig: dict = DB_KONFIG):
        self.konfig = konfig
        self.conn = None

    def __enter__(self):
        self.conn = pymysql.connect(**self.konfig)
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()


class Hilfsfunktionen:
    """Sammlung wiederverwendbarer Hilfsfunktionen (Hashing, DB, Formatierung)."""

    @staticmethod
    def hash_pw_bcrypt(passwort: str) -> str:
        """Erstellt einen bcrypt-Hash aus dem Klartextpasswort."""
        return bcrypt.hashpw(passwort.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_pw_bcrypt(passwort: str, gespeicherter_hash: str) -> bool:
        """Prüft ein Klartextpasswort gegen einen gespeicherten bcrypt-Hash."""
        try:
            return bcrypt.checkpw(passwort.encode("utf-8"), gespeicherter_hash.encode("utf-8"))
        except Exception:
            return False

    @staticmethod
    def daten_abfragen(sql: str, params: tuple = ()):
        """Führt SELECT-Query aus und liefert alle Zeilen als Liste von Dicts."""
        with DBVerbindung() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()

    @staticmethod
    def query_ausfuehren(sql: str, params: tuple = ()):
        """Führt INSERT/UPDATE/DELETE aus. Gibt ggf. lastrowid zurück."""
        with DBVerbindung() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return getattr(cur, "lastrowid", 0) or 0

    @staticmethod
    def datum_formatieren(dt_wert):
        """Formatiert DB-Datetime zur Anzeige (DD.MM.YYYY HH:MM)."""
        if not dt_wert:
            return "—"
        try:
            dt = datetime.fromisoformat(str(dt_wert).replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            return str(dt_wert)


# Repositories (Datenzugriff)

class Mitarbeiter:
    """CRUD-Methoden für Tabelle `mitarbeiter`."""

    @staticmethod
    def mitarbeiter_suchen(username: str) -> Optional[Dict[str, Any]]:
        """Sucht Mitarbeiter anhand Email oder Name (Limit 1)."""
        sql = (
            "SELECT ID_Mitarbeiter, Name, Email, Password_hash, Aktiv, ID_Rolle "
            "FROM mitarbeiter WHERE Email=%s OR Name=%s LIMIT 1"
        )
        with DBVerbindung() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (username.strip(), username.strip()))
                rows = cur.fetchall()
        if not rows:
            return None
        row = rows[0]
        if row.get("Aktiv") != 1:
            return None
        return {
            "id": row["ID_Mitarbeiter"],
            "name": row.get("Name"),
            "email": row.get("Email"),
            "password_hash": row.get("Password_hash"),
            "id_rolle": row.get("ID_Rolle"),
        }

    @staticmethod
    def liste_aktiv() -> List[Dict[str, Any]]:
        """Gibt aktive Mitarbeiter zurück (id, username, email)."""
        sql = "SELECT ID_Mitarbeiter AS id, Name AS username, Email AS email FROM mitarbeiter WHERE Aktiv=1 ORDER BY Name"
        return Hilfsfunktionen.daten_abfragen(sql)

    @staticmethod
    def mitarbeiter_erstellen(name: str, email: str, password_hash: str, id_rolle: Optional[int] = None) -> int:
        """Erstellt neuen Mitarbeiter und gibt ID zurück."""
        sql = "INSERT INTO mitarbeiter (Name, Email, Password_hash, ID_Rolle) VALUES (%s,%s,%s,%s)"
        return Hilfsfunktionen.query_ausfuehren(sql, (name, email, password_hash, id_rolle))

    @staticmethod
    def mitarbeiter_deaktivieren(mitarbeiter_id: int):
        """Deaktiviert einen Mitarbeiter (soft delete)."""
        sql = "UPDATE mitarbeiter SET Aktiv=0, Geloescht_am=NOW() WHERE ID_Mitarbeiter=%s"
        Hilfsfunktionen.query_ausfuehren(sql, (mitarbeiter_id,))


class Ticket:
    """CRUD-Methoden für Tabelle `ticket`."""

    @staticmethod
    def repo_ticket_erstellen(titel: str, beschreibung: str, prioritaet: str, id_kunde: Optional[int], ersteller_id: int) -> int:
        """Legt ein neues Ticket an und gibt die erzeugte ID zurück. (Repository layer)"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        sql = (
            "INSERT INTO ticket (Titel, Beschreibung, Priorität, ID_Status, ID_Kunde, Erstellt_am, Geändert_am, Archiviert, Geändert_von) "
            "VALUES (%s,%s,%s,NULL,%s,%s,%s,0,%s)"
        )
        return Hilfsfunktionen.query_ausfuehren(sql, (titel, beschreibung, prioritaet, id_kunde, now, now, ersteller_id))

    @staticmethod
    def hole_tickets(creator_id: Optional[int] = None, archiviert: bool = False,
                     suchbegriff: Optional[str] = None, id_status: Optional[int] = None,
                     prioritaet: Optional[str] = None) -> List[Dict[str, Any]]:
        """Holt Tickets mit optionalen Filtern und join für lesbare Namen."""
        params: List[Any] = []
        where: List[str] = []

        if not archiviert:
            where.append("t.Archiviert = 0")
        if creator_id is not None:
            where.append("t.Geändert_von = %s")
            params.append(creator_id)
        if suchbegriff:
            where.append("(t.Titel LIKE %s OR t.Beschreibung LIKE %s)")
            params.extend([f"%{suchbegriff}%", f"%{suchbegriff}%"])
        if id_status is not None:
            where.append("t.ID_Status = %s")
            params.append(id_status)
        if prioritaet:
            where.append("t.Priorität = %s")
            params.append(prioritaet)

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        sql = f"""
            SELECT
                t.*,
                ersteller.Name AS creator_name,
                geaendert.Name AS assignee_name,
                s.Name AS status_name
            FROM ticket t
            LEFT JOIN mitarbeiter ersteller ON ersteller.ID_Mitarbeiter = t.Geändert_von
            LEFT JOIN mitarbeiter geaendert ON geaendert.ID_Mitarbeiter = t.Geändert_von
            LEFT JOIN status s ON s.ID_Status = t.ID_Status
            {where_sql}
            ORDER BY t.Geändert_am DESC
        """
        return Hilfsfunktionen.daten_abfragen(sql, tuple(params))

    @staticmethod
    def aktualisiere(ticket_id: int, felder: Dict[str, Any]):
        """Aktualisiert Felder eines Tickets und setzt Geändert_am."""
        if not felder:
            return
        felder["Geändert_am"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        set_clause = ", ".join(f"{k}=%s" for k in felder.keys())
        params = list(felder.values()) + [ticket_id]
        sql = f"UPDATE ticket SET {set_clause} WHERE ID_Ticket=%s"
        Hilfsfunktionen.query_ausfuehren(sql, tuple(params))

    @staticmethod
    def hole_alle_tickets(archiviert: bool = False) -> List[Dict[str, Any]]:
        """Gibt alle Tickets (roh) zurück, optional nur Archivierte."""
        sql = "SELECT * FROM ticket " + ("WHERE Archiviert=1 " if archiviert else "") + "ORDER BY Geändert_am DESC"
        return Hilfsfunktionen.daten_abfragen(sql)

    @staticmethod
    def statistik() -> Dict[str, int]:
        """Berechnet einfache Ticket-Statistiken (total, offene, archiviert)."""
        sql = """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN ID_Status IS NULL THEN 1 ELSE 0 END) as offene,
                SUM(CASE WHEN Archiviert = 1 THEN 1 ELSE 0 END) as archiviert
            FROM ticket
        """
        rows = Hilfsfunktionen.daten_abfragen(sql)
        return rows[0] if rows else {}


# --------------------
# Services (Geschäftslogik)
# --------------------
class AuthDienst:
    """Authentifizierungs- und Benutzerverwaltungs-Logik."""

    @staticmethod
    def login(username_oder_email: str, passwort: str) -> Optional[Dict[str, Any]]:
        """Authentifiziert einen Benutzer und liefert user-info bei Erfolg."""
        mit = Mitarbeiter.mitarbeiter_suchen(username_oder_email.strip())
        if not mit:
            return None
        if Hilfsfunktionen.verify_pw_bcrypt(passwort, mit.get("password_hash", "")):
            rolle_name = None
            if mit.get("id_rolle"):
                r = Hilfsfunktionen.daten_abfragen("SELECT Name FROM rolle WHERE ID_Rolle=%s", (mit.get("id_rolle"),))
                rolle_name = r[0]["Name"] if r else None
            return {"id": mit["id"], "username": mit["name"], "role": rolle_name}
        return None

    @staticmethod
    def erstelle_mitarbeiter(name: str, email: str, passwort: str, id_rolle: Optional[int] = None) -> int:
        """Erstellt neuen Mitarbeiter (Hashing des Passworts)."""
        pw_hash = Hilfsfunktionen.hash_pw_bcrypt(passwort)
        return Mitarbeiter.mitarbeiter_erstellen(name, email, pw_hash, id_rolle)


class TicketDienst:
    """Ticket-bezogene Logik (Erstellen, Listen, Updaten)."""

    @staticmethod
    def svc_ticket_erstellen(titel: str, beschreibung: str, prioritaet: str, id_kunde: Optional[int], ersteller_id: int) -> int:
        """Validiert Priorität und delegiert an das Repository (Service layer)."""
        if prioritaet not in PRIO_WERTE:
            prioritaet = "mittel"
        return Ticket.repo_ticket_erstellen(titel, beschreibung, prioritaet, id_kunde, ersteller_id)

    @staticmethod
    def liste_tickets(creator_id: Optional[int] = None, archiviert: bool = False,
                      suchbegriff: Optional[str] = None, id_status: Optional[int] = None,
                      prioritaet: Optional[str] = None) -> List[Dict[str, Any]]:
        """Wrapper: liefert Ticketliste mit Filteroptionen."""
        return Ticket.hole_tickets(creator_id, archiviert, suchbegriff, id_status, prioritaet)

    @staticmethod
    def update_ticket(ticket_id: int, **felder):
        """Wrapper für Ticket-Update."""
        Ticket.aktualisiere(ticket_id, felder)

    @staticmethod
    def stats() -> Dict[str, int]:
        """Gibt Ticket-Statistiken zurück."""
        return Ticket.statistik()


# --------------------
# Präsentationsschicht (Streamlit UI) - AppUI
# --------------------
class AppUI:
    """Streamlit-Oberfläche"""

    def __init__(self):
        st.set_page_config(page_title="Ticketsystem", layout="wide", page_icon="🎫")
        st.markdown("""
            <style>
            .stButton button { border-radius: 5px; }
            div[data-testid="stExpander"] { border: 1px solid #ddd; border-radius: 5px; }
            </style>
        """, unsafe_allow_html=True)

    def zeige_statistiken(self):
        """Zeigt Kennzahlen als Metriken."""
        stats = TicketDienst.stats()
        col1, col2 = st.columns(2)
        col1.metric("Gesamt", stats.get("total", 0))
        col2.metric("📦 Archiviert", stats.get("archiviert", 0))
        st.divider()

    def kanban(self, t: Dict[str, Any]):
        """Rendert eine Ticket-Karte (Kurzinfo)."""
        prio = t.get("Priorität", "-")
        st.markdown(f"**#{t['ID_Ticket']} — {t.get('Titel','-')}**")
        st.caption(f"📁 {t.get('status_name','-')} • ⏰ {Hilfsfunktionen.datum_formatieren(t.get('Geändert_am'))}")
        st.write((t.get("Beschreibung") or "")[:200])
        st.caption(f"👤 {t.get('creator_name','?')}")

    def seite_login(self):
        """Zeigt Login-Formular und führt Authentifizierung durch."""
        st.title("🎫 Ticketsystem Login")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                st.subheader("Anmelden")
                u = st.text_input("Benutzername / Email")
                p = st.text_input("Passwort", type="password")
                if st.form_submit_button("🔐 Anmelden"):
                    user = AuthDienst.login(u, p)
                    if user:
                        st.session_state.update({"user_id": user["id"], "role": user["role"], "username": user["username"]})
                        st.success("✅ Erfolgreich angemeldet!")
                        st.rerun()
                    else:
                        st.error("❌ Ungültige Zugangsdaten")

    def ui_ticket_erstellen(self):
        """Formular zum Anlegen eines neuen Tickets (UI layer)."""
        st.header("➕ Neues Ticket erstellen")
        with st.form("create_ticket_form"):
            titel = st.text_input("📝 Titel")
            beschreibung = st.text_area("📄 Beschreibung", height=200)
            col1, col2 = st.columns(2)
            prio = col1.selectbox("⚠️ Priorität", PRIO_WERTE, index=1)
            kunden = Hilfsfunktionen.daten_abfragen("SELECT ID_Kunde AS id, Name FROM kunde ORDER BY Name")
            kundeliste = [None] + [k["id"] for k in kunden]
            kunden_map = {k["id"]: k["Name"] for k in kunden}
            kunde = col2.selectbox("🔎 Kunde", kundeliste, format_func=lambda v: "—" if v is None else kunden_map.get(v, "?"))
            if st.form_submit_button("✅ Ticket anlegen"):
                if not titel or not beschreibung:
                    st.error("❌ Titel und Beschreibung dürfen nicht leer sein.")
                else:
                    TicketDienst.svc_ticket_erstellen(titel.strip(), beschreibung.strip(), prio, kunde, st.session_state.user_id)
                    st.success("✅ Ticket angelegt!")
                    st.balloons()
                    st.rerun()

    def kanban_seite(self):
        """Zeigt das Kanban-Board mit Filtern und gruppierten Tickets."""
        st.header("🎫 Ticket Kanban-Board")
        self.zeige_statistiken()

        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
        suchtext = col1.text_input("🔍 Suche")
        statusliste = Hilfsfunktionen.daten_abfragen("SELECT ID_Status AS id, Name FROM status ORDER BY ID_Status")
        filter_status = col2.selectbox("📁 Status", ["Alle"] + [s["Name"] for s in statusliste])
        filter_prio = col3.selectbox("⚠️ Priorität", ["Alle"] + PRIO_WERTE)
        zeige_arch = col4.checkbox("📦 Archiv")

        id_status = None if filter_status == "Alle" else next((s["id"] for s in statusliste if s["Name"] == filter_status), None)
        prior = None if filter_prio == "Alle" else filter_prio

        tickets = TicketDienst.liste_tickets(archiviert=zeige_arch, suchbegriff=suchtext or None, id_status=id_status, prioritaet=prior)

        if not tickets:
            st.info("ℹ️ Keine Tickets gefunden.")
            return

        gruppiert: Dict[str, List[Dict[str, Any]]] = {}
        for t in tickets:
            key = t.get("status_name") or "Unbekannt"
            gruppiert.setdefault(key, []).append(t)

        cols = st.columns(3)
        for idx, (status_name, tlist) in enumerate(gruppiert.items()):
            with cols[idx % 3]:
                st.subheader(f"{status_name} ({len(tlist)})")
                for t in tlist:
                    with st.container():
                        self.kanban(t)
                        c1, c2 = st.columns([1, 3])
                        with c1:
                            if st.button("➡️", key=f"right_{t['ID_Ticket']}"):
                                TicketDienst.update_ticket(t["ID_Ticket"], ID_Status=None)
                                st.rerun()
                        with c2:
                            st.caption(f"Letzte Änderung: {Hilfsfunktionen.datum_formatieren(t.get('Geändert_am'))}")

    def tickets_verwalten(self):
        """Admin-Ansicht: Tickets ansehen und editieren."""
        st.header("🔧 Admin: Tickets verwalten")
        zeige_arch = st.checkbox("📦 Archivierte anzeigen")
        tickets = TicketDienst.liste_tickets(archiviert=zeige_arch)

        if not tickets:
            st.info("ℹ️ Keine Tickets vorhanden")
            return

        benutzer = Mitarbeiter.liste_aktiv()
        benutzer_map = {u["id"]: u["username"] for u in benutzer}
        benutzer_ids = [None] + [u["id"] for u in benutzer]

        for t in tickets:
            with st.expander(f"#{t['ID_Ticket']} — {t['Titel']}", expanded=False):
                st.markdown(f"**Ticket #{t['ID_Ticket']}**")
                st.caption(f"Erstellt: {Hilfsfunktionen.datum_formatieren(t.get('Erstellt_am'))} | Aktualisiert: {Hilfsfunktionen.datum_formatieren(t.get('Geändert_am'))}")
                st.write(t.get("Beschreibung", ""))

                c1, c2, c3, c4 = st.columns(4)
                status_namen = [s["Name"] for s in Hilfsfunktionen.daten_abfragen("SELECT ID_Status AS id, Name FROM status ORDER BY ID_Status")]
                status = c1.selectbox("Status", status_namen, index=0, key=f"st_{t['ID_Ticket']}")
                prio_index = PRIO_WERTE.index(t.get("Priorität")) if t.get("Priorität") in PRIO_WERTE else 1
                prio = c2.selectbox("Priorität", PRIO_WERTE, index=prio_index, key=f"pr_{t['ID_Ticket']}")
                cur = t.get("Geändert_von")
                a_index = 0 if cur in (None, 0) else (benutzer_ids.index(cur) if cur in benutzer_ids else 0)
                assignee = c4.selectbox("Bearbeiter", benutzer_ids, index=a_index, format_func=lambda v: "—" if v is None else benutzer_map.get(v, "?"), key=f"as_adm_{t['ID_Ticket']}")
                arch = st.checkbox("📦 Archivieren", value=bool(t.get("Archiviert", 0)), key=f"arch_adm_{t['ID_Ticket']}")

                if st.button("💾 Speichern", key=f"save_adm_{t['ID_Ticket']}"):
                    status_row = Hilfsfunktionen.daten_abfragen("SELECT ID_Status FROM status WHERE Name=%s", (status,))
                    status_id = status_row[0]["ID_Status"] if status_row else None
                    felder = {"ID_Status": status_id, "Priorität": prio, "Geändert_von": assignee, "Archiviert": int(arch)}
                    TicketDienst.update_ticket(t["ID_Ticket"], **felder)
                    st.success("✅ Gespeichert")
                    st.rerun()

    def admin_seite(self):
        """Admin-Benutzerverwaltung: Auflistung, anlegen, deaktivieren."""
        st.header("🗄️ Benutzerverwaltung")
        users = Mitarbeiter.liste_aktiv()
        if users:
            st.dataframe(pd.DataFrame(users), use_container_width=True, hide_index=True)
        else:
            st.info("Keine Benutzer vorhanden")

        st.divider()
        with st.form("new_user"):
            st.subheader("➕ Neuen Benutzer anlegen")
            col1, col2, col3 = st.columns(3)
            name = col1.text_input("Name")
            email = col2.text_input("Email")
            pw = col3.text_input("Passwort", type="password")
            if st.form_submit_button("✅ Anlegen"):
                if name and email and pw:
                    AuthDienst.erstelle_mitarbeiter(name, email, pw, None)
                    st.success("✅ Benutzer angelegt.")
                    st.rerun()
                else:
                    st.error("❌ Name, Email und Passwort erforderlich.")

        st.divider()
        st.subheader("🗑️ Benutzer deaktivieren")
        users = Mitarbeiter.liste_aktiv()
        if not users:
            st.info("Keine aktiven Benutzer vorhanden.")
        else:
            victim = st.selectbox("Benutzer auswählen", users, format_func=lambda x: x["username"])
            confirm = st.text_input("Zur Bestätigung Benutzernamen erneut eingeben")
            sure = st.checkbox("Ich bin sicher")
            is_self = ("user_id" in st.session_state) and (victim["id"] == st.session_state["user_id"])
            if is_self:
                st.warning("⚠️ Du kannst dich nicht selbst deaktivieren.")
            if st.button("🗑️ Benutzer deaktivieren", disabled=is_self or not sure or confirm != victim["username"]):
                Mitarbeiter.mitarbeiter_deaktivieren(victim["id"])
                st.success(f"✅ Benutzer '{victim['username']}' wurde deaktiviert.")
                st.rerun()

    def profil_seite(self):
        """Zeigt Profilinformationen und bietet Logout an."""
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
# Hauptprogramm / Navigation (Sidebar)
# --------------------

def main():
    """Entry-Point: baut UI auf und routet zwischen Seiten."""
    app = AppUI()

    if "user_id" not in st.session_state:
        app.seite_login()
        return

    st.sidebar.title("🎫 Ticketsystem")
    st.sidebar.markdown(f"**👤 Benutzer:**  {st.session_state.get('username','-')}")
    st.sidebar.markdown(f"**🛡️ Rolle:**  {st.session_state.get('role','-')}")
    st.sidebar.divider()

    menue = ["📋 Kanban-Board", "➕ Ticket erstellen"]
    if st.session_state.get("role") == "admin":
        menue.append("🛠️ Verwaltung")

    auswahl = st.sidebar.radio("Navigation", menue, label_visibility="collapsed")
    st.sidebar.divider()
    if st.sidebar.button("🚪 Logout"):
        for k in ["user_id", "role", "username"]:
            st.session_state.pop(k, None)
        st.rerun()

    # Routing zu den Seiten (UI-Methoden angepasst)
    if auswahl == "📋 Kanban-Board":
        app.kanban_seite()
    elif auswahl == "➕ Ticket erstellen":
        app.ui_ticket_erstellen()
    elif auswahl == "🛠️ Verwaltung":
        sub = st.radio("Verwaltungsbereich", ["🎫 Tickets", "👥 Benutzer"], horizontal=True)
        if sub == "🎫 Tickets":
            app.tickets_verwalten()
        else:
            app.admin_seite()


if __name__ == "__main__":
    main()
