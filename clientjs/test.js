const { Client, registerMsgDefinition } = require("./Client");

registerMsgDefinition(
  "geometry_msgs/Point32",
  `
float32 x
float32 y
float32 z
`
);

registerMsgDefinition(
  "sensor_msgs/PointCloud",
  `
geometry_msgs/Point32[] points
`
);

registerMsgDefinition(
  "sensor_msgs/PointCloud2Lite",
  `
uint32 width
uint8[] data
bool is_dense
`
);

(async () => {
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
