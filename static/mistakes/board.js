document.querySelectorAll("[data-reveal-button]").forEach((button) => {
    button.addEventListener("click", () => {
        const container = button.closest("[data-reveal-block]");
        if (!container) {
            return;
        }
        const target = container.querySelector("[data-reveal-target]");
        if (!target) {
            return;
        }
        const isHidden = button.dataset.state !== "shown";
        if (isHidden) {
            target.textContent = button.dataset.revealText || "";
            button.dataset.state = "shown";
            button.textContent = "Hide best move";
            return;
        }
        target.textContent = button.dataset.hiddenText || "Hidden";
        button.dataset.state = "hidden";
        button.textContent = "Reveal best move";
    });
});
