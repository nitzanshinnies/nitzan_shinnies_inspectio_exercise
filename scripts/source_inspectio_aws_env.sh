#!/usr/bin/env bash
# Source for Inspectio AWS: predictable region and pager for scripts/CLI.
# Usage: source scripts/source_inspectio_aws_env.sh

export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_PAGER="${AWS_PAGER:-}"
