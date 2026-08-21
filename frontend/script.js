(function (root, factory) {
	const api = factory();
	if (typeof module !== "undefined" && module.exports) {
		module.exports = api;
	}
	if (typeof root !== "undefined") {
		root.OrchestratorFrontend = api;
	}
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
	function resolveEndpoints(locationLike = {}, overrides = {}) {
		const protocol = (locationLike.protocol || "http:").toLowerCase();
		const hostname = locationLike.hostname || "localhost";
		const isSecure = protocol === "https:";
		const wsScheme = overrides.wsScheme || (isSecure ? "wss:" : "ws:");
		const apiScheme = overrides.apiScheme || (isSecure ? "https:" : "http:");
		const wsPort = overrides.wsPort != null ? overrides.wsPort : 8080;
		const apiPort = overrides.apiPort != null ? overrides.apiPort : 8090;
		const wsHost = overrides.wsHost || hostname;
		const apiHost = overrides.apiHost || hostname;
		const wsPath = overrides.wsPath || "";
		const apiBase =
			overrides.apiBase ||
			`${apiScheme}//${apiHost}${apiPort ? `:${apiPort}` : ""}`;
		const wsUrl =
			overrides.wsUrl ||
			`${wsScheme}//${wsHost}${wsPort ? `:${wsPort}` : ""}${wsPath}`;
		return { wsUrl, apiBase, writeToken: overrides.writeToken || null };
	}

	function parseInputValue(type, raw) {
		const value = (raw || "").trim();
		if (!value) return null;

		if (type === "std_msgs/Int32" || type === "std_msgs/Int64" || type === "std_msgs/UInt32" || type === "std_msgs/UInt64") {
			if (!/^-?\d+$/.test(value)) {
				throw new Error(`Invalid integer for ${type}`);
			}
			const parsed = Number(value);
			if (!Number.isFinite(parsed)) {
				throw new Error(`Invalid integer for ${type}`);
			}
			return parsed;
		}

		if (type === "std_msgs/Float32" || type === "std_msgs/Float64") {
			const parsed = Number(value);
			if (!Number.isFinite(parsed)) {
				throw new Error(`Invalid float for ${type}`);
			}
			return parsed;
		}

		if (type === "std_msgs/Bool") {
			if (/^(true|1)$/i.test(value)) return true;
			if (/^(false|0)$/i.test(value)) return false;
			throw new Error("Invalid boolean (use true/false or 1/0)");
		}

		if (type === "std_msgs/Char") {
			if (value.length !== 1) throw new Error("Char must be a single character");
			return value;
		}

		if (type.startsWith("std_msgs/")) {
			return value;
		}

		if (value.startsWith("{") || value.startsWith("[")) {
			return JSON.parse(value);
		}
		return value;
	}

	return {
		resolveEndpoints,
		parseInputValue,
	};
});

