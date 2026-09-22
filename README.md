# Approval Reviewer

Review an assistant's proposed emails and save your decisions as data for fine-tuning a separate review model.

[Interactive demo](https://habibdebaya.github.io/agent-reviewer/) · [Source code](https://github.com/habibdebaya/agent-reviewer)

## How it works

1. Open a prepared email and compare it with the owner's request, source notes, and allowed recipients.
2. Approve it, reject it with a reason, or ask for more information.
3. Inspect and download the saved input and answer from **Fine-tuning data**.

Approve only when the recipient is allowed, the draft does the requested job, its claims match the notes, and it contains no protected information. Asking for more information keeps the draft pending without creating a completed training answer.

Start with **Catch a wrong detail**, reject the false claim, then review the correction. Approved drafts enter a simulated outbox. No real email is sent.

## Run locally

Requires Python 3.12 or newer.

```bash
git clone https://github.com/habibdebaya/agent-reviewer.git
cd agent-reviewer
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m app seed
.venv/bin/python -m app serve
```

Open [the local app](http://127.0.0.1:8000). Prepared examples work without an API key.

For live drafts, copy `.env.example` to `.env`, add `OPENROUTER_API_KEY`, and restart. The example configuration selects **Luna** through OpenRouter using `OPENROUTER_MODEL=openai/gpt-5.6-luna`. Live requests send your request and the workspace notes the model reads through OpenRouter. Prepared examples make no model calls.

Reviews and downloads prepare data. Fine-tuning happens later. The optional local training experiment uses a simple classifier, not Luna.

## Interactive demo

The `docs` folder contains a self-contained interactive demo for reviewing sample drafts, recording decisions, and exporting training data. Decisions are stored in the visitor's browser. Live model calls and local reviewer training require the Python application.

Preview it locally.

```bash
python3 -m http.server 8002 --bind 127.0.0.1 --directory docs
```

Open [the local preview](http://127.0.0.1:8002).

For deployment, select `main` and `/docs` as the publishing source in the [repository's Pages settings](https://github.com/habibdebaya/agent-reviewer/settings/pages).
