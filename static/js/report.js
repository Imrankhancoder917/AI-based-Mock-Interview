document.addEventListener("DOMContentLoaded", () => {
  const rings = document.querySelectorAll(".score-ring");

  rings.forEach((ring) => {
    const score = Number(ring.getAttribute("data-score") || 0);
    const progress = ring.querySelector(".progress");
    const circumference = 314;
    const offset = circumference - (Math.max(0, Math.min(score, 100)) / 100) * circumference;

    window.setTimeout(() => {
      progress.style.strokeDashoffset = offset;
    }, 160);
  });

  const sections = document.querySelectorAll(".score-card, .panel, .footer-cta");
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.14 });

  sections.forEach((section) => observer.observe(section));
});