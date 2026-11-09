import os
import json
import sqlite3
import time
import requests
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, Response, stream_with_context, g

app = Flask(__name__)

# ============================================================
#  🔑 ВСТАВЬ СВОИ 10 КЛЮЧЕЙ ZVENOAI
# ============================================================
API_KEY_1  = "sk-Qa6KRiNFRTDgCH_gqjDbch7XJYEh0_8D3jh750htQ8o"
API_KEY_2  = "sk-Gd4OQEUb1aURb4-kW7ZUh5mCBv26bh8COKJ2vSOY_vw"
API_KEY_3  = "sk-pAe_SKAzOPw4Yc1i2INngih0EH8djgf9FbWRuHRdBDA"
API_KEY_4  = "sk-7WQjhjr2KPwIJdD16RX4mOZJBkrq8BoaCLoEEr2KQXY"
API_KEY_5  = "sk-rz5pWLKn8d7Y7cpA87ClJ6k17fN6yaS3lO-MrzTg54E"
API_KEY_6  = "sk-NII_SaXV9-OvZB0gT4igQBobQ8dhP1dgw89IcY9kQdk"
API_KEY_7  = "sk-oc8_S9S0_V1PNM3E6YV6D5JI0INs7CSrgjaIRyUUJo8"
API_KEY_8  = "sk-g385f3nuniJbUZdge-m7cpS-lADAVJrqfpjt8DDskUU"
API_KEY_9  = "sk-yqerKzULF1Jl8j-D4wdKQH038rH-iBI0dLJH2JR49VQ"
API_KEY_10 = "sk-zcs_nGT0esSHpZ8vAWRa5wRIwGJ6xq7G8_pBUEClzGU"

ZVENO_URL = "https://api.zveno.ai/v1/chat/completions"

AI_NAME = "Daapsaak"
FREE_TOKENS = 999_999_999
HISTORY_LIMIT = 20
RATE_LIMIT_SECONDS = 2
DB_PATH = "chat.db"

# ============================================================
#  🧠 МОДЕЛИ ПО УМНОСТИ (от самой умной к самой быстрой)
# ============================================================
MODELS_BY_SMARTNESS = [
    {
        "id": "cohere/north-mini-code:free",
        "name": "🧠 Очень умная (код + reasoning)",
        "icon": "🧠",
    },
    {
        "id": "nvidia/nemotron-3.5-super-vl:free",
        "name": "💡 Умная (большой контекст)",
        "icon": "💡",
    },
    {
        "id": "nvidia/nemotron-3.5-lightning:free",
        "name": "⚡ Быстрая",
        "icon": "⚡",
    },
]

SYSTEM_PROMPTS = {
    "chat": f"Ты — {AI_NAME}, дружелюбный ИИ-ассистент. Отвечай на русском, чётко и по делу.",
    "code": (
        f"Ты — {AI_NAME}, экспертный программист. Помогаешь с кодом на Lua (Roblox Studio), "
        "Python, C++, C, JavaScript, TypeScript. Всегда давай полный рабочий код с комментариями. "
        "Код оформляй в блоках ```язык."
    ),
    "deep": (
        f"Ты — {AI_NAME} в режиме глубокого мышления. Решай сложные задачи по программированию "
        "шаг за шагом. Поддерживаемые языки: Lua (Roblox), Python, C++, JavaScript. "
        "Объясняй сложные моменты, предлагай альтернативы."
    ),
    "vision": (
        f"Ты — {AI_NAME}. Пользователь может прислать изображение. "
        "Опиши, что на нём, ответь на вопрос."
    ),
}

CODE_KEYWORDS = [
    "код", "code", "скрипт", "script", "функци", "function", "класс", "class",
    "lua", "luau", "roblox", "роблокс", "python", "питон", "c++", "cpp", "c#",
    "javascript", "js", "typescript", "ts", "html", "css", "sql",
    "напиши", "исправь", "debug", "ошибк", "error", "баг", "bug",
]

