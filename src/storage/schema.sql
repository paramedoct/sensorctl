PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

INSERT INTO schema_version (version)
SELECT 1
WHERE NOT EXISTS (SELECT 1 FROM schema_version);

CREATE TABLE IF NOT EXISTS sensor_instance (
    id INTEGER PRIMARY KEY,
    logical_id TEXT NOT NULL,
    driver TEXT NOT NULL,
    bus_id TEXT NOT NULL,
    location TEXT NOT NULL,
    config_fingerprint TEXT NOT NULL,
    created_at_ns INTEGER NOT NULL,
    UNIQUE (logical_id, config_fingerprint)
);

CREATE TABLE IF NOT EXISTS field (
    id INTEGER PRIMARY KEY,
    sensor_instance_id INTEGER NOT NULL REFERENCES sensor_instance(id),
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    UNIQUE (sensor_instance_id, name)
);

CREATE TABLE IF NOT EXISTS sample (
    id INTEGER PRIMARY KEY,
    sensor_instance_id INTEGER NOT NULL REFERENCES sensor_instance(id),
    wall_time_ns INTEGER NOT NULL,
    monotonic_ns INTEGER NOT NULL,
    boot_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS sample_sensor_time_idx
ON sample (sensor_instance_id, wall_time_ns);

CREATE TABLE IF NOT EXISTS measurement (
    sample_id INTEGER NOT NULL REFERENCES sample(id) ON DELETE CASCADE,
    field_id INTEGER NOT NULL REFERENCES field(id),
    value REAL NOT NULL,
    PRIMARY KEY (sample_id, field_id)
);
