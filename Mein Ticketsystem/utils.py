#utils.py - Hilfsfunktionen für das Ticketsystem
import bcrypt
from datetime import datetime, timezone


def hash_pw_bcrypt(passwort: str) -> str:
    """Erstellt einen bcrypt-Hash aus dem Klartextpasswort."""
    return bcrypt.hashpw(
        passwort.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

def verify_pw_bcrypt(passwort: str, gespeicherter_hash: str) -> bool:
    """Prüft ein Klartextpasswort gegen einen gespeicherten bcrypt-Hash."""
    try:
        return bcrypt.checkpw(
            passwort.encode("utf-8"),
            gespeicherter_hash.encode("utf-8")
        )
    except Exception:
        return False



def datum_formatieren(dt_wert):
    """Formatiert DB-Datetime zur Anzeige (DD.MM.YYYY HH:MM)."""
    if not dt_wert:
        return "—"
    try:
        dt = datetime.fromisoformat(
            str(dt_wert).replace("Z", "+00:00")
        )
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(dt_wert)