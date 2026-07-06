from __future__ import annotations

"""AnPaw 的入口文件。

这个文件同时模拟了两类入口：
1. CLI：`python run.py "你好"`，方便快速调试一轮 Agent。
2. HTTP：`python run.py --server`，给前端实验页面提供 API。

真实 QwenPaw 里，这一层大致对应 FastAPI、CLI、渠道回调等入口层。
它只负责接收外部请求，不直接做 Agent 推理。
"""

import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import parse_qs

from anpaw.config import load_model_config
from anpaw.logging_config import setup_logging
from anpaw.manager import MultiAgentManager
from anpaw.messages import TraceEvent, UserMessage
from anpaw.model import KiloChatModel
from anpaw.providers import list_models, list_providers


ROOT = Path(__file__).parent
LOG_FILE = setup_logging(ROOT)
logger = logging.getLogger("anpaw.app")

# 一个进程内只有一个多 Agent 管理器。
# 后续所有请求都会先经过它，再找到对应 agent_id 的 Workspace。
manager = MultiAgentManager(root_dir=ROOT)


def chat_once(
    agent_id: str,
    text: str,
    api_key: str = "",
    provider_id: str = "",
    model: str = "",
) -> dict:
    """执行一次聊天请求，并返回页面需要的 answer + trace。

    这里是学习链路的总入口：
    entry -> manager -> workspace -> runner -> agent-loop。
    """
    print(
        f"[入口] 收到消息 agent={agent_id} "
        f"provider={provider_id or '(默认)'} "
        f"model={model or '(默认)'} text={text[:60]!r}",
    )
    logger.info(
        "chat request agent=%s provider=%s model=%s text=%r",
        agent_id,
        provider_id or "(default)",
        model or "(default)",
        text[:120],
    )
    trace = [
        TraceEvent(
            stage="entry",
            detail="HTTP/CLI request entered AnPaw",
            data={
                "agent_id": agent_id,
                "provider": provider_id or "(default)",
                "model": model or "(default)",
                "message_preview": text[:120],
            },
        ),
    ]

    # Manager 负责按 agent_id 找 Workspace。
    # 如果 workspace 还没加载，它会懒加载并初始化 tools/skills/runner。
    print("[入口] 交给 MultiAgentManager 查找 Workspace")
    workspace = manager.get_agent(agent_id, trace=trace)

    # Runner 负责一次请求的编排：命令判断、记忆、模型配置、Agent 创建。
    print("[入口] 找到 Workspace，交给 AgentRunner 编排本轮请求")
    response = workspace.runner.run(
        UserMessage(text=text),
        api_key=api_key,
        provider_id=provider_id,
        model=model,
        initial_trace=trace,
    )
    payload = {
        "agent_id": agent_id,
        "answer": response.text,
        "trace": response.metadata.get("trace", []),
    }
    logger.info(
        "chat response agent=%s trace_events=%s answer_preview=%r",
        agent_id,
        len(payload["trace"]),
        response.text[:120],
    )
    print(f"[入口] 本轮结束，trace 事件数={len(payload['trace'])}")
    return payload


