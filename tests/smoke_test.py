"""Quick end-to-end check of the app against a real database.
Run:  python tests/smoke_test.py   (needs DATABASE_URL, ADMIN_PASSWORD and a model file)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from streamlit.testing.v1 import AppTest

import auth
from db import User, init_db, make_engine

engine = make_engine()
factory = init_db(engine)

# ---- unit checks on the auth layer ----
with factory() as s:
    assert auth.validate_password("short") is not None
    assert auth.validate_username("a b") is not None
    u, err = auth.register_user(s, "tester1", "t1@example.com", "goodpassword1")
    assert u and not err, err
    _, err = auth.register_user(s, "TESTER1", "", "goodpassword1")
    assert err and "taken" in err
    assert auth.authenticate(s, "tester1", "wrong")[0] is None
    assert auth.authenticate(s, "tester1", "goodpassword1")[0] is not None
    for _ in range(5):
        auth.authenticate(s, "tester1", "wrong")
    user, err = auth.authenticate(s, "tester1", "goodpassword1")
    assert user is None and "Too many" in err, err   # locked after 5 failures
    s.delete(s.scalar(select(User).where(User.username == "tester1")))
    s.commit()
print("auth layer OK")

# ---- UI checks ----
app_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.py")
at = AppTest.from_file(app_file, default_timeout=120).run()
assert not at.exception, at.exception
assert any("Sign in" in t.label for t in at.tabs), "login page missing"

at.text_input[0].set_value(os.environ.get("ADMIN_USERNAME", "admin"))
at.text_input[1].set_value(os.environ["ADMIN_PASSWORD"])
at.button[0].click().run()
assert not at.exception, at.exception
assert at.session_state["user_id"], "admin could not sign in"
assert any("Admin dashboard" in o for o in at.sidebar.radio[0].options), "admin menu missing"
print("admin sign-in OK")

for page in ["Classify", "My history", "Admin dashboard"]:
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, (page, at.exception)
print("all pages render OK")
print("SMOKE TEST PASSED")
