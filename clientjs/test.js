const { Client } = require("./Client");

(async () => {
  const c = new Client({
    url: "ws://localhost:8080",
    onUpdate: (info) => {
      console.log("update", info);
      //c.stop();
    },
    onNewTopic: (info) => console.log("new topic", info),
    onEcho: (topics) => console.log("echo", topics),
    onBigUpdate: (data) => console.log("big_update", data),
  });

  await c.start();
  await c.subscribe();
})();
