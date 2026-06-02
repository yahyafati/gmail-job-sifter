import os.path
import sqlite3
from configparser import ConfigParser
from typing import Optional, TypedDict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

from utils.config import load_config
from utils.db import create_connection, close_connections

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def load_creds(config: ConfigParser) -> Credentials | None:
    token_path = config["labeler"].get("token_path", "token.json")
    credentials_path = config["labeler"].get("credentials_path", "credentials.json")
    creds: Optional[Credentials] = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        if creds:
            with open(token_path, "w") as token:
                token.write(creds.to_json())
    return creds


class LabelNode(TypedDict):
    id: Optional[str]
    children: dict[str, "LabelNode"]


class GMailLabel(TypedDict):
    id: str
    name: str


def populate_label_tree(
    service: Resource,
    label_tree: dict[str, LabelNode],
    labels_dict: dict[str, GMailLabel],
    prefix="",
):
    for name, label_node in label_tree.items():
        full_name = f"{prefix}/{name}".strip("/")
        label = labels_dict.get(full_name, None)
        if label:
            label_node["id"] = label["id"]
        else:
            created_label: GMailLabel = (
                service.users()
                .labels()
                .create(
                    userId="me",
                    body={
                        "name": full_name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
                .execute()
            )
            label_node["id"] = created_label["id"]
            labels_dict["full_name"] = created_label
        populate_label_tree(
            service,
            label_node["children"],
            labels_dict,
            prefix=full_name,
        )


def flatten_tree(label_tree: dict[str, LabelNode], prefix=""):
    tree: dict[str, LabelNode] = {}
    for name, label_node in label_tree.items():
        full_name = f"{prefix}/{name}".strip("/")
        tree[full_name] = label_node

        flattened_child = flatten_tree(label_node["children"], prefix=full_name)
        tree.update(flattened_child)
    return tree


def ensure_labels(
    creds: Credentials,
) -> dict[str, LabelNode]:
    service = build("gmail", "v1", credentials=creds)
    results = service.users().labels().list(userId="me").execute()
    labels: list[GMailLabel] = results.get("labels", [])
    labels_dict = {label["name"]: label for label in labels}

    label_tree: dict[str, LabelNode] = {
        "Job": LabelNode(
            id=None,
            children={
                "Application": LabelNode(id=None, children={}),
                "Interview": LabelNode(id=None, children={}),
                "Rejection": LabelNode(id=None, children={}),
                "Advertisement": LabelNode(id=None, children={}),
            },
        )
    }

    populate_label_tree(service, label_tree, labels_dict, "")
    return flatten_tree(label_tree)


def generate_data(cur: sqlite3.Cursor, chunk_size=64):
    query = "SELECT message_id,category FROM emails where category IS NOT NULL AND category != 'None'"

    try:
        res = cur.execute(query)
    except sqlite3.Error as e:
        raise

    while True:
        rows = res.fetchmany(chunk_size)
        if not rows:
            break
        grouped_messages: dict[str, list[str]] = {}
        for message_id, category in rows:
            category = category.replace(" ", "/")
            if category not in grouped_messages:
                grouped_messages[category] = []
            grouped_messages[category].append(message_id)
        yield grouped_messages


def main():
    config = load_config()
    con, read_cur, write_cur = create_connection(config)
    creds = load_creds(config)
    if not creds:
        return
    label_tree = ensure_labels(creds)
    service = build("gmail", "v1", credentials=creds)

    for batch in generate_data(read_cur):
        for label, ids in batch.items():
            results = (
                service.users()
                .messages()
                .batchModify(
                    userId="me",
                    body={"ids": ids, "addLabelIds": [label_tree[label]["id"]]},
                )
                .execute()
            )


if __name__ == "__main__":
    try:
        main()
    finally:
        close_connections()
