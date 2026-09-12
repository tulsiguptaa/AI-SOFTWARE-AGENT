// ---- Tab switching --------------------------------------------------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");
  });
});

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function truncate(str, n) {
  return str.length > n ? str.slice(0, n) + "…" : str;
}

// ---- File explorer + code viewer --------------------------------------
// Lets a person actually see the codebase the agent is working on, and
// follows along live as the agent reads/writes specific files - this is
// the main thing the plain scrolling log couldn't show.

const fileList = document.getElementById("file-list");
const codeFilename = document.getElementById("code-filename");
const codeBadge = document.getElementById("code-badge");
const codeContent = document.getElementById("code-content");

let currentFiles = [];       // [{name, lines}]
let touchedFiles = {};       // filename -> "read" | "write"
let activeFile = null;

async function loadFileList() {
  const res = await fetch("/api/files");
  const data = await res.json();
  currentFiles = data.files;
  renderFileList();
}

function renderFileList() {
  fileList.innerHTML = "";
  currentFiles.forEach((f) => {
    const li = document.createElement("li");
    li.className = "file-item";
    if (f.name === activeFile) li.classList.add("active");
    if (touchedFiles[f.name] === "read") li.classList.add("touched-read");
    if (touchedFiles[f.name] === "write") li.classList.add("touched-write");

    li.innerHTML = `<span><span class="file-dot"></span>${escapeHtml(f.name)}</span><span class="file-lines">${f.lines}</span>`;
    li.addEventListener("click", () => openFile(f.name));
    fileList.appendChild(li);
  });
}

async function openFile(filename) {
  activeFile = filename;
  renderFileList();

  const res = await fetch(`/api/file/${encodeURIComponent(filename)}`);
  const data = await res.json();

  codeFilename.textContent = data.filename;
  codeBadge.hidden = touchedFiles[filename] !== "write";

  codeContent.textContent = data.content;
  codeContent.className = "language-python";
  if (window.hljs) hljs.highlightElement(codeContent);
}

function markTouched(filename, kind) {
  // "write" always wins over "read" for the little indicator dot - a file
  // that was edited is more noteworthy than one that was only inspected.
  if (kind === "write" || !touchedFiles[filename]) {
    touchedFiles[filename] = kind;
  }
  renderFileList();
}

// ---- Status / toolbar --------------------------------------------------

const runBtn = document.getElementById("run-btn");
const resetBtn = document.getElementById("reset-btn");
const liveFeed = document.getElementById("live-feed");
const brandDot = document.getElementById("brand-dot");
const statBranch = document.getElementById("stat-branch");
const statState = document.getElementById("stat-state");
const statTests = document.getElementById("stat-tests");
const progressTrack = document.getElementById("progress-track");
const progressFill = document.getElementById("progress-fill");

const MAX_ITERATIONS = 15; // mirrors agent.py's MAX_ITERATIONS, for the progress bar only

async function refreshStatus() {
  const res = await fetch("/api/status");
  const data = await res.json();
  statBranch.textContent = data.branch;
  if (data.tests_passing === true) {
    statTests.textContent = `${data.passed} passing`;
    statTests.className = "stat-value mono state-pass";
  } else if (data.tests_passing === false) {
    statTests.textContent = `${data.failed} failing`;
    statTests.className = "stat-value mono state-fail";
  } else {
    statTests.textContent = "unknown";
    statTests.className = "stat-value mono";
  }
}

// ---- Shared event rendering ------------------------------------------
// Renders one agent event (see agent.py's run_agent_events docstring) as
// a DOM element. Long tool results collapse behind a <details> toggle so
// the feed stays scannable instead of becoming a wall of text.

