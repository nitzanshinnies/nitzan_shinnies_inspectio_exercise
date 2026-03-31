# P12.7 Throughput Comparison Report

Status: pending in-cluster benchmark execution.

This report is generated/updated by:

```bash
python scripts/v3_persistence_throughput_report.py \
  --persist-off-json <persist-off.json> \
  --persist-on-json <persist-on.json> \
  --persist-off-delete-rps <value> \
  --persist-on-delete-rps <value> \
  --persist-off-writer-lag-ms <value> \
  --persist-on-writer-lag-ms <value> \
  --persist-off-error-rate <value> \
  --persist-on-error-rate <value>
```

Gate definitions:

- hard gate: persistence-on throughput >= 70% of persistence-off baseline
- target gate: persistence-on throughput >= 85% of persistence-off baseline

Use in-cluster benchmark Job outputs and CloudWatch queue delete metrics only.
