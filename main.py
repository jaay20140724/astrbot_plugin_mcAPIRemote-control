"""
麦块联机 (MineKuai) / 雨云 (RainYun) 多平台服务器远程控制插件

【麦块联机】通过麦块联机开放 API 远程控制 Minecraft 云服务器：
    · 启动 / 停止 / 重启 / 强制重启
    · 查看运行状态与资源占用（CPU / 内存 / 磁盘 / 网络 / 运行时长）
    · 向服务器控制台发送任意指令（如 list、say、op、gamemode 等）
    · 列出账号下全部服务器并一键切换控制目标

【雨云】通过雨云开放 API 远程控制云服务器(RCS) / 游戏云(RGS) 实例：
    · 启动 / 停止 / 重启
    · 查看实例状态、配置与公网 IP
    · 列出账号下全部实例并一键切换控制目标（非常适合托管 Minecraft 游戏云）

API 文档: 麦块联机 https://minekuai.cn/account/api | 雨云 https://api.v2.rainyun.com
API 节点: 麦块联机默认 https://minekuai.com/api/client（可在配置中改为个人专属节点）

本插件基于 AstrBot 插件规范开发，天然兼容 QQ 官方机器人 / OneBot / 其他平台。
"""

import asyncio
import json
import os
from datetime import datetime

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

# GreedyStr 用于接收指令之后的「全部剩余文本」，例如「mc命令 say 大家好」中的 "say 大家好"。
# 若运行环境版本较旧未提供该类型，则退化为普通注解，底层仍能正确合并剩余文本。
try:
    from astrbot.core.star.filter.command import GreedyStr
except ImportError:  # pragma: no cover - 兼容旧版本
    GreedyStr = None

DEFAULT_API_URL = "https://minekuai.com/api/client"
STATE_FILE = os.path.join("data", "state.json")

# 电源信号 → 中文描述
SIGNAL_LABEL = {
    "start": "启动",
    "stop": "停止",
    "restart": "重启",
    "kill": "强制停止",
}

# 服务器状态枚举 → 中文
STATE_ZH = {
    "running": "运行中",
    "starting": "启动中",
    "stopping": "停止中",
    "offline": "已离线",
    "stopped": "已停止",
    "suspended": "已暂停",
    "installing": "安装中",
}

# ---------------- 雨云 (RainYun) 配置 ----------------
RAINDUN_BASE = "https://api.v2.rainyun.com"

# 雨云产品类型 → 中文名
RAINDUN_PRODUCTS = {
    "rcs": "云服务器",
    "rgs": "游戏云",
}

# 雨云实例状态枚举 → 中文（其余未知状态原样展示）
RAINDUN_STATE = {
    "running": "运行中",
    "stopped": "已停止",
    "starting": "启动中",
    "stopping": "停止中",
    "pending": "待处理",
    "expired": "已过期",
    "suspended": "已暂停",
    "banned": "已封禁",
    "failed": "异常",
}


