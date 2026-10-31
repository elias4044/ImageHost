const select = (value) => document.querySelector(value);
const formatCount = (value) => new Intl.NumberFormat("en").format(value);
const formatBytes = (value) => {
  if (value < 1024) return `${value} B`;
  const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 3);
  return `${(value / 1024 ** unit).toFixed(1)} ${["B", "KiB", "MiB", "GiB"][unit]}`;
};
const formatDate = (value) =>
  new Date(value * 1000).toLocaleString("en", {
    dateStyle: "medium",
    timeStyle: "short",
  });
const stateNames = {
  pending: "Queued",
  scanning: "Scanning",
  ready: "Approved",
  blocked: "Blocked",
  scan_error: "Scanner error",
  expired: "Expired",
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
  });
  if (response.status === 401 && !path.includes("/auth/login")) {
    location.assign("/login");
    throw new Error("Your session expired. Sign in again.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(
      data?.error?.message || `Request failed (${response.status})`,
    );
  }
  return response.status === 204 ? null : response.json();
}

function showError(error) {
  const box = select("#page-error");
  if (box) {
    box.textContent = error.message;
    box.hidden = false;
  }
}

let toastTimer;
function toast(message) {
  const box = select("#toast");
  if (!box) return;
  clearTimeout(toastTimer);
  box.textContent = message;
  box.hidden = false;
  toastTimer = setTimeout(() => {
    box.hidden = true;
  }, 5000);
}

function action(label, handler) {
  const button = element("button", "", label);
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await handler();
    } catch (error) {
      showError(error);
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

let pendingConfirmation;
function confirmAction(title, description, handler) {
  select("#confirm-title").textContent = title;
  select("#confirm-description").textContent = description;
  pendingConfirmation = handler;
  select("#confirm-dialog").showModal();
}

select("#confirm-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const handler = pendingConfirmation;
  pendingConfirmation = null;
  select("#confirm-dialog").close();
  try {
    await handler();
  } catch (error) {
    showError(error);
  }
});

document.querySelectorAll(".close-dialog").forEach((button) => {
  button.addEventListener("click", () => {
    const dialog = button.closest("dialog");
    if (dialog.id === "secret-dialog") select("#new-secret").value = "";
    dialog.close();
  });
});
select("#secret-dialog")?.addEventListener("cancel", () => {
  select("#new-secret").value = "";
});
select("#secret-dialog")?.addEventListener("close", () => {
  select("#new-secret").value = "";
});
select("#menu-toggle")?.addEventListener("click", (event) => {
  const open = select("#navigation").classList.toggle("open");
  event.currentTarget.setAttribute("aria-expanded", String(open));
});
select("#logout")?.addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST" });
    location.assign("/login");
  } catch (error) {
    showError(error);
  }
});