DEEP_KEYWORDS = [
    "сложн", "оптимизир", "архитектур", "рефактор", "производительн",
    "подумай", "рассужд", "reasoning", "алгоритм",
]

VISION_KEYWORDS = ["картинк", "изображен", "фото", "скриншот", "скрин"]


def detect_mode(message: str) -> str:
    lower = message.lower()
    if any(kw in lower for kw in VISION_KEYWORDS):
        return "vision"
    if any(kw in lower for kw in DEEP_KEYWORDS):
        return "deep"
    if any(kw in lower for kw in CODE_KEYWORDS):
        return "code"
    return "chat"


# ============================================================
#  🗄️ БАЗА ДАННЫХ
# ============================================================
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                tokens_left INTEGER NOT NULL DEFAULT 999999999,
                created_at TEXT NOT NULL,
                last_request_at REAL DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.commit()


def get_or_create_user(email: str):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        return row
    db.execute(
        "INSERT INTO users (email, tokens_left, created_at) VALUES (?, ?, ?)",
        (email, FREE_TOKENS, datetime.utcnow().isoformat()),
    )
    db.commit()
    return db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def save_message(user_id: int, role: str, content: str):
    db = get_db()
    db.execute(
        "INSERT INTO messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (user_id, role, content, datetime.utcnow().isoformat()),
    )
    db.commit()


def get_history(user_id: int, limit: int = HISTORY_LIMIT):
    db = get_db()
    rows = db.execute(
        "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ============================================================
#  🎯 ВСЕ 10 КЛЮЧЕЙ
# ============================================================
ALL_KEYS = [
    API_KEY_1, API_KEY_2, API_KEY_3, API_KEY_4, API_KEY_5,
    API_KEY_6, API_KEY_7, API_KEY_8, API_KEY_9, API_KEY_10,
]


def get_valid_keys():
    return [k for k in ALL_KEYS if k and not k.startswith("sk-твой")]


def pick_one_model(messages, mode, model_list):
    """
    Пробует модели по умности. Для каждой модели — все 10 ключей.
    Возвращает (response, model_id) первой свободной или (None, None).
    """
    keys = get_valid_keys()
    if not keys:
        return None, None

    for model_info in model_list:
        model = model_info["id"]
        for key in keys:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.7 if mode == "chat" else 0.3,
                "max_tokens": 4000,
                "stream": True,
            }
            if mode == "deep":
                payload["reasoning"] = {"type": "enabled"}

            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }

            try:
                r = requests.post(
                    ZVENO_URL, headers=headers, json=payload,
                    stream=True, timeout=120,
                )
                if r.status_code == 200:
                    return r, model
                else:
                    try:
                        r.close()
                    except Exception:
                        pass
                    continue
            except Exception:
                continue

    return None, None


