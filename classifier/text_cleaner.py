import logging
from logging import Logger

import regex as re
from bs4 import BeautifulSoup


class TextCleaner:
    URL_PATTERN = re.compile(r"""(?xi)
        \b
        (?:https?://|www\.)
        [^\s<>]+
    """)

    MULTI_NEWLINES = re.compile(r"\n{3,}")

    SEPARATOR_LINE = re.compile(r"(?m)^[\s\p{P}\p{S}]{5,}\s*$")

    ALLOWED_CHARS = re.compile(r"[^\p{Latin}\p{N}\p{P}\p{Z}\n]")

    UUID_PATTERN = re.compile(
        r"\b[0-9a-fA-F]{8}-"
        r"[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}\b"
    )

    def __init__(self, logger: Logger | None = None):
        self.logger = logger or self._build_default_logger()

    @staticmethod
    def _build_default_logger() -> Logger:
        logger = logging.getLogger("TextCleaner")

        if not logger.handlers:
            handler = logging.StreamHandler()

            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

        return logger

    # ---------------- internal helpers ----------------

    def _log_diff(self, stage: str, before: str, after: str):
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                "%s | len: %d -> %d | delta: %d",
                stage,
                len(before),
                len(after),
                len(after) - len(before),
            )

    @staticmethod
    def _trim_lines(text: str) -> str:
        return "\n".join(line.strip() for line in text.splitlines())

    def _clean_once(self, text: str) -> str:
        original = text

        text = self._trim_lines(text)

        # URLs
        text = self.URL_PATTERN.sub("[link]", text)
        self._log_diff("URL_REPLACE", original, text)
        original = text

        # Separator lines
        text = TextCleaner.SEPARATOR_LINE.sub("", text)
        self._log_diff("SEPARATOR_REMOVE", original, text)
        original = text

        # Disallowed chars
        text = TextCleaner.ALLOWED_CHARS.sub("", text)
        self._log_diff("CHAR_FILTER", original, text)
        original = text

        # Newlines normalization
        text = TextCleaner.MULTI_NEWLINES.sub("\n\n", text)
        self._log_diff("NEWLINE_NORMALIZE", original, text)
        original = text

        # Trailing whitespace cleanup
        text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
        self._log_diff("TRAILING_WS", original, text)

        return text.strip()

    @staticmethod
    def _strip_html(text: str) -> str:
        soup = BeautifulSoup(text, "html.parser")
        return soup.get_text(separator=" ", strip=True)

    @staticmethod
    def replace_uuid(text: str) -> str:
        return TextCleaner.UUID_PATTERN.sub("[UUID]", text)

    # ---------------- public API ----------------

    def clean_text(self, text: str, max_iters: int = 10) -> str:
        start_length = len(text)
        self.logger.debug(
            "Starting cleaning | initial_len=%d | max_iters=%d", start_length, max_iters
        )

        text = self._strip_html(text)
        text = self.replace_uuid(text)

        prev = None
        curr = text

        for i in range(max_iters):
            before_iter = curr
            curr = self._clean_once(curr)

            self.logger.debug(
                "Iteration %d | len: %d -> %d",
                i + 1,
                len(before_iter),
                len(curr),
            )

            if curr == prev:
                self.logger.info("Stabilized after %d iterations", i + 1)
                break

            prev = curr
        end_length = len(curr)
        self.logger.debug("Finished cleaning | final_len=%d", end_length)
        self.logger.info(f"Cleaned text from {start_length} to {end_length}")
        return curr


if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="Clean text using TextCleaner")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", "-t", type=str, help="Raw input text")
    group.add_argument("--file", "-f", type=str, help="Path to input text file")

    args = parser.parse_args()

    sample = None
    if args.text is not None:
        sample = args.text
    else:
        with open(args.file, "r", encoding="utf-8") as f:
            sample = f.read()
    if not sample:
        sys.exit(-1)
    cleaner = TextCleaner()
    cleaned = cleaner.clean_text(sample)

    print(cleaned)
