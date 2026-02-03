#!/bin/bash
set -e

cleanup() {
  echo "Error occurred. Cleaning up..."
  docker stop onyx_postgres onyx_elasticsearch onyx_kibana onyx_redis onyx_minio 2>/dev/null || true
  docker rm onyx_postgres onyx_elasticsearch onyx_kibana onyx_redis onyx_minio 2>/dev/null || true
}

# Trap errors and output a message, then cleanup
trap 'echo "Error occurred on line $LINENO. Exiting script." >&2; cleanup' ERR

# Usage of the script with optional volume arguments
# ./restart_containers_eleven.sh [elasticsearch_volume] [postgres_volume] [redis_volume] [minio_volume]

ELASTICSEARCH_VOLUME=${1:-""}  # Default is empty if not provided
POSTGRES_VOLUME=${2:-""}  # Default is empty if not provided
REDIS_VOLUME=${3:-""}  # Default is empty if not provided
MINIO_VOLUME=${4:-""}  # Default is empty if not provided

# Stop and remove the existing containers
echo "Stopping and removing existing containers..."
docker stop onyx_postgres onyx_elasticsearch onyx_kibana onyx_redis onyx_minio 2>/dev/null || true
docker rm onyx_postgres onyx_elasticsearch onyx_kibana onyx_redis onyx_minio 2>/dev/null || true

# Start the PostgreSQL container with optional volume
echo "Starting PostgreSQL container..."
if [[ -n "$POSTGRES_VOLUME" ]]; then
    docker run -p 5432:5432 --name onyx_postgres -e POSTGRES_PASSWORD=password -d -v $POSTGRES_VOLUME:/var/lib/postgresql/data postgres -c max_connections=250
else
    docker run -p 5432:5432 --name onyx_postgres -e POSTGRES_PASSWORD=password -d postgres -c max_connections=250
fi

# Start the Elasticsearch container with optional volume
echo "Starting Elasticsearch container..."
if [[ -n "$ELASTICSEARCH_VOLUME" ]]; then
    docker run --detach \
        --name onyx_elasticsearch \
        --publish 9200:9200 \
        --publish 9300:9300 \
        -e discovery.type=single-node \
        -e xpack.security.enabled=false \
        -e "ES_JAVA_OPTS=-Xms512m -Xmx512m" \
        -e bootstrap.memory_lock=true \
        --ulimit memlock=-1:-1 \
        --ulimit nofile=65536:65536 \
        -v $ELASTICSEARCH_VOLUME:/usr/share/elasticsearch/data \
        docker.elastic.co/elasticsearch/elasticsearch:8.17.2
else
    docker run --detach \
        --name onyx_elasticsearch \
        --publish 9200:9200 \
        --publish 9300:9300 \
        -e discovery.type=single-node \
        -e xpack.security.enabled=false \
        -e "ES_JAVA_OPTS=-Xms512m -Xmx512m" \
        -e bootstrap.memory_lock=true \
        --ulimit memlock=-1:-1 \
        --ulimit nofile=65536:65536 \
        docker.elastic.co/elasticsearch/elasticsearch:8.17.2
fi

# Start the Kibana container
echo "Starting Kibana container..."
docker run --detach \
    --name onyx_kibana \
    --publish 5601:5601 \
    --link onyx_elasticsearch:elasticsearch \
    -e ELASTICSEARCH_HOSTS=http://elasticsearch:9200 \
    -e SERVERNAME=kibana \
    -e SERVER_HOST=0.0.0.0 \
    -e XPACK_SECURITY_ENABLED=false \
    docker.elastic.co/kibana/kibana:8.17.2

# Start the Redis container with optional volume
echo "Starting Redis container..."
if [[ -n "$REDIS_VOLUME" ]]; then
    docker run --detach --name onyx_redis --publish 6379:6379 -v $REDIS_VOLUME:/data redis
else
    docker run --detach --name onyx_redis --publish 6379:6379 redis
fi

# Start the MinIO container with optional volume
echo "Starting MinIO container..."
if [[ -n "$MINIO_VOLUME" ]]; then
    docker run --detach --name onyx_minio --publish 9004:9000 --publish 9005:9001 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin -v $MINIO_VOLUME:/data minio/minio server /data --console-address ":9001"
else
    docker run --detach --name onyx_minio --publish 9004:9000 --publish 9005:9001 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin minio/minio server /data --console-address ":9001"
fi

# Ensure alembic runs in the correct directory (backend/)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PARENT_DIR"

# Give Postgres a second to start
sleep 1

# Alembic should be configured in the virtualenv for this repo
if [[ -f "../.venv/bin/activate" ]]; then
    source ../.venv/bin/activate
else
    echo "Warning: Python virtual environment not found at .venv/bin/activate; alembic may not work."
fi

# Run Alembic upgrade
echo "Running Alembic migration..."
alembic upgrade head

# Run the following instead of the above if using MT cloud
# alembic -n schema_private upgrade head

echo "Containers restarted and migration completed."
