# Database Migration Guide (Alembic + Asyncpg)

This document provides a step-by-step guide on configuring and using Alembic for database migrations in an asynchronous SQLAlchemy (`asyncpg`) environment.

---

## 🚀 Initial Environment Setup

Run these commands from your project root directory if you are configuring the migration pipeline for the first time:

```bash
# 1. Install Alembic and the async PostgreSQL driver
pip install alembic asyncpg

# 2. Verify that Alembic is available
alembic --version

# 3. Initialize the migration directory structure
alembic init alembic
```

---

## ⚙️ Required Configuration Updates

To support asynchronous operations and automatic model detection, you must update two specific files:

### 1. Update Connection String (`alembic.ini`)
Open `alembic.ini` in your root folder, locate the `sqlalchemy.url` configuration key, and update it to match your local asynchronous database URL:
```ini
sqlalchemy.url = postgresql+asyncpg://postgres:postgres@localhost:5432/prlens
```

### 2. Update Environment Logic (`alembic/env.py`)
Open `alembic/env.py`, delete its contents, and modify both the model registry imports and the asynchronous execution block to match the code snippet below:

```python
import asyncio
from logging.config import fileConfig
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# --- 1. IMPORT YOUR DATABASE MODELS HERE ---
# Point this to the location where your declarative Base is defined
from app.db.base import Base  

# This is the Alembic Config object
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- 2. LINK TARGET METADATA ---
# This allows Alembic to look at your Python files and auto-detect changes
target_metadata = Base.metadata

def do_run_migrations(connection):
    context.configure(
        connection=connection, 
        target_metadata=target_metadata,
        compare_type=True  # Helps detect changed column types
    )
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online():
    """Run migrations in 'online' mode using an AsyncEngine."""
    # Read database URL dynamically from your alembic.ini setting
    configuration = config.get_section(config.config_ini_section)
    url = configuration.get("sqlalchemy.url")
    
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    # --- 3. TRIGGER ASYNC ENGINE LOOP ---
    asyncio.run(run_migrations_online())
```

> ⚠️ **Important Developer Constraint:** For `--autogenerate` to detect your tables, ensure your application's actual structural model files (e.g., `user.py`, `finding.py`) are imported into your execution space so that SQLAlchemy's `Base.metadata` registry stays populated when Alembic scans the project.

---

## 🏃‍♂️ Everyday Migration Workflow

Whenever you add new columns, remove indices, or create entirely new database models, use the following execution lifecycle:

### Step 1: Create an Automated Version File
Compare your live database state directly against your updated SQLAlchemy models to output a version step file:
```bash
alembic revision --autogenerate -m "describe_your_schema_changes"
```
*Example:* `alembic revision --autogenerate -m "add_findings_table"`

### Step 2: Code Verification
Open the newly created migration sequence inside `alembic/versions/`. Double-check the generated `upgrade()` and `downgrade()` code definitions to confirm accuracy before hitting the database.

### Step 3: Execute Schema Upgrades
Push the script forward onto your running backend instance:
```bash
alembic upgrade head
```

---

## ⏪ Reverting Changes (Rollback)

If a schema migration causes errors, roll back exactly one step by running:
```bash
alembic downgrade -1
```