from logging import Logger

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

from labeler.types import LabelNode, GMailLabel


def populate_label_tree(
    service: Resource,
    label_tree: dict[str, LabelNode],
    labels_dict: dict[str, GMailLabel],
    logger: Logger,
    prefix="",
):
    for name, label_node in label_tree.items():
        full_name = f"{prefix}/{name}".strip("/")

        logger.debug("Processing label: %s", full_name)

        label = labels_dict.get(full_name)

        if label:
            logger.debug("Label exists: %s (id=%s)", full_name, label["id"])
            label_node["id"] = label["id"]
        else:
            logger.info("Creating label: %s", full_name)
            try:
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
            except Exception:
                logger.exception("Failed to create label: %s", full_name)
                raise

            label_node["id"] = created_label["id"]
            labels_dict[full_name] = created_label

            logger.info("Created label: %s (id=%s)", full_name, created_label["id"])

        populate_label_tree(
            service,
            label_node["children"],
            labels_dict,
            logger,
            prefix=full_name,
        )


def flatten_tree(label_tree: dict[str, LabelNode], logger: Logger, prefix=""):
    tree: dict[str, LabelNode] = {}

    for name, label_node in label_tree.items():
        full_name = f"{prefix}/{name}".strip("/")
        tree[full_name] = label_node

        logger.debug("Flattened label: %s -> %s", full_name, label_node["id"])

        flattened_child = flatten_tree(label_node["children"], logger, prefix=full_name)
        tree.update(flattened_child)

    return tree


def ensure_labels(creds: Credentials, logger: Logger) -> dict[str, LabelNode]:
    logger.info("Ensuring Gmail labels exist")

    service = build("gmail", "v1", credentials=creds)

    try:
        results = service.users().labels().list(userId="me").execute()
    except Exception:
        logger.exception("Failed to fetch existing labels")
        raise

    labels: list[GMailLabel] = results.get("labels", [])
    logger.info("Fetched %d existing labels", len(labels))

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

    populate_label_tree(service, label_tree, labels_dict, logger, "")
    flat = flatten_tree(label_tree, logger)

    logger.info("Label tree ready (%d labels)", len(flat))

    return flat
