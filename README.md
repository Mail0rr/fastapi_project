## Discord-Style Messenger (FastAPI + WebSocket)

A minimal yet feature-rich messenger built with FastAPI, SQLite (aiosqlite), JWT auth (cookie + OAuth2), and WebSockets. It ships with clean server-side rendered pages using Jinja2 templates and a real-time chat experience.

### ✨ Features
- **User auth**: Sign up, sign in, logout (JWT stored in cookie)
- **Profile**: Update nickname and avatar URL
- **Real-time chat**: WebSocket-based 1:1 messaging, online status broadcasts
- **Saved chats**: Auto-saved upon first message; tracks last message/time
- **Search users**: Find users by `username`
- **SSR UI**: Jinja2 templates for sign-in, sign-up, settings, chat, and main page
- **SQLite**: Async queries with `aiosqlite`

---

## Project Structure
```text
fastapi_project-1/
├─ app.py                  # FastAPI app, routes, DB setup, WebSocket logic
├─ templates/              # Jinja2 templates (SSR)
│  ├─ base.html
│  ├─ sign-in.html
│  ├─ sign-up.html
│  ├─ settings.html
│  ├─ chat.html
│  └─ index.html
└─ mydb.db                 # SQLite database (auto-created)
```

---

## Tech Stack
- **Backend**: FastAPI, WebSockets
- **DB**: SQLite via `aiosqlite`
- **Auth**: JWT (`pyjwt`), OAuth2 password flow for API
- **Templates**: Jinja2
- **Server**: Uvicorn (dev)

---

## Getting Started (Windows PowerShell)

### 1) Prerequisites
- Python 3.10+
- PowerShell

### 2) Clone / Open
If you already have the folder, open it in your editor. Otherwise:
```powershell
git clone <your-repo-url> fastapi_project-1
cd fastapi_project-1
```

### 3) Create and activate a virtual environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 4) Install dependencies
```powershell
pip install fastapi "uvicorn[standard]" aiosqlite jinja2 python-multipart pydantic pyjwt
```

Optionally, save them:
```powershell
pip freeze > requirements.txt
```

### 5) Configure secrets (optional but recommended)
The app ships with a default `SECRET_KEY` in `app.py`. For production, set your own via environment variable and read it in code.

Generate a strong key:
```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Then either edit `app.py` or export before running:
```powershell
$env:SECRET_KEY = "<your-generated-hex>"
```

### 6) Run the server
```powershell
uvicorn app:app --reload --port 8000
```

Visit: `http://127.0.0.1:8000`

---

## How It Works

### Authentication Overview
- HTML flows (`/sign-in`, `/sign-up`) use forms; successful sign-in sets `access_token` cookie containing a JWT.
- Protected pages and APIs read the cookie to identify the current user.
- Programmatic auth is available via `/api/login` (OAuth2 Password flow) that returns a Bearer token.

### Database Schema (auto-created)
- `users(id, username, email, password, nickname, pfp)`
- `messages(id, sender_username, receiver_username, message, timestamp)`
- `saved_chats(id, user_username, chat_username, chat_nickname, chat_pfp, last_message, last_message_time, created_at)`

ER sketch:
```text
users (username) ─┐                ┌─> messages.receiver_username (FK -> users.username)
                  ├─> messages.sender_username (FK)
                  └─> saved_chats.user_username (FK)
                     saved_chats.chat_username (FK)
```

### WebSocket Flow
- Endpoint: `/ws/{token}` where `{token}` is a JWT.
- After connection, sending a message JSON like below stores it and forwards to the recipient if online.

Send format:
```json
{
  "to": "receiver_username",
  "message": "Hello there!"
}
```

Server emits:
- `type: "message"` to recipient
- `type: "sent"` confirmation to sender
- `type: "error"` if recipient is offline

---

## Endpoints

### Pages (SSR)
- `GET /` → Home (redirects to `/sign-in` if unauthenticated)
- `GET /sign-in` → Login page
- `POST /sign-in` → Handle login form
- `GET /sign-up` → Registration page
- `POST /sign-up` → Handle registration form
- `GET /settings` → Profile settings (auth required)
- `GET /logout` → Clear cookie and redirect

### Auth & Users (JSON)
- `POST /api/register` → body: `{ username, email, password }` → creates user
- `POST /api/login` → OAuth2 Password (form fields `username`, `password`) → returns `{ access_token, token_type }`
- `GET /api/search-user/{username}` → returns public profile

### Profile (auth required via cookie)
- `GET /api/user-profile` → current user profile
- `POST /api/update-nickname` → form field `nickname`
- `POST /api/update-avatar` → form field `avatar_url`

### Chats & Messages (auth required via cookie)
- `GET /api/saved-chats` → list of saved chats ordered by recent activity
- `POST /api/save-chat` → body: `{ username, nickname, pfp }` (manual save or update)
- `GET /api/messages/{other_username}` → last 50 messages with that user

### WebSocket
- `GET /ws/{token}` → Connect with a valid JWT; send message JSON as above

---

## Usage Examples

### 1) Register via API
```bash
curl -X POST http://127.0.0.1:8000/api/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","email":"alice@example.com","password":"Password123"}'
```

### 2) Login (API, token-based)
```bash
curl -X POST http://127.0.0.1:8000/api/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=alice&password=Password123"
```

Use the returned `access_token` to connect to WebSocket or as Bearer token for API clients.

### 3) Login (HTML, cookie-based)
- Open `http://127.0.0.1:8000/sign-in`
- On success, a cookie named `access_token` is set; you’ll be redirected to `/`.

### 4) Connect to WebSocket
In your browser, after logging in via HTML, fetch a token from the cookie or call `/api/login` manually and connect to:
```
ws://127.0.0.1:8000/ws/<JWT>
```

---

## Security Notes
- Cookies are set with `SameSite=Lax`. In production, serve over HTTPS and set `secure=True` for the cookie.
- Replace the default `SECRET_KEY` for any non-local use.
- Passwords are salted and hashed using PBKDF2-SHA256.

---

## Troubleshooting
- "Invalid token" or 401 → Ensure your cookie `access_token` is set or pass a valid JWT in the WebSocket path.
- Database not updating → Confirm the app has write permissions; `mydb.db` is in the project root.
- WebSocket not receiving messages → Verify the recipient is connected; otherwise you’ll get an error payload.
- Windows venv activation blocked → Run PowerShell as Administrator and execute:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```

---

## Development Tips
- Keep templates in `templates/`; Jinja is auto-discovered via `Jinja2Templates(directory="templates")`.
- During local dev, `--reload` auto-restarts on changes.
- Use `aiosqlite` row factory for dict-like access to columns (already configured).

---

## License
Choose a license (e.g., MIT) and add it here if you plan to share.

---

## Acknowledgements
- FastAPI, Uvicorn, aiosqlite, Jinja2, Pydantic, PyJWT
