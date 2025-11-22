import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import bcrypt
import pandas as pd
import pymysql
import streamlit as st


# --------------------
# Konfiguration
# --------------------
# Hier werden zentrale Einstellungen definiert, die für die gesamte
# Anwendung gebraucht werden: Datenbankverbindung, Zeichencodierung
# und Cursor-Typ. Durch Verwendung von Umgebungsvariablen ist die
# Anwendung portabel und sicherer (keine fest eingebetteten Passwörter
# im Quellcode in Produktionsumgebungen).
DB_KONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "Xyz1343!!!"),
    "database": os.getenv("DB_NAME", "ticketsystemabkoo"),
    "charset": "utf8mb4",
    # DictCursor liefert Zeilen als Dict -> leserlicherer Zugriff per Spaltenname
    "cursorclass": pymysql.cursors.DictCursor,
    # Autocommit deaktiviert auf Verbindungsebene, wir verwenden Kontextmanager
    # und commit/rollback explizit, um Konsistenz zu gewährleisten.
    "autocommit": False,
}

# Prioritätswerte für Tickets. Wird an vielen Stellen als "Whitelist"
# für gültige Werte verwendet (UI, Validierung in Service-Schicht).
PRIO_WERTE = ["niedrig", "mittel", "hoch"]


# --------------------
# Infrastruktur: DB-Kontextmanager
# --------------------
class DBVerbindung:
    """Kontextmanager für DB-Verbindung.

    Zweck:
    - Öffnet bei Eintritt in den Kontext eine neue Verbindung zur DB.
    - Stellt sicher, dass bei erfolgreicher Ausführung commit() ausgeführt wird
      und bei Exception ein rollback erfolgt.
    - Schließt die Verbindung am Ende immer.

    Design-Entscheidungen:
    - Die Konfiguration wird beim Instanziieren übergeben (Default: DB_KONFIG).
    - Dadurch ist es einfach, in Tests eine andere DB-Konfiguration zu verwenden.
    """

    def __init__(self, konfig: dict = DB_KONFIG):
        # Konfigurations-Dict auf Instanz speichern, damit __enter__ damit verbinden kann
        self.konfig = konfig
        self.conn = None

    def __enter__(self):
        # Verbindungsaufbau: pymysql.connect wirft bei Fehler eine Exception,
        # welche an den Aufrufer durchgereicht wird. Das ist beabsichtigt:
        # Ein Verbindungsfehler sollte nicht stillschweigend ignoriert werden.
        self.conn = pymysql.connect(**self.konfig)
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        # Ausführen von commit/rollback und schließen der Verbindung.
        # exc_type ist None, falls kein Fehler aufgetreten ist.
        try:
            if exc_type is None:
                # Erfolgreiche Ausführung -> Änderungen persistieren
                self.conn.commit()
            else:
                # Fehler aufgetreten -> Änderungen verwerfen
                self.conn.rollback()
        finally:
            # Verbindung zuverlässig schließen, unabhängig vom Ausgang
            self.conn.close()


