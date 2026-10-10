// Dependency-free SVG charts + sortable tables.
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const pct = v => v == null ? "-" : Math.round(v * 100) + "%";

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  function tooltip(host) {
    const tip = document.createElement("div");
    tip.className = "tooltip";
    host.appendChild(tip);
    return {
      show(html, x, y) {
        tip.innerHTML = html;
        tip.style.display = "block";
        const w = tip.offsetWidth, hw = host.clientWidth;
        tip.style.left = Math.min(Math.max(0, x + 12), hw - w) + "px";
        tip.style.top = (y - tip.offsetHeight - 8) + "px";
      },
      hide() { tip.style.display = "none"; }
    };
  }

  // Horizontal win-rate bars with 95% CI whiskers and a 50% reference line.
  function wrBars(host) {
    const rows = JSON.parse(host.dataset.rows).filter(r => r.n > 0);
    if (!rows.length) { host.innerHTML = '<p class="small">No games in this filter.</p>'; return; }
    const W = host.clientWidth || 400, labelW = 170, valW = 92, rowH = 30, top = 4;
    const H = top + rows.length * rowH + 18;
    const x0 = labelW, x1 = W - valW, sx = v => x0 + v * (x1 - x0);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img" }, host);
    const g = el("g", { class: "grid" }, svg);
    [0, 0.25, 0.75, 1].forEach(t => {
      el("line", { x1: sx(t), x2: sx(t), y1: top, y2: H - 18 }, g);
      el("text", { x: sx(t), y: H - 4, "text-anchor": "middle" }, svg).textContent = pct(t);
    });
    el("text", { x: sx(0.5), y: H - 4, "text-anchor": "middle" }, svg).textContent = "50%";
    const tip = tooltip(host);
    rows.forEach((r, i) => {
      const y = top + i * rowH, cy = y + rowH / 2;
      const grp = el("g", { class: "row" }, svg);
      el("rect", { class: "hit", x: 0, y, width: W, height: rowH, rx: 4 }, grp);
      el("text", { class: "lbl", x: 0, y: cy + 4 }, grp).textContent = r.label;
      const bw = Math.max(0, sx(r.wr) - x0), bh = 12;
      // 4px rounded data-end, square at baseline
      el("path", {
        class: "bar",
        d: bw < 4 ? `M${x0},${cy - bh / 2}h${bw}v${bh}h${-bw}z`
          : `M${x0},${cy - bh / 2}h${bw - 4}a4,4 0 0 1 4,4v${bh - 8}a4,4 0 0 1 -4,4h${-(bw - 4)}z`
      }, grp);
      el("line", { class: "ci", x1: sx(r.lo), x2: sx(r.hi), y1: cy, y2: cy }, grp);
      el("text", { class: "val", x: x1 + 8, y: cy + 4 }, grp).textContent = pct(r.wr);
      el("text", { x: x1 + 44, y: cy + 4 }, grp).textContent = `${r.wins}-${r.losses}`;
      grp.addEventListener("mousemove", e => {
        const b = host.getBoundingClientRect();
        tip.show(`<div class="t">${r.label}</div><div>${pct(r.wr)} win rate · ${r.wins}-${r.losses}</div>` +
          `<div class="m">95% CI ${pct(r.lo)}–${pct(r.hi)}</div>`, e.clientX - b.left, e.clientY - b.top);
      });
      grp.addEventListener("mouseleave", () => tip.hide());
    });
    el("line", { class: "ref", x1: sx(0.5), x2: sx(0.5), y1: top, y2: H - 18 }, svg);
  }

  // Rolling + cumulative match win rate over time, crosshair tooltip.
  function trendChart(host) {
    const pts = JSON.parse(host.dataset.points);
    if (pts.length < 2) { host.innerHTML = '<p class="small">Not enough matches to plot a trend.</p>'; return; }
    const W = host.clientWidth || 800, H = 240, L = 40, R = 90, T = 10, B = 24;
    const sx = i => L + i * (W - L - R) / (pts.length - 1);
    const sy = v => T + (1 - v) * (H - T - B);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img" }, host);
    const g = el("g", { class: "grid" }, svg);
    [0, 0.25, 0.75, 1].forEach(v => {
      el("line", { x1: L, x2: W - R, y1: sy(v), y2: sy(v) }, g);
      el("text", { x: L - 6, y: sy(v) + 4, "text-anchor": "end" }, svg).textContent = pct(v);
    });
    el("line", { class: "ref", x1: L, x2: W - R, y1: sy(0.5), y2: sy(0.5) }, svg);
    el("text", { x: L - 6, y: sy(0.5) + 4, "text-anchor": "end" }, svg).textContent = "50%";
    // x ticks: first/middle/last dates
    [0, Math.floor((pts.length - 1) / 2), pts.length - 1].forEach(i => {
      el("text", { x: sx(i), y: H - 6, "text-anchor": i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle" }, svg)
        .textContent = pts[i].x.slice(0, 10);
    });
    const series = [["cumulative", "var(--series-2)", "Cumulative"], ["rolling", "var(--series-1)", host.dataset.rollingLabel]];
    series.forEach(([key, color, name]) => {
      const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(p[key]).toFixed(1)}`).join("");
      el("path", { d, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      const last = pts[pts.length - 1];
      el("circle", { cx: sx(pts.length - 1), cy: sy(last[key]), r: 4, fill: color, stroke: "var(--surface-1)", "stroke-width": 2 }, svg);
      el("text", { class: "lbl", x: W - R + 8, y: sy(last[key]) + 4 }, svg).textContent = `${pct(last[key])} ${name.split(" ")[0].toLowerCase()}`;
    });
    // de-collide end labels: if within 14px, fall back to legend + tooltip only
    const labels = svg.querySelectorAll("text.lbl");
    if (labels.length === 2 && Math.abs(labels[0].getAttribute("y") - labels[1].getAttribute("y")) < 14)
      labels.forEach(n => n.remove());
    const cross = el("line", { class: "crosshair", y1: T, y2: H - B, visibility: "hidden" }, svg);
    const dots = series.map(([, color]) => el("circle", { r: 4, fill: color, stroke: "var(--surface-1)", "stroke-width": 2, visibility: "hidden" }, svg));
    const tip = tooltip(host);
    const hit = el("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" }, svg);
    hit.addEventListener("mousemove", e => {
      const b = svg.getBoundingClientRect();
      const mx = (e.clientX - b.left) * W / b.width;
      const i = Math.max(0, Math.min(pts.length - 1, Math.round((mx - L) / ((W - L - R) / (pts.length - 1)))));
      const p = pts[i];
      cross.setAttribute("x1", sx(i)); cross.setAttribute("x2", sx(i)); cross.setAttribute("visibility", "visible");
      series.forEach(([key], k) => { dots[k].setAttribute("cx", sx(i)); dots[k].setAttribute("cy", sy(p[key])); dots[k].setAttribute("visibility", "visible"); });
      tip.show(`<div class="t">Match ${p.n} · ${p.x.replace("T", " ")}</div><div>${p.label}</div>` +
        `<div class="m">${host.dataset.rollingLabel}: ${pct(p.rolling)} · cumulative: ${pct(p.cumulative)}</div>`,
        sx(i) * b.width / W, sy(p.rolling) * b.height / H);
    });
    hit.addEventListener("mouseleave", () => { tip.hide(); cross.setAttribute("visibility", "hidden"); dots.forEach(d => d.setAttribute("visibility", "hidden")); });
  }

  // Click-to-sort tables: <th data-sort="num|text">, cells may carry data-v.
  function sortable(table) {
    table.querySelectorAll("th[data-sort]").forEach(th => {
      th.addEventListener("click", () => {
        const idx = Array.from(th.parentNode.children).indexOf(th);
        // first click: text A-Z, numbers high-to-low; later clicks toggle
        const asc = th.classList.contains("sorted-desc") ? true
          : th.classList.contains("sorted-asc") ? false
          : th.dataset.sort === "text";
        table.querySelectorAll("th").forEach(h => h.classList.remove("sorted-asc", "sorted-desc"));
        th.classList.add(asc ? "sorted-asc" : "sorted-desc");
        const body = table.tBodies[0];
        const val = tr => { const c = tr.children[idx]; return c.dataset.v ?? c.textContent.trim(); };
        const rows = Array.from(body.rows).sort((a, b) => {
          let x = val(a), y = val(b);
          if (th.dataset.sort === "num") { x = x === "" ? -Infinity : +x; y = y === "" ? -Infinity : +y; return asc ? x - y : y - x; }
          return asc ? x.localeCompare(y) : y.localeCompare(x);
        });
        rows.forEach(r => body.appendChild(r));
      });
    });
  }

  function render() {
    document.querySelectorAll(".wrbars").forEach(h => { h.innerHTML = ""; wrBars(h); });
    document.querySelectorAll(".trend").forEach(h => { h.innerHTML = ""; trendChart(h); });
  }
  document.addEventListener("DOMContentLoaded", () => {
    render();
    document.querySelectorAll("table.sortable").forEach(sortable);
    let t; window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(render, 150); });
  });
})();
