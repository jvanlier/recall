# Cards repository

`recall` keeps cards and review history in a separate, private Git repository.
The example repository in [`examples/cards/`](../examples/cards/) is a starter
template; copy it into your cards repository before adding your own decks.

## Create the repository

Create a private GitHub repository for the cards. The planned repository is
[`jvanlier/recall-cards`](https://github.com/jvanlier/recall-cards). If you
start from scratch, give the app's server deploy key write access to the
repository under **Settings → Deploy keys**.

Clone it over SSH and copy the starter kit:

```sh
git clone git@github.com:jvanlier/recall-cards.git
cp -a /path/to/recall/examples/cards/. recall-cards/
cd recall-cards
```

Install Docker first; the offline link checker uses the `lychee-docker`
hook. Then install the hooks once per clone:

```sh
uvx prek install
```

The starter kit includes `.gitattributes` so concurrent review-log appends
merge as a union, and `.recall/config.toml` documenting the scheduler
defaults. The sample decks and image are safe to replace.

## Daily loop

Edit decks in nvim, then run the hooks and commit your changes:

```sh
uvx prek run --all-files
git add .
git commit -m "cards: update Spanish vocabulary"
git push
```

The server pulls card edits and pushes review sessions. Do not edit
`.recall/reviews.jsonl` by hand; it is the app's append-only state.
