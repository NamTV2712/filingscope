"use strict";

const stages = {
  understanding_question: "Understanding question",
  identifying_requirements: "Identifying required facts",
  searching_filings: "Searching filings",
  searching_structured_facts: "Searching structured facts",
  inspecting_tables: "Inspecting financial tables",
  additional_retrieval: "Additional retrieval completed",
  checking_coverage: "Checking evidence coverage",
  missing_evidence: "Missing evidence detected",
  calculations_verified: "Calculations verified",
  checking_claims: "Checking claims",
  claim_checks_complete: "Claim checks complete",
  finalizing_answer: "Finalizing answer",
};
const dispositions = {
  VERIFIED: ["Verified answer", "good"],
  PARTIAL: ["Partial answer", "warn"],
  ABSTAIN: ["Insufficient evidence", "warn"],
  UNSUPPORTED: ["Outside supported scope", "warn"],
  REJECTED: ["Answer withheld", "warn"],
};
const meanings = {
  company_not_resolved: "The company could not be identified.",
  metric_not_recognized: "The requested financial metric could not be identified.",
  future_reporting_period_requires_clarification: "The question refers to a future reporting period.",
  operation_missing_required_period_scope: "The requested calculation needs explicit reporting periods.",
  predictive_or_advisory_request_unsupported: "The workspace handles historical filing research.",
  no_period_aligned_numeric_fact: "A numeric value aligned to the requested fiscal period was unavailable.",
  no_aligned_numeric_fact: "A numeric value aligned to the requested metric was unavailable.",
  numerical_value_or_period_alignment_missing: "The evidence did not establish a numeric value for the requested period.",
  numerical_value_missing: "The source did not establish a numeric value.",
  no_candidate_evidence: "No evidence candidates were available for this run.",
  period_mismatch: "The source period did not match the requested fiscal period.",
  all_claims_supported: "All released claims passed verification.",
  numeric_claim_matches_cited_fact: "The value matches the cited financial fact.",
  fallback_answer: "The research workflow withheld the answer because evidence was insufficient.",
};
const byId = (id) => document.getElementById(id);
const form = byId("research-form");
const question = byId("question");
const mode = byId("mode");
const status = byId("status");
const run = byId("run");
const tabs = [...document.querySelectorAll('[role="tab"]')];
let busy = false;

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined && text !== null) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function label(value) {
  const cleaned = String(value || "").replaceAll("_", " ").toLowerCase();
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function reason(value) {
  return meanings[value] || label(value);
}

function badge(text, tone = "") {
  return node("span", text, `pill ${tone}`.trim());
}

function externalLink(url, name) {
  if (!url) return null;
  try {
    const target = new URL(url);
    if (!["http:", "https:"].includes(target.protocol) || target.username || target.password) return null;
    const link = node("a", name);
    link.href = target.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  } catch {
    return null;
  }
}

function selectTab(id, focus = false) {
  for (const tab of tabs) {
    const active = tab.id === `tab-${id}`;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    byId(tab.getAttribute("aria-controls")).hidden = !active;
    if (active && focus) tab.focus();
  }
}

tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectTab(tab.getAttribute("aria-controls")));
  tab.addEventListener("keydown", (event) => {
    const next = {
      ArrowLeft: (index + tabs.length - 1) % tabs.length,
      ArrowRight: (index + 1) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    selectTab(tabs[next].getAttribute("aria-controls"), true);
  });
});

function linkButton(text, action) {
  const button = node("button", text, "link-button");
  button.type = "button";
  button.addEventListener("click", action);
  return button;
}

function reference(source, text) {
  return linkButton(text || (source.citation ? `Source ${source.citation}` : (source.company || "Source evidence")), () => {
    selectTab("sources");
    const target = byId(`source-${source.id}`);
    target?.closest("details")?.setAttribute("open", "");
    target?.focus();
    target?.scrollIntoView({ block: "nearest" });
  });
}

function references(ids, sources) {
  const row = node("div", null, "reference-row");
  for (const id of ids) {
    if (sources.has(id)) row.append(reference(sources.get(id)));
  }
  return row;
}

