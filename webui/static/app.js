"use strict";

const state = {
  env: null,
  cases: [],
  currentRunId: null,
  pollTimer: null,
};

const $ = (sel) => document.querySelector(sel);

const fmt = (v) => {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
};

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

/* ---- env ---- */
function renderEnv(env) {
  const items = [
    ["docker", env.docker, "Docker"],
    ["platform_dsn", env.platform_dsn, "平台 DB"],
    ["agh_ready", env.agh_ready, "AGH"],
    ["model_key", env.model_key, "Agnes key"],
  ];
  for (const [key, ok, label] of items) {
    const el = document.querySelector(`[data-env="${key}"]`);
    el.textContent = `${label}: ${ok ? "就绪" : "未就绪"}`;
    el.classList.remove("pending");
    el.classList.add(ok ? "ok" : "bad");
  }
  const realRadio = document.querySelector('input[name="mode"][value="real"]');
  realRadio.disabled = !env.real_ready;
  if (!env.real_ready) {
    realRadio.title = "真跑需 Docker + 平台 DB + AGH + Agnes key 就绪";
  }
}

/* ---- matrix ---- */
function pill(text, cls) {
  const span = document.createElement("span");
  span.className = `pill ${cls || ""}`;
  span.textContent = text || "—";
  return span;
}

function renderMatrix(run) {
  const report = run && run.report;
  const perCase = (run && run.progress && run.progress.per_case) || {};
  const results = {};
  if (report && report.cases) {
    for (const c of report.cases) results[c.case_id] = c;
  }

  const tbody = $("#matrix-body");
  tbody.innerHTML = "";
  for (const c of state.cases) {
    const tr = document.createElement("tr");
    tr.dataset.caseId = c.case_id;
    if (run && perCase[c.case_id] === "running") tr.classList.add("current");

    const result = results[c.case_id];
    const pStatus = perCase[c.case_id] || "pending";
    const decision = result ? scoreValue(result, "decision_match") : null;

    tr.appendChild(td(c.case_id, "mono"));
    tr.appendChild(td(c.title));
    tr.appendChild(td("", null, pill(typeLabel(c.case_type), c.case_type)));
    tr.appendChild(td(c.difficulty));
    tr.appendChild(td(c.problem_kind));
    tr.appendChild(td("", null, decisionPill(c.expected_decision, "expected")));
    tr.appendChild(td("", null, decisionPill(decision, "actual")));
    tr.appendChild(td("", null, statusDot(pStatus, result)));

    tr.addEventListener("click", () => openDrawer(c.case_id, result, pStatus));
    tbody.appendChild(tr);
  }
}

function td(text, cls, child) {
  const el = document.createElement("td");
  if (cls) el.className = cls;
  if (child) el.appendChild(child);
  else el.textContent = text || "—";
  return el;
}

const TYPE_LABEL = { normal: "正常", boundary: "边界", failure: "失败" };
const typeLabel = (t) => TYPE_LABEL[t] || t || "—";

const DECISION_LABEL = { exact: "精确", under: "漏判", over: "误判" };
function decisionPill(v, kind) {
  const cls = v && (v === "exact" ? "exact" : v === "under" ? "under" : "over");
  const label = DECISION_LABEL[v] || v || "—";
  const span = document.createElement("span");
  span.className = `decision ${cls || ""}`;
  span.textContent = kind === "expected" && v ? `期望 ${label}` : label;
  return span;
}

function statusDot(pStatus, result) {
  const span = document.createElement("span");
  let cls = pStatus;
  let label;
  if (pStatus === "running") {
    label = "运行中";
  } else if (pStatus === "failed") {
    label = "运行失败";
  } else if (pStatus === "missing") {
    label = "缺失运行包";
  } else if (pStatus === "skipped") {
    label = "跳过";
  } else if (result) {
    cls = result.passed ? "ok" : "failed";
    label = result.passed ? "通过" : "未通过";
  } else {
    label = "待运行";
  }
  span.className = `status-dot ${cls}`;
  span.textContent = label;
  return span;
}

function scoreValue(result, name) {
  for (const s of result.scores || []) if (s.name === name) return s.value;
  return null;
}

/* ---- summary ---- */
function renderSummary(run) {
  const report = run && run.report;
  const global = (report && report.global) || {};
  const agg = (report && report.aggregate) || {};
  const results = (report && report.cases) || [];

  const passed = results.filter((c) => c.passed).length;
  const failed = results.length - passed;
  const missing = (global.cases_missing_bundle || []).length;

  const summary = $("#summary");
  summary.hidden = !report;
  if (!report) return;

  setCard("total", state.cases.length);
  setCard("passed", passed);
  setCard("failed", failed);
  setCard("under", (agg.decision && agg.decision.miss && agg.decision.miss.count) ?? 0);
  setCard("over", (agg.decision && agg.decision.false_judgment && agg.decision.false_judgment.count) ?? 0);
  setCard("false_verified", global.false_verified_count ?? 0);
  setCard("missing", missing);
  const overallCard = document.querySelector('[data-key="overall"] .value');
  overallCard.textContent = global.overall_passed === true ? "PASS" : "FAIL";
  overallCard.parentElement.classList.toggle("pass", global.overall_passed === true);
  overallCard.parentElement.classList.toggle("fail", global.overall_passed !== true);
}

function setCard(key, value) {
  const el = document.querySelector(`[data-key="${key}"] .value`);
  el.textContent = fmt(value);
  el.className = "value " + (key === "passed" ? "ok" : key === "failed" || key === "false_verified" ? "bad" : "warn");
}

