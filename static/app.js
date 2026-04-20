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

let pollInterval = null;

async function loadDuplicates() {
    try {
        const res = await fetch("/api/duplicates");
        const data = await res.json();
        renderPairs(data);
    } catch (e) {
        console.error(e);
        statusEl.innerText = "Error loading duplicates.";
    }
}

function formatRes(w, h) {
    if (!w || !h) return "Unknown res";
    const mp = (w * h / 1000000).toFixed(1);
    return `${w}x${h} (${mp}MP)`;
}

function renderPairs(data) {
    mainContainer.innerHTML = "";

    if (data.length === 0) {
        mainContainer.innerHTML = `<div style="text-align: center; padding: 3rem; color: #94a3b8;">No duplicates found. Try starting a new scan with a higher threshold or enabling Deep Scan.</div>`;
        return;
    }

    data.forEach((pair, index) => {
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
                <img src="${pair.p1.url}" alt="${pair.p1.title}" onerror="this.src='https://placehold.co/600x400?text=Image+Not+Found'"/>
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
                <img src="${pair.p2.url}" alt="${pair.p2.title}" onerror="this.src='https://placehold.co/600x400?text=Image+Not+Found'"/>
                <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-top: 5px;">
                    <div style="font-size: 0.9rem; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${pair.p2.title || 'Untitled'}</div>
                    <button class="danger" onclick="deletePhoto('${pair.p2.id}', this, 'pair-row-${index}')">DELETE</button>
                </div>
            </div>
        `;

        mainContainer.appendChild(card);
    });
}

async function startScan() {
    const threshold = parseInt(thresholdEl.value);
    const global_search = globalSearchEl.checked;

    scanBtn.disabled = true;
    scanBtn.classList.add("loading");
    statusEl.innerHTML = "<span>🔄</span> Initializing scan...";
    progressContainer.style.display = "block";

    try {
        const res = await fetch("/api/scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ threshold, global_search })
        });
        const data = await res.json();

        if (data.status === "started") {
            startPolling();
        } else if (data.error) {
            if (data.error === "Scan already in progress") {
                // If it's already running, just start polling
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
    const percent = status.total > 0 ? (status.current / status.total) * 100 : 0;
    progressBarFill.style.width = `${percent}%`;

    let displayMsg = status.message;
    if (status.total > 0) {
        displayMsg += ` (${Math.round(percent)}%)`;
    }

    statusMsg.innerText = displayMsg;
    statusEl.innerText = status.message;

    // Ensure buttons reflect the running state
    if (status.is_running) {
        scanBtn.disabled = true;
        scanBtn.classList.add("loading");
        progressContainer.style.display = "block";
    }
}

async function cancelScan() {
    if (!confirm("Are you sure you want to cancel the current scan?")) return;

    const cancelBtn = document.getElementById("cancelBtn");
    cancelBtn.disabled = true;
    cancelBtn.innerText = "Cancelling...";

    try {
        await fetch("/api/cancel", { method: "POST" });
        // Resetting UI will happen via polling if it's still running, 
        // or we can wait for the status to change.
    } catch (e) {
        console.error("Cancel error:", e);
        cancelBtn.disabled = false;
        cancelBtn.innerText = "Cancel Scan";
    }
}

async function finishScan() {
    await loadDuplicates();
    progressContainer.style.display = "none";
    scanBtn.disabled = false;
    scanBtn.classList.remove("loading");
    statusEl.innerText = "Scan complete. Review the results below.";

    const cancelBtn = document.getElementById("cancelBtn");
    cancelBtn.disabled = false;
    cancelBtn.innerText = "Cancel Scan";
}

function resetUI() {
    progressContainer.style.display = "none";
    scanBtn.disabled = false;
    scanBtn.classList.remove("loading");
    statusEl.innerText = "Ready to scan.";

    const cancelBtn = document.getElementById("cancelBtn");
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

        if (status.is_running) {
            startPolling();
        }
    } catch (e) {
        console.error("Initial status check failed:", e);
    }
}

loadDuplicates();
checkInitialStatus();
