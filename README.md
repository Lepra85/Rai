# Rai

Personal AI on a VPS, accessible from Telegram.

A DigitalOcean droplet running [Claude Code](https://github.com/anthropics/claude-code) (foundation for Daniel Miessler's [PAI](https://github.com/danielmiessler/PAI)) with a small Python bot that bridges Telegram messages to a persistent Claude Code session per chat.

## Architecture

```
You (Telegram on your phone)
        |
        v   HTTPS, long-poll
+-------------------+
|  Telegram Bot     |  Python (python-telegram-bot)
|  /opt/rai/bot     |  systemd: rai-bot.service
+-------------------+
        |   subprocess
        v
+-------------------+
|  Claude Code CLI  |  npm: @anthropic-ai/claude-code
|  (~/.claude)      |  authenticated with your Anthropic account
+-------------------+
        |
        v
   Anthropic API
```

- **One Anthropic login** per droplet (the `rai` user runs `claude login` once).
- **Per-chat memory**: the bot stores a Claude session id per Telegram chat in `~/.rai/sessions.json` and resumes it on every message via `claude --resume`.
- **Whitelist**: only chat ids in `RAI_ALLOWED_CHAT_IDS` are answered.

## Repo layout

```
infra/
  cloud-init.yaml            full bootstrap (deps, Claude Code, bot, systemd)
  setup-droplet.sh           setup script run by cloud-init on the droplet
  systemd/rai-bot.service    systemd unit for the bot
  droplet.json               (gitignored) DO API response from creation
bot/
  main.py                    Telegram <-> Claude Code bridge
  requirements.txt
  .env.example               TELEGRAM_BOT_TOKEN + RAI_ALLOWED_CHAT_IDS
.secrets/                    (gitignored) SSH keypair, droplet IP
```

## Provisioning (already done from this branch)

The droplet was created via the DigitalOcean API:

- Region: `nyc3`
- Size: `s-1vcpu-2gb` ($12/mo)
- Image: `ubuntu-24-04-x64`
- IPv6 + monitoring on, backups off
- `cloud-init` from `infra/cloud-init.yaml`

## Final steps (do these once, in the DigitalOcean Web Console on your phone)

The droplet boots with everything installed but _not started_. You need to log in
to Anthropic once and provide a Telegram bot token.

1. **Open the Web Console** for the droplet (DigitalOcean dashboard → your
   droplet → "Console"). It is mobile-friendly: works in the browser, no SSH
   client needed.

2. **Switch to the `rai` user**:
   ```bash
   su - rai
   ```

3. **Wait for cloud-init to finish** (first boot only, takes 5-10 min):
   ```bash
   ls /var/log/rai-setup-done   # appears when done
   tail -f /var/log/rai-setup.log
   ```

4. **Log in to Anthropic** (interactive — prints a URL):
   ```bash
   claude login
   ```
   Open the URL on your phone, authorize, paste the code back into the console.

5. **Configure the bot**:
   ```bash
   sudo cp /opt/rai/bot/.env.example /opt/rai/bot/.env
   sudo nano /opt/rai/bot/.env
   ```
   Set:
   - `TELEGRAM_BOT_TOKEN=...` (from @BotFather in Telegram)
   - `RAI_ALLOWED_CHAT_IDS=<your numeric chat id>` (from @userinfobot)

6. **Start the bot**:
   ```bash
   sudo systemctl start rai-bot
   sudo systemctl status rai-bot
   sudo journalctl -u rai-bot -f
   ```

7. **Test from Telegram**: open your bot, send `/start`, then any message.

## Bot commands

- `/start` — greeting
- `/id` — shows your Telegram chat id (use it to populate `RAI_ALLOWED_CHAT_IDS`)
- `/reset` — drops the saved session for your chat
- any other text — forwarded to Claude Code with `--resume` so the conversation persists

## Adding PAI on top (optional)

Once the bot works with bare Claude Code, layer PAI:

```bash
# as user 'rai'
curl -fsSL https://ourpai.ai/install.sh | bash
```

Skip / disable the Pulse dashboard (no web UI exposed). The bot picks up PAI
skills, agents and hooks automatically because Claude Code reads `~/.claude/`.

## Cost & teardown

- Droplet: **$12/mo** (NYC3, 2 GB / 1 vCPU). ~$0.018/hour.
- Anthropic: per the Claude subscription tied to the account you log in with.

Destroy:

```bash
curl -X DELETE -H "Authorization: Bearer $DO_TOKEN" \
  https://api.digitalocean.com/v2/droplets/<id>
```

## Security notes

- SSH: password auth disabled, key-only, root login key-only.
- UFW: only port 22 open inbound.
- `fail2ban` enabled.
- Telegram bot uses long-poll, no public webhook exposed.
- `RAI_ALLOWED_CHAT_IDS` whitelist is the main auth barrier — keep it tight.
- The DO API token used for provisioning should be rotated after setup.
