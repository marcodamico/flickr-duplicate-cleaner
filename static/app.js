// static/app.js
// Author: Marco D'Amico <marcodamico@protonmail.com>
// Copyright (c) 2026 Marco D'Amico

const statusEl = document.getElementById("status");
const scanBtn = document.getElementById("scanBtn");
const thresholdEl = document.getElementById("threshold");
const globalSearchEl = document.getElementById("globalSearch");
const scanModeEl = document.getElementById("scanMode");
const mainContainer = document.getElementById("container");
const progressContainer = document.getElementById("progressContainer");
const progressBarFill = document.getElementById("progressBarFill");
const statusMsg = document.getElementById("status-msg");
const statusTitle = document.getElementById("status-title");
const cancelBtn = document.getElementById("cancelBtn");
const loadMoreBtn = document.getElementById("loadMoreBtn");
const resultsSummary = document.getElementById("resultsSummary");

const lightboxModal = document.getElementById("lightboxModal");
const lightboxOverlay = document.getElementById("lightboxOverlay");
const lightboxClose = document.getElementById("lightboxClose");
const lightboxPrev = document.getElementById("lightboxPrev");
const lightboxNext = document.getElementById("lightboxNext");
const lightboxImage = document.getElementById("lightboxImage");
const lightboxCaption = document.getElementById("lightboxCaption");
const lightboxOpenOriginal = document.getElementById("lightboxOpenOriginal");
const lightboxSelect = document.getElementById("lightboxSelect");
const lightboxSelectLabel = document.getElementById("lightboxSelectLabel");
const lightboxOriginalInfo = document.getElementById("lightboxOriginalInfo");

const PAGE_SIZE = 50;

let pollInterval = null;
let loadingResults = false;
let renderedGroups = 0;
let totalGroups = 0;
let currentScanMode = "duplicates";
const groupsById = new Map();
const selectedByGroup = new Map();
const compactByGroup = new Map();
const originalInfoCache = new Map();
const lightboxState = { groupId: null, index: 0 };

function formatRes(w, h) {
    if (!w || !h) return "Unknown";
    const mp = (w * h / 1000000).toFixed(1);
    return `${w}x${h} (${mp}MP)`;
}