function reasonList(reasons) {
  const list = node("ul");
  for (const code of new Set(reasons)) list.append(node("li", reason(code)));
  return list;
}

function renderAnswer(result, sources) {
  const panel = byId("answer");
  const answer = node("p", null, "answer-text");
  const byNumber = new Map(result.sources.filter((source) => source.citation).map((source) => [source.citation, source]));
  for (const part of result.answer.split(/(\[Source \d+\])/gi)) {
    const citation = /^\[Source (\d+)\]$/i.exec(part);
    const source = citation && byNumber.get(Number(citation[1]));
    answer.append(source ? reference(source, part) : document.createTextNode(part));
  }
  panel.append(answer);
  const supported = result.verification?.claims.filter((claim) => claim.statement) || [];
  if (supported.length) {
    const why = node("details");
    why.append(node("summary", "Why this answer?"));
    const list = node("div", null, "entry-list");
    for (const claim of supported) {
      const entry = node("article", null, "entry");
      entry.append(node("p", claim.statement));
      if (claim.reason_codes.length) entry.append(node("p", claim.reason_codes.map(reason).join(" "), "meta"));
      if (claim.source_ids.length) entry.append(references(claim.source_ids, sources));
      if (claim.calculation_id) {
        entry.append(linkButton("Inspect calculation", () => {
          selectTab("calculations");
          byId(`calculation-${claim.calculation_id}`)?.focus();
        }));
      }
      list.append(entry);
    }
    why.append(list);
    panel.append(why);
  }
  const withheld = ["ABSTAIN", "UNSUPPORTED", "REJECTED", "PARTIAL"].includes(result.status);
  if (withheld) {
    const missing = result.coverage.filter((item) => item.status !== "found");
    const reasons = [...result.coverage_issues, ...(result.verification?.reason_codes || [])];
    panel.append(node("h3", missing.length || result.coverage_issues.length ? "Evidence gaps" : "Release checks"));
    if (missing.length) {
      const list = node("ul");
      for (const item of missing) {
        const requirement = [item.company, item.metric, item.period].filter(Boolean).join(" · ");
        list.append(node("li", item.reason ? `${requirement} — ${reason(item.reason)}` : `${requirement} — ${label(item.status)}`));
      }
      panel.append(list);
    }
    if (reasons.length) panel.append(reasonList(reasons));
    const issues = [...new Set(result.attempts.flatMap((attempt) => attempt.issues))];
    if (issues.length) {
      const list = node("ul");
      for (const issue of issues) list.append(node("li", issue));
      panel.append(list);
    }
    panel.append(node("p", result.attempts.length
      ? `${result.usage.retrieval_calls} retrieval calls and ${result.usage.tool_calls} total tool calls.`
      : "No source searches ran for this question.", "meta"));
    panel.append(linkButton("Inspect search attempts", () => selectTab("trace", true)));
  }
}

function renderSources(result) {
  const panel = byId("sources");
  if (!result.sources.length) {
    panel.append(node("p", "No primary sources were recorded for this question.", "muted"));
    return;
  }
  const used = new Set(result.verification?.claims.filter((claim) => claim.statement).flatMap((claim) => claim.source_ids) || []);
  const related = node("div", null, "source-list");
  const candidates = node("div", null, "source-list");
  for (const source of result.sources) {
    const supported = used.has(source.id);
    const item = node("article", null, "source-card");
    item.id = `source-${source.id}`;
    item.tabIndex = -1;
    const title = source.company || source.document || "Filing source";
    item.append(node("h3", supported && source.citation ? `Source ${source.citation} · ${title}` : title));
    const location = [label(source.type), source.form, source.period, source.page == null ? null : `Page ${source.page}`, source.section].filter(Boolean);
    item.append(node("p", location.join(" · "), "meta"));
    if (source.document && source.document !== source.company) item.append(node("p", source.document, "meta"));
    if (source.value) item.append(node("p", [source.metric, source.value, source.unit].filter(Boolean).join(" · ")));
    if (source.accession) {
      const revision = source.revision_policy ? ` · Requested basis ${label(source.revision_policy)}` : "";
      item.append(node("p", `Accession ${source.accession} · ${label(source.revision)}${revision}`, "meta"));
      item.append(node("p", [source.tag, source.start, source.end, source.filed && `Filed ${source.filed}`].filter(Boolean).join(" · "), "meta"));
    }
    const links = node("div", null, "reference-row");
    for (const link of [externalLink(source.url, "Open source filing"), externalLink(source.facts_url, "Open SEC Company Facts")]) {
      if (link) links.append(link);
    }
    if (links.childElementCount) item.append(links);
    (supported ? related : candidates).append(item);
  }
  if (related.childElementCount) panel.append(related);
  if (candidates.childElementCount) {
    const details = node("details");
    details.append(node("summary", `Other evidence records (${candidates.childElementCount})`), candidates);
    details.open = !related.childElementCount;
    panel.append(details);
  }
}

