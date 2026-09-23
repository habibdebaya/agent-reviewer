# Agent Action Review

Human review for agent actions that automated checks can't settle. Each decision is captured with the evidence behind it and the reason given, as training data for a decision model.

[Open the site](https://habibdebaya.github.io/agent-reviewer/)

## Why

In practice, most actions an agent takes get settled by automated checks, meaning deterministic rules plus a trained model. Only the ones the checks can't settle with confidence reach a human. Those human decisions become the corpus that trains each customer's own decision model, and as that model improves, fewer cases need a human.

In a gateway setup, this step sits right after approval and captures the decision with its evidence and reason.

Small organizations won't accumulate enough reviews to train on, so fine-tuning would likely need synthetic data on top. Getting that generation right is its own engineering problem, and it is out of scope here.

## What this demo covers

Only the human review step and the data it produces. The automated checks and the model training are not included.

**Review cases.** Five emails an agent proposes to send. Each case shows the intended recipient, the data available to the agent with the one item it may share, and the proposed email. The reviewer approves it, or rejects it and says why (unapproved data or an unapproved recipient). There is no answer key. The reviewer's decision is the label.

**Export training data.** Every decided case becomes one line of a JSONL file, in the chat format that fine-tuning services accept.

- The system message is the review rule.
- The user message is the evidence the reviewer saw.
- The assistant message is the decision and reason.

Everything runs in the browser. Decisions are saved in local storage and never leave the machine. There are no API keys, no server and no model calls.

## Run locally

```bash
python3 -m http.server 8000 --directory docs
```

Then open http://localhost:8000.

## Files

- `docs/cases.js` holds the five cases
- `docs/app.js` renders the pages and builds the export
- `docs/style.css` is the stylesheet

To publish, select `main` and `/docs` as the source in the repository's Pages settings.
