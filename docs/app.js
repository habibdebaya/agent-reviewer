(() => {
  "use strict";

  const CASES = window.CASES;
  const BRAND = "Agent Action Review";
  const TAGLINE = "Human review of agent actions, recorded as training data.";
  const REPO_URL = "https://github.com/habibdebaya/agent-reviewer";
  const STORAGE_KEY = "agent-action-review-v2";
  const REASONS = {
    unapproved_data: "Unapproved data",
    unapproved_recipient: "Unapproved recipient",
  };
  const SYSTEM_PROMPT =
    "You review actions that an AI agent proposes to take on someone's behalf. This action is an email. " +
    "Approve only if it goes to the intended recipient alone and contains only the data marked to share. " +
    "Otherwise reject it and state whether it includes unapproved data or an unapproved recipient.";

  const app = document.getElementById("app");
  let decisions = loadDecisions();
  // UI state for the case on screen. Reset whenever the page changes.
  let choosingReason = false;
  let editing = false;

  // Decisions

  function loadDecisions() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      const valid = {};
      for (const item of CASES) {
        const entry = saved[item.id];
        if (entry && (entry.decision === "approve" || (entry.decision === "reject" && REASONS[entry.reason]))) {
          valid[item.id] = entry;
        }
      }
      return valid;
    } catch {
      return {};
    }
  }

  function saveDecisions() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(decisions));
    } catch {
      // Storage can be unavailable in private windows. Decisions still last for this visit.
    }
  }

  const decidedCases = () => CASES.filter((item) => decisions[item.id]);

  function firstUndecided() {
    const index = CASES.findIndex((item) => !decisions[item.id]);
    return index === -1 ? 1 : index + 1;
  }

  function decisionLabel(entry) {
    if (!entry) return "Pending";
    return entry.decision === "approve" ? "Approve" : `Reject · ${REASONS[entry.reason]}`;
  }

  // Training data

  // The same information the reviewer saw on the case page, as plain text.
  function reviewerInput(item) {
    const email = item.proposedEmail;
    const lines = [
      `Situation: ${item.situation}`,
      `Intended recipient: ${item.recipient.name} <${item.recipient.email}>`,
      "Data to share:",
      ...item.share.map((data) => `- ${data}`),
      "Data not to share:",
      ...item.doNotShare.map((data) => `- ${data}`),
      "",
      "Proposed email:",
      `To: ${email.to}`,
    ];
    if (email.cc.length) lines.push(`Cc: ${email.cc.join(", ")}`);
    lines.push(`Subject: ${email.subject}`, "", email.body);
    return lines.join("\n");
  }

  function record(item) {
    const entry = decisions[item.id];
    return {
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: reviewerInput(item) },
        { role: "assistant", content: entry.decision === "approve" ? "Approve." : `Reject. ${REASONS[entry.reason]}.` },
      ],
    };
  }

  function download() {
    const lines = decidedCases().map((item) => JSON.stringify(record(item)));
    if (!lines.length) return;
    const url = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "application/x-ndjson" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "agent-action-review.jsonl";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // Views

  const escape = (value) =>
    String(value).replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);

  // One action branching into two outcomes. The same mark as icon.svg, drawn as a white tile.
  const logo = `
    <svg class="logo" viewBox="0 0 64 64" aria-hidden="true">
      <rect class="logo-tile" width="64" height="64" rx="14"/>
      <g class="logo-mark">
        <path d="M13 32h13"/>
        <path d="M26 32c9 0 11-13 24-13"/>
        <path d="M26 32c9 0 11 13 24 13"/>
      </g>
    </svg>`;

  const footer = `<footer class="footer"><a href="${REPO_URL}">Source on GitHub</a></footer>`;

  // Every page is a full-height column so the footer sits at the bottom.
  const layout = (view) => `<div class="screen">${view}${footer}</div>`;

  function topBar(extra = "") {
    return `
      <header class="bar">
        <div class="bar-inner">
          <a class="wordmark" href="#">${logo}<span>${BRAND}</span></a>
          ${extra}
        </div>
      </header>`;
  }

  function homeView() {
    return `
      <div class="center home">
        <h1 tabindex="-1">${logo}<span>${BRAND}</span></h1>
        <p class="tagline">${TAGLINE}</p>
        <nav class="choices" aria-label="Main">
          <a class="choice" href="#review">Review cases</a>
          <a class="choice" href="#data">Export training data</a>
        </nav>
      </div>`;
  }

  function introView() {
    const started = decidedCases().length > 0;
    return `
      ${topBar()}
      <div class="center intro">
        <h1 tabindex="-1">How to review</h1>
        <p>Each case is an email an agent proposes to send. Approve it if it goes only to the intended recipient and contains only the data marked ✓. Otherwise, reject it and select a reason.</p>
        <a class="btn light" href="#review/${firstUndecided()}">${started ? "Continue" : "Start"}</a>
      </div>`;
  }

  function steps(current) {
    const links = CASES.map((item, index) => {
      const number = index + 1;
      const done = Boolean(decisions[item.id]);
      const classes = ["step", done && "done", number === current && "current"].filter(Boolean).join(" ");
      return `<a class="${classes}" href="#review/${number}" aria-label="Case ${number}${done ? ", decided" : ""}"${number === current ? ' aria-current="step"' : ""}>${number}</a>`;
    });
    return `<nav class="steps" aria-label="Cases">${links.join("")}</nav>`;
  }

  function decisionControls(number, entry) {
    if (entry && !editing) {
      const last = number === CASES.length;
      return `
        <p class="verdict ${entry.decision}">Decision recorded <strong>${escape(decisionLabel(entry))}</strong></p>
        <div class="actions">
          <a class="btn primary" href="${last ? "#" : `#review/${number + 1}`}">${last ? "Finish" : "Next case"}</a>
          <button class="btn quiet" type="button" data-action="edit">Change decision</button>
        </div>`;
    }
    if (choosingReason) {
      const reasons = Object.entries(REASONS).map(([key, label]) =>
        `<button class="btn reject" type="button" data-action="reject" data-reason="${key}">${label}</button>`);
      return `
        <p class="prompt">Reason for rejection</p>
        <div class="actions">
          ${reasons.join("")}
          <button class="btn quiet" type="button" data-action="reject-cancel">Cancel</button>
        </div>`;
    }
    return `
      <div class="actions">
        <button class="btn approve" type="button" data-action="approve">Approve</button>
        <button class="btn reject" type="button" data-action="reject-start">Reject</button>
        ${editing ? '<button class="btn quiet" type="button" data-action="edit-cancel">Cancel</button>' : ""}
      </div>`;
  }

  function caseView(number) {
    const item = CASES[number - 1];
    const email = item.proposedEmail;
    const dataItem = (data, kind, mark, tag) =>
      `<li class="${kind}"><span class="data-mark" aria-hidden="true">${mark}</span><span>${escape(data)}</span><span class="data-tag">${tag}</span></li>`;
    const dataList = [
      ...item.share.map((data) => dataItem(data, "share", "✓", "share")),
      ...item.doNotShare.map((data) => dataItem(data, "withhold", "✗", "do not share")),
    ];
    const cc = email.cc.length ? `<div><dt>Cc</dt><dd>${escape(email.cc.join(", "))}</dd></div>` : "";
    return `
      ${topBar(steps(number))}
      <article class="page">
        <p class="eyebrow">Case ${number} of ${CASES.length}</p>
        <h1 tabindex="-1">${escape(item.situation)}</h1>

        <section class="card" aria-labelledby="context-title">
          <h2 id="context-title">Context</h2>
          <dl>
            <div><dt>Intended recipient</dt><dd>${escape(item.recipient.name)} <span class="muted">${escape(item.recipient.email)}</span></dd></div>
            <div><dt>Available data</dt><dd><ul class="data-list">${dataList.join("")}</ul></dd></div>
          </dl>
        </section>

        <section class="card" aria-labelledby="email-title">
          <h2 id="email-title">Proposed email</h2>
          <dl class="email-headers">
            <div><dt>To</dt><dd>${escape(email.to)}</dd></div>
            ${cc}
            <div><dt>Subject</dt><dd>${escape(email.subject)}</dd></div>
          </dl>
          <p class="email-body">${escape(email.body)}</p>
        </section>

        <section class="card decision" aria-live="polite">${decisionControls(number, decisions[item.id])}</section>
      </article>`;
  }

  function dataView() {
    const decided = decidedCases();
    const example = decided[0];
    const rows = CASES.map((item, index) => {
      const entry = decisions[item.id];
      return `<tr>
        <td class="num">${index + 1}</td>
        <td><a href="#review/${index + 1}">${escape(item.situation)}</a></td>
        <td class="${entry ? entry.decision : "pending"}">${escape(decisionLabel(entry))}</td>
      </tr>`;
    });
    const preview = example
      ? `<h2>Example record · case ${CASES.indexOf(example) + 1}</h2>
         <pre>${escape(JSON.stringify(record(example), null, 2))}</pre>`
      : `<h2>Example record</h2><p class="muted">No cases decided yet.</p>`;
    return `
      ${topBar()}
      <article class="page">
        <p class="eyebrow">${decided.length} of ${CASES.length} cases decided</p>
        <h1 tabindex="-1">Training data</h1>
        <p class="lede">Each decided case produces one record. Pending cases are excluded.</p>

        <section class="card table-card">
          <table>
            <thead><tr><th scope="col" class="num">#</th><th scope="col">Case</th><th scope="col">Decision</th></tr></thead>
            <tbody>${rows.join("")}</tbody>
          </table>
        </section>

        <section class="card">${preview}</section>

        <div class="actions">
          <button class="btn light" type="button" data-action="download"${decided.length ? "" : " disabled"}>Download JSONL</button>
          <button class="btn ghost" type="button" data-action="clear"${decided.length ? "" : " disabled"}>Clear decisions</button>
        </div>
      </article>`;
  }

  // Routing. #review is the intro, #review/N is a case, #data is the export page, anything else is home.

  function currentCase() {
    const [page, param] = location.hash.slice(1).split("/");
    const number = Number.parseInt(param, 10);
    return page === "review" && number >= 1 && number <= CASES.length ? number : null;
  }

  function render() {
    const [page, param] = location.hash.slice(1).split("/");
    if (page === "review") {
      const number = currentCase();
      if (number === null && param !== undefined) {
        history.replaceState(null, "", "#review");
        return render();
      }
      app.innerHTML = layout(number === null ? introView() : caseView(number));
      document.title = number === null ? `How to review · ${BRAND}` : `Case ${number} · ${BRAND}`;
    } else if (page === "data") {
      app.innerHTML = layout(dataView());
      document.title = `Training data · ${BRAND}`;
    } else {
      app.innerHTML = layout(homeView());
      document.title = BRAND;
    }
  }

  // Re-render after a decision and keep keyboard focus in the decision area.
  function update() {
    render();
    app.querySelector(".decision .btn")?.focus();
  }

  app.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const number = currentCase();
    const item = number && CASES[number - 1];

    switch (button.dataset.action) {
      case "approve":
        decisions[item.id] = { decision: "approve" };
        choosingReason = editing = false;
        saveDecisions();
        return update();
      case "reject-start":
        choosingReason = true;
        return update();
      case "reject":
        decisions[item.id] = { decision: "reject", reason: button.dataset.reason };
        choosingReason = editing = false;
        saveDecisions();
        return update();
      case "reject-cancel":
        choosingReason = false;
        return update();
      case "edit":
        editing = true;
        return update();
      case "edit-cancel":
        editing = false;
        return update();
      case "download":
        return download();
      case "clear":
        if (!confirm("Clear all recorded decisions?")) return;
        decisions = {};
        saveDecisions();
        return render();
    }
  });

  window.addEventListener("hashchange", () => {
    choosingReason = editing = false;
    render();
    window.scrollTo(0, 0);
    app.querySelector("h1")?.focus();
  });

  render();
})();
