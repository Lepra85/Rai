"""Rai Telegram bot — Phase 1: chat with per-chat memory.

Wraps the OpenAI Agents SDK Agent and exposes it over Telegram.
History is kept in-memory keyed by chat_id, so each Telegram conversation
has its own context. Restart loses history; persistence comes in phase 2.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from agents import Agent, Runner
from dotenv import load_dotenv

from tools import get_weather
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_CHAT_IDS = {
    int(x)
    for x in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
    if x.strip()
}
MODEL = os.environ.get("RAI_MODEL", "gpt-4o-mini")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("rai-bot")

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def build_instructions(_ctx, _agent) -> str:
    now = datetime.now(TZ)
    hoy = f"{DIAS[now.weekday()]} {now.day} de {MESES[now.month - 1]} de {now.year}"
    return (
        f"Hoy es {hoy} (zona horaria America/Argentina/Buenos_Aires). "
        "Sos Rai, un asistente conciso que responde en castellano rioplatense. "
        "Si no sabés algo, decilo en lugar de inventar. No uses emojis. "
        "Tenés acceso a la tool `get_weather` para consultar el clima actual de "
        "10 ciudades: Buenos Aires, Córdoba, Rosario, Mendoza, São Paulo, "
        "Santiago de Chile, Madrid, Nueva York, Londres y Tokio."
    )


agent = Agent(name="Rai", instructions=build_instructions, model=MODEL, tools=[get_weather])

# In-memory history per chat_id (Agents SDK input-list format).
histories: dict[int, list] = defaultdict(list)


async def authorized(update: Update) -> bool:
    chat_id = update.effective_chat.id
    if not ALLOWED_CHAT_IDS:
        log.warning("TELEGRAM_ALLOWED_CHAT_IDS empty — bot is open to anyone")
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
        "Hola, soy Rai. Escribime lo que quieras.\n"
        "/reset borra mi memoria de esta conversación.\n"
        "/id muestra tu chat id."
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    histories.pop(update.effective_chat.id, None)
    await update.message.reply_text("Memoria borrada.")


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"chat_id: {update.effective_chat.id}")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await authorized(update):
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)

    history = histories[chat_id]
    new_input = history + [{"role": "user", "content": text}]

    try:
        result = await Runner.run(agent, new_input)
    except Exception as exc:
        log.exception("agent run failed")
        await update.message.reply_text(f"Error: {exc}")
        return

    histories[chat_id] = result.to_input_list()

    response = result.final_output or "(sin respuesta)"
    for i in range(0, len(response), 4000):
        await update.message.reply_text(response[i : i + 4000])


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    log.info("Rai bot starting (model=%s)…", MODEL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