function renderCoverage(result, sources) {
  const panel = byId("coverage");
  if (result.coverage.length) {
    const found = result.coverage.filter((item) => item.status === "found").length;
    panel.append(node("p", `${found} of ${result.coverage.length} required facts found.`, "meta"));
    const wrap = node("div", null, "table-wrap");
    const table = node("table");
    const header = table.createTHead().insertRow();
    for (const title of ["Required fact", "Fiscal period", "Evidence"]) {
      const heading = node("th", title);
      heading.scope = "col";
      header.append(heading);
    }
    const body = table.createTBody();
    for (const item of result.coverage) {
      const row = body.insertRow();
      row.insertCell().textContent = [item.company, item.metric].filter(Boolean).join(" · ");
      row.insertCell().textContent = item.period || "Unspecified";
      const evidence = row.insertCell();
      evidence.append(badge(label(item.status), item.status === "found" ? "good" : "warn"));
      if (item.reason) evidence.append(node("p", reason(item.reason), "meta"));
      if (item.source_ids.length) evidence.append(references(item.source_ids, sources));
    }
    wrap.append(table);
    panel.append(wrap);
  } else {
    panel.append(node("p", "No financial fact requirements were resolved.", "muted"));
  }
  if (result.coverage_issues.length) panel.append(reasonList(result.coverage_issues));
}

function renderCalculations(result, sources) {
  const panel = byId("calculations");
  if (!result.calculations.length) {
    panel.append(node("p", "This run produced no calculations.", "muted"));
    return;
  }
  for (const calculation of result.calculations) {
    const item = node("article", null, "entry");
    item.id = `calculation-${calculation.id}`;
    item.tabIndex = -1;
    item.append(node("h3", [label(calculation.operation), calculation.period].filter(Boolean).join(" · ")));
    item.append(badge(label(calculation.status), calculation.status === "verified" ? "good" : "warn"));
    item.append(node("p", `${calculation.formula} = ${calculation.result} ${calculation.unit || ""}`));
    item.append(node("p", calculation.rounding, "meta"));
    const inputs = node("ul");
    for (const input of calculation.inputs) {
      const row = node("li", input.value);
      if (sources.has(input.source_id)) row.append(" · ", reference(sources.get(input.source_id)));
      inputs.append(row);
    }
    item.append(inputs);
    panel.append(item);
  }
}

function renderVerification(result, sources) {
  const panel = byId("verification");
  if (!result.verification) {
    panel.append(node("p", "No claims reached verification.", "muted"));
    return;
  }
  panel.append(node("p", `Release decision · ${label(result.verification.disposition)}`, "meta"));
  if (result.verification.reason_codes.length) panel.append(reasonList(result.verification.reason_codes));
  for (const claim of result.verification.claims) {
    const item = node("article", null, "entry");
    item.append(badge(label(claim.status), claim.status === "SUPPORTED" ? "good" : "warn"));
    if (claim.statement) item.append(node("p", claim.statement));
    item.append(node("p", `Citation check · ${label(claim.citation_status)}`, "meta"));
    if (claim.reason_codes.length) item.append(reasonList(claim.reason_codes));
    if (claim.source_ids.length) item.append(references(claim.source_ids, sources));
    panel.append(item);
  }
}

