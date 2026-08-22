# Investment Tracker

Self-hosted investment tracker that auto-imports Interactive Brokers (IBKR) fill emails from a forwarding Gmail inbox and pushes a Telegram alert per fill. Mirrors the architecture of `expense_tracker` with IBKR as the only supported broker.

## Prerequisites

- Python 3.12+
- MySQL 8 (or Docker to run MySQL in a container)
- Gmail account with App Password
- Telegram bot token (from [@BotFather](https://t.me/BotFather))

## Installation

### 1. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone and setup environment

```bash
git clone <repository-url>
cd investment-tracker
cp .env.example .env
```

### 3. Configure environment

Edit `.env` with your settings:

```env
TIMEZONE=Asia/Singapore
MYSQL_HOST=mysql
MYSQL_PORT=3306
MYSQL_USER=investment_user
MYSQL_PASSWORD=investment_password
MYSQL_DATABASE=investment_tracker
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USERNAME=your-email@gmail.com
IMAP_PASSWORD=your-app-password
POLL_INTERVAL_SECONDS=60
HEALTH_PORT=8080
LOG_LEVEL=INFO
```

### 4. Database Setup (with Docker Compose)

```bash
docker network create investment-tracker-net
docker compose up -d investment-tracker
```

The application container connects to an existing MySQL 8 container on the same Docker network. Tortoise generates the schema on first startup.

### 5. Manual DB Onboarding

Connect to MySQL and add users:

```sql
INSERT INTO users (telegram_chat_id, name, active) VALUES (123456789, 'Your Name', true);
INSERT INTO user_emails (user_id, email) VALUES (1, 'your-email@gmail.com');
```

### 6. Telegram Setup

1. Start a conversation with your bot by sending `/start`
2. Forward IBKR fill emails to your configured inbox

## Email Forwarding Setup

Configure your Gmail to forward IBKR fill emails (sender `TradingAssistant@interactivebrokers.com`) to the shared inbox. The parser only accepts emails that match the IBKR sender domain AND contain a `BOUGHT ... @ ...` or `SOLD ... @ ...` summary line in the subject or body — margin notices and dividend emails from the same sender are ignored.

Sample accepted summary line:

```
BOUGHT 100 MRNA @ 108.31 (UXXX6864)
SOLD 10 SGOV @ 100.5805 (UXXX6864)
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/help` | Show help text |
| `/ping` | Check bot is alive |
| `/latest [count]` | Show latest trades (default: 10, max: 50) |
| `/today` | Today's trade counts + USD notional |
| `/week` | This week's trade counts |
| `/month` | This month's trade counts |
| `/range <start> <end>` | Trades in date range (`YYYY-MM-DD`) |
| `/search <symbol>` | Search trades by symbol substring |
| `/delete <id|index>` | Start delete confirmation |
| `/confirm [id|index]` | Confirm a pending delete (omit the index to confirm all) |
| `/cancel [id|index]` | Cancel pending delete(s) |

### Alert format

Every successfully imported fill triggers a Telegram alert like:

```
�� New trade recorded
You bought 100 MRNA @ USD 108.31
Notional: USD 10,831.00
Account: UXXX6864
Time: 22 Aug 2026 17:35
```

## Healthcheck

The application exposes an in-process HTTP endpoint at `http://localhost:$HEALTH_PORT/health` (default port `8080`). Returns `200 OK` when both the Telegram bot and email poller are running, `503` otherwise. Does not call Telegram or touch the database.

The Docker healthcheck runs:

```bash
python -m app.cli healthcheck
```

This CLI does an HTTP GET against the local endpoint and exits `0` on `200`.

## Database Migrations

Tortoise auto-generates the schema on first startup (`Tortoise.generate_schemas()`). A reference DDL is in `migrations/01_initial_setup.sql` for manual bootstrapping.

For schema changes, add a new SQL migration under `migrations/`.

## Running Tests

```bash
uv sync --extra dev
uv run pytest tests/
```

Tests run independently without MySQL, IMAP, or Telegram dependencies.

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format .
```

## Architecture

- **IBKR Parser**: Single `IBKRParser` extending `BaseParser`. Matches the IBKR sender domain AND the `BOUGHT/SOLD <qty> <SYMBOL> @ <price> (<account>)` summary line.
- **Parser Registry**: Order-independent dispatch — first parser whose `can_parse()` returns True is selected.
- **Telegram Bot**: Command-based interface with whitelist authorization loaded from `users.telegram_chat_id`.
- **Email Poller**: IMAP polling of unseen emails with `message_id`-based dedup via `imported_emails`.
- **Database**: Tortoise-ORM async ORM with repositories (`UserRepository`, `UserEmailRepository`, `TradeRepository`, `ImportedEmailRepository`).
- **Timezone**: All user-facing times in SGT (`Asia/Singapore`), UTC at the DB storage boundary only.

## Local Development (without Docker)

The full application (Telegram bot + poller + health server) runs locally with `uv run python -m app.main`. MySQL must be available — either installed directly or in a Docker container.

**1. Install dependencies**

```bash
uv sync
```

**2. MySQL**

```bash
docker run -d \
  --name investment-mysql \
  -e MYSQL_ROOT_PASSWORD=rootpassword \
  -e MYSQL_DATABASE=investment_tracker \
  -e MYSQL_USER=investment_user \
  -e MYSQL_PASSWORD=investment_password \
  -p 3306:3306 \
  mysql:8
```

**3. Configure `.env`**

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=investment_user
MYSQL_PASSWORD=investment_password
MYSQL_DATABASE=investment_tracker
TELEGRAM_BOT_TOKEN=your-bot-token
IMAP_USERNAME=your-email@gmail.com
IMAP_PASSWORD=your-app-password
POLL_INTERVAL_SECONDS=60
TIMEZONE=Asia/Singapore
LOG_LEVEL=INFO
```

**4. Bootstrap users**

Tortoise creates the schema automatically on first startup. Insert user rows manually:

```sql
INSERT INTO users (telegram_chat_id, name, active) VALUES (123456789, 'Your Name', true);
INSERT INTO user_emails (user_id, email) VALUES (1, 'your-forwarding-email@gmail.com');
```

**5. Run**

```bash
uv run python -m app.main