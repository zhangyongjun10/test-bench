# TestBench - Agent 验证平台

基于 FastAPI + React + Ant Design 的 Agent 验证测试平台。

## 项目结构

```
.
├── backend/          # Python FastAPI 后端
├── frontend/         # React TypeScript 前端
├── docker-compose.yml
└── README.md
```

## 本地开发启动

### 启动后端

```bash
cd backend
# 安装依赖（首次运行）
pip install -r requirements.txt

# 启动开发服务器
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

后端地址: http://localhost:8000

### 启动前端（新开终端）

```bash
cd frontend
# 安装依赖（首次运行）
npm install

# 启动开发服务器
npm run dev
```

前端地址: http://localhost:5173

## 环境变量

复制 `backend/.env.example` 到 `backend/.env` 并修改配置：

```bash
cp backend/.env.example backend/.env
# 编辑 .env 文件填写数据库等信息
```

## 数据库迁移

```bash
cd backend
alembic upgrade head
```

## 停止所有进程

如果需要停止所有前后端进程：

```bash
# Windows
powershell "Get-Process | Where-Object {$_.ProcessName -like '*node*' -or $_.ProcessName -like '*python*'} | Stop-Process -Force"
```

## Docker 启动

```bash
docker-compose up -d
```

前端: http://localhost:80
后端: http://localhost:8000
