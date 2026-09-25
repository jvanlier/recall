(() => {
  const cardStarted = () => { window.recallCardStartedAt = performance.now(); };

  const showAnswer = (card) => {
    if (!card) return;
    const answer = card.querySelector("[data-answer]");
    const ratings = card.querySelector("[data-ratings]");
    const button = card.querySelector("[data-show-answer]");
    if (answer) answer.hidden = false;
    if (ratings) ratings.hidden = false;
    if (button) {
      button.hidden = true;
      button.setAttribute("aria-expanded", "true");
    }
  };

  const renderMath = (root) => {
    const mathElements = root.matches?.(".math")
      ? [root]
      : [...root.querySelectorAll(".math")];
    if (typeof katex === "object" && typeof katex.render === "function") {
      mathElements.forEach((element) => {
        if (element.dataset.katexRendered === "true") return;
        katex.render(element.textContent || "", element, {
          displayMode: element.classList.contains("block"),
          throwOnError: false
        });
        element.dataset.katexRendered = "true";
      });
    }
    if (typeof renderMathInElement !== "function") return;
    renderMathInElement(root, {
      throwOnError: false,
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "$", right: "$", display: false },
        { left: "\\(", right: "\\)", display: false }
      ]
    });
  };

  document.addEventListener("click", (event) => {
    const target = event.target.closest?.("[data-show-answer]");
    if (target) showAnswer(target.closest("[data-card-id]"));
  });

  document.addEventListener("htmx:configRequest", (event) => {
    const elapsed = Math.max(0, Math.round(performance.now() - (window.recallCardStartedAt || performance.now())));
    event.detail.parameters.ms = String(elapsed);
  });

  document.addEventListener("htmx:afterSwap", (event) => {
    renderMath(event.detail.target);
    const reviewed = document.querySelector("#review-card")?.dataset?.reviewed;
    const counter = document.querySelector("[data-session-count]");
    if (reviewed !== undefined && counter) counter.textContent = `${reviewed} reviewed`;
    cardStarted();
  });

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    const focusedControl = event.target.closest?.(
      "button, a, input, textarea, select, summary, [contenteditable='true']"
    );
    if (focusedControl) return;
    const card = document.querySelector("[data-card-id]");
    if (!card) return;

    if (event.key === "u") {
      const undo = card.querySelector("[data-undo]");
      if (undo) { event.preventDefault(); undo.click(); }
      return;
    }
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      const answer = card.querySelector("[data-answer]");
      if (answer?.hidden) showAnswer(card);
      else card.querySelector("button[name='rating'][value='3']")?.click();
      return;
    }
    if (/^[1-4]$/.test(event.key)) {
      event.preventDefault();
      showAnswer(card);
      card.querySelector(`button[name='rating'][value='${event.key}']`)?.click();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    renderMath(document.body);
    cardStarted();
  });
})();
