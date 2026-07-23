# cdo-mcp-server

MCP server exposing a canonical data model (customers, jobs, tasks,
invoices) as tools for Claude — backed by Postgres.

## Local dev setup

1. Start Postgres (creates both the `cdo` dev database and a `cdo_test`
   database, same schema in each — see `schema.sql`):

   ```bash
   docker compose up -d
   ```

2. Install the package (editable) and its dependencies:

   ```bash
   pip install -e .
   ```

3. Seed the dev database with the sample data checked into `data/db.json`
   (Tan Brothers Pte Ltd, an Office Rewire job, etc.):

   ```bash
   DATABASE_URL=postgresql://cdo:cdo@localhost:5432/cdo \
       python scripts/migrate_json_to_postgres.py
   ```

4. Run the server directly, or via the installed console script:

   ```bash
   DATABASE_URL=postgresql://cdo:cdo@localhost:5432/cdo cdo-mcp-server
   ```

## Running tests

Tests need Postgres running (step 1 above) — they isolate against a
separate, disposable `cdo_test` database, truncated before every test, so
they never touch the dev data. See `tests/test_server.py`'s `isolated_db`
fixture for details.

```bash
pytest tests/
```

## Claude Desktop integration

Point `claude_desktop_config.json`'s `cdo-data-server` entry at the
installed `cdo-mcp-server` console script, with `DATABASE_URL` set in its
`env` block (see the MCP docs for the config file's exact schema/location
on your OS).
