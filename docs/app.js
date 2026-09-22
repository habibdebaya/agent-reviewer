/* Browser-only walkthrough. Prepared cases share their content with the Python app. */
(() => {
  "use strict";
  const data = window.REVIEW_DEMO;
  const storageKey = "approval-reviewer-demo-v2";
  const emptyState = () => ({version: 2, nextId: 1, proposals: [], examples: []});
  let state = emptyState();
  let storageAvailable = true;
  let flash = "";
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (saved && saved.version === 2 && Number.isInteger(saved.nextId) &&
        Array.isArray(saved.proposals) && Array.isArray(saved.examples)) state = saved;
  } catch { storageAvailable = false; }
  const main = document.querySelector("#main");
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const save = () => {
    try { localStorage.setItem(storageKey, JSON.stringify(state)); }
    catch { storageAvailable = false; }
  };
  const navigate = (hash) => {
    if (window.location.hash === hash) render();
    else window.location.hash = hash;
  };
  const status = (value) => `<span class="status status-${escape(value === "approve" ? "approved" : value === "reject" ? "rejected" : value)}">${escape(value.replaceAll("_", " "))}</span>`;
  const reasons = () => Object.entries(data.reasons).map(([value, label]) =>
    `<option value="${escape(value)}">${escape(label)}</option>`).join("");
  const allExamples = () => [...state.examples, ...data.samples];
  const teachingRecord = (example) => {
    const {trusted_permission, ...action} = example.action;
    const answer = {decision: example.decision, reason_code: example.reason_code};
    if (example.reason_text) answer.reason = example.reason_text;
    return {messages: [
      {role: "system", content: data.systemInstruction},
      {role: "user", content: JSON.stringify({
        original_request: example.request, prior_history: example.history || [],
        trusted_permission_facts: trusted_permission,
        untrusted_document_evidence: example.evidence, proposed_action: action,
      })},
      {role: "assistant", content: JSON.stringify(answer)},
    ]};
  };
  const download = (filename, records) => {
    const blob = new Blob([records.map((item) => JSON.stringify(teachingRecord(item))).join("\n") + "\n"],
      {type: "application/x-ndjson;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const rulesPanel = () => `
    <section class="panel review-rules" aria-labelledby="rules-heading">
      <p class="eyebrow">The standard you are judging against</p><h2 id="rules-heading">What makes an email okay to send?</h2>
      <p>Use the owner's request, the owner's sending rules, and the source notes. Approve only when all four checks below pass.</p>
      <ol class="criteria-list">${data.reviewCriteria.map((rule) => `<li><h3>${escape(rule.title)}</h3><p>${escape(rule.description)}</p></li>`).join("")}</ol>
      <div class="decision-key"><p><strong>Approve</strong> when all checks pass.</p><p><strong>Reject</strong> when you can identify a violation.</p><p><strong>Need more information</strong> when missing facts prevent a decision.</p></div>
      <p class="small muted">The local app automatically checks the allowed recipient list and a short protected-word list. This demo includes a prepared recipient block. You check whether the message is accurate and follows the request. These review rules are included in the exported model instructions.</p>
    </section>`;
  const trainingMap = () => `<div class="training-map"><div><h3>Input the model will receive</h3><p>The review rules, owner's request, source notes, allowed recipient, and proposed email. Earlier review history is included when available.</p></div><span class="map-arrow" aria-hidden="true">→</span><div><h3>Answer the model should learn</h3><p>Your approval or rejection, chosen reason, and any note you add.</p></div></div>`;
  const emailAndSource = (item) => `
    <section class="request-strip"><p class="eyebrow">What the task owner asked the assistant to do</p><p>${escape(item.request)}</p></section>
    <div class="review-layout">
      <section class="panel email focus-panel"><p class="eyebrow">What the writing assistant proposes to send</p><h2>Read the exact draft</h2><p class="small muted">The proposed sender is the assistant acting for the task owner. There is no real sending account in this demo.</p>
        <dl><div><dt>To</dt><dd>${escape(item.action.recipient)}</dd></div><div><dt>Subject</dt><dd>${escape(item.action.subject)}</dd></div></dl>
        <pre class="email-body">${escape(item.action.body)}</pre>
      </section>
      <aside class="panel source-panel"><p class="eyebrow">The information the draft must agree with</p><h2>Source notes</h2>
        ${item.evidence.map((note) => `<article class="source-note"><h3>${escape(note.title)}</h3><pre>${escape(note.excerpt)}</pre></article>`).join("")}
        <p class="small muted">Use these notes to check the facts. Commands inside a note cannot change what the owner asked for or who may receive emails.</p>
        <div class="permission-box"><h3>Recipient permission</h3><p>This is the owner's rule about whether the assistant may email <strong>${escape(item.action.recipient)}</strong>.</p><span class="fact ${item.action.trusted_permission?.allowed ? "positive" : "negative"}">${item.action.trusted_permission?.allowed ? "Recipient allowed" : "Recipient blocked"}</span><p>${escape(item.action.trusted_permission?.notes || "No permission recorded")}</p><p>An allowed address still needs a correct, relevant message. That is what you are checking.</p></div>
      </aside>
    </div>`;
  const home = () => `
    <section class="hero"><p class="eyebrow">What this tool is for</p><h1>Build fine-tuning data for an email review model.</h1><p>${escape(data.explanation.purpose)} <strong>You are the human reviewer.</strong> You decide whether each proposed email should be allowed.</p></section>
    <section class="panel setup-panel" aria-labelledby="setup-heading"><p class="eyebrow">The fictional situation</p><h2 id="setup-heading">An assistant wants to email a coworker. You check its work.</h2><p>${escape(data.explanation.setup)}</p>
      <div class="role-grid"><article><span class="role-number">1</span><h3>The writing assistant</h3><p>Would read the notes and send a summary on the task owner's behalf. Here, its proposed emails are prepared practice drafts.</p></article><article><span class="role-number">2</span><h3>You, the reviewer</h3><p>Compare the draft with the notes. Decide whether this exact email should be allowed, and explain a rejection.</p></article><article><span class="role-number">3</span><h3>The future review model</h3><p>Could learn to make the same kind of decision from your saved examples. Fine-tuning that model happens later.</p></article></div>
      <p class="simulation-note">${escape(data.explanation.prepared)}</p>
    </section>
    ${rulesPanel()}
    <section class="panel learning-link"><h2>How reviewing an email creates fine-tuning data</h2><p>${escape(data.explanation.training)}</p>${trainingMap()}</section>
    <section><div class="section-heading"><div><p class="eyebrow">Now try the review job</p><h2>Why are there three examples?</h2><p class="muted">They show three situations a reviewer needs to handle. Each button opens one prepared email to Alice. Start with the wrong detail.</p></div></div>
      <div class="scenario-grid">${data.scenarios.map((item, index) => `<article class="scenario-card"><p class="eyebrow">${index === 0 ? "Start here" : "Another situation"}</p><h3>${escape(item.title)}</h3><p>${escape(item.description)}</p><div class="scenario-purpose"><strong>${escape(item.suggested_decision)}</strong><p>${escape(item.training_effect)}</p></div><button data-start="${escape(item.id)}">Open draft <span aria-hidden="true">↗</span></button></article>`).join("")}</div>
    </section>
    <section class="panel permissions-explainer"><h2>What do permissions mean here?</h2><p>${escape(data.explanation.permission)}</p><div class="permission-list"><div><span>alice@example.com</span><strong>May receive emails</strong></div><div><span>finance@example.com</span><strong>Blocked by the owner</strong></div></div><p class="small muted">These are fictional addresses and preset rules for the practice drafts. Text inside a document cannot change them.</p></section>
    <section class="panel"><div class="section-heading"><h2>Waiting for a decision</h2><span class="count-chip">${state.proposals.filter((item) => item.status === "pending").length}</span></div>
      ${state.proposals.filter((item) => item.status === "pending").map((item) => `<a class="queue-item" href="#draft/${item.id}"><span><strong>${escape(item.action.subject)}</strong><small>${item.needsInformation ? "Waiting for more information" : "To " + escape(item.action.recipient)}</small></span><span>Review →</span></a>`).join("") || '<p class="empty-state">Open an example above to make your first decision.</p>'}
    </section>
    <details class="panel"><summary>See an automatic permission block</summary><p>Finance is outside the allowed recipient list. The draft is blocked before a person can approve it.</p><button class="secondary" data-start="blocked">Show the blocked example</button></details>
    <div class="quiet-row"><span>${state.proposals.filter((item) => item.status === "approved").length} approved emails in the pretend outbox</span><a href="#outbox">View outbox →</a></div>`;
  const draftPage = (proposal) => `
    <a class="back" href="#review">← How this works and practice cases</a>
    <div class="section-heading review-heading"><div><p class="eyebrow">Prepared sample · You are the reviewer</p><h1>${proposal.needsInformation ? "Waiting for more information" : proposal.status === "pending" ? "Decide whether this email should be allowed." : "Draft " + escape(proposal.status)}</h1></div>${status(proposal.status)}</div>
    <section class="panel review-brief"><h2>What you are doing on this page</h2><p>The task owner asked for the email below. The <strong>writing assistant</strong> would send it on the owner's behalf to <strong>${escape(proposal.action.recipient)}</strong>. <strong>You are reviewing that proposed action.</strong> Your approval or rejection will become an answer for a future review model to learn.</p><p class="simulation-note">This is a prewritten practice draft representing an assistant's proposed email. Opening it did not call a model. No sending account is connected. Your click will not deliver a real email.</p></section>
    ${proposal.exampleId ? `<section class="confirmation panel" aria-label="Decision saved"><div><p class="eyebrow">Decision saved in this browser</p><h2>You just created one input-and-answer pair</h2><p><strong>Input</strong> is the request, notes, sending permission, and exact email you checked. <strong>Expected answer</strong> is your ${proposal.status === "approved" ? "approval" : "rejection"} and reason. ${proposal.status === "approved" ? "The email was also copied to a pretend outbox." : "The email stayed out of the outbox."} No model was trained and no real email was sent.</p></div><a class="button" href="#example/${proposal.exampleId}">View saved example →</a></section>` : ""}
    ${proposal.status === "blocked" ? '<section class="panel blocked"><h2>Blocked by a fixed rule</h2><p>This recipient is not allowed. A person cannot override this block. No human training answer was created.</p></section>' : ""}
    ${emailAndSource(proposal)}
    ${proposal.history.length ? `<details class="panel"><summary>See the previous draft and feedback</summary>${proposal.history.map((item) => `<pre>${escape(item.body)}</pre>${item.reviews.map((review) => `<p>${escape(review.reason)}</p>`).join("")}`).join("")}</details>` : ""}
    ${proposal.status === "pending" ? `${rulesPanel()}<section class="panel decision-panel"><p class="eyebrow">Now record your judgment</p><h2>What answer should the future review model learn?</h2><p>Use the four checks above. You are supplying the answer, not asking a model to decide for you.</p>
      <div class="decision-effects"><p><strong>Approve draft</strong> saves an approval training answer and copies this email to the pretend outbox.</p><p><strong>Reject draft</strong> saves a rejection training answer with your chosen reason. The draft stays out of the outbox.</p><p><strong>Need more information</strong> records your question and keeps the draft pending. It creates no completed training answer yet.</p></div>
      <form id="decision-form" data-proposal="${proposal.id}"><div class="feedback-fields"><div><label for="reason-code">Reason if you reject</label><select id="reason-code" name="reason_code"><option value="">Choose a reason</option>${reasons()}</select></div><div><label for="reason">Note or question <span class="optional">optional</span></label><textarea id="reason" name="reason" rows="2" placeholder="What needs correcting or clarifying?"></textarea></div></div>
        <p id="decision-error" class="notice" role="alert" hidden></p>
        <div class="button-row"><button name="decision" value="approve">Approve draft</button><button class="danger" name="decision" value="reject">Reject draft</button><button class="secondary" name="decision" value="need_information">Need more information</button></div>
      </form><p class="small review-expiry">This step collects data. It does not fine-tune a model. Your decisions stay in this browser until you download them.</p></section>` : ""}
    ${proposal.status === "rejected" && proposal.scenario !== "uncertain" ? `<section class="panel revision"><p class="eyebrow">Next step</p><h2>A corrected draft needs a fresh decision</h2><p>Continue with a prepared correction that sticks to the meeting notes. Your original decision stays saved.</p><button data-correct="${proposal.id}">Review a prepared correction →</button></section>` : ""}
    ${proposal.reviews.length ? `<details class="panel"><summary>Review history</summary>${proposal.reviews.map((item) => `<p><strong>${escape(item.decision.replaceAll("_", " "))}</strong><br>${escape(item.reason)}</p>`).join("")}</details>` : ""}`;
  const examplesPage = (bundled) => {
    const examples = bundled ? data.samples : [...state.examples].reverse();
    const records = allExamples();
    return `
      <section class="hero compact"><p class="eyebrow">The result of your review work</p><h1>Your decisions are the answers a review model will learn.</h1><p>${escape(data.explanation.training)}</p></section>
      <section class="panel learning-link"><h2>What exactly are we preparing for fine-tuning?</h2><p>A collection of input-and-answer pairs. The model's job will be to review an assistant's proposed email and return an approval decision.</p>${trainingMap()}<p>For the false Thursday launch claim, a useful answer is <strong>Reject · Unsupported information</strong>.</p><p class="simulation-note">This page stores and exports the examples. Fine-tuning a language model is a later step outside this page. It does not happen when you review or download. Your decisions stay in this browser.</p></section>
      <div class="examples-summary"><div><strong>${state.examples.length}</strong><span>Your decisions</span></div><div><strong>${data.samples.length}</strong><span>Bundled samples</span></div><div><strong>${records.filter((item) => item.split === "test").length}</strong><span>Reserved for testing</span></div></div>
      <section class="panel"><div class="section-heading"><div><h2>Open a saved input-and-answer pair</h2><p class="muted"><strong>Your decisions</strong> are the answers you recorded on the review page. <strong>Bundled samples</strong> are fictional examples with preset answers supplied by this demo. They are shown separately so you can tell where each answer came from.</p></div><a href="#review">Review another draft →</a></div>
        <nav class="filter-tabs" aria-label="Example source"><a href="#examples" ${!bundled ? 'aria-current="page"' : ""}>Your decisions</a><a href="#examples/bundled" ${bundled ? 'aria-current="page"' : ""}>Bundled samples</a></nav>
        ${examples.map((item) => `<a class="example-row" href="#example/${item.id}"><div><strong>${escape(item.action.subject)}</strong><p>${escape(item.request)}</p><small>${item.source === "human_review" ? "Your decision on a prepared draft" : "Bundled sample"} · ${item.split === "test" ? "Reserved for testing" : item.split === "validation" ? "Used to choose reviewer settings" : "Teaching example"}</small></div>${status(item.decision)}</a>`).join("") || '<div class="empty-state"><h3>No saved decisions here yet</h3><p>Approve or reject a draft to create your first example. Asking for information keeps the draft pending.</p><a class="button" href="#review">Open a draft</a></div>'}
      </section>
      <section class="panel download-panel"><div><p class="eyebrow">Files for a later fine-tuning job</p><h2>Download the training files</h2><p>The downloads combine your completed decisions with the bundled samples. Each record contains the review instructions, model input, and expected answer.</p><ul class="file-explanations"><li><strong>train.jsonl</strong> contains ${records.filter((item) => item.split === "train").length} examples for teaching the model.</li><li><strong>validation.jsonl</strong> contains ${records.filter((item) => item.split === "validation").length} separate examples for checking it during training.</li></ul><p class="small muted">The ${records.filter((item) => item.split === "test").length} final test examples are left out so they can later check performance on examples the model was not taught. Downloading does not start a training job.</p></div><div class="button-row"><button data-download-split="train">Download training examples ↓</button><button class="secondary" data-download-split="validation">Download validation examples ↓</button></div></section>
      <details class="panel experiment"><summary>How to test whether the reviewer improves</summary><p>The local Python app can train a simple classifier to predict approval or rejection from the saved examples. It compares mistakes and requests for human help using separate test examples. Fine-tuning the intended reviewer language model remains a later step using the downloaded files. This interactive demo collects and exports data only.</p></details>`;
  };
  const examplePage = (example) => `
    <a class="back" href="#examples">← Fine-tuning data</a>
    <section class="hero compact"><p class="eyebrow">${example.source === "human_review" ? "Your saved decision" : "Bundled sample with a preset answer"}</p><h1>This is one example for teaching the review model.</h1><p>A fine-tuning example pairs the information a model sees with the answer it should give. ${example.source === "human_review" ? "You supplied the answer by reviewing this email." : "This answer came from the demo preset."}</p></section>
    <section class="panel training-map"><div><h2>What the model will see</h2><p>The review rules, the owner's request, the source notes, the allowed recipient, and the exact draft below. Earlier review history is included when available.</p></div><span class="map-arrow" aria-hidden="true">→</span><div><h2>What it should answer</h2><p><strong>${example.decision === "approve" ? "Approve this email" : "Reject this email"}</strong> with the saved reason below.</p><p class="small muted">This is a desired training answer. No model is making a new prediction on this page.</p></div></section>
    <section class="panel saved-answer">${status(example.decision)}<div><p class="eyebrow">The saved expected answer and reason</p><h2>${escape(data.reasons[example.reason_code] || (example.reason_code === "within_scope" ? "Matches the request and allowed scope" : example.reason_code.replaceAll("_", " ")))}</h2><p>${escape(example.reason_text)}</p></div></section>
    ${emailAndSource(example)}
    <section class="panel download-panel"><div><h2>${example.split === "test" ? "Reserved for the final test" : "Download this input-and-answer pair"}</h2><p>${example.split === "test" ? "This record is kept out of training downloads so the reviewer can be tested on examples it has not learned from." : example.split === "validation" ? "This record is used to check the reviewer during training. It stays separate from the teaching examples in the full download." : "The file contains the review rules, saved input, and expected answer shown on this page. A later fine-tuning job can use it to teach the reviewer."}</p><p class="small muted">Downloading this record does not train a model.</p></div>
      ${example.split !== "test" ? `<button data-download-example="${example.id}">Download this example ↓</button>` : ""}
    </section>
    <details class="panel"><summary>See the exact record included in the download</summary><p>The system message contains the review rules. The user message contains the email and its context. The assistant message contains the answer you want a future review model to learn. That answer is an approval decision, not the email written by the writing assistant.</p><pre>${escape(JSON.stringify(teachingRecord(example), null, 2))}</pre></details>
    ${example.history?.length ? `<details class="panel"><summary>Earlier drafts and feedback included in this example</summary><pre>${escape(JSON.stringify(example.history, null, 2))}</pre></details>` : ""}
    <div class="quiet-row">${example.proposalId ? `<a href="#draft/${example.proposalId}">Back to the reviewed draft</a>` : ""}<a href="#review">Review another example →</a></div>`;
  const outboxPage = () => `<a class="back" href="#review">← How this works and practice cases</a><section class="hero compact"><p class="eyebrow">Copies of approved drafts</p><h1>Pretend outbox</h1><p>These are the exact emails you allowed in this browser. In a connected system, the writing assistant would send them on the task owner's behalf. This demo has no sending account and delivers no real email.</p></section>${state.proposals.filter((item) => item.status === "approved").map((item) => `<section class="panel"><h2>${escape(item.action.subject)}</h2><p>To ${escape(item.action.recipient)}</p><pre class="email-body">${escape(item.action.body)}</pre><a href="#example/${item.exampleId}">See the saved decision →</a></section>`).join("") || '<p class="empty-state">No approved drafts yet.</p>'}`;
  function render() {
    const hash = window.location.hash.slice(1) || "review";
    const [page, id] = hash.split("/");
    document.querySelector("#nav-review").toggleAttribute("aria-current", !["examples", "example"].includes(page));
    document.querySelector("#nav-examples").toggleAttribute("aria-current", ["examples", "example"].includes(page));
    document.querySelectorAll("nav a[aria-current]").forEach((item) => item.setAttribute("aria-current", "page"));
    let content;
    if (page === "examples" || page === "learning") content = examplesPage(id === "bundled");
    else if (page === "draft") {
      const proposal = state.proposals.find((item) => String(item.id) === id);
      content = proposal ? draftPage(proposal) : '<h1>Draft not found</h1><a href="#review">Open a prepared example</a>';
    } else if (page === "example") {
      const example = allExamples().find((item) => String(item.id) === id);
      content = example ? examplePage(example) : '<h1>Example not found</h1><a href="#examples">View saved examples</a>';
    } else if (page === "outbox") content = outboxPage();
    else content = home();
    main.innerHTML = (storageAvailable ? "" : '<p class="notice">Browser storage is unavailable. Keep this tab open and download your decisions before leaving.</p>') +
      (flash ? `<p class="notice" role="status">${escape(flash)}</p>` : "") + content;
    flash = "";
  }
  document.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.start) {
      const scenario = button.dataset.start;
      if (!data.cases[scenario]) return;
      const proposal = {...copy(data.cases[scenario]), id: state.nextId++, scenario,
        status: scenario === "blocked" ? "blocked" : "pending", history: [], reviews: []};
      state.proposals.push(proposal);
      save();
      navigate("#draft/" + proposal.id);
    } else if (button.dataset.correct) {
      const original = state.proposals.find((item) => String(item.id) === button.dataset.correct);
      if (!original || original.status !== "rejected" || original.scenario === "uncertain") return;
      const existing = state.proposals.find((item) => item.corrects === original.id);
      if (existing) return navigate("#draft/" + existing.id);
      const proposal = {...copy(data.cases.supported), id: state.nextId++, scenario: "supported",
        status: "pending", corrects: original.id, history: [...copy(original.history), {
          event: "previous_proposal", proposal_id: original.id, status: original.status,
          recipient: original.action.recipient, subject: original.action.subject, body: original.action.body,
          reviews: copy(original.reviews),
        }], reviews: []};
      proposal.action.subject = "Corrected meeting summary";
      proposal.action.body = data.correction;
      state.proposals.push(proposal);
      save();
      navigate("#draft/" + proposal.id);
    } else if (button.dataset.downloadExample) {
      const example = allExamples().find((item) => String(item.id) === button.dataset.downloadExample);
      if (example && example.split !== "test") download("review-example-" + example.id + "-" + example.split + ".jsonl", [example]);
    } else if (["train", "validation"].includes(button.dataset.downloadSplit)) {
      const split = button.dataset.downloadSplit;
      download(split + ".jsonl", allExamples().filter((item) => item.split === split));
    }
  });
  document.addEventListener("submit", (event) => {
    if (event.target.id !== "decision-form") return;
    event.preventDefault();
    const proposal = state.proposals.find((item) => String(item.id) === event.target.dataset.proposal);
    if (!proposal || proposal.status !== "pending") return;
    const decision = event.submitter?.value;
    if (!["approve", "reject", "need_information"].includes(decision)) return;
    const fields = new FormData(event.target);
    const note = String(fields.get("reason") || "").trim();
    const selectedReason = String(fields.get("reason_code") || "");
    if (decision === "reject" && (!data.reasons[selectedReason] || (selectedReason === "reviewer_rejection" && !note))) {
      const error = document.querySelector("#decision-error");
      error.textContent = selectedReason === "reviewer_rejection" ? "Add a short note for this reason." : "Choose a reason for rejecting this draft.";
      error.hidden = false;
      document.querySelector(selectedReason === "reviewer_rejection" ? "#reason" : "#reason-code").focus();
      return;
    }
    if (decision === "need_information") {
      const reason = note || "More information is needed before a decision";
      const previous = proposal.reviews.at(-1);
      if (!previous || previous.decision !== decision || previous.reason !== reason) proposal.reviews.push({decision, reason, actor: "human"});
      proposal.needsInformation = true;
      flash = "Waiting for more information. No training answer was saved.";
    } else {
      const reasonCode = decision === "approve" ? "within_scope" : selectedReason;
      const reason = note || data.reasons[reasonCode] || "Approved by reviewer";
      proposal.reviews.push({decision, reason, actor: "human"});
      proposal.status = decision === "approve" ? "approved" : "rejected";
      proposal.needsInformation = false;
      const example = {id: "decision-" + state.nextId++, proposalId: proposal.id, request: proposal.request,
        history: copy(proposal.history), evidence: copy(proposal.evidence), action: copy(proposal.action),
        decision, reason_code: reasonCode, reason_text: reason, source: "human_review",
        split: "train", group_key: "prepared-launch-review-v1"};
      proposal.exampleId = example.id;
      state.examples.push(example);
    }
    save();
    render();
  });
  window.addEventListener("hashchange", () => { render(); window.scrollTo(0, 0); });
  render();
})();
