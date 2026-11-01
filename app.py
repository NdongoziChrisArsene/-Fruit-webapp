"""Fruit Classifier web app: sign in, predict fruits from photos, history, admin panel."""
import io
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from PIL import Image
from sqlalchemy import delete, func, select

import auth
import classifier
import config
from db import AuditLog, Prediction, User, init_db, make_engine, utcnow

st.set_page_config(page_title="Fruit Classifier", page_icon="🍎", layout="wide")


# ----------------------------------------------------------------------------
# Shared resources (created once per server process)
# ----------------------------------------------------------------------------
@st.cache_resource(show_spinner="Connecting to the database...")
def get_session_factory():
    factory = init_db(make_engine())
    with factory() as session:
        warning = auth.ensure_admin(session)
    return factory, warning


@st.cache_resource(show_spinner="Loading the fruit model...")
def get_model():
    return classifier.load_model()


try:
    SessionLocal, admin_warning = get_session_factory()
except Exception as exc:  # noqa: BLE001
    st.error(f"Database connection failed.\n\n{exc}")
    st.stop()


def current_user(session):
    """Re-reads the signed-in user from the database on every run, so a user that was
    deactivated or demoted by an admin loses access immediately."""
    user_id = st.session_state.get("user_id")
    if not user_id:
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        st.session_state.clear()
        return None
    return user


