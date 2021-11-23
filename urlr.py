import datetime
import json
import os
import pathlib
import shutil
import string
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

import toml
import typer
from bs4 import BeautifulSoup
from jsondb import DuplicateEntryError, jsondb
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

app = typer.Typer()
date_format = "%a %d %b %Y %X"

TOMLEXT = ".toml"
command = string.Template("$editor $filename")
fuzzy_search_command = string.Template(
    'echo -n "$options" | sk -m --color="prompt:27,pointer:27" --preview="urlr preview {}" --preview-window=up:50%'
)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.9.0.7) Gecko/2009021910 Firefox/3.0.7"
}

console = Console()
title_style = Style(color="grey74")
url_style = Style(color="blue", underline=True)
description_style = Style(color="white")


# template
"""
[[-]]
url = ''
title = ''
description= ''
tags = []
"""
bookmark_template = {"-": [{"url": "", "title": "", "description": "", "tags": []}]}


def environ_present(key="EDITOR"):
    return key in os.environ


def format_date(dtms):
    seconds, micros = divmod(dtms, 1000000)
    days, seconds = divmod(seconds, 86400)
    bmdate = datetime.datetime(1601, 1, 1) + datetime.timedelta(days, seconds, micros)
    return bmdate.strftime(date_format)


def open_temp_toml_file(template=bookmark_template):
    if environ_present("EDITOR"):
        editor = os.environ["EDITOR"]
        fd, filename = tempfile.mkstemp(suffix=TOMLEXT, text=True)
        with open(filename, "w") as file:
            toml.dump(template, file)
        write_status = subprocess.call(
            command.substitute(editor=editor, filename=filename), shell=True
        )
        if write_status != 0:
            os.remove(filename)
        return filename, write_status
    else:
        raise Exception("EDITOR not found in env")


def format_text(bookmark):
    newline = Text("\n\n", justify="center")
    bookmark_text = Text(justify="center")
    bookmark_text.append_text(Text(bookmark.get("title"), style=title_style))
    bookmark_text.append_text(newline)

    if bookmark.get("description"):
        bookmark_text.append_text(
            Text(bookmark.get("description"), style=description_style)
        )
        bookmark_text.append_text(newline)

    bookmark_text.append(Text(bookmark.get("url"), style=url_style))
    bookmark_text.append_text(newline)

    tags = bookmark.get("tags")
    colored_tags = map(lambda x: "[black on blue]#" + x + "[/]", tags)
    tags = " ── ".join(colored_tags)
    return Panel(
        bookmark_text,
        title=str(bookmark.get("_id")),
        title_align="left",
        subtitle=tags + " ── " + bookmark.get("added_date"),
        subtitle_align="right",
        padding=1,
    )


def display_bookmark(bookmarks: List[Dict]):
    if bookmarks:
        for bookmark in bookmarks:
            console.print("\n\n")
            console.print(format_text(bookmark))


def deduce_title(url: str) -> str:
    request = urllib.request.Request(url, headers=headers)
    web = BeautifulSoup(urllib.request.urlopen(request), features="html.parser")
    return web.title.string


def is_valid_url(url: str) -> bool:
    result = urllib.parse.urlparse(url)
    return all([result.scheme, result.netloc])


def insert(bookmarks):
    total_bookmark = len(bookmarks.get("-"))
    insert_count = 0
    for bookmark in bookmarks.get("-"):
        url = bookmark.get("url")
        if not url:
            console.print("[red bold]url not added")
            sys.exit()
        if not is_valid_url(url):
            console.print("[red bol]url not valid")
            sys.exit()
        try:
            db.insert(
                [
                    {
                        "url": url,
                        "title": bookmark.get("title")
                        or deduce_title(bookmark.get("url"))
                        or "---",
                        "description": bookmark.get("description"),
                        "tags": bookmark.get("tags"),
                        "added_date": bookmark.get("added_date")
                        or datetime.datetime.now().strftime(date_format),
                    }
                ]
            )
            insert_count += 1
        except DuplicateEntryError as err:
            console.print("[red]Duplicate url found - {}".format(url))
    console.print(
        "[green bold]{}/{} {} added".format(
            insert_count,
            total_bookmark,
            "bookmark" if total_bookmark == 1 else "bookmarks",
        )
    )


