(() => {
  const cardStarted = () => { window.recallCardStartedAt = performance.now(); };

  const ease = "cubic-bezier(.2,.8,.2,1)";
  const riseIn = (element, distance, duration, delay) => element.animate(
    [{ opacity: 0, transform: `translateY(${distance}px)` }, { opacity: 1, transform: "none" }],
    { duration, delay, easing: ease, fill: "backwards" }
  );

  // Morph the "Show answer" button into the answer box, then stagger in its content and the ratings.
  const animateReveal = (button, answer, ratings) => {
    if (!button || !answer || !ratings || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const from = button.getBoundingClientRect().height;
    const to = answer.getBoundingClientRect().height;
    const { backgroundColor, borderRadius } = getComputedStyle(button);
    const children = [...answer.children];
    answer.animate(
      [{ height: `${from}px`, overflow: "hidden", backgroundColor, borderRadius }, { height: `${to}px`, overflow: "hidden" }],
      { duration: 480, easing: ease }
    );
    const ghost = document.createElement("span");
    ghost.className = "answer-ghost";
    ghost.textContent = button.textContent;
    ghost.style.height = `${from}px`;
    answer.append(ghost);
    ghost.animate([{ opacity: 1 }, { opacity: 0, transform: "scale(.92)" }], { duration: 200, fill: "forwards" })
      .finished.then(() => ghost.remove());
    children.forEach((child, i) => riseIn(child, 8, 320, 160 + i * 60));
    ratings.animate(
      [{ height: "0px", marginTop: "0px", overflow: "hidden" }, { height: `${ratings.offsetHeight}px`, overflow: "hidden" }],
      { duration: 480, easing: ease }
    );
    ratings.querySelector(".rating-label")?.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, delay: 250, fill: "backwards" });
    ratings.querySelectorAll(".rating").forEach((rating, i) => riseIn(rating, 12, 360, 300 + i * 55));
  };

  const showAnswer = (card) => {
    if (!card) return;
    const answer = card.querySelector("[data-answer]");
    const ratings = card.querySelector("[data-ratings]");
    const button = card.querySelector("[data-show-answer]");
    const wasHidden = answer?.hidden;
    const buttonVisible = button && !button.hidden;
    if (answer) answer.hidden = false;
    if (ratings) ratings.hidden = false;
    if (wasHidden && buttonVisible) animateReveal(button, answer, ratings);
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
