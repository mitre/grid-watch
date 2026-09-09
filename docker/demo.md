0. make sure docker desktop is running
1. spin up containers with docker compose
2. spin up hmi (python run.py)
3. check outstation ip address in docker container info
4. change gridwatch facts to use outstation ip address, select only 1 control func(direct operate), select only 1 control type (OFF)
5. demo caldera

## commands

spin up the stack (with the capture sidecar):
```bash
docker compose -f docker/docker-compose.yml --profile capture up --build -d
```

tear down the stack:
```bash
docker compose -f docker/docker-compose.yml down
```