select("#login-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  const message = event.currentTarget.querySelector(".form-message");
  button.disabled = true;
  message.textContent = "";
  try {
    await api("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: select("#password").value }),
    });
    location.assign("/");
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

let imageOffset = 0;
let imageTotal = 0;
let lastHistory = [];
const page = select("[data-page]")?.dataset.page;

function drawActivity(history) {
  const chart = select("#upload-chart");
  if (!chart) return;
  chart.replaceChildren();
  const max = Math.max(1, ...history.map((day) => day.uploads));
  const step = Math.max(1, Math.ceil(max / 3));
  const top = (Math.floor(max / step) + 1) * step;
  const ticks = Array.from(
    { length: top / step + 1 },
    (_, index) => index * step,
  );
  Charts.line(chart, {
    labels: history.map((day) =>
      new Date(`${day.day}T12:00:00Z`).toLocaleDateString("en", {
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      }),
    ),
    series: [
      {
        name: "Uploads",
        values: history.map((day) => day.uploads),
        colour: "#1b6c80",
      },
    ],
    yTicks: ticks,
    format: formatCount,
    tickFormat: formatCount,
    xAt: [0, 4, 8, 12],
  });
}

async function refreshStats() {
  const [stats, system] = await Promise.all([
    api("/api/v1/stats"),
    api("/api/v1/system"),
  ]);
  if (!select("#finding")) return;
  const quarantine = (stats.states.pending || 0) + (stats.states.scanning || 0);
  const errors = stats.states.scan_error || 0;
  const missing = Object.entries(system.scanners)
    .filter(([name, configured]) => !configured && system.requiredScanners.includes(name))
    .map(([name]) => name);
  select("#finding").textContent = missing.length
    ? `Setup required: configure ${missing.join(" and ")} screening. Uploads remain private.`
    : errors
      ? `${errors} image(s) need a scanner retry. Unapproved images remain private.`
      : `${formatCount(stats.states.ready || 0)} approved images. ${formatCount(quarantine)} awaiting a verdict.`;
  if (!select("#count-ready")) return;
  select("#count-quarantine").textContent = formatCount(quarantine);
  select("#count-ready").textContent = formatCount(stats.states.ready || 0);
  select("#count-blocked").textContent = formatCount(stats.states.blocked || 0);
  select("#count-errors").textContent = formatCount(errors);
  select("#stat-views").textContent = formatCount(stats.views14d);
  select("#stat-bandwidth").textContent = formatBytes(stats.bytes14d);
  select("#stat-storage").textContent = formatBytes(stats.storage);
  select("#storage-progress").value = Math.min(
    100,
    (stats.storage / stats.storageLimit) * 100,
  );
  select("#storage-limit").textContent =
    `${formatBytes(stats.storage)} of ${formatBytes(stats.storageLimit)} capacity`;
  lastHistory = stats.history;
  await document.fonts.ready;
  drawActivity(lastHistory);
}

function imageRow(image) {
  const row = element("article", "image-row");
  const identity = element("div", "image-identity");
  if (image.state === "ready") {
    const thumbnail = element("img");
    thumbnail.src = `/api/v1/images/${image.id}/content`;
    thumbnail.alt = "";
    thumbnail.loading = "lazy";
    identity.append(thumbnail);
  } else identity.append(element("span", "private-image-mark", "Private"));
  const description = element("div", "image-description");
  const name = element("span", "image-name", image.name);
  name.title = image.name;
  description.append(
    name,
    element("span", "image-subline", formatDate(image.created)),
  );
  identity.append(description);
  const state = element("div", "row-state");
  state.append(
    element("span", `state-pill state-${image.state}`, stateNames[image.state]),
  );
  if (image.state === "scan_error") {
    const reasons = {
      scanner_configuration: "Scanner setup changed. Retry this image.",
      nsfw_not_configured: "Install the local scanner dependencies.",
      nsfw_local_failed: "Local model could not run. Check dependencies.",
      nsfw_local_timeout: "Local scan timed out. Retry this image.",
      nsfw_local_unavailable: "Local scanner could not start.",
      nsfw_service_unavailable: "Scanner service is not reachable.",
      nsfw_auth_failed: "Scanner credentials do not match.",
      nsfw_response: "Scanner returned an invalid result.",
      antivirus_unavailable: "ClamAV is not reachable.",
      specialist_unavailable: "Optional specialist service is unavailable.",
      specialist_review: "Optional specialist check is undecided.",
      storage_unavailable: "Stored image could not be read.",
    };
    state.append(element("span", "row-meta", reasons[image.reason] || "Scan failed. Retry or check the server log."));
  }
  const size = element("div", "number", formatBytes(image.size));
  size.append(element("span", "row-meta", `${image.width} x ${image.height}`));
  const access = element(
    "span",
    "row-access",
    image.public ? "Public" : "Private",
  );
  const actions = element("div", "row-actions");
  if (image.url)
    actions.append(
      action("Copy URL", async () => {
        await navigator.clipboard.writeText(image.url);
        toast("Image URL copied");
      }),
    );
  if (image.state === "scan_error")
    actions.append(
      action("Retry", async () => {
        await api(`/api/v1/images/${image.id}/retry`, { method: "POST" });
        await loadImages();
        await refreshStats();
        toast("Image queued for another scan");
      }),
    );
  actions.append(
    action("Delete", () =>
      confirmAction(
        "Delete this image?",
        `Remove ${image.name} and its stored bytes. Its delivery URL will stop working.`,
        async () => {
          await api(`/api/v1/images/${image.id}`, { method: "DELETE" });
          await loadImages();
          await refreshStats();
          toast("Image deleted");
        },
      ),
    ),
  );
  row.append(identity, state, size, access, actions);
  return row;
}

let imageRequestVersion = 0;
async function loadImages(append = false) {
  const version = ++imageRequestVersion;
  const offset = append ? imageOffset : 0;
  const query = new URLSearchParams({
    limit: page === "/" ? "5" : "25",
    offset: String(offset),
    search: select("#image-search").value,
  });
  if (select("#image-state").value)
    query.set("state", select("#image-state").value);
  const data = await api(`/api/v1/images?${query}`);
  if (version !== imageRequestVersion) return;
  const rows = select("#image-rows");
  if (!append) rows.replaceChildren();
  if (!data.total)
    rows.append(
      element(
        "p",
        "empty-state",
        select("#image-search").value || select("#image-state").value
          ? "No images match these filters."
          : "Your library is ready. Upload an image or connect an application with an API key.",
      ),
    );
  for (const image of data.images) rows.append(imageRow(image));
  imageOffset = offset + data.images.length;
  imageTotal = data.total;
  if (select("#image-total"))
    select("#image-total").textContent = `${formatCount(imageTotal)} ${imageTotal === 1 ? "image" : "images"}`;
  select("#load-more").hidden = page === "/" || imageOffset >= imageTotal;
}

select("#open-upload")?.addEventListener("click", () =>
  select("#upload-dialog").showModal(),
);
select("#upload-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const message = form.querySelector(".form-message");
  button.disabled = true;
  message.textContent = "Uploading to quarantine...";
  const data = new FormData(form);
  data.set("public", String(form.elements.public.checked));
  try {
    await api("/api/v1/images", { method: "POST", body: data });
    select("#upload-dialog").close();
    form.reset();
    message.textContent = "";
    await Promise.all([loadImages(), refreshStats()]);
    toast("Uploaded. Screening must finish before delivery.");
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
select("#refresh-images")?.addEventListener("click", () =>
  Promise.all([loadImages(), refreshStats()]).catch(showError),
);
select("#load-more")?.addEventListener("click", () =>
  loadImages(true).catch(showError),
);
select("#image-state")?.addEventListener("change", () =>
  loadImages().catch(showError),
);
let searchTimer;
select("#image-search")?.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadImages().catch(showError), 250);
});
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (lastHistory.length) drawActivity(lastHistory);
  }, 100);
});

