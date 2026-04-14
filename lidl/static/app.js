// ── State ────────────────────────────────────────────────
let allProducts = [];
let activeTag = "";

// ── Init ─────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadCategories();
    loadProducts();
});

// ── API Calls ────────────────────────────────────────────
async function loadCategories() {
    const res = await fetch("/api/categories");
    const cats = await res.json();
    const select = document.getElementById("category-filter");
    cats.forEach(cat => {
        const opt = document.createElement("option");
        opt.value = cat;
        opt.textContent = cat;
        select.appendChild(opt);
    });
}

async function loadProducts() {
    const minScore = document.getElementById("min-score").value;
    const category = document.getElementById("category-filter").value;

    const params = new URLSearchParams({ min_score: minScore });
    if (category) params.set("category", category);

    const res = await fetch(`/api/products?${params}`);
    const data = await res.json();

    allProducts = data.products || [];
    renderProducts();

    const statsText = data.message
        ? data.message
        : `${data.filtered} healthy picks from ${data.total} products scanned`;
    document.getElementById("stats-text").textContent = statsText;
}

// ── Render ───────────────────────────────────────────────
function renderProducts() {
    const grid = document.getElementById("products-grid");
    const empty = document.getElementById("empty-state");

    let filtered = allProducts;
    if (activeTag) {
        filtered = allProducts.filter(p => p.tags.includes(activeTag));
    }

    if (filtered.length === 0) {
        grid.innerHTML = "";
        empty.classList.remove("hidden");
        return;
    }

    empty.classList.add("hidden");

    const maxScore = Math.max(...filtered.map(p => p.score), 1);

    grid.innerHTML = filtered.map((p, i) => {
        const scoreClass = p.score >= 10 ? "high" : p.score >= 6 ? "med" : "low";
        const barWidth = Math.round((p.score / maxScore) * 100);

        const oldPriceHtml = p.old_price
            ? `<span class="old-price">${escHtml(p.old_price)}</span>`
            : "";

        const tagsHtml = p.tags
            .map(t => `<span class="tag tag-${t}">${t.replace("_", " ")}</span>`)
            .join("");

        const clickAttr = p.url
            ? `onclick="window.open('${escHtml(p.url)}', '_blank')" style="cursor:pointer; animation: fadeIn 0.3s ease ${i * 0.03}s both"`
            : `style="animation: fadeIn 0.3s ease ${i * 0.03}s both"`;

        return `
            <div class="product-card score-${scoreClass}" ${clickAttr}>
                <div class="card-header">
                    <div class="product-name">${escHtml(p.name)}</div>
                    <div class="score-badge ${scoreClass}">
                        <span>★</span> ${p.score}
                    </div>
                </div>
                <div class="score-bar-container">
                    <div class="score-bar ${scoreClass}" style="width: ${barWidth}%"></div>
                </div>
                <div class="card-body">
                    <div class="price-block">
                        <span class="price">${escHtml(p.price || "—")}</span>
                        ${oldPriceHtml}
                    </div>
                    <span class="category-label">${escHtml(p.category)}</span>
                </div>
                <div class="card-tags">${tagsHtml}</div>
            </div>
        `;
    }).join("");
}

// ── Filters ──────────────────────────────────────────────
function onFilterChange() {
    const val = document.getElementById("min-score").value;
    document.getElementById("min-score-val").textContent = val;
    loadProducts();
}

function toggleTag(btn) {
    document.querySelectorAll(".tag-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    activeTag = btn.dataset.tag;
    renderProducts();
}

// ── Scan ─────────────────────────────────────────────────
async function startScan() {
    const btn = document.getElementById("scan-btn");
    const banner = document.getElementById("scan-banner");
    const msg = document.getElementById("scan-message");

    btn.classList.add("scanning");
    banner.classList.remove("hidden");
    msg.textContent = "Scanning Lidl Bulgaria...";

    await fetch("/api/scan", { method: "POST" });
    pollScanStatus();
}

async function pollScanStatus() {
    const banner = document.getElementById("scan-banner");
    const msg = document.getElementById("scan-message");
    const btn = document.getElementById("scan-btn");

    const res = await fetch("/api/scan/status");
    const data = await res.json();

    msg.textContent = data.message;

    if (data.running) {
        setTimeout(pollScanStatus, 2000);
    } else {
        btn.classList.remove("scanning");
        setTimeout(() => banner.classList.add("hidden"), 2000);
        loadProducts();
    }
}

// ── Helpers ──────────────────────────────────────────────
function escHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// ── Animation ────────────────────────────────────────────
const style = document.createElement("style");
style.textContent = `
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
`;
document.head.appendChild(style);