# --------------------
# Hilfsfunktionen (Utility)
# --------------------
class Hilfsfunktionen:
    """Sammlung wiederverwendbarer Helper-Funktionen.

    Diese Klasse gruppiert Low-Level-Operationen: Passwort-Hashing/Verifikation,
    vereinfachte DB-Helper für SELECT / DML, sowie Formatierung von Datumswerten.
    Ziel ist, Duplikation zu vermeiden und semantische Klarheit in höheren Schichten
    (Repositories / Services / UI) zu ermöglichen.
    """

    @staticmethod
    def hash_pw_bcrypt(passwort: str) -> str:
        """Erstellt einen bcrypt-Hash aus dem Klartextpasswort.

        Hinweise:
        - bcrypt.gensalt() wählt automatisch einen sicheren Salt und Cost-Faktor.
        - Rückgabewert ist ein bytes-Objekt, das wir zu UTF-8 dekodieren, um es
          problemlos in Textspalten in der DB zu speichern.
        - In Produktionssystemen sollten zusätzliche Policies (z.B. Mindestlänge)
          vor dem Hashing validiert werden.
        """
        return bcrypt.hashpw(passwort.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_pw_bcrypt(passwort: str, gespeicherter_hash: str) -> bool:
        """Prüft ein Klartextpasswort gegen einen gespeicherten bcrypt-Hash.

        - Schützt gegen Exceptions, indem bei Fehlern False zurückgegeben wird.
        - Typische Fehler wären fehlerhafte Hash-Formate oder None-Werte.
        """
        try:
            return bcrypt.checkpw(passwort.encode("utf-8"), gespeicherter_hash.encode("utf-8"))
        except Exception:
            # Bei jeder Exception (z.B. ungültiger Hash) behandeln wir das wie "kein Match"
            return False

    @staticmethod
    def daten_abfragen(sql: str, params: tuple = ()):  # pragma: no cover - DB integration
        """Führt SELECT-Queries aus und liefert alle Zeilen als Liste von Dicts.

        - Verwendet DBVerbindung-Kontextmanager, damit Commit/Rollback und Schließen
          zentral behandelt werden.
        - Erwartet, dass der Aufrufer SQL-Injection durch Prepared Statements
          (Platzhalter %s + params) verhindert.
        - Rückgabewert: Liste von Dictionaries (kann leer sein).
        """
        with DBVerbindung() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()

    @staticmethod
    def query_ausfuehren(sql: str, params: tuple = ()):  # pragma: no cover - DB integration
        """Führt INSERT/UPDATE/DELETE aus und gibt optional lastrowid zurück.

        - Wird für DML-Operationen (Data Manipulation Language) verwendet.
        - Achtung: Bei großen Batch-Operationen sollte ggf. ein dedizierter
          Transaktions- bzw. Batch-Mechanismus verwendet werden.
        """
        with DBVerbindung() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                # Einige Cursor-Implementationen haben lastrowid, andere nicht.
                return getattr(cur, "lastrowid", 0) or 0

    @staticmethod
    def datum_formatieren(dt_wert):
        """Formatiert DB-Datetime zur Anzeige (DD.MM.YYYY HH:MM).

        - Akzeptiert verschiedene Eingabetypen (str, datetime, None) und versucht,
          robust ein lesbares Format zurückzugeben.
        - Wenn ein ISO-Format mit 'Z' (UTC) geliefert wird, wird es korrekt zu einem
          offset-aware datetime geparst.
        - Bei Parsing-Fehlern wird der Originalwert als String zurückgegeben,
          damit die UI nicht komplett abstürzt.
        """
        if not dt_wert:
            return "—"
        try:
            # fromisoformat unterstützt kein 'Z' direkt -> ersetzen mit +00:00
            dt = datetime.fromisoformat(str(dt_wert).replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            # Fallback: Rohwert zurückgeben (z. B. falls DB ein anderes Format verwendet)
            return str(dt_wert)


# --------------------
# Repositories (Datenzugriffsschicht)
# --------------------
# Repositories kapseln reine DB-Operationen. Sie sollten keine Business-Logik
# enthalten, sondern nur CRUD-Operationen (Create, Read, Update, Delete).

class Mitarbeiter:
    """CRUD-Methoden für Tabelle `mitarbeiter`.

    - Methoden sind statisch, damit kein Instanziierungs-Overhead entsteht.
    - Kehrt Datenschemata als Python-Primitive (dict/list) zurück, um die
    - Zusammenarbeit mit Service-/UI-Schichten zu erleichtern.
    """

    @staticmethod
    def mitarbeiter_suchen(username: str) -> Optional[Dict[str, Any]]:
        """Sucht Mitarbeiter anhand Email oder Name (Limit 1).

        - Rückgabe: Dict mit Schlüsseln (id, name, email, password_hash, id_rolle) oder None.
        - Wenn der gefundene Mitarbeiter inaktiv ist (Aktiv != 1), wird None zurückgegeben.
        - Warum Email oder Name? Praktische UX: Login-Feld kann beides akzeptieren.
        """
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
        # Wenn der Benutzer nicht aktiviert ist, behandeln wir ihn wie nicht existent
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
        """Gibt aktive Mitarbeiter zurück (id, username, email).

        - Praktische Helferfunktion für Admin-Listen und Auswahlfelder.
        """
        sql = "SELECT ID_Mitarbeiter AS id, Name AS username, Email AS email FROM mitarbeiter WHERE Aktiv=1 ORDER BY Name"
        return Hilfsfunktionen.daten_abfragen(sql)

    @staticmethod
    def mitarbeiter_erstellen(name: str, email: str, password_hash: str, id_rolle: Optional[int] = None) -> int:
        """Erstellt einen neuen Mitarbeiter und gibt die erzeugte ID zurück.

        - Erwartet bereits gehashten Passwort-Hash (die Hash-Logik gehört in die Service-Schicht).
        - Gibt die DB-ID des neuen Mitarbeiters zurück (oder 0 bei Nichtverfügbarkeit).
        """
        sql = "INSERT INTO mitarbeiter (Name, Email, Password_hash, ID_Rolle) VALUES (%s,%s,%s,%s)"
        return Hilfsfunktionen.query_ausfuehren(sql, (name, email, password_hash, id_rolle))

    @staticmethod
    def mitarbeiter_deaktivieren(mitarbeiter_id: int):
        """Deaktiviert einen Mitarbeiter (soft delete).

        - Setzt Aktiv=0 und schreibt ein Zeitstempel in Geloescht_am.
        - Soft-delete-Prinzip: Historische Referenzen in anderen Tabellen bleiben intakt.
        """
        sql = "UPDATE mitarbeiter SET Aktiv=0, Geloescht_am=NOW() WHERE ID_Mitarbeiter=%s"
        Hilfsfunktionen.query_ausfuehren(sql, (mitarbeiter_id,))


class Ticket:
    """CRUD-Methoden für Tabelle `ticket`.

    - Die Methoden kapseln SQL, so dass Services sich auf Validierung konzentrieren können.
    - Namen enthalten repo_ / hole_ etc., um klar die Schicht zu kennzeichnen.
    """

    @staticmethod
    def repo_ticket_erstellen(titel: str, beschreibung: str, prioritaet: str, id_kunde: Optional[int], ersteller_id: int) -> int:
        """Legt ein neues Ticket an und gibt die erzeugte ID zurück.

        - Setzt sowohl Erstellt_am als auch Geändert_am auf aktuellen UTC-Zeitstempel.
        - ID_Status wird bewusst als NULL gespeichert (z.B. "neu/unassigned").
        - Archiviert-Flag default 0, Geändert_von wird mit dem Ersteller gefüllt.
        """
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
        """Holt Tickets mit optionalen Filtern und join für lesbare Namen.

        - Dynamisches WHERE-Builder-Pattern: nur gesetzte Filter werden zur Query
          hinzugefügt. Das macht die SQL flexibel und vermeidet viele ähnliche
          hartkodierte Queries.
        - Joins auf mitarbeiter sind so gesetzt, dass sowohl Ersteller als auch
          aktuell Bearbeiter lesbar ausgegeben werden können. Falls Spaltenbeziehungen
          falsch sind, müssten die Join-Bedingungen überprüft werden (siehe unten).
        """
        params: List[Any] = []
        where: List[str] = []

        if not archiviert:
            # Standardmäßig nur nicht-archivierte Tickets
            where.append("t.Archiviert = 0")
        if creator_id is not None:
            # Filter nach demjenigen, der das Ticket zuletzt geändert hat
            where.append("t.Geändert_von = %s")
            params.append(creator_id)
        if suchbegriff:
            # Volltext-ähnliche Suche via LIKE (einfache Implementierung)
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
            LEFT JOIN mitarbeiter geaendert ON geaendert.ID_Mitarbeiter = t.ID_Kunde
            LEFT JOIN status s ON s.ID_Status = t.ID_Status
            {where_sql}
            ORDER BY t.Geändert_am DESC
        """
        # WICHTIG: Die Joins oben müssen zur Datenstruktur passen. Wenn z.B. "Ersteller"
        # in einer anderen Spalte gespeichert ist, ist die Join-Bedingung anzupassen.
        return Hilfsfunktionen.daten_abfragen(sql, tuple(params))

    @staticmethod
    def aktualisiere(ticket_id: int, felder: Dict[str, Any]):
        """Aktualisiert Felder eines Tickets und setzt Geändert_am.

        - felder ist ein Dict mapping Spaltennamen -> Werte. Nur übergebene Felder
          werden gesetzt.
        - Fügt automatisch ein Geändert_am-Feld hinzu, damit es immer einen
          Änderungszeitpunkt gibt.
        - Achtung: Der Aufrufer sollte validieren, welche Spalten erlaubt sind.
        """
        if not felder:
            return
        # Setze Änderungszeit automatisch (UTC)
        felder["Geändert_am"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        set_clause = ", ".join(f"{k}=%s" for k in felder.keys())
        params = list(felder.values()) + [ticket_id]
        sql = f"UPDATE ticket SET {set_clause} WHERE ID_Ticket=%s"
        Hilfsfunktionen.query_ausfuehren(sql, tuple(params))

    @staticmethod
    def hole_alle_tickets(archiviert: bool = False) -> List[Dict[str, Any]]:
        """Gibt alle Tickets (roh) zurück, optional nur Archivierte.

        - Diese Methode ist ein einfacher Helfer; für Filter bitte hole_tickets verwenden.
        """
        sql = "SELECT * FROM ticket " + ("WHERE Archiviert=1 " if archiviert else "") + "ORDER BY Geändert_am DESC"
        return Hilfsfunktionen.daten_abfragen(sql)

    @staticmethod
    def statistik() -> Dict[str, int]:
        """Berechnet einfache Ticket-Statistiken (total, offene, archiviert).

        - Diese Kennzahlen sind minimal, können aber leicht erweitert werden
          (z. B. pro Status, pro Priorität, SLA-Berechnungen).
        """
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
# Services sind der Ort für Validierung, Transaktionsgrenzen (falls nötig)
# und Business-Regeln. Sie orchestrieren Repositories und können komplexere
# Operationen durchführen (z.B. mehrere Updates in einer Transaction).

class AuthDienst:
    """Authentifizierungs- und Benutzerverwaltungs-Logik.

    - Trennt Hashing-/DB-Operationen von Auth-Logik.
    - Liefert eine schlanke Repräsentation des Benutzers zurück (id, username, role).
    """

    @staticmethod
    def login(username_oder_email: str, passwort: str) -> Optional[Dict[str, Any]]:
        """Authentifiziert einen Benutzer und liefert user-info bei Erfolg.

        Ablauf:
        1. Benutzer mit Mitarbeiter-Repository suchen
        2. Passwort mit bcrypt prüfen
        3. Falls vorhanden: Rolle (Namen) aus Tabelle rolle lesen
        4. Minimale Benutzerdaten zurückgeben
        """
        mit = Mitarbeiter.mitarbeiter_suchen(username_oder_email.strip())
        if not mit:
            return None
        if Hilfsfunktionen.verify_pw_bcrypt(passwort, mit.get("password_hash", "")):
            # Rolle nachschlagen, falls eine ID vorhanden ist
            rolle_name = None
            if mit.get("id_rolle"):
                r = Hilfsfunktionen.daten_abfragen("SELECT Name FROM rolle WHERE ID_Rolle=%s", (mit.get("id_rolle"),))
                rolle_name = r[0]["Name"] if r else None
            return {"id": mit["id"], "username": mit["name"], "role": rolle_name}
        return None

    @staticmethod
    def erstelle_mitarbeiter(name: str, email: str, passwort: str, id_rolle: Optional[int] = None) -> int:
        """Erstellt neuen Mitarbeiter (Hashing des Passworts).

        - Verantwortlich für Passwort-Hashing, damit das Repository nur persistiert.
        - Gibt ID des neu erstellten Mitarbeiters zurück.
        """
        pw_hash = Hilfsfunktionen.hash_pw_bcrypt(passwort)
        return Mitarbeiter.mitarbeiter_erstellen(name, email, pw_hash, id_rolle)


class TicketDienst:
    """Ticket-bezogene Logik (Erstellen, Listen, Updaten)."""

    @staticmethod
    def svc_ticket_erstellen(titel: str, beschreibung: str, prioritaet: str, id_kunde: Optional[int], ersteller_id: int) -> int:
        """Validiert Priorität und delegiert an das Repository.

        - Wenn eine ungültige Priorität übergeben wird, fällt die Geschäftslogik
          auf 'mittel' zurück (sichere Default-Entscheidung).
        - Zusätzliche Validierungen (z.B. Mindestlänge Titel/Beschreibung) könnten
          hier ergänzt werden.
        """
        if prioritaet not in PRIO_WERTE:
            prioritaet = "mittel"
        return Ticket.repo_ticket_erstellen(titel, beschreibung, prioritaet, id_kunde, ersteller_id)

    @staticmethod
    def liste_tickets(creator_id: Optional[int] = None, archiviert: bool = False,
                      suchbegriff: Optional[str] = None, id_status: Optional[int] = None,
                      prioritaet: Optional[str] = None) -> List[Dict[str, Any]]:
        """Wrapper: liefert Ticketliste mit Filteroptionen (delegiert an Repo)."""
        return Ticket.hole_tickets(creator_id, archiviert, suchbegriff, id_status, prioritaet)

    @staticmethod
    def update_ticket(ticket_id: int, **felder):
        """Wrapper für Ticket-Update - hier könnten zusätzliche Prüfungen
        (Autorisierung, Validierung) ergänzt werden.
        """
        Ticket.aktualisiere(ticket_id, felder)

    @staticmethod
    def stats() -> Dict[str, int]:
        """Gibt Ticket-Statistiken zurück (Wrapper)."""
        return Ticket.statistik()


# --------------------
# Präsentationsschicht (Streamlit UI) - AppUI
# --------------------
# Die UI-Klasse kapselt die Streamlit-seitigen Elemente und macht die App
# testbarer / strukturierter. Die Methoden sind in logische Bereiche unterteilt:
# Login, Ticket-Erstellung, Kanban-Board, Admin-Ansichten, Profil.

class AppUI:
    """Streamlit-Oberfläche

    - Verantwortlich nur für Darstellung und einfache Interaktionslogik.
    - Geschäftslogik (z. B. Erstellen eines Tickets) wird an TicketDienst delegiert.
    """

    def __init__(self):
        # Seitenkonfiguration und minimale CSS-Anpassung
        st.set_page_config(page_title="Ticketsystem", layout="wide", page_icon="🎫")
        st.markdown("""
            <style>
            .stButton button { border-radius: 5px; }
            div[data-testid="stExpander"] { border: 1px solid #ddd; border-radius: 5px; }
            </style>
        """, unsafe_allow_html=True)

    def zeige_statistiken(self):
        """Zeigt Kennzahlen als Metriken.

        - Holt Kennzahlen aus TicketDienst und rendert zwei Metriken nebeneinander.
        - Kann leicht erweitert werden (z. B. Balkendiagramme für Statusverteilung).
        """
        stats = TicketDienst.stats()
        col1, col2 = st.columns(2)
        col1.metric("Gesamt", stats.get("total", 0))
        col2.metric("📦 Archiviert", stats.get("archiviert", 0))
        st.divider()

    def kanban(self, t: Dict[str, Any]):
        """Rendert eine einzelne Ticket-Karte (Kurzinfo) für das Board.

        - Diese Komponente ist bewusst minimal, damit mehrere Karten schnell
        - gerendert werden können.
        - Kürzt die Beschreibung auf 200 Zeichen für übersichtliche Darstellung.
        """
        prio = t.get("Priorität", "-")
        st.markdown(f"**#{t['ID_Ticket']} — {t.get('Titel','-')}**")
        st.caption(f"📁 {t.get('status_name','-')} • ⏰ {Hilfsfunktionen.datum_formatieren(t.get('Geändert_am'))}")
        st.write((t.get("Beschreibung") or "")[:200])
        st.caption(f"👤 {t.get('creator_name','?')}")

    def seite_login(self):
        """Zeigt Login-Formular und führt Authentifizierung durch.

        - Nutzt st.form um geordnetes Submit-Verhalten zu haben (keine Autoupdates).
        - Bei erfolgreichem Login werden user_id, role und username in session_state
          gespeichert. Danach ein st.rerun(), damit die App in den angemeldeten Modus wechselt.
        """
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
                        # Session-State füllen, damit andere Seiten wissen, wer angemeldet ist
                        st.session_state.update({"user_id": user["id"], "role": user["role"], "username": user["username"]})
                        st.success("✅ Erfolgreich angemeldet!")
                        st.rerun()
                    else:
                        st.error("❌ Ungültige Zugangsdaten")

    def ui_ticket_erstellen(self):
        """Formular zum Anlegen eines neuen Tickets (UI layer).

        - Führt Basisvalidierung (Titel+Beschreibung nicht leer) aus.
        - Liest Kundenliste für Auswahlfeld.
        - Bei Erfolg: TicketDienst aufrufen, Erfolgsmeldung zeigen und App neu laden.
        """
        st.header("➕ Neues Ticket erstellen")
        with st.form("create_ticket_form"):
            titel = st.text_input("📝 Titel")
            beschreibung = st.text_area("📄 Beschreibung", height=200)
            col1, col2 = st.columns(2)
            prio = col1.selectbox("⚠️ Priorität", PRIO_WERTE, index=1)
            # Kunden aus DB laden (id, Name) -> für Auswahlfeld
            kunden = Hilfsfunktionen.daten_abfragen("SELECT ID_Kunde AS id, Name FROM kunde ORDER BY Name")
            kundeliste = [None] + [k["id"] for k in kunden]
            kunden_map = {k["id"]: k["Name"] for k in kunden}
            kunde = col2.selectbox("🔎 Kunde", kundeliste, format_func=lambda v: "—" if v is None else kunden_map.get(v, "?"))
            if st.form_submit_button("✅ Ticket anlegen"):
                if not titel or not beschreibung:
                    st.error("❌ Titel und Beschreibung dürfen nicht leer sein.")
                else:
                    # Service aufrufen, übergibt Validierung und Persistenz an Schichten darunter
                    TicketDienst.svc_ticket_erstellen(titel.strip(), beschreibung.strip(), prio, kunde, st.session_state.user_id)
                    st.success("✅ Ticket angelegt!")
                    st.balloons()
                    st.rerun()

    def kanban_seite(self):
        """Zeigt das Kanban-Board mit Filtern und gruppierten Tickets.

        - Filter: Suche, Status, Priorität, Archiv
        - Tickets werden nach Status gruppiert und in drei Spalten verteilt.
        - Achtung: Bei vielen Statuswerten könnte die Spaltenverteilung ungleichmäßig werden.
        """
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

        # Gruppierung nach Status-Name (oder 'Unbekannt')
        gruppiert: Dict[str, List[Dict[str, Any]]] = {}
        for t in tickets:
            key = t.get("status_name") or "Unbekannt"
            gruppiert.setdefault(key, []).append(t)

        # Drei Spalten-Layout für das Kanban-Board
        cols = st.columns(3)
        for idx, (status_name, tlist) in enumerate(gruppiert.items()):
            with cols[idx % 3]:
                st.subheader(f"{status_name} ({len(tlist)})")
                for t in tlist:
                    with st.container():
                        self.kanban(t)
                        c1, c2 = st.columns([1, 3])
                        with c1:
                            # Beispiel-Button um Ticket nach rechts zu bewegen (hier Platzhalter):
                            if st.button("➡️", key=f"right_{t['ID_Ticket']}"):
                                # In dieser Demo setzen wir ID_Status auf None (als Platzhalter).
                                # In einer echten App müsste hier die konkrete Statuslogik implementiert werden.
                                TicketDienst.update_ticket(t["ID_Ticket"], ID_Status=None)
                                st.rerun()
                        with c2:
                            st.caption(f"Letzte Änderung: {Hilfsfunktionen.datum_formatieren(t.get('Geändert_am'))}")

    def tickets_verwalten(self):
        """Admin-Ansicht: Tickets ansehen und editieren.

        - Bietet Inline-Editiermöglichkeiten (Status, Priorität, Bearbeiter, Archiv).
        - Beim Speichern werden die geänderten Felder validiert und persistiert.
        - Achtung: Autorisierungsprüfungen (wer darf was ändern) fehlen und sollten
          in einer echten App ergänzt werden.
        """
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
                # Priorität: index bestimmen (Default: mittel)
                prio_index = PRIO_WERTE.index(t.get("Priorität")) if t.get("Priorität") in PRIO_WERTE else 1
                prio = c2.selectbox("Priorität", PRIO_WERTE, index=prio_index, key=f"pr_{t['ID_Ticket']}")
                cur = t.get("Geändert_von")
                a_index = 0 if cur in (None, 0) else (benutzer_ids.index(cur) if cur in benutzer_ids else 0)
                assignee = c4.selectbox("Bearbeiter", benutzer_ids, index=a_index, format_func=lambda v: "—" if v is None else benutzer_map.get(v, "?"), key=f"as_adm_{t['ID_Ticket']}")
                arch = st.checkbox("📦 Archivieren", value=bool(t.get("Archiviert", 0)), key=f"arch_adm_{t['ID_Ticket']}")

                if st.button("💾 Speichern", key=f"save_adm_{t['ID_Ticket']}"):
                    # Status-ID aus Name ermitteln
                    status_row = Hilfsfunktionen.daten_abfragen("SELECT ID_Status FROM status WHERE Name=%s", (status,))
                    status_id = status_row[0]["ID_Status"] if status_row else None
                    felder = {"ID_Status": status_id, "Priorität": prio, "Geändert_von": assignee, "Archiviert": int(arch)}
                    TicketDienst.update_ticket(t["ID_Ticket"], **felder)
                    st.success("✅ Gespeichert")
                    st.rerun()

    def admin_seite(self):
        """Admin-Benutzerverwaltung: Auflistung, Anlegen, Deaktivieren.

        - Zeigt aktive Benutzer als DataFrame an und bietet Form zur Anlage neuer Benutzer.
        - Deaktivierung ist ein Soft-Delete und schützt davor, dass ein Nutzer
          sich selbst aus Versehen deaktiviert.
        """
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
            # Auswahlbox mit ganzen User-Objekten bietet Zugriff auf id/username im Anschluss
            victim = st.selectbox("Benutzer auswählen", users, format_func=lambda x: x["username"])
            confirm = st.text_input("Zur Bestätigung Benutzernamen erneut eingeben")
            sure = st.checkbox("Ich bin sicher")
            is_self = ("user_id" in st.session_state) and (victim["id"] == st.session_state["user_id"])
            if is_self:
                st.warning("⚠️ Du kannst dich nicht selbst deaktivieren.")
            # Deaktivieren Button ist nur aktiv, wenn Bestätigung korrekt ist und nicht self
            if st.button("🗑️ Benutzer deaktivieren", disabled=is_self or not sure or confirm != victim["username"]):
                Mitarbeiter.mitarbeiter_deaktivieren(victim["id"])
                st.success(f"✅ Benutzer '{victim['username']}' wurde deaktiviert.")
                st.rerun()

    def profil_seite(self):
        """Zeigt Profilinformationen und bietet Logout an.

        - Logout entfernt user-spezifische Keys aus st.session_state und
          führt einen rerun durch, damit die App wieder in den Login-Modus wechselt.
        """
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
    """Entry-Point: baut UI auf und routet zwischen Seiten.

    - Initialisiert AppUI und entscheidet anhand von session_state, welche
      Seite angezeigt werden soll (Login vs. angemeldeter Benutzer).
    """
    app = AppUI()

    # Wenn nicht eingeloggt: Login-Seite zeigen
    if "user_id" not in st.session_state:
        app.seite_login()
        return

    # Sidebar mit Benutzer-Info und Navigation
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
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import bcrypt
import pandas as pd
import pymysql
import streamlit as st


# --------------------
# Konfiguration
# --------------------
# Hier werden zentrale Einstellungen definiert, die für die gesamte
# Anwendung gebraucht werden: Datenbankverbindung, Zeichencodierung
# und Cursor-Typ. Durch Verwendung von Umgebungsvariablen ist die
# Anwendung portabel und sicherer (keine fest eingebetteten Passwörter
# im Quellcode in Produktionsumgebungen).
DB_KONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "Xyz1343!!!"),
    "database": os.getenv("DB_NAME", "ticketsystemabkoo"),
    "charset": "utf8mb4",
    # DictCursor liefert Zeilen als Dict -> leserlicherer Zugriff per Spaltenname
    "cursorclass": pymysql.cursors.DictCursor,
    # Autocommit deaktiviert auf Verbindungsebene, wir verwenden Kontextmanager
    # und commit/rollback explizit, um Konsistenz zu gewährleisten.
    "autocommit": False,
}

# Prioritätswerte für Tickets. Wird an vielen Stellen als "Whitelist"
# für gültige Werte verwendet (UI, Validierung in Service-Schicht).
PRIO_WERTE = ["niedrig", "mittel", "hoch"]


# --------------------
# Infrastruktur: DB-Kontextmanager
# --------------------
class DBVerbindung:
    """Kontextmanager für DB-Verbindung.

    Zweck:
    - Öffnet bei Eintritt in den Kontext eine neue Verbindung zur DB.
    - Stellt sicher, dass bei erfolgreicher Ausführung commit() ausgeführt wird
      und bei Exception ein rollback erfolgt.
    - Schließt die Verbindung am Ende immer.

    Design-Entscheidungen:
    - Die Konfiguration wird beim Instanziieren übergeben (Default: DB_KONFIG).
    - Dadurch ist es einfach, in Tests eine andere DB-Konfiguration zu verwenden.
    """

    def __init__(self, konfig: dict = DB_KONFIG):
        # Konfigurations-Dict auf Instanz speichern, damit __enter__ damit verbinden kann
        self.konfig = konfig
        self.conn = None

    def __enter__(self):
        # Verbindungsaufbau: pymysql.connect wirft bei Fehler eine Exception,
        # welche an den Aufrufer durchgereicht wird. Das ist beabsichtigt:
        # Ein Verbindungsfehler sollte nicht stillschweigend ignoriert werden.
        self.conn = pymysql.connect(**self.konfig)
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        # Ausführen von commit/rollback und schließen der Verbindung.
        # exc_type ist None, falls kein Fehler aufgetreten ist.
        try:
            if exc_type is None:
                # Erfolgreiche Ausführung -> Änderungen persistieren
                self.conn.commit()
            else:
                # Fehler aufgetreten -> Änderungen verwerfen
                self.conn.rollback()
        finally:
            # Verbindung zuverlässig schließen, unabhängig vom Ausgang
            self.conn.close()


# --------------------
# Hilfsfunktionen (Utility)
# --------------------
class Hilfsfunktionen:
    """Sammlung wiederverwendbarer Helper-Funktionen.

    Diese Klasse gruppiert Low-Level-Operationen: Passwort-Hashing/Verifikation,
    vereinfachte DB-Helper für SELECT / DML, sowie Formatierung von Datumswerten.
    Ziel ist, Duplikation zu vermeiden und semantische Klarheit in höheren Schichten
    (Repositories / Services / UI) zu ermöglichen.
    """

    @staticmethod
    def hash_pw_bcrypt(passwort: str) -> str:
        """Erstellt einen bcrypt-Hash aus dem Klartextpasswort.

        Hinweise:
        - bcrypt.gensalt() wählt automatisch einen sicheren Salt und Cost-Faktor.
        - Rückgabewert ist ein bytes-Objekt, das wir zu UTF-8 dekodieren, um es
          problemlos in Textspalten in der DB zu speichern.
        - In Produktionssystemen sollten zusätzliche Policies (z.B. Mindestlänge)
          vor dem Hashing validiert werden.
        """
        return bcrypt.hashpw(passwort.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_pw_bcrypt(passwort: str, gespeicherter_hash: str) -> bool:
        """Prüft ein Klartextpasswort gegen einen gespeicherten bcrypt-Hash.

        - Schützt gegen Exceptions, indem bei Fehlern False zurückgegeben wird.
        - Typische Fehler wären fehlerhafte Hash-Formate oder None-Werte.
        """
        try:
            return bcrypt.checkpw(passwort.encode("utf-8"), gespeicherter_hash.encode("utf-8"))
        except Exception:
            # Bei jeder Exception (z.B. ungültiger Hash) behandeln wir das wie "kein Match"
            return False

    @staticmethod
    def daten_abfragen(sql: str, params: tuple = ()):  # pragma: no cover - DB integration
        """Führt SELECT-Queries aus und liefert alle Zeilen als Liste von Dicts.

        - Verwendet DBVerbindung-Kontextmanager, damit Commit/Rollback und Schließen
          zentral behandelt werden.
        - Erwartet, dass der Aufrufer SQL-Injection durch Prepared Statements
          (Platzhalter %s + params) verhindert.
        - Rückgabewert: Liste von Dictionaries (kann leer sein).
        """
        with DBVerbindung() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()

    @staticmethod
    def query_ausfuehren(sql: str, params: tuple = ()):  # pragma: no cover - DB integration
        """Führt INSERT/UPDATE/DELETE aus und gibt optional lastrowid zurück.

        - Wird für DML-Operationen (Data Manipulation Language) verwendet.
        - Achtung: Bei großen Batch-Operationen sollte ggf. ein dedizierter
          Transaktions- bzw. Batch-Mechanismus verwendet werden.
        """
        with DBVerbindung() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                # Einige Cursor-Implementationen haben lastrowid, andere nicht.
                return getattr(cur, "lastrowid", 0) or 0

    @staticmethod
    def datum_formatieren(dt_wert):
        """Formatiert DB-Datetime zur Anzeige (DD.MM.YYYY HH:MM).

        - Akzeptiert verschiedene Eingabetypen (str, datetime, None) und versucht,
          robust ein lesbares Format zurückzugeben.
        - Wenn ein ISO-Format mit 'Z' (UTC) geliefert wird, wird es korrekt zu einem
          offset-aware datetime geparst.
        - Bei Parsing-Fehlern wird der Originalwert als String zurückgegeben,
          damit die UI nicht komplett abstürzt.
        """
        if not dt_wert:
            return "—"
        try:
            # fromisoformat unterstützt kein 'Z' direkt -> ersetzen mit +00:00
            dt = datetime.fromisoformat(str(dt_wert).replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            # Fallback: Rohwert zurückgeben (z. B. falls DB ein anderes Format verwendet)
            return str(dt_wert)


# --------------------
# Repositories (Datenzugriffsschicht)
# --------------------
# Repositories kapseln reine DB-Operationen. Sie sollten keine Business-Logik
# enthalten, sondern nur CRUD-Operationen (Create, Read, Update, Delete).

class Mitarbeiter:
    """CRUD-Methoden für Tabelle `mitarbeiter`.

    - Methoden sind statisch, damit kein Instanziierungs-Overhead entsteht.
    - Kehrt Datenschemata als Python-Primitive (dict/list) zurück, um die
    - Zusammenarbeit mit Service-/UI-Schichten zu erleichtern.
    """

    @staticmethod
    def mitarbeiter_suchen(username: str) -> Optional[Dict[str, Any]]:
        """Sucht Mitarbeiter anhand Email oder Name (Limit 1).

        - Rückgabe: Dict mit Schlüsseln (id, name, email, password_hash, id_rolle) oder None.
        - Wenn der gefundene Mitarbeiter inaktiv ist (Aktiv != 1), wird None zurückgegeben.
        - Warum Email oder Name? Praktische UX: Login-Feld kann beides akzeptieren.
        """
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
        # Wenn der Benutzer nicht aktiviert ist, behandeln wir ihn wie nicht existent
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
        """Gibt aktive Mitarbeiter zurück (id, username, email).

        - Praktische Helferfunktion für Admin-Listen und Auswahlfelder.
        """
        sql = "SELECT ID_Mitarbeiter AS id, Name AS username, Email AS email FROM mitarbeiter WHERE Aktiv=1 ORDER BY Name"
        return Hilfsfunktionen.daten_abfragen(sql)

    @staticmethod
    def mitarbeiter_erstellen(name: str, email: str, password_hash: str, id_rolle: Optional[int] = None) -> int:
        """Erstellt einen neuen Mitarbeiter und gibt die erzeugte ID zurück.

        - Erwartet bereits gehashten Passwort-Hash (die Hash-Logik gehört in die Service-Schicht).
        - Gibt die DB-ID des neuen Mitarbeiters zurück (oder 0 bei Nichtverfügbarkeit).
        """
        sql = "INSERT INTO mitarbeiter (Name, Email, Password_hash, ID_Rolle) VALUES (%s,%s,%s,%s)"
        return Hilfsfunktionen.query_ausfuehren(sql, (name, email, password_hash, id_rolle))

    @staticmethod
    def mitarbeiter_deaktivieren(mitarbeiter_id: int):
        """Deaktiviert einen Mitarbeiter (soft delete).

        - Setzt Aktiv=0 und schreibt ein Zeitstempel in Geloescht_am.
        - Soft-delete-Prinzip: Historische Referenzen in anderen Tabellen bleiben intakt.
        """
        sql = "UPDATE mitarbeiter SET Aktiv=0, Geloescht_am=NOW() WHERE ID_Mitarbeiter=%s"
        Hilfsfunktionen.query_ausfuehren(sql, (mitarbeiter_id,))


class Ticket:
    """CRUD-Methoden für Tabelle `ticket`.

    - Die Methoden kapseln SQL, so dass Services sich auf Validierung konzentrieren können.
    - Namen enthalten repo_ / hole_ etc., um klar die Schicht zu kennzeichnen.
    """

    @staticmethod
    def repo_ticket_erstellen(titel: str, beschreibung: str, prioritaet: str, id_kunde: Optional[int], ersteller_id: int) -> int:
        """Legt ein neues Ticket an und gibt die erzeugte ID zurück.

        - Setzt sowohl Erstellt_am als auch Geändert_am auf aktuellen UTC-Zeitstempel.
        - ID_Status wird bewusst als NULL gespeichert (z.B. "neu/unassigned").
        - Archiviert-Flag default 0, Geändert_von wird mit dem Ersteller gefüllt.
        """
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
        """Holt Tickets mit optionalen Filtern und join für lesbare Namen.

        - Dynamisches WHERE-Builder-Pattern: nur gesetzte Filter werden zur Query
          hinzugefügt. Das macht die SQL flexibel und vermeidet viele ähnliche
          hartkodierte Queries.
        - Joins auf mitarbeiter sind so gesetzt, dass sowohl Ersteller als auch
          aktuell Bearbeiter lesbar ausgegeben werden können. Falls Spaltenbeziehungen
          falsch sind, müssten die Join-Bedingungen überprüft werden (siehe unten).
        """
        params: List[Any] = []
        where: List[str] = []

        if not archiviert:
            # Standardmäßig nur nicht-archivierte Tickets
            where.append("t.Archiviert = 0")
        if creator_id is not None:
            # Filter nach demjenigen, der das Ticket zuletzt geändert hat
            where.append("t.Geändert_von = %s")
            params.append(creator_id)
        if suchbegriff:
            # Volltext-ähnliche Suche via LIKE (einfache Implementierung)
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
            LEFT JOIN mitarbeiter geaendert ON geaendert.ID_Mitarbeiter = t.ID_Kunde
            LEFT JOIN status s ON s.ID_Status = t.ID_Status
            {where_sql}
            ORDER BY t.Geändert_am DESC
        """
        # WICHTIG: Die Joins oben müssen zur Datenstruktur passen. Wenn z.B. "Ersteller"
        # in einer anderen Spalte gespeichert ist, ist die Join-Bedingung anzupassen.
        return Hilfsfunktionen.daten_abfragen(sql, tuple(params))

    @staticmethod
    def aktualisiere(ticket_id: int, felder: Dict[str, Any]):
        """Aktualisiert Felder eines Tickets und setzt Geändert_am.

        - felder ist ein Dict mapping Spaltennamen -> Werte. Nur übergebene Felder
          werden gesetzt.
        - Fügt automatisch ein Geändert_am-Feld hinzu, damit es immer einen
          Änderungszeitpunkt gibt.
        - Achtung: Der Aufrufer sollte validieren, welche Spalten erlaubt sind.
        """
        if not felder:
            return
        # Setze Änderungszeit automatisch (UTC)
        felder["Geändert_am"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        set_clause = ", ".join(f"{k}=%s" for k in felder.keys())
        params = list(felder.values()) + [ticket_id]
        sql = f"UPDATE ticket SET {set_clause} WHERE ID_Ticket=%s"
        Hilfsfunktionen.query_ausfuehren(sql, tuple(params))

    @staticmethod
    def hole_alle_tickets(archiviert: bool = False) -> List[Dict[str, Any]]:
        """Gibt alle Tickets (roh) zurück, optional nur Archivierte.

        - Diese Methode ist ein einfacher Helfer; für Filter bitte hole_tickets verwenden.
        """
        sql = "SELECT * FROM ticket " + ("WHERE Archiviert=1 " if archiviert else "") + "ORDER BY Geändert_am DESC"
        return Hilfsfunktionen.daten_abfragen(sql)

    @staticmethod
    def statistik() -> Dict[str, int]:
        """Berechnet einfache Ticket-Statistiken (total, offene, archiviert).

        - Diese Kennzahlen sind minimal, können aber leicht erweitert werden
          (z. B. pro Status, pro Priorität, SLA-Berechnungen).
        """
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
# Services sind der Ort für Validierung, Transaktionsgrenzen (falls nötig)
# und Business-Regeln. Sie orchestrieren Repositories und können komplexere
# Operationen durchführen (z.B. mehrere Updates in einer Transaction).

class AuthDienst:
    """Authentifizierungs- und Benutzerverwaltungs-Logik.

    - Trennt Hashing-/DB-Operationen von Auth-Logik.
    - Liefert eine schlanke Repräsentation des Benutzers zurück (id, username, role).
    """

    @staticmethod
    def login(username_oder_email: str, passwort: str) -> Optional[Dict[str, Any]]:
        """Authentifiziert einen Benutzer und liefert user-info bei Erfolg.

        Ablauf:
        1. Benutzer mit Mitarbeiter-Repository suchen
        2. Passwort mit bcrypt prüfen
        3. Falls vorhanden: Rolle (Namen) aus Tabelle rolle lesen
        4. Minimale Benutzerdaten zurückgeben
        """
        mit = Mitarbeiter.mitarbeiter_suchen(username_oder_email.strip())
        if not mit:
            return None
        if Hilfsfunktionen.verify_pw_bcrypt(passwort, mit.get("password_hash", "")):
            # Rolle nachschlagen, falls eine ID vorhanden ist
            rolle_name = None
            if mit.get("id_rolle"):
                r = Hilfsfunktionen.daten_abfragen("SELECT Name FROM rolle WHERE ID_Rolle=%s", (mit.get("id_rolle"),))
                rolle_name = r[0]["Name"] if r else None
            return {"id": mit["id"], "username": mit["name"], "role": rolle_name}
        return None

    @staticmethod
    def erstelle_mitarbeiter(name: str, email: str, passwort: str, id_rolle: Optional[int] = None) -> int:
        """Erstellt neuen Mitarbeiter (Hashing des Passworts).

        - Verantwortlich für Passwort-Hashing, damit das Repository nur persistiert.
        - Gibt ID des neu erstellten Mitarbeiters zurück.
        """
        pw_hash = Hilfsfunktionen.hash_pw_bcrypt(passwort)
        return Mitarbeiter.mitarbeiter_erstellen(name, email, pw_hash, id_rolle)


class TicketDienst:
    """Ticket-bezogene Logik (Erstellen, Listen, Updaten)."""

    @staticmethod
    def svc_ticket_erstellen(titel: str, beschreibung: str, prioritaet: str, id_kunde: Optional[int], ersteller_id: int) -> int:
        """Validiert Priorität und delegiert an das Repository.

        - Wenn eine ungültige Priorität übergeben wird, fällt die Geschäftslogik
          auf 'mittel' zurück (sichere Default-Entscheidung).
        - Zusätzliche Validierungen (z.B. Mindestlänge Titel/Beschreibung) könnten
          hier ergänzt werden.
        """
        if prioritaet not in PRIO_WERTE:
            prioritaet = "mittel"
        return Ticket.repo_ticket_erstellen(titel, beschreibung, prioritaet, id_kunde, ersteller_id)

    @staticmethod
    def liste_tickets(creator_id: Optional[int] = None, archiviert: bool = False,
                      suchbegriff: Optional[str] = None, id_status: Optional[int] = None,
                      prioritaet: Optional[str] = None) -> List[Dict[str, Any]]:
        """Wrapper: liefert Ticketliste mit Filteroptionen (delegiert an Repo)."""
        return Ticket.hole_tickets(creator_id, archiviert, suchbegriff, id_status, prioritaet)

    @staticmethod
    def update_ticket(ticket_id: int, **felder):
        """Wrapper für Ticket-Update - hier könnten zusätzliche Prüfungen
        (Autorisierung, Validierung) ergänzt werden.
        """
        Ticket.aktualisiere(ticket_id, felder)

    @staticmethod
    def stats() -> Dict[str, int]:
        """Gibt Ticket-Statistiken zurück (Wrapper)."""
        return Ticket.statistik()


# --------------------
# Präsentationsschicht (Streamlit UI) - AppUI
# --------------------
# Die UI-Klasse kapselt die Streamlit-seitigen Elemente und macht die App
# testbarer / strukturierter. Die Methoden sind in logische Bereiche unterteilt:
# Login, Ticket-Erstellung, Kanban-Board, Admin-Ansichten, Profil.

class AppUI:
    """Streamlit-Oberfläche

    - Verantwortlich nur für Darstellung und einfache Interaktionslogik.
    - Geschäftslogik (z. B. Erstellen eines Tickets) wird an TicketDienst delegiert.
    """

    def __init__(self):
        # Seitenkonfiguration und minimale CSS-Anpassung
        st.set_page_config(page_title="Ticketsystem", layout="wide", page_icon="🎫")
        st.markdown("""
            <style>
            .stButton button { border-radius: 5px; }
            div[data-testid="stExpander"] { border: 1px solid #ddd; border-radius: 5px; }
            </style>
        """, unsafe_allow_html=True)

    def zeige_statistiken(self):
        """Zeigt Kennzahlen als Metriken.

        - Holt Kennzahlen aus TicketDienst und rendert zwei Metriken nebeneinander.
        - Kann leicht erweitert werden (z. B. Balkendiagramme für Statusverteilung).
        """
        stats = TicketDienst.stats()
        col1, col2 = st.columns(2)
        col1.metric("Gesamt", stats.get("total", 0))
        col2.metric("📦 Archiviert", stats.get("archiviert", 0))
        st.divider()

    def kanban(self, t: Dict[str, Any]):
        """Rendert eine einzelne Ticket-Karte (Kurzinfo) für das Board.

        - Diese Komponente ist bewusst minimal, damit mehrere Karten schnell
        - gerendert werden können.
        - Kürzt die Beschreibung auf 200 Zeichen für übersichtliche Darstellung.
        """
        prio = t.get("Priorität", "-")
        st.markdown(f"**#{t['ID_Ticket']} — {t.get('Titel','-')}**")
        st.caption(f"📁 {t.get('status_name','-')} • ⏰ {Hilfsfunktionen.datum_formatieren(t.get('Geändert_am'))}")
        st.write((t.get("Beschreibung") or "")[:200])
        st.caption(f"👤 {t.get('creator_name','?')}")

    def seite_login(self):
        """Zeigt Login-Formular und führt Authentifizierung durch.

        - Nutzt st.form um geordnetes Submit-Verhalten zu haben (keine Autoupdates).
        - Bei erfolgreichem Login werden user_id, role und username in session_state
          gespeichert. Danach ein st.rerun(), damit die App in den angemeldeten Modus wechselt.
        """
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
                        # Session-State füllen, damit andere Seiten wissen, wer angemeldet ist
                        st.session_state.update({"user_id": user["id"], "role": user["role"], "username": user["username"]})
                        st.success("✅ Erfolgreich angemeldet!")
                        st.rerun()
                    else:
                        st.error("❌ Ungültige Zugangsdaten")

    def ui_ticket_erstellen(self):
        """Formular zum Anlegen eines neuen Tickets (UI layer).

        - Führt Basisvalidierung (Titel+Beschreibung nicht leer) aus.
        - Liest Kundenliste für Auswahlfeld.
        - Bei Erfolg: TicketDienst aufrufen, Erfolgsmeldung zeigen und App neu laden.
        """
        st.header("➕ Neues Ticket erstellen")
        with st.form("create_ticket_form"):
            titel = st.text_input("📝 Titel")
            beschreibung = st.text_area("📄 Beschreibung", height=200)
            col1, col2 = st.columns(2)
            prio = col1.selectbox("⚠️ Priorität", PRIO_WERTE, index=1)
            # Kunden aus DB laden (id, Name) -> für Auswahlfeld
            kunden = Hilfsfunktionen.daten_abfragen("SELECT ID_Kunde AS id, Name FROM kunde ORDER BY Name")
            kundeliste = [None] + [k["id"] for k in kunden]
            kunden_map = {k["id"]: k["Name"] for k in kunden}
            kunde = col2.selectbox("🔎 Kunde", kundeliste, format_func=lambda v: "—" if v is None else kunden_map.get(v, "?"))
            if st.form_submit_button("✅ Ticket anlegen"):
                if not titel or not beschreibung:
                    st.error("❌ Titel und Beschreibung dürfen nicht leer sein.")
                else:
                    # Service aufrufen, übergibt Validierung und Persistenz an Schichten darunter
                    TicketDienst.svc_ticket_erstellen(titel.strip(), beschreibung.strip(), prio, kunde, st.session_state.user_id)
                    st.success("✅ Ticket angelegt!")
                    st.balloons()
                    st.rerun()

    def kanban_seite(self):
        """Zeigt das Kanban-Board mit Filtern und gruppierten Tickets.

        - Filter: Suche, Status, Priorität, Archiv
        - Tickets werden nach Status gruppiert und in drei Spalten verteilt.
        - Achtung: Bei vielen Statuswerten könnte die Spaltenverteilung ungleichmäßig werden.
        """
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

        # Gruppierung nach Status-Name (oder 'Unbekannt')
        gruppiert: Dict[str, List[Dict[str, Any]]] = {}
        for t in tickets:
            key = t.get("status_name") or "Unbekannt"
            gruppiert.setdefault(key, []).append(t)

        # Drei Spalten-Layout für das Kanban-Board
        cols = st.columns(3)
        for idx, (status_name, tlist) in enumerate(gruppiert.items()):
            with cols[idx % 3]:
                st.subheader(f"{status_name} ({len(tlist)})")
                for t in tlist:
                    with st.container():
                        self.kanban(t)
                        c1, c2 = st.columns([1, 3])
                        with c1:
                            # Beispiel-Button um Ticket nach rechts zu bewegen (hier Platzhalter):
                            if st.button("➡️", key=f"right_{t['ID_Ticket']}"):
                                # In dieser Demo setzen wir ID_Status auf None (als Platzhalter).
                                # In einer echten App müsste hier die konkrete Statuslogik implementiert werden.
                                TicketDienst.update_ticket(t["ID_Ticket"], ID_Status=None)
                                st.rerun()
                        with c2:
                            st.caption(f"Letzte Änderung: {Hilfsfunktionen.datum_formatieren(t.get('Geändert_am'))}")

    def tickets_verwalten(self):
        """Admin-Ansicht: Tickets ansehen und editieren.

        - Bietet Inline-Editiermöglichkeiten (Status, Priorität, Bearbeiter, Archiv).
        - Beim Speichern werden die geänderten Felder validiert und persistiert.
        - Achtung: Autorisierungsprüfungen (wer darf was ändern) fehlen und sollten
          in einer echten App ergänzt werden.
        """
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
                # Priorität: index bestimmen (Default: mittel)
                prio_index = PRIO_WERTE.index(t.get("Priorität")) if t.get("Priorität") in PRIO_WERTE else 1
                prio = c2.selectbox("Priorität", PRIO_WERTE, index=prio_index, key=f"pr_{t['ID_Ticket']}")
                cur = t.get("Geändert_von")
                a_index = 0 if cur in (None, 0) else (benutzer_ids.index(cur) if cur in benutzer_ids else 0)
                assignee = c4.selectbox("Bearbeiter", benutzer_ids, index=a_index, format_func=lambda v: "—" if v is None else benutzer_map.get(v, "?"), key=f"as_adm_{t['ID_Ticket']}")
                arch = st.checkbox("📦 Archivieren", value=bool(t.get("Archiviert", 0)), key=f"arch_adm_{t['ID_Ticket']}")

                if st.button("💾 Speichern", key=f"save_adm_{t['ID_Ticket']}"):
                    # Status-ID aus Name ermitteln
                    status_row = Hilfsfunktionen.daten_abfragen("SELECT ID_Status FROM status WHERE Name=%s", (status,))
                    status_id = status_row[0]["ID_Status"] if status_row else None
                    felder = {"ID_Status": status_id, "Priorität": prio, "Geändert_von": assignee, "Archiviert": int(arch)}
                    TicketDienst.update_ticket(t["ID_Ticket"], **felder)
                    st.success("✅ Gespeichert")
                    st.rerun()

    def admin_seite(self):
        """Admin-Benutzerverwaltung: Auflistung, Anlegen, Deaktivieren.

        - Zeigt aktive Benutzer als DataFrame an und bietet Form zur Anlage neuer Benutzer.
        - Deaktivierung ist ein Soft-Delete und schützt davor, dass ein Nutzer
          sich selbst aus Versehen deaktiviert.
        """
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
            # Auswahlbox mit ganzen User-Objekten bietet Zugriff auf id/username im Anschluss
            victim = st.selectbox("Benutzer auswählen", users, format_func=lambda x: x["username"])
            confirm = st.text_input("Zur Bestätigung Benutzernamen erneut eingeben")
            sure = st.checkbox("Ich bin sicher")
            is_self = ("user_id" in st.session_state) and (victim["id"] == st.session_state["user_id"])
            if is_self:
                st.warning("⚠️ Du kannst dich nicht selbst deaktivieren.")
            # Deaktivieren Button ist nur aktiv, wenn Bestätigung korrekt ist und nicht self
            if st.button("🗑️ Benutzer deaktivieren", disabled=is_self or not sure or confirm != victim["username"]):
                Mitarbeiter.mitarbeiter_deaktivieren(victim["id"])
                st.success(f"✅ Benutzer '{victim['username']}' wurde deaktiviert.")
                st.rerun()

    def profil_seite(self):
        """Zeigt Profilinformationen und bietet Logout an.

        - Logout entfernt user-spezifische Keys aus st.session_state und
          führt einen rerun durch, damit die App wieder in den Login-Modus wechselt.
        """
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

    # Login zuerst abfragen, ohne UI-Duplikat zu erzeugen
    if "user_id" not in st.session_state:
        app = AppUI()
        app.seite_login()
        return

    # Ab hier ist man eingeloggt → AppUI erzeugen
    app = AppUI()

    st.sidebar.title("🎫 Ticketsystem")
    st.sidebar.markdown(f"**👤 Benutzer:** {st.session_state.get('username','-')}")
    st.sidebar.markdown(f"**🛡️ Rolle:** {st.session_state.get('role','-')}")
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

    # Routing
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
