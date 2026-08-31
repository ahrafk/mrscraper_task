import asyncio
import uuid
from typing import Optional

from app.config import settings
from app.logging_config import get_logger
from app.phone_relay.registry import phone_registry

logger = get_logger(__name__)

READ_CHUNK = 65536


class LocalConnectProxy:
    def __init__(self) -> None:
        self._server: Optional[asyncio.base_events.Server] = None

    async def start(self) -> None:
        if not settings.PHONE_RELAY_ENABLED:
            return
        self._server = await asyncio.start_server(
            self._handle_client, host="127.0.0.1", port=settings.PHONE_RELAY_LOCAL_PORT
        )
        logger.info("Phone-relay CONNECT proxy listening on 127.0.0.1:%d", settings.PHONE_RELAY_LOCAL_PORT)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            if not request_line.startswith(b"CONNECT"):
                writer.close()
                return

            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"", b"\n"):
                    break

            parts = request_line.split()
            if len(parts) < 2:
                writer.close()
                return
            target = parts[1].decode()
            if ":" in target:
                host, port_str = target.rsplit(":", 1)
                port = int(port_str)
            else:
                host, port = target, 443

            await self._proxy_tunnel(reader, writer, host, port)
        except Exception as err:
            logger.warning("CONNECT proxy client error: %s", err)
            try:
                writer.close()
            except Exception:
                pass

    async def _proxy_tunnel(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str, port: int
    ) -> None:
        phone = phone_registry.pick_phone()
        if not phone:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\nNo phone relay available\r\n")
            await writer.drain()
            writer.close()
            return

        stream_id = uuid.uuid4()
        opened_future: asyncio.Future = asyncio.get_event_loop().create_future()
        phone.pending_opens[stream_id] = opened_future

        try:
            await phone.send_json({"type": "open", "stream_id": str(stream_id), "host": host, "port": port})
            ok = await asyncio.wait_for(
                opened_future, timeout=settings.PHONE_RELAY_OPEN_TIMEOUT_MS / 1000
            )
        except (asyncio.TimeoutError, Exception):
            ok = False
        finally:
            phone.pending_opens.pop(stream_id, None)

        if not ok:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\nPhone relay could not open stream\r\n")
            await writer.drain()
            writer.close()
            return

        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()

        incoming_queue: asyncio.Queue = asyncio.Queue()
        phone.streams[stream_id] = incoming_queue
        phone.active_stream_count += 1

        async def pump_local_to_phone():
            try:
                while True:
                    data = await reader.read(READ_CHUNK)
                    if not data:
                        break
                    await phone.send_binary(stream_id, data)
            except Exception:
                pass
            finally:
                try:
                    await phone.send_json({"type": "close", "stream_id": str(stream_id)})
                except Exception:
                    pass
                incoming_queue.put_nowait(None)

        async def pump_phone_to_local():
            try:
                while True:
                    data = await incoming_queue.get()
                    if data is None:
                        break
                    writer.write(data)
                    await writer.drain()
            except Exception:
                pass

        try:
            await asyncio.gather(pump_local_to_phone(), pump_phone_to_local())
        finally:
            phone.streams.pop(stream_id, None)
            phone.active_stream_count = max(0, phone.active_stream_count - 1)
            try:
                writer.close()
            except Exception:
                pass


local_connect_proxy = LocalConnectProxy()