if (typeof document !== "undefined") {
document.addEventListener("DOMContentLoaded", () => {
	if (!window.ROSClient || !window.ROSClient.Client) {
		console.error("ROSClient.Client is not available. Check that clientjs/Client.js is loaded.");
		return;
	}

	const helpers = window.OrchestratorFrontend || {};
	const resolveEndpoints = helpers.resolveEndpoints || ((loc) => ({
		wsUrl: `ws://${loc.hostname || "localhost"}:8080`,
		apiBase: `http://${loc.hostname || "localhost"}:8090`,
		writeToken: null,
	}));
	const parseInputValue = helpers.parseInputValue;

	const { Client } = window.ROSClient;
	const topics = new Map();
	const overrides = window.ORCHESTRATOR_CONFIG || {};
	const endpoints = resolveEndpoints(window.location, overrides);

	const container = document.createElement("div");
	container.className = "container py-4";
	container.innerHTML = `
		<h1 class="mb-4">Topic Monitor</h1>
		<div class="mb-3 d-flex gap-2 flex-wrap">
			<button id="btn-connect" class="btn btn-primary">Connect</button>
			<button id="btn-echo" class="btn btn-outline-secondary">Load Topics</button>
			<button id="btn-request-all" class="btn btn-outline-secondary">Request All Values</button>
			<span id="connection-status" class="align-self-center text-muted">Disconnected</span>
		</div>

		<div class="row g-4">
			<div class="col-md-7">
				<h2 class="h5 mb-3">Active Topics</h2>
				<div class="table-responsive">
					<table class="table table-sm table-striped align-middle mb-0">
						<thead class="table-light">
							<tr>
								<th scope="col">Name</th>
								<th scope="col">Type</th>
								<th scope="col">Last Value</th>
								<th scope="col">Updated</th>
							</tr>
						</thead>
						<tbody id="topics-body"></tbody>
					</table>
				</div>
			</div>

			<div class="col-md-5">
				<h2 class="h5 mb-3">Publish</h2>
				<form id="publish-form" class="card card-body">
					<div class="mb-3">
						<label for="topic-name" class="form-label">Topic</label>
						<input list="topic-list" id="topic-name" class="form-control" placeholder="/example/topic" required />
						<datalist id="topic-list"></datalist>
					</div>
					<div class="mb-3">
						<label for="topic-type" class="form-label">Type</label>
						<input id="topic-type" class="form-control" list="type-list" value="std_msgs/String" required />
						<datalist id="type-list">
							<option value="std_msgs/String"></option>
							<option value="std_msgs/Int32"></option>
							<option value="std_msgs/Float32"></option>
							<option value="std_msgs/Bool"></option>
						</datalist>
						<div class="form-text">Existing topics keep their current type. Custom types are supported.</div>
					</div>
					<div class="mb-3">
						<label for="topic-value" class="form-label">Value</label>
						<textarea id="topic-value" class="form-control" rows="5" placeholder='For custom types use JSON, e.g. {"x":1.0,"y":2.0,"z":3.0}'></textarea>
						<div class="form-text">Primitives: plain values. Objects/arrays: valid JSON.</div>
					</div>
					<button type="submit" class="btn btn-success">Publish</button>
					<div id="publish-status" class="mt-2 small text-muted"></div>
				</form>
			</div>
		</div>
	`;

	document.body.prepend(container);

	const topicsBody = document.getElementById("topics-body");
	const datalist = document.getElementById("topic-list");
	const form = document.getElementById("publish-form");
	const topicNameInput = document.getElementById("topic-name");
	const typeInput = document.getElementById("topic-type");
	const valueInput = document.getElementById("topic-value");
	const publishStatus = document.getElementById("publish-status");
	const statusEl = document.getElementById("connection-status");
	const btnConnect = document.getElementById("btn-connect");
	const btnEcho = document.getElementById("btn-echo");
	const btnRequestAll = document.getElementById("btn-request-all");

	let connecting = false;

	function escapeHtml(text) {
		return String(text)
			.replaceAll("&", "&amp;")
			.replaceAll("<", "&lt;")
			.replaceAll(">", "&gt;")
			.replaceAll('"', "&quot;")
			.replaceAll("'", "&#039;");
	}

	function toReadable(value) {
		if (value === null || value === undefined) return "";
		if (typeof value === "bigint") return value.toString();
		if (value instanceof Uint8Array) return `Uint8Array(${value.length}) [${Array.from(value).slice(0, 32).join(",")}${value.length > 32 ? ",..." : ""}]`;
		if (Array.isArray(value)) return value.map((item) => (typeof item === "bigint" ? item.toString() : item));
		if (typeof value === "object") {
			const out = {};
			for (const [key, val] of Object.entries(value)) {
				out[key] = typeof val === "bigint" ? val.toString() : toReadable(val);
			}
			return out;
		}
		return value;
	}

	function formatValueForCell(value) {
		const readable = toReadable(value);
		if (typeof readable === "string" || typeof readable === "number" || typeof readable === "boolean") {
			return `<span>${escapeHtml(String(readable))}</span>`;
		}
		return `<pre class="mb-0" style="white-space:pre-wrap">${escapeHtml(JSON.stringify(readable, null, 2))}</pre>`;
	}

	function renderTopics() {
		topicsBody.innerHTML = "";
		datalist.innerHTML = "";

		const sorted = Array.from(topics.entries()).sort(([a], [b]) => a.localeCompare(b));

		for (const [name, info] of sorted) {
			const tr = document.createElement("tr");
			const updated = info.updatedAt ? new Date(info.updatedAt).toLocaleTimeString() : "";

			tr.innerHTML = `
				<td>${escapeHtml(name)}</td>
				<td><code>${escapeHtml(info.type || "")}</code></td>
				<td>${formatValueForCell(info.value)}</td>
				<td>${escapeHtml(updated)}</td>
			`;
			topicsBody.appendChild(tr);

			const opt = document.createElement("option");
			opt.value = name;
			datalist.appendChild(opt);
		}
	}

	function setStatus(text, variant = "muted") {
		statusEl.textContent = text;
		statusEl.className = `align-self-center text-${variant}`;
	}

	const client = new Client({
		url: endpoints.wsUrl,
		onOpen: () => {
			connecting = false;
			btnConnect.disabled = true;
			btnConnect.textContent = "Connected";
			setStatus("Connected", "success");
		},
		onClose: () => {
			connecting = false;
			btnConnect.disabled = false;
			btnConnect.textContent = "Connect";
			setStatus("Disconnected", "muted");
		},
		onError: (info) => {
			setStatus(`Protocol error: ${info.message}`, "danger");
		},
		onEcho: async (list) => {
			for (const info of list) {
				const existing = topics.get(info.name) || {};
				topics.set(info.name, { ...existing, type: info.typeStr });
			}
			renderTopics();
		},
		onNewTopic: async (info) => {
			const existing = topics.get(info.name) || {};
			topics.set(info.name, {
				...existing,
				type: info.typeStr,
				updatedAt: Date.now(),
			});
			renderTopics();
		},
		onUpdate: async (info) => {
			const existing = topics.get(info.name) || {};
			topics.set(info.name, {
				...existing,
				type: info.typeStr,
				value: info.value,
				updatedAt: Date.now(),
			});
			renderTopics();
		},
		onBigUpdate: async (updates) => {
			const now = Date.now();
			for (const [name, info] of Object.entries(updates)) {
				const existing = topics.get(name) || {};
				topics.set(name, {
					...existing,
					type: info.type,
					value: info.value,
					updatedAt: now,
				});
			}
			renderTopics();
		},
	});

	btnConnect.addEventListener("click", async () => {
		if (connecting || client.isOpen()) return;
		connecting = true;
		btnConnect.disabled = true;
		setStatus("Connecting...", "warning");
		try {
			try {
				const synced = await client.syncTypesFromServer({
					apiBase: endpoints.apiBase,
					token: endpoints.writeToken,
				});
				if (synced?.count) {
					setStatus(`Synced ${synced.count} type(s), connecting...`, "info");
				}
			} catch (err) {
				console.warn("type sync skipped:", err);
			}
			await client.start();
		} catch (err) {
			connecting = false;
			btnConnect.disabled = false;
			console.error("Client stopped with error", err);
			setStatus(`Error: ${err.message || "see console"}`, "danger");
		}
	});

	btnEcho.addEventListener("click", async () => {
		try {
			await client.echo();
			setStatus("Requested topics", "info");
		} catch (e) {
			console.error("Echo failed", e);
			setStatus("Echo failed", "danger");
		}
	});

	btnRequestAll.addEventListener("click", async () => {
		try {
			await client.requestAll();
			setStatus("Requested all values", "info");
		} catch (e) {
			console.error("requestAll failed", e);
			setStatus("Request all failed", "danger");
		}
	});

	form.addEventListener("submit", async (evt) => {
		evt.preventDefault();
		publishStatus.textContent = "";

		const name = topicNameInput.value.trim();
		if (!name) return;

		let type = typeInput.value.trim();
		const existing = topics.get(name);
		if (existing && existing.type) {
			type = existing.type;
		}

		let coerced;
		try {
			coerced = parseInputValue(type, valueInput.value);
		} catch (err) {
			publishStatus.textContent = err.message || "Invalid value";
			publishStatus.className = "mt-2 small text-danger";
			return;
		}

		try {
			await client.publish(name, type, coerced);
			publishStatus.textContent = `Published to ${name}`;
			publishStatus.className = "mt-2 small text-success";

			topics.set(name, {
				...(existing || {}),
				type,
				value: coerced,
				updatedAt: Date.now(),
			});
			renderTopics();
		} catch (e) {
			console.error("Publish failed", e);
			publishStatus.textContent = e.message || "Publish failed";
			publishStatus.className = "mt-2 small text-danger";
		}
	});
});
}
