let currentRole = null;

function encodePath(path) {
    // Encode chaque segment separement (pas la chaine entiere, qui
    // encoderait aussi les "/" et casserait le routage cote serveur).
    return path.split("/").map(encodeURIComponent).join("/");
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function statusBadge(status) {
    if (status === "ok") return '<span class="badge badge-ok">ok</span>';
    if (status === "failed") return '<span class="badge badge-error">echec</span>';
    return '<span class="badge badge-pending">en cours</span>';
}

function formatDate(iso) {
    if (!iso) return "-";
    return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium" });
}

async function loadRoles() {
    const list = document.getElementById("roles-list");
    const tagsPanel = document.getElementById("tags-panel");
    const tagsList = document.getElementById("tags-list");
    const errorPanel = document.getElementById("bastion-error-panel");
    const errorText = document.getElementById("bastion-error-text");
    const runLimit = document.getElementById("run-limit");

    try {
        const res = await fetch("/api/roles");
        const data = await res.json();
        const roles = data.roles || [];
        const missingTags = data.missing_tags || [];

        if (data.bastion_error) {
            errorPanel.hidden = false;
            errorText.textContent = data.bastion_error;
        } else {
            errorPanel.hidden = true;
        }

        if (!roles.length) {
            list.innerHTML = '<p class="empty">Aucun role</p>';
        } else {
            list.innerHTML = `<div class="card-list">${roles.map(r => `
                <div class="card">
                    <div class="card-title">${escapeHtml(r)}</div>
                    <div class="card-actions">
                        <button class="secondary" data-edit-role="${escapeHtml(r)}">Modifier</button>
                    </div>
                </div>
            `).join("")}</div>`;
            list.querySelectorAll("button[data-edit-role]").forEach(btn => {
                btn.addEventListener("click", () => openRoleEditor(btn.dataset.editRole));
            });
        }

        if (missingTags.length) {
            tagsPanel.hidden = false;
            tagsList.innerHTML = `<div class="card-list">${missingTags.map(t => `
                <div class="card">
                    <div class="card-title">${escapeHtml(t)}</div>
                    <div class="card-actions">
                        <button class="secondary" data-scaffold-tag="${escapeHtml(t)}">Scaffolder</button>
                    </div>
                </div>
            `).join("")}</div>`;
            tagsList.querySelectorAll("button[data-scaffold-tag]").forEach(btn => {
                btn.addEventListener("click", () => scaffoldTag(btn.dataset.scaffoldTag));
            });
        } else {
            tagsPanel.hidden = true;
        }

        const currentValue = runLimit.value;
        runLimit.innerHTML = '<option value="">Tout le parc</option>' +
            roles.map(r => `<option value="${escapeHtml(r)}">${escapeHtml(r)}</option>`).join("");
        runLimit.value = currentValue;
    } catch (e) {
        list.innerHTML = '<p class="status-error">Erreur de chargement</p>';
    }
}

async function scaffoldTag(tag) {
    const res = await fetch(`/api/roles/${encodeURIComponent(tag)}/scaffold`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
        alert(data.error || "Erreur");
        return;
    }
    loadRoles();
    loadOrder();
}

let currentFilePath = null;

async function openRoleEditor(role) {
    currentRole = role;
    currentFilePath = null;
    document.getElementById("role-file-editor").hidden = true;
    const panel = document.getElementById("role-editor-panel");
    const title = document.getElementById("role-editor-title");
    const status = document.getElementById("role-editor-status");
    status.hidden = true;
    title.textContent = `Modifier '${role}'`;

    await loadRoleFilesList();
    panel.hidden = false;
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadRoleFilesList() {
    const list = document.getElementById("role-files-list");
    const res = await fetch(`/api/roles/${encodeURIComponent(currentRole)}/files`);
    const data = await res.json();
    if (!res.ok) {
        alert(data.error || "Erreur de chargement du role");
        return;
    }
    const files = data.files || [];
    if (!files.length) {
        list.innerHTML = '<p class="empty">Aucun fichier</p>';
        return;
    }
    list.innerHTML = files.map(path => `
        <div class="card">
            <div class="card-title"><code>${escapeHtml(path)}</code></div>
            <div class="card-actions">
                <button class="secondary" data-open-file="${escapeHtml(path)}">Ouvrir</button>
            </div>
        </div>
    `).join("");
    list.querySelectorAll("button[data-open-file]").forEach(btn => {
        btn.addEventListener("click", () => openRoleFile(btn.dataset.openFile));
    });
}

async function openRoleFile(path) {
    const res = await fetch(`/api/roles/${encodeURIComponent(currentRole)}/file/${encodePath(path)}`);
    const data = await res.json();
    if (!res.ok) {
        alert(data.error || "Erreur de chargement du fichier");
        return;
    }
    currentFilePath = path;
    document.getElementById("role-file-editor-label").textContent = path;
    document.getElementById("role-file-editor-content").value = data.content;
    document.getElementById("role-file-editor").hidden = false;
    document.getElementById("role-editor-status").hidden = true;
}

document.getElementById("role-editor-close").addEventListener("click", () => {
    document.getElementById("role-editor-panel").hidden = true;
    currentRole = null;
    currentFilePath = null;
});

document.getElementById("role-new-file-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("role-new-file-path");
    const path = input.value.trim().replace(/^\/+/, "");
    if (!path) return;

    const res = await fetch(`/api/roles/${encodeURIComponent(currentRole)}/file/${encodePath(path)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: "" }),
    });
    const data = await res.json();
    if (!res.ok) {
        alert(data.error || "Erreur");
        return;
    }
    input.value = "";
    await loadRoleFilesList();
    openRoleFile(path);
});

document.getElementById("role-file-save-btn").addEventListener("click", async () => {
    if (!currentRole || !currentFilePath) return;
    const btn = document.getElementById("role-file-save-btn");
    const status = document.getElementById("role-editor-status");
    btn.disabled = true;
    status.hidden = true;

    const content = document.getElementById("role-file-editor-content").value;
    const res = await fetch(`/api/roles/${encodeURIComponent(currentRole)}/file/${encodePath(currentFilePath)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
    });
    const data = await res.json();

    status.hidden = false;
    if (!res.ok) {
        status.className = "status status-error";
        status.textContent = data.error || "Erreur";
    } else {
        status.className = "status status-ok";
        status.textContent = "Enregistre.";
    }
    btn.disabled = false;
});

document.getElementById("role-file-delete-btn").addEventListener("click", async () => {
    if (!currentRole || !currentFilePath) return;
    if (!confirm(`Supprimer '${currentFilePath}' ?`)) return;

    const res = await fetch(`/api/roles/${encodeURIComponent(currentRole)}/file/${encodePath(currentFilePath)}`, {
        method: "DELETE",
    });
    const data = await res.json();
    if (!res.ok) {
        alert(data.error || "Erreur");
        return;
    }
    currentFilePath = null;
    document.getElementById("role-file-editor").hidden = true;
    await loadRoleFilesList();
});

async function loadOrder() {
    const list = document.getElementById("order-list");
    try {
        const res = await fetch("/api/order");
        const data = await res.json();
        renderOrder(data.order || []);
    } catch (e) {
        list.innerHTML = '<p class="status-error">Erreur de chargement</p>';
    }
}

function renderOrder(order) {
    const list = document.getElementById("order-list");
    if (!order.length) {
        list.innerHTML = '<p class="empty">Aucun role</p>';
        return;
    }
    list.innerHTML = `<div class="card-list">${order.map((role, i) => `
        <div class="card">
            <div class="card-title">
                <span class="order-position">${i + 1}</span>
                ${escapeHtml(role)}
            </div>
            <div class="card-actions">
                <button class="secondary" data-move-up="${i}" ${i === 0 ? "disabled" : ""}>Monter</button>
                <button class="secondary" data-move-down="${i}" ${i === order.length - 1 ? "disabled" : ""}>Descendre</button>
            </div>
        </div>
    `).join("")}</div>`;
    list.querySelectorAll("button[data-move-up]").forEach(btn => {
        btn.addEventListener("click", () => moveOrder(order, parseInt(btn.dataset.moveUp, 10), -1));
    });
    list.querySelectorAll("button[data-move-down]").forEach(btn => {
        btn.addEventListener("click", () => moveOrder(order, parseInt(btn.dataset.moveDown, 10), 1));
    });
}

async function moveOrder(order, index, direction) {
    const newOrder = order.slice();
    const target = index + direction;
    [newOrder[index], newOrder[target]] = [newOrder[target], newOrder[index]];

    const status = document.getElementById("order-status");
    const res = await fetch("/api/order", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order: newOrder }),
    });
    const data = await res.json();
    status.hidden = false;
    if (!res.ok) {
        status.className = "status status-error";
        status.textContent = data.error || "Erreur";
        return;
    }
    status.className = "status status-ok";
    status.textContent = "Ordre mis a jour.";
    renderOrder(newOrder);
}

