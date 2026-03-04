# solana-validator-monitor

**Solana Validator 集群监控系统 — 事件监听 & Slack Webhook 推送**  
**Solana Validator Cluster Monitor — Event Detection & Slack Webhook Alerts**

---

## 目录 / Table of Contents

- [项目介绍 / Introduction](#项目介绍--introduction)
- [架构图 / Architecture](#架构图--architecture)
- [事件类型 / Event Types](#事件类型--event-types)
- [快速开始 / Quick Start](#快速开始--quick-start)
- [配置说明 / Configuration](#配置说明--configuration)
- [部署指南 / Deployment](#部署指南--deployment)
- [开发与测试 / Development & Testing](#开发与测试--development--testing)

---

## 项目介绍 / Introduction

### 中文

本系统是一套完整的 Python 异步监控方案，专为 Solana 验证节点集群设计。它持续轮询 Solana JSON-RPC 接口，检测 6 种关键事件，并通过 Slack Incoming Webhook 推送格式化告警。

**主要特性：**
- 基于 `asyncio` + `aiohttp` 的高性能异步架构
- Pydantic v2 强类型事件模型
- Slack Block Kit 彩色消息格式（按严重程度区分颜色）
- 多 RPC 节点自动故障转移
- Webhook 指数退避重试 + 速率限制 + 消息去重
- Docker 一键部署，内置健康检查端点

### English

A complete Python async monitoring system for Solana validator clusters. It continuously polls the Solana JSON-RPC API, detects 6 critical event types, and pushes formatted alerts to a Slack Incoming Webhook.

**Key Features:**
- High-performance async architecture with `asyncio` + `aiohttp`
- Strongly typed event models with Pydantic v2
- Slack Block Kit colour-coded messages (per severity level)
- Multi-RPC-node automatic failover
- Webhook with exponential-backoff retry, rate limiting & message deduplication
- One-command Docker deployment with a built-in health-check endpoint

---

## 架构图 / Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    solana-validator-monitor                       │
│                                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────┐               │
│  │  Validator  │  │    Slot     │  │  Failover  │               │
│  │   Monitor   │  │   Monitor   │  │   Monitor  │               │
│  └──────┬──────┘  └──────┬──────┘  └─────┬──────┘               │
│         │                │               │                        │
│  ┌──────┴──────┐  ┌──────┴──────┐        │                       │
│  │   Version   │  │     RPC     │        │                       │
│  │   Monitor   │  │   Monitor   │        │                       │
│  └──────┬──────┘  └──────┬──────┘        │                       │
│         └────────────────┴───────────────┘                        │
│                          │                                        │
│               ┌──────────▼──────────┐                            │
│               │   Event Callback    │                            │
│               └──────────┬──────────┘                            │
│                          │                                        │
│               ┌──────────▼──────────┐                            │
│               │   Slack Webhook     │                            │
│               │  (retry + dedup)    │                            │
│               └──────────┬──────────┘                            │
└──────────────────────────┼──────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │    Slack    │
                    │  Workspace  │
                    └─────────────┘

           ┌─────────────────────────┐
           │  Solana RPC Cluster     │
           │  (multi-endpoint HA)    │
           └─────────────────────────┘
```

---

## 事件类型 / Event Types

| 事件 / Event | 描述 / Description | 严重程度 / Severity | 颜色 / Color |
|---|---|---|---|
| `validator.delinquent` | 验证节点掉线 / Validator went delinquent | 🔴 CRITICAL | `#FF0000` |
| `validator.recovered` | 验证节点恢复 / Validator recovered | 🟢 INFO | `#36A64F` |
| `validator.slot_missed` | Leader Slot 跳过 / Leader slot missed | 🟡 WARNING | `#FFA500` |
| `validator.failover` | 故障切换 / Failover triggered | 🔴 CRITICAL | `#FF0000` |
| `validator.version_change` | 软件版本变更 / Version changed | 🔵 INFO | `#36A64F` |
| `rpc.unhealthy` | RPC 节点不健康 / RPC node unhealthy | 🟠 WARNING | `#FFA500` |

---

## 快速开始 / Quick Start

### 前置要求 / Prerequisites

- Python 3.11+
- Docker & docker-compose（可选 / optional）

### 本地运行 / Local Run

```bash
# 1. 克隆仓库 / Clone the repo
git clone https://github.com/whyrulike/solana-validator-monitor.git
cd solana-validator-monitor

# 2. 安装依赖 / Install dependencies
pip install -r requirements.txt

# 3. 复制并编辑配置文件 / Copy and edit config
cp config.example.yaml config.yaml
# Edit config.yaml with your settings

# 4. 运行 / Run
python -m src.main
```

### Docker 运行 / Docker Run

```bash
cp config.example.yaml config.yaml
# Edit config.yaml

SLACK_WEBHOOK_URL=https://hooks.slack.com/... \
VALIDATOR_IDENTITIES=YourValidatorPubkey1,YourValidatorPubkey2 \
docker-compose up -d
```

---

## 配置说明 / Configuration

配置来源优先级（高→低）/ Configuration priority (high → low):
1. 环境变量 / Environment variables
2. `config.yaml` 文件
3. 内置默认值 / Built-in defaults

### 关键配置项 / Key Configuration Items

| 环境变量 / Env Var | YAML 路径 / YAML Path | 默认值 / Default | 说明 / Description |
|---|---|---|---|
| `SLACK_WEBHOOK_URL` | `slack.webhook_url` | — | Slack Incoming Webhook URL |
| `SOLANA_RPC_URLS` | `solana.rpc_urls` | mainnet-beta | 逗号分隔的 RPC 列表 / Comma-separated RPC list |
| `VALIDATOR_IDENTITIES` | `validator_identities` | — | 逗号分隔的 Pubkey 列表 |
| `MONITOR_INTERVAL_SECONDS` | `monitoring.interval_seconds` | `10` | 轮询间隔（秒）|
| `RPC_HEALTH_CHECK_INTERVAL` | `monitoring.rpc_health_check_interval` | `30` | RPC 健康检查间隔（秒）|
| `RPC_LATENCY_THRESHOLD_MS` | `monitoring.rpc_latency_threshold_ms` | `2000` | 延迟告警阈值（ms）|
| `SLOT_MISS_THRESHOLD` | `monitoring.slot_miss_threshold` | `5` | Slot 跳过告警阈值 |
| `VERSION_COMPONENT` | `version.component` | `jito-solana` | 软件组件名称 |

---

## 部署指南 / Deployment

### Docker Compose

```yaml
# .env file
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
VALIDATOR_IDENTITIES=Pubkey1,Pubkey2
SOLANA_RPC_URLS=https://api.mainnet-beta.solana.com,https://rpc2.example.com
```

```bash
docker-compose up -d
# 健康检查端点 / Health check endpoint: http://localhost:8080/health
```

### Kubernetes

```bash
kubectl create secret generic monitor-secrets \
  --from-literal=SLACK_WEBHOOK_URL=https://hooks.slack.com/...

kubectl apply -f k8s/deployment.yaml
```

---

## 开发与测试 / Development & Testing

```bash
# 安装依赖 / Install deps
pip install -r requirements.txt

# 运行全部测试 / Run all tests
python -m pytest tests/ -v

# 单独运行某类测试 / Run specific test file
python -m pytest tests/test_models.py -v
python -m pytest tests/test_monitors.py -v
python -m pytest tests/test_slack_webhook.py -v
python -m pytest tests/test_solana_client.py -v
```

### 项目结构 / Project Structure

```
solana-validator-monitor/
├── README.md
├── requirements.txt
├── config.example.yaml
├── Dockerfile
├── docker-compose.yml
├── src/
│   ├── main.py                    # asyncio 编排入口
│   ├── config.py                  # 配置加载
│   ├── solana_client.py           # 异步 JSON-RPC 客户端
│   ├── models/
│   │   └── events.py              # 6 种 Pydantic 事件模型
│   ├── monitors/
│   │   ├── validator_monitor.py   # delinquent/recovered
│   │   ├── slot_monitor.py        # 跳过 slot
│   │   ├── failover_monitor.py    # 故障切换
│   │   ├── version_monitor.py     # 版本变更
│   │   └── rpc_monitor.py         # RPC 健康检查
│   └── webhook/
│       └── slack.py               # Slack Webhook 推送
└── tests/
    ├── conftest.py
    ├── test_models.py
    ├── test_solana_client.py
    ├── test_monitors.py
    └── test_slack_webhook.py
```
