import streamlit as st
import pandas as pd
from services import (
    STATI, PRIO, CATS, STATUS_COLORS, PRIO_COLORS,
    safe_index, format_datetime, next_status, prev_status, now_utc_str,
    login_user, list_users, create_user, deactivate_user,
    create_ticket, fetch_tickets, update_ticket, get_ticket_stats
)
from pages import page_login, page_kanban, page_admin_dashboard

# -------- Setup --------
def setup_page():
    st.set_page_config(page_title="Ticketsystem", layout="wide", page_icon="🎫")
    st.markdown("""
        <style>
        .stButton button { border-radius: 5px; }
        div[data-testid="stExpander"] { border: 1px solid #ddd; border-radius: 5px; }
        </style>
    """, unsafe_allow_html=True)

def is_logged_in() -> bool:
    return "user_id" in st.session_state


# -------- Seiten --------

def page_create_ticket():
    st.header("➕ Neues Ticket erstellen")
    with st.form("create_ticket_form"):
        title = st.text_input("📝 Titel")
        desc  = st.text_area("📄 Beschreibung", height=200)
        col1, col2 = st.columns(2)
        cat = col1.selectbox("📁 Kategorie", CATS)
        prio = col2.selectbox("⚠️ Priorität", PRIO, index=1)
        if st.form_submit_button("✅ Ticket anlegen", use_container_width=True):
            if not title.strip() or not desc.strip():
                st.error("❌ Titel und Beschreibung dürfen nicht leer sein.")
            else:
                create_ticket(title.strip(), desc.strip(), cat, prio, st.session_state.user_id)
                st.success("✅ Ticket angelegt!"); st.balloons(); st.rerun()



# -------- App-Flow --------
def show_sidebar():
    user = st.session_state.get("username", "Unbekannt")
    role = st.session_state.get("role", "user")

    st.sidebar.title("🎫 Ticketsystem")
    st.sidebar.markdown(f"**Angemeldet als:** {user} ({role})")
    st.sidebar.divider()

    # Logout direkt in der Sidebar
    if st.sidebar.button("🚪 Logout", use_container_width=True, type="primary"):
        for k in ["user_id", "role", "username"]:
            st.session_state.pop(k, None)
        st.sidebar.success("✅ Abgemeldet!")
        st.rerun()

def get_pages(role: str) -> dict:
    pages = {"🎫 Kanban-Board": page_kanban, "➕ Ticket erstellen": page_create_ticket}
    if role == "admin":
        pages["🛠️ Verwaltung"] = page_admin_dashboard
    return pages

def route_to_selected_page():
    role = st.session_state.get("role", "user")
    pages = get_pages(role)
    choice = st.sidebar.radio("Navigation", list(pages.keys()), label_visibility="collapsed")
    pages[choice]()

def app_start():
    setup_page()
    if not is_logged_in():
        page_login(); return
    show_sidebar()
    route_to_selected_page()

if __name__ == "__main__":
    app_start()
