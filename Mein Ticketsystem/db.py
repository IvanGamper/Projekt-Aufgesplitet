# db.py - Datenbankzugriff für Ticketsystem
import os
import pymysql
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


# Konfiguration

DB_KONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "Xyz1343!!!"),
    "database": os.getenv("DB_NAME", "ticketsystemabkoo13"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}


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

def daten_abfragen(sql: str, params: tuple = ()):
    """Führt SELECT-Query aus und liefert alle Zeilen als Liste von Dicts."""
    with DBVerbindung() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)

            return cur.fetchall()


def query_ausfuehren(sql: str, params: tuple = ()):
    """Führt INSERT/UPDATE/DELETE aus. Gibt ggf. lastrowid zurück."""
    with DBVerbindung() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)

            return getattr(cur, "lastrowid", 0) or 0

# Repositories (Datenzugriff)

class Mitarbeiter:
    """CRUD-Methoden für Tabelle `mitarbeiter`."""

    @staticmethod
    def mitarbeiter_suchen(username: str) -> Optional[Dict[str, Any]]:
        """Sucht Mitarbeiter anhand Email oder Name (Limit 1)."""
        sql = """
              SELECT
                  ID_Mitarbeiter,
                  Name,
                  Email,
                  Password_hash,
                  Aktiv,
                  ID_Rolle
              FROM mitarbeiter
              WHERE Email=%s OR Name=%s
                  LIMIT 1 \
              """

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
        sql = """
              SELECT
                  ID_Mitarbeiter AS id,
                  Name AS username,
                  Email AS email
              FROM mitarbeiter
              WHERE Aktiv=1
              ORDER BY Name \
              """

        return daten_abfragen(sql)

    @staticmethod
    def mitarbeiter_erstellen(
            name: str,
            email: str,
            password_hash: str,
            id_rolle: Optional[int] = None,
    )-> int:
        """Erstellt neuen Mitarbeiter und gibt ID zurück."""
        sql = """
              INSERT INTO mitarbeiter (
                  Name,
                  Email,
                  Password_hash,
                  ID_Rolle
              )
              VALUES (%s,%s,%s,%s) \
              """

        return query_ausfuehren(
            sql,
            (name, email, password_hash, id_rolle),
        )

    @staticmethod
    def mitarbeiter_deaktivieren(mitarbeiter_id: int):
        """Deaktiviert einen Mitarbeiter (soft delete)."""
        sql = """
              UPDATE mitarbeiter
              SET Aktiv=0,
                  Geloescht_am=NOW()
              WHERE ID_Mitarbeiter=%s \
              """
        query_ausfuehren(sql, (mitarbeiter_id,))

#Repositories: Ticket
class Ticket:
    """CRUD-Methoden für Tabelle `ticket`."""

    @staticmethod
    def repo_ticket_erstellen(
            titel: str,
            beschreibung: str,
            prioritaet: str,
            id_kunde: Optional[int],
            ersteller_id: int,
    ) -> int:
        """Legt ein neues Ticket an und gibt die erzeugte ID zurück. (Repository layer)"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        sql = """
              INSERT INTO ticket (
                  Titel,
                  Beschreibung,
                  Priorität,
                  ID_Status,
                  ID_Kunde,
                  Erstellt_am,
                  Geändert_am,
                  Archiviert,
                  Geändert_von
              )
              VALUES (%s,%s,%s,NULL,%s,%s,%s,0,%s) \
              """

        return query_ausfuehren(
            sql,
            (
                titel,
                beschreibung,
                prioritaet,
                id_kunde,
                now,
                now,
                ersteller_id,
            ),
        )

    @staticmethod
    def hole_tickets(
            creator_id: Optional[int] = None,
            archiviert: bool = False,
            suchbegriff: Optional[str] = None,
            id_status: Optional[int] = None,
            prioritaet: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Holt Tickets mit optionalen Filtern und join für lesbare Namen."""
        params: List[Any] = []
        where: List[str] = []

        #Filter

        if not archiviert:
            where.append("t.Archiviert = 0")

        if creator_id is not None:
            where.append("t.Geändert_von = %s")
            params.append(creator_id)

        if suchbegriff:
            where.append(
                "(t.Titel LIKE %s OR t.Beschreibung LIKE %s)"
            )
            params.extend([
                f"%{suchbegriff}%",
                f"%{suchbegriff}%"
            ])

        if id_status is not None:
            where.append("t.ID_Status = %s")
            params.append(id_status)

        if prioritaet:
            where.append("t.Priorität = %s")
            params.append(prioritaet)

        where_sql = (
            "WHERE " + " AND ".join(where)
            if where else ""
        )

        sql = f"""
        SELECT
            t.*,
            ersteller.Name      AS creator_name,
            geaendert.Name      AS assignee_name,
            s.Name              AS status_name
        FROM ticket t
        LEFT JOIN mitarbeiter ersteller 
            ON ersteller.ID_Mitarbeiter = t.Geändert_von
        LEFT JOIN mitarbeiter geaendert 
            ON geaendert.ID_Mitarbeiter = t.Geändert_von
        LEFT JOIN status s 
            ON s.ID_Status = t.ID_Status
        {where_sql}
        ORDER BY t.Geändert_am DESC
        """

        return daten_abfragen(
            sql,
            tuple(params)
        )

    @staticmethod
    def aktualisiere(ticket_id: int, felder: Dict[str, Any]):
        """Aktualisiert Felder eines Tickets und setzt Geändert_am."""

        if not felder:
            return

        felder["Geändert_am"] = datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S")

        set_clause = ", ".join(
            f"{k}=%s"
            for k in felder.keys()
        )

        params = (
                list(felder.values())
                + [ticket_id]
        )

        sql = f"""
        UPDATE ticket 
        SET {set_clause} 
        WHERE ID_Ticket=%s
        """

        query_ausfuehren(
            sql,
            tuple(params)
        )

    @staticmethod
    def hole_alle_tickets(
            archiviert: bool = False
    )-> List[Dict[str, Any]]:
        """Gibt alle Tickets (roh) zurück, optional nur Archivierte."""

        sql = (
                "SELECT * "
                "FROM ticket "
                + ("WHERE Archiviert=1 " if archiviert else "")
                + "ORDER BY Geändert_am DESC"
        )

        return daten_abfragen(sql)

    @staticmethod
    def statistik() -> Dict[str, int]:
        """Berechnet einfache Ticket-Statistiken (total, offene, archiviert)."""
        sql = """
              SELECT
                  COUNT(*) as total,
                  SUM(
                          CASE
                              WHEN ID_Status IS NULL
                                  THEN 1
                              ELSE 0
                              END
                  )as offene,
                  SUM(
                          CASE
                              WHEN Archiviert = 1
                                  THEN 1
                              ELSE 0
                              END
                  ) as archiviert
              FROM ticket \
              """

        rows = daten_abfragen(sql)
        return rows[0] if rows else {}

__all__ = [
    "DBVerbindung",
    "daten_abfragen",
    "query_ausfuehren",
    "Mitarbeiter",
    "Ticket",
]





