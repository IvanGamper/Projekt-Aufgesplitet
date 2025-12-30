#app.py
from typing import Any, Dict, List
import pandas as pd
import streamlit as st

from services import (
    TicketDienst,
    AuthDienst,
    PRIO_WERTE,
    KANBAN_STATUS, 
    NEXT_STATUS,
    PREV_STATUS,
)
from utils import datum_formatieren
from db import Mitarbeiter, daten_abfragen


class AppUI:
    """Streamlit-Oberfläche"""

    def __init__(self):
        st.set_page_config(
            page_title="Ticketsystem",
            layout="wide",
            page_icon="🎫"
        )

        st.markdown(
            """
            <style>
                .stButton button { 
                    border-radius: 5px; 
                }
                div[data-testid="stExpander"] { 
                    border: 1px solid #ddd; 
                    border-radius: 5px; 
                }
            </style>
            """,
            unsafe_allow_html=True
        )

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

        st.markdown(
            f"**#{t['ID_Ticket']} — {t.get('Titel','-')}**"
        )

        st.caption(
            f"📁 {t.get('status_name','-')} • "
            f"⏰ {datum_formatieren(t.get('Geändert_am'))}"
        )
        st.write(
            (t.get("Beschreibung") or "")[:200]
        )

        st.caption(
            f"👤 {t.get('creator_name','?')}"
        )

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
                        st.session_state.update(
                            {
                                "user_id": user["id"],
                                "role": user["role"],
                                "username": user["username"]
                            }
                        )
                        st.success("✅ Erfolgreich angemeldet!")
                        st.rerun()
                    else:
                        st.error("❌ Ungültige Zugangsdaten")

    def ui_ticket_erstellen(self):
        """Formular zum Anlegen eines neuen Tickets (UI layer)."""

        st.header("➕ Neues Ticket erstellen")

        with st.form("create_ticket_form"):
            titel = st.text_input("📝 Titel")
            beschreibung = st.text_area(
                "📄 Beschreibung",
                height=200
            )

            col1, col2 = st.columns(2)

            prio = col1.selectbox(
                "⚠️ Priorität",
                PRIO_WERTE,
                index=1
            )

            kunden = daten_abfragen(
                "SELECT ID_Kunde AS id, Name FROM kunde ORDER BY Name"
            )

            kundeliste = [None] + [k["id"] for k in kunden]
            kunden_map = {k["id"]: k["Name"] for k in kunden}

            kunde = col2.selectbox(
                "🔎 Kunde",
                kundeliste,
                format_func=lambda v: "—" if v is None else kunden_map.get(v, "?"),
            )

            if st.form_submit_button("✅ Ticket anlegen"):
                if not titel or not beschreibung:
                    st.error(
                        "❌ Titel und Beschreibung dürfen nicht leer sein."
                    )
                else:
                    TicketDienst.svc_ticket_erstellen(
                        titel.strip(),
                        beschreibung.strip(),
                        prio, kunde,
                        st.session_state.user_id,
                    )
                    st.success("✅ Ticket angelegt!")
                    st.balloons()
                    st.rerun()

    def kanban_seite(self):
        """Zeigt das Kanban-Board mit Filtern und gruppierten Tickets."""
        st.header("🎫 Ticket Kanban-Board")
        self.zeige_statistiken()

        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

        suchtext = col1.text_input("🔍 Suche")

        statusliste = daten_abfragen(
            "SELECT ID_Status AS id, Name FROM status ORDER BY ID_Status"
        )
        filter_status = col2.selectbox(
            "📁 Status",
            ["Alle"] + [s["Name"] for s in statusliste],
            )

        filter_prio = col3.selectbox(
            "⚠️ Priorität",
            ["Alle"] + PRIO_WERTE,
            )
        zeige_arch = col4.checkbox("📦 Archiv")

        id_status = (
            None
            if filter_status == "Alle"
            else next(
                (s["id"] for s in statusliste if s["Name"] == filter_status),
                None,
            )
        )

        prior = None if filter_prio == "Alle" else filter_prio

        tickets = TicketDienst.liste_tickets(
            archiviert=zeige_arch,
            suchbegriff=suchtext or None,
            id_status=id_status,
            prioritaet=prior,
        )

        if not tickets:
            st.info("ℹ️ Keine Tickets gefunden.")
            return

        # ---------------------------
        # KANBAN: feste Spalten
        # ---------------------------
        gruppiert: Dict[str, List[Dict[str, Any]]] = {
            s: [] for s in KANBAN_STATUS
        }

        for t in tickets:
            status = t.get("status_name") or "Neu"
            if status not in gruppiert:
                status = "Neu"
            gruppiert[status].append(t)

        cols = st.columns(len(KANBAN_STATUS))

        for idx, status in enumerate(KANBAN_STATUS):
            with cols[idx]:
                st.subheader(f"{status} ({len(gruppiert[status])})")

                if not gruppiert[status]:
                    st.caption("— keine Tickets —")

                for t in gruppiert[status]:
                    with st.container():
                        self.kanban(t)

                        # ---------------------------
                        # Status-Buttons (Kanban)
                        # ---------------------------
                        btn_left, btn_right = st.columns(2)

                        # ⬅️ Zurück
                        if status in PREV_STATUS:
                            if btn_left.button("⬅️", key=f"prev_{t['ID_Ticket']}"):
                                status_id = daten_abfragen(
                                    "SELECT ID_Status FROM status WHERE Name=%s",
                                    (PREV_STATUS[status],),
                                )[0]["ID_Status"]

                                TicketDienst.update_ticket(
                                    t["ID_Ticket"],
                                    ID_Status=status_id,
                                    Geändert_von=st.session_state.user_id,
                                )
                                st.rerun()

                        # ➡️ Weiter
                        if status in NEXT_STATUS:
                            if btn_right.button("➡️", key=f"next_{t['ID_Ticket']}"):
                                status_id = daten_abfragen(
                                    "SELECT ID_Status FROM status WHERE Name=%s",
                                    (NEXT_STATUS[status],),
                                )[0]["ID_Status"]

                                TicketDienst.update_ticket(
                                    t["ID_Ticket"],
                                    ID_Status=status_id,
                                    Geändert_von=st.session_state.user_id,
                                )
                                st.rerun()




    def tickets_verwalten(self):
        """Admin-Ansicht: Tickets ansehen und editieren."""

        st.header("🔧 Admin: Tickets verwalten")

        zeige_arch = st.checkbox("📦 Archivierte anzeigen")
        tickets = TicketDienst.liste_tickets(
            archiviert=zeige_arch
        )

        if not tickets:
            st.info("ℹ️ Keine Tickets vorhanden")
            return

        benutzer = Mitarbeiter.liste_aktiv()
        benutzer_map = {u["id"]: u["username"] for u in benutzer}
        benutzer_ids = [None] + [u["id"] for u in benutzer]

        for t in tickets:
            with (((st.expander(
                    f"#{t['ID_Ticket']} — {t['Titel']}",
                    expanded=False,
            )))):
                st.markdown(f"**Ticket #{t['ID_Ticket']}**")

                st.caption(
                    f"Erstellt: "
                    f"{datum_formatieren(t.get('Erstellt_am'))} | "
                    f"Aktualisiert: "
                    f"{datum_formatieren(t.get('Geändert_am'))}"
                )

                st.write(
                    t.get("Beschreibung", "")
                )

                c1, c2, c3, c4 = st.columns(4)

                status_namen = [
                    s["Name"]
                    for s in daten_abfragen(
                        "SELECT ID_Status AS id, Name FROM status ORDER BY ID_Status"
                    )
                ]

                status = c1.selectbox(
                    "Status",
                    status_namen,
                    index=0,
                    key=f"st_{t['ID_Ticket']}",
                )

                prio_index = (
                    PRIO_WERTE.index(t.get("Priorität"))
                    if t.get("Priorität") in PRIO_WERTE
                    else 1
                )

                prio = c2.selectbox(
                    "Priorität",
                    PRIO_WERTE,
                    index=prio_index,
                    key=f"pr_{t['ID_Ticket']}",
                )

                cur = t.get("Geändert_von")

                a_index = (
                    0
                    if cur in (None, 0)
                    else (
                        benutzer_ids.index(cur)
                        if cur in benutzer_ids
                        else 0
                    )
                )

                assignee = c4.selectbox(
                    "Bearbeiter",
                    benutzer_ids,
                    index=a_index,
                    format_func=lambda v: "—" if v is None else benutzer_map.get(v, "?"),
                    key=f"as_adm_{t['ID_Ticket']}",
                )

                arch = st.checkbox(
                    "📦 Archivieren",
                    value=bool(t.get("Archiviert", 0)),
                    key=f"arch_adm_{t['ID_Ticket']}",
                )

                if st.button(
                        "💾 Speichern",
                        key=f"save_adm_{t['ID_Ticket']}",
                ):
                    status_row = daten_abfragen(
                        "SELECT ID_Status FROM status WHERE Name=%s",
                        (status,),
                    )

                    status_id = (
                        status_row[0]["ID_Status"]
                        if status_row
                        else None
                    )

                    felder = {
                        "ID_Status": status_id,
                        "Priorität": prio,
                        "Geändert_von": assignee,
                        "Archiviert": int(arch),

                    }
                    TicketDienst.update_ticket(
                        t["ID_Ticket"],
                        **felder,
                    )

                    st.success("✅ Gespeichert")
                    st.rerun()

    def admin_seite(self):
        """Admin-Benutzerverwaltung: Auflistung, anlegen, deaktivieren."""
        st.header("🗄️ Benutzerverwaltung")

        users = Mitarbeiter.liste_aktiv()

        if users:
            st.dataframe(
                pd.DataFrame(users),
                use_container_width=True,
                hide_index=True,
            )

        else:
            st.info("Keine Benutzer vorhanden")

        st.divider()

        with st.form("new_user"):
            st.subheader("➕ Neuen Benutzer anlegen")

            col1, col2, col3 = st.columns(3)

            name = col1.text_input("Name")
            email = col2.text_input("Email")
            pw = col3.text_input(
                "Passwort",
                type="password",
            )

            if st.form_submit_button("✅ Anlegen"):
                if name and email and pw:
                    AuthDienst.erstelle_mitarbeiter(
                        name,
                        email,
                        pw,
                        None,
                    )
                    st.success("✅ Benutzer angelegt.")
                    st.rerun()
                else:
                    st.error(
                        "❌ Name, Email und Passwort erforderlich."
                    )

        st.divider()

        st.subheader("🗑️ Benutzer deaktivieren")

        users = Mitarbeiter.liste_aktiv()

        if not users:
            st.info("Keine aktiven Benutzer vorhanden.")
        else:
            victim = st.selectbox(
                "Benutzer auswählen",
                users,
                format_func=lambda x: x["username"],
            )

            confirm = st.text_input(
                "Zur Bestätigung Benutzernamen erneut eingeben"
            )

            sure = st.checkbox("Ich bin sicher")

            is_self = (
                    "user_id" in st.session_state
                    and victim["id"] == st.session_state["user_id"]
            )

            if is_self:
                st.warning(
                    "⚠️ Du kannst dich nicht selbst deaktivieren."
                )

            if st.button(
                    "🗑️ Benutzer deaktivieren",
                    disabled=is_self
                             or not sure or confirm != victim["username"],
            ):
                Mitarbeiter.mitarbeiter_deaktivieren(
                    victim["id"]
                )
                st.success(
                    f"✅ Benutzer '{victim['username']}' wurde deaktiviert."
                )
                st.rerun()

    def profil_seite(self):
        """Zeigt Profilinformationen und bietet Logout an."""
        st.header("👤 Profil")

        col1, col2, col3 = st.columns([1, 2, 1])

        with col2:
            st.markdown(
                f"""
                ### Angemeldet als

                **Benutzername:** {st.session_state.username}  
                **Rolle:** {st.session_state.role}
                """
            )

            if st.button(
                    "🚪 Logout",
                    use_container_width=True,
                    type="primary",
            ):
                for k in ["user_id", "role", "username"]:
                    st.session_state.pop(k, None)

                st.success("✅ Erfolgreich abgemeldet!")
                st.rerun()

def main():
    """Entry-Point: baut UI auf und routet zwischen Seiten."""
    app = AppUI()

    if "user_id" not in st.session_state:
        app.seite_login()
        return

    st.sidebar.title("🎫 Ticketsystem")
    st.sidebar.markdown(
        f"**👤 Benutzer:**  {st.session_state.get('username','-')}"
    )
    st.sidebar.markdown(
        f"**🛡️ Rolle:**  {st.session_state.get('role','-')}"
    )
    st.sidebar.divider()

    menue = [
        "📋 Kanban-Board",
        "➕ Ticket erstellen"
    ]

    if st.session_state.get("role") == "admin":
        menue.append("🛠️ Verwaltung")

    auswahl = st.sidebar.radio(
        "Navigation",
        menue,
        label_visibility="collapsed",
    )

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
        sub = st.radio(
            "Verwaltungsbereich",
            ["🎫 Tickets", "👥 Benutzer"],
            horizontal=True,
        )

        if sub == "🎫 Tickets":
            app.tickets_verwalten()
        else:
            app.admin_seite()


if __name__ == "__main__":
    main()
