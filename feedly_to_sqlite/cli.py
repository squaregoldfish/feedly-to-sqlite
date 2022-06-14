import time
from datetime import timedelta, date
import click
import pathlib
import json
import sqlite_utils
import requests
from urllib.parse import quote_plus
from feedly_to_sqlite import utils

FEEDLY_API_URL = "https://cloud.feedly.com"


@click.group()
@click.version_option()
def cli():
    "Save data from feedly to a SQLite database"


@cli.command()
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default="auth.json",
    help="Path to save tokens to, defaults to auth.json",
)
@click.argument("developer_token", required=False)
def auth(auth, developer_token):
    "Save authentication credentials to a JSON file"
    auth_data = {}
    if pathlib.Path(auth).exists():
        auth_data = json.load(open(auth))

    if developer_token:
        auth_data["developer_token"] = developer_token
    else:
        click.echo(
            "Visit the following link and find your personal developer token: https://feedly.com/v3/auth/dev"
        )
        auth_data["developer_token"] = click.prompt("feedly developer token")

    open(auth, "w").write(json.dumps(auth_data, indent=4) + "\n")
    click.echo()
    click.echo(
        "Your credentials have been saved to {}. You can now import feedly data by running".format(
            auth
        )
    )
    click.echo()
    click.echo("    feedly-to-sqlite subscriptions feedly.db")
    click.echo()


COLLECTION_KEYS = ["label", "created", "id"]
FEED_KEYS = [
    "id",
    "topics",
    "title",
    "website",
    "updated",
    "language",
    "state",
    "description",
]
BOARD_KEYS = ["label", "id"]
ITEM_ROOT_KEYS = ["id", "title", "published", "crawled", "unread", "readTime", "actionTimestamp"]
ITEM_SUB_KEYS = {
    "origin": ["title"],
    "content": ["content"]
}
ITEM_SUB_ARRAY_KEYS = {
    "alternate": ["href", "type"],
}


@cli.command()
@click.argument(
    "db_path",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default="auth.json",
    help="Path to save tokens to, defaults to auth.json",
)
def subscriptions(db_path, auth):
    """Download feedly goals for the authenticated user"""
    db = sqlite_utils.Database(db_path)

    try:
        data = json.load(open(auth))
        token = data["developer_token"]
    except (KeyError, FileNotFoundError):
        utils.error(
            "Cannot find authentication data, please run `feedly_to_sqlite auth`!"
        )

    click.echo("Downloading subscriptions")
    r = requests.get(
        FEEDLY_API_URL + "/v3/collections",
        headers={"Authorization": "Bearer {}".format(token)},
    )
    r.raise_for_status()

    collections = r.json()
    for coll in collections:
        feeds = coll["feeds"]
        coll_id = coll["id"]
        coll_data = {k: coll.get(k) for k in COLLECTION_KEYS}
        db["collections"].upsert(coll_data, pk="id")
        for f in feeds:
            feed_data = {k: f.get(k) for k in FEED_KEYS}
            db["collections"].update(coll_id).m2m(db.table("feeds", pk="id"), feed_data)

    click.echo("Downloading boards")
    r = requests.get(
        FEEDLY_API_URL + "/v3/boards",
        headers={"Authorization": "Bearer {}".format(token)},
    )
    r.raise_for_status()

    boards = r.json()
    for board in boards:
        board_id = board["id"]
        board_data = {k: board.get(k) for k in BOARD_KEYS}
        db["boards"].upsert(board_data, pk="id")

        # Get the contents of each board
        r = requests.get(
            FEEDLY_API_URL + "/v3/streams/contents?streamId=" + quote_plus(board_id) + "&unreadOnly=false&ranked=oldest&count=500",
            headers={"Authorization": "Bearer {}".format(token)},
        )
        r.raise_for_status()

        contents = r.json()
        for item in contents["items"]:
            item_data = {k: item.get(k) for k in ITEM_ROOT_KEYS}
            for parent in ITEM_SUB_KEYS:
                if parent in item:
                    parent_dict = item.get(parent)
                    sub_values = {parent + "_" + k: parent_dict.get(k) for k in ITEM_SUB_KEYS[parent]}
                    item_data.update(sub_values)

            for parent in ITEM_SUB_ARRAY_KEYS:
                if parent in item:
                    parent_dict = item.get(parent)[0]
                    sub_values = {parent + "_" + k: parent_dict.get(k) for k in ITEM_SUB_ARRAY_KEYS[parent]}
                    item_data.update(sub_values)

            db["boards"].update(board_id).m2m(db.table("items", pk="id"), item_data)


if __name__ == "__main__":
    cli()