function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return "Unknown size";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function escapeHtml(value) {
    return String(value || "").replace(/[&<>'\"]/g, (ch) => {
        return {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            "\"": "&quot;",
            "'": "&#39;"
        }[ch] || ch;
    });
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

function updateResultsSummary() {
    if (totalGroups === 0) {
        if (currentScanMode === "nsfw") {
            resultsSummary.innerText = "No saved NSFW matches found.";
        } else {
            resultsSummary.innerText = "No saved duplicate groups found.";
        }
        loadMoreBtn.style.display = "none";
        return;
    }

    if (currentScanMode === "nsfw") {
        resultsSummary.innerText = `Showing ${renderedGroups.toLocaleString()} of ${totalGroups.toLocaleString()} nudity matches.`;
    } else {
        resultsSummary.innerText = `Showing ${renderedGroups.toLocaleString()} of ${totalGroups.toLocaleString()} groups.`;
    }
    loadMoreBtn.style.display = renderedGroups < totalGroups ? "inline-flex" : "none";
}

function getResultEndpoint() {
    return currentScanMode === "nsfw" ? "/api/nsfw-results" : "/api/duplicates";
}

function getMinimumGroupSize() {
    return currentScanMode === "nsfw" ? 1 : 2;
}

function getSelectedSet(groupId) {
    if (!selectedByGroup.has(groupId)) {
        selectedByGroup.set(groupId, new Set());
    }
    return selectedByGroup.get(groupId);
}

function sortGroupPhotosInPlace(group) {
    if (!group || !Array.isArray(group.photos)) return;
    group.photos.sort((a, b) => {
        const titleA = String(a.title || "").trim();
        const titleB = String(b.title || "").trim();
        const cmp = titleA.localeCompare(titleB, undefined, { sensitivity: "base", numeric: true });
        if (cmp !== 0) return cmp;
        return String(a.id || "").localeCompare(String(b.id || ""), undefined, { numeric: true });
    });
}

function createGroupCard(group) {
    const card = document.createElement("section");
    card.className = "group-card";
    card.dataset.groupId = group.group_id;

    const photosHtml = group.photos.map((photo, idx) => {
        const safeTitle = escapeHtml(photo.title || "Untitled");
        const nsfwLabel = escapeHtml(photo.nsfw_label || "unknown");
        const nsfwScore = Number.isFinite(photo.nsfw_score)
            ? ` • NSFW score ${(photo.nsfw_score * 100).toFixed(1)}%`
            : "";
        return `
            <article class="group-photo" data-photo-id="${photo.id}">
                <label class="photo-checkline">
                    <input class="photo-check" type="checkbox" data-group-id="${group.group_id}" data-photo-id="${photo.id}">
                    <span>Select</span>
                </label>
                <button class="thumb-btn" type="button" data-action="open-lightbox" data-group-id="${group.group_id}" data-photo-index="${idx}">
                    <img loading="lazy" decoding="async" src="${photo.url}" alt="${safeTitle}" onerror="this.src='https://placehold.co/300x200?text=Image+Not+Found'"/>
                </button>
                <div class="photo-title" title="${safeTitle}">${safeTitle}</div>
                <div class="photo-meta">Original: ${formatRes(photo.original_width, photo.original_height)} • Preview: ${formatRes(photo.width, photo.height)} • ID ${photo.id}${currentScanMode === "nsfw" ? ` • Label ${nsfwLabel}${nsfwScore}` : ""}</div>
                <a class="photo-original-link" href="${photo.original_url || photo.url}" target="_blank" rel="noopener noreferrer">Open Original</a>
            </article>
        `;
    }).join("");

    const isCompact = compactByGroup.get(group.group_id) === true;

    card.innerHTML = `
        <header class="group-header">
            <div>
                <h3>${currentScanMode === "nsfw" ? "NSFW Match" : "Group"} ${escapeHtml(group.group_id)}</h3>
                <p>${group.size} photos${currentScanMode === "nsfw" ? "" : ` • Avg diff ${group.avg_diff}`}</p>
            </div>
            <div class="group-actions">
                <button class="secondary toggle-compact" type="button" data-group-id="${group.group_id}">
                    ${isCompact ? "Expand" : "Compact"}
                </button>
                <label class="select-all-wrap">
                    <input class="select-all" type="checkbox" data-group-id="${group.group_id}">
                    <span>Select all</span>
                </label>
                <button class="secondary resolve-selected" type="button" data-group-id="${group.group_id}" disabled>Resolve selected</button>
                <button class="danger delete-selected" type="button" data-group-id="${group.group_id}" disabled>Delete selected</button>
            </div>
        </header>
        <div class="group-grid">
            ${photosHtml}
        </div>
    `;

    card.classList.toggle("compact", isCompact);
    return card;
}

function syncGroupControls(groupId) {
    const card = document.querySelector(`.group-card[data-group-id="${groupId}"]`);
    if (!card) return;

    const group = groupsById.get(groupId);
    if (!group) return;

    const selected = getSelectedSet(groupId);
    const allIds = group.photos.map((p) => p.id);
    const selectedCount = allIds.filter((id) => selected.has(id)).length;

    const selectAll = card.querySelector(".select-all");
    const resolveBtn = card.querySelector(".resolve-selected");
    const deleteBtn = card.querySelector(".delete-selected");

    deleteBtn.disabled = selectedCount === 0;
    resolveBtn.disabled = selectedCount === 0;
    deleteBtn.textContent = selectedCount > 0 ? `Delete selected (${selectedCount})` : "Delete selected";
    resolveBtn.textContent = selectedCount > 0 ? `Resolve selected (${selectedCount})` : "Resolve selected";

    selectAll.checked = selectedCount > 0 && selectedCount === allIds.length;
    selectAll.indeterminate = selectedCount > 0 && selectedCount < allIds.length;

    card.querySelectorAll(".photo-check").forEach((input) => {
        const pid = input.dataset.photoId;
        input.checked = selected.has(pid);
    });
}

function renderGroups(items, append = true) {
    if (!append) {
        mainContainer.innerHTML = "";
        groupsById.clear();
        selectedByGroup.clear();
        compactByGroup.clear();
    }

    const fragment = document.createDocumentFragment();
    items.forEach((group) => {
        sortGroupPhotosInPlace(group);
        groupsById.set(group.group_id, group);
        selectedByGroup.set(group.group_id, new Set());
        if (!compactByGroup.has(group.group_id)) {
            compactByGroup.set(group.group_id, false);
        }
        fragment.appendChild(createGroupCard(group));
    });
    mainContainer.appendChild(fragment);
}

async function loadSavedResults(reset = true) {
    if (loadingResults) return;

    loadingResults = true;
    try {
        const offset = reset ? 0 : renderedGroups;
        const targetName = currentScanMode === "nsfw" ? "nudity matches" : "duplicate groups";

        setProgressState({
            title: "Loading Saved Results",
            message: `Fetching ${targetName} (${offset.toLocaleString()} loaded)...`,
            show: true,
            indeterminate: true
        });

        const res = await fetch(`${getResultEndpoint()}?offset=${offset}&limit=${PAGE_SIZE}`);
        const payload = await res.json();

        if (payload.error) {
            statusEl.innerText = `Error loading groups: ${payload.error}`;
            setProgressState({ show: false });
            return;
        }

        const items = payload.items || [];
        totalGroups = payload.total || 0;

        if (reset) {
            renderedGroups = 0;
            if (totalGroups === 0) {
                mainContainer.innerHTML = currentScanMode === "nsfw"
                    ? `<div class="empty-state">No NSFW matches found yet. Start an NSFW scan to detect nudity and possible nudity.</div>`
                    : `<div class="empty-state">No duplicate groups found yet. Start a scan with your chosen similarity level.</div>`;
                updateResultsSummary();
                setProgressState({ show: false });
                statusEl.innerText = currentScanMode === "nsfw"
                    ? "Ready. No saved NSFW matches to display."
                    : "Ready. No saved duplicate groups to display.";
                return;
            }
        }

        setProgressState({
            title: "Rendering Results",
            message: `Rendering ${items.length.toLocaleString()} groups...`,
            current: offset + items.length,
            total: totalGroups,
            show: true,
            indeterminate: false
        });

        renderGroups(items, !reset);
        renderedGroups += items.length;

        updateResultsSummary();
        statusEl.innerText = currentScanMode === "nsfw"
            ? `Ready. Loaded ${renderedGroups.toLocaleString()} / ${totalGroups.toLocaleString()} NSFW matches.`
            : `Ready. Loaded ${renderedGroups.toLocaleString()} / ${totalGroups.toLocaleString()} groups.`;
        setProgressState({ show: false });
    } catch (e) {
        console.error(e);
        statusEl.innerText = currentScanMode === "nsfw"
            ? "Error loading NSFW matches."
            : "Error loading duplicate groups.";
        setProgressState({ show: false });
    } finally {
        loadingResults = false;
    }
}

async function startScan() {
    const threshold = parseInt(thresholdEl.value, 10);
    const global_search = globalSearchEl.checked;
    const use_cache = document.getElementById("useCache").checked;
    currentScanMode = scanModeEl.value === "nsfw" ? "nsfw" : "duplicates";

    scanBtn.disabled = true;
    scanBtn.classList.add("loading");
    statusEl.innerText = "Initializing scan...";

    setProgressState({
        title: "Scan in Progress",
        message: currentScanMode === "nsfw"
            ? "Initializing NSFW scan (nudity + possible nudity)..."
            : (global_search
                ? "Initializing global exact scan (threshold ignored)..."
                : "Initializing strict similarity scan..."),
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
            body: JSON.stringify({ threshold, global_search, use_cache, scan_mode: currentScanMode })
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
    statusEl.innerText = currentScanMode === "nsfw"
        ? "Scan complete. Review NSFW matches below."
        : "Scan complete. Review grouped results below.";

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

async function deleteSelectedInGroup(groupId) {
    const group = groupsById.get(groupId);
    if (!group) return;

    const selected = Array.from(getSelectedSet(groupId));
    if (selected.length === 0) return;

    const confirmed = confirm(`Delete ${selected.length} selected photo(s) from Flickr? This action cannot be undone.`);
    if (!confirmed) return;

    const card = document.querySelector(`.group-card[data-group-id="${groupId}"]`);
    const deleteBtn = card ? card.querySelector(".delete-selected") : null;
    if (deleteBtn) {
        deleteBtn.disabled = true;
        deleteBtn.textContent = "Deleting...";
    }

    try {
        const res = await fetch("/api/delete-batch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ photo_ids: selected })
        });
        const payload = await res.json();

        if (payload.error) {
            alert("Delete failed: " + payload.error);
            syncGroupControls(groupId);
            return;
        }

        const failed = [];
        const successIds = [];
        (payload.results || []).forEach((item) => {
            if (item.status === "ok") {
                successIds.push(item.photo_id);
            } else {
                failed.push(item);
            }
        });

        if (successIds.length > 0) {
            const nextPhotos = group.photos.filter((photo) => !successIds.includes(photo.id));
            group.photos = nextPhotos;
            sortGroupPhotosInPlace(group);
            group.size = nextPhotos.length;

            const sel = getSelectedSet(groupId);
            successIds.forEach((id) => sel.delete(id));

            if (group.photos.length < getMinimumGroupSize()) {
                groupsById.delete(groupId);
                selectedByGroup.delete(groupId);
                compactByGroup.delete(groupId);
                if (card) card.remove();
                if (lightboxState.groupId === groupId) {
                    closeLightbox();
                }
                renderedGroups = Math.max(0, renderedGroups - 1);
                totalGroups = Math.max(0, totalGroups - 1);
                updateResultsSummary();
                if (groupsById.size === 0) {
                    mainContainer.innerHTML = currentScanMode === "nsfw"
                        ? `<div class="empty-state">No NSFW matches remaining in loaded results.</div>`
                        : `<div class="empty-state">No duplicate groups remaining in loaded results.</div>`;
                }
            } else if (card) {
                const replacement = createGroupCard(group);
                card.replaceWith(replacement);
                syncGroupControls(groupId);
                if (lightboxState.groupId === groupId) {
                    const currentPhoto = getCurrentLightboxPhoto();
                    if (!currentPhoto) {
                        lightboxState.index = Math.max(0, group.photos.length - 1);
                    }
                    openLightbox(groupId, Math.min(lightboxState.index, group.photos.length - 1));
                }
            }
        }

        if (failed.length > 0) {
            const details = failed.map((f) => `${f.photo_id}: ${f.error || "Unknown error"}`).join("\n");
            alert(`Some deletions failed:\n${details}`);
        }

        statusEl.innerText = `Deleted ${successIds.length} photo(s)${failed.length ? `, ${failed.length} failed` : ""}.`;
    } catch (e) {
        console.error(e);
        alert("An error occurred while deleting selected photos.");
    } finally {
        syncGroupControls(groupId);
    }
}

async function resolveSelectedInGroup(groupId) {
    const group = groupsById.get(groupId);
    if (!group) return;

    const selected = Array.from(getSelectedSet(groupId));
    if (selected.length === 0) return;

    const confirmed = confirm(`Mark ${selected.length} selected photo(s) as resolved for this scan?`);
    if (!confirmed) return;

    const card = document.querySelector(`.group-card[data-group-id="${groupId}"]`);
    const resolveBtn = card ? card.querySelector(".resolve-selected") : null;
    if (resolveBtn) {
        resolveBtn.disabled = true;
        resolveBtn.textContent = "Resolving...";
    }

    try {
        const res = await fetch("/api/resolve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ photo_ids: selected, mode: currentScanMode })
        });
        const payload = await res.json();
        if (payload.error) {
            alert("Resolve failed: " + payload.error);
            syncGroupControls(groupId);
            return;
        }

        const nextPhotos = group.photos.filter((photo) => !selected.includes(photo.id));
        group.photos = nextPhotos;
        sortGroupPhotosInPlace(group);
        group.size = nextPhotos.length;

        const sel = getSelectedSet(groupId);
        selected.forEach((id) => sel.delete(id));

        if (group.photos.length < getMinimumGroupSize()) {
            groupsById.delete(groupId);
            selectedByGroup.delete(groupId);
            compactByGroup.delete(groupId);
            if (card) card.remove();
            if (lightboxState.groupId === groupId) {
                closeLightbox();
            }
            renderedGroups = Math.max(0, renderedGroups - 1);
            totalGroups = Math.max(0, totalGroups - 1);
            updateResultsSummary();
            if (groupsById.size === 0) {
                mainContainer.innerHTML = currentScanMode === "nsfw"
                    ? `<div class="empty-state">No NSFW matches remaining in loaded results.</div>`
                    : `<div class="empty-state">No duplicate groups remaining in loaded results.</div>`;
            }
        } else if (card) {
            const replacement = createGroupCard(group);
            card.replaceWith(replacement);
            syncGroupControls(groupId);
            if (lightboxState.groupId === groupId) {
                const currentPhoto = getCurrentLightboxPhoto();
                if (!currentPhoto) {
                    lightboxState.index = Math.max(0, group.photos.length - 1);
                }
                openLightbox(groupId, Math.min(lightboxState.index, group.photos.length - 1));
            }
        }

        statusEl.innerText = `Marked ${selected.length} photo(s) as resolved in current scan.`;
    } catch (e) {
        console.error(e);
        alert("An error occurred while resolving selected photos.");
    } finally {
        syncGroupControls(groupId);
    }
}

function openLightbox(groupId, index) {
    const group = groupsById.get(groupId);
    if (!group || !group.photos[index]) return;

    lightboxState.groupId = groupId;
    lightboxState.index = index;

    const photo = group.photos[index];
    lightboxImage.src = photo.url;
    lightboxImage.alt = photo.title || "Expanded preview";
    lightboxCaption.textContent = `${photo.title || "Untitled"} • ${formatRes(photo.width, photo.height)} • ${index + 1}/${group.photos.length}`;
    lightboxOpenOriginal.disabled = !(photo.original_url || photo.url);
    lightboxOpenOriginal.dataset.url = photo.original_url || photo.url;
    lightboxOriginalInfo.textContent = `Original: ${formatRes(photo.original_width, photo.original_height)} • Size: loading...`;
    loadOriginalInfo(photo);
    syncLightboxSelection();

    lightboxModal.classList.remove("hidden");
    lightboxModal.setAttribute("aria-hidden", "false");
}

function closeLightbox() {
    lightboxModal.classList.add("hidden");
    lightboxModal.setAttribute("aria-hidden", "true");
    lightboxImage.src = "";
    lightboxOpenOriginal.dataset.url = "";
    lightboxOriginalInfo.textContent = "";
    lightboxState.groupId = null;
    lightboxState.index = 0;
}

function navigateLightbox(step) {
    const group = groupsById.get(lightboxState.groupId);
    if (!group || group.photos.length === 0) return;

    const nextIndex = (lightboxState.index + step + group.photos.length) % group.photos.length;
    openLightbox(lightboxState.groupId, nextIndex);
}

function getCurrentLightboxPhoto() {
    const group = groupsById.get(lightboxState.groupId);
    if (!group) return null;
    return group.photos[lightboxState.index] || null;
}

function syncLightboxSelection() {
    const photo = getCurrentLightboxPhoto();
    if (!photo || !lightboxState.groupId) {
        lightboxSelect.checked = false;
        lightboxSelectLabel.textContent = "Select this photo";
        return;
    }

    const selected = getSelectedSet(lightboxState.groupId);
    lightboxSelect.checked = selected.has(photo.id);
    lightboxSelectLabel.textContent = `Select this photo (ID ${photo.id})`;
}

async function loadOriginalInfo(photo) {
    if (!photo || !photo.id) return;
    if (originalInfoCache.has(photo.id)) {
        const cached = originalInfoCache.get(photo.id);
        if (cached.original_url) {
            photo.original_url = cached.original_url;
        }
        if (cached.original_width) {
            photo.original_width = cached.original_width;
        }
        if (cached.original_height) {
            photo.original_height = cached.original_height;
        }
        if (
            lightboxState.groupId &&
            getCurrentLightboxPhoto() &&
            getCurrentLightboxPhoto().id === photo.id
        ) {
            lightboxOpenOriginal.disabled = !(photo.original_url || photo.url);
            lightboxOpenOriginal.dataset.url = photo.original_url || photo.url;
        }
        lightboxOriginalInfo.textContent = `Original: ${formatRes(cached.original_width, cached.original_height)} • ${formatBytes(cached.original_size_bytes)}`;
        return;
    }

    lightboxOriginalInfo.textContent = "Loading original file size...";
    try {
        const res = await fetch(`/api/photo-original-info/${encodeURIComponent(photo.id)}`);
        const payload = await res.json();
        if (payload.error) {
            lightboxOriginalInfo.textContent = "Original file size unavailable.";
            return;
        }
        originalInfoCache.set(photo.id, payload);
        if (payload.original_url) {
            photo.original_url = payload.original_url;
        }
        if (payload.original_width) {
            photo.original_width = payload.original_width;
        }
        if (payload.original_height) {
            photo.original_height = payload.original_height;
        }
        if (
            lightboxState.groupId &&
            getCurrentLightboxPhoto() &&
            getCurrentLightboxPhoto().id === photo.id
        ) {
            lightboxOpenOriginal.disabled = !(photo.original_url || photo.url);
            lightboxOpenOriginal.dataset.url = photo.original_url || photo.url;
        }
        lightboxOriginalInfo.textContent = `Original: ${formatRes(payload.original_width, payload.original_height)} • ${formatBytes(payload.original_size_bytes)}`;
    } catch (e) {
        console.error(e);
        lightboxOriginalInfo.textContent = "Original file size unavailable.";
    }
}

function loadMoreResults() {
    loadSavedResults(false);
}

function syncScanModeUi() {
    currentScanMode = scanModeEl.value === "nsfw" ? "nsfw" : "duplicates";
    const nsfwMode = currentScanMode === "nsfw";
    thresholdEl.disabled = nsfwMode;
    globalSearchEl.disabled = nsfwMode;
    if (nsfwMode) {
        globalSearchEl.checked = false;
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

mainContainer.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    if (target.classList.contains("photo-check")) {
        const groupId = target.dataset.groupId;
        const photoId = target.dataset.photoId;
        const selected = getSelectedSet(groupId);
        if (target.checked) {
            selected.add(photoId);
        } else {
            selected.delete(photoId);
        }
        syncGroupControls(groupId);
        if (lightboxState.groupId === groupId) {
            syncLightboxSelection();
        }
        return;
    }

    if (target.classList.contains("select-all")) {
        const groupId = target.dataset.groupId;
        const group = groupsById.get(groupId);
        if (!group) return;

        const selected = getSelectedSet(groupId);
        selected.clear();
        if (target.checked) {
            group.photos.forEach((p) => selected.add(p.id));
        }
        syncGroupControls(groupId);
        if (lightboxState.groupId === groupId) {
            syncLightboxSelection();
        }
    }
});

mainContainer.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const lightboxBtn = target.closest('[data-action="open-lightbox"]');
    if (lightboxBtn) {
        openLightbox(lightboxBtn.dataset.groupId, Number(lightboxBtn.dataset.photoIndex));
        return;
    }

    const deleteBtn = target.closest(".delete-selected");
    if (deleteBtn) {
        deleteSelectedInGroup(deleteBtn.dataset.groupId);
        return;
    }

    const resolveBtn = target.closest(".resolve-selected");
    if (resolveBtn) {
        resolveSelectedInGroup(resolveBtn.dataset.groupId);
        return;
    }

    const compactBtn = target.closest(".toggle-compact");
    if (compactBtn) {
        const groupId = compactBtn.dataset.groupId;
        const isCompact = compactByGroup.get(groupId) === true;
        compactByGroup.set(groupId, !isCompact);
        const card = compactBtn.closest(".group-card");
        if (card) {
            card.classList.toggle("compact", !isCompact);
        }
        compactBtn.textContent = !isCompact ? "Expand" : "Compact";
    }
});

