// ── State ────────────────────────────────────────────────
let allProducts = [];
let activeTag = "";
let saleOnly = false;

// ── Init ─────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadTheme();
    loadCategories();
    loadProducts();
});

// ── Theme ────────────────────────────────────────────────
function loadTheme() {
    const saved = localStorage.getItem("lidl-theme") || "light";
    document.body.className = "theme-" + saved;
}

function toggleTheme() {
    const isLight = document.body.classList.contains("theme-light");
    const next = isLight ? "dark" : "light";
    document.body.className = "theme-" + next;
    localStorage.setItem("lidl-theme", next);
}

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
    if (saleOnly) {
        filtered = filtered.filter(p => p.old_price);
    }
    if (activeTag) {
        filtered = filtered.filter(p => p.tags.includes(activeTag));
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

        const weightHtml = p.weight
            ? `<span class="weight-label">${escHtml(p.weight)}</span>`
            : "";

        const tagsHtml = p.tags
            .map(t => `<span class="tag tag-${t}">${t.replace("_", " ")}</span>`)
            .join("");

        const imageHtml = p.image_url
            ? `<img src="${escHtml(p.image_url)}" alt="${escHtml(p.name)}" loading="lazy">`
            : `<div class="card-image-placeholder">&#127860;</div>`;

        const clickAttr = p.url
            ? `onclick="window.open('${escHtml(p.url)}', '_blank')" style="cursor:pointer;"`
            : "";

        return `
            <div class="product-card score-${scoreClass} fade-in" ${clickAttr}>
                <div class="card-image">${imageHtml}</div>
                <div class="card-content">
                    <div class="card-header">
                        <div class="product-name">${escHtml(p.name)}</div>
                        <div class="score-badge ${scoreClass}">
                            <span>&#9733;</span> ${p.score}
                        </div>
                    </div>
                    <div class="score-bar-container">
                        <div class="score-bar ${scoreClass}" style="width: ${barWidth}%"></div>
                    </div>
                    <div class="card-body">
                        <div class="price-block">
                            <span class="price">${escHtml(p.price || "\u2014")}</span>
                            ${oldPriceHtml}
                            ${weightHtml}
                        </div>
                        <span class="category-label">${escHtml(p.category)}</span>
                    </div>
                    <div class="card-tags">${tagsHtml}</div>
                </div>
            </div>
        `;
    }).join("");

    // Stagger fade-in animations
    grid.querySelectorAll(".fade-in").forEach((el, i) => {
        el.style.animationDelay = `${i * 0.03}s`;
    });
}

// ── Filters ──────────────────────────────────────────────
function onFilterChange() {
    const val = document.getElementById("min-score").value;
    document.getElementById("min-score-val").textContent = val;
    loadProducts();
}

function toggleSale() {
    saleOnly = !saleOnly;
    document.getElementById("sale-toggle").classList.toggle("active", saleOnly);
    renderProducts();
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

// ── Meal plan ────────────────────────────────────────────
let mealMode = "sale";  // "sale" = on-sale picks, "best" = healthiest overall

function mealPlanScore() {
    return document.getElementById("min-score").value;
}

const MEAL_SUBTITLES = {
    sale: "Healthy picks on sale",
    best: "Healthiest picks — on sale or not",
};

// Lock/unlock the page scroll based on whether any modal is open.
function syncBodyScrollLock() {
    const anyOpen = document.querySelector(".modal-overlay:not(.hidden)") !== null;
    document.body.classList.toggle("modal-open", anyOpen);
}

async function openMealPlan() {
    document.getElementById("mealplan-overlay").classList.remove("hidden");
    syncBodyScrollLock();
    await loadMealPlan();
}

async function loadMealPlan() {
    const body = document.getElementById("mealplan-body");
    document.getElementById("mealplan-sub").textContent = MEAL_SUBTITLES[mealMode];
    document.getElementById("tab-sale").classList.toggle("active", mealMode === "sale");
    document.getElementById("tab-best").classList.toggle("active", mealMode === "best");
    body.innerHTML = `<div class="modal-loading">Building your plan&hellip;</div>`;

    const res = await fetch(`/api/mealplan?mode=${mealMode}&min_score=${mealPlanScore()}`);
    const data = await res.json();
    renderMealPlan(data);
}

function setMealMode(mode) {
    if (mode === mealMode) return;
    mealMode = mode;
    loadMealPlan();
}

function renderMealPlan(data) {
    const body = document.getElementById("mealplan-body");

    if (data.message || !data.meals || data.meals.length === 0) {
        body.innerHTML = `<div class="modal-empty">${escHtml(
            data.message || "No on-sale healthy picks to build a plan from right now."
        )}</div>`;
        return;
    }

    const mealsHtml = data.meals.map(m => {
        const rows = m.slots.map(s => `
            <div class="plan-row">
                <span class="plan-role">${escHtml(s.role)}</span>
                <span class="plan-item">${escHtml(s.name)}</span>
                <span class="plan-price">${escHtml(s.price || "—")}</span>
            </div>`).join("");
        return `
            <section class="plan-meal">
                <h3><span class="plan-emoji">${m.emoji}</span>${escHtml(m.title)}</h3>
                ${rows}
            </section>`;
    }).join("");

    const shopHtml = (data.shopping || []).map(it => {
        const was = it.old_price
            ? `<span class="old-price">${escHtml(it.old_price)}</span>` : "";
        return `<li><span class="plan-box"></span>
            <span class="plan-shop-name">${escHtml(it.name)}</span>
            <span class="plan-shop-price">${escHtml(it.price)} ${was}</span></li>`;
    }).join("");

    body.innerHTML = `
        <div class="plan-meals">${mealsHtml}</div>
        <div class="plan-shop">
            <h3>&#128722; Shopping list</h3>
            <ul>${shopHtml}</ul>
        </div>`;
}

function closeMealPlan(event) {
    // Clicks inside the modal are stopped before they reach here; an overlay
    // click arrives with the overlay itself as target.
    if (event && event.target.id !== "mealplan-overlay") return;
    document.getElementById("mealplan-overlay").classList.add("hidden");
    syncBodyScrollLock();
}

// ── Nutri-Score explainer ────────────────────────────────
function openNutri() {
    document.getElementById("nutri-overlay").classList.remove("hidden");
    syncBodyScrollLock();
}

function closeNutri(event) {
    if (event && event.target.id !== "nutri-overlay") return;
    document.getElementById("nutri-overlay").classList.add("hidden");
    syncBodyScrollLock();
}

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closeMealPlan(); closeNutri(); }
});

function downloadMealImage() {
    window.open(`/api/mealplan/image?mode=${mealMode}&min_score=${mealPlanScore()}`, "_blank");
}

function downloadChecklist() {
    window.open(`/api/mealplan/checklist?mode=${mealMode}&min_score=${mealPlanScore()}`, "_blank");
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
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .fade-in {
        animation: fadeIn 0.3s ease both;
    }
`;
document.head.appendChild(style);
