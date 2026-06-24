.PHONY: setup start stop logs demo test clean

setup:
	@test -f .env || cp .env.template .env
	@echo "请编辑 .env（默认 USE_MOCK=true 可直接运行），然后执行 make start"

start:
	docker compose up --build -d
	@echo "等待服务健康检查..."
	@sleep 15
	@docker compose ps

stop:
	docker compose down

logs:
	docker compose logs -f --tail=100

demo:
	USE_MOCK=true docker compose up --build -d
	@echo "Demo 模式已启动，15 秒后可用..."
	@sleep 15
	@docker compose ps

test:
	@echo "正在调用 briefing 接口..."
	@curl -X POST http://localhost:3000/briefing \
		-H "Content-Type: application/json" \
		-d '{"query": "给我生成一份关于 Pilbara 锂矿的今日简报"}'

clean:
	docker compose down -v
	docker system prune -f
