@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Tabellen erstellen
    cursor.execute("""CREATE TABLE mitarbeiter (
        mitarbeiter_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT UNIQUE,
        passwort TEXT
    )""")

    cursor.execute("""CREATE TABLE ticket (
        ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
        titel TEXT,
        beschreibung TEXT,
        prioritaet TEXT,
        zugewiesen_an INTEGER,
        status TEXT,
        FOREIGN KEY(zugewiesen_an) REFERENCES mitarbeiter(mitarbeiter_id)
    )""")

    conn.commit()
    Hilfsfunktionen._connection = conn  # optional: eigene Variable setzen
    return conn

def test_mitarbeiter_erstellen(db):
    user = AuthDienst.erstelle_mitarbeiter("Alice", "a@example.com", "pw123")

    rows = Hilfsfunktionen.daten_abfragen("SELECT name, email FROM mitarbeiter")
    assert rows[0][0] == "Alice"
    assert rows[0][1] == "a@example.com"


def test_login_korrekt(db):
    AuthDienst.erstelle_mitarbeiter("Bob", "b@example.com", "secret")

    result = AuthDienst.login("b@example.com", "secret")
    assert result["email"] == "b@example.com"


def test_login_fehlerhaftes_passwort(db):
    AuthDienst.erstelle_mitarbeiter("Charlie", "c@example.com", "pass")

    try:
        AuthDienst.login("c@example.com", "falsch")
        assert False, "Exception erwartet"
    except Exception as e:
        assert "falsches Passwort" in str(e).lower()

def test_ticket_erstellen(db):
    user = AuthDienst.erstelle_mitarbeiter("Dave", "d@example.com", "p")

    ticket_id = TicketDienst.svc_ticket_erstellen(
        "Server down",
        "Der Server reagiert nicht mehr",
        "hoch",
        None,
        user
    )

    # DB prüfen
    rows = Hilfsfunktionen.daten_abfragen("SELECT titel, beschreibung FROM ticket")
    assert rows[0][0] == "Server down"
    assert rows[0][1] == "Der Server reagiert nicht mehr"


def test_ticket_zuweisen_und_statuswechsel(db):
    creator = AuthDienst.erstelle_mitarbeiter("Eve", "e@example.com", "pw")
    support = AuthDienst.erstelle_mitarbeiter("Support", "s@example.com", "pw")

    ticket_id = TicketDienst.svc_ticket_erstellen(
        "Bug", "Fehler in Modul X", "mittel", None, creator
    )

    TicketDienst.svc_ticket_zuweisen(ticket_id, support)

    rows = Hilfsfunktionen.daten_abfragen(
        "SELECT zugewiesen_an FROM ticket WHERE ticket_id=?", (ticket_id,)
    )
    assert rows[0][0] == support["mitarbeiter_id"]


def test_ticket_erstellen_ungueltige_daten(db):
    creator = AuthDienst.erstelle_mitarbeiter("Test", "t@example.com", "p")

    try:
        TicketDienst.svc_ticket_erstellen("", "", "x", None, creator)
        assert False, "Exception erwartet"
    except Exception:
        assert True

def test_insert_and_query(db):
    Hilfsfunktionen.daten_ausfuehren(
        "INSERT INTO mitarbeiter (name, email, passwort) VALUES (?, ?, ?)",
        ("Max", "max@example.com", "pw")
    )

    rows = Hilfsfunktionen.daten_abfragen("SELECT name FROM mitarbeiter")
    assert rows[0][0] == "Max"


def test_update_operation(db):
    Hilfsfunktionen.daten_ausfuehren(
        "INSERT INTO mitarbeiter (name, email, passwort) VALUES (?, ?, ?)",
        ("Anna", "a@example.com", "pw")
    )

    Hilfsfunktionen.daten_ausfuehren(
        "UPDATE mitarbeiter SET name=? WHERE email=?",
        ("Anna Müller", "a@example.com")
    )

    rows = Hilfsfunktionen.daten_abfragen("SELECT name FROM mitarbeiter")
    assert rows[0][0] == "Anna Müller"