(function () {
  const form = document.getElementById("ask-form");
  const input = document.getElementById("prompt");
  const button = document.getElementById("ask-btn");
  const result = document.getElementById("result");
  const hints = document.getElementById("hints");

  const cfg = window.APP_CONFIG || {};
  const invokeUrl = String(cfg.apiGatewayUrl || "")
    .trim()
    .replace(/\/$/, "");
  const healthUrl =
    String(cfg.apiGatewayHealthUrl || "").trim() ||
    (invokeUrl.endsWith("/invoke")
      ? invokeUrl.slice(0, -"/invoke".length) + "/health"
      : "");

  const SESSION_KEY = "centerTrafficSessionId";

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
        // Keep >= 33 chars (same recommendation as Lambda / test_api_gateway.py)
        while (id.length < 33) id += "-x";
        sessionStorage.setItem(SESSION_KEY, id);
      }
      return id;
    } catch (_) {
      return "sess-" + Date.now() + "-" + Math.random().toString(16).slice(2) + "-pad";
    }
  }

  async function checkHealth() {
    if (!healthUrl) return;
    try {
      const resp = await fetch(healthUrl, {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(data.error || "Health check failed (" + resp.status + ")");
      }
      if (data.harnessConfigured === false) {
        throw new Error("Lambda에 HARNESS_ARN이 설정되지 않았습니다.");
      }
    } catch (err) {
      // Non-fatal for invoke, but surface a clear message when health is unreachable.
      console.warn("health check:", err);
    }
  }

  async function ask(prompt) {
    const q = (prompt || "").trim();
    if (!q) return;

    if (!invokeUrl) {
      setResult(
        "error",
        "API 주소가 설정되지 않았습니다. config.js의 apiGatewayUrl을 확인하거나 python installer.py --web-only 를 실행하세요."
      );
      return;
    }

    button.disabled = true;
    setResult("loading", "에이전트가 교통 정보를 조회하는 중입니다…");

    const sessionId = getSessionId();
    // Match test_api_gateway.py: POST {apiGatewayUrl} body { prompt, sessionId }
    const payload = { prompt: q, sessionId: sessionId };

    try {
      await checkHealth();

      const controller = new AbortController();
      // API Gateway integration timeout ~29s (same as test_api_gateway.py client)
      const timer = setTimeout(function () {
        controller.abort();
      }, 29000);

      const response = await fetch(invokeUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      clearTimeout(timer);

      const data = await response.json().catch(function () {
        return {};
      });

      if (!response.ok) {
        throw new Error(data.error || "요청 실패 (" + response.status + ")");
      }
      if (data.error && !data.result) {
        throw new Error(data.error);
      }

      if (data.sessionId) {
        try {
          sessionStorage.setItem(SESSION_KEY, data.sessionId);
        } catch (_) {}
      }

      setResult("idle", data.result || "(응답이 비어 있습니다)", {
        markdown: true,
      });
    } catch (err) {
      var message =
        err && err.name === "AbortError"
          ? "요청 시간이 초과되었습니다. 질문을 짧게 줄이거나 잠시 후 다시 시도해 주세요."
          : (err && err.message) || String(err);
      setResult("error", message);
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
