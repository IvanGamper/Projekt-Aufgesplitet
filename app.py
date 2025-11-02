import streamlit as st
from services import PRIO, CATS, create_ticket
from pages import page_login, page_kanban, page_admin_dashboard

# -------- Setup + Seiten --------

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
                st.success("✅ Ticket angelegt!")
                st.balloons()
                st.rerun()

def show_sidebar():
    """Sidebar mit Userinfo, Navigation und Logout."""
    user = st.session_state.get("username", "Unbekannt")
    role = st.session_state.get("role", "user")

    st.sidebar.title("🎫 Ticketsystem")
    st.sidebar.markdown(f"**Angemeldet als:** {user} ({role})")
    st.sidebar.divider()

    # Navigation direkt hier:
    pages = {
        "🎫 Kanban-Board": page_kanban,
        "➕ Ticket erstellen": page_create_ticket
    }
    if role == "admin":
        pages["🛠️ Verwaltung"] = page_admin_dashboard

    choice = st.sidebar.radio("Navigation", list(pages.keys()), label_visibility="collapsed")
    st.sidebar.divider()

    # Logout-Button
    if st.sidebar.button("🚪 Logout", use_container_width=True, type="primary"):
        for k in ["user_id", "role", "username"]:
            st.session_state.pop(k, None)
        st.sidebar.success("✅ Abgemeldet!")
        st.rerun()

    return pages[choice]

def app_start():
    """App-Einstiegspunkt."""
    st.set_page_config(page_title="Ticketsystem", layout="wide", page_icon="🎫")
    st.markdown("""
        <style>
        .stButton button { border-radius: 5px; }
        div[data-testid="stExpander"] { border: 1px solid #ddd; border-radius: 5px; }
        </style>
    """, unsafe_allow_html=True)

    if "user_id" not in st.session_state:
        page_login()
        return

    selected_page = show_sidebar()
    selected_page()

if __name__ == "__main__":
    app_start()
