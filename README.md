# Minecraft 服务器远程控制插件

通过开放 API 远程控制你的 Minecraft 云服务器。
插件基于 [AstrBot](https://github.com/AstrBot-AIGC/AstrBot) 插件规范开发，天然兼容 **QQ 官方机器人**、OneBot 及其他平台适配器。

## ✨ 功能特性

| 功能 | 指令 | 说明 |
| --- | --- | --- |
| 启动服务器 | `mc开服` / `mc启动` | 向麦块节点发送启动信号 |
| 停止服务器 | `mc关服` / `mc停止` | 向麦块节点发送停止信号 |
| 重启服务器 | `mc重启` | 平滑重启 |
| 强制重启 | `mc强制重启` | 停止 → 强杀 → 启动，用于卡死恢复 |
| 查看状态 | `mc状态` | 运行状态、CPU、内存、磁盘、网络、运行时长 |
| 执行命令 | `mc命令 <指令>` | 向服务器控制台发送任意指令（如 `list`、`say`、`op`、`gamemode`） |
| 服务器列表 | `mc列表` | 列出账号下全部服务器及其实例ID |
| 切换目标 | `mc选择 <实例ID>` | 切换当前控制的服务器（持久保存） |
| 帮助 | `mc帮助` | 显示所有指令 |

所有控制指令都支持在末尾追加服务器实例ID，例如：

```
mc开服 abc123
mc状态 def456
mc命令 say 大家好
```

## 📦 安装

1. 将本插件目录（`astrbot_plugin_mcAPIRemote control`）放入 AstrBot 的 `data/plugins/` 目录。
2. 在 AstrBot 管理面板「插件」中启用本插件，或重启 AstrBot。
3. 在插件配置中填写 API 节点地址与 API 密钥后保存。

## ⚙️ 配置说明

在 AstrBot 插件配置面板中填写以下参数（亦可直接编辑 `_conf_schema.json` 对应的用户配置）：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `api_url` | string | `https://minekuai.com/api/client` | 麦块联机 API 节点地址 |
| `api_key` | string | 空 | 麦块联机 API 密钥（**必填**） |
| `server_id` | string | 空 | 默认控制的服务器实例ID，留空则用 `mc选择` 动态指定 |
| `request_timeout` | int | `10` | 单次 API 请求超时时间（秒） |
| `max_retries` | int | `3` | API 请求失败后的自动重试次数 |
| `admin_qqs` | list | `[]` | 允许控制服务器的管理员QQ号，**留空=不限制**（同时作用于麦块与雨云） |
| `allowed_groups` | list | `[]` | 允许使用本插件的QQ群，**留空=不限制**（同时作用于麦块与雨云） |
| `rainyun_api_key` | string | 空 | 雨云 API 密钥（**启用雨云功能时必填**） |
| `rainyun_server_id` | string | 空 | 默认控制的雨云实例ID，留空则用 `ry选择` 动态指定 |
| `rainyun_product_type` | string | `rcs` | 雨云产品类型：`rcs`=云服务器，`rgs`=游戏云（Minecraft 推荐选 `rgs`） |

### 获取 API 节点地址与密钥

1. 登录 [麦块联机官网](https://minekuai.cn)。
2. 进入「**账户 → API**」页面（参考 [官方 API 文档](https://minekuai.cn/account/api)）。
3. 复制页面提供的 **API 节点地址**（即 `api_url`，不同账号可能分配到不同节点）与 **API 密钥**（即 `api_key`）。
4. 将两者填入插件配置并保存。

### 获取服务器实例ID

配置好密钥后，直接在 QQ 中向机器人发送：

```
mc列表
```

机器人会返回你账号下所有服务器及其 **实例ID（identifier）**。复制对应服务器的实例ID，发送：

```
mc选择 <实例ID>
```

此后所有控制指令都会作用于该服务器。你也可以把常用服务器的实例ID直接写入 `server_id` 配置项。

## 📝 使用示例

```
用户：mc状态
机器人：
📊 我的生存服（abc123）资源使用情况
📋 状态: 运行中
🔄 暂停: 否
🖥️ CPU: 12.34%
💾 内存: 2.15GB
💿 磁盘: 5.32GB
📡 网络接收: 128.50MB
📡 网络发送: 340.00MB
⏱️ 运行时间: 3天 5小时 12分钟 8秒
⏰ 查询时间: 2026-08-18 17:20:01

用户：mc命令 list
机器人：✅ 已向服务器 abc123 发送命令：
💬 /list

用户：mc开服
机器人：✅ 已向服务器 abc123 发送启动指令，请稍后用「mc状态」确认结果。
```

## ☁️ 雨云平台（云服务器 RCS / 游戏云 RGS）

本插件在麦块联机之外，额外接入了 [雨云 (RainYun)](https://www.rainyun.com) 开放 API，可远程控制你账号下的 **云服务器（RCS）** 与 **游戏云（RGS）** 实例。游戏云（RGS）预装了 MCSM 面板，非常适合托管 Minecraft 服务器。

> 麦块联机指令以 `mc` 开头，雨云指令以 `ry` 开头，两者共享同一套权限白名单（`admin_qqs` / `allowed_groups`）。

### 功能一览

| 功能 | 指令 | 说明 |
| --- | --- | --- |
| 启动实例 | `ry开服` / `ry启动` | 向雨云发送开机信号 |
| 停止实例 | `ry关服` / `ry停止` | 向雨云发送关机信号 |
| 重启实例 | `ry重启` | 重启实例 |
| 查看状态 | `ry状态` | 状态、公网 IP、系统、配置、实时 CPU |
| 实例列表 | `ry列表` | 列出账号下全部实例及其实例ID |
| 切换目标 | `ry选择 <实例ID>` | 切换当前控制的实例（持久保存） |
| 帮助 | `ry帮助` | 显示雨云相关指令 |

所有 `ry` 控制指令都支持在末尾追加实例ID，例如：

```
ry开服 114514
ry状态 114514
```

### 启用步骤

1. 登录 [雨云控制台](https://www.rainyun.com)，进入「**账户设置 → API 密钥**」创建并复制密钥。
2. 在插件配置中填写 `rainyun_api_key`（**必填**）。
3. 如需固定控制某台实例，可填写 `rainyun_server_id`；否则用 `ry列表` + `ry选择` 动态指定。
4. 根据你要控制的实例类型，将 `rainyun_product_type` 设为 `rcs`（云服务器）或 `rgs`（游戏云，Minecraft 推荐）。
5. 在 QQ 中发送 `ry列表` 查看账号下实例及其 ID，再 `ry选择 <实例ID>` 锁定目标。

```
用户：ry列表
机器人：
🗂️ 共 2 台雨云游戏云实例：
✅ [114514] mc-server | 状态: 运行中 | IP: 1.2.3.4
• [114515] test | 状态: 已停止

用户：ry重启
机器人：✅ 已向雨云实例 114514 发送重启指令，请稍后用「ry状态」确认结果。

用户：ry状态
机器人：
☁️ 雨云游戏云 · mc-server（114514）
📋 状态: 运行中
🌐 主IP: 1.2.3.4
💻 系统: Ubuntu 22.04
🧠 CPU配置: 2 核
🧠 内存配置: 4096 MB
📈 实时CPU占用: 5.10%
⏰ 查询时间: 2026-08-18 17:30:12
```

### 雨云 API 接口说明

| 操作 | 方法 | 路径（{type}=rcs/rgs） | 说明 |
| --- | --- | --- | --- |
| 实例列表 | GET | `/product/{type}/`（RCS 为 `/product/rcs?options=`） | 返回 `data.Records` |
| 实例详情 | GET | `/product/{type}/{id}/` | 返回 `data.Data` |
| 开机 | POST | `/product/{type}/{id}/start` | — |
| 关机 | POST | `/product/{type}/{id}/stop` | — |
| 重启 | POST | `/product/{type}/{id}/reboot` | — |

认证方式：请求头 `x-api-key: <rainyun_api_key>`。所有响应均为 `{code, data, message}` 结构，业务 `code` 非 0/200 视为失败（如密钥错误 `30039`、实例状态不允许该操作 `70026`、需二次验证 `30043`）。

## 🔌 API 接口说明

本插件调用的麦块联机 API（Pterodactyl 兼容）接口：

| 操作 | 方法 | 路径 | 请求体 |
| --- | --- | --- | --- |
| 电源控制 | POST | `/servers/{id}/power` | `{"signal": "start\|stop\|restart\|kill"}` |
| 资源/状态 | GET | `/servers/{id}/resources` | — |
| 服务器详情 | GET | `/servers/{id}` | — |
| 控制台命令 | POST | `/servers/{id}/command` | `{"command": "..."}` |
| 服务器列表 | GET | `/` | — |

认证方式：请求头 `Authorization: Bearer <api_key>`。

## ⚠️ 注意事项

- **密钥安全**：`api_key` 等同于你账户的控制权限，请勿泄露。配置面板中该字段建议设为私密。
- **强制重启**：仅在服务器卡死、普通重启无效时使用，会强制结束进程，可能导致未保存数据丢失。
- **权限控制**：若在 `admin_qqs` / `allowed_groups` 中填写了内容，则仅白名单内的用户/群可控制服务器；留空则对所有人开放。
- 网络异常时插件会自动重试 `max_retries` 次，仍失败会返回具体错误信息。

## 📄 开源协议

[MIT](./LICENSE)
