# Deployment

The server runs Total Recall in Docker and mounts a clone of the private cards
repository, which it pulls with a read-only GitHub deploy key. Review history
is stored in a SQLite database in a separate `recall-data` directory.

## First deployment

Install Docker Engine and the Docker Compose plugin on the server. Clone the
application repository and enter its directory:

```sh
git clone git@github.com:jvanlier/recall.git recall
cd recall
```

If the application repository is already checked out, just enter that
checkout. Then run the following commands from its root:

```sh
mkdir -p secrets
ssh-keygen -t ed25519 -N "" -f secrets/deploy_key -C recall@home-server
chmod 600 secrets/deploy_key
```

This dedicated key has an empty passphrase because the container has no SSH
agent to unlock it. Protect `secrets/deploy_key` and do not reuse it for
interactive access.

Add `secrets/deploy_key.pub` to
[`jvanlier/recall-cards` → Settings → Deploy keys](https://github.com/jvanlier/recall-cards/settings/keys)
with **Allow write access** left off. The private key stays on the server and
is mounted read-only into the container; it is never copied into the image.

Create the known-hosts file and verify its fingerprint against GitHub's
[published SSH key fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints):

```sh
ssh-keyscan -t ed25519 github.com > secrets/known_hosts
ssh-keygen -lf secrets/known_hosts
chmod 644 secrets/known_hosts
```

Only after registering the deploy key and checking the fingerprint, clone the
cards repository with that key:

```sh
GIT_SSH_COMMAND="ssh -i \"$PWD/secrets/deploy_key\" \
  -o UserKnownHostsFile=\"$PWD/secrets/known_hosts\" \
  -o StrictHostKeyChecking=yes" \
  git clone git@github.com:jvanlier/recall-cards.git recall-cards
```

The image runs as the non-root user with UID 1000. The cards directory and
both secret files must be readable by that UID, and the cards and data
directories must be writable. If the server account uses another UID/GID,
use `sudo` to give the container user ownership of the mounts before
starting the service:

```sh
mkdir -p recall-data
sudo chown -R 1000:1000 recall-cards recall-data
sudo chown 1000:1000 secrets/deploy_key secrets/known_hosts
sudo chmod 600 secrets/deploy_key
```

Keep the deploy key mode at `600`.

Optionally, create a `.env` file next to `compose.yaml` to override the
defaults. Keep the `secrets/` directory private:

```dotenv
PORT=8000
TZ=Europe/Amsterdam
```

Build and start the service:

```sh
docker compose up -d
```

It serves on `http://server:8000` by default. The health endpoint is
`/healthz`.

## Backups

`recall-data/reviews.db` holds the complete review history and is not in Git,
so include it in the server's backups. To take a consistent copy while the app
is running:

```sh
docker compose exec recall python -c \
  "import sqlite3; sqlite3.connect('/data/reviews.db').backup(sqlite3.connect('/data/backup.db'))"
```

## Updates

CI builds the image but does not publish it, so this checkout uses a local
build. Pull the application changes, rebuild, and restart the service:

```sh
git pull --ff-only
docker compose build --pull
docker compose up -d
```

If a published image is configured later by adding an `image:` entry to
`compose.yaml`, use `docker compose pull` instead of `docker compose build
--pull`, then run `docker compose up -d`.

## Logs

Follow the application logs with:

```sh
docker compose logs -f recall
```

The app's Git pull failures are also shown as a warning on the deck-list page
and are retried on the next deck load. The server clone is pulled with
`--ff-only`, so it must never have local commits.
