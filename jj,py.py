from tinydb import TinyDB
from datetime import datetime, timezone
import bcrypt

DB_PATH = "tickets_nosql.json"

def _iso(dt):
    if dt is None:
        return None
    return dt.replace(" ", "T") + "+00:00"

db = TinyDB(DB_PATH)
users = db.table("users")
tickets = db.table("tickets")


# ----------------------
# USERS aus MySQL Dump
# ----------------------
users_data = [
    (1, "admin", "$2b$12$5FJabMhmhO6opEQddkeUe.A/vWewksnzdQUg/vAu4GAmZWI.u4Fm.", "admin", 1, None),
    (2, "alice", "$2b$12$Ed5JT1fQ1raQ8xGCOGe9sutXFfUrc6M/qn3EeubiQK7Hqs1jiQw5G", "user", 0, "2025-10-27 16:41:58"),
    (3, "bob", "$2b$12$A8oR9V7nF3yCl0.zOXAPbOMpw0FeWJ6gMoGaS4tzRkXt8lvqySiO6", "user", 1, None),
    (4, "joel", "$2b$12$BaR8EuzD9Vh/QGtrvcC6o.Gwm7fFNgeqxp3PBRXE9fhm1hqHTI1Zq", "admin", 0, "2025-10-27 17:51:11"),
    (5, "jigi", "$2b$12$46QAH6k4gYJyzYzW/iTk1.OgUu2Yt71DfF9eGVRO2Cq0m/11pI6Je", "admin", 1, None),
    (6, "fsf", "$2b$12$g2NP2zU5d56REOUKzsnloOpz7qY6.pQenDpsSka1m0J2gQdaK0ThK", "user", 0, "2025-11-02 11:33:22"),
    (7, "gg", "$2b$12$GHZsQ6e3lpE1sA3luDPPK.UTS7EsA6d42nTxlG8bhlZfHo3PCTKpm", "user", 1, None),
]

for u in users_data:
    users.insert({
        "old_id": u[0],
        "username": u[1],
        "password_hash": u[2],
        "role": u[3],
        "active": u[4],
        "created_at": _iso(u[5]),
        "deleted_at": None
    })


# ----------------------
# TICKETS aus MySQL Dump
# ----------------------
tickets_data = [
    (1,"Laptop startet nicht","Bildschirm bleibt beim Einschalten schwarz.","Hardware","Neu","Hoch",2,1,"2025-10-25 11:40:21","2025-10-27 16:58:18",1),
    (2,"VPN instabil","Verbindung bricht alle 5 Minuten ab.","Netzwerk","Neu","Normal",2,3,"2025-10-25 11:40:21","2025-10-27 19:05:17",0),
    (3,"XApp Fehler 42","Update stoppt bei 70% mit Fehler 42.","Software","Gelöst","Niedrig",3,1,"2025-10-25 11:40:21","2025-11-20 09:54:08",0),
    (4,"Drucker Papierstau","Papierstau im 2.OG.","Hardware","Geschlossen","Normal",2,1,"2025-10-25 11:40:21","2025-11-20 09:54:03",0),
    (5,"Neuer Monitor","Anfrage für 27\" Monitor.","Sonstiges","Geschlossen","Niedrig",3,None,"2025-10-25 11:40:21","2025-10-25 11:40:21",1),
    (6,"ughbuhg","uihguhiuh","Hardware","Warten auf Benutzer","Normal",1,None,"2025-10-27 15:35:33","2025-11-20 09:52:43",1),
    (7,"kabel kaputt","so ischs lebe ebe","Hardware","Geschlossen","Normal",1,None,"2025-10-27 19:05:42","2025-11-20 09:52:44",1),
    (8,"adfff","sdffsad","Hardware","Neu","Normal",1,None,"2025-11-02 10:32:37","2025-11-20 09:52:35",1),
    (9,"thh","rthhh","Hardware","In Bearbeitung","Normal",1,None,"2025-11-02 11:27:43","2025-11-20 09:52:41",1),
    (10,"vv","vv","Hardware","Neu","Normal",1,None,"2025-11-02 11:42:11","2025-11-20 09:52:37",1),
    (11,"ggggg","ggggggggggggggggggggggggggggggg","Hardware","Neu","Normal",1,None,"2025-11-05 18:51:05","2025-11-20 09:52:38",1),
    (12,"Windows Update Problem","Fehler beim Update","Software","In Bearbeitung","Hoch",1,None,"2025-11-20 09:53:13","2025-11-20 09:54:11",0),
    (13,"Fax Gerät kaputt","Senden geht nicht","Hardware","Warten auf Benutzer","Kritisch",1,None,"2025-11-20 09:53:50","2025-11-20 09:54:09",0)
]

for t in tickets_data:
    tickets.insert({
        "old_id": t[0],
        "title": t[1],
        "description": t[2],
        "category": t[3],
        "status": t[4],
        "priority": t[5],
        "creator_id": t[6],
        "assignee_id": t[7],
        "created_at": _iso(t[8]),
        "updated_at": _iso(t[9]),
        "archived": t[10]
    })

print("🚀 Import abgeschlossen – alle Daten aus MySQL Dump wurden in TinyDB übernommen.")