/* ---- progress ---- */
function renderProgress(run) {
  const wrap = $("#progress-wrap");
  const progress = (run && run.progress) || {};
  if (!run || run.status === "done" || run.status === "error") {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  const total = progress.total || state.cases.length || 1;
  const done = progress.done || 0;
  const pct = Math.round((done / total) * 100);
  $("#progress-fill").style.width = `${pct}%`;
  $("#progress-text").textContent =
    `${done} / ${total}` + (progress.current_case ? ` · 当前 ${progress.current_case}` : "");
}

/* ---- run control ---- */
async function startRun() {
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const onlyBundled = $("#only-bundled").checked;
  const btn = $("#run-btn");
  btn.disabled = true;
  $("#run-status").textContent = mode === "real" ? "真跑启动中…" : "评分中…";
  try {
    const { run_id } = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, only_bundled: onlyBundled }),
    });
    state.currentRunId = run_id;
    poll();
  } catch (e) {
    $("#run-status").textContent = `启动失败：${e.message}`;
    btn.disabled = false;
  }
}

function poll() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    if (!state.currentRunId) return;
    try {
      const run = await api(`/api/runs/${state.currentRunId}`);
      renderRun(run);
      if (run.status === "done" || run.status === "error") {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        $("#run-btn").disabled = false;
        $("#run-status").textContent =
          run.status === "error" ? `运行出错：${run.error || ""}` : "完成";
      }
    } catch (e) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      $("#run-btn").disabled = false;
      $("#run-status").textContent = `轮询失败：${e.message}`;
    }
  }, 1000);
}

function renderRun(run) {
  renderSummary(run);
  renderProgress(run);
  renderMatrix(run);
}

/* ---- drawer ---- */
function openDrawer(caseId, result, pStatus) {
  const meta = state.cases.find((c) => c.case_id === caseId);
  const content = $("#drawer-content");
  content.innerHTML = "";

  const h2 = document.createElement("h2");
  h2.textContent = `${caseId} · ${meta ? meta.title : ""}`;
  content.appendChild(h2);

  const kv = document.createElement("dl");
  kv.className = "kv";
  kv.appendChild(kvRow("类型", typeLabel(meta && meta.case_type)));
  kv.appendChild(kvRow("难度", meta && meta.difficulty));
  kv.appendChild(kvRow("问题类型", meta && meta.problem_kind));
  kv.appendChild(kvRow("症状", meta && meta.symptom_summary));
  kv.appendChild(kvRow("期望决策", meta && meta.expected_decision));
  kv.appendChild(kvRow("运行状态", pStatus));
  content.appendChild(kv);

  if (result) {
    content.appendChild(h3("结论与闸门"));
    const dec = scoreValue(result, "decision_match");
    kv.appendChild(kvRow("实际决策", DECISION_LABEL[dec] || dec));
    kv.appendChild(kvRow("通过", fmt(result.passed)));

    const gates = result.gates || {};
    const gateNames = Object.keys(gates);
    if (gateNames.length) {
      const gateList = document.createElement("div");
      for (const name of gateNames) {
        const row = document.createElement("div");
        row.className = `gate ${gates[name] ? "pass" : "fail"}`;
        row.textContent = `${gates[name] ? "✓" : "✗"} ${name}`;
        gateList.appendChild(row);
      }
      content.appendChild(gateList);
    }

    content.appendChild(h3("评分"));
    const scoreTable = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>指标</th><th>值</th><th>说明</th></tr>";
    scoreTable.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const s of result.scores || []) {
      const tr = document.createElement("tr");
      tr.appendChild(td(s.name, "mono"));
      tr.appendChild(td(fmt(s.value), "mono"));
      tr.appendChild(td(s.comment || ""));
      tbody.appendChild(tr);
    }
    scoreTable.appendChild(tbody);
    content.appendChild(scoreTable);

    const reward = result.reward || {};
    content.appendChild(h3("奖励"));
    const rewardPre = document.createElement("pre");
    rewardPre.textContent = JSON.stringify(reward, null, 2);
    content.appendChild(rewardPre);

    const notes = result.notes || [];
    if (notes.length) {
      content.appendChild(h3("评测说明"));
      const ul = document.createElement("ul");
      for (const n of notes) {
        const li = document.createElement("li");
        li.textContent = n;
        ul.appendChild(li);
      }
      content.appendChild(ul);
    }
  }

  $("#drawer").hidden = false;
  $("#drawer-backdrop").hidden = false;
}

function h3(text) {
  const el = document.createElement("h3");
  el.textContent = text;
  return el;
}

function kvRow(key, value) {
  const dt = document.createElement("dt");
  dt.textContent = key;
  const dd = document.createElement("dd");
  dd.textContent = value || "—";
  const frag = document.createDocumentFragment();
  frag.appendChild(dt);
  frag.appendChild(dd);
  return frag;
}

function closeDrawer() {
  $("#drawer").hidden = true;
  $("#drawer-backdrop").hidden = true;
}

/* ---- boot ---- */
async function boot() {
  $("#run-btn").addEventListener("click", startRun);
  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
  });

  try {
    const [env, cases] = await Promise.all([api("/api/env"), api("/api/cases")]);
    state.env = env;
    state.cases = cases;
    renderEnv(env);
    renderMatrix(null);
  } catch (e) {
    $("#matrix-body").innerHTML =
      `<tr><td colspan="8" class="loading">加载失败：${e.message}</td></tr>`;
  }
}

boot();