function renderEvent(event) {
  const el = document.createElement("div");

  switch (event.type) {
    case "iteration_start":
      el.className = "event event-iteration";
      el.textContent = `Iteration ${event.iteration}`;
      break;

    case "budget_warning":
      el.className = "event event-card event-rate-limited";
      el.textContent = "⚠ 2 iterations left — wrapping up.";
      break;

    case "reasoning":
      el.className = "event event-card event-reasoning";
      el.textContent = event.text;
      break;

    case "rate_limited":
      el.className = "event event-card event-rate-limited";
      el.textContent = `⏳ Rate limited — retrying in ${event.wait_seconds}s (attempt ${event.attempt})…`;
      break;

    case "api_error":
      el.className = "event event-card event-api-error";
      el.textContent = `✗ API error: ${event.message}`;
      break;

    case "already_running":
      el.className = "event event-card event-rate-limited";
      el.textContent = "⚠ A run is already in progress - this one was ignored to avoid doubling up API requests.";
      break;

    case "tool_call": {
      el.className = "event event-card event-tool-call";
      const argsStr = JSON.stringify(event.args);
      el.innerHTML = `&gt; <span class="tool-name">${escapeHtml(event.name)}</span>(${escapeHtml(truncate(argsStr, 200))})`;
      break;
    }

    case "tool_result": {
      el.className = "event event-card event-tool-result";
      let resultClass = "";
      if (event.name === "run_tests") {
        const passed = /\bpassed\b/.test(event.result) && !/\bfailed\b/.test(event.result);
        resultClass = passed ? "result-pass" : "result-fail";
      }
      if (event.is_stagnant_repeat) resultClass = "result-stagnant";
      if (resultClass) el.classList.add(resultClass);

      const short = truncate(event.result, 150);
      if (event.result.length > 150) {
        el.innerHTML = `<details><summary>${escapeHtml(short)}</summary><div class="result-body">${escapeHtml(event.result)}</div></details>`;
      } else {
        el.textContent = event.result;
      }
      break;
    }

    case "stopped": {
      el.className = `event event-stopped reason-${event.reason}`;
      const labels = {
        auto_complete: "✓ AUTO-COMPLETE — tests passing, fix committed",
        model_stopped: "Agent finished (no more tool calls)",
        stagnation: "✗ STOPPED — agent got stuck repeating itself",
        max_iterations: "✗ STOPPED — reached max iterations",
        api_error: "✗ STOPPED — unrecoverable API error (see above)",
      };
      el.textContent = `${labels[event.reason] || event.reason} · ${event.iterations_used} iterations`;
      break;
    }

    default:
      el.className = "event event-card";
      el.textContent = JSON.stringify(event);
  }

  return el;
}

// Extracts a filename from a tool call's args, if it has one - used to
// drive the file explorer + code viewer following along live.
function filenameFromArgs(toolName, args) {
  return args && args.filename ? args.filename : null;
}

// ---- Live Run tab -----------------------------------------------------

runBtn.addEventListener("click", () => {
  liveFeed.innerHTML = "";
  touchedFiles = {};
  runBtn.disabled = true;
  brandDot.classList.add("running");
  statState.textContent = "running";
  statState.className = "stat-value mono state-running";
  progressTrack.hidden = false;
  progressFill.style.width = "0%";

  // Tracks the filename argument of whichever tool_call just fired, so the
  // immediately-following tool_result (always paired 1:1 in the event
  // stream - see agent.py's run_agent_events) knows which file it's about,
  // without guessing from whatever happens to be open in the viewer.
  let currentCallFilename = null;

  const source = new EventSource("/api/run-stream");

  source.onmessage = (msg) => {
    const event = JSON.parse(msg.data);
    liveFeed.appendChild(renderEvent(event));
    liveFeed.scrollTop = liveFeed.scrollHeight;

    if (event.type === "iteration_start") {
      progressFill.style.width = `${Math.min(100, (event.iteration / MAX_ITERATIONS) * 100)}%`;
    }

    if (event.type === "tool_call") {
      currentCallFilename = filenameFromArgs(event.name, event.args);
      if (currentCallFilename && event.name === "read_file") {
        markTouched(currentCallFilename, "read");
        openFile(currentCallFilename);
      }
      if (event.name === "create_branch" && event.args.branch_name) {
        statBranch.textContent = event.args.branch_name;
      }
    }

    if (event.type === "tool_result" && event.name === "write_file" && event.result.startsWith("Successfully") && currentCallFilename) {
      markTouched(currentCallFilename, "write");
      openFile(currentCallFilename);
    }

    if (event.type === "stopped" || event.type === "already_running") {
      brandDot.classList.remove("running");
      if (event.type === "already_running") {
        statState.textContent = "already running";
        statState.className = "stat-value mono state-fail";
      } else {
        statState.textContent = event.reason === "auto_complete" ? "done" : "stopped";
        statState.className = `stat-value mono ${event.reason === "auto_complete" ? "state-pass" : "state-fail"}`;
      }
      source.close();
      runBtn.disabled = false;
      refreshStatus();
      loadFileList();
    }
  };

  source.onerror = () => {
    source.close();
    runBtn.disabled = false;
    brandDot.classList.remove("running");
    statState.textContent = "connection lost";
    statState.className = "stat-value mono state-fail";
  };
});

