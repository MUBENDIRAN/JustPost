# JustPost Social App

JustPost is a small social media app with a FastAPI backend and a Streamlit frontend. Users can register, log in, upload image/video posts, like posts, and comment in a simple feed.

## Tech Stack

- Backend: `FastAPI`, `SQLAlchemy (async)`, `fastapi-users`, `asyncpg`
- Frontend: `Streamlit`
- Media hosting: `ImageKit`
- Database: `PostgreSQL`

## Project Structure

```text
app/
  main.py       # API routes
  db.py         # DB models + connection/session setup
  users.py      # FastAPI Users auth config
  schemas.py    # Pydantic schemas
frontend.py     # Streamlit client app
```

## Prerequisites

- Python `3.12+`
- PostgreSQL database
- ImageKit account (private key required)

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment Variables

Create a `.env` file (or export vars in your shell):

```env
# Option 1: full URL
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DB_NAME

# Option 2: individual PG vars (if DATABASE_URL is not set)
PGHOST=localhost
PGPORT=5432
PGDATABASE=justpost
PGUSER=postgres
PGPASSWORD=postgres
PGSSLMODE=prefer

# Required for media upload
IMAGEKIT_PRIVATE_KEY=your_imagekit_private_key

# Optional (frontend defaults to http://localhost:8000)
BASE_URL=http://localhost:8000
```

## Running the App

Start backend:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Start frontend (new terminal):

```bash
streamlit run frontend.py
```

Then open:

- API docs: `http://localhost:8000/docs`
- Frontend: `http://localhost:8501`

## Main API Endpoints

- Auth:
  - `POST /auth/register`
  - `POST /auth/jwt/login`
  - `GET /auth/me`
- Posts:
  - `POST /upload`
  - `GET /feed`
  - `DELETE /posts/{post_id}`
- Likes:
  - `POST /posts/{post_id}/like`
  - `DELETE /posts/{post_id}/like`
- Comments:
  - `POST /posts/{post_id}/comments`
  - `GET /posts/{post_id}/comments`
  - `DELETE /comments/{comment_id}`
- Follow/Profile:
  - `POST /users/{user_id}/follow`
  - `DELETE /users/{user_id}/follow`
  - `GET /users/{user_id}/profile`
  - `GET /users/{user_id}/followers`
  - `GET /users/{user_id}/following`
  - `GET /users/profile/me`
  - `PUT /users/profile/me`

## Notes

- `app/users.py` currently contains a placeholder JWT secret (`CHANGE_THIS_TO_A_LONG_RANDOM_SECRET`). Replace it before production use.
- Tables are created automatically on backend startup.
