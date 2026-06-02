import sys
from datetime import datetime
from typing import (
    List,
)

from classifier.db import get_row_count, generate_dataset, update_classification
from classifier.text_cleaner import TextCleaner
from classifier.types import ClassifiedEmail
from classifier.utils import (
    classify_email,
    NONE_CONTENT_FLAG,
    save_to_json,
    get_ranked_llms,
    create_clients,
)
from utils.config import set_runtime_value, init_mode, load_config
from utils.db import create_connection, close_connections
from utils.log import add_file_handler, create_logger
from utils.misc import sleep_stochastically

logger = create_logger(None, __name__)


def main():
    logger.info("=== Email Classifier Starting ===")

    config = load_config()

    current_mode = init_mode(config)

    text_cleaner = TextCleaner(logger)

    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    set_runtime_value(config, "run_id", run_id)
    add_file_handler(config, logger, "classifier.log")

    con, read_cursor, write_cursor = create_connection(config)
    logger.debug("Database cursor created")

    ranked_llms = get_ranked_llms(config)
    if len(ranked_llms) == 0:
        logger.fatal("At least one LLM definition needed.")
        sys.exit(32)
    ranked_clients = create_clients(ranked_llms, logger)
    logger.debug(f"{len(ranked_clients)} OpenAI clients initialized.")

    total_number_of_emails = get_row_count(config, read_cursor, logger)
    logger.info(f"Total Number of Emails: {total_number_of_emails}")

    if total_number_of_emails == 0:
        logger.warning("No emails found to classify; exiting early")
        return

    temp_data: List[ClassifiedEmail] = []
    classification_counts: dict[str, int] = {}
    none_content_count = 0

    logger.info("Starting classification loop for %d emails", total_number_of_emails)
    for i, email in enumerate(generate_dataset(config, read_cursor, logger)):
        human_index = i + 1
        logger.debug(
            "Processing email %d/%d (message_id='%s')",
            human_index,
            total_number_of_emails,
            email["message_id"],
        )

        classification = classify_email(
            ranked_clients, text_cleaner, ranked_llms, email, logger
        )

        if classification == NONE_CONTENT_FLAG:
            none_content_count += 1
            logger.warning(
                "Email %d/%d (message_id='%s') received a None classification from LLM",
                human_index,
                total_number_of_emails,
                email["message_id"],
            )

        if classification is not None:
            classification_counts[classification] = (
                classification_counts.get(classification, 0) + 1
            )

            update_classification(
                write_cursor,
                message_id=email["message_id"],
                classification=classification,
                logger=logger,
            )
            temp_data.append(ClassifiedEmail(classification=classification, **email))
        else:
            logger.warning(
                "Could not classify using any of the LLMs provided. Skipping!"
            )

        if human_index % 100 == 0 or human_index == total_number_of_emails:
            logger.info(
                "Progress: %d/%d emails classified",
                human_index,
                total_number_of_emails,
            )
        sleep_stochastically()

    logger.info("Classification complete. Summary:")
    for label, count in sorted(classification_counts.items()):
        logger.info("  %-25s %d", label, count)
    if none_content_count:
        logger.warning("  Emails with None LLM response: %d", none_content_count)

    logger.debug("Post-classification mode check: mode='%s'", current_mode)
    if current_mode == "dev":
        logger.info("Dev mode active — saving results to JSON")
        save_to_json(config, temp_data, logger)
    else:
        logger.info("Prod mode active — skipping JSON export")

    logger.info("=== Email Classifier Finished ===")


if __name__ == "__main__":
    try:
        logger.debug("Entry point reached")
        main()
    except KeyboardInterrupt:
        logger.fatal("User interrupted; aborting.")
    except Exception:
        logger.exception("Unhandled exception in main(); aborting")
        raise
    finally:
        logger.debug("Running cleanup for any closeable resource(s)")
        close_connections()
        logger.info("Cleanup complete")
