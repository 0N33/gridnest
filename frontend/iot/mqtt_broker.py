"""
Micro MQTT 3.1.1 Lightweight Broker and Event Bus for Smart Grid Digital Twin.
Runs an in-process asyncio MQTT broker on port 1883 (or fallback port), allowing
standard MQTT clients (paho-mqtt, mosquitto_pub, IoT microcontrollers) to connect,
publish sensor telemetry, and receive control commands with zero external dependencies.
"""
from __future__ import annotations
import asyncio
import struct
import logging
from typing import Dict, Set, Callable, Optional, List, Tuple

logger = logging.getLogger("GridNestMQTT")


def encode_remaining_length(length: int) -> bytes:
    """Encodes remaining length according to MQTT 3.1.1 spec."""
    encoded = bytearray()
    while True:
        byte = length % 128
        length //= 128
        if length > 0:
            byte |= 128
        encoded.append(byte)
        if length == 0:
            break
    return bytes(encoded)


def decode_remaining_length(data: bytes, offset: int = 1) -> Tuple[int, int]:
    """Decodes remaining length and returns (length, num_bytes_consumed)."""
    multiplier = 1
    value = 0
    bytes_consumed = 0
    idx = offset
    while True:
        if idx >= len(data):
            return 0, 0
        encoded_byte = data[idx]
        value += (encoded_byte & 127) * multiplier
        multiplier *= 128
        idx += 1
        bytes_consumed += 1
        if (encoded_byte & 128) == 0:
            break
        if bytes_consumed > 4:
            raise ValueError("Malformed Remaining Length in MQTT header")
    return value, bytes_consumed


