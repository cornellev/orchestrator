const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
	encodeValue,
	decodeValue,
	buildTopicData,
	MAX_TOPIC_NAME_LEN,
	registerMsgDefinition,
} = require("../clientjs/Client.js");
const { resolveEndpoints, parseInputValue } = require("../frontend/script.js");

const fixtureCandidates = [
	path.join(__dirname, "..", "clientrs", "orchestrator-protocol", "tests", "fixtures", "protocol_vectors.json"),
	path.join(__dirname, "protocol_vectors.json"),
];
const vectorsPath = fixtureCandidates.find((p) => fs.existsSync(p));
const vectors = JSON.parse(fs.readFileSync(vectorsPath, "utf8"));

function toHex(bytes) {
	return Buffer.from(bytes).toString("hex");
}

function normalizeInput(typeName, value) {
	if (value && typeof value === "object" && Array.isArray(value.__bytes__)) {
		return Uint8Array.from(value.__bytes__);
	}
	if (
		typeName === "std_msgs/Int64" ||
		typeName === "std_msgs/UInt64" ||
		typeName === "std_msgs/UInt32" ||
		typeName === "std_msgs/Int32"
	) {
		if (typeof value === "string" || typeof value === "number" || typeof value === "bigint") {
			if (typeName === "std_msgs/Int64" || typeName === "std_msgs/UInt64") {
				return BigInt(value);
			}
			return Number(value);
		}
	}
	if (value && typeof value === "object" && !Array.isArray(value)) {
		const out = {};
		for (const [k, v] of Object.entries(value)) {
			out[k] = normalizeInput("", v);
		}
		return out;
	}
	if (Array.isArray(value)) {
		return value.map((item) => normalizeInput("", item));
	}
	return value;
}

function registerVectorSchemas(vector) {
	if (vector.definition) {
		registerMsgDefinition(vector.type, vector.definition);
	}
	if (vector.definitions) {
		for (const [typeName, definition] of Object.entries(vector.definitions)) {
			registerMsgDefinition(typeName, definition);
		}
	}
}

function assertApproxEqual(actual, expected) {
	if (typeof expected === "number" && !Number.isInteger(expected)) {
		assert.ok(Math.abs(actual - expected) < 1e-5);
		return;
	}
	if (typeof expected === "bigint") {
		assert.equal(BigInt(actual), expected);
		return;
	}
	if (expected instanceof Uint8Array) {
		assert.deepEqual(Uint8Array.from(actual), expected);
		return;
	}
	if (Array.isArray(expected)) {
		assert.equal(actual.length, expected.length);
		for (let i = 0; i < expected.length; i += 1) {
			assertApproxEqual(actual[i], expected[i]);
		}
		return;
	}
	if (expected && typeof expected === "object") {
		assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort());
		for (const key of Object.keys(expected)) {
			assertApproxEqual(actual[key], expected[key]);
		}
		return;
	}
	assert.deepEqual(actual, expected);
}

describe("protocol vectors", () => {
	for (const [name, vector] of Object.entries(vectors)) {
		it(`matches golden vector ${name}`, () => {
			registerVectorSchemas(vector);
			const input = normalizeInput(vector.type, vector.value);
			const encoded = encodeValue(vector.type, input);
			assert.equal(toHex(encoded), vector.hex);
			const decoded = decodeValue(encoded, 0);
			assert.equal(decoded.type, vector.type);
			assertApproxEqual(decoded.value, input);
		});
	}
});

describe("topic limits and dynamic schemas", () => {
	it("rejects topic names over 255 bytes", () => {
		assert.throws(() => buildTopicData("x".repeat(MAX_TOPIC_NAME_LEN + 1), "std_msgs/Int32", 1));
		const ok = buildTopicData("x".repeat(MAX_TOPIC_NAME_LEN), "std_msgs/Int32", 1);
		assert.equal(ok[0], MAX_TOPIC_NAME_LEN);
	});

	it("round-trips a dynamic message", () => {
		registerMsgDefinition(
			"geometry_msgs/Point32",
			["float32 x", "float32 y", "float32 z"].join("\n")
		);
		const value = { x: 1.25, y: -2.5, z: 3.75 };
		const encoded = encodeValue("geometry_msgs/Point32", value);
		const decoded = decodeValue(encoded, 0);
		assert.equal(decoded.type, "geometry_msgs/Point32");
		assert.ok(Math.abs(decoded.value.x - 1.25) < 1e-5);
		assert.ok(Math.abs(decoded.value.y + 2.5) < 1e-5);
		assert.ok(Math.abs(decoded.value.z - 3.75) < 1e-5);
	});
});

describe("frontend helpers", () => {
	it("derives secure websocket urls", () => {
		const endpoints = resolveEndpoints({ protocol: "https:", hostname: "example.test" });
		assert.equal(endpoints.wsUrl, "wss://example.test:8080");
		assert.equal(endpoints.apiBase, "https://example.test:8090");
	});

	it("validates numeric publish inputs", () => {
		assert.equal(parseInputValue("std_msgs/Int32", "12"), 12);
		assert.throws(() => parseInputValue("std_msgs/Int32", "abc"));
		assert.throws(() => parseInputValue("std_msgs/Float32", "nope"));
		assert.equal(parseInputValue("std_msgs/Bool", "true"), true);
	});
});
