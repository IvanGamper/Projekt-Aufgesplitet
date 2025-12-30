# services.py
from typing import Any, Dict, List, Optional
from utils import hash_pw_bcrypt, verify_pw_bcrypt
from db import daten_abfragen, query_ausfuehren, DBVerbindung, Ticket, Mitarbeiter

PRIO_WERTE = [
    "niedrig",
    "mittel",
    "hoch"
]

KANBAN_STATUS = [
    "Neu",
    "In Bearbeitung",
    "Warten auf Benutzer",
    "Gelöst",
    "Geschlossen",
]

NEXT_STATUS = {
    "Neu": "In Bearbeitung",
    "In Bearbeitung": "Warten auf Benutzer",
    "Warten auf Benutzer": "Gelöst",
    "Gelöst": "Geschlossen",
}

PREV_STATUS = {
    "Geschlossen": "Gelöst",
    "Gelöst": "Warten auf Benutzer",
    "Warten auf Benutzer": "In Bearbeitung",
    "In Bearbeitung": "Neu",
}

class AuthDienst:
    """Authentifizierungs- und Benutzerverwaltungs-Logik."""

    @staticmethod
    def login(
            username_oder_email: str,
            passwort: str
    ) -> Optional[Dict[str, Any]]:
        """Authentifiziert einen Benutzer und liefert user-info bei Erfolg."""

        mit = Mitarbeiter.mitarbeiter_suchen(
            username_oder_email.strip()
        )

        if not mit:
            return None

        if verify_pw_bcrypt(
                passwort,
                mit.get("password_hash", "")
        ):
            rolle_name = None

            if mit.get("id_rolle"):
                r = daten_abfragen(
                    "SELECT Name FROM rolle WHERE ID_Rolle=%s",
                    (mit.get("id_rolle"),)
                )
                rolle_name = r[0]["Name"] if r else None

            return {
                "id": mit["id"],
                "username": mit["name"],
                "role": rolle_name
            }

        return None

    @staticmethod
    def erstelle_mitarbeiter(
            name: str,
            email: str,
            passwort: str,
            id_rolle: Optional[int] = None
    ) -> int:
        """Erstellt neuen Mitarbeiter (Hashing des Passworts)."""

        pw_hash = hash_pw_bcrypt(passwort)

        return Mitarbeiter.mitarbeiter_erstellen(
            name,
            email,
            pw_hash,
            id_rolle
        )

class TicketDienst:
    """Ticket-bezogene Logik (Erstellen, Listen, Updaten)."""

    @staticmethod
    def svc_ticket_erstellen(
            titel: str,
            beschreibung: str,
            prioritaet: str,
            id_kunde: Optional[int],
            ersteller_id: int
    ) -> int:
        """Validiert Priorität und delegiert an das Repository (Service layer)."""

        if prioritaet not in PRIO_WERTE:
            prioritaet = "mittel"

        return Ticket.repo_ticket_erstellen(
            titel,
            beschreibung,
            prioritaet,
            id_kunde,
            ersteller_id
        )

    @staticmethod
    def liste_tickets(
            creator_id: Optional[int] = None,
            archiviert: bool = False,
            suchbegriff: Optional[str] = None,
            id_status: Optional[int] = None,
            prioritaet: Optional[str] = None) -> List[Dict[str, Any]]:
        """Wrapper: liefert Ticketliste mit Filteroptionen."""
        return Ticket.hole_tickets(creator_id, archiviert, suchbegriff, id_status, prioritaet)

    @staticmethod
    def update_ticket(
            ticket_id: int,
            **felder
    ):
        """Wrapper für Ticket-Update."""
        Ticket.aktualisiere(ticket_id, felder)

    @staticmethod
    def stats() -> Dict[str, int]:
        """Gibt Ticket-Statistiken zurück."""
        return Ticket.statistik()

__all__ = [
    "AuthDienst",
    "TicketDienst",
    "PRIO_WERTE",
    "KANBAN_STATUS",
    "NEXT_STATUS",
    "PREV_STATUS",
]
