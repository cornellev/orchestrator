const { Client, syncTypesFromServer } = require("./Client");

(async () => {
  try {
    const synced = await syncTypesFromServer({ apiBase: "http://localhost:8090" });
    console.log(`synced ${synced.count} message type(s) from server`);
  } catch (err) {
    console.warn("type sync skipped:", err.message);
  }

  const c = new Client({
    url: "ws://localhost:8080",
    onUpdate: (info) => {
      console.log("update", info.name, info.typeStr);
      console.dir(info.value, { depth: null });
    },
    onNewTopic: (info) => console.log("new topic", info.name, info.typeStr),
    onEcho: (topics) => {
      console.log("echo topics:", topics.length);
      for (const t of topics) {
        console.log(`- ${t.name} (${t.typeStr})`);
      }
    },
    onBigUpdate: (data) => {
      console.log("big_update");
      for (const [name, payload] of Object.entries(data)) {
        console.log(`${name} (${payload.type})`);
        console.dir(payload.value, { depth: null });
      }
    },
  });

  await c.start();
  await c.subscribe();
  await c.echo();
  await c.requestAll();
})();
