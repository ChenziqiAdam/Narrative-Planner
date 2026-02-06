.PHONY: help install test baseline interview clean

help:           ## 显示帮助信息
	@echo "可用命令："
	@echo "  make install     - 安装依赖"
	@echo "  make test        - 运行测试"
	@echo "  make baseline    - 运行 Baseline Agent"
	@echo "  make interview   - 运行实时访谈"
	@echo "  make clean       - 清理生成文件"

install:        ## 安装依赖
	pip install -r requirements.txt

test:           ## 运行测试
	python -m pytest tests/ -v

baseline:       ## 运行 Baseline Agent
	python scripts/run_baseline.py

interview:      ## 运行实时访谈
	python scripts/run_interview.py --agent baseline --session-id $(shell date +%Y%m%d_%H%M%S)

clean:          ## 清理生成文件
	rm -rf results/* __pycache__ src/__pycache__ src/**/__pycache__ .pytest_cache
