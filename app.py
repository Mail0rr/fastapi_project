import aiosqlite
import uvicorn
import datetime
import secrets
import jwt
import hashlib
import os
import json

from typing import Any
from fastapi import FastAPI, Depends, HTTPException, Request, status, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, SecretStr
from contextlib import asynccontextmanager
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

SECRET_KEY = "fc2b20edc79f41422c1cbaf115be91b9"
ALGORITHM = "HS256"

SQLITE_DB_NAME = "mydb.db"

templates = Jinja2Templates(directory="templates")


class WebsocketConnectionManager:
    """Менеджер роботи з WebSocket."""

    def __init__(self) -> None:
        """Ініціалізація структури для зберігання з'єднань."""
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, username: str) -> None:
        """Приєднання до websocket та оповіщення всіх про це."""
        await websocket.accept()
        await self.broadcast(f"{username} is online.", exclude={username})
        self.active_connections[username] = websocket

    def disconnect(self, username: str) -> None:
        """Від'єднання від websocket та видалення із контейнера об'єкта з'єднання."""
        self.active_connections.pop(username, None)

    async def send_personal_message(self, message: str, username: str) -> None:
        """Відправлення приватного повідомлення на одне відкрите з'єднання."""
        websocket = self.active_connections.get(username)
        if websocket:
            await websocket.send_text(message)

    async def broadcast(self, message: str, exclude: set[str] | None = None) -> None:
        """
        Відправлення загальнодоступного повідомлення на всі відкриті з'єднання,
        окрім з'єднань з `exclude`.
        """
        if exclude is None:
            exclude = set()

        for username, connection in self.active_connections.items():
            if username not in exclude:
                await connection.send_text(message)


