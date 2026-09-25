# Deployment

The server runs `recall` in Docker and mounts a clone of the private cards
repository. The container uses a GitHub deploy key to push review sessions
back to that repository.

## First deployment

Install Docker Engine and the Docker Compose plugin on the server. Run the
following commands in a directory where the deployment will live:

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
with **Allow write access** enabled. The private key stays on the server and
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

Compose runs as UID 1000 by default. The cards directory and both secret
files must be readable by that UID, and the cards directory must be writable.
If the server account uses another non-root UID/GID, set `RECALL_UID` and
`RECALL_GID` in `.env` to `id -u` and `id -g`; the bind-mounted files must be
owned or readable by those IDs. Keep the deploy key mode at `600`.

Create a `.env` file next to `compose.yaml` and set the identity used for
review commits. Keep this file and the `secrets/` directory private:

```dotenv
PORT=8000
TZ=Europe/Amsterdam
GIT_AUTHOR_NAME=Recall
GIT_AUTHOR_EMAIL=recall@example.invalid
GIT_COMMITTER_NAME=Recall
GIT_COMMITTER_EMAIL=recall@example.invalid
# Optional when the server account is not UID/GID 1000:
# RECALL_UID=1001
# RECALL_GID=1001
```

Build and start the service:

```sh
docker compose up -d
```

It serves on `http://server:8000` by default. The health endpoint is
`/healthz`.

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

The app's Git failures are also shown as a warning on the deck-list page and
are retried by the next sync trigger. The cards clone can be inspected on the
server with normal Git commands; review commits are pushed automatically when
a session ends, after five minutes of inactivity, and during shutdown.
