// static/app.js
// Author: Marco D'Amico <marcodamico@protonmail.com>
// Copyright (c) 2026 Marco D'Amico

const statusEl = document.getElementById("status");
const scanBtn = document.getElementById("scanBtn");
const thresholdEl = document.getElementById("threshold");
const globalSearchEl = document.getElementById("globalSearch");
const mainContainer = document.getElementById("container");
const progressContainer = document.getElementById("progressContainer");
const progressBarFill = document.getElementById("progressBarFill");
const statusMsg = document.getElementById("status-msg");
const statusTitle = document.getElementById("status-title");
const cancelBtn = document.getElementById("cancelBtn");
const loadMoreBtn = document.getElementById("loadMoreBtn");
const resultsSummary = document.getElementById("resultsSummary");

const PAGE_SIZE = 100;

let pollInterval = null;
let loadingResults = false;
let renderedPairs = 0;
let totalPairs = 0;

function formatRes(w, h) {
    if (!w || !h) return "Unknown res";
    const mp = (w * h / 1000000).toFixed(1);
    return `${w}x${h} (${mp}MP)`;
}

function setProgressState({
    title,
    message,
    current = 0,
    total = 0,
    show = true,
    showCancel = false,
    indeterminate = false
}) {
    progressContainer.style.display = show ? "block" : "none";
    if (!show) return;

    statusTitle.innerText = title;
    statusMsg.innerText = message;

    cancelBtn.style.display = showCancel ? "block" : "none";
    progressBarFill.classList.toggle("indeterminate", indeterminate);

    if (indeterminate || total <= 0) {
        progressBarFill.style.width = "40%";
        return;
    }

    const percent = Math.max(0, Math.min(100, (current / total) * 100));
    progressBarFill.style.width = `${percent}%`;
}

function createPairCard(pair, index) {
    const card = document.createElement("div");
    card.className = "pair-card";
    card.id = `pair-row-${index}`;

    card.innerHTML = `
        <div class="diff-tag">Similarity Offset: ${pair.diff}</div>
        <div class="photo-box" id="box-${pair.p1.id}">
            <div class="photo-info">
                <span class="badge secondary">${formatRes(pair.p1.width, pair.p1.height)}</span>
                <span style="font-size: 0.8rem; opacity: 0.7">ID: ${pair.p1.id}</span>
            </div>
            <img loading="lazy" decoding="async" src="${pair.p1.url}" alt="${pair.p1.title}" onerror="this.src='https://placehold.co/600x400?text=Image+Not+Found'"/>
            <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-top: 5px;">
                <div style="font-size: 0.9rem; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${pair.p1.title || 'Untitled'}</div>
                <button class="danger" onclick="deletePhoto('${pair.p1.id}', this, 'pair-row-${index}')">DELETE</button>
            </div>
        </div>
        <div class="photo-box" id="box-${pair.p2.id}">
            <div class="photo-info">
                <span class="badge secondary">${formatRes(pair.p2.width, pair.p2.height)}</span>
                <span style="font-size: 0.8rem; opacity: 0.7">ID: ${pair.p2.id}</span>
            </div>
            <img loading="lazy" decoding="async" src="${pair.p2.url}" alt="${pair.p2.title}" onerror="this.src='https://placehold.co/600x400?text=Image+Not+Found'"/>
            <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-top: 5px;">
                <div style="font-size: 0.9rem; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${pair.p2.title || 'Untitled'}</div>
                <button class="danger" onclick="deletePhoto('${pair.p2.id}', this, 'pair-row-${index}')">DELETE</button>
            </div>
        </div>
    `;

    return card;
}

function renderPairs(items, append = true) {
    if (!append) {
        mainContainer.innerHTML = "";
    }

    const fragment = document.createDocumentFragment();
    items.forEach((pair, i) => {
        fragment.appendChild(createPairCard(pair, renderedPairs + i));
    });

    mainContainer.appendChild(fragment);
}

function updateResultsSummary() {
    if (totalPairs === 0) {
        resultsSummary.innerText = "No saved duplicates found.";
        loadMoreBtn.style.display = "none";
        return;
    }

    resultsSummary.innerText = `Showing ${renderedPairs.toLocaleString()} of ${totalPairs.toLocaleString()} duplicate pairs.`;
    loadMoreBtn.style.display = renderedPairs < totalPairs ? "inline-flex" : "none";
}

async function loadSavedResults(reset = true) {
    if (loadingResults) return;

    loadingResults = true;
    try {
        const offset = reset ? 0 : renderedPairs;

        setProgressState({
            title: "Loading Saved Results",
            message: `Fetching duplicate pairs (${offset.toLocaleString()} loaded)...`,
            show: true,
            showCancel: false,
            indeterminate: true
        });

        const res = await fetch(`/api/duplicates?offset=${offset}&limit=${PAGE_SIZE}`);
        const payload = await res.json();

        if (payload.error) {
            statusEl.innerText = `Error loading duplicates: ${payload.error}`;
            setProgressState({ show: false });
            return;
        }

        const items = payload.items || [];
        totalPairs = payload.total || 0;

        if (reset) {
            renderedPairs = 0;
            if (totalPairs === 0) {
                mainContainer.innerHTML = `<div style="text-align: center; padding: 3rem; color: #94a3b8;">No duplicates found. Start a scan with your chosen similarity level.</div>`;
                updateResultsSummary();
                setProgressState({ show: false });
                statusEl.innerText = "Ready. No saved duplicates to display.";
                return;
            }
            mainContainer.innerHTML = "";
        }

        setProgressState({
            title: "Rendering Results",
            message: `Rendering ${items.length.toLocaleString()} pairs...`,
            current: offset + items.length,
            total: totalPairs,
            show: true,
            showCancel: false,
            indeterminate: false
        });

        renderPairs(items, !reset);
        renderedPairs += items.length;

        updateResultsSummary();
        statusEl.innerText = `Ready. Loaded ${renderedPairs.toLocaleString()} / ${totalPairs.toLocaleString()} saved pairs.`;
        setProgressState({ show: false });
    } catch (e) {
        console.error(e);
        statusEl.innerText = "Error loading duplicates.";
        setProgressState({ show: false });
    } finally {
        loadingResults = false;
    }
}

