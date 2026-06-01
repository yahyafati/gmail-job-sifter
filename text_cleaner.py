import logging
from logging import Logger

import regex as re


class TextCleaner:
    URL_PATTERN = re.compile(r"""(?xi)
        \b
        (?:https?://|www\.)
        [^\s<>]+
    """)

    MULTI_NEWLINES = re.compile(r"\n{3,}")

    SEPARATOR_LINE = re.compile(r"(?m)^[\s\p{P}\p{S}]{5,}\s*$")

    ALLOWED_CHARS = re.compile(r"[^\p{Latin}\p{N}\p{P}\p{Z}\n]")

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

    # ---------------- public API ----------------

    def clean_text(self, text: str, max_iters: int = 10) -> str:
        self.logger.info(
            "Starting cleaning | initial_len=%d | max_iters=%d", len(text), max_iters
        )

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

        self.logger.info("Finished cleaning | final_len=%d", len(curr))
        return curr


if __name__ == "__main__":
    SAMPLE = """
Top job picks for you:     https://www.linkedin.com/comm/jobs/collections/recommended?origin=JYMBII_EMAIL&lgCta=eml-jymbii-bottom-see-all-jobs&lgTemp=jobs_jymbii_digest&lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-null-0-null&trkEmail=eml-jobs_jymbii_digest-null-0-null-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D
  
            
Full Stack Developer - Java & React (f/m/d)
ecosio
Munich

This company is actively hiring
View job: https://www.linkedin.com/comm/jobs/view/4385312888/?trackingId=ZHUmFP1%2FTVKZRtZRxOkDrQ%3D%3D&refId=H4z3acSeTJa65jD4EvyFfg%3D%3D&lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-jymbii-0-view_job&trkEmail=eml-jobs_jymbii_digest-jymbii-0-view_job-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D

---------------------------------------------------------
  
            
Full Stack / Front End Engineer (Freelance)
MVP Match
Berlin Metropolitan Area

This company is actively hiring
Apply with resume & profile
View job: https://www.linkedin.com/comm/jobs/view/4384248594/?trackingId=C60YNZp5SSOoifyp7yWubQ%3D%3D&refId=z83D%2F%2BVwTuuve4Hf8gUyNQ%3D%3D&lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-jymbii-0-view_job&trkEmail=eml-jobs_jymbii_digest-jymbii-0-view_job-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D

---------------------------------------------------------
  
            
Software Engineer, Front-End
Superhuman
Berlin

High experience match
View job: https://www.linkedin.com/comm/jobs/view/4384635364/?trackingId=um4mXi%2FGQZKtdboLGvfpxA%3D%3D&refId=zyAYCyUXSyiJXdVBE%2B%2BDYA%3D%3D&lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-jymbii-0-view_job&trkEmail=eml-jobs_jymbii_digest-jymbii-0-view_job-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D

---------------------------------------------------------
  
            
Frontend Engineer (all genders)
Avelios Medical
Munich

2 school alumni
View job: https://www.linkedin.com/comm/jobs/view/4361502751/?trackingId=MV659Nk5TxuiVuAB6%2BBSWQ%3D%3D&refId=NxtxtizOShOS7tiS4YxO%2Bw%3D%3D&lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-jymbii-0-view_job&trkEmail=eml-jobs_jymbii_digest-jymbii-0-view_job-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D

---------------------------------------------------------
  
            
Web-Frontend-Developer:innen (w/m/d)
Instaffo
90429

This company is actively hiring
View job: https://www.linkedin.com/comm/jobs/view/4344413547/?trackingId=xZL4s0cZTI%2Bi9x2vZ3AYMA%3D%3D&refId=AvPctVvRQgyUAQShZ6flWw%3D%3D&lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-jymbii-0-view_job&trkEmail=eml-jobs_jymbii_digest-jymbii-0-view_job-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D

---------------------------------------------------------
  
            
Software Engineer (Python/React)
AMBOSS
Berlin

This company is actively hiring
View job: https://www.linkedin.com/comm/jobs/view/4348073626/?trackingId=v2yJ2RBhTrKLkyXWhfykWw%3D%3D&refId=jETddmoyRnOLQdewO8R1uw%3D%3D&lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-jymbii-0-view_job&trkEmail=eml-jobs_jymbii_digest-jymbii-0-view_job-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D

---------------------------------------------------------
  
See all jobs https://www.linkedin.com/comm/jobs/collections/recommended?origin=JYMBII_EMAIL&lgCta=eml-jymbii-bottom-see-all-jobs&lgTemp=jobs_jymbii_digest&lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-null-0-null&trkEmail=eml-jobs_jymbii_digest-null-0-null-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D

Land your next role with Premium
See jobs where you’re more likely to hear back.
http://www.linkedin.com/comm/premium/products/?upsellOrderOrigin=Tracking%3Av1%3Aemail_jymbii_upsell%3AEmail+Stork%3AMarketing&utype=job&referenceId=ajJB2s%2B%2BQSWdqarYJaMO1w%3D%3D&isSS=false&lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-jymbii-0-premium~upsell~v2~text&trkEmail=eml-jobs_jymbii_digest-jymbii-0-premium~upsell~v2~text-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D
  


----------------------------------------

This email was intended for Yahya Haji (Full-stack Developer)
Learn why we included this: https://www.linkedin.com/help/linkedin/answer/4788?lang=en&lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-SecurityHelp-0-textfooterglimmer&trkEmail=eml-jobs_jymbii_digest-SecurityHelp-0-textfooterglimmer-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D
You are receiving Jobs You Might Be Interested In emails.

         https://www.linkedin.com/comm/jobs/alerts?lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-null-0-null&trkEmail=eml-jobs_jymbii_digest-null-0-null-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D 
Unsubscribe: https://www.linkedin.com/comm/psettings/email-unsubscribe?lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-unsubscribe-0-textfooterglimmer&trkEmail=eml-jobs_jymbii_digest-unsubscribe-0-textfooterglimmer-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&loid=AQE5dP8WwDBuJgAAAZ0qOalMlO86GZkE-W802RTBO9Gln68cGP8ZEGULPbUev0IkAYAH39QJNLlkaRGIRJQ4YA2-Y9PgCxdhNfI42g
Help: https://www.linkedin.com/help/linkedin/answer/67?lang=en&lipi=urn%3Ali%3Apage%3Aemail_jobs_jymbii_digest%3BSdvcyj1EQiG4bGAF5nzBZQ%3D%3D&midToken=AQEAZB3EUSKipA&midSig=0WsEYoR_5aisc1&trk=eml-jobs_jymbii_digest-help-0-textfooterglimmer&trkEmail=eml-jobs_jymbii_digest-help-0-textfooterglimmer-null-e32yz0~mn7ha5yo~u7-null-null&eid=e32yz0-mn7ha5yo-u7&otpToken=MWEwMDFmZTcxMjJkYzBjMGJjMjQwNGVkNDExYWUyYjY4NmM3ZDE0NDliYWQ4YjYxNzZjZTAxNmU0ZTUyNWNmM2YzZGRkZmEzNDhjOGUwY2I2NDg1Yzk3ZDg4MjI0Njg3OWM3N2Q4ZGQyMzBiMjQ5NWRlMjE0NywxLDE%3D

© 2026 LinkedIn Corporation, 1zwnj000 West Maude Avenue, Sunnyvale, CA 94085.
LinkedIn and the LinkedIn logo are registered trademarks of LinkedIn.
    """

    cleaner = TextCleaner()
    cleaned = cleaner.clean_text(SAMPLE)
    print(cleaned)
