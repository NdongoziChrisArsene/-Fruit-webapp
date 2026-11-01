# Fruit Classifier web app (Streamlit + PostgreSQL)

Users create an account, sign in and upload a fruit photo. The trained model names the fruit
(apple, banana, mango, orange, strawberry). Every result is saved in PostgreSQL.
Admins get a dashboard: statistics, all predictions (filter, export CSV, delete), user management
(roles, deactivate, reset password, delete), a read-only database browser and an audit log.

## 1. The model

Your trained `best.pt` is already included in the **models** folder. To use a newer model, replace:

    models/best.pt

## 2. Run it with Docker (easiest)

Install Docker Desktop, then in this folder:

    docker compose up --build

Open http://localhost:8501 and sign in with the admin account from the `.env` file
(`ADMIN_USERNAME` / `ADMIN_PASSWORD`). **Change that password** (Admin dashboard > Users > Reset password).
The first build takes a few minutes (PyTorch is large). Stop with `Ctrl+C`; your data stays in the
`pgdata` Docker volume. `docker compose down -v` deletes the data too.

To look at the database directly (psql or pgAdmin): host `localhost`, port `5432`, and the
`POSTGRES_*` values from `.env`.

## 3. Run it without Docker

1. Install Python 3.12 and PostgreSQL. Create a database and user:

       CREATE USER fruit WITH PASSWORD 'your_password';
       CREATE DATABASE fruitdb OWNER fruit;

2. In this folder:

       python -m venv .venv
       .venv\Scripts\activate          (Windows)   |   source .venv/bin/activate   (Mac/Linux)
       pip install -r requirements.txt

3. Set the settings, then start (Mac/Linux shown; on Windows use `set NAME=value`):

       export DATABASE_URL="postgresql://fruit:your_password@localhost:5432/fruitdb"
       export ADMIN_USERNAME=admin
       export ADMIN_PASSWORD=choose_a_strong_password
       streamlit run app.py

## 4. Put it online (GitHub + Streamlit Community Cloud)

Streamlit Cloud has no database of its own, so first create a free hosted PostgreSQL
(for example Neon or Supabase) and copy its connection string.

1. Upload this folder to a **private** GitHub repository, including `models/best.pt`
   (about 10 MB). Do **not** upload `.env` (it is in `.gitignore`).
2. On share.streamlit.io click **Create app**, choose the repository and `app.py`.
   In **Advanced settings** pick Python 3.12 and paste in **Secrets**:

       DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require"
       ADMIN_USERNAME = "admin"
       ADMIN_PASSWORD = "a-strong-password"

3. Deploy. The tables and the admin account are created on the first start.

## Settings (environment variables or Streamlit secrets)

| Name | Default | Meaning |
|---|---|---|
| DATABASE_URL | built from POSTGRES_* | PostgreSQL connection string |
| ADMIN_USERNAME / ADMIN_PASSWORD | admin / none | first admin, created only if no admin exists |
| MODEL_PATH | models/best.pt | where the model is |
| CONFIDENCE_THRESHOLD | 0.60 | below this the app says "not sure" |
| STORE_IMAGES | true | save a small 400 px copy of each photo in the database |
| MAX_LOGIN_ATTEMPTS / LOCKOUT_MINUTES | 5 / 15 | account lock after failed sign-ins |

## Files

    app.py          pages: sign in, classify, history, admin dashboard
    auth.py         registration, login (bcrypt), lockout, admin helpers
    db.py           PostgreSQL tables: users, predictions, audit_logs
    classifier.py   loads best.pt and predicts
    config.py       settings
    tests/smoke_test.py   end-to-end check against a real database

## Notes

- The model only knows 5 fruits; other fruits are named as one of them. Photos should show one fruit.
- Passwords are stored as bcrypt hashes, never in plain text.
- Photos are stored in the database. Set `STORE_IMAGES=false` if you do not want that, and tell
  your users how their photos are used.
