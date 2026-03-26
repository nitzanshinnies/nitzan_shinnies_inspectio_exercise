#!/usr/bin/env bash
set -euo pipefail
export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
# Inside the LocalStack container, the edge API is on localhost:4566.
endpoint="${LOCALSTACK_EDGE_URL:-http://localhost:4566}"
aws() { command aws --endpoint-url="${endpoint}" "$@"; }
bucket="${INSPECTIO_S3_BUCKET:-inspectio-dev}"
stream="${INSPECTIO_KINESIS_STREAM_NAME:-inspectio-ingest}"
shards="${INSPECTIO_KINESIS_LOCAL_SHARDS:-1}"
aws s3 mb "s3://${bucket}" 2>/dev/null || true
aws kinesis create-stream --stream-name "${stream}" --shard-count "${shards}" 2>/dev/null || true
echo "inspectio localstack init: bucket=${bucket} stream=${stream} shards=${shards}"