async function loadRuns() {
    const list = document.getElementById("runs-list");
    try {
        const res = await fetch("/api/runs");
        const data = await res.json();
        const runs = data.runs || [];
        if (!runs.length) {
            list.innerHTML = '<p class="empty">Aucun run</p>';
            return;
        }
        list.innerHTML = `<div class="card-list">${runs.map(r => `
            <div class="card">
                <div class="card-title">
                    ${escapeHtml(r.limit || "Tout le parc")}
                    ${statusBadge(r.status)}
                </div>
                <div class="card-meta">
                    <span>Demarre : ${formatDate(r.started_at)}</span>
                    <span>Termine : ${formatDate(r.finished_at)}</span>
                </div>
                <div class="card-actions">
                    <button class="secondary" data-log="${escapeHtml(r.id)}">Voir le log</button>
                </div>
            </div>
        `).join("")}</div>`;
        list.querySelectorAll("button[data-log]").forEach(btn => {
            btn.addEventListener("click", () => showLog(btn.dataset.log));
        });
    } catch (e) {
        list.innerHTML = '<p class="status-error">Erreur de chargement</p>';
    }
}

async function showLog(runId) {
    const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/log`);
    const data = await res.json();
    document.getElementById("log-title").textContent = `Log - ${runId}`;
    document.getElementById("log-content").textContent = data.log || data.error || "";
    document.getElementById("log-panel").hidden = false;
    document.getElementById("log-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

document.getElementById("log-close").addEventListener("click", () => {
    document.getElementById("log-panel").hidden = true;
});

document.getElementById("run-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("run-btn");
    const status = document.getElementById("run-status");
    const limit = document.getElementById("run-limit").value;
    btn.disabled = true;
    status.hidden = true;

    try {
        const res = await fetch("/api/runs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ limit: limit || null }),
        });
        const data = await res.json();
        status.hidden = false;
        if (!res.ok) {
            status.className = "status status-error";
            status.textContent = data.error || "Erreur";
        } else {
            status.className = "status status-ok";
            status.textContent = `Run '${data.id}' lance.`;
            loadRuns();
        }
    } catch (e) {
        status.hidden = false;
        status.className = "status status-error";
        status.textContent = "Erreur reseau";
    } finally {
        btn.disabled = false;
    }
});

loadRoles();
loadOrder();
loadRuns();
