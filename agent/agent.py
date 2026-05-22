"""Rai agent — Phase 0: chat without memory.

Just a REPL that sends each user message to an OpenAI model via the
OpenAI Agents SDK. The agent has no message history yet, so each turn is
independent. Useful to verify the framework works end-to-end before adding
memory and tools.
"""
import asyncio
import os
import sys

from agents import Agent, Runner

from tools import get_weather

MODEL = os.environ.get("RAI_MODEL", "gpt-4o-mini")

agent = Agent(
    name="Rai",
    instructions=(
        "Sos Rai, un asistente conciso que responde en castellano rioplatense. "
        "Si no sabés algo, decilo en lugar de inventar. No uses emojis. "
        "Tenés acceso a la tool `get_weather` para consultar el clima actual de "
        "10 ciudades: Buenos Aires, Córdoba, Rosario, Mendoza, São Paulo, "
        "Santiago de Chile, Madrid, Nueva York, Londres y Tokio."
    ),
    model=MODEL,
    tools=[get_weather],
)


async def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: falta OPENAI_API_KEY en el entorno", file=sys.stderr)
        sys.exit(1)
    print(f"Rai (modelo: {MODEL}) — escribí 'salir' para terminar\n")
    while True:
        try:
            user_input = input("Vos: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in {"salir", "exit", "quit"}:
            break
        try:
            result = await Runner.run(agent, user_input)
        except Exception as exc:
            print(f"[error] {exc}\n", file=sys.stderr)
            continue
        print(f"Rai: {result.final_output}\n")


if __name__ == "__main__":
    asyncio.run(main())