def get_bookmarks_sorted():
    all_bookmarks = db.find(lambda x: True)
    ordered_latest = sorted(
        all_bookmarks,
        key=lambda i: datetime.datetime.strptime(i["added_date"], date_format),
        reverse=True,
    )
    return ordered_latest


def fuzzy_search(options):
    options = "\n".join(options)
    selected = subprocess.Popen(
        fuzzy_search_command.substitute(options=options),
        shell=True,
        stdout=subprocess.PIPE,
    ).communicate()[0]
    selected = selected.decode("utf-8")
    return list(filter(None, selected.split("\n")))


def distinct_tags():
    tags = set()
    notes = db.find(lambda x: True)
    for note in notes:
        tags.update(note.get("tags"))
    return list(tags)


def distinct_titles():
    notes = db.find(lambda x: True)
    return [note.get("title") for note in notes]


@app.command()
def new():
    filename, status = open_temp_toml_file()
    total_bookmarks = 0
    if status == 0:
        with open(filename, "r") as file:
            bookmarks = toml.load(file)
            insert(bookmarks)


@app.command()
def preview(title: str):
    bookmark = db.find(lambda x: x.get("title") == title)
    if bookmark:
        console.print(format_text(bookmark[0]))


@app.command()
def tag():
    tags = fuzzy_search(distinct_tags())
    bookmarks = db.find(lambda x: set(tags).issubset(set(x.get("tags"))))
    display_bookmark(bookmarks)


@app.command()
def tags():
    content = []
    for tag in distinct_tags():
        total = len(db.find(lambda x: tag in x.get("tags")))
        content.append(
            "[black on blue] {} [/][black on grey93] {} [/]\t".format(tag, total)
        )
    console.print(Columns(content, expand=True, equal=True))


@app.command()
def find(searchstr: str):
    searchstr = searchstr.strip()
    bookmarks = db.find(
        lambda x: searchstr in x.get("title") or searchstr in x.get("url")
    )
    display_bookmark(bookmarks)


@app.command()
def ls(order: str = typer.Argument("recent"), val: int = typer.Argument(10)):
    if order not in ["recent", "past"]:
        raise Exception('order has to be either "recent" or "past"')

    bookmarks = get_bookmarks_sorted()
    if order == "recent":
        display_bookmark(bookmarks[:val])
    else:
        display_bookmark(bookmarks[-val:])


@app.command()
def edit():
    title = fuzzy_search(distinct_titles())

    def update(document):
        if document:
            filename, status = open_temp_toml_file(
                {
                    "url": document.get("url"),
                    "title": document.get("title"),
                    "tags": document.get("tags"),
                    "description": document.get("description"),
                }
            )
            if status == 0:
                with open(filename, "r") as file:
                    updated_bookmark = toml.load(file)
                    document.update(updated_bookmark)
                    return document

    db.update(update, lambda x: x.get("title") == title)


@app.command()
def rm():
    title = fuzzy_search(distinct_titles())
    doc = db.delete(lambda x: x.get("title") == title)
    return doc


@app.command("import")
def import_viv():
    """import from vivaldi bookmarks"""
    home = str(pathlib.Path.home())
    fullpath = home + "/.config/vivaldi/Default/Bookmarks"
    bookmarks = {"-": list()}
    with open(fullpath) as browserbm:
        jsondict = json.loads(browserbm.read())
        blist = jsondict["roots"]["bookmark_bar"]["children"]
        for element in blist:
            print(element.get("name"))
            bookmarks["-"].append(
                {
                    "url": element.get("url"),
                    "title": element.get("name"),
                    "tags": ["browser"],
                    "description": "",
                    "added_date": format_date(int(element.get("date_added"))),
                }
            )
        insert(bookmarks)


def init_db():
    dbroot = pathlib.Path.home() / ".local/urlr"
    dbroot.mkdir(parents=True, exist_ok=True)
    collection_name = "urlr"
    db = jsondb(str(pathlib.Path(dbroot / "urlr.json")))
    db.set_index("url")
    db.set_index("title")
    return db


db = init_db()
if __name__ == "__main__":
    app()
