# Deployment

The server runs `recall` in Docker and mounts a clone of the private cards
repository. The container uses a GitHub deploy key to push review sessions
back to that repository.

## First deployment

Install Docker Engine and the Docker Compose plugin on the server. Run the
following commands in a directory where the deployment will live:

```sh
git clone git@github.com:jvanlier/recall-cards.git recall-cards
mkdir -p secrets
ssh-keygen -t ed25519 -f secrets/deploy_key -C recall@home-server
chmod 600 secrets/deploy_key
```

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

The cards directory and the two secret files must be readable by the
container user (UID 1000), and the cards directory must be writable. For
example, when the server account owns these files, no extra permissions are
needed.

Create a `.env` file next to `compose.yaml` and set the identity used for
review commits. Keep this file and the `secrets/` directory private:

```dotenv
PORT=8000
TZ=Europe/Amsterdam
GIT_AUTHOR_NAME=Recall
GIT_AUTHOR_EMAIL=recall@example.invalid
GIT_COMMITTER_NAME=Recall
GIT_COMMITTER_EMAIL=recall@example.invalid
```

Build and start the service:

```sh
docker compose up -d
```

It serves on `http://server:8000` by default. The health endpoint is
`/healthz`.

## Updates

Pull the application changes, then either pull a published image or build the
local image, and restart the service:

```sh
git pull --ff-only
docker compose pull                 # when using a published image
docker compose build --pull         # when building from this checkout
docker compose up -d
```

Do not run both `pull` and `build` unless you need both workflows.

## Logs

Follow the application logs with:

```sh
docker compose logs -f recall
```

The app's Git failures are also shown as a warning on the deck-list page and
are retried by the next sync trigger. The cards clone can be inspected on the
server with normal Git commands; review commits are pushed automatically when
a session ends, after five minutes of inactivity, and during shutdown.
