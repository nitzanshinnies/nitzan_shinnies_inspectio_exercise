"""Iteration 4 optional path: DynamoDB for hot SMS state + S3 append-only WAL.

This package is **parallel** to the default v3 SQS bulk → expander → send-worker pipeline.
Run ``inspectio-v3-iter4-api`` / ``inspectio-v3-iter4-worker`` when migrating to this model;
it does **not** replace L2 ``POST /messages`` until explicitly wired.
"""
