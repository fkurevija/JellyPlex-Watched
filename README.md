# JellyPlex-Watched

[![Codacy Badge](https://app.codacy.com/project/badge/Grade/26b47c5db63942f28f02f207f692dc85)](https://www.codacy.com/gh/luigi311/JellyPlex-Watched/dashboard?utm_source=github.com&utm_medium=referral&utm_content=luigi311/JellyPlex-Watched&utm_campaign=Badge_Grade)

> This repository is a personal fork of [luigi311/JellyPlex-Watched](https://github.com/luigi311/JellyPlex-Watched). It is maintained for my own use while I implement synchronization of unwatched states between media servers. Changes may differ from the original project and are not intended to represent the upstream project.

Sync watched between jellyfin, plex and emby locally

## Description

Keep in sync all your users watched history between jellyfin, plex and emby servers locally. This uses file names and provider ids to find the correct episode/movie between the two. This is not perfect but it works for most cases. You can use this for as many servers as you want by entering multiple options in the .env plex/jellyfin section separated by commas.

Watched-state history is stored in SQLite at `WATCHED_STATE_DB` (default:
`.jellyplex-watched-state.db`). If the previous JSON state file exists at
`WATCHED_STATE_FILE`, it is migrated automatically the first time the SQLite
database is initialized.

### Persisting state in Docker

Manual-unwatch propagation (detecting that an item was watched → unwatched
so the change can sync to the other server) depends on comparing the current
scan against the state recorded during the *previous* scan. If you run this
container with `RUN_ONLY_ONCE=True` and a restart policy such as
`unless-stopped`, the container exits after each run and Docker recreates it,
which wipes the container's filesystem — including the SQLite state
database, `log.log`, and `mark.log` — unless you mount a persistent volume.
Without persisted state, every scan looks like the "first ever" comparison
between servers, and unwatch actions can be silently overwritten by whichever
server's watched state is processed first.

To avoid this, mount a volume (see `docker-compose.yml` for an example
mounting `./data:/app/data`) and point `WATCHED_STATE_DB` (and optionally
`LOG_FILE`/`MARK_FILE`) at a path under that mounted directory, e.g.
`WATCHED_STATE_DB=data/jellyplex-watched-state.db`.

## Features

### Plex

- \[x] Match via filenames
- \[x] Match via provider ids
- \[x] Map usernames
- \[x] Use single login
- \[x] One way/multi way sync
- \[x] Sync watched
- \[x] Sync in progress
- \[ ] Sync view dates

### Jellyfin

- \[x] Match via filenames
- \[x] Match via provider ids
- \[x] Map usernames
- \[x] Use single login
- \[x] One way/multi way sync
- \[x] Sync watched
- \[x] Sync in progress
- \[x] Sync view dates


### Emby

- \[x] Match via filenames
- \[x] Match via provider ids
- \[x] Map usernames
- \[x] Use single login
- \[x] One way/multi way sync
- \[x] Sync watched
- \[x] Sync in progress
- \[x] Sync view dates


## Configuration

Full list of configuration options can be found in the [.env.sample](.env.sample)

## Installation

### Baremetal

- [Install uv](https://docs.astral.sh/uv/getting-started/installation/)

- Create a .env file similar to .env.sample; fill in baseurls and tokens, **remember to uncomment anything you wish to use** (e.g., user mapping, library mapping, black/whitelist, etc.). If you want to store your .env file anywhere else or under a different name you can use ENV_FILE variable to specify the location.

- Run

  ```bash
  uv run main.py
  ```

  ```bash
  ENV_FILE="Test.env" uv run main.py
  ```

### Docker

- Build docker image

  ```bash
  docker build -t jellyplex-watched .
  ```

- or use pre-built image

  ```bash
  docker pull fkurevija/jellyplex-watched:latest
  ```

#### With variables

- Run

  ```bash
  docker run --rm -it -e PLEX_TOKEN='SuperSecretToken' fkurevija/jellyplex-watched:latest
  ```

#### With .env

- Create a .env file similar to .env.sample and set the variables to match your setup

- Run

  ```bash
   docker run --rm -it -v "$(pwd)/.env:/app/.env" fkurevija/jellyplex-watched:latest
  ```

## Troubleshooting/Issues

- Jellyfin

  - Attempt to decode JSON with unexpected mimetype, make sure you enable remote access or add your docker subnet to lan networks in jellyfin settings

- Configuration
  - Do not use quotes around variables in docker compose
  - If you are not running all 3 supported servers, that is, Plex, Jellyfin, and Emby simultaneously, make sure to comment out the server url and token of the server you aren't using.

## Contributing

I am open to receiving pull requests. If you are submitting a pull request, please make sure run it locally for a day or two to make sure it is working as expected and stable.

## License

This is currently under the GNU General Public License v3.0.
