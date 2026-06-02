import os.path
from configparser import ConfigParser
from typing import Optional, TypedDict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

from utils.config import load_config

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

    return label_tree


def main():
    config = load_config()
    creds = load_creds(config)
    if not creds:
        return
    label_tree = ensure_labels(creds)


if __name__ == "__main__":
    main()