class HttpApp(BaseHTTPRequestHandler):
    """极简 HTTP 应用。

    为了让项目更容易学习，这里没有引入 FastAPI。
    真实项目里这些 GET/POST 会拆成路由、中间件、服务层。
    """

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        logger.info("HTTP GET %s", parsed.path)
        if parsed.path == "/":
            self._file(ROOT / "public" / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._file(ROOT / "public" / "app.js", "text/javascript; charset=utf-8")
            return
        if parsed.path == "/style.css":
            self._file(ROOT / "public" / "style.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/config":
            # 页面启动时读取当前默认 provider/model 配置。
            config = load_model_config()
            self._json(
                {
                    "provider": config.provider,
                    "model": config.model,
                    "base_url": config.base_url,
                    "has_env_key": bool(config.api_key),
                    "api_key_required": False,
                },
            )
            return
        if parsed.path == "/providers":
            # 返回学习版支持的云端 Provider 列表。
            self._json({"providers": list_providers()})
            return
        if parsed.path == "/models":
            # 返回某个 Provider 下的学习版模型清单。
            query = parse_qs(parsed.query)
            provider = (query.get("provider") or ["kilo"])[0]
            refresh = (query.get("refresh") or ["false"])[0].lower() == "true"
            models = list_models(provider, refresh=refresh)
            self._json(
                {
                    "provider": provider,
                    "models": [
                        {
                            "id": model.id,
                            "name": model.name,
                            "description": model.description,
                        }
                        for model in models
                    ],
                },
            )
            return
        if parsed.path == "/logs":
            # 页面右侧“日志”按钮会调用这里，方便直接看后端日志尾部。
            query = parse_qs(parsed.query)
            lines = int((query.get("lines") or ["120"])[0])
            self._json({"log_file": str(LOG_FILE), "lines": tail_log(lines)})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        logger.info("HTTP POST %s keys=%s", self.path, sorted(payload))
        if self.path == "/model-test":
            # 只测试模型连通性，不进入完整 Agent Loop。
            api_key = payload.get("api_key") or ""
            provider = payload.get("provider") or ""
            model = payload.get("model") or ""
            self._json(
                test_model(
                    api_key=api_key,
                    provider_id=provider,
                    model=model,
                ),
            )
            return

        if self.path != "/chat":
            self.send_error(404, "Only POST /chat or /model-test is supported")
            return

        # 前端传来的 provider/model/key 会在 Runner 中合成 ModelConfig。
        agent_id = payload.get("agent_id") or "default"
        message = payload.get("message") or ""
        api_key = payload.get("api_key") or ""
        provider = payload.get("provider") or ""
        model = payload.get("model") or ""

        try:
            self._json(
                chat_once(
                    agent_id,
                    message,
                    api_key=api_key,
                    provider_id=provider,
                    model=model,
                ),
            )
        except Exception as exc:  # pragma: no cover - teaching server
            logger.exception("chat request failed")
            self.send_error(500, str(exc))

    def log_message(self, format: str, *args) -> None:
        # BaseHTTPRequestHandler 默认会把每个请求打到 stderr。
        # 项目已经使用 logging_config 统一记录，所以这里关闭默认噪声。
        return

    def _file(self, path: Path, content_type: str) -> None:
        """返回前端静态资源。"""
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: dict) -> None:
        """统一返回 JSON，保留中文而不是转义成 \\uXXXX。"""
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    """命令行入口。

    不带 `--server` 时，只执行一轮聊天。
    带 `--server` 时，启动本地实验页面。
    """
    parser = argparse.ArgumentParser(description="AnPaw learning agent")
    parser.add_argument("message", nargs="*", help="message to send")
    parser.add_argument("--agent", default="default", help="agent id")
    parser.add_argument("--server", action="store_true", help="start HTTP demo")
    args = parser.parse_args()

    if args.server:
        server = ThreadingHTTPServer(("127.0.0.1", 8095), HttpApp)
        print("AnPaw page: http://127.0.0.1:8095/")
        print("AnPaw API : http://127.0.0.1:8095/chat")
        print(f"AnPaw log : {LOG_FILE}")
        print("[服务] 已启动，前端页面请求会在这里打印中文流程")
        logger.info("server started on http://127.0.0.1:8095")
        server.serve_forever()

    text = " ".join(args.message).strip()
    if not text:
        text = input("You: ").strip()
    print(chat_once(args.agent, text)["answer"])


def test_model(
    api_key: str = "",
    provider_id: str = "",
    model: str = "",
) -> dict:
    """测试云端模型是否可调用。

    注意：OpenCode/Kilo Code 免费模型通常不需要 Key；
    如果公共免费池限流，这里会返回 ok=False 和云端错误。
    """
    print(
        f"[模型测试] provider={provider_id or '(默认)'} "
        f"model={model or '(默认)'} auth={'with_key' if api_key else 'no_key'}",
    )
    config = load_model_config(
        api_key=api_key,
        provider_id=provider_id,
        model=model,
    )
    model = KiloChatModel(config)
    try:
        answer = model.chat(
            [
                {
                    "role": "system",
                    "content": "You are a concise connectivity test assistant.",
                },
                {
                    "role": "user",
                    "content": "用一句中文回复：模型已接通。",
                },
            ],
            temperature=0,
        )
        return {
            "ok": True,
            "message": answer,
            "provider": config.provider,
            "model": config.model,
            "base_url": config.base_url,
            "auth": "with_key" if config.api_key else "no_key",
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": str(exc),
            "provider": config.provider,
            "model": config.model,
            "base_url": config.base_url,
            "auth": "with_key" if config.api_key else "no_key",
        }


def tail_log(lines: int = 120) -> list[str]:
    """读取后端日志文件尾部，供页面“日志”按钮使用。"""
    if not LOG_FILE.exists():
        return []
    safe_lines = max(1, min(lines, 500))
    content = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    return content[-safe_lines:]


if __name__ == "__main__":
    main()