function renderTrace(result, progress) {
  const panel = byId("trace");
  panel.append(node("p", `${label(result.route)} route · ${result.usage.retrieval_calls} retrieval calls · ${result.usage.llm_calls} LLM calls · ${(result.usage.wall_time_ms / 1000).toFixed(2)} s`, "meta"));
  const timeline = node("ol", null, "timeline");
  for (const stage of progress) timeline.append(node("li", stage));
  panel.append(timeline, node("h3", "Search attempts"));
  if (!result.attempts.length) panel.append(node("p", "No search workers ran.", "muted"));
  for (const attempt of result.attempts) {
    const item = node("article", null, "entry");
    item.append(node("h3", attempt.stage), badge(label(attempt.status)));
    item.append(node("p", `${attempt.searches} retrieval calls · ${attempt.tools} tool calls · ${attempt.candidates} candidate chunks`, "meta"));
    if (attempt.issues.length) {
      const issues = node("ul");
      for (const issue of attempt.issues) issues.append(node("li", issue));
      item.append(issues);
    }
    panel.append(item);
  }
  if (result.scopes.length) {
    const scope = node("details");
    scope.append(node("summary", "Planned source scope"));
    const items = node("ul");
    for (const item of result.scopes) {
      items.append(node("li", [item.company, item.metric, item.period, label(item.availability), `${item.documents} scoped filing documents`].filter(Boolean).join(" · ")));
    }
    scope.append(items);
    panel.append(scope);
  }
}

function render(result, progress) {
  const sources = new Map(result.sources.map((source) => [source.id, source]));
  for (const tab of tabs) byId(tab.getAttribute("aria-controls")).replaceChildren();
  byId("result-status").replaceChildren(badge(...dispositions[result.status]));
  renderAnswer(result, sources);
  renderSources(result);
  renderCoverage(result, sources);
  renderCalculations(result, sources);
  renderVerification(result, sources);
  renderTrace(result, progress);
  byId("results").hidden = false;
  selectTab("answer");
  byId("result-title").focus({ preventScroll: true });
}

async function readResearch(response, progress) {
  if (!response.ok) throw new Error((await response.json()).message);
  if (!response.body) throw new Error("The response stream is unavailable.");
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let pending = "";
  let result = null;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += value;
      const lines = pending.split("\n");
      pending = lines.pop();
      for (const line of lines) {
        if (!line) continue;
        const event = JSON.parse(line);
        if (event.type === "error") throw new Error(event.message);
        if (event.type === "result") result = event.result;
        if (event.type === "progress" && Object.hasOwn(stages, event.stage)) {
          const text = stages[event.stage];
          progress.push(text);
          byId("activity-list").append(node("li", text));
          status.textContent = text;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
  if (pending.trim() || !result) throw new Error("The research stream ended before a result arrived. Retry the question.");
  return result;
}

for (const example of document.querySelectorAll("[data-example]")) {
  example.addEventListener("click", () => {
    question.value = example.dataset.example;
    question.setCustomValidity("");
    mode.value = example.dataset.mode;
    question.focus();
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  if (!question.value.trim()) {
    question.setCustomValidity("Enter a financial research question.");
    question.reportValidity();
    return;
  }
  busy = true;
  run.disabled = true;
  const payload = { question: question.value, mode: mode.value };
  question.readOnly = true;
  mode.disabled = true;
  byId("welcome").hidden = true;
  byId("results").hidden = true;
  byId("error").hidden = true;
  byId("activity-empty").hidden = true;
  byId("activity-list").replaceChildren();
  status.textContent = "Starting research…";
  status.classList.remove("visually-hidden");
  const progress = [];
  try {
    const response = await fetch("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await readResearch(response, progress);
    render(result, progress);
    status.textContent = dispositions[result.status][0];
    status.classList.add("visually-hidden");
  } catch (error) {
    status.textContent = "";
    byId("error").textContent = error instanceof SyntaxError || error instanceof TypeError
      ? "The workspace could not read the research result. Check the local server and retry."
      : error.message;
    byId("error").hidden = false;
  } finally {
    busy = false;
    run.disabled = false;
    question.readOnly = false;
    mode.disabled = false;
  }
});
question.addEventListener("input", () => question.setCustomValidity(""));