manager = WebsocketConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(SQLITE_DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                password TEXT NOT NULL,
                nickname TEXT NOT NULL,
                pfp TEXT
            );
        """)
        await db.execute("""CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_username TEXT NOT NULL,
                receiver_username TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_username) REFERENCES users (username),
                FOREIGN KEY (receiver_username) REFERENCES users (username)
            );
        """)
        await db.execute("""CREATE TABLE IF NOT EXISTS saved_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_username TEXT NOT NULL,
                chat_username TEXT NOT NULL,
                chat_nickname TEXT NOT NULL,
                chat_pfp TEXT,
                last_message_time DATETIME,
                last_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_username) REFERENCES users (username),
                FOREIGN KEY (chat_username) REFERENCES users (username),
                UNIQUE(user_username, chat_username)
            );
        """)
        await db.commit()
    yield


app = FastAPI(
    title="Discord Style Messenger",
    description="Messenger приложение с регистрацией и авторизацией",
    version="0.1.0",
    lifespan=lifespan
)


def create_jwt(
        payload: dict[str, Any], expires_delta: datetime.timedelta | None = None
) -> str:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    payload_copy = payload.copy()

    if expires_delta is not None:
        expire = now_utc + expires_delta
    else:
        expire = now_utc + datetime.timedelta(minutes=15)

    jti = secrets.token_urlsafe()
    payload_copy.update(exp=expire, iat=now_utc, jti=jti)

    try:
        token = jwt.encode(payload_copy, key=SECRET_KEY, algorithm=ALGORITHM)
    except jwt.PyJWTError as e:
        raise ValueError(f"Error while encoding token: {e}") from e

    return token


def decode_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, key=SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return {}


def hash_password(password: str) -> str:
    """Hash password using PBKDF2 with SHA256"""
    salt = os.urandom(32)  # 32 bytes salt
    pwdhash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex() + pwdhash.hex()


def verify_password(stored_password: str, provided_password: str) -> bool:
    """Verify password against stored hash"""
    salt = bytes.fromhex(stored_password[:64])  # First 32 bytes (64 hex chars) are salt
    stored_hash = stored_password[64:]  # Rest is the hash
    pwdhash = hashlib.pbkdf2_hmac('sha256', provided_password.encode('utf-8'), salt, 100000)
    return pwdhash.hex() == stored_hash


async def get_db():
    async with aiosqlite.connect(SQLITE_DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None

    payload = decode_jwt(token)
    username = payload.get("sub")
    return username


async def get_current_user_ws(token: str):
    if not token:
        return None

    payload = decode_jwt(token)
    username = payload.get("sub")
    return username


class UserCreate(BaseModel):
    username: str
    email: str
    password: str


class UserShow(BaseModel):
    username: str


class Token(BaseModel):
    token_type: str
    access_token: str


class SaveChatRequest(BaseModel):
    username: str
    nickname: str
    pfp: str = None


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    username = await get_current_user(request)
    if not username:
        return RedirectResponse(url="/sign-in", status_code=303)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "username": username
    })


@app.get("/sign-in", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("sign-in.html", {"request": request})


@app.post("/sign-in", response_class=HTMLResponse)
async def login_form(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        connection: aiosqlite.Connection = Depends(get_db)
):
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT * FROM users WHERE username = ?;", (username,))
            db_user = await cursor.fetchone()

            if db_user is None or not verify_password(db_user["password"], password):
                return templates.TemplateResponse(
                    "sign-in.html",
                    {"request": request, "error": "Неверный логин или пароль"}
                )

        token = create_jwt({"sub": username})
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key="access_token",
            value=token,
            max_age=3600 * 24 * 31,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax"
        )
        return response

    except Exception as e:
        return templates.TemplateResponse(
            "sign-in.html",
            {"request": request, "error": "Произошла ошибка при входе"}
        )


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/sign-in", status_code=303)
    response.delete_cookie("access_token")
    return response


@app.get("/sign-up", response_class=HTMLResponse)
async def sign_up_page(request: Request):
    return templates.TemplateResponse("sign-up.html", {"request": request})


@app.post("/sign-up", response_class=HTMLResponse)
async def sign_up_form(
        request: Request,
        username: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
        connection: aiosqlite.Connection = Depends(get_db)
):
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT 1 FROM users WHERE username = ?;", (username,))
            db_user = await cursor.fetchone()

            if db_user is not None:
                return templates.TemplateResponse(
                    "sign-up.html",
                    {"request": request, "error": "Пользователь с таким именем уже существует"}
                )

            hashed_password = hash_password(password)
            await cursor.execute(
                "INSERT INTO users (username, email, password, nickname) VALUES (?, ?, ?, ?);",
                (username, email, hashed_password, username)
            )
            await connection.commit()

        return RedirectResponse(url="/sign-in", status_code=303)

    except Exception as e:
        return templates.TemplateResponse(
            "sign-up.html",
            {"request": request, "error": "Произошла ошибка при регистрации"}
        )


@app.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    username = await get_current_user(request)
    if not username:
        return RedirectResponse(url="/sign-in", status_code=303)

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "username": username
    })


@app.post("/api/update-nickname")
async def update_nickname(
        request: Request,
        nickname: str = Form(...),
        connection: aiosqlite.Connection = Depends(get_db)
):
    username = await get_current_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE users SET nickname = ? WHERE username = ?;",
                (nickname, username)
            )
            await connection.commit()

        return {"success": True, "message": "Nickname updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to update nickname")


@app.post("/api/update-avatar")
async def update_avatar(
        request: Request,
        avatar_url: str = Form(...),
        connection: aiosqlite.Connection = Depends(get_db)
):
    username = await get_current_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "UPDATE users SET pfp = ? WHERE username = ?;",
                (avatar_url, username)
            )
            await connection.commit()

        return {"success": True, "message": "Avatar updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to update avatar")


@app.get("/api/user-profile")
async def get_user_profile(
        request: Request,
        connection: aiosqlite.Connection = Depends(get_db)
):
    username = await get_current_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT username, nickname, pfp FROM users WHERE username = ?;",
            (username,)
        )
        user = await cursor.fetchone()

        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        return {
            "username": user["username"],
            "nickname": user["nickname"] or user["username"],
            "pfp": user["pfp"]
        }


@app.get("/api/saved-chats")
async def get_saved_chats(
        request: Request,
        connection: aiosqlite.Connection = Depends(get_db)
):
    username = await get_current_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with connection.cursor() as cursor:
        await cursor.execute("""
            SELECT sc.*, u.nickname as current_nickname, u.pfp as current_pfp
            FROM saved_chats sc
            LEFT JOIN users u ON sc.chat_username = u.username
            WHERE sc.user_username = ?
            ORDER BY sc.last_message_time DESC NULLS LAST, sc.created_at DESC
        """, (username,))

        chats = await cursor.fetchall()

        return [{
            "username": chat["chat_username"],
            "nickname": chat["current_nickname"] or chat["chat_nickname"],
            "pfp": chat["current_pfp"],
            "last_message": chat["last_message"],
            "last_message_time": chat["last_message_time"]
        } for chat in chats]


@app.post("/api/save-chat")
async def save_chat(
        request: Request,
        chat_data: SaveChatRequest,
        connection: aiosqlite.Connection = Depends(get_db)
):
    username = await get_current_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        async with connection.cursor() as cursor:
            # Check if chat already exists
            await cursor.execute(
                "SELECT id FROM saved_chats WHERE user_username = ? AND chat_username = ?",
                (username, chat_data.username)
            )
            existing_chat = await cursor.fetchone()

            if existing_chat:
                # Update existing chat
                await cursor.execute("""
                    UPDATE saved_chats 
                    SET chat_nickname = ?, chat_pfp = ?
                    WHERE user_username = ? AND chat_username = ?
                """, (chat_data.nickname, chat_data.pfp, username, chat_data.username))
            else:
                # Insert new chat
                await cursor.execute("""
                    INSERT INTO saved_chats (user_username, chat_username, chat_nickname, chat_pfp)
                    VALUES (?, ?, ?, ?)
                """, (username, chat_data.username, chat_data.nickname, chat_data.pfp))

            await connection.commit()

        return {"success": True, "message": "Chat saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to save chat")


async def update_chat_last_message(sender_username: str, receiver_username: str, message: str, connection):
    """Update last message for both users' saved chats"""
    timestamp = datetime.datetime.now().isoformat()

    async with connection.cursor() as cursor:
        # Update for sender
        await cursor.execute("""
            UPDATE saved_chats 
            SET last_message = ?, last_message_time = ?
            WHERE user_username = ? AND chat_username = ?
        """, (message, timestamp, sender_username, receiver_username))

        # Update for receiver
        await cursor.execute("""
            UPDATE saved_chats 
            SET last_message = ?, last_message_time = ?
            WHERE user_username = ? AND chat_username = ?
        """, (message, timestamp, receiver_username, sender_username))

        await connection.commit()


