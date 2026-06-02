from classifier.types import EmailObject


def system_prompt() -> str:
    return """
You are an email classification system.

Classify the given email into exactly one of the following categories:

* `Job Application`
* `Job Rejection`
* `Job Interview`
* `Job Advertisement`
* `None`

Definitions:

* Job Application: Confirmation or submission of an application.
* Job Rejection: Explicit decline or unsuccessful outcome.
* Job Interview: Invitation, scheduling, or discussion of an interview.
* Job Advertisement: Job offers, recruiting emails, or open positions.
* None: Not related to jobs.

Rules:

* Output only the category name.
* Do not explain your answer.
* If uncertain, choose the closest match.
    """.strip()


def user_prompt(email: EmailObject) -> str:
    return f"""
From: {email['sender']}
Subject: {email['subject']}

{email['body']}
"""
