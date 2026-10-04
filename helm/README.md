# Shared application chart

One Deployment and Service per Helm release. Names and selectors derive from the release name; there are no database resources or subchart dependencies. Application values and release names are supplied by the consumer.

Values: `image`, `replicas`, `port`, `healthPath`, `env`, `resources`, and optional `writableDirectory`. The latter copies an image directory into writable runtime storage while preserving the image startup command. Containers run as UID 1000 with restricted security settings and a read-only root filesystem. Images must support that contract.

PostgreSQL is independently provisioned by the platform bootstrap using a pinned upstream chart; it is never part of application upgrade/rollback. See the package README for versioned consumption and release instructions.