async function loadKeys() {
  const keys = await api("/api/v1/keys");
  const rows = select("#key-rows");
  rows.replaceChildren();
  if (!keys.length)
    rows.append(
      element(
        "p",
        "empty-state",
        "No application keys yet. Create a key to connect your first application.",
      ),
    );
  for (const key of keys) {
    const row = element("article", "key-row");
    const identity = element("div");
    identity.append(
      element("strong", "", key.name),
      element("code", "", `${key.prefix}...`),
    );
    const expired = key.expires * 1000 <= Date.now();
    row.append(
      identity,
      element("div", "scope-list", JSON.parse(key.scopes).join(", ")),
      element(
        "span",
        "",
        key.revoked
          ? "Revoked"
          : expired
            ? "Expired"
            : `Expires ${new Date(key.expires * 1000).toISOString().slice(0, 10)}`,
      ),
    );
    if (!key.revoked)
      row.append(
        action("Revoke", () =>
          confirmAction(
            "Revoke this key?",
            `${key.name} will lose API access. Existing approved public images remain public.`,
            async () => {
              await api(`/api/v1/keys/${key.id}`, { method: "DELETE" });
              await loadKeys();
              toast("API key revoked");
            },
          ),
        ),
      );
    rows.append(row);
  }
}
select("#open-key")?.addEventListener("click", () =>
  select("#key-dialog").showModal(),
);
select("#refresh-keys")?.addEventListener("click", () =>
  loadKeys().catch(showError),
);
select("#key-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const message = form.querySelector(".form-message");
  const scopes = data.getAll("scope");
  if (!scopes.length) {
    message.textContent = "Choose at least one permission.";
    return;
  }
  const button = form.querySelector("[type=submit]");
  button.disabled = true;
  try {
    const result = await api("/api/v1/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: data.get("name"),
        expiresInDays: Number(data.get("expiresInDays")),
        scopes,
      }),
    });
    select("#key-dialog").close();
    form.reset();
    message.textContent = "";
    select("#new-secret").value = result.key;
    select("#copy-status").textContent = "";
    select("#secret-dialog").showModal();
    await loadKeys();
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
select("#copy-secret")?.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(select("#new-secret").value);
    select("#copy-status").textContent =
      "Copied. Save it before closing this window.";
  } catch {
    select("#copy-status").textContent =
      "Select the key above and copy it manually.";
  }
});

async function loadSafety() {
  const [system, events] = await Promise.all([
    api("/api/v1/system"),
    api("/api/v1/audit"),
  ]);
  const rows = select("#scanner-rows");
  rows.replaceChildren();
  const scanners = {
    antivirus: ["ClamAV", "Malware signatures / original and rebuilt bytes"],
    nsfw: ["NudeNet (local)", `Exposed nudity detection / ${system.nsfwBackend === "local" ? "local Python process" : "private scanner service"}`],
    specialist: [
      "Specialist safety adapter",
      "Illegal-content screening / original file",
    ],
  };
  for (const [id, [name, description]] of Object.entries(scanners)) {
    const required = system.requiredScanners.includes(id);
    const row = element("div", "scanner-row");
    const label = element("div");
    label.append(element("strong", "", name), element("p", "", description));
    row.append(
      label,
      element(
        "span",
        `state-pill ${!system.scanners[id] && required ? "state-scan_error" : ""}`,
        system.scanners[id] ? "Configured" : required ? "Setup required" : "Optional / off",
      ),
    );
    rows.append(row);
  }
  const workerRow = element("div", "scanner-row");
  workerRow.append(
    element("span", "", "Background scan worker"),
    element("span", "state-pill", system.workerAlive ? "Running" : "Stopped"),
  );
  rows.append(workerRow);
  const auditRows = select("#audit-rows");
  auditRows.replaceChildren();
  if (!events.length)
    auditRows.append(
      element("p", "empty-state", "No audit events recorded yet."),
    );
  for (const entry of events) {
    const row = element("article", "audit-row");
    const detail = element("div", "", entry.action);
    detail.append(element("code", "", entry.target));
    row.append(
      element("time", "", formatDate(entry.created)),
      detail,
      element(
        "small",
        "",
        entry.actor === "admin" || entry.actor === "scanner"
          ? entry.actor
          : "API key",
      ),
    );
    auditRows.append(row);
  }
}
select("#refresh-safety")?.addEventListener("click", () =>
  loadSafety().catch(showError),
);

async function initialize() {
  if (page === "/" || page === "/images")
    await Promise.all([loadImages(), refreshStats()]);
  if (page === "/keys") await loadKeys();
  if (page === "/safety") await loadSafety();
}
initialize().catch(showError);
