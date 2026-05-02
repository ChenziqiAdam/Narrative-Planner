.PHONY: help install dev test clean neo4j neo4j-down

help:           ## 显示帮助信息
	@echo "可用命令："
	@echo "  make install     - 安装后端依赖"
	@echo "  make dev         - 启动后端开发服务器"
	@echo "  make frontend    - 安装前端依赖并启动"
	@echo "  make test        - 运行测试"
	@echo "  make neo4j       - 启动 Neo4j"
	@echo "  make neo4j-down  - 停止 Neo4j"
	@echo "  make clean       - 清理生成文件"

install:        ## 安装后端依赖
	pip install -r requirements.txt

dev:            ## 启动后端开发服务器（需要先启动 Neo4j）
	python -m uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

frontend:       ## 安装前端依赖并启动
	cd frontend && pnpm install && pnpm dev

test:           ## 运行测试
	python -m pytest tests/ -v

neo4j:          ## 启动 Neo4j
	docker compose up -d

neo4j-down:     ## 停止 Neo4j
	docker compose down

clean:          ## 清理生成文件
	rm -rf results/* __pycache__ src/__pycache__ src/**/__pycache__ .pytest_cache