@app.get("/api/messages/{other_username}")
async def get_messages(
        other_username: str,
        request: Request,
        connection: aiosqlite.Connection = Depends(get_db)
):
    username = await get_current_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with connection.cursor() as cursor:
        await cursor.execute("""
            SELECT m.*, u1.nickname as sender_nickname, u1.pfp as sender_pfp,
                   u2.nickname as receiver_nickname, u2.pfp as receiver_pfp
            FROM messages m
            JOIN users u1 ON m.sender_username = u1.username
            JOIN users u2 ON m.receiver_username = u2.username
            WHERE (m.sender_username = ? AND m.receiver_username = ?) 
               OR (m.sender_username = ? AND m.receiver_username = ?)
            ORDER BY m.timestamp ASC
            LIMIT 50
        """, (username, other_username, other_username, username))

        messages = await cursor.fetchall()

        return [{
            "id": msg["id"],
            "sender_username": msg["sender_username"],
            "sender_nickname": msg["sender_nickname"] or msg["sender_username"],
            "sender_pfp": msg["sender_pfp"],
            "receiver_username": msg["receiver_username"],
            "receiver_nickname": msg["receiver_nickname"] or msg["receiver_username"],
            "receiver_pfp": msg["receiver_pfp"],
            "message": msg["message"],
            "timestamp": msg["timestamp"]
        } for msg in messages]


