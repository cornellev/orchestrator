const { it } = require("node:test");
const assert = require("node:assert/strict");
const { once } = require("node:events");
const { createServer } = require("node:http");
const { WebSocketServer } = require("ws");

// Each test file runs in its own process. Exercise Node without browser globals.
delete globalThis.WebSocket;
delete globalThis.fetch;
const { Client, buildTopicData, syncTypesFromServer } = require("../clientjs/Client.js");

it("uses the Node WebSocket and HTTP fallbacks from an ES module", { timeout: 5000 }, async (t) => {
	const server = createServer((req, res) => {
		assert.equal(req.url, "/api/types");
		res.setHeader("Content-Type", "application/json");
		res.end(JSON.stringify({ types: [{ type: "example/Note", definition: "string text" }] }));
	});
	const sockets = new WebSocketServer({ server });
	t.after(() => {
		for (const socket of sockets.clients) socket.terminate();
		sockets.close();
		return new Promise((resolve) => server.close(resolve));
	});
	server.listen(0, "127.0.0.1");
	await once(server, "listening");
	const address = `127.0.0.1:${server.address().port}`;
	const synced = await syncTypesFromServer({ apiBase: `http://${address}` });
	assert.deepEqual(synced.types, ["example/Note"]);

	const client = new Client({ url: `ws://${address}`, reconnect: false, autoSubscribe: false });
	t.after(() => client.stop());
	const connected = once(sockets, "connection");
	const running = client.start();
	const [socket] = await connected;
	const received = once(socket, "message");
	await client.publish("/note", "example/Note", { text: "hello" });
	assert.equal(client.isOpen(), true);
	const [payload] = await received;
	assert.deepEqual(payload, Buffer.from([2, ...buildTopicData("/note", "example/Note", { text: "hello" })]));
	await client.stop();
	await running;
});
