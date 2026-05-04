#!/usr/bin/env python3
"""Rai Telegram bot — bridges Telegram chats to Claude Code (with PAI)."""
import asyncio
import json
import logging
import os
import shlex
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_CHAT_IDS = {
    int(x) for x in os.environ.get("RAI_ALLOWED_CHAT_IDS", "").split(",") if x.strip()
}
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
WORK_DIR = Path(os.environ.get("RAI_WORK_DIR", str(Path.home())))
SESSIONS_FILE = Path(
    os.environ.get("RAI_SESSIONS_FILE", str(Path.home() / ".rai" / "sessions.json"))
)
SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
TIMEOUT_S = int(os.environ.get("RAI_TIMEOUT_S", "180"))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
log = logging.getLogger("rai")

_sessions_lock = asyncio.Lock()


def load_sessions() -> dict:
    if SESSIONS_FILE.exists():
        try:
            return json.loads(SESSIONS_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_sessions(data: dict) -> None:
    tmp = SESSIONS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(SESSIONS_FILE)


async def call_claude(prompt: str, session_id: str | None) -> tuple[str, str]:
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if session_id:
        cmd.extend(["--resume", session_id])
    log.info("claude cmd: %s …", shlex.join(cmd[:4]))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(WORK_DIR),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"claude timed out after {TIMEOUT_S}s")
    if proc.returncode != 0:
        log.error("claude rc=%s stderr=%s", proc.returncode, stderr.decode()[:500])
        raise RuntimeError(f"claude failed: {stderr.decode()[:300]}")
    try:
        payload = json.loads(stdout.decode())
    except json.JSONDecodeError:
        return stdout.decode().strip(), session_id or ""
    return payload.get("result", "") or "", payload.get("session_id", session_id or "")


async def authorized(update: Update) -> bool:
    chat_id = update.effective_chat.id
    if not ALLOWED_CHAT_IDS:
        log.warning("RAI_ALLOWED_CHAT_IDS empty — bot is open to anyone")
        return True
    if chat_id in ALLOWED_CHAT_IDS:
        return True
    log.warning("rejected chat_id=%s", chat_id)
    if update.message:
        await update.message.reply_text("No autorizado.")
    return False


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    await update.message.reply_text(
        "Hola, soy Rai.\nMandame un mensaje y te respondo usando Claude Code.\n"
        "/reset reinicia tu conversación.\n/id muestra tu chat id."
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    chat_id = str(update.effective_chat.id)
    async with _sessions_lock:
        sessions = load_sessions()
        sessions.pop(chat_id, None)
        save_sessions(sessions)
    await update.message.reply_text("Conversación reiniciada.")


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"chat_id: {update.effective_chat.id}")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    chat_id = str(update.effective_chat.id)
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    async with _sessions_lock:
        sessions = load_sessions()
        session_id = sessions.get(chat_id)
    try:
        response, new_session_id = await call_claude(text, session_id)
    except Exception as exc:
        log.exception("claude call failed")
        await update.message.reply_text(f"Error: {exc}")
        return
    if new_session_id and new_session_id != session_id:
        async with _sessions_lock:
            sessions = load_sessions()
            sessions[chat_id] = new_session_id
            save_sessions(sessions)
    if not response:
        response = "(sin respuesta)"
    for i in range(0, len(response), 4000):
        chunk = response[i : i + 4000]
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk)


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    log.info("Rai bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
