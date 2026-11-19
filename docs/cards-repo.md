# Cards repository

Total Recall keeps cards and review history in a separate, private Git repository.
The example repository in [`examples/cards/`](../examples/cards/) is a starter
template; copy it into your cards repository before adding your own decks.

## Create the repository

Create a private GitHub repository for the cards. The planned repository is
[`jvanlier/recall-cards`](https://github.com/jvanlier/recall-cards). If you
start from scratch, give the app's server read access to the
repository with a deploy key under **Settings → Deploy keys**.

Clone it over SSH and copy the starter kit:

```sh
git clone git@github.com:jvanlier/recall-cards.git
cp -a /path/to/recall/examples/cards/. recall-cards/
cd recall-cards
```

With `lychee` installed, install the hooks once per clone:

```sh
prek install
```

The starter kit includes `.recall/config.toml` documenting the scheduler
defaults, and a `.gitignore` for a local review database. The sample decks
and image are safe to replace.

## Daily loop

Edit decks in nvim, then run the hooks and commit your changes:

```sh
prek run --all-files
git add .
git commit -m "cards: update Spanish vocabulary"
git push
```

The server pulls card edits. Review history lives in the app's SQLite
database, not in this repository.