# ============================================================
#  🎨 HTML
# ============================================================
HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🤖 Daapsaak</title>
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0a0a15; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }
    header { background: linear-gradient(135deg, #1a1a2e, #16213e); border-bottom: 2px solid #00d4ff; padding: 14px 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
    header h1 { font-size: 20px; color: #00d4ff; }
    .stats { display: flex; gap: 10px; align-items: center; font-size: 13px; }
    .stat { background: #0a0a15; padding: 6px 12px; border-radius: 8px; border: 1px solid #2a2a4a; }
    .login-overlay { position: fixed; inset: 0; background: rgba(10, 10, 21, 0.98); display: flex; align-items: center; justify-content: center; z-index: 100; }
    .login-box { background: #14141f; padding: 35px; border-radius: 14px; border: 2px solid #00d4ff; max-width: 420px; width: 90%; box-shadow: 0 0 50px rgba(0,212,255,0.4); }
    .login-box h2 { color: #00d4ff; margin-bottom: 8px; text-align: center; font-size: 32px; }
    .login-box .subtitle { color: #888; font-size: 14px; margin-bottom: 25px; text-align: center; line-height: 1.6; }
    .login-box input { width: 100%; padding: 14px; border: 2px solid #2a2a4a; border-radius: 10px; background: #0a0a15; color: #fff; font-size: 16px; margin-bottom: 15px; }
    .login-box input:focus { outline: none; border-color: #00d4ff; }
    .login-box button { width: 100%; padding: 14px; background: linear-gradient(135deg, #00d4ff, #0088cc); color: #fff; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; }
    .messages { flex: 1; overflow-y: auto; padding: 20px; max-width: 850px; width: 100%; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }
    .msg { padding: 12px 16px; border-radius: 12px; max-width: 90%; line-height: 1.6; font-size: 15px; white-space: pre-wrap; word-wrap: break-word; animation: fadeIn 0.2s ease; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; } }
    .msg.user { background: linear-gradient(135deg, #00d4ff, #0088cc); color: #fff; align-self: flex-end; }
    .msg.assistant { background: #1e1e3a; border-left: 3px solid #00d4ff; align-self: flex-start; }
    .msg.error { background: #3a1e1e; border-left-color: #ff4757; color: #ffaaaa; }
    .msg.busy-box { background: #2a1e3a; border-left: 3px solid #a371f7; align-self: flex-start; max-width: 100%; }
    .msg pre { background: #0a0a15; padding: 12px; border-radius: 8px; overflow-x: auto; margin: 8px 0; border: 1px solid #2a2a4a; position: relative; }
    .msg code { font-family: 'Consolas', monospace; font-size: 13px; color: #00ff88; }
    .msg code.inline { background: #0a0a15; padding: 2px 6px; border-radius: 4px; color: #ff6b9d; }
    .copy-btn { position: absolute; top: 6px; right: 6px; background: #2a2a4a; color: #aaa; border: none; padding: 3px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; }
    .copy-btn:hover { background: #00d4ff; color: #fff; }
    .typing { color: #00d4ff; font-style: italic; }
    .typing::after { content: '...'; animation: dots 1.5s infinite; }
    @keyframes dots { 0%,20%{content:'.';} 40%{content:'..';} 60%,100%{content:'...';} }
    .model-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; background: #2a2a4a; font-size: 11px; color: #aaa; margin-bottom: 6px; }
    .mode-bar { display: flex; gap: 8px; padding: 10px 20px 0; max-width: 850px; width: 100%; margin: 0 auto; flex-wrap: wrap; }
    .mode-btn { padding: 6px 14px; border-radius: 20px; background: #1e1e3a; color: #aaa; border: 1px solid #2a2a4a; cursor: pointer; font-size: 13px; }
    .mode-btn.active { background: #00d4ff; color: #000; border-color: #00d4ff; }
    .mode-btn.deep { background: linear-gradient(135deg, #a371f7, #6c3483); color: #fff; border: none; }
    .mode-btn.deep.active { box-shadow: 0 0 15px rgba(163,113,247,0.6); }
    .input-area { padding: 12px 20px 20px; background: #14141f; display: flex; gap: 10px; max-width: 850px; width: 100%; margin: 0 auto; }
    textarea { flex: 1; background: #0a0a15; border: 2px solid #2a2a4a; color: #e0e0e0; padding: 12px; border-radius: 10px; font-family: inherit; font-size: 15px; resize: none; min-height: 50px; max-height: 200px; }
    textarea:focus { outline: none; border-color: #00d4ff; }
    .btn { padding: 12px 22px; border-radius: 10px; border: none; font-weight: bold; font-size: 15px; cursor: pointer; white-space: nowrap; }
    .btn-send { background: linear-gradient(135deg, #00d4ff, #0088cc); color: #fff; }
    .btn:hover:not(:disabled) { transform: scale(1.05); }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .busy-actions { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
    .btn-queue { background: linear-gradient(135deg, #00ff88, #008844); color: #000; }
    .btn-smart { background: linear-gradient(135deg, #a371f7, #6c3483); color: #fff; }
    .model-list { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
    .model-item { padding: 8px 12px; background: #1e1e3a; border-radius: 8px; border: 1px solid #2a2a4a; cursor: pointer; font-size: 13px; }
    .model-item:hover { border-color: #00d4ff; background: #2a2a5a; }
    ::-webkit-scrollbar { width: 8px; }
    ::-webkit-scrollbar-track { background: #0a0a15; }
    ::-webkit-scrollbar-thumb { background: #2a2a4a; border-radius: 4px; }
</style>
</head>
<body>
<div class="login-overlay" id="loginOverlay">
    <div class="login-box">
        <h2>🤖 Daapsaak</h2>
        <div class="subtitle">ИИ для любых задач<br>10 ключей · автоматический подбор модели</div>
        <input type="email" id="emailInput" placeholder="Введи email" autofocus>
        <button onclick="login()">Начать</button>
    </div>
</div>
<header>
    <h1>🤖 Daapsaak</h1>
    <div class="stats">
        <div class="stat">👤 <span id="userEmail">—</span></div>
        <div class="stat">🔑 10 ключей</div>
        <button onclick="logout()" style="background:#2a2a4a;color:#ccc;border:none;padding:6px 12px;border-radius:8px;cursor:pointer;font-size:12px;">Выйти</button>
    </div>
</header>
<div class="messages" id="messages">
    <div style="text-align:center;color:#666;padding:40px 20px;">
        <h2 style="color:#00d4ff;margin-bottom:15px;">Привет! Я Daapsaak</h2>
        <p>Пиши вопросы, проси код или включай <b style="color:#a371f7;">🧠 Глубокое мышление</b>.</p>
        <p style="margin-top:10px;font-size:13px;">10 ключей · модель подбирается автоматически по умности.</p>
    </div>
</div>
<div class="mode-bar">
    <button class="mode-btn active" data-mode="auto" onclick="setMode('auto')">🤖 Авто</button>
    <button class="mode-btn" data-mode="chat" onclick="setMode('chat')">💬 Диалог</button>
    <button class="mode-btn" data-mode="code" onclick="setMode('code')">💻 Код</button>
    <button class="mode-btn deep" data-mode="deep" onclick="setMode('deep')">🧠 Глубокое мышление</button>
    <button class="mode-btn" data-mode="vision" onclick="setMode('vision')">🖼️ Картинки</button>
</div>
<div class="input-area">
    <textarea id="input" placeholder="Напиши сообщение... (Enter — отправить)" rows="1"></textarea>
    <button class="btn btn-send" id="sendBtn" onclick="sendMessage()">Отправить</button>
</div>
<script>
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('sendBtn');
const loginOverlay = document.getElementById('loginOverlay');
const emailInput = document.getElementById('emailInput');
const userEmailEl = document.getElementById('userEmail');
let currentUser = localStorage.getItem('user_email') || null;
let busy = false;
let abortController = null;
let currentMode = 'auto';
let pendingMessage = null;

function setMode(mode) {
    currentMode = mode;
    document.querySelectorAll('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
}
function login() {
    const email = emailInput.value.trim();
    if (!email || !email.includes('@')) { alert('Введи корректный email'); return; }
    localStorage.setItem('user_email', email);
    currentUser = email;
    initAfterLogin();
}
function logout() { localStorage.removeItem('user_email'); location.reload(); }
function initAfterLogin() {
    loginOverlay.style.display = 'none';
    userEmailEl.textContent = currentUser;
    inputEl.disabled = false;
    sendBtn.disabled = false;
    inputEl.focus();
    loadHistory();
}
async function loadHistory() {
    try {
        const resp = await fetch('/me', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email: currentUser}) });
        const data = await resp.json();
        if (data.history && data.history.length > 0) { messagesEl.innerHTML = ''; data.history.forEach(m => addMsg(m.role, m.content)); }
    } catch (e) { console.error(e); }
}
function escapeHtml(text) { const d = document.createElement('div'); d.textContent = text; return d.innerHTML; }
function renderMarkdown(text) {
    let html = escapeHtml(text);
    html = html.replace(/```(\\w*)\\n([\\s\\S]*?)```/g, (m, lang, code) => {
        const id = 'cb_' + Math.random().toString(36).slice(2, 9);
        return `<pre><code id="${id}">${code}</code><button class="copy-btn" onclick="copyCode('${id}', this)">📋</button></pre>`;
    });
    html = html.replace(/`([^`\\n]+)`/g, '<code class="inline">$1</code>');
    html = html.replace(/\\*\\*([^*]+)\\*\\*/g, '<b>$1</b>');
    html = html.replace(/\\n/g, '<br>');
    return html;
}
function copyCode(id, btn) { const code = document.getElementById(id).textContent; navigator.clipboard.writeText(code).then(() => { btn.textContent = '✅'; setTimeout(() => btn.textContent = '📋', 1200); }); }
function addMsg(role, text, useMarkdown) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;
    if (role === 'assistant' && useMarkdown) div.innerHTML = renderMarkdown(text);
    else div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
}

function showBusyBox(originalText) {
    pendingMessage = originalText;
    const div = document.createElement('div');
    div.className = 'msg busy-box';
    div.innerHTML = `
        <div style="font-size:16px;margin-bottom:8px;">🧠 <b>Все модели сейчас переполнены</b></div>
        <div style="color:#aaa;font-size:13px;margin-bottom:12px;">10 ключей × все модели заняты. Что делать?</div>
        <div class="busy-actions">
            <button class="btn btn-queue" onclick="joinQueue(this)">⏳ Встать в очередь</button>
            <button class="btn btn-smart" onclick="showSmartList(this)">💡 Выбрать по умности</button>
        </div>
    `;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function joinQueue(btn) {
    const box = btn.closest('.busy-box');
    let elapsed = 0;
    box.innerHTML = '<div class="typing">⏳ В очереди 0 сек</div>';
    const timer = setInterval(() => {
        elapsed++;
        const t = box.querySelector('.typing');
        if (t) t.textContent = `⏳ В очереди ${elapsed} сек`;
    }, 1000);
    let attempts = 0;
    while (attempts < 12) {
        await new Promise(r => setTimeout(r, 5000));
        attempts++;
        try {
            const resp = await fetch('/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({email: currentUser, message: pendingMessage, mode: currentMode})
            });
            if (resp.status === 503) continue;
            if (!resp.ok) continue;
            clearInterval(timer);
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let fullText = '';
            let streamDiv = null;
            while (true) {
                const {done, value} = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, {stream: true});
                const lines = buffer.split('\\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const data = line.slice(6);
                    if (data === '[DONE]') continue;
                    try {
                        const parsed = JSON.parse(data);
                        if (parsed.content) {
                            if (!streamDiv) { box.innerHTML = ''; streamDiv = document.createElement('div'); box.appendChild(streamDiv); }
                            fullText += parsed.content;
                            streamDiv.innerHTML = renderMarkdown(fullText);
                            messagesEl.scrollTop = messagesEl.scrollHeight;
                        }
                    } catch (e) {}
                }
            }
            return;
        } catch (e) { continue; }
    }
    clearInterval(timer);
    box.innerHTML = '<div class="msg error">⏰ Очередь не освободилась за минуту. Попробуй позже.</div>';
}

async function showSmartList(btn) {
    const box = btn.closest('.busy-box');
    box.innerHTML = '<div class="typing">💡 Загружаю модели</div>';
    try {
        const resp = await fetch('/models');
        const data = await resp.json();
        let html = '<div style="font-size:14px;margin-bottom:8px;">💡 Выбери модель по умности:</div><div class="model-list">';
        data.models.forEach(m => {
            html += `<div class="model-item" onclick="useModel('${m.id}', '${m.name}', this)">${m.icon} ${m.name}</div>`;
        });
        html += '</div>';
        box.innerHTML = html;
    } catch (e) { box.innerHTML = '<div class="msg error">❌ ' + e.message + '</div>'; }
}

async function useModel(modelId, modelName, itemEl) {
    const box = itemEl.closest('.busy-box');
    box.innerHTML = `<div class="typing">🤖 ${modelName} думает</div>`;
    try {
        const resp = await fetch('/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({email: currentUser, message: pendingMessage, mode: currentMode, custom_model: modelId})
        });
        if (!resp.ok) { const err = await resp.json(); box.innerHTML = '<div class="msg error">❌ ' + (err.error || 'Ошибка') + '</div>'; return; }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullText = '';
        let streamDiv = null;
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, {stream: true});
            const lines = buffer.split('\\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6);
                if (data === '[DONE]') continue;
                try {
                    const parsed = JSON.parse(data);
                    if (parsed.content) {
                        if (!streamDiv) { box.innerHTML = ''; streamDiv = document.createElement('div'); box.appendChild(streamDiv); }
                        fullText += parsed.content;
                        streamDiv.innerHTML = renderMarkdown(fullText);
                        messagesEl.scrollTop = messagesEl.scrollHeight;
                    }
                } catch (e) {}
            }
        }
    } catch (e) { box.innerHTML = '<div class="msg error">❌ ' + e.message + '</div>'; }
}

async function sendMessage() {
    if (busy) { if (abortController) abortController.abort(); return; }
    const text = inputEl.value.trim();
    if (!text) return;
    addMsg('user', text);
    inputEl.value = '';
    inputEl.style.height = 'auto';
    sendBtn.disabled = true;
    const aiDiv = addMsg('assistant', '');
    aiDiv.innerHTML = '<span class="typing">Daapsaak подбирает модель</span>';
    busy = true;
    abortController = new AbortController();
    sendBtn.textContent = '⏹';
    let fullText = '';
    try {
        const resp = await fetch('/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({email: currentUser, message: text, mode: currentMode}),
            signal: abortController.signal
        });
        if (resp.status === 503) {
            aiDiv.remove();
            showBusyBox(text);
            return;
        }
        if (!resp.ok) { const err = await resp.json().catch(() => ({error: 'HTTP ' + resp.status})); throw new Error(err.error || 'Ошибка сервера'); }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let modelBadge = null;
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, {stream: true});
            const lines = buffer.split('\\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6);
                if (data === '[DONE]') continue;
                try {
                    const parsed = JSON.parse(data);
                    if (parsed.model_name) {
                        modelBadge = document.createElement('div');
                        modelBadge.className = 'model-badge';
                        modelBadge.textContent = '🤖 ' + parsed.model_name;
                        aiDiv.appendChild(modelBadge);
                    }
                    if (parsed.content) { fullText += parsed.content; aiDiv.innerHTML = (modelBadge ? modelBadge.outerHTML : '') + renderMarkdown(fullText); messagesEl.scrollTop = messagesEl.scrollHeight; }
                    if (parsed.error) { aiDiv.className = 'msg error'; aiDiv.textContent = '❌ ' + parsed.error; }
                } catch (e) {}
            }
        }
    } catch (e) {
        if (e.name === 'AbortError') aiDiv.innerHTML = renderMarkdown(fullText) + '<br><em>[остановлено]</em>';
        else { aiDiv.className = 'msg error'; aiDiv.textContent = '❌ ' + e.message; }
    } finally {
        busy = false;
        abortController = null;
        sendBtn.textContent = 'Отправить';
        sendBtn.disabled = false;
        inputEl.focus();
    }
}
inputEl.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
inputEl.addEventListener('input', () => { inputEl.style.height = 'auto'; inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + 'px'; });
if (currentUser) initAfterLogin();
else emailInput.addEventListener('keydown', e => { if (e.key === 'Enter') login(); });
</script>
</body>
</html>
"""


# ============================================================
#  🌐 РОУТЫ
# ============================================================
@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/me", methods=["POST"])
def me():
    data = request.get_json()
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Email обязателен"}), 400
    user = get_or_create_user(email)
    history = get_history(user["id"], limit=30)
    return jsonify({"history": history})


@app.route("/models")
def models():
    return jsonify({
        "models": [
            {"id": m["id"], "name": m["name"], "icon": m["icon"]}
            for m in MODELS_BY_SMARTNESS
        ]
    })


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    email = (data.get("email") or "").strip().lower()
    message = (data.get("message") or "").strip()
    user_mode = (data.get("mode") or "auto").strip()
    custom_model = data.get("custom_model")

    if not email or not message:
        return jsonify({"error": "Email и сообщение обязательны"}), 400

    user = get_or_create_user(email)
    user_id = user["id"]

    now = time.time()
    if now - (user["last_request_at"] or 0) < RATE_LIMIT_SECONDS:
        wait = int(RATE_LIMIT_SECONDS - (now - user["last_request_at"]))
        return jsonify({"error": f"Подожди {wait} сек."}), 429

    db = get_db()
    db.execute("UPDATE users SET last_request_at = ? WHERE id = ?", (now, user_id))
    db.commit()

    save_message(user_id, "user", message)

    if user_mode == "auto":
        mode = detect_mode(message)
    else:
        mode = user_mode if user_mode in ("chat", "code", "deep", "vision") else "chat"

    system_prompt = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["chat"])
    history = get_history(user_id, limit=HISTORY_LIMIT)
    messages = [{"role": "system", "content": system_prompt}] + history

    if custom_model:
        model_list = [m for m in MODELS_BY_SMARTNESS if m["id"] == custom_model]
        if not model_list:
            model_list = MODELS_BY_SMARTNESS
    else:
        model_list = MODELS_BY_SMARTNESS

    # Проверяем заранее, есть ли свободная модель
    r_check, _ = pick_one_model(messages, mode, model_list)
    if r_check is None:
        return jsonify({"busy": True}), 503
    try:
        r_check.close()
    except Exception:
        pass

    def generate():
        r, picked_model = pick_one_model(messages, mode, model_list)
        if r is None:
            yield "data: " + json.dumps({"busy": True}, ensure_ascii=False) + "\n\n"
            return

        model_name = picked_model
        for m in MODELS_BY_SMARTNESS:
            if m["id"] == picked_model:
                model_name = m["name"]
                break

        yield "data: " + json.dumps({"model_name": model_name}, ensure_ascii=False) + "\n\n"

        full_reply = ""
        try:
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                chunk = line[6:]
                if chunk == "[DONE]":
                    break
                try:
                    parsed = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                delta = parsed.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    full_reply += content
                    yield "data: " + json.dumps({"content": content}, ensure_ascii=False) + "\n\n"

            save_message(user_id, "assistant", full_reply)
            yield "data: [DONE]\n\n"

        except Exception as e:
            yield "data: " + json.dumps({"error": str(e)}, ensure_ascii=False) + "\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    init_db()
    print("=" * 60)
    print(f"🤖 {AI_NAME} — ИИ-ассистент (10 ключей)")
    print("=" * 60)
    for i, k in enumerate(ALL_KEYS, 1):
        status = "✅" if k and not k.startswith("sk-твой") else "⚠️ не задан"
        print(f"Ключ {i:2d}: {status}")
    print("─" * 60)
    print("🧠 Модели по умности:")
    for m in MODELS_BY_SMARTNESS:
        print(f"   {m['icon']} {m['name']}")
    print("─" * 60)
    print("🚀 http://127.0.0.1:5000")
    print("=" * 60)
    app.run(debug=True, host="0.0.0.0", port=5000, threaded=True)
