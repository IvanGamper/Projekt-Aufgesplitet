# components.py
import streamlit as st
from services import (
    STATI, STATUS_COLORS, PRIO_COLORS,
    format_datetime, now_utc_str, next_status, prev_status,
    list_users, update_ticket
)

def show_stats(get_ticket_stats_fn):
    """Zeigt die Metriken (Stats oben). Übergib get_ticket_stats aus services per Funktions-Ref."""
    stats = get_ticket_stats_fn()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Gesamt", stats.get('total', 0))
    c2.metric("🔵 Neu", stats.get('neue', 0))
    c3.metric("🟡 In Bearbeitung", stats.get('in_bearbeitung', 0))
    c4.metric("🟢 Gelöst", stats.get('geloest', 0))
    c5.metric("📦 Archiviert", stats.get('archiviert', 0))
    st.divider()

def kanban_card(t: dict):
    st.markdown(f"{STATUS_COLORS.get(t.get('status',''),'⚪')} "
                f"{PRIO_COLORS.get(t.get('priority',''),'⚪')} "
                f"**#{t['id']} — {t['title']}**")
    st.caption(f"📁 {t.get('category','-')} • ⏰ {format_datetime(t.get('updated_at'))}")
    desc = t.get('description') or ''
    st.write(desc[:150] + ("…" if len(desc) > 150 else ""))
    st.caption(f"👤 {t.get('creator_name','?')} → 👨‍💼 {t.get('assignee_name','—') or 'Nicht zugewiesen'}")

def get_user_map_and_ids():
    users = list_users()
    user_map = {u["id"]: u["username"] for u in users}
    user_ids = [None] + [u["id"] for u in users]
    return user_map, user_ids

def render_ticket_controls(t, user_map, user_ids, is_admin: bool):
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("⬅️", key=f"left_{t['id']}"):
            update_ticket(t["id"], status=prev_status(t["status"]), updated_at=now_utc_str())
            st.rerun()
    with c2:
        if st.button("➡️", key=f"right_{t['id']}"):
            update_ticket(t["id"], status=next_status(t["status"]), updated_at=now_utc_str())
            st.rerun()

    cur = t.get("assignee_id")
    a_index = 0 if cur in (None, 0) else (user_ids.index(cur) if cur in user_ids else 0)
    assignee = c3.selectbox("Bearbeiter", user_ids, index=a_index,
                            format_func=lambda v: "—" if v is None else user_map.get(v, "?"),
                            key=f"as_{t['id']}", label_visibility="collapsed")

    arch_val = bool(t.get("archived", 0))
    arch = st.checkbox("📦 Archivieren", value=arch_val, key=f"arch_{t['id']}") if is_admin else arch_val

    if st.button("💾 Speichern", key=f"save_{t['id']}", use_container_width=True):
        fields = {"assignee_id": assignee, "updated_at": now_utc_str()}
        if is_admin:
            fields["archived"] = int(arch)
        update_ticket(t["id"], **fields)
        st.success("✅ Gespeichert")
        st.rerun()

def render_ticket_column(status_name: str, tickets: list[dict], user_map, user_ids, is_admin: bool):
    st.subheader(f"{STATUS_COLORS.get(status_name,'⚪')} {status_name} "
                 f"({sum(1 for t in tickets if t.get('status') == status_name)})")
    for t in [t for t in tickets if t.get("status") == status_name]:
        with st.container(border=True):
            kanban_card(t)
            render_ticket_controls(t, user_map, user_ids, is_admin)
