<h1 align="left">
  <img src="./justpost(logo).jpeg" alt="JustPost logo" width="48" style="vertical-align: middle; margin-right: 10px;" />
  <span style="vertical-align: middle;">JustPost</span>
</h1>

JustPost is a social app with a `FastAPI` backend and a `Streamlit` frontend. Users can sign up, log in, upload image/video posts, like posts, comment, follow/unfollow other users, and manage profile details (custom username + birthday).

## Features

- JWT auth with `fastapi-users`
- Image and video uploads via ImageKit
- Feed with likes and comments
- Follow / unfollow users
- Profile stats (followers, following, posts)
- Profile editing (`custom_username`, `birthday`)
- Shareable media links from the frontend

## Tech Stack

- Backend: `FastAPI`, `SQLAlchemy (async)`, `fastapi-users`, `asyncpg`
- Frontend: `Streamlit`
- Media hosting: `ImageKit`
- Database: `PostgreSQL`

## Project Structure

```text
app/
  main.py       # API routes and business logic
  db.py         # DB models + async connection/session setup
  users.py      # FastAPI Users auth configuration
  schemas.py    # User/Post schemas
frontend.py     # Streamlit client app
```

## Prerequisites

- Python `3.12+`
- PostgreSQL
- ImageKit account (private key required)

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment Variables

Create a `.env` file in the project root:

```env
# Option 1: full database URL
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DB_NAME

# Option 2: separate PG vars (used when DATABASE_URL is not set)
PGHOST=localhost
PGPORT=5432
PGDATABASE=justpost
PGUSER=postgres
PGPASSWORD=postgres
PGSSLMODE=prefer

# Required for upload API
IMAGEKIT_PRIVATE_KEY=your_imagekit_private_key

# Optional (frontend default)
BASE_URL=http://localhost:8000
```

For Render deployment, set frontend `BASE_URL` to your backend public URL (for example, `https://your-backend-service.onrender.com`).

## Run the App

Start backend:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Start frontend (new terminal):

```bash
streamlit run frontend.py
```

Open:

- API docs: `http://localhost:8000/docs`
- Frontend: `http://localhost:8501`

## Render Free Tier Note

Render free web services sleep after inactivity and wake independently.  
This app sends a one-time, non-blocking backend `/health` ping on frontend startup so opening the frontend URL can wake the backend without delaying frontend render.

## Main API Endpoints

- Auth
  - `POST /auth/register`
  - `POST /auth/jwt/login`
  - `GET /auth/me`
- Posts
  - `POST /upload`
  - `GET /feed`
  - `DELETE /posts/{post_id}`
- Likes
  - `POST /posts/{post_id}/like`
  - `DELETE /posts/{post_id}/like`
- Comments
  - `POST /posts/{post_id}/comments`
  - `GET /posts/{post_id}/comments`
  - `DELETE /comments/{comment_id}`
- Follow & Profile
  - `POST /users/{user_id}/follow`
  - `DELETE /users/{user_id}/follow`
  - `GET /users/{user_id}/profile`
  - `GET /users/{user_id}/followers`
  - `GET /users/{user_id}/following`
  - `GET /users/profile/me`
  - `PUT /users/profile/me`

## WorkFlow

![alt text](worflow(justpost)-1.jpeg)

## 🎥 Demo Video

Watch the full project demo here:  
https://youtu.be/v0czx0QKHss
