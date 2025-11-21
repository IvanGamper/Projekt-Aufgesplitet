import streamlit as st
import pandas as pd
from services import (STATI, PRIO, CATS, safe_index,
    login_user, list_users, create_user, deactivate_user,
    create_ticket, fetch_tickets, get_ticket_stats)
from components import show_stats, render_ticket_column, get_user_map_and_ids

def page_create_ticket():
    st.header("➕ Neues Ticket erstellen")
    with st.form("create_ticket_form"):
        title = st.text_input("📝 Titel")
        desc  = st.text_area("📄 Beschreibung", height=200)
        col1, col2 = st.columns(2)
        cat = col1.selectbox("📁 Kategorie", CATS)
        prio = col2.selectbox("⚠️ Priorität", PRIO, index=1)
        if st.form_submit_button("✅ Ticket anlegen", use_container_width=True):
            if not title or not desc:
                st.error("❌ Titel und Beschreibung dürfen nicht leer sein.")
            else:
                create_ticket(title.strip(), desc.strip(), cat, prio, st.session_state.user_id)
                st.success("✅ Ticket angelegt!")
                st.balloons()
                st.rerun()

def page_login():
    st.title("🎫 Ticketsystem Login")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            st.subheader("Anmelden")
            u = st.text_input("Benutzername")
            p = st.text_input("Passwort", type="password")
            if st.form_submit_button("🔐 Anmelden", use_container_width=True):
                user = login_user(u, p)
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

def page_kanban():
    st.header("🎫 Ticket Kanban-Board")
    show_stats(get_ticket_stats)

    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    search = col1.text_input("🔍 Suche", placeholder="Ticket durchsuchen...")
    filter_cat = col2.selectbox("📁 Kategorie", ["Alle"] + CATS)
    filter_prio = col3.selectbox("⚠️ Priorität", ["Alle"] + PRIO)
    show_arch = col4.checkbox("📦 Archiv")

    is_admin = (st.session_state.get("role") == "admin")
    tickets = fetch_tickets(
        archived=show_arch,
        search_term=search or None,
        category=(None if filter_cat == "Alle" else filter_cat),
        priority=(None if filter_prio == "Alle" else filter_prio),
    )
    if not tickets:
        st.info("ℹ️ Keine Tickets gefunden.")
        return

    user_map, user_ids = get_user_map_and_ids()
    cols = st.columns(len(STATI))
    for idx, status_name in enumerate(STATI):
        with cols[idx]:
            render_ticket_column(status_name, tickets, user_map, user_ids, is_admin)

def page_admin_dashboard():
    """Admin-Dashboard: Tickets & Benutzer in einer Seite."""
    st.header("🛠️ Verwaltung (Admin)")

    tab1, tab2 = st.tabs(["🎫 Tickets", "👥 Benutzer"])

    # Tickets
    with tab1:
        st.subheader("Ticketverwaltung")
        show_arch = st.checkbox("📦 Archivierte anzeigen")
        tickets = fetch_tickets(archived=show_arch)
        if not tickets:
            st.info("ℹ️ Keine Tickets vorhanden")
        else:
            users = list_users()
            user_map = {u["id"]: u["username"] for u in users}
            user_ids = [None] + [u["id"] for u in users]

            for t in tickets:
                with st.expander(f"#{t['id']} — {t['title']}", expanded=False):
                    c1, c2, c3, c4 = st.columns(4)
                    status = c1.selectbox("Status", STATI, index=safe_index(STATI, t.get("status")), key=f"st_{t['id']}")
                    prio   = c2.selectbox("Priorität", PRIO, index=safe_index(PRIO, t.get("priority"), 1), key=f"pr_{t['id']}")
                    cat    = c3.selectbox("Kategorie", CATS, index=safe_index(CATS, t.get("category")), key=f"ct_{t['id']}")
                    cur = t.get("assignee_id")
                    a_index = 0 if cur in (None, 0) else (user_ids.index(cur) if cur in user_ids else 0)
                    assignee = c4.selectbox("Bearbeiter", user_ids, index=a_index,
                                            format_func=lambda v: "—" if v is None else user_map.get(v, "?"),
                                            key=f"as_{t['id']}")
                    arch = st.checkbox("📦 Archivieren", value=bool(t.get("archived", 0)), key=f"arch_adm_{t['id']}")
                    if st.button("💾 Speichern", key=f"save_adm_{t['id']}", use_container_width=True):
                        from services import update_ticket  # lokal, um Seitenimporte schlank zu halten
                        update_ticket(t["id"], status=status, priority=prio, category=cat,
                                      assignee_id=assignee, archived=int(arch))
                        st.success("✅ Gespeichert")
                        st.rerun()

    # Benutzer
    with tab2:
        st.subheader("Benutzerverwaltung")
        users = list_users()
        if users:
            st.dataframe(pd.DataFrame(users), use_container_width=True, hide_index=True)
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
                    create_user(u, p, r)
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
                         disabled=is_self or not sure or confirm != victim["username"], type="primary"):
                deactivate_user(victim["id"])
                st.success(f"✅ Benutzer '{victim['username']}' wurde deaktiviert.")
                st.rerun()
