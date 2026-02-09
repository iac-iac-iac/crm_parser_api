CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    status TEXT CHECK(status IN ('running', 'completed', 'failed')),
    total_phones INTEGER DEFAULT 0,
    new_phones INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    client_id INTEGER NOT NULL,
    status INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS project_phones (
    project_id INTEGER NOT NULL,
    phone_id INTEGER NOT NULL,
    run_id INTEGER NOT NULL,
    created_at_api TIMESTAMP,
    PRIMARY KEY (project_id, phone_id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (phone_id) REFERENCES phones(id),
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
