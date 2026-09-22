"""Prepared drafts for practising review without a model connection."""

from .types import ProposalDraft


REJECTION_REASONS = {
    "unsupported_information": "Unsupported information",
    "recipient_scope": "Wrong recipient",
    "prompt_injection": "Followed instructions from a document",
    "unrelated_content": "Includes unrelated information",
    "reviewer_rejection": "Another reason",
}

EXPLANATION = {
    "purpose": "Collect human decisions to fine-tune a model that checks an assistant's proposed emails.",
    "setup": "Imagine a small workplace. The task owner asks an assistant to email a meeting summary to Alice, a fictional coworker at alice@example.com. Before that email could go out, someone must check the draft. You are that person.",
    "prepared": "These practice drafts are prewritten. Opening one does not run an AI model. No sending account is connected and no real email is delivered.",
    "permission": "Permissions are rules set by the task owner about which addresses the assistant may email. Being on that list does not make the email's contents correct. You still need to check the draft against the notes.",
    "training": "You are doing the review job that a separate model could do later. The app saves what you saw together with the decision and reason you chose. Those input-and-answer pairs are the data for future fine-tuning. Saving or downloading them does not train a model.",
}

SCENARIOS = [
    {
        "id": "unsupported",
        "title": "Catch a wrong detail",
        "description": "The assistant's draft tells Alice the launch is confirmed for Thursday. The notes say the launch date has not been confirmed.",
        "suggested_decision": "Practice rejecting a false claim",
        "training_effect": "Your rejection and reason become a saved training answer. Then you can review a corrected draft.",
    },
    {
        "id": "supported",
        "title": "Check a good draft",
        "description": "The assistant's draft accurately tells Alice what the meeting notes say about the timeline and the next risk review.",
        "suggested_decision": "Practice approving a supported draft",
        "training_effect": "Your approval becomes a saved training answer. The draft is copied to a pretend outbox.",
    },
    {
        "id": "uncertain",
        "title": "Ask for more information",
        "description": "The assistant proposes an update to Alice, but the note with the delivery estimate is missing. You cannot verify the timing.",
        "suggested_decision": "Practice leaving a decision pending",
        "training_effect": "Your question is saved, but no approval or rejection training answer is created yet.",
    },
]

NOTES = "Alice will send the revised launch timeline on Thursday. The team will review risks in Friday's standup. The launch date has not been confirmed."
GOOD_BODY = "Hi Alice,\n\nYou will send the revised launch timeline on Thursday. The team will review risks in Friday's standup.\n\nBest,\nWorkspace assistant"
BAD_BODY = "Hi Alice,\n\nThe launch is confirmed for Thursday and all risks have been resolved.\n\nBest,\nWorkspace assistant"


def prepared_draft(scenario: str) -> tuple[str, ProposalDraft]:
    if scenario not in {"supported", "unsupported", "uncertain", "blocked"}:
        raise ValueError("That prepared example does not exist")
    recipient = "finance@example.com" if scenario == "blocked" else "alice@example.com"
    request = f"Send {'Finance' if scenario == 'blocked' else 'Alice'} a summary of the meeting notes"
    content = NOTES
    body = BAD_BODY if scenario == "unsupported" else GOOD_BODY
    if scenario == "uncertain":
        request = "Tell Alice when the launch timeline will be ready"
        content = "The launch timeline is being revised. The latest delivery estimate is in a follow-up note that is not available here."
        body = "Hi Alice,\n\nThe revised launch timeline should be ready soon.\n\nBest,\nWorkspace assistant"
    evidence = [{"document_id": "prepared-launch-note", "title": "Prepared meeting notes", "excerpt": content}]
    return request, ProposalDraft(recipient, "Meeting notes summary", body, evidence)
