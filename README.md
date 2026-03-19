# TubeChecker

A lightweight, self-hosted tool that watches YouTube channels via RSS, detects new videos, and automatically dispatches them to a [MeTube](https://github.com/alexta69/metube) instance for downloading. Optionally triggers a Jellyfin library refresh after new videos are queued.

Runs as a single Docker container with a built-in web UI. No external services, no message queues — just a SQLite database and a scheduler.

## Features

- Polls YouTube channel RSS feeds on a configurable interval
- Resolves channels from a `@handle`, full URL, or bare `UC…` channel ID
- Filters by start date — only downloads videos published on or after a given date
- Per-channel download folder configuration
- Download history with status tracking (`sent` / `failed`)
- Retry failed downloads individually or in bulk
- Optional Jellyfin library refresh after new videos are queued

## Requirements

- Docker + Docker Compose
- A running [MeTube](https://github.com/alexta69/metube) instance
- (Optional) A running [Jellyfin](https://jellyfin.org) instance

---

## Quick Start (published image)

No clone required. Create a `docker-compose.yml`:

```yaml
services:
  tubechecker:
    image: ghcr.io/spaggel/tubechecker:latest
    container_name: tubechecker
    restart: unless-stopped
    ports:
      - "8083:8083"
    volumes:
      - ./data:/data
    environment:
      - METUBE_URL=http://your-metube-host:8081
      - CHECK_INTERVAL=60
      # - JELLYFIN_URL=http://your-jellyfin-host:8096
      # - JELLYFIN_API_KEY=your_key_here
```

Then run:

```bash
docker compose up -d
```

The UI is available at `http://localhost:8083`.

Open **Settings** and set your MeTube URL, then add channels from the **Channels** view.

---

## Integration into an Existing Docker Compose Stack

If you already run MeTube (and optionally Jellyfin) in a shared `docker-compose.yml`, add TubeChecker as another service. Because all containers share the same Compose network by default, you can reference MeTube by its service name.

### Without a reverse proxy

```yaml
tubechecker:
  image: ghcr.io/spaggel/tubechecker:latest
  container_name: tubechecker
  restart: unless-stopped
  ports:
    - "8083:8083"
  volumes:
    - ${DATA_DIR}/tubechecker:/data
  environment:
    - METUBE_URL=http://metube:8081     # internal Docker service name
    - CHECK_INTERVAL=60
    # - JELLYFIN_URL=http://jellyfin:8096
    # - JELLYFIN_API_KEY=your_key_here
```

### With Traefik

```yaml
tubechecker:
  image: ghcr.io/spaggel/tubechecker:latest
  container_name: tubechecker
  restart: unless-stopped
  volumes:
    - ${DATA_DIR}/tubechecker:/data
  environment:
    - METUBE_URL=http://metube:8081
    - CHECK_INTERVAL=60
    # - JELLYFIN_URL=http://jellyfin:8096
    # - JELLYFIN_API_KEY=your_key_here
  labels:
    - "traefik.enable=true"
    - "traefik.http.routers.tubechecker.rule=Host(`${URL_TUBECHECKER}`)"
    - "traefik.http.routers.tubechecker.entrypoints=websecure"
    - "traefik.http.routers.tubechecker.tls.certresolver=myresolver"
    - "traefik.http.services.tubechecker.loadbalancer.server.port=8083"
```

Add `URL_TUBECHECKER=channels.yourdomain.com` to your `.env` file.

> **Note:** The web UI has no built-in authentication. If it is publicly accessible, protect it with a Traefik `basicauth` middleware or equivalent.

---

## Build from Source

```bash
git clone https://github.com/Spaggel/TubeChecker.git
cd TubeChecker
docker compose up -d --build
```

---

## Configuration

All settings can be configured from the **Settings** view in the UI and are persisted to the database. Environment variables seed the database on first run and act as defaults — subsequent UI changes take precedence.

| Environment Variable | Default                    | Description                                              |
|----------------------|----------------------------|----------------------------------------------------------|
| `DATA_DIR`           | `/data`                    | Directory where the SQLite database is stored            |
| `METUBE_URL`         | `http://localhost:8081`    | Base URL of your MeTube instance (no trailing slash)     |
| `CHECK_INTERVAL`     | `60`                       | How often to poll RSS feeds, in minutes                  |
| `JELLYFIN_URL`       | *(empty)*                  | Base URL of your Jellyfin instance — leave empty to disable |
| `JELLYFIN_API_KEY`   | *(empty)*                  | Jellyfin API key (Dashboard → API Keys)                  |

---

## Usage

### Adding a channel

1. Go to **Channels** and click **Add Channel**.
2. Enter any of the following in the channel field:
   - A `@handle` (e.g. `@mkbhd`)
   - A full channel URL (e.g. `https://www.youtube.com/@mkbhd`)
   - A bare channel ID starting with `UC…`
3. Optionally set a **Start Date** to limit downloads to videos published on or after that date. Leave empty to download all available videos.
4. Optionally set a **Download Folder** — a subfolder inside MeTube's download directory. Defaults to the channel name.
5. Click **Add Channel**. The channel name is auto-fetched from YouTube if you leave it blank.

### Checking for new videos

- Channels are checked automatically on the configured interval (default: every 60 minutes).
- Click **Check Now** on any row to trigger an immediate check for a single channel.
- Click **Check All Now** to trigger an immediate check for all channels.

### Viewing download history

- **History** shows the most recent 200 dispatched videos across all channels, with status (`sent` / `failed`).
- Hover over a `failed` badge to see the error detail.
- Use the retry button on any row, or **Retry All Failed**, to re-dispatch failed downloads.

### Per-channel video history

- Click the playlist icon on any channel row to open that channel's video history.
- The same retry controls are available scoped to just that channel.

### Jellyfin integration

1. In **Settings**, enter your Jellyfin URL and API key.
2. Click **Save Settings**.
3. After each scheduled check that dispatches at least one new video, a library refresh is triggered automatically.
4. The **Refresh Jellyfin** button in the Channels view (and the test button in Settings) let you trigger a refresh manually.

---

## Updating

**Published image:**
```bash
docker compose pull tubechecker
docker compose up -d tubechecker
```

**Built from source:**
```bash
git -C /path/to/TubeChecker pull
docker compose up -d --build tubechecker
```

The SQLite database is stored in the mounted volume and is preserved across updates.

---

## Stack

| Layer     | Technology                          |
|-----------|-------------------------------------|
| Backend   | Python 3.12, FastAPI, APScheduler   |
| Database  | SQLite via SQLAlchemy               |
| Frontend  | Vue 3 (CDN), Bootstrap 5 (CDN)      |
| Container | Docker (single image, no build step for frontend) |
