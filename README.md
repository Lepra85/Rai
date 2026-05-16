# Rai

Bot de Telegram con OpenAI Agents SDK, corriendo en un droplet de DigitalOcean.

Es la base sobre la que se construye un **agente vertical para un café** (3 sucursales en CABA): facturas, remitos, stock, pedidos. La conversación de discovery y el plan de MVP están en notas separadas — este README documenta solo el estado actual del código.

## Estado actual (Phase 1)

- Chat con memoria por `chat_id`, **en RAM** (se pierde al reiniciar — persistencia viene en la próxima fase)
- Modelo por default: `gpt-4o-mini` (override con `RAI_MODEL`)
- Whitelist de `chat_id` como única barrera de acceso

## Layout

```
agent/
  bot.py              bot de Telegram (OpenAI Agents SDK + memoria en RAM)
  agent.py            REPL para probar el agente sin Telegram
  requirements.txt
  run.sh              corre el REPL
  run-bot.sh          corre el bot localmente
infra/
  cloud-init-agent.yaml       cloud-init para el droplet
  install-bot.sh              instalador idempotente del bot en el droplet
  systemd/rai-bot.service     unit systemd
  droplet.json                (gitignored) respuesta DO de creación
.secrets/                     (gitignored) SSH keypair, droplet IP
```

## Variables de entorno

`agent/.env` (lo crea el cloud-init y lo completa `install-bot.sh`):

| Variable | Requerida | Descripción |
|---|---|---|
| `OPENAI_API_KEY` | sí | clave de OpenAI |
| `TELEGRAM_BOT_TOKEN` | sí | token de @BotFather |
| `TELEGRAM_ALLOWED_CHAT_IDS` | sí | lista de chat ids autorizados (coma-separados) |
| `RAI_MODEL` | no | default `gpt-4o-mini` |

## Comandos del bot

- `/start` — saludo
- `/id` — muestra tu `chat_id` (para configurar la whitelist)
- `/reset` — borra la memoria del chat
- cualquier otro texto — pasa al agente con la historia del chat

## Deploy

El droplet se crea con `infra/cloud-init-agent.yaml` (sustituye `__OPENAI_API_KEY__` en la creación). Una vez booteado:

```bash
sudo bash /home/rai/repo/infra/install-bot.sh
```

El script:
1. Pulls `origin/agent`
2. Instala deps del bot en venv
3. Pide `TELEGRAM_BOT_TOKEN` y `TELEGRAM_ALLOWED_CHAT_IDS` (si no están)
4. Instala y arranca `rai-bot.service`

Logs: `sudo journalctl -u rai-bot -f`

## Correr local (dev)

```bash
cd agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # editar con tus valores
./run-bot.sh           # bot completo
./run.sh               # REPL sin Telegram
```

## Costos y teardown

- Droplet: **~$12/mo** (NYC3, 2 GB / 1 vCPU)
- OpenAI: pay-as-you-go según uso

Destruir:

```bash
curl -X DELETE -H "Authorization: Bearer $DO_TOKEN" \
  https://api.digitalocean.com/v2/droplets/<id>
```

## Seguridad

- SSH: password auth deshabilitado, solo key
- UFW: solo 22/tcp abierto inbound
- `fail2ban` activo
- Telegram en long-poll, sin webhook público
- `TELEGRAM_ALLOWED_CHAT_IDS` es la barrera principal — mantenerla cerrada
