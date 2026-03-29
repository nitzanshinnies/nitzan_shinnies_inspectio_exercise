#!/usr/bin/env bash
set -euo pipefail
# LocalStack only: dummy credentials (real AWS CLI profile is not available inside this container).
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
# Inside the LocalStack container, the edge API is on localhost:4566.
endpoint="${LOCALSTACK_EDGE_URL:-http://localhost:4566}"
aws() { command aws --endpoint-url="${endpoint}" "$@"; }
# Default bucket name matches root compose / INSPECTIO_S3_BUCKET (inspectio-test-bucket).
bucket="${INSPECTIO_S3_BUCKET:-${S3_BUCKET:-inspectio-test-bucket}}"
queue_name="${INSPECTIO_INGEST_QUEUE_NAME:-inspectio-ingest.fifo}"
aws s3 mb "s3://${bucket}" 2>/dev/null || true
aws sqs create-queue \
  --queue-name "${queue_name}" \
  --attributes "FifoQueue=true,ContentBasedDeduplication=false" \
  2>/dev/null || true
v3_bulk_name="${INSPECTIO_V3_BULK_QUEUE_NAME:-inspectio-v3-bulk}"
aws sqs create-queue --queue-name "${v3_bulk_name}" 2>/dev/null || true
v3_send_name="${INSPECTIO_V3_SEND_QUEUE_NAME:-inspectio-v3-send-0}"
aws sqs create-queue --queue-name "${v3_send_name}" 2>/dev/null || true
echo "inspectio localstack init: bucket=${bucket} sqs_fifo_queue=${queue_name} v3_bulk_standard=${v3_bulk_name} v3_send_placeholder=${v3_send_name}"