async function startScan() {
    const threshold = parseInt(thresholdEl.value, 10);
    const global_search = globalSearchEl.checked;
    const use_cache = document.getElementById("useCache").checked;

    scanBtn.disabled = true;
    scanBtn.classList.add("loading");
    statusEl.innerText = "Initializing scan...";

    setProgressState({
        title: "Scan in Progress",
        message: "Initializing scan...",
        current: 0,
        total: 0,
        show: true,
        showCancel: true,
        indeterminate: true
    });

    try {
        const res = await fetch("/api/scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ threshold, global_search, use_cache })
        });
        const data = await res.json();

        if (data.status === "started") {
            startPolling();
        } else if (data.error) {
            if (data.error === "Scan already in progress") {
                startPolling();
            } else {
                alert("Scan failed: " + data.error);
                resetUI();
            }
        }
    } catch (e) {
        console.error(e);
        alert("An error occurred during scan start.");
        resetUI();
    }
}

function startPolling() {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
        try {
            const res = await fetch("/api/status");
            const status = await res.json();

            updateProgress(status);

            if (status.message === "Scan complete.") {
                clearInterval(pollInterval);
                finishScan();
            } else if (status.message.startsWith("Error:")) {
                clearInterval(pollInterval);
                alert("Scan failed: " + status.message);
                resetUI();
            }
        } catch (e) {
            console.error("Polling error:", e);
        }
    }, 1000);
}

function updateProgress(status) {
    const hasTotal = status.total > 0;
    const percent = hasTotal ? (status.current / status.total) * 100 : 0;

    setProgressState({
        title: "Scan in Progress",
        message: hasTotal
            ? `${status.message} (${status.current} / ${status.total}, ${Math.round(percent)}%)`
            : status.message,
        current: status.current,
        total: status.total,
        show: true,
        showCancel: true,
        indeterminate: !hasTotal
    });

    statusEl.innerText = hasTotal
        ? `${status.message} (${status.current} / ${status.total})`
        : status.message;

    if (status.is_running) {
        scanBtn.disabled = true;
        scanBtn.classList.add("loading");
    }
}

async function cancelScan() {
    if (!confirm("Are you sure you want to cancel the current scan?")) return;

    cancelBtn.disabled = true;
    cancelBtn.innerText = "Cancelling...";

    try {
        await fetch("/api/cancel", { method: "POST" });
    } catch (e) {
        console.error("Cancel error:", e);
        cancelBtn.disabled = false;
        cancelBtn.innerText = "Cancel Scan";
    }
}

async function finishScan() {
    await loadSavedResults(true);

    scanBtn.disabled = false;
    scanBtn.classList.remove("loading");
    statusEl.innerText = "Scan complete. Review the results below.";

    cancelBtn.disabled = false;
    cancelBtn.innerText = "Cancel Scan";
}

function resetUI() {
    setProgressState({ show: false });

    scanBtn.disabled = false;
    scanBtn.classList.remove("loading");
    statusEl.innerText = "Ready to scan.";

    cancelBtn.disabled = false;
    cancelBtn.innerText = "Cancel Scan";
}

async function deletePhoto(id, btn, rowId) {
    if (!confirm("Are you sure you want to delete this photo from Flickr? This action cannot be undone.")) return;

    btn.disabled = true;
    btn.innerText = "Deleting...";

    try {
        const res = await fetch("/api/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ photo_id: id })
        });
        const data = await res.json();

        if (data.status === "ok") {
            const row = document.getElementById(rowId);
            row.style.opacity = "0.5";
            row.style.pointerEvents = "none";
            btn.className = "secondary";
            btn.innerText = "Deleted";
            statusEl.innerText = "Photo deleted successfully. Pair resolved.";
        } else {
            alert("Delete failed: " + data.error);
            btn.disabled = false;
            btn.innerText = "DELETE";
        }
    } catch (e) {
        console.error(e);
        alert("An error occurred while deleting.");
        btn.disabled = false;
        btn.innerText = "DELETE";
    }
}

async function checkInitialStatus() {
    try {
        const res = await fetch("/api/status");
        const status = await res.json();

        if (status.db_count !== undefined) {
            statusEl.innerText = `Ready. ${status.db_count.toLocaleString()} photos already in local database.`;
        }

        if (status.is_running) {
            startPolling();
            return;
        }

        await loadSavedResults(true);
    } catch (e) {
        console.error("Initial status check failed:", e);
    }
}

function loadMoreResults() {
    loadSavedResults(false);
}

checkInitialStatus();
