(function () {
  const form = document.getElementById("ask-form");
  const input = document.getElementById("prompt");
  const button = document.getElementById("ask-btn");
  const result = document.getElementById("result");
  const hints = document.getElementById("hints");

  const cfg = window.APP_CONFIG || {};
  const jobsUrl = String(cfg.apiJobsUrl || cfg.apiGatewayUrl || "")
    .trim()
    .replace(/\/$/, "");
  const healthUrl =
    String(cfg.apiGatewayHealthUrl || "").trim() ||
    (jobsUrl.endsWith("/jobs")
      ? jobsUrl.slice(0, -"/jobs".length) + "/health"
      : jobsUrl.endsWith("/invoke")
        ? jobsUrl.slice(0, -"/invoke".length) + "/health"
        : "");

  const SESSION_KEY = "centerTrafficSessionId";
  const POLL_INTERVAL_MS = 2000;
  const POLL_MAX_MS = 5 * 60 * 1000;

  if (window.marked && typeof window.marked.setOptions === "function") {
    window.marked.setOptions({
      gfm: true,
      breaks: true,
    });
  }

  function renderMarkdown(text) {
    var source = String(text || "");
    if (!window.marked || typeof window.marked.parse !== "function") {
      return null;
    }
    try {
      var html = window.marked.parse(source);
      if (window.DOMPurify && typeof window.DOMPurify.sanitize === "function") {
        html = window.DOMPurify.sanitize(html, {
          USE_PROFILES: { html: true },
        });
      }
      return html;
    } catch (err) {
      console.warn("markdown render failed:", err);
      return null;
    }
  }

  function setResult(state, text, options) {
    var opts = options || {};
    result.dataset.state = state;
    var asMarkdown = opts.markdown === true && state === "idle";
    if (asMarkdown) {
      var html = renderMarkdown(text);
      if (html != null) {
        result.classList.add("markdown");
        result.innerHTML = html;
        return;
      }
    }
    result.classList.remove("markdown");
    result.textContent = text;
  }

  function getSessionId() {
    try {
      let id = sessionStorage.getItem(SESSION_KEY);
      if (!id || id.length < 33) {
        id =
          (crypto.randomUUID && crypto.randomUUID()) ||
          "sess-" + Date.now() + "-" + Math.random().toString(16).slice(2);
        while (id.length < 33) id += "-x";
        sessionStorage.setItem(SESSION_KEY, id);
      }
      return id;
    } catch (_) {
      return "sess-" + Date.now() + "-" + Math.random().toString(16).slice(2) + "-pad";
    }
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  async function checkHealth() {
    if (!healthUrl) return;
    try {
      const resp = await fetch(healthUrl, {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      const data = await resp.json().catch(function () {
        return {};
      });
      if (!resp.ok) {
        throw new Error(data.error || "Health check failed (" + resp.status + ")");
      }
      if (data.harnessConfigured === false) {
        throw new Error("Lambda에 HARNESS_ARN이 설정되지 않았습니다.");
      }
      if (data.jobsTableConfigured === false) {
        throw new Error(
          "Lambda에 JOBS_TABLE이 설정되지 않았습니다. installer.py --harness-only 를 다시 실행하세요."
        );
      }
    } catch (err) {
      console.warn("health check:", err);
    }
  }

  async function createJob(prompt, sessionId) {
    const response = await fetch(jobsUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ prompt: prompt, sessionId: sessionId }),
    });
    const data = await response.json().catch(function () {
      return {};
    });
    if (!response.ok && response.status !== 202) {
      throw new Error(data.error || "작업 생성 실패 (" + response.status + ")");
    }
    if (!data.jobId) {
      throw new Error(data.error || "jobId가 응답에 없습니다.");
    }
    return data;
  }

  async function getJob(jobId) {
    var url = jobsUrl.replace(/\/$/, "") + "/" + encodeURIComponent(jobId);
    const response = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    const data = await response.json().catch(function () {
      return {};
    });
    if (!response.ok) {
      throw new Error(data.error || "작업 조회 실패 (" + response.status + ")");
    }
    return data;
  }

  async function pollJob(jobId) {
    var started = Date.now();
    var lastStatus = "";
    while (Date.now() - started < POLL_MAX_MS) {
      var job = await getJob(jobId);
      var status = String(job.status || "");
      if (status !== lastStatus) {
        lastStatus = status;
        if (status === "QUEUED") {
          setResult("loading", "요청을 접수했습니다. 에이전트 작업을 기다리는 중…");
        } else if (status === "RUNNING") {
          setResult("loading", "에이전트가 교통 정보를 조회·분석하는 중입니다…");
        }
      }
      if (status === "SUCCEEDED") {
        return job;
      }
      if (status === "FAILED") {
        throw new Error(job.error || "분석 작업이 실패했습니다.");
      }
      await sleep(POLL_INTERVAL_MS);
    }
    throw new Error(
      "분석이 예상보다 오래 걸립니다. 잠시 후 다시 시도하거나 질문을 짧게 줄여 주세요."
    );
  }

  async function ask(prompt) {
    const q = (prompt || "").trim();
    if (!q) return;

    if (!jobsUrl) {
      setResult(
        "error",
        "API 주소가 설정되지 않았습니다. config.js의 apiJobsUrl을 확인하거나 python installer.py --web-only 를 실행하세요."
      );
      return;
    }

    button.disabled = true;
    setResult("loading", "요청을 접수하는 중입니다…");

    const sessionId = getSessionId();

    try {
      await checkHealth();

      const created = await createJob(q, sessionId);
      if (created.sessionId) {
        try {
          sessionStorage.setItem(SESSION_KEY, created.sessionId);
        } catch (_) {}
      }

      setResult("loading", "에이전트가 교통 정보를 조회하는 중입니다…");
      const job = await pollJob(created.jobId);

      if (job.sessionId) {
        try {
          sessionStorage.setItem(SESSION_KEY, job.sessionId);
        } catch (_) {}
      }

      setResult("idle", job.result || "(응답이 비어 있습니다)", {
        markdown: true,
      });
    } catch (err) {
      setResult("error", (err && err.message) || String(err));
    } finally {
      button.disabled = false;
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    ask(input.value);
  });

  hints.addEventListener("click", function (event) {
    var target = event.target.closest("button[data-prompt]");
    if (!target) return;
    input.value = target.getAttribute("data-prompt") || "";
    ask(input.value);
  });
})();