# ----------------------------------------------------------------------------
# Sign in / register
# ----------------------------------------------------------------------------
def page_auth(session):
    st.title("🍎 Fruit Classifier")
    st.write("Sign in to classify fruit photos. New here? Create an account in the second tab.")
    if admin_warning:
        st.warning(admin_warning)

    tab_login, tab_register = st.tabs(["Sign in", "Create account"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            user, error = auth.authenticate(session, username, password)
            if error:
                st.error(error)
            else:
                st.session_state["user_id"] = user.id
                st.rerun()

    with tab_register:
        with st.form("register_form"):
            new_username = st.text_input("Choose a username", help="3-30 characters: letters, digits, _ . -")
            new_email = st.text_input("Email (optional)")
            new_password = st.text_input("Choose a password (min. 8 characters)", type="password")
            confirm = st.text_input("Repeat the password", type="password")
            submitted = st.form_submit_button("Create account", type="primary")
        if submitted:
            if new_password != confirm:
                st.error("The two passwords do not match.")
            else:
                user, error = auth.register_user(session, new_username, new_email, new_password)
                if error:
                    st.error(error)
                else:
                    st.success("Account created. You can now sign in from the first tab.")


# ----------------------------------------------------------------------------
# Predict
# ----------------------------------------------------------------------------
def page_predict(session, user):
    st.header("Classify a fruit")
    st.write("Upload a photo of **one fruit**. The model knows: apple, banana, mango, orange and strawberry.")

    try:
        model = get_model()
    except FileNotFoundError as exc:
        st.error(str(exc))
        return

    source = st.radio("Photo source", ["Upload a file", "Use the camera"], horizontal=True)
    if source == "Upload a file":
        file = st.file_uploader("Choose a photo", type=["jpg", "jpeg", "png", "webp"])
    else:
        file = st.camera_input("Take a photo")
    if file is None:
        return

    try:
        image = classifier.open_image(file)
    except Exception:  # noqa: BLE001
        st.error("This file could not be read as an image.")
        return

    left, right = st.columns(2)
    left.image(image, caption="Your photo", width="stretch")

    with st.spinner("Analysing..."):
        ranked = classifier.predict(model, image)
    label, confidence = ranked[0]

    with right:
        if confidence >= config.CONFIDENCE_THRESHOLD:
            st.success(f"This looks like **{label}** ({confidence * 100:.0f}% confident)")
        else:
            st.warning(
                f"Not sure. Best guess: **{label}** ({confidence * 100:.0f}%). "
                "Try a clearer photo of a single fruit."
            )
        st.subheader("All probabilities")
        for name, p in ranked:
            st.write(f"{name.capitalize()}: {p * 100:.1f}%")
            st.progress(min(max(p, 0.0), 1.0))
        st.caption("Only these fruits are known. Other fruits may be wrongly named as one of them.")

    # save once per uploaded file (Streamlit reruns the script on every click)
    file_key = f"{getattr(file, 'name', 'camera')}-{getattr(file, 'size', 0)}-{getattr(file, 'file_id', '')}"
    if st.session_state.get("last_saved") != file_key:
        session.add(
            Prediction(
                user_id=user.id,
                filename=(getattr(file, "name", None) or "camera.jpg")[:255],
                predicted_label=label,
                confidence=confidence,
                probabilities={n: round(p, 6) for n, p in ranked},
                image_thumb=classifier.make_thumbnail(image) if config.STORE_IMAGES else None,
            )
        )
        session.commit()
        st.session_state["last_saved"] = file_key
        st.toast("Result saved to your history")


# ----------------------------------------------------------------------------
# History
# ----------------------------------------------------------------------------
def prediction_frame(rows, with_user=False) -> pd.DataFrame:
    data = []
    for p, username in rows:
        row = {
            "id": p.id,
            "date": p.created_at.strftime("%Y-%m-%d %H:%M"),
            "file": p.filename,
            "fruit": p.predicted_label,
            "confidence %": round(p.confidence * 100, 1),
        }
        if with_user:
            row = {"id": p.id, "user": username, **{k: v for k, v in row.items() if k != "id"}}
        data.append(row)
    return pd.DataFrame(data)


def page_history(session, user):
    st.header("My history")
    rows = session.execute(
        select(Prediction, User.username)
        .join(User, User.id == Prediction.user_id)
        .where(Prediction.user_id == user.id)
        .order_by(Prediction.created_at.desc())
        .limit(500)
    ).all()
    if not rows:
        st.info("No predictions yet. Go to **Classify** and upload a photo.")
        return
    st.dataframe(prediction_frame(rows), hide_index=True)
    ids = [p.id for p, _ in rows]
    chosen = st.selectbox("Show the photo of prediction #", ids)
    pred = next(p for p, _ in rows if p.id == chosen)
    if pred.image_thumb:
        st.image(Image.open(io.BytesIO(pred.image_thumb)), caption=f"{pred.predicted_label} ({pred.confidence * 100:.0f}%)")
    else:
        st.caption("No photo stored for this prediction.")


# ----------------------------------------------------------------------------
# Admin
# ----------------------------------------------------------------------------
def admin_overview(session):
    users_total = session.scalar(select(func.count()).select_from(User))
    preds_total = session.scalar(select(func.count()).select_from(Prediction))
    week_ago = utcnow() - timedelta(days=7)
    preds_week = session.scalar(
        select(func.count()).select_from(Prediction).where(Prediction.created_at >= week_ago)
    )
    avg_conf = session.scalar(select(func.avg(Prediction.confidence))) or 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Users", users_total)
    c2.metric("Predictions", preds_total)
    c3.metric("Last 7 days", preds_week)
    c4.metric("Average confidence", f"{avg_conf * 100:.0f}%")

    by_label = session.execute(
        select(Prediction.predicted_label, func.count()).group_by(Prediction.predicted_label)
    ).all()
    if by_label:
        st.subheader("Predictions per fruit")
        st.bar_chart(pd.DataFrame(by_label, columns=["fruit", "count"]).set_index("fruit"))
        per_day = session.execute(
            select(func.date(Prediction.created_at), func.count())
            .group_by(func.date(Prediction.created_at))
            .order_by(func.date(Prediction.created_at))
        ).all()
        st.subheader("Predictions per day")
        st.bar_chart(pd.DataFrame(per_day, columns=["day", "count"]).set_index("day"))
    else:
        st.info("No predictions in the database yet.")


def admin_predictions(session, admin):
    usernames = [u for (u,) in session.execute(select(User.username).order_by(User.username))]
    labels = [l for (l,) in session.execute(select(Prediction.predicted_label).distinct())]
    f1, f2, f3, f4 = st.columns(4)
    pick_users = f1.multiselect("User", usernames)
    pick_labels = f2.multiselect("Fruit", sorted(labels))
    date_from = f3.date_input("From", value=date.today() - timedelta(days=30))
    date_to = f4.date_input("To", value=date.today())

    query = (
        select(Prediction, User.username)
        .join(User, User.id == Prediction.user_id)
        .where(Prediction.created_at >= pd.Timestamp(date_from, tz="UTC"))
        .where(Prediction.created_at < pd.Timestamp(date_to, tz="UTC") + pd.Timedelta(days=1))
        .order_by(Prediction.created_at.desc())
        .limit(500)
    )
    if pick_users:
        query = query.where(User.username.in_(pick_users))
    if pick_labels:
        query = query.where(Prediction.predicted_label.in_(pick_labels))
    rows = session.execute(query).all()
    st.caption(f"{len(rows)} prediction(s) shown (maximum 500).")
    if not rows:
        return

    frame = prediction_frame(rows, with_user=True)
    st.download_button("Download CSV", frame.to_csv(index=False).encode(), "predictions.csv", "text/csv")

    editable = frame.copy()
    editable.insert(0, "delete", False)
    edited = st.data_editor(
        editable,
        hide_index=True,
        disabled=[c for c in editable.columns if c != "delete"],
        key="pred_editor",
    )
    to_delete = edited.loc[edited["delete"], "id"].tolist()
    if to_delete:
        st.warning(f"{len(to_delete)} prediction(s) selected for deletion.")
        if st.button("Delete selected predictions", type="primary"):
            session.execute(delete(Prediction).where(Prediction.id.in_(to_delete)))
            session.commit()
            auth.log_action(session, admin, "delete_predictions", f"ids={to_delete[:50]}")
            st.rerun()

    chosen = st.selectbox("Show the photo of prediction #", frame["id"].tolist())
    pred = next(p for p, _ in rows if p.id == chosen)
    if pred.image_thumb:
        st.image(Image.open(io.BytesIO(pred.image_thumb)), caption=f"{pred.predicted_label} ({pred.confidence * 100:.0f}%)")
        st.json(pred.probabilities)
    else:
        st.caption("No photo stored for this prediction.")


def admin_users(session, admin):
    users = session.scalars(select(User).order_by(User.id)).all()
    counts = dict(session.execute(select(Prediction.user_id, func.count()).group_by(Prediction.user_id)).all())
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email or "",
                    "role": u.role,
                    "active": u.is_active,
                    "predictions": counts.get(u.id, 0),
                    "created": u.created_at.strftime("%Y-%m-%d %H:%M"),
                    "last login": u.last_login.strftime("%Y-%m-%d %H:%M") if u.last_login else "",
                }
                for u in users
            ]
        ),
        hide_index=True,
    )

    st.subheader("Manage a user")
    ids_by_label = {f"{u.username} (#{u.id}, {u.role})": u.id for u in users}
    choice = st.selectbox("User", list(ids_by_label))
    # re-read the row from the database so changes are saved on the real record
    target = session.get(User, ids_by_label[choice]) if choice is not None else None
    if target is None:
        return
    is_self = target.id == admin.id
    if is_self:
        st.info("This is your own account: you cannot demote, deactivate or delete it here.")

    c1, c2 = st.columns(2)
    with c1:
        new_role = st.selectbox("Role", ["user", "admin"], index=0 if target.role == "user" else 1, disabled=is_self)
        active = st.checkbox("Account active", value=target.is_active, disabled=is_self)
        if st.button("Save role and status", disabled=is_self):
            losing_admin = target.role == "admin" and (new_role != "admin" or not active)
            if losing_admin and auth.count_active_admins(session) <= 1:
                st.error("There must be at least one active admin.")
            else:
                target.role, target.is_active = new_role, active
                session.commit()
                auth.log_action(session, admin, "update_user", f"{target.username}: role={new_role}, active={active}")
                st.success("Saved.")
                st.rerun()
    with c2:
        new_password = st.text_input("Set a new password", type="password", key="reset_pw")
        if st.button("Reset password"):
            error = auth.validate_password(new_password)
            if error:
                st.error(error)
            else:
                target.password_hash = auth.hash_password(new_password)
                target.failed_attempts, target.locked_until = 0, None
                session.commit()
                auth.log_action(session, admin, "reset_password", target.username)
                st.success("Password changed.")
        confirm = st.checkbox(f"I want to delete {target.username} and all their predictions", disabled=is_self)
        if st.button("Delete user", disabled=is_self or not confirm):
            if target.role == "admin" and auth.count_active_admins(session) <= 1:
                st.error("There must be at least one active admin.")
            else:
                name = target.username
                session.delete(target)
                session.commit()
                auth.log_action(session, admin, "delete_user", name)
                st.rerun()


