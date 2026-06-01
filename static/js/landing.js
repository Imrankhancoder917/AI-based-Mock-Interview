document.addEventListener("DOMContentLoaded", () => {
  const reveals = document.querySelectorAll(".reveal-up");

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        }
      });
    },
    {
      threshold: 0.16,
      rootMargin: "0px 0px -10% 0px",
    }
  );

  reveals.forEach((element) => observer.observe(element));

  const navLinks = document.querySelectorAll(".navbar .nav-link, .footer-link");
  navLinks.forEach((link) => {
    link.addEventListener("click", () => {
      const collapseElement = document.querySelector(".navbar-collapse.show");
      if (collapseElement && window.bootstrap) {
        const collapseInstance = bootstrap.Collapse.getInstance(collapseElement);
        if (collapseInstance) {
          collapseInstance.hide();
        }
      }
    });
  });

  const heroSection = document.querySelector(".hero-section");
  if (heroSection) {
    let ticking = false;

    const onScroll = () => {
      if (ticking) {
        return;
      }

      ticking = true;
      window.requestAnimationFrame(() => {
        const offset = window.scrollY * 0.08;
        heroSection.style.setProperty("--hero-offset", `${offset}px`);
        ticking = false;
      });
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }
});
