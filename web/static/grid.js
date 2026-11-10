/* AG Grid Community (MIT), loaded from jsdelivr at a pinned version. One shared setup for the Ledger, Earnings and the
   PayPal spine table: sorting, column filters, a quick search, CSV export, and a row tap that opens the details
   (receipt hash, request ID, where PayPal's status came from). Totals stay the server's: code does the maths. */
(function () {
  const VERSION = "32.2.0";
  const SRC = `https://cdn.jsdelivr.net/npm/ag-grid-community@${VERSION}/dist/ag-grid-community.min.js`;
  let loading = null;
  function load() {
    if (window.agGrid) return Promise.resolve();
    return loading || (loading = new Promise((res, rej) => {
      const s = document.createElement("script");
      s.src = SRC; s.onload = res;
      s.onerror = () => { loading = null; rej(new Error("The table couldn't load. Check your connection and try again.")); };
      document.head.appendChild(s);
    }));
  }
  function isDark() {
    const h = document.documentElement.classList;
    return h.contains("theme-dark") || (!h.contains("theme-light") && matchMedia("(prefers-color-scheme: dark)").matches);
  }
  function themeClass() { return isDark() ? "ag-theme-quartz-dark" : "ag-theme-quartz"; }
  function follow(el) {  // switch with the app's theme (Settings or the device)
    const set = () => { el.classList.remove("ag-theme-quartz", "ag-theme-quartz-dark"); el.classList.add(themeClass()); };
    new MutationObserver(set).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", set);
    set();
  }
  const E = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const SOURCE_TEXT = { reply: "PayPal's reply to Amend's call", GET: "a GET Amend made to PayPal", webhook: "a verified PayPal webhook" };
  const source = p => !p.value ? `<span class="muted">–</span>`
    : /^Demo/.test(p.value) ? `<span class="src-chip src-demo" title="Seeded demo history: never sent to PayPal">${E(p.value)}</span>`
    : `<span class="src-chip src-${E(p.value).toLowerCase()}" title="${E(SOURCE_TEXT[p.value] || "")}">${E(p.value)}</span>`;
  const usdCell = p => p.value == null ? "" : "$" + Number(p.value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // The details sheet for one row: the receipt hash first (what was written into PayPal), then the ids.
  function detail(title, pairs, links) {
    let d = document.getElementById("grid-detail");
    if (!d) {
      d = document.createElement("dialog"); d.id = "grid-detail"; d.className = "grid-detail";
      d.addEventListener("click", e => { if (e.target === d) d.close(); });
      document.body.appendChild(d);
    }
    d.innerHTML = `<div class="gd-head"><h3>${E(title)}</h3><button class="btn small ghost" data-close aria-label="Close">${icon("x")}</button></div>
      <dl>${pairs.filter(([, v]) => v != null && v !== "").map(([k, v, mono]) => `<dt>${E(k)}</dt><dd>${mono ? `<code>${E(v)}</code>` : E(v)}</dd>`).join("")}</dl>
      ${links && links.length ? `<div class="row wrapx" style="gap:8px;margin-top:12px">${links.map(([t, h]) => `<a class="btn small" href="${E(h)}">${E(t)}</a>`).join("")}</div>` : ""}`;
    d.querySelector("[data-close]").onclick = () => d.close();
    d.showModal ? d.showModal() : d.setAttribute("open", "");
  }

  /* mount(el, {rows, columns, file, placeholder, onRow, pageSize}) → the grid api. el gets a toolbar and the grid. */
  async function mount(el, o) {
    el.innerHTML = `<div class="grid-tools row wrapx"><input type="search" class="grid-q grow" placeholder="${E(o.placeholder || "Search")}" aria-label="Search the table">
      <button class="btn small grid-csv" type="button">Export CSV</button></div><div class="ag-wrap grid-box" role="region" aria-label="${E(o.label || "Table")}"></div>`;
    await load();
    const box = el.querySelector(".grid-box");
    follow(box);
    // phones: the money first (date, amount, status), then the rest; a column that repeats on every row can hide
    let cols = o.columns;
    if (window.innerWidth < 600) {
      const first = o.narrowFirst || [], hide = o.narrowHide || [];
      const pick = cols.filter(c => first.includes(c.field)).sort((a, b) => first.indexOf(a.field) - first.indexOf(b.field));
      cols = [cols[0], ...pick, ...cols.slice(1).filter(c => !first.includes(c.field))].map(c => hide.includes(c.field) ? { ...c, hide: true } : c);
    }
    const api = agGrid.createGrid(box, {
      rowData: o.rows, columnDefs: cols, domLayout: "autoHeight", pagination: true,
      paginationPageSize: o.pageSize || 20, paginationPageSizeSelector: [10, 20, 50, 100],
      defaultColDef: { sortable: true, filter: true, resizable: true, minWidth: 90 },
      tooltipShowDelay: 300, suppressColumnVirtualisation: true,
      onRowClicked: e => o.onRow && o.onRow(e.data),
    });
    el.querySelector(".grid-q").oninput = e => api.setGridOption("quickFilterText", e.target.value);
    el.querySelector(".grid-csv").onclick = () => api.exportDataAsCsv({ fileName: o.file || "amend.csv", allColumns: true });
    return api;
  }
  window.AGrid = { VERSION, load, mount, detail, isDark, source, usdCell, E };
})();