@register(
    "astrbot_plugin_xingjie",
    "xingjie",
    "多平台服务器远程控制：麦块联机(Minecraft)启动/停止/重启/强制重启/状态/命令/列表；雨云(RCS/RGS)启动/停止/重启/状态/列表",
    "1.1.0",
)
class XingjieController(Star):
    """麦块联机 + 雨云 多平台服务器远程控制器。"""

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}

        # ---------------- 麦块联机 API 配置 ----------------
        self.api_url = str(self.config.get("api_url") or DEFAULT_API_URL).strip().rstrip("/")
        self.api_key = str(self.config.get("api_key") or "").strip()
        self.server_id = str(self.config.get("server_id") or "").strip()
        self.timeout = int(self.config.get("request_timeout") or 10)
        self.max_retries = int(self.config.get("max_retries") or 3)

        # ---------------- 雨云 (RainYun) API 配置 ----------------
        self.rainyun_api_key = str(self.config.get("rainyun_api_key") or "").strip()
        self.rainyun_server_id = str(self.config.get("rainyun_server_id") or "").strip()
        self.rainyun_product = str(self.config.get("rainyun_product_type") or "rcs").strip().lower() or "rcs"

        # ---------------- 权限控制（可选，实时读取以支持配置热更新） ----------------
        # admin_qqs / allowed_groups 在每次检查时从配置动态读取，见 _get_admin_qqs / _get_allowed_groups。

        # ---------------- 运行时状态 ----------------
        # 记录通过「mc选择」切换的当前服务器；优先级高于配置文件中的 server_id。
        # current_rainyun_id 为雨云平台当前选中的实例ID。
        self._state: dict = {"current_server_id": "", "current_rainyun_id": ""}
        self._load_state()

        if not self.api_key:
            logger.warning(
                "[麦块联机] 未配置 API 密钥（api_key），所有 API 相关指令将无法工作，"
                "请在插件配置中填写麦块联机官网「账户 → API」页面提供的密钥。"
            )
        logger.info(
            "[麦块联机] 插件已加载 | API节点: %s | 默认服务器: %s",
            self.api_url,
            self.server_id or "（未设置）",
        )
        if not self.rainyun_api_key:
            logger.warning(
                "[雨云] 未配置 API 密钥（rainyun_api_key），雨云平台相关指令将无法工作，"
                "请在插件配置中填写雨云控制台「账户设置 → API 密钥」提供的密钥。"
            )
        logger.info(
            "[雨云] 插件已加载 | 产品类型: %s | 默认实例: %s",
            RAINDUN_PRODUCTS.get(self.rainyun_product, self.rainyun_product),
            self.rainyun_server_id or "（未设置）",
        )

    # ====================================================================
    # 状态持久化
    # ====================================================================

    def _state_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), STATE_FILE)

    def _load_state(self) -> None:
        try:
            path = self._state_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._state = data
        except Exception as e:  # 状态读取失败不影响插件加载
            logger.warning("[麦块联机] 读取状态文件失败: %s", e)

    def _save_state(self) -> None:
        try:
            path = self._state_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("[麦块联机] 保存状态文件失败: %s", e)

    def _resolve_server_id(self, given: str | None = None) -> str:
        """解析实际使用的服务器实例ID：指令参数 > 会话选择 > 配置默认。"""
        sid = (given or "").strip()
        if not sid:
            sid = (self._state.get("current_server_id") or "").strip()
        if not sid:
            sid = self.server_id
        return sid

    # ====================================================================
    # 权限控制
    # ====================================================================

    # ---------------- 权限配置实时读取（支持热更新） ----------------

    def _get_admin_qqs(self) -> set:
        return {str(q).strip() for q in (self.config.get("admin_qqs") or []) if str(q).strip()}

    def _get_allowed_groups(self) -> set:
        return {str(g).strip() for g in (self.config.get("allowed_groups") or []) if str(g).strip()}

    @staticmethod
    def _resolve_sender_id(event: AstrMessageEvent) -> str:
        """获取发送者ID。

        AstrBot 的 get_sender_id() 仅接受 str 类型的 user_id；而部分 QQ 适配器
        （如 OneBot 系）的 user_id 为 int 型 QQ 号，会返回空串；QQ 官方机器人下
        user_id 则是 openid 字符串（并非 QQ 号本身）。此处做兼容回退，直接读取
        message_obj.sender.user_id，无论其是 int 还是 str。
        """
        sid = str(event.get_sender_id() or "")
        if sid:
            return sid
        sender = getattr(event.message_obj, "sender", None)
        raw = getattr(sender, "user_id", None)
        return str(raw) if raw is not None else ""

    def _check_permission(self, event: AstrMessageEvent) -> tuple[bool, str]:
        """返回 (是否允许, 拒绝原因)。权限未配置时默认放行。"""
        sender = self._resolve_sender_id(event)
        group = str(event.get_group_id() or "")
        admin_qqs = self._get_admin_qqs()
        if admin_qqs and sender and sender not in admin_qqs:
            return False, (
                "⛔ 您不在管理员白名单中，无法执行服务器控制操作。\n"
                f"💡 您当前的用户ID为：{sender}\n"
                "请将此ID（注意：QQ官方机器人下它是 openid 而非QQ号）填入插件配置"
                " admin_qqs 中，保存并重启/重载插件即可生效。"
            )
        allowed_groups = self._get_allowed_groups()
        if allowed_groups and group and group not in allowed_groups:
            return False, f"⛔ 当前群组({group})不在允许使用列表中，无法执行服务器控制操作。"
        return True, ""

    # ====================================================================
    # 麦块联机 API 客户端
    # ====================================================================

    async def _api_request(self, method: str, path: str, body: dict | None = None) -> dict:
        """向麦块联机 API 发送请求，失败时自动重试。返回解析后的 JSON。"""
        if not self.api_key:
            raise RuntimeError(
                "未配置麦块联机 API 密钥（api_key），请在插件配置中填写。"
            )

        url = f"{self.api_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "AstrBot-MineKuai-Plugin/1.0",
        }

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    timeout = aiohttp.ClientTimeout(total=self.timeout)
                    async with session.request(
                        method, url, headers=headers, json=body, timeout=timeout
                    ) as resp:
                        text = await resp.text()
                        if resp.status in (200, 201, 202, 204):
                            if not text or not text.strip():
                                return {}
                            try:
                                return json.loads(text)
                            except (json.JSONDecodeError, ValueError):
                                # power/command 等写操作接口通常返回空体或非 JSON 文本，
                                # 只要状态码为 2xx 即视为操作成功。
                                logger.debug(
                                    "[麦块联机] 响应体非JSON(HTTP %s)，按成功处理: %s",
                                    resp.status,
                                    text[:200],
                                )
                                return {}

                        # 解析麦块API返回的错误信息（通常形如 {"errors":[{"detail": "..."}]}）
                        detail = ""
                        try:
                            payload = json.loads(text)
                            err = payload.get("errors") or payload.get("error") or payload.get("message")
                            if isinstance(err, list) and err:
                                detail = "; ".join(
                                    str(item.get("detail") or item) for item in err[:3]
                                )
                            elif isinstance(err, str):
                                detail = err
                        except Exception:
                            detail = text[:200]
                        raise RuntimeError(
                            f"麦块API返回错误 (HTTP {resp.status}): {detail or '未知错误'}"
                        )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_err = e
                logger.warning("[麦块联机] API请求第%d次失败: %s", attempt, e)
                if attempt < self.max_retries:
                    await asyncio.sleep(attempt)
                    continue
                raise RuntimeError(f"无法连接麦块API节点: {type(e).__name__}: {e}") from e
            except RuntimeError:
                raise
            except Exception as e:
                last_err = e
                logger.warning("[麦块联机] API请求第%d次失败: %s", attempt, e)
                if attempt < self.max_retries:
                    await asyncio.sleep(attempt)
                    continue
                raise RuntimeError(f"麦块API请求失败: {e}") from e

        raise RuntimeError(f"麦块API请求失败: {last_err}")

    async def power_action(self, signal: str, server_id: str | None = None) -> None:
        """电源控制：signal 取值 start / stop / restart / kill。"""
        sid = self._resolve_server_id(server_id)
        if not sid:
            raise RuntimeError("未设置服务器实例ID，请先使用「mc选择 <实例ID>」或填写配置 server_id。")
        await self._api_request("POST", f"/servers/{sid}/power", {"signal": signal})

    async def get_resources(self, server_id: str | None = None) -> dict:
        """查询服务器资源与运行状态。"""
        sid = self._resolve_server_id(server_id)
        if not sid:
            raise RuntimeError("未设置服务器实例ID。")
        data = await self._api_request("GET", f"/servers/{sid}/resources")
        return data.get("attributes") or {}

    async def get_server_detail(self, server_id: str | None = None) -> dict:
        """查询服务器详细信息（名称、状态、限制等）。"""
        sid = self._resolve_server_id(server_id)
        if not sid:
            raise RuntimeError("未设置服务器实例ID。")
        data = await self._api_request("GET", f"/servers/{sid}")
        return data.get("attributes") or {}

    async def list_servers(self) -> list:
        """获取当前账号下全部服务器。"""
        data = await self._api_request("GET", "/")
        return data.get("data") or []

    async def send_command(self, command: str, server_id: str | None = None) -> None:
        """向服务器控制台发送指令。"""
        sid = self._resolve_server_id(server_id)
        if not sid:
            raise RuntimeError("未设置服务器实例ID。")
        if not command or not command.strip():
            raise RuntimeError("命令内容不能为空。")
        await self._api_request(
            "POST", f"/servers/{sid}/command", {"command": command.strip()}
        )

    # ====================================================================
    # 消息格式化工具
    # ====================================================================

    @staticmethod
    def _format_bytes(bytes_value: float, unit: str = "GB") -> str:
        try:
            v = float(bytes_value or 0)
        except (TypeError, ValueError):
            v = 0.0
        if unit == "MB":
            return f"{v / 1024 / 1024:.2f}MB"
        return f"{v / 1024 / 1024 / 1024:.2f}GB"

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        try:
            s = int(seconds or 0)
        except (TypeError, ValueError):
            s = 0
        days, rem = divmod(s, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)
        return f"{days}天 {hours}小时 {minutes}分钟 {secs}秒"

    @staticmethod
    def _state_zh(state: str) -> str:
        return STATE_ZH.get((state or "").lower(), state or "未知")

    # ====================================================================
    # 指令：帮助
    # ====================================================================

    @filter.command("mc帮助")
    async def mc_help(self, event: AstrMessageEvent):
        ok, reason = self._check_permission(event)
        if not ok:
            yield event.plain_result(reason)
            return
        help_text = (
            "🛠️ 麦块联机 · Minecraft 服务器控制\n"
            "────────────────\n"
            "📌 控制指令：\n"
            "• mc状态 —— 查看服务器运行状态与资源\n"
            "• mc开服 / mc启动 —— 启动服务器\n"
            "• mc关服 / mc停止 —— 停止服务器\n"
            "• mc重启 —— 重启服务器\n"
            "• mc强制重启 —— 强制停止并重启\n"
            "• mc命令 <指令> —— 执行控制台命令\n"
            "     例：mc命令 say 大家好\n"
            "────────────────\n"
            "🔧 管理指令：\n"
            "• mc列表 —— 列出账号下全部服务器\n"
            "• mc选择 <实例ID> —— 切换当前控制目标\n"
            "────────────────\n"
            "💡 控制指令均可追加服务器实例ID，例如：mc开服 abc123\n"
            "💡 获取 API 密钥与实例ID：登录麦块联机官网 → 账户 → API\n"
            "🌐 本插件同时支持雨云平台（云服务器/游戏云），使用 ry 前缀指令，"
            "输入「ry帮助」查看雨云控制说明。"
        )
        yield event.plain_result(help_text)

    # ====================================================================
    # 指令：状态
    # ====================================================================

    @filter.command("mc状态")
    async def mc_status(self, event: AstrMessageEvent, server_id: str = None):
        ok, reason = self._check_permission(event)
        if not ok:
            yield event.plain_result(reason)
            return
        try:
            sid = self._resolve_server_id(server_id)
            if not sid:
                yield event.plain_result(
                    "⚠️ 尚未指定要控制的服务器。\n"
                    "请先使用「mc列表」查看服务器，再用「mc选择 <实例ID>」指定，\n"
                    "或在插件配置中填写 server_id。"
                )
                return

            attrs = await self.get_resources(sid)
            resources = attrs.get("resources") or {}
            state = self._state_zh(attrs.get("current_state"))
            suspended = attrs.get("is_suspended", False)

            # 尝试获取服务器名称（失败不影响主流程）
            name = sid
            try:
                detail = await self.get_server_detail(sid)
                name = detail.get("name") or sid
            except Exception:
                pass

            lines = [
                f"📊 {name}（{sid}）资源使用情况",
                f"📋 状态: {state}",
                f"🔄 暂停: {'是' if suspended else '否'}",
                f"🖥️ CPU: {float(resources.get('cpu_absolute') or 0):.2f}%",
                f"💾 内存: {self._format_bytes(resources.get('memory_bytes'), 'GB')}",
                f"💿 磁盘: {self._format_bytes(resources.get('disk_bytes'), 'GB')}",
                f"📡 网络接收: {self._format_bytes(resources.get('network_rx_bytes'), 'MB')}",
                f"📡 网络发送: {self._format_bytes(resources.get('network_tx_bytes'), 'MB')}",
                f"⏱️ 运行时间: {self._format_uptime(resources.get('uptime'))}",
                f"⏰ 查询时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ]
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error("[麦块联机] 查询状态失败: %s", e)
            yield event.plain_result(f"❌ 查询服务器状态失败: {e}")

    # ====================================================================
    # 指令：电源控制
    # ====================================================================

    async def _do_power(
        self, event: AstrMessageEvent, signal: str, label: str, server_id: str | None
    ) -> tuple[bool, str]:
        """电源控制的公共逻辑，返回 (是否成功, 提示消息)。"""
        ok, reason = self._check_permission(event)
        if not ok:
            return False, reason
        try:
            sid = self._resolve_server_id(server_id)
            if not sid:
                return False, (
                    "⚠️ 未指定服务器实例ID。\n"
                    "请先使用「mc列表」+「mc选择 <实例ID>」，或在插件配置中填写 server_id。"
                )
            await self.power_action(signal, sid)
            logger.info(
                "[麦块联机] 已向服务器 %s 发送 %s 指令（操作人: %s）",
                sid,
                signal,
                event.get_sender_id(),
            )
            return True, (
                f"✅ 已向服务器 {sid} 发送{label}指令，请稍后用「mc状态」确认结果。"
            )
        except Exception as e:
            logger.error("[麦块联机] %s服务器失败: %s", label, e)
            return False, f"❌ {label}服务器失败: {e}"

    @filter.command("mc开服", alias={"mc启动"})
    async def mc_start(self, event: AstrMessageEvent, server_id: str = None):
        ok, msg = await self._do_power(event, "start", "启动", server_id)
        yield event.plain_result(msg)

    @filter.command("mc关服", alias={"mc停止"})
    async def mc_stop(self, event: AstrMessageEvent, server_id: str = None):
        ok, msg = await self._do_power(event, "stop", "停止", server_id)
        yield event.plain_result(msg)

    @filter.command("mc重启")
    async def mc_restart(self, event: AstrMessageEvent, server_id: str = None):
        ok, msg = await self._do_power(event, "restart", "重启", server_id)
        yield event.plain_result(msg)

    @filter.command("mc强制重启")
    async def mc_force_restart(self, event: AstrMessageEvent, server_id: str = None):
        ok, reason = self._check_permission(event)
        if not ok:
            yield event.plain_result(reason)
            return
        try:
            sid = self._resolve_server_id(server_id)
            if not sid:
                yield event.plain_result(
                    "⚠️ 未指定服务器实例ID，请先使用「mc选择 <实例ID>」。"
                )
                return
            # 强制重启流程：停止 → 强杀 → 等待 → 启动
            await self.power_action("stop", sid)
            await asyncio.sleep(1)
            await self.power_action("kill", sid)
            await asyncio.sleep(3)
            await self.power_action("start", sid)
            logger.info("[麦块联机] 已向服务器 %s 发送强制重启指令", sid)
            yield event.plain_result(
                f"✅ 已向服务器 {sid} 发送强制重启指令（停止→强杀→启动），请稍后确认。"
            )
        except Exception as e:
            logger.error("[麦块联机] 强制重启失败: %s", e)
            yield event.plain_result(f"❌ 强制重启服务器失败: {e}")

    # ====================================================================
    # 指令：执行命令
    # ====================================================================

    @filter.command("mc命令")
    async def mc_command(self, event: AstrMessageEvent, command: GreedyStr):
        # 兼容 GreedyStr 未提供的旧版本：手动解析剩余文本
        if GreedyStr is None or not command:
            parts = event.get_message_str().split(maxsplit=1)
            command = parts[1] if len(parts) > 1 else ""

        ok, reason = self._check_permission(event)
        if not ok:
            yield event.plain_result(reason)
            return

        cmd = (command or "").strip()
        if not cmd:
            yield event.plain_result(
                "⚠️ 请输入要执行的命令。\n"
                "例如：mc命令 say 大家好\n"
                "也可执行 list、op <玩家名>、gamemode <模式> 等服务器指令。"
            )
            return
        try:
            sid = self._resolve_server_id(None)
            if not sid:
                yield event.plain_result(
                    "⚠️ 未指定服务器实例ID，请先使用「mc选择 <实例ID>」。"
                )
                return
            await self.send_command(cmd, sid)
            logger.info("[麦块联机] 向服务器 %s 发送命令: %s", sid, cmd)
            yield event.plain_result(f"✅ 已向服务器 {sid} 发送命令：\n💬 /{cmd}")
        except Exception as e:
            logger.error("[麦块联机] 执行命令失败: %s", e)
            yield event.plain_result(f"❌ 执行命令失败: {e}")

    # ====================================================================
    # 指令：服务器列表 / 切换
    # ====================================================================

    @filter.command("mc列表")
    async def mc_list(self, event: AstrMessageEvent):
        ok, reason = self._check_permission(event)
        if not ok:
            yield event.plain_result(reason)
            return
        try:
            servers = await self.list_servers()
            if not servers:
                yield event.plain_result(
                    "📭 当前账号下没有服务器，或 API 密钥无权限访问。"
                )
                return
            lines = [f"🗂️ 共 {len(servers)} 台服务器：", ""]
            current = self._resolve_server_id(None)
            for s in servers:
                attrs = s.get("attributes") or {}
                sid = attrs.get("identifier") or "?"
                name = attrs.get("name") or sid
                state = self._state_zh(attrs.get("status"))
                suspended = attrs.get("is_suspended", False)
                mark = "✅" if sid == current else "•"
                suffix = "（已暂停）" if suspended else ""
                lines.append(f"{mark} [{sid}] {name} | 状态: {state}{suffix}")
            lines.append("")
            lines.append("💡 使用「mc选择 <实例ID>」切换要控制的服务器，例如：mc选择 abc123")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error("[麦块联机] 获取服务器列表失败: %s", e)
            yield event.plain_result(f"❌ 获取服务器列表失败: {e}")

    @filter.command("mc选择")
    async def mc_select(self, event: AstrMessageEvent, server_id: str = None):
        ok, reason = self._check_permission(event)
        if not ok:
            yield event.plain_result(reason)
            return
        sid = (server_id or "").strip()
        if not sid:
            yield event.plain_result(
                "⚠️ 请输入服务器实例ID，例如：mc选择 abc123\n"
                "可用「mc列表」查看所有服务器及其实例ID。"
            )
            return
        self._state["current_server_id"] = sid
        self._save_state()
        yield event.plain_result(
            f"✅ 已将当前控制的服务器切换为：{sid}\n可使用「mc状态」确认服务器信息。"
        )

    # ====================================================================
    # 雨云 (RainYun) API 客户端
    # ====================================================================

    def _rainyun_product(self) -> str:
        """当前生效的雨云产品类型（rcs / rgs），实时读取以支持配置热更新。"""
        p = str(self.config.get("rainyun_product_type") or self.rainyun_product).strip().lower()
        return p if p in RAINDUN_PRODUCTS else "rcs"

    def _resolve_rainyun_id(self, given: str | None = None) -> str:
        """解析实际使用的雨云实例ID：指令参数 > 会话选择 > 配置默认。"""
        sid = (given or "").strip()
        if not sid:
            sid = (self._state.get("current_rainyun_id") or "").strip()
        if not sid:
            sid = self.rainyun_server_id
        return sid

    async def _rainyun_request(self, method: str, path: str, body: dict | None = None) -> dict:
        """向雨云 API 发送请求，失败时自动重试。返回解析后的 JSON（含 code/data/message）。"""
        if not self.rainyun_api_key:
            raise RuntimeError(
                "未配置雨云 API 密钥（rainyun_api_key），请在插件配置中填写。"
            )

        url = f"{RAINDUN_BASE}{path}"
        headers = {
            "x-api-key": self.rainyun_api_key,
            "Accept": "application/json",
            "User-Agent": "AstrBot-RainYun-Plugin/1.1",
        }

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    timeout = aiohttp.ClientTimeout(total=self.timeout)
                    kwargs: dict = {"headers": headers, "timeout": timeout}
                    if body is not None:
                        kwargs["json"] = body
                    async with session.request(method, url, **kwargs) as resp:
                        text = await resp.text()
                        try:
                            payload = json.loads(text) if text and text.strip() else {}
                        except (json.JSONDecodeError, ValueError):
                            payload = {}
                        if resp.status < 200 or resp.status >= 300:
                            code = payload.get("code")
                            msg = payload.get("message") or text[:200]
                            raise RuntimeError(
                                f"雨云API返回错误 (HTTP {resp.status}, code={code}): {msg}"
                            )
                        # 业务 code 非 0/200 视为失败（如密钥错误 30039、状态不允许 70026、需二次验证 30043）
                        code = payload.get("code")
                        if code not in (None, 0, 200, "0", "200"):
                            raise RuntimeError(
                                f"雨云API业务错误 (code={code}): {payload.get('message') or '未知错误'}"
                            )
                        return payload
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_err = e
                logger.warning("[雨云] API请求第%d次失败: %s", attempt, e)
                if attempt < self.max_retries:
                    await asyncio.sleep(attempt)
                    continue
                raise RuntimeError(f"无法连接雨云API节点: {type(e).__name__}: {e}") from e
            except RuntimeError:
                raise
            except Exception as e:
                last_err = e
                logger.warning("[雨云] API请求第%d次失败: %s", attempt, e)
                if attempt < self.max_retries:
                    await asyncio.sleep(attempt)
                    continue
                raise RuntimeError(f"雨云API请求失败: {e}") from e

        raise RuntimeError(f"雨云API请求失败: {last_err}")

    async def _rainyun_power(self, action: str, server_id: str | None = None) -> None:
        """电源控制：action 取值 start / stop / reboot。"""
        sid = self._resolve_rainyun_id(server_id)
        if not sid:
            raise RuntimeError(
                "未设置雨云实例ID，请先使用「ry列表」+「ry选择 <实例ID>」或填写配置 rainyun_server_id。"
            )
        product = self._rainyun_product()
        await self._rainyun_request("POST", f"/product/{product}/{sid}/{action}")

    async def _rainyun_list(self) -> list:
        """获取当前账号下指定产品类型的全部实例。"""
        product = self._rainyun_product()
        # RCS 列表接口带 options 查询参数；RGS 列表接口为尾部斜杠。
        path = "/product/rcs?options=" if product == "rcs" else f"/product/{product}/"
        payload = await self._rainyun_request("GET", path)
        return self._rainyun_extract_records(payload)

    async def _rainyun_detail(self, server_id: str) -> dict:
        """获取实例详情（RCS / RGS 均为 data.Data 嵌套）。"""
        product = self._rainyun_product()
        return await self._rainyun_request("GET", f"/product/{product}/{server_id}/")

    @staticmethod
    def _rainyun_extract_records(payload: dict) -> list:
        """从雨云列表响应中提取实例记录列表（兼容多种嵌套结构）。"""
        data = payload.get("data") or {}
        if isinstance(data, dict):
            if isinstance(data.get("Records"), list):
                return data["Records"]
            inner = data.get("Data") or data.get("data")
            if isinstance(inner, dict) and isinstance(inner.get("Records"), list):
                return inner["Records"]
            if isinstance(data.get("list"), list):
                return data["list"]
        if isinstance(payload.get("data"), list):
            return payload["data"]
        return []

    @staticmethod
    def _rainyun_extract_server(payload: dict) -> dict:
        """从雨云详情响应中提取实例主体（兼容 data.Data 嵌套）。"""
        data = payload.get("data") or {}
        if isinstance(data, dict):
            inner = data.get("Data") or data.get("data")
            if isinstance(inner, dict):
                return inner
            return data
        return {}

    @staticmethod
    def _rainyun_state_zh(state: str) -> str:
        return RAINDUN_STATE.get((state or "").lower(), state or "未知")

    # ====================================================================
    # 指令（雨云）：帮助
    # ====================================================================

    @filter.command("ry帮助")
    async def ry_help(self, event: AstrMessageEvent):
        ok, reason = self._check_permission(event)
        if not ok:
            yield event.plain_result(reason)
            return
        product = self._rainyun_product()
        pname = RAINDUN_PRODUCTS.get(product, product)
        help_text = (
            f"☁️ 雨云 (RainYun) · {pname} 控制\n"
            "────────────────\n"
            "📌 控制指令：\n"
            "• ry状态 —— 查看实例运行状态与配置\n"
            "• ry开服 / ry启动 —— 启动实例\n"
            "• ry关服 / ry停止 —— 停止实例\n"
            "• ry重启 —— 重启实例\n"
            "────────────────\n"
            "🔧 管理指令：\n"
            "• ry列表 —— 列出账号下全部实例\n"
            "• ry选择 <实例ID> —— 切换当前控制目标\n"
            "────────────────\n"
            f"💡 当前产品类型: {pname}（可在配置 rainyun_product_type 切换 rcs / rgs）\n"
            "💡 控制指令均可追加实例ID，例如：ry开服 114514\n"
            "💡 获取 API 密钥：雨云控制台 → 账户设置 → API 密钥"
        )
        yield event.plain_result(help_text)

    # ====================================================================
    # 指令（雨云）：状态
    # ====================================================================

    @filter.command("ry状态")
    async def ry_status(self, event: AstrMessageEvent, server_id: str = None):
        ok, reason = self._check_permission(event)
        if not ok:
            yield event.plain_result(reason)
            return
        try:
            sid = self._resolve_rainyun_id(server_id)
            if not sid:
                yield event.plain_result(
                    "⚠️ 尚未指定要控制的雨云实例。\n"
                    "请先使用「ry列表」查看实例，再用「ry选择 <实例ID>」指定，\n"
                    "或在插件配置中填写 rainyun_server_id。"
                )
                return
            product = self._rainyun_product()
            payload = await self._rainyun_detail(sid)
            server = self._rainyun_extract_server(payload)
            name = server.get("HostName") or server.get("OsName") or server.get("McsmUserName") or sid
            status = self._rainyun_state_zh(server.get("Status"))
            ip = server.get("MainIPv4") or server.get("NatPublicIP") or "（无公网IP）"
            usage = server.get("UsageData") or {}
            lines = [
                f"☁️ 雨云{RAINDUN_PRODUCTS.get(product, product)} · {name}（{sid}）",
                f"📋 状态: {status}",
                f"🌐 主IP: {ip}",
                f"💻 系统: {server.get('OsName') or '未知'}",
                f"🧠 CPU配置: {server.get('CPU') or '未知'} 核",
                f"🧠 内存配置: {server.get('Memory') or '未知'} MB",
            ]
            cpu = usage.get("CPU")
            if cpu is not None:
                lines.append(f"📈 实时CPU占用: {float(cpu):.2f}%")
            lines.append(f"⏰ 查询时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error("[雨云] 查询状态失败: %s", e)
            yield event.plain_result(f"❌ 查询雨云实例状态失败: {e}")

    # ====================================================================
    # 指令（雨云）：电源控制
    # ====================================================================

    async def _ry_do_power(
        self, event: AstrMessageEvent, action: str, label: str, server_id: str | None
    ) -> tuple[bool, str]:
        ok, reason = self._check_permission(event)
        if not ok:
            return False, reason
        try:
            sid = self._resolve_rainyun_id(server_id)
            if not sid:
                return False, (
                    "⚠️ 未指定雨云实例ID。\n"
                    "请先使用「ry列表」+「ry选择 <实例ID>」，或在插件配置中填写 rainyun_server_id。"
                )
            await self._rainyun_power(action, sid)
            logger.info(
                "[雨云] 已向实例 %s 发送 %s 指令（操作人: %s）",
                sid,
                action,
                event.get_sender_id(),
            )
            return True, f"✅ 已向雨云实例 {sid} 发送{label}指令，请稍后用「ry状态」确认结果。"
        except Exception as e:
            logger.error("[雨云] %s实例失败: %s", label, e)
            return False, f"❌ {label}雨云实例失败: {e}"

    @filter.command("ry开服", alias={"ry启动"})
    async def ry_start(self, event: AstrMessageEvent, server_id: str = None):
        ok, msg = await self._ry_do_power(event, "start", "启动", server_id)
        yield event.plain_result(msg)

    @filter.command("ry关服", alias={"ry停止"})
    async def ry_stop(self, event: AstrMessageEvent, server_id: str = None):
        ok, msg = await self._ry_do_power(event, "stop", "停止", server_id)
        yield event.plain_result(msg)

    @filter.command("ry重启")
    async def ry_reboot(self, event: AstrMessageEvent, server_id: str = None):
        ok, msg = await self._ry_do_power(event, "reboot", "重启", server_id)
        yield event.plain_result(msg)

    # ====================================================================
    # 指令（雨云）：列表 / 切换
    # ====================================================================

    @filter.command("ry列表")
    async def ry_list(self, event: AstrMessageEvent):
        ok, reason = self._check_permission(event)
        if not ok:
            yield event.plain_result(reason)
            return
        try:
            product = self._rainyun_product()
            records = await self._rainyun_list()
            if not records:
                yield event.plain_result(
                    f"📭 当前账号下没有雨云{RAINDUN_PRODUCTS.get(product, product)}实例，"
                    "或 API 密钥无权限访问。"
                )
                return
            lines = [
                f"🗂️ 共 {len(records)} 台雨云{RAINDUN_PRODUCTS.get(product, product)}实例：",
                "",
            ]
            current = self._resolve_rainyun_id(None)
            for r in records:
                if not isinstance(r, dict):
                    continue
                rid = str(r.get("ID") or r.get("id") or "?")
                name = r.get("HostName") or r.get("OsName") or r.get("McsmUserName") or rid
                status = self._rainyun_state_zh(r.get("Status"))
                ip = r.get("MainIPv4") or r.get("NatPublicIP") or ""
                mark = "✅" if rid == current else "•"
                suffix = f" | IP: {ip}" if ip else ""
                lines.append(f"{mark} [{rid}] {name} | 状态: {status}{suffix}")
            lines.append("")
            lines.append("💡 使用「ry选择 <实例ID>」切换要控制的实例，例如：ry选择 114514")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error("[雨云] 获取实例列表失败: %s", e)
            yield event.plain_result(f"❌ 获取雨云实例列表失败: {e}")

    @filter.command("ry选择")
    async def ry_select(self, event: AstrMessageEvent, server_id: str = None):
        ok, reason = self._check_permission(event)
        if not ok:
            yield event.plain_result(reason)
            return
        sid = (server_id or "").strip()
        if not sid:
            yield event.plain_result(
                "⚠️ 请输入雨云实例ID，例如：ry选择 114514\n"
                "可用「ry列表」查看所有实例及其实例ID。"
            )
            return
        self._state["current_rainyun_id"] = sid
        self._save_state()
        yield event.plain_result(
            f"✅ 已将当前控制的雨云实例切换为：{sid}\n可使用「ry状态」确认实例信息。"
        )

    # ====================================================================
    # 生命周期
    # ====================================================================

    async def terminate(self):
        """插件卸载时持久化运行状态。"""
        try:
            self._save_state()
        except Exception as e:
            logger.error("[麦块联机] 保存状态失败: %s", e)
