document.addEventListener("DOMContentLoaded", () => {
  // Reveal Animations
  const reveals = document.querySelectorAll(".reveal-up");
  const revealObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          revealObserver.unobserve(entry.target);
        }
      });
    },
    {
      threshold: 0.16,
      rootMargin: "0px 0px -10% 0px",
    }
  );
  reveals.forEach((element) => revealObserver.observe(element));

  // Counter Animations
  const counters = document.querySelectorAll(".counter-anim");
  const speed = 200; // lower is faster

  const counterObserver = new IntersectionObserver(
    (entries, observer) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const counter = entry.target;
          const target = +counter.getAttribute("data-target") || 0;
          
          if (target === 0) {
            counter.innerText = "0";
            observer.unobserve(counter);
            return;
          }

          const updateCount = () => {
            const current = +counter.innerText;
            const increment = Math.max(1, Math.ceil(target / speed));

            if (current < target) {
              counter.innerText = current + increment;
              setTimeout(updateCount, 20);
            } else {
              counter.innerText = target;
            }
          };

          updateCount();
          observer.unobserve(counter);
        }
      });
    },
    { threshold: 0.5 }
  );

  counters.forEach((counter) => counterObserver.observe(counter));

  // Navbar collapse logic
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

  // Premium Hero Mouse Parallax Effect
  const heroPremium = document.querySelector(".hero-visual-premium");
  if (heroPremium) {
    const parallaxElements = document.querySelectorAll("[data-depth]");
    
    document.addEventListener("mousemove", (e) => {
      const x = (e.clientX / window.innerWidth) - 0.5;
      const y = (e.clientY / window.innerHeight) - 0.5;

      requestAnimationFrame(() => {
        parallaxElements.forEach((el) => {
          const depth = parseFloat(el.getAttribute("data-depth")) || 0.5;
          const moveX = x * depth * 60; // Max movement in pixels
          const moveY = y * depth * 60;
          
          // Apply translate while preserving the existing animations by using a CSS variable or wrapper.
          // Since the cards use animations that overwrite transform, we'll shift the whole hero-visual-premium wrapper slightly,
          // or apply margins if transform is locked. Actually, best way is to translate the parent or use a CSS custom property.
          // Let's use CSS custom properties for cleaner integration:
          el.style.setProperty("--px", `${moveX}px`);
          el.style.setProperty("--py", `${moveY}px`);
        });
      });
    });
  }
});
