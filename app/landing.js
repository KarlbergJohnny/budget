// Effekter för startsidan: 3D-scen som följer pekaren, kort som lutar,
// menyn på mobil, aktiv meny vid scroll och fram-animation.
"use strict";

const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const finePointer = window.matchMedia("(pointer: fine)").matches;

// Menyn på mobil
const nav = document.querySelector(".nav");
const menuBtn = document.querySelector(".menu-btn");
menuBtn.addEventListener("click", () => {
  const open = nav.classList.toggle("open");
  menuBtn.setAttribute("aria-expanded", String(open));
});
nav.querySelectorAll("nav a").forEach((a) => a.addEventListener("click", () => {
  nav.classList.remove("open");
  menuBtn.setAttribute("aria-expanded", "false");
}));

// Fram-animation när sektioner kommer in i bild
const io = new IntersectionObserver((entries) => {
  entries.forEach((e) => {
    if (e.isIntersecting) {
      e.target.classList.add("in");
      io.unobserve(e.target);
    }
  });
}, { threshold: 0.12 });
document.querySelectorAll(".reveal").forEach((el) => io.observe(el));

// Markera menyval för den sektion som syns
const links = new Map([...document.querySelectorAll('.nav nav a[href^="#"]')].map((a) => [a.getAttribute("href").slice(1), a]));
const spy = new IntersectionObserver((entries) => {
  entries.forEach((e) => {
    const a = links.get(e.target.id);
    if (a && e.isIntersecting) {
      links.forEach((l) => l.classList.remove("active"));
      a.classList.add("active");
    }
  });
}, { rootMargin: "-45% 0px -50% 0px" });
links.forEach((_, id) => { const s = document.getElementById(id); if (s) spy.observe(s); });

if (!reduced) {
  // 3D-scenen i toppen följer pekaren
  const scene = document.getElementById("scene");
  const wrap = scene && scene.parentElement;
  if (scene && finePointer) {
    wrap.addEventListener("pointermove", (ev) => {
      const r = wrap.getBoundingClientRect();
      const x = (ev.clientX - r.left) / r.width - 0.5;
      const y = (ev.clientY - r.top) / r.height - 0.5;
      scene.style.setProperty("--ry", `${-16 + x * 22}deg`);
      scene.style.setProperty("--rx", `${10 - y * 16}deg`);
    });
    wrap.addEventListener("pointerleave", () => {
      scene.style.setProperty("--ry", "-16deg");
      scene.style.setProperty("--rx", "10deg");
    });
  } else if (scene) {
    // På mobil: långsam gungning i stället
    let t = 0;
    const tick = () => {
      t += 0.01;
      scene.style.setProperty("--ry", `${-16 + Math.sin(t) * 8}deg`);
      scene.style.setProperty("--rx", `${10 + Math.cos(t * 0.8) * 3}deg`);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // Kort som lutar och lyser där pekaren är
  if (finePointer) {
    document.querySelectorAll("[data-tilt]").forEach((el) => {
      el.addEventListener("pointermove", (ev) => {
        const r = el.getBoundingClientRect();
        const x = (ev.clientX - r.left) / r.width;
        const y = (ev.clientY - r.top) / r.height;
        el.style.setProperty("--ty", `${(x - 0.5) * 10}deg`);
        el.style.setProperty("--tx", `${(0.5 - y) * 10}deg`);
        el.style.setProperty("--mx", `${x * 100}%`);
        el.style.setProperty("--my", `${y * 100}%`);
      });
      el.addEventListener("pointerleave", () => {
        el.style.setProperty("--ty", "0deg");
        el.style.setProperty("--tx", "0deg");
      });
    });
  }

  // Demo: totalvikten "lastas" när sidan öppnas
  const total = document.getElementById("demoTotal");
  const bar = document.getElementById("demoBar");
  if (total && bar) {
    const target = 76.2, start = 20.0, dur = 2200;
    const t0 = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - t0) / dur);
      const e = 1 - Math.pow(1 - p, 3);
      const v = start + (target - start) * e;
      total.textContent = `${v.toFixed(1).replace(".", ",")} t`;
      bar.style.width = `${(v / 90) * 100}%`;
      if (p < 1) requestAnimationFrame(step);
    };
    bar.style.width = `${(start / 90) * 100}%`;
    requestAnimationFrame(step);
  }
}
