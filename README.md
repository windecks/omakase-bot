# 🍣 Omakase.in Reservation Bot

Automated reservation bot for [omakase.in](https://omakase.in) with two operating modes:

- **Sniper** – Waits for the exact slot release time, then instantly books
- **Monitor** – Continuously checks for cancellation openings every N minutes

Built with [Playwright](https://playwright.dev/python/) + [playwright-stealth](https://github.com/AtuboDad/playwright_stealth) for reliable browser automation.

---

## ⚡ Quick Start

```bash
# 1. Clone & enter the project
cd omakase-bot

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browsers
playwright install chromium

# 5. Copy & edit config
cp config.example.yaml config.yaml
# Edit config.yaml with your credentials and target

# 6. Run
python main.py --config config.yaml
```

---

## 🎯 Modes

### Sniper Mode
Best for **new slot releases**. The bot:

1. Logs in and pre-loads the restaurant page
2. Waits until the exact release time (configurable, default midnight JST)
3. Rapidly refreshes and attempts to book the first matching slot
4. Retries up to `max_attempts` times with small random jitter

```bash
python main.py --config config.yaml --mode sniper --release-time 00:00
```

### Monitor Mode
Best for **cancellation hunting**. The bot:

1. Logs in once
2. Checks for availability every `check_interval` seconds (default: 300 = 5 min)
3. When a slot appears: auto-books or notifies (configurable)
4. Handles session expiry with automatic re-login

```bash
python main.py --config config.yaml --mode monitor --check-interval 300
```

---

## 🚀 Fleet Mode (Multi-Instance)

For production deployments where you want to monitor or snipe **multiple restaurants simultaneously** (or use multiple accounts), use the `fleet.py` manager.

1. Copy the example tasks config:
   ```bash
   cp tasks.yaml.example tasks.yaml
   ```
2. Define as many tasks as you want. Each task runs in an isolated process with its own session cookies.
3. Run the fleet:
   ```bash
   python fleet.py tasks.yaml
   ```

**Features:**
- **Self-Healing:** If a monitor task crashes, the fleet manager automatically restarts it.
- **Auto-Updates:** Checks for `cloakbrowser` PyPI updates every 24h and safely reloads the fleet if found.
- **Session Isolation:** Tasks using different emails automatically get their own isolated cookie jars in the `sessions/` folder to prevent account mixing.

---

## 🐳 Docker Deployment

The best way to run Fleet Mode 24/7 on a VPS is via Docker. The image is **multi-arch** (works on x86_64 and ARM64/aarch64), so it runs on everything from a DigitalOcean droplet to an Oracle Cloud free-tier ARM instance.

### Recommended: Docker Compose

```bash
# Edit tasks.yaml with your targets, then:
docker compose up -d --build
```

This gives you auto-restart on crash/reboot, resource limits, and log rotation out of the box. See `docker-compose.yml` for tuning options.

```bash
# View logs
docker compose logs -f

# Stop
docker compose down
```

### Alternative: Manual Docker Run

```bash
# Build the image
docker build -t omakase-bot .

# Run in background, mounting your config and sessions
docker run -d \
  --name omakase-fleet \
  --restart unless-stopped \
  -v $(pwd)/sessions:/app/sessions \
  -v $(pwd)/tasks.yaml:/app/tasks.yaml:ro \
  omakase-bot
```

---

## ⚙️ Configuration

### YAML Config File

Copy `config.example.yaml` to `config.yaml` and fill in your details:

```yaml
# Account
email: "you@example.com"
password: "your_password"

# Target
restaurant_id: "kv798125"       # From URL: /en/r/kv798125
date: "2026-07-12"              # YYYY-MM-DD
time: "18:00"                   # Preferred time (picks closest)
party_size: 2

# Mode
mode: "sniper"                  # "sniper" | "monitor"
auto_book: true                 # false = notify only, don't book
dry_run: false                  # true = run entire flow but stop right before final confirm click

# Sniper settings
release_time: "00:00"           # HH:MM in JST
max_attempts: 100

# Monitor settings
check_interval: 300             # Seconds between checks

# Browser
headless: true                  # false = show browser window
proxy: "http://user:pass@host:port"  # Optional residential proxy

```

### CLI Overrides

Any config field can be overridden via CLI flags:

```bash
python main.py \
  --config config.yaml \
  --mode monitor \
  --date 2026-08-01 \
  --time 19:00 \
  --party-size 4 \
  --headless false \
  --auto-book false \
  --dry-run true
```

**Priority:** CLI flags > YAML config > defaults.

### All CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `--config` / `-c` | Path to YAML config file | – |
| `--email` | Login email | – |
| `--password` | Login password | – |
| `--restaurant-id` | Restaurant ID from URL | – |
| `--date` | Target date (YYYY-MM-DD) | – |
| `--time` | Preferred time (HH:MM) | `18:00` |
| `--party-size` | Number of guests | `2` |
| `--mode` | `sniper` or `monitor` | `sniper` |
| `--auto-book` | Auto-complete booking | `true` |
| `--dry-run` | Run entire flow but stop before final confirm | `false` |
| `--release-time` | Slot drop time in JST (HH:MM) | `00:00` |
| `--max-attempts` | Max sniper retries | `100` |
| `--check-interval` | Monitor poll interval (seconds) | `300` |
| `--headless` | Run browser headless | `true` |
| `--proxy` | Residential proxy URL | – |

---

## 🔍 How It Works

### Authentication
1. Attempts to restore a saved session (`session.json`) first
2. Falls back to full login via the web form
3. Uses adaptive selectors to find login elements
4. Saves cookies after successful login for reuse

### Booking Flow
1. Navigate to restaurant page
2. Set party size (if selector exists)
3. Navigate calendar to target month
4. Click the target date
5. Find available time slots
6. Pick the slot closest to your preferred time
7. Click the slot and complete any confirmation steps

### Anti-Detection
- **playwright-stealth** patches `navigator.webdriver` and other fingerprints
- Realistic Chrome user agent and viewport
- Random human-like delays between actions
- Tokyo timezone and `en-US` locale
- Cookie persistence to minimize login frequency

---

## 🐛 Debugging

### Screenshots
The bot automatically takes screenshots on failures, saved as `debug_*.png` in the project root.

### Headed Mode
Run with `--headless false` to watch the browser in real-time:

```bash
python main.py --config config.yaml --headless false
```

### Verbose Logging
All actions are logged to stdout with timestamps and color coding.

---

## 📁 Project Structure

```
omakase-bot/
├── main.py                 # Single-task CLI entry point
├── fleet.py                # Multi-task Fleet Manager
├── config.example.yaml     # Single-task config template
├── tasks.yaml.example      # Multi-task config template
├── Dockerfile              # Docker container definition
├── requirements.txt        # Python dependencies
├── src/
│   ├── __init__.py
│   ├── config.py           # Config loading & validation
│   ├── browser.py          # Playwright browser management
│   ├── auth.py             # Login & session management
│   ├── reservation.py      # Calendar nav, slot finding, booking
│   ├── sniper.py           # Sniper mode logic
│   ├── monitor.py          # Monitor mode logic
│   └── notifications.py    # Colored output & sound alerts
└── README.md
```

---

## ⚠️ Disclaimer

This bot is for personal use only. Use responsibly and respect omakase.in's terms of service. The author is not responsible for any account restrictions or bans resulting from automated access.

---

## 📝 Notes

- **Release times vary by restaurant.** Check the restaurant page for their specific schedule. Default is midnight JST.
- **Session cookies** are saved to `session.json` for reuse. Delete this file to force a fresh login.
- **2-Step Verification**: If your omakase.in account has email-based 2FA enabled, you'll need to handle the verification code manually during the first login (use `--headless false`).
- **Debug screenshots** are automatically gitignored.
