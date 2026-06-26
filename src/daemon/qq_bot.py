"""QQ Bot gateway service for workspace IM integrations."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha1
from typing import Any, Callable

import httpx
import websockets

from core.user_data.projects import DEFAULT_PROJECT_ID, ProjectEntry, list_all_projects
from core.user_data.workspace_config import (
    get_workspace_config,
    normalize_workspace_config,
    qq_bot_bindings,
)
from daemon.api.protocol import TERMINAL_STATUSES
from daemon.supervisor import supervisor


QQ_ACCESS_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
QQ_API_BASE = "https://api.sgroup.qq.com"
GROUP_AND_C2C_INTENT = 1 << 25
SUPPORTED_MESSAGE_EVENTS = {"C2C_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE"}
TEXT_MESSAGE_TYPE = 0
MAX_REPLY_CHARS = 1800
MESSAGE_DEDUP_TTL_SECONDS = 3600
RUN_TIMEOUT_SECONDS = 540


@dataclass(frozen=True)
class QQBotMessage:
    event_type: str
    message_id: str
    content: str
    user_openid: str = ""
    group_openid: str = ""
    event_id: str = ""

    @property
    def is_group(self) -> bool:
        return bool(self.group_openid)

    @property
    def chat_key(self) -> str:
        if self.is_group:
            return f"group:{self.group_openid}"
        return f"c2c:{self.user_openid}"

    @property
    def thread_id(self) -> str:
        digest = sha1(self.chat_key.encode("utf-8")).hexdigest()[:16]
        return f"qq-{digest}"

    @property
    def client_id(self) -> str:
        return f"qq-bot:{self.thread_id}"


def parse_qq_message(event_type: str, data: dict[str, Any]) -> QQBotMessage | None:
    if event_type not in SUPPORTED_MESSAGE_EVENTS:
        return None

    message_id = str(data.get("id") or "")
    if not message_id:
        return None

    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    content = _clean_message_content(str(data.get("content") or ""))
    event_id = str(data.get("event_id") or data.get("eventId") or message_id)

    if event_type == "C2C_MESSAGE_CREATE":
        user_openid = str(
            data.get("user_openid")
            or data.get("openid")
            or author.get("user_openid")
            or author.get("openid")
            or ""
        )
        if not user_openid:
            return None
        return QQBotMessage(
            event_type=event_type,
            message_id=message_id,
            content=content,
            user_openid=user_openid,
            event_id=event_id,
        )

    group_openid = str(data.get("group_openid") or "")
    if not group_openid:
        return None
    member_openid = str(author.get("member_openid") or data.get("member_openid") or "")
    return QQBotMessage(
        event_type=event_type,
        message_id=message_id,
        content=content,
        user_openid=member_openid,
        group_openid=group_openid,
        event_id=event_id,
    )


def _clean_message_content(content: str) -> str:
    text = re.sub(r"<@!?[^>]+>", "", content or "")
    return text.strip()


def _trim_reply(text: str) -> str:
    reply = (text or "").strip()
    if not reply:
        return "我没有生成可发送的回复。"
    if len(reply) <= MAX_REPLY_CHARS:
        return reply
    return f"{reply[:MAX_REPLY_CHARS - 18].rstrip()}\n\n...回复过长，已截断"


class QQBotClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        access_token_url: str = QQ_ACCESS_TOKEN_URL,
        api_base: str = QQ_API_BASE,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.access_token_url = access_token_url
        self.api_base = api_base.rstrip("/")
        self._access_token = ""
        self._expires_at = 0.0

    async def get_access_token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token

        data = await self._request_json(
            "POST",
            self.access_token_url,
            json={"appId": self.app_id, "clientSecret": self.app_secret},
            use_auth=False,
        )
        token = str(data.get("access_token") or "")
        if not token:
            raise RuntimeError(f"QQ Bot access_token 获取失败：{data}")

        try:
            expires_in = int(data.get("expires_in") or 7200)
        except (TypeError, ValueError):
            expires_in = 7200
        self._access_token = token
        self._expires_at = time.time() + max(60, expires_in)
        return token

    async def fetch_gateway(self) -> dict[str, Any]:
        data = await self._request_json("GET", f"{self.api_base}/gateway/bot")
        url = str(data.get("url") or "")
        if not url:
            raise RuntimeError(f"QQ Bot gateway 地址为空：{data}")
        return data

    async def send_text_reply(self, message: QQBotMessage, text: str, *, msg_seq: int = 1) -> None:
        payload = {
            "content": _trim_reply(text),
            "msg_type": TEXT_MESSAGE_TYPE,
            "msg_id": message.message_id,
            "msg_seq": msg_seq,
        }
        if message.is_group:
            path = f"/v2/groups/{message.group_openid}/messages"
        else:
            path = f"/v2/users/{message.user_openid}/messages"
        await self._request_json("POST", f"{self.api_base}{path}", json=payload)

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        use_auth: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Content-Type", "application/json")
        if use_auth:
            token = await self.get_access_token()
            headers["Authorization"] = f"QQBot {token}"

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=20.0)) as client:
            response = await client.request(method, url, headers=headers, **kwargs)

        content_type = response.headers.get("content-type", "")
        try:
            data = response.json() if "json" in content_type else json.loads(response.text or "{}")
        except (json.JSONDecodeError, ValueError):
            data = {"raw": response.text}

        if response.is_error:
            raise RuntimeError(f"QQ Bot API 请求失败 {response.status_code}：{data}")
        if isinstance(data, dict) and data.get("code") not in (None, 0):
            raise RuntimeError(f"QQ Bot API 返回错误：{data}")
        return data if isinstance(data, dict) else {}


class QQBotService:
    def __init__(
        self,
        *,
        project_id: str = DEFAULT_PROJECT_ID,
        project_name: str = "",
        binding_id: str = "default",
        remark: str = "",
        client_factory: Callable[[str, str], QQBotClient] = QQBotClient,
        websocket_connect: Callable[..., Any] | None = None,
    ) -> None:
        self._project_id = project_id or DEFAULT_PROJECT_ID
        self._project_name = project_name
        self._binding_id = binding_id or "default"
        self._remark = remark
        self._client_factory = client_factory
        self._websocket_connect = websocket_connect or websockets.connect
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._signature: tuple[bool, str, str] | None = None
        self._last_sequence: int | None = None
        self._session_id = ""
        self._seen_message_ids: dict[str, float] = {}
        self._message_tasks: set[asyncio.Task] = set()
        self._status: dict[str, Any] = {
            "project_id": self._project_id,
            "project_name": self._project_name,
            "binding_id": self._binding_id,
            "remark": self._remark,
            "enabled": False,
            "running": False,
            "connected": False,
            "state": "disabled",
            "message": "QQ Bot 未启用",
            "last_error": "",
            "last_event_at": None,
            "last_reply_at": None,
        }

    def configure(self, config: dict[str, Any] | None) -> dict[str, Any]:
        config = config or {}
        enabled = bool(config.get("enabled", config.get("qq_bot_enabled", False)))
        app_id = str(config.get("app_id") or "").strip()
        app_secret = str(config.get("app_secret") or "").strip()
        remark = str(config.get("remark") or self._remark or "").strip()
        signature = (enabled, app_id, app_secret, self._project_id, self._binding_id, remark)
        self._remark = remark

        if not enabled:
            self.stop()
            self._set_status(
                enabled=False,
                running=False,
                connected=False,
                state="disabled",
                message="QQ Bot 未启用",
                last_error="",
                remark=self._remark,
            )
            self._signature = signature
            return self.status()

        if not app_id or not app_secret:
            self.stop()
            self._set_status(
                enabled=True,
                running=False,
                connected=False,
                state="missing_credentials",
                message="QQ Bot 缺少 AppID 或 AppSecret",
                last_error="",
                remark=self._remark,
            )
            self._signature = signature
            return self.status()

        with self._lock:
            thread_alive = self._thread is not None and self._thread.is_alive()
            if self._signature == signature and thread_alive:
                return dict(self._status)

        self.stop()
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._thread_main,
            args=(app_id, app_secret, stop_event),
            name="qq-bot-gateway",
            daemon=True,
        )
        with self._lock:
            self._signature = signature
            self._stop_event = stop_event
            self._thread = thread
            self._last_sequence = None
            self._session_id = ""
            self._status.update(
                {
                    "enabled": True,
                    "running": True,
                    "connected": False,
                    "state": "starting",
                    "message": "QQ Bot 正在启动",
                    "last_error": "",
                    "remark": self._remark,
                }
            )
        thread.start()
        return self.status()

    def stop(self) -> None:
        with self._lock:
            stop_event = self._stop_event
            thread = self._thread
            self._stop_event = None
            self._thread = None
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)

    def status(self) -> dict[str, Any]:
        with self._lock:
            status = dict(self._status)
            thread_alive = self._thread is not None and self._thread.is_alive()
            status["running"] = bool(status.get("running") and thread_alive)
            if status.get("enabled") and status.get("state") not in {"disabled", "missing_credentials"}:
                status["running"] = thread_alive
            return status

    def _thread_main(self, app_id: str, app_secret: str, stop_event: threading.Event) -> None:
        try:
            asyncio.run(self._run_until_stopped(app_id, app_secret, stop_event))
        finally:
            if not stop_event.is_set():
                self._set_status(running=False, connected=False, state="stopped", message="QQ Bot 已停止")

    async def _run_until_stopped(
        self,
        app_id: str,
        app_secret: str,
        stop_event: threading.Event,
    ) -> None:
        backoff = 2.0
        while not stop_event.is_set():
            client = self._client_factory(app_id, app_secret)
            try:
                await self._connect_once(client, stop_event)
                backoff = 2.0
            except Exception as exc:
                if stop_event.is_set():
                    break
                self._set_status(
                    running=True,
                    connected=False,
                    state="error",
                    message="QQ Bot 连接失败，稍后重试",
                    last_error=str(exc),
                )
                await self._sleep_or_stop(stop_event, backoff)
                backoff = min(60.0, backoff * 2)

        self._set_status(running=False, connected=False, state="stopped", message="QQ Bot 已停止")

    async def _connect_once(self, client: QQBotClient, stop_event: threading.Event) -> None:
        self._set_status(running=True, connected=False, state="authenticating", message="正在获取 QQ Bot AccessToken")
        token = await client.get_access_token()

        self._set_status(running=True, connected=False, state="connecting", message="正在连接 QQ Bot Gateway")
        gateway = await client.fetch_gateway()
        gateway_url = str(gateway.get("url") or "")

        async with self._websocket_connect(gateway_url, ping_interval=None, close_timeout=5) as websocket:
            hello = await self._recv_json(websocket, stop_event, timeout=15.0)
            if int(hello.get("op", -1)) != 10:
                raise RuntimeError(f"QQ Bot Gateway 未返回 Hello：{hello}")
            interval_ms = int((hello.get("d") or {}).get("heartbeat_interval") or 45000)
            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(websocket, stop_event, max(5.0, interval_ms / 1000))
            )
            try:
                identify = {
                    "op": 2,
                    "d": {
                        "token": f"QQBot {token}",
                        "intents": GROUP_AND_C2C_INTENT,
                        "shard": [0, 1],
                        "properties": {
                            "$os": "windows",
                            "$browser": "Ra3Copilot",
                            "$device": "Ra3Copilot",
                        },
                    },
                }
                await websocket.send(json.dumps(identify, ensure_ascii=False))
                await self._receive_loop(websocket, client, stop_event)
            finally:
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task

    async def _receive_loop(self, websocket: Any, client: QQBotClient, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                payload = await self._recv_json(websocket, stop_event, timeout=1.0)
            except asyncio.TimeoutError:
                continue

            op_code = int(payload.get("op", -1))
            sequence = payload.get("s")
            if isinstance(sequence, int):
                self._last_sequence = sequence

            if op_code == 0:
                await self._handle_dispatch(client, payload)
            elif op_code == 7:
                raise RuntimeError("QQ Bot Gateway 请求重连")
            elif op_code == 9:
                raise RuntimeError(f"QQ Bot Gateway 会话无效：{payload}")
            elif op_code == 11:
                self._set_status(running=True, connected=True, state="connected", message="QQ Bot 已连接")

    async def _handle_dispatch(self, client: QQBotClient, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("t") or "")
        data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
        if event_type == "READY":
            self._session_id = str(data.get("session_id") or "")
            self._set_status(running=True, connected=True, state="connected", message="QQ Bot 已连接")
            return

        message = parse_qq_message(event_type, data)
        if message is None:
            return

        self._set_status(last_event_at=time.time())
        if not self._mark_message_seen(message.message_id):
            return

        task = asyncio.create_task(self._process_message(client, message))
        self._message_tasks.add(task)
        task.add_done_callback(self._message_tasks.discard)

    async def _process_message(self, client: QQBotClient, message: QQBotMessage) -> None:
        try:
            if not message.content:
                reply = "我暂时只能处理文本消息。"
            else:
                reply = await asyncio.to_thread(self._run_agent_for_message, message)
            await client.send_text_reply(message, reply)
            self._set_status(last_reply_at=time.time(), last_error="")
        except Exception as exc:
            self._set_status(state="error", message="QQ Bot 处理消息失败", last_error=str(exc))
            try:
                await client.send_text_reply(message, f"处理这条消息时出错：{exc}")
            except Exception:
                pass

    def _run_agent_for_message(self, message: QQBotMessage) -> str:
        source = "QQ群聊" if message.is_group else "QQ单聊"
        prompt = f"{message.content}\n\n[来源：{source}。请生成一条适合直接发回 QQ 的简洁回复。]"
        try:
            state = supervisor.start_run(
                client_id=self._client_id_for_message(message),
                thread_id=self._thread_id_for_message(message),
                project_id=self._project_id,
                agent_mode="assistant",
                prompt=prompt,
                permission_policy="remember",
            )
        except RuntimeError as exc:
            if str(exc) == "RUN_ALREADY_ACTIVE":
                return "我还在处理上一条消息，请稍等一下。"
            raise

        deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
        final_status = "running"
        while time.monotonic() < deadline:
            result = supervisor.poll_run(state.run_id, 100)
            if result:
                final_status = str(result.get("status") or final_status)
                if final_status in TERMINAL_STATUSES:
                    break
            time.sleep(0.25)
        else:
            supervisor.stop_run(state.run_id)
            return "这次处理时间太久，我已经先停止了。可以换一种更小的任务再发我。"

        text = state.assistant_text.strip()
        if text:
            return _trim_reply(text)
        if state.error:
            return f"处理这条消息时出错：{state.error}"
        if final_status == "cancelled":
            return "这次处理已停止。"
        return "我处理完了，但没有生成可发送的回复。"

    def _thread_id_for_message(self, message: QQBotMessage) -> str:
        digest = sha1(f"{self._binding_id}:{message.chat_key}".encode("utf-8")).hexdigest()[:16]
        return f"qq-{digest}"

    def _client_id_for_message(self, message: QQBotMessage) -> str:
        return f"qq-bot:{self._project_id}:{self._binding_id}:{message.chat_key}"

    async def _heartbeat_loop(self, websocket: Any, stop_event: threading.Event, interval_seconds: float) -> None:
        while not stop_event.is_set():
            await self._sleep_or_stop(stop_event, interval_seconds)
            if stop_event.is_set():
                break
            payload = {"op": 1, "d": self._last_sequence}
            await websocket.send(json.dumps(payload, ensure_ascii=False))

    async def _recv_json(self, websocket: Any, stop_event: threading.Event, *, timeout: float) -> dict[str, Any]:
        if stop_event.is_set():
            raise asyncio.CancelledError()
        raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    async def _sleep_or_stop(self, stop_event: threading.Event, seconds: float) -> None:
        end_at = time.monotonic() + seconds
        while not stop_event.is_set():
            remaining = end_at - time.monotonic()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.5, remaining))

    def _mark_message_seen(self, message_id: str) -> bool:
        now = time.time()
        with self._lock:
            for key, seen_at in list(self._seen_message_ids.items()):
                if now - seen_at > MESSAGE_DEDUP_TTL_SECONDS:
                    self._seen_message_ids.pop(key, None)
            if message_id in self._seen_message_ids:
                return False
            self._seen_message_ids[message_id] = now
            return True

    def _set_status(self, **updates: Any) -> None:
        with self._lock:
            self._status.update(updates)


class QQBotManager:
    def __init__(self) -> None:
        self._services: dict[str, QQBotService] = {}
        self._lock = threading.RLock()

    def configure_all_projects(self) -> None:
        projects = list_all_projects()
        desired_keys: set[str] = set()
        for project in projects:
            config = get_workspace_config(project)
            desired_keys.update(self._configure_project_locked(project, config))

        with self._lock:
            for key in list(self._services):
                if key not in desired_keys:
                    service = self._services.pop(key)
                    service.stop()

    def configure_project(self, project: ProjectEntry, config: dict[str, Any] | None = None) -> None:
        config = normalize_workspace_config(config if config is not None else get_workspace_config(project))
        with self._lock:
            desired_keys = self._configure_project_locked(project, config)
            project_prefix = f"{project.id}:"
            for key in list(self._services):
                if key.startswith(project_prefix) and key not in desired_keys:
                    service = self._services.pop(key)
                    service.stop()

    def status_for_project(
        self,
        project: ProjectEntry,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = normalize_workspace_config(config if config is not None else get_workspace_config(project))
        bot_statuses = []
        with self._lock:
            for bot in qq_bot_bindings(config):
                key = self._service_key(project.id, bot["id"])
                service = self._services.get(key)
                if service is not None:
                    status = service.status()
                else:
                    status = self._inactive_status(project, bot)
                bot_statuses.append(status)
        return {
            "im_integrations": {"qq": bot_statuses},
            "qq_bots": bot_statuses,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            services = [service.status() for service in self._services.values()]
        connected = sum(1 for service in services if service.get("connected"))
        running = sum(1 for service in services if service.get("running"))
        return {
            "enabled": bool(services),
            "running": running > 0,
            "connected": connected > 0,
            "state": "connected" if connected else ("running" if running else "idle"),
            "message": f"{connected}/{len(services)} 个 QQ Bot 已连接" if services else "没有启用的 QQ Bot",
            "services": services,
        }

    def stop(self) -> None:
        with self._lock:
            services = list(self._services.values())
            self._services.clear()
        for service in services:
            service.stop()

    def _configure_project_locked(self, project: ProjectEntry, config: dict[str, Any]) -> set[str]:
        desired_keys: set[str] = set()

        for bot in qq_bot_bindings(config):
            key = self._service_key(project.id, bot["id"])
            if not bot.get("enabled"):
                continue
            desired_keys.add(key)
            with self._lock:
                service = self._services.get(key)
                if service is None:
                    service = QQBotService(
                        project_id=project.id,
                        project_name=project.name,
                        binding_id=bot["id"],
                        remark=bot.get("remark") or "",
                    )
                    self._services[key] = service
            service.configure(bot)
        return desired_keys

    def _inactive_status(self, project: ProjectEntry, bot: dict[str, Any]) -> dict[str, Any]:
        enabled = bool(bot.get("enabled"))
        has_credentials = bool(bot.get("app_id") and bot.get("app_secret"))
        state = "disabled"
        message = "QQ Bot 未启用"
        if enabled and not has_credentials:
            state = "missing_credentials"
            message = "QQ Bot 缺少 AppID 或 AppSecret"
        elif enabled:
            state = "stopped"
            message = "QQ Bot 未启动"
        return {
            "project_id": project.id,
            "project_name": project.name,
            "binding_id": bot.get("id") or "",
            "remark": bot.get("remark") or "",
            "enabled": enabled,
            "running": False,
            "connected": False,
            "state": state,
            "message": message,
            "last_error": "",
            "last_event_at": None,
            "last_reply_at": None,
        }

    def _service_key(self, project_id: str, binding_id: str) -> str:
        return f"{project_id}:{binding_id}"


qq_bot_service = QQBotManager()