@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    username = await get_current_user_ws(token)
    if not username:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, username)

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)

            # Save message to database
            async with aiosqlite.connect(SQLITE_DB_NAME) as db:
                db.row_factory = aiosqlite.Row
                async with db.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO messages (sender_username, receiver_username, message) VALUES (?, ?, ?)",
                        (username, message_data["to"], message_data["message"])
                    )
                    await db.commit()

                    # Get sender info for the message
                    await cursor.execute(
                        "SELECT nickname, pfp FROM users WHERE username = ?",
                        (username,)
                    )
                    sender_info = await cursor.fetchone()

                    await cursor.execute(
                        "SELECT nickname, pfp FROM users WHERE username = ?",
                        (message_data["to"],)
                    )
                    receiver_info = await cursor.fetchone()

                await auto_save_chat_for_both_users(username, message_data["to"], sender_info, receiver_info, db)
                await update_chat_last_message(username, message_data["to"], message_data["message"], db)

            # Send message to recipient if online
            if message_data["to"] in manager.active_connections:
                formatted_message = json.dumps({
                    "type": "message",
                    "from": username,
                    "from_nickname": sender_info["nickname"] or username,
                    "from_pfp": sender_info["pfp"],
                    "message": message_data["message"],
                    "timestamp": datetime.datetime.now().isoformat()
                })
                await manager.send_personal_message(formatted_message, message_data["to"])

                # Send confirmation to sender
                confirmation = json.dumps({
                    "type": "sent",
                    "to": message_data["to"],
                    "message": message_data["message"],
                    "timestamp": datetime.datetime.now().isoformat()
                })
                await manager.send_personal_message(confirmation, username)
            else:
                # User is offline
                offline_message = json.dumps({
                    "type": "error",
                    "message": f"User {message_data['to']} is not online."
                })
                await manager.send_personal_message(offline_message, username)

    except WebSocketDisconnect:
        manager.disconnect(username)
        await manager.broadcast(f"{username} left the chat.", exclude={username})


async def auto_save_chat_for_both_users(sender_username: str, receiver_username: str, sender_info, receiver_info,
                                        connection):
    """Auto-save chat for both sender and receiver when they exchange messages"""
    async with connection.cursor() as cursor:
        # Save chat for sender (receiver appears in sender's chat list)
        await cursor.execute(
            "SELECT id FROM saved_chats WHERE user_username = ? AND chat_username = ?",
            (sender_username, receiver_username)
        )
        existing_sender_chat = await cursor.fetchone()

        if not existing_sender_chat:
            await cursor.execute("""
                INSERT INTO saved_chats (user_username, chat_username, chat_nickname, chat_pfp)
                VALUES (?, ?, ?, ?)
            """, (sender_username, receiver_username, receiver_info["nickname"] or receiver_username,
                  receiver_info["pfp"]))

        # Save chat for receiver (sender appears in receiver's chat list)
        await cursor.execute(
            "SELECT id FROM saved_chats WHERE user_username = ? AND chat_username = ?",
            (receiver_username, sender_username)
        )
        existing_receiver_chat = await cursor.fetchone()

        if not existing_receiver_chat:
            await cursor.execute("""
                INSERT INTO saved_chats (user_username, chat_username, chat_nickname, chat_pfp)
                VALUES (?, ?, ?, ?)
            """, (receiver_username, sender_username, sender_info["nickname"] or sender_username, sender_info["pfp"]))

        await connection.commit()


@app.post(
    "/api/register",
    status_code=status.HTTP_200_OK,
    response_model=UserShow,
    tags=["register"],
    summary="User registration",
    description="Endpoint used for registering new users",
)
async def user_registration(user_data: UserCreate, connection: aiosqlite.Connection = Depends(get_db)) -> UserShow:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT 1 FROM users WHERE username = ?;", (user_data.username,))
        db_user = await cursor.fetchone()

        if db_user is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "User exists.")

        hashed_password = hash_password(user_data.password)
        await cursor.execute(
            "INSERT INTO users (username, email, password, nickname) VALUES (?, ?, ?, ?) RETURNING id;",
            (user_data.username, user_data.email, hashed_password, user_data.username),
        )

        last_inserted = await cursor.fetchone()
        await connection.commit()

    return UserShow(username=user_data.username)


@app.post("/api/login", response_model=Token, tags=["auth"])
async def login(
        form_data: OAuth2PasswordRequestForm = Depends(),
        connection: aiosqlite.Connection = Depends(get_db),
) -> Token:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT * FROM users WHERE username = ?;", (form_data.username,)
        )
        db_user = await cursor.fetchone()

        if db_user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User does not exist.")

    if not verify_password(db_user["password"], form_data.password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect password.")

    token = create_jwt({"sub": form_data.username})
    return Token(
        access_token=token,
        token_type="bearer"
    )


@app.get("/api/search-user/{username}")
async def search_user(username: str, connection: aiosqlite.Connection = Depends(get_db)):
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT username, nickname, pfp FROM users WHERE username = ?;",
            (username,)
        )
        user = await cursor.fetchone()

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="Человека с таким username'ом не найдено"
            )

        return {
            "username": user["username"],
            "nickname": user["nickname"] or user["username"],
            "pfp": user["pfp"]
        }

if __name__ == '__main__':
    uvicorn.run("app:app", reload=True, port=8000)