resetBtn.addEventListener("click", async () => {
  resetBtn.disabled = true;
  await fetch("/api/reset", { method: "POST" });
  liveFeed.innerHTML = '<p class="feed-empty">Demo reset. Press "Run Agent" to watch it work, live.</p>';
  touchedFiles = {};
  statState.textContent = "idle";
  statState.className = "stat-value mono";
  progressTrack.hidden = true;
  await refreshStatus();
  await loadFileList();
  if (activeFile) openFile(activeFile);
  resetBtn.disabled = false;
});

// ---- Evaluation tab -----------------------------------------------------

const evalRunBtn = document.getElementById("eval-run-btn");
const evalFeed = document.getElementById("eval-feed");
const evalSummary = document.getElementById("eval-summary");

evalRunBtn.addEventListener("click", () => {
  evalFeed.innerHTML = "";
  evalSummary.hidden = true;
  evalRunBtn.disabled = true;

  document.querySelectorAll(".scenario-card").forEach((card) => {
    card.classList.remove("pass", "fail", "running");
    card.querySelector(".scenario-status").textContent = "not run";
  });

  const source = new EventSource("/api/eval-stream");

  source.onmessage = (msg) => {
    const event = JSON.parse(msg.data);

    if (event.type === "already_running") {
      evalFeed.appendChild(renderEvent(event));
      source.close();
      evalRunBtn.disabled = false;
      return;
    }

    if (event.type === "scenario_start") {
      const card = document.querySelector(`.scenario-card[data-scenario="${event.scenario}"]`);
      card.classList.add("running");
      card.querySelector(".scenario-status").textContent = "running…";
    }

    if (event.type === "agent_event") {
      const el = renderEvent(event.event);
      el.prepend(document.createTextNode(`[${event.scenario}] `));
      evalFeed.appendChild(el);
      evalFeed.scrollTop = evalFeed.scrollHeight;
    }

    if (event.type === "scenario_result") {
      const card = document.querySelector(`.scenario-card[data-scenario="${event.scenario}"]`);
      card.classList.remove("running");
      card.classList.add(event.success ? "pass" : "fail");
      card.querySelector(".scenario-status").textContent =
        `${event.success ? "PASS" : "FAIL"} · ${event.iterations_used} iter · ${event.time_seconds}s`;
    }

    if (event.type === "eval_summary") {
      const s = event.summary;
      document.getElementById("summary-passrate").textContent = `${s.passed}/${s.total}`;
      document.getElementById("summary-iterations").textContent = s.avg_iterations;
      document.getElementById("summary-time").textContent = s.avg_time_seconds;
      evalSummary.hidden = false;
      source.close();
      evalRunBtn.disabled = false;
    }
  };

  source.onerror = () => {
    source.close();
    evalRunBtn.disabled = false;
  };
});

// ---- Init --------------------------------------------------------------

refreshStatus();
loadFileList();
