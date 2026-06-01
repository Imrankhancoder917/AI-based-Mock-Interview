document.addEventListener("DOMContentLoaded", () => {
  const charts = document.querySelectorAll("[data-chart]");

  charts.forEach((chart) => {
    const chartType = chart.getAttribute("data-chart");

    if (chartType === "trend") {
      const values = [42, 58, 72, 65, 81, 76, 93];
      values.forEach((value, index) => {
        const bar = document.createElement("div");
        bar.className = "bar";
        bar.style.height = `${value}%`;
        bar.style.animation = `rise 800ms ease ${index * 70}ms both`;
        chart.appendChild(bar);
      });
    }

    if (chartType === "focus") {
      chart.animate(
        [
          { transform: "scale(0.98)", opacity: 0.82 },
          { transform: "scale(1)", opacity: 1 },
        ],
        { duration: 1400, iterations: Infinity, direction: "alternate", easing: "ease-in-out" }
      );
    }
  });

  const actionButtons = document.querySelectorAll(".action-btn");
  actionButtons.forEach((button) => {
    button.addEventListener("click", () => {
      button.animate(
        [
          { transform: "translateY(0) scale(1)" },
          { transform: "translateY(-2px) scale(1.02)" },
          { transform: "translateY(0) scale(1)" },
        ],
        { duration: 360, easing: "ease-out" }
      );
    });
  });
});