lightboxClose.addEventListener("click", closeLightbox);
lightboxOverlay.addEventListener("click", closeLightbox);
lightboxPrev.addEventListener("click", () => navigateLightbox(-1));
lightboxNext.addEventListener("click", () => navigateLightbox(1));
lightboxOpenOriginal.addEventListener("click", () => {
    const url = lightboxOpenOriginal.dataset.url;
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
});
lightboxSelect.addEventListener("change", () => {
    const photo = getCurrentLightboxPhoto();
    const groupId = lightboxState.groupId;
    if (!photo || !groupId) return;

    const selected = getSelectedSet(groupId);
    if (lightboxSelect.checked) {
        selected.add(photo.id);
    } else {
        selected.delete(photo.id);
    }
    syncGroupControls(groupId);
    syncLightboxSelection();
});

document.addEventListener("keydown", (event) => {
    if (lightboxModal.classList.contains("hidden")) return;
    if (event.key === "Escape") {
        closeLightbox();
    } else if (event.key === "ArrowRight") {
        navigateLightbox(1);
    } else if (event.key === "ArrowLeft") {
        navigateLightbox(-1);
    } else if (event.key.toLowerCase() === " ") {
        lightboxSelect.click();
        event.preventDefault();
    }
});

checkInitialStatus();

scanModeEl.addEventListener("change", () => {
    syncScanModeUi();
    loadSavedResults(true);
});

syncScanModeUi();