class MicroMQTTBroker:
    """
    Lightweight, robust MQTT 3.1.1 broker.
    Supports CONNECT, CONNACK, PUBLISH (QoS 0/1), PUBACK, SUBSCRIBE, SUBACK, PINGREQ, PINGRESP, DISCONNECT.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 1883):
        self.host = host
        self.port = port
        self.server: Optional[asyncio.Server] = None
        self.subscribers: Dict[str, Set[asyncio.StreamWriter]] = {} # topic -> set of client writers
        self.clients: Set[asyncio.StreamWriter] = set()
        self.message_callbacks: List[Callable[[str, bytes], None]] = []
        self.is_running = False

    def on_message(self, callback: Callable[[str, bytes], None]):
        """Registers a Python callback for ingested MQTT messages."""
        self.message_callbacks.append(callback)

    async def start(self) -> bool:
        """Starts the MQTT TCP broker server."""
        try:
            self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
            self.is_running = True
            logger.info(f"[MicroMQTTBroker] Listening on {self.host}:{self.port} (MQTT 3.1.1 ready)")
            return True
        except OSError as e:
            logger.warning(f"[MicroMQTTBroker] Port {self.port} in use or unavailable: {e}. Trying fallback port 1884...")
            try:
                self.port = 1884
                self.server = await asyncio.start_server(self._handle_client, self.host, self.port)
                self.is_running = True
                logger.info(f"[MicroMQTTBroker] Listening on fallback {self.host}:{self.port}")
                return True
            except OSError as e2:
                logger.error(f"[MicroMQTTBroker] Could not bind MQTT broker: {e2}")
                self.is_running = False
                return False

    async def stop(self):
        """Stops the broker and closes all client connections."""
        self.is_running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in list(self.clients):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self.clients.clear()
        self.subscribers.clear()

    async def publish_local(self, topic: str, payload: bytes | str):
        """Publishes a message from internal Python code to all MQTT subscribers."""
        if isinstance(payload, str):
            payload = payload.encode("utf-8")

        # Notify internal callbacks
        for cb in self.message_callbacks:
            try:
                cb(topic, payload)
            except Exception as e:
                logger.error(f"[MicroMQTTBroker] Callback error: {e}")

        # Broadcast to matching MQTT subscriber TCP streams
        topic_bytes = topic.encode("utf-8")
        var_header = struct.pack("!H", len(topic_bytes)) + topic_bytes
        total_len = len(var_header) + len(payload)
        packet = b"\x30" + encode_remaining_length(total_len) + var_header + payload

        for filter_topic, writers in list(self.subscribers.items()):
            if self._topic_matches(filter_topic, topic):
                for w in list(writers):
                    try:
                        w.write(packet)
                        await w.drain()
                    except Exception:
                        writers.discard(w)

    def _topic_matches(self, pattern: str, topic: str) -> bool:
        """Evaluates MQTT wildcard topics (# and +)."""
        if pattern == "#" or pattern == topic:
            return True
        p_parts = pattern.split("/")
        t_parts = topic.split("/")
        for i, p in enumerate(p_parts):
            if p == "#":
                return True
            if i >= len(t_parts):
                return False
            if p != "+" and p != t_parts[i]:
                return False
        return len(p_parts) == len(t_parts)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handles an individual MQTT client TCP session."""
        self.clients.add(writer)
        client_subscriptions: Set[str] = set()

        try:
            while self.is_running:
                # Read fixed header byte 1
                b1 = await reader.read(1)
                if not b1:
                    break
                packet_type = (b1[0] >> 4) & 0x0F
                flags = b1[0] & 0x0F

                # Read remaining length
                multiplier = 1
                rem_len = 0
                while True:
                    lb = await reader.read(1)
                    if not lb:
                        break
                    rem_len += (lb[0] & 127) * multiplier
                    multiplier *= 128
                    if (lb[0] & 128) == 0:
                        break

                # Read variable header and payload
                body = await reader.readexactly(rem_len) if rem_len > 0 else b""

                # 1. CONNECT -> Reply CONNACK
                if packet_type == 1:
                    connack = b"\x20\x02\x00\x00" # Session Present: 0, Return Code: 0 (Accepted)
                    writer.write(connack)
                    await writer.drain()

                # 3. PUBLISH
                elif packet_type == 3:
                    if len(body) >= 2:
                        topic_len = struct.unpack("!H", body[0:2])[0]
                        topic = body[2:2 + topic_len].decode("utf-8", errors="replace")
                        idx = 2 + topic_len
                        qos = (flags >> 1) & 0x03
                        packet_id = 0
                        if qos > 0 and len(body) >= idx + 2:
                            packet_id = struct.unpack("!H", body[idx:idx + 2])[0]
                            idx += 2

                        payload = body[idx:]

                        # Acknowledge QoS 1 with PUBACK
                        if qos == 1 and packet_id > 0:
                            puback = b"\x40\x02" + struct.pack("!H", packet_id)
                            writer.write(puback)
                            await writer.drain()

                        # Dispatch message to internal digital twin engine
                        for cb in self.message_callbacks:
                            try:
                                cb(topic, payload)
                            except Exception as e:
                                logger.error(f"[MicroMQTTBroker] Error processing topic '{topic}': {e}")

                        # Forward to all matching subscriber clients
                        topic_bytes = topic.encode("utf-8")
                        out_var = struct.pack("!H", len(topic_bytes)) + topic_bytes
                        out_pkt = b"\x30" + encode_remaining_length(len(out_var) + len(payload)) + out_var + payload

                        for filter_topic, sub_writers in list(self.subscribers.items()):
                            if self._topic_matches(filter_topic, topic):
                                for sw in list(sub_writers):
                                    if sw != writer: # Don't echo to publisher
                                        try:
                                            sw.write(out_pkt)
                                            await sw.drain()
                                        except Exception:
                                            sub_writers.discard(sw)

                # 8. SUBSCRIBE -> Reply SUBACK
                elif packet_type == 8:
                    if len(body) >= 2:
                        pkt_id = struct.unpack("!H", body[0:2])[0]
                        offset = 2
                        sub_return_codes = bytearray()
                        while offset < len(body):
                            t_len = struct.unpack("!H", body[offset:offset + 2])[0]
                            offset += 2
                            sub_topic = body[offset:offset + t_len].decode("utf-8", errors="replace")
                            offset += t_len
                            _req_qos = body[offset] if offset < len(body) else 0
                            offset += 1

                            if sub_topic not in self.subscribers:
                                self.subscribers[sub_topic] = set()
                            self.subscribers[sub_topic].add(writer)
                            client_subscriptions.add(sub_topic)
                            sub_return_codes.append(0x00) # Granted QoS 0

                        suback_body = struct.pack("!H", pkt_id) + bytes(sub_return_codes)
                        suback = b"\x90" + encode_remaining_length(len(suback_body)) + suback_body
                        writer.write(suback)
                        await writer.drain()

                # 12. PINGREQ -> Reply PINGRESP
                elif packet_type == 12:
                    writer.write(b"\xd0\x00")
                    await writer.drain()

                # 14. DISCONNECT
                elif packet_type == 14:
                    break

        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            logger.debug(f"[MicroMQTTBroker] Client exception: {e}")
        finally:
            self.clients.discard(writer)
            for sub_topic in client_subscriptions:
                if sub_topic in self.subscribers:
                    self.subscribers[sub_topic].discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
