
document.addEventListener("DOMContentLoaded", () => {
	if (!window.ROSClient || !window.ROSClient.Client) {
		console.error("ROSClient.Client is not available. Check that clientjs/Client.js is loaded.");
		return;
	}

	const { Client } = window.ROSClient;

	const topics = new Map(); // name -> { type, value, updatedAt }

	// --- Build UI ---
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
						<select id="topic-type" class="form-select" required>
							<option value="std_msgs/String">std_msgs/String</option>
							<option value="std_msgs/Int32">std_msgs/Int32</option>
							<option value="std_msgs/Float32">std_msgs/Float32</option>
							<option value="std_msgs/Bool">std_msgs/Bool</option>
						</select>
						<div class="form-text">For existing topics, the stored type will be used.</div>
					</div>
					<div class="mb-3">
						<label for="topic-value" class="form-label">Value</label>
						<input id="topic-value" class="form-control" placeholder="Enter value" />
						<div class="form-text">Booleans: true/false. Numbers: use plain numeric values.</div>
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
	const typeSelect = document.getElementById("topic-type");
	const valueInput = document.getElementById("topic-value");
	const publishStatus = document.getElementById("publish-status");
	const statusEl = document.getElementById("connection-status");
	const btnConnect = document.getElementById("btn-connect");
	const btnEcho = document.getElementById("btn-echo");
	const btnRequestAll = document.getElementById("btn-request-all");

	function renderTopics() {
		// Clear table and datalist
		topicsBody.innerHTML = "";
		datalist.innerHTML = "";

		const sorted = Array.from(topics.entries()).sort(([a], [b]) => a.localeCompare(b));

		for (const [name, info] of sorted) {
			const tr = document.createElement("tr");
			const lastVal = info.value === undefined ? "" : String(info.value);
			const updated = info.updatedAt ? new Date(info.updatedAt).toLocaleTimeString() : "";

			tr.innerHTML = `
				<td>${name}</td>
				<td><code>${info.type || ""}</code></td>
				<td>${lastVal}</td>
				<td>${updated}</td>
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

	function coerceValue(type, raw) {
		if (raw === "" || raw == null) return null;
		switch (type) {
			case "std_msgs/Int32":
				return parseInt(raw, 10);
			case "std_msgs/Float32":
				return parseFloat(raw);
			case "std_msgs/Bool":
				return /^true$/i.test(raw) || raw === "1";
			default:
				return raw;
		}
	}

	// --- WebSocket client ---
	const client = new Client({
		url: `ws://${location.hostname}:8080`,
		onOpen: () => {
			setStatus("Connected", "success");
		},
		onClose: () => {
			setStatus("Disconnected", "muted");
		},
		onEcho: async (list) => {
			for (const info of list) {
				const existing = topics.get(info.name) || {};
				topics.set(info.name, {
					...existing,
					type: info.typeStr,
				});
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
				updatedAt: Date.now(),
			});
			renderTopics();
			// Refresh values after an update so we show live data
			try {
				await client.requestAll();
			} catch (e) {
				console.error("Failed to request all after update", e);
			}
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

	// Start connection when user clicks connect
	btnConnect.addEventListener("click", () => {
		setStatus("Connecting...", "warning");
		client
			.start()
			.catch((err) => {
				console.error("Client stopped with error", err);
				setStatus("Error - see console", "danger");
			});
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

		let type = typeSelect.value;
		const existing = topics.get(name);
		if (existing && existing.type) {
			// Enforce existing topic type
			type = existing.type;
		}

		const rawVal = valueInput.value.trim();
		const coerced = coerceValue(type, rawVal);

		try {
			await client.publish(name, type, coerced);
			publishStatus.textContent = `Published to ${name}`;
			publishStatus.className = "mt-2 small text-success";

			// Optimistically update local view
			const now = Date.now();
			topics.set(name, {
				...(existing || {}),
				type,
				value: coerced,
				updatedAt: now,
			});
			renderTopics();
		} catch (e) {
			console.error("Publish failed", e);
			publishStatus.textContent = "Publish failed";
			publishStatus.className = "mt-2 small text-danger";
		}
	});
});