TABLES = {
    "users": (User, {"password_hash"}),
    "predictions": (Prediction, {"image_thumb"}),
    "audit_logs": (AuditLog, set()),
}


def admin_database(session, admin):
    st.write(
        "Browse the database tables (read-only). Password hashes and stored images are hidden here. "
        "For full SQL access, connect with `psql` or pgAdmin using the database settings."
    )
    name = st.selectbox("Table", list(TABLES))
    model, hidden = TABLES[name]
    columns = [c for c in model.__table__.columns if c.name not in hidden]
    limit = st.slider("Rows", 10, 1000, 100, step=10)
    rows = session.execute(select(*columns).order_by(model.id.desc()).limit(limit)).all()
    frame = pd.DataFrame(rows, columns=[c.name for c in columns])
    if "probabilities" in frame:
        frame["probabilities"] = frame["probabilities"].astype(str)
    total = session.scalar(select(func.count()).select_from(model))
    st.caption(f"{len(frame)} of {total} row(s) in `{name}`.")
    st.dataframe(frame, hide_index=True)
    st.download_button("Download CSV", frame.to_csv(index=False).encode(), f"{name}.csv", "text/csv")


def admin_audit(session):
    rows = session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)).all()
    if not rows:
        st.info("No admin actions recorded yet.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {"when": r.created_at.strftime("%Y-%m-%d %H:%M"), "admin": r.admin_username,
                 "action": r.action, "detail": r.detail}
                for r in rows
            ]
        ),
        hide_index=True,
    )


def page_admin(session, admin):
    st.header("Admin dashboard")
    tabs = st.tabs(["Overview", "Predictions", "Users", "Database", "Audit log"])
    with tabs[0]:
        admin_overview(session)
    with tabs[1]:
        admin_predictions(session, admin)
    with tabs[2]:
        admin_users(session, admin)
    with tabs[3]:
        admin_database(session, admin)
    with tabs[4]:
        admin_audit(session)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    with SessionLocal() as session:
        user = current_user(session)
        if user is None:
            page_auth(session)
            return

        pages = ["Classify", "My history"] + (["Admin dashboard"] if user.role == "admin" else [])
        with st.sidebar:
            st.write(f"Signed in as **{user.username}**" + (" (admin)" if user.role == "admin" else ""))
            page = st.radio("Menu", pages)
            if st.button("Sign out"):
                st.session_state.clear()
                st.rerun()

        if page == "Classify":
            page_predict(session, user)
        elif page == "My history":
            page_history(session, user)
        elif page == "Admin dashboard" and user.role == "admin":
            page_admin(session, user)


main()
