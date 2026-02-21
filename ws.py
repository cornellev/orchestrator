import asyncio
from websockets.asyncio.server import serve
from enum import Enum
import serialization as s

methods = {
    0x00: "echo",
    0x01: "subscribe",
    0x02: "publish",
    0x03: "request_all"
}

responses = {
    "echo": 0x80,
    "echo_new": 0x81, # new topic added since last echo
    "update": 0x82, # topic data update
    "big_update": 0x83 # lots of topic updates (e.g. after request_all)
}

class WebSocketServer:
    def __init__(self, host: str = "localhost", port: int = 8080) -> None:
        self.host = host
        self.port = port

        self.clients = {} # maps connected clients with last interaction time
        self.sim = ROSSim(self.broadcast)

    async def broadcast(self, data: bytes, targets=None):
        # use a copy to avoid RuntimeError if clients disconnect during iteration
        if targets is None:
            targets = list(self.clients.keys())
        for client in list(targets):
            try:
                await client.send(data)
            except Exception as e:
                print(f"Error sending to client: {e}")
                self.clients.pop(client, None) # remove disconnected client

    async def handler(self, websocket):
        self.clients[websocket] = asyncio.get_event_loop().time() # store the time of connection
        try:
            try:
                async for message in websocket:
                    # message is expected to be a bytes object containing the topic name and type
                    # first byte is operation code (0 for subscribe, 1 for publish)
                    op_code = message[0]
                    op = methods.get(op_code, None)
                    if op is None:
                        print(f"Unknown operation code: {op_code}")
                        continue

                    await self.sim.handleMethod(op, message[1:], websocket)
            except Exception as exc:
                from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
                if not isinstance(exc, (ConnectionClosedOK, ConnectionClosedError)):
                    raise
        finally:
            self.clients.pop(websocket, None)
            self.sim.unsubscribe(websocket)


    async def run(self) -> None:
        async with serve(self.handler, self.host, self.port):
            # Run forever until cancelled (e.g. Ctrl+C in main)
            await asyncio.Future()

def construct_topicData(topic_name: str, type_str: str, data):
    # returns [type byte][count (4 bytes)][data...]
    if data is None:
        data = bytes([s.type_encoder(type_str)]) + (0).to_bytes(4, byteorder='little')
    else:
        data = s.encode(type_str, data)
    pre_topic = topic_name.encode('utf-8')
    topic_len = len(pre_topic)

    return bytes([topic_len]) + pre_topic + data

def decode_topicData(topic_data: bytes):
    topic_len = topic_data[0]
    topic_name = topic_data[1:1+topic_len].decode('utf-8')
    type_str, data = s.decode(topic_data[1+topic_len:])
    return topic_name, type_str, data

class ROSSim:
    def __init__(self, broadcaster):
        self.broadcast = broadcaster

        self.topics = {} # topic_name -> type_str
        self.topic_order = [] # preserve insertion order
        self.data = {}

        self.topicMap = {} # maps topic names to 4 bytes identifiers for efficient transmission over WebSocket
        self.counter = 0

        self.subscribers = set() # websockets that have subscribed to topics

    def add_topic(self, topic_name: str, type_str: str):
        if topic_name in self.topics:
            return

        self.topics[topic_name] = type_str
        self.topic_order.append(topic_name)
        self.data[topic_name] = None

        self.counter += 1
        self.topicMap[topic_name] = self.counter.to_bytes(4, byteorder='big')

        asyncio.create_task(self.notifyNewTopic(topic_name))

    def update_topic(self, topic_name: str, data):
        if topic_name in self.topics:
            self.data[topic_name] = data
            asyncio.create_task(self.notifyTopicUpdate(topic_name))
        else:
            raise ValueError(f"Topic '{topic_name}' not found in ROSSim.")
        
    def get_topic_data(self, topic_name: str):
        if topic_name in self.topics:
            return self.data[topic_name]
        else:
            raise ValueError(f"Topic '{topic_name}' not found in ROSSim.")

    def get_topic_type(self, topic_name: str):
        if topic_name in self.topics:
            return self.topics[topic_name]
        raise ValueError(f"Topic '{topic_name}' not found in ROSSim.")
    
    def serializeTopic(self, topic_name: str):
        type_str = self.get_topic_type(topic_name)
        data = self.get_topic_data(topic_name)
        return construct_topicData(topic_name, type_str, data)
        
    async def handleMethod(self, method, data, websocket):
        if method == "echo":
            await self.handleEchoTopics(websocket)

        if method == "subscribe":
            self.subscribers.add(websocket)

        if method == "publish":
            topic_name, type_str, decoded = decode_topicData(data)
            if topic_name not in self.topics:
                self.add_topic(topic_name, type_str)
            self.update_topic(topic_name, decoded)

        if method == "request_all":
            # send all topic data to client
            payload = bytearray()
            payload.append(responses["big_update"])
            payload.extend(len(self.topic_order).to_bytes(4, byteorder='little'))

            for topic_name in self.topic_order:
                payload.extend(self.serializeTopic(topic_name))
            await websocket.send(bytes(payload))
            
    def smallTopicInfoMsg(self, topic_name: str):
        type_str = self.get_topic_type(topic_name)
        data = self.get_topic_data(topic_name)
        type_byte = s.type_encoder(type_str)
        count = 0
        if data is not None:
            encoded = s.encode(type_str, data)
            count = int.from_bytes(encoded[1:5], byteorder='little')

        topic = topic_name.encode('utf-8')
        d = bytearray()
        d.extend(self.topicMap[topic_name]) # topic identifier (4 bytes)
        d.append(type_byte) # type byte
        d.extend(count.to_bytes(4, byteorder='little')) # count
        d.extend(len(topic).to_bytes(1, byteorder='little')) # topic name length
        d.extend(topic) # topic name data
        return bytes(d)

    """
    Echo method sends all current topics and their types + assignments to the client.
    NO DATA IS SENT.
    """
    async def handleEchoTopics(self, websocket):
        payload = bytearray()
        payload.append(responses["echo"])
        payload.extend(len(self.topic_order).to_bytes(4, byteorder='little')) # number of topics

        for topic_name in self.topic_order:
            payload.extend(self.smallTopicInfoMsg(topic_name))
    
        await websocket.send(bytes(payload))
    
    async def notifyNewTopic(self, topic_name: str):
        # send new topic info to all subscribers
        payload = bytearray()
        payload.append(responses["echo_new"])
        payload.extend(self.smallTopicInfoMsg(topic_name))

        await self.broadcast(bytes(payload), targets=self.subscribers)

    async def notifyTopicUpdate(self, topic_name: str):
        # send topic update to all subscribers
        payload = bytearray()
        payload.append(responses["update"])
        payload.extend(self.smallTopicInfoMsg(topic_name))

        await self.broadcast(bytes(payload), targets=self.subscribers)

    def unsubscribe(self, websocket):
        self.subscribers.discard(websocket